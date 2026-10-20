from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api, periodic, accounting, reports
from hospitality_suite.service import operation
from hospitality_suite.pricing import decimal


class TestPeriodic(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H101'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.start=now_datetime().replace(microsecond=0)
        self.gl_before=frappe.db.count('GL Entry')
        with operation():
            self.prop.lodging_charge_policy='Nightly'
            self.prop.business_date=self.start.date()
            self.prop.save()

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def call(self,action,data=None,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data or {})

    def enter(self,nights=3):
        data=dict(starts_at=str(self.start),ends_at=str(self.start+timedelta(days=nights)),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        data['acceptance']=api.preview(self.prop.name,data)['acceptance']
        return self.call('walk_in',data)

    def rows(self,stay):
        return frappe.get_all('HS Charge',filters={'stay':stay},fields=['*'],order_by='service_date asc,name asc')

    def day(self,offset):
        with operation():
            self.prop.business_date=self.start.date()+timedelta(days=offset)
            self.prop.save()

    def test_nights_keep_accepted_prices_and_unique_origins_across_fresh_requests(self):
        entered=self.enter()
        rows=self.rows(entered['stay'])
        self.assertEqual(len(rows),3)
        self.assertEqual({r.status for r in rows},{'Scheduled'})
        self.assertEqual(len({r.period_key for r in rows}),3)
        self.assertEqual(sum(decimal(r.amount) for r in rows),4500)
        balance=accounting.folio_balance(entered['folio'])
        self.assertEqual((balance['pending'],balance['scheduled'],balance['outstanding']),('0.00','4500.00','4500.00'))
        rate=frappe.get_doc('HS Rate',{'property':self.prop.name})
        with operation():rate.amount=9999;rate.save()
        first=self.call('generate_lodging')
        self.assertEqual(first['generated'],1)
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        self.day(1)
        self.assertEqual(self.call('generate_lodging')['generated'],1)
        self.assertEqual([r.amount for r in self.rows(entered['stay'])],[1500,1500,1500])
        self.assertEqual(frappe.db.count('HS Audit Event',{'action':'Generate nightly charges','property':self.prop.name}),2)
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual(frappe.db.count('GL Entry'),self.gl_before)
        self.assertTrue(any(row.Column_name=='period_key' and row.Non_unique==0 for row in frappe.db.sql('SHOW INDEX FROM `tabHS Charge`',as_dict=True)))

    def test_prior_nights_catch_up_once_but_future_nights_stay_scheduled(self):
        entered=self.enter(4)
        self.day(2)
        self.assertEqual(self.call('generate_lodging')['generated'],3)
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        rows=self.rows(entered['stay'])
        self.assertEqual([r.status for r in rows],['Pending','Pending','Pending','Scheduled'])
        self.assertEqual([str(r.business_date) for r in rows],[str(self.start.date()+timedelta(days=i)) for i in range(4)])

    def test_nightly_close_reviews_repeat_without_recreating_charges(self):
        entered=self.enter()
        first=self.call('daily_close',dict(confirm=False))
        second=self.call('daily_close',dict(confirm=False))
        self.assertEqual(first['close'],second['close'])
        self.assertEqual(first['review_acceptance'],second['review_acceptance'])
        self.assertEqual(len(self.rows(entered['stay'])),3)
        self.assertEqual(frappe.db.count('HS Charge',{'stay':entered['stay'],'status':'Pending'}),1)
        self.assertEqual(frappe.db.count('HS Charge',{'stay':entered['stay'],'status':'Scheduled'}),2)
        currency=next(row for row in second['period']['financial']['currencies'] if row['currency']=='NIO')
        self.assertEqual(currency['pending_charges'],'1500.00')
        self.assertEqual(currency['scheduled_charges'],'3000.00')
        self.assertTrue(any(row['type']=='Cargos sin facturar' for row in second['blockers']))

    def test_early_invoice_settles_all_accepted_nights_once_and_can_be_reversed(self):
        entered=self.enter()
        result=self.call('invoice',dict(folio=entered['folio']))
        invoice=frappe.get_doc('Sales Invoice',result['invoice'])
        self.assertEqual(invoice.grand_total,4500)
        self.assertEqual(len(invoice.items),3)
        origins={r.period_key for r in self.rows(entered['stay'])}
        self.assertEqual({r.status for r in self.rows(entered['stay'])},{'Invoiced'})
        self.day(3)
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        self.assertNotIn('invoice',self.call('invoice',dict(folio=entered['folio'])))
        with operation():
            invoice.hs_correction_reason='Reversión sintética de prueba'
            invoice.cancel()
        self.assertEqual({r.status for r in self.rows(entered['stay'])},{'Pending'})
        self.assertEqual({r.period_key for r in self.rows(entered['stay'])},origins)
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        self.assertEqual(accounting.folio_balance(entered['folio'])['outstanding'],'4500.00')

    def test_extension_keeps_the_stay_policy_and_each_new_night(self):
        entered=self.enter(2)
        stay=frappe.get_doc('HS Stay',entered['stay'])
        with operation():self.prop.lodging_charge_policy='Arrival';self.prop.save()
        data=dict(stay=stay.name,folio=entered['folio'],ends_at=str(self.start+timedelta(days=4)),modified=str(stay.modified))
        data['acceptance']=api.preview(self.prop.name,data,action='extend')['acceptance']
        self.call('extend',data)
        self.assertEqual(len(self.rows(stay.name)),4)
        self.assertEqual({r.status for r in self.rows(stay.name)},{'Scheduled'})
        self.assertEqual(sum(decimal(r.amount) for r in self.rows(stay.name)),6000)
        with self.assertRaises(frappe.TimestampMismatchError):self.call('extend',data)
        self.assertEqual(len(self.rows(stay.name)),4)

    def test_partial_generator_failure_rolls_back_the_entire_batch_and_retry_succeeds(self):
        entered=self.enter()
        self.day(2)
        original=periodic.locked_doc
        count=0
        def fail_second(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('synthetic interrupted nightly batch')
            return original(*args,**kwargs)
        with patch('hospitality_suite.periodic.locked_doc',side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.call('generate_lodging',key='retry-after-interruption')
        self.assertEqual({r.status for r in self.rows(entered['stay'])},{'Scheduled'})
        self.assertEqual(self.call('generate_lodging',key='retry-after-interruption')['generated'],3)
        self.assertEqual(len(self.rows(entered['stay'])),3)

    def test_scheduled_sources_and_adjustments_move_together_to_a_group_folio(self):
        entered=self.enter()
        first=self.rows(entered['stay'])[0]
        # A negative manual room-change adjustment inherits its scheduled period.
        from hospitality_suite.operations import charge
        stay=frappe.get_doc('HS Stay',entered['stay'])
        folio=frappe.get_doc('HS Folio',entered['folio'])
        with operation():credit=charge(self.prop,stay,folio,first.item,-100,'Lodging','Ajuste sintético',applies_to=first.name)
        self.assertEqual(credit.status,'Scheduled')
        self.assertEqual(credit.service_date,first.service_date)
        destination=self.call('create_folio',dict(stay=stay.name,customer=self.guest.customer,label='Empresa',group=1))['folio']
        self.call('move_charge',dict(charge=first.name,folio=destination,reason='Reparto sintético'))
        self.assertEqual(frappe.db.get_value('HS Charge',credit.name,'folio'),destination)
        result=self.call('invoice',dict(folio=destination))
        invoice=frappe.get_doc('Sales Invoice',result['invoice'])
        self.assertEqual(invoice.grand_total,1400)
        self.assertEqual(len(invoice.items),1)
        self.assertEqual(self.call('generate_lodging')['generated'],0)

    def test_reception_and_auditor_cannot_generate_financial_charges(self):
        entered=self.enter()
        for user in ('receptionist@hospitality.example.invalid','auditor@hospitality.example.invalid'):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):self.call('generate_lodging')
        frappe.set_user('Administrator')
        self.assertEqual({r.status for r in self.rows(entered['stay'])},{'Scheduled'})

    def test_unequal_accepted_nights_are_not_averaged_or_counted_as_current_production(self):
        original=frappe.get_doc('HS Rate',{'property':self.prop.name})
        special=frappe.copy_doc(original)
        special.title='Noche especial sintética'
        special.amount=2000
        special.priority=20
        special.valid_from=special.valid_to=self.start.date()+timedelta(days=1)
        with operation():special.insert()
        entered=self.enter()
        self.assertEqual([row.amount for row in self.rows(entered['stay'])],[1500,2000,1500])
        self.assertEqual(accounting.folio_balance(entered['folio'])['outstanding'],'5000.00')
        self.assertEqual(reports.summary(self.prop)['production'],'0.00')
        with operation():special.amount=9000;special.save()
        self.day(1)
        self.assertEqual(self.call('generate_lodging')['generated'],2)
        self.assertEqual([row.amount for row in self.rows(entered['stay'])],[1500,2000,1500])

    def test_motel_keeps_its_block_charge_with_nightly_property_setting(self):
        self.prop=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'M101'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        with operation():self.prop.lodging_charge_policy='Nightly';self.prop.save()
        data=dict(starts_at=str(self.start),ends_at=str(self.start+timedelta(hours=3)),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        data['acceptance']=api.preview(self.prop.name,data)['acceptance']
        entered=self.call('walk_in',data)
        self.assertEqual(frappe.db.get_value('HS Stay',entered['stay'],'lodging_charge_policy'),'Arrival')
        self.assertEqual(len(self.rows(entered['stay'])),1)
        self.assertEqual(self.rows(entered['stay'])[0].status,'Pending')
        self.assertFalse(self.rows(entered['stay'])[0].period_key)
        self.assertEqual(self.call('generate_lodging')['generated'],0)

    def test_close_confirm_retry_and_reopening_keep_one_set_of_nights_and_native_documents(self):
        entered=self.enter()
        self.call('daily_close',dict(confirm=False))
        shift=self.call('open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1})
        self.call('payment',dict(stay=entered['stay'],folio=entered['folio'],shift=shift,method=method,kind='Payment',amount=4500))
        shift_doc=frappe.get_doc('HS Shift',shift)
        self.call('close_shift',dict(shift=shift,modified=str(shift_doc.modified),denominations={'NIO':[dict(value=1,count=4500)]}))
        review=self.call('daily_close',dict(confirm=False))
        self.assertEqual(review['blockers'],[])
        data=dict(confirm=True,review_acceptance=review['review_acceptance'])
        key=uuid.uuid4().hex
        first=self.call('daily_close',data,key)
        self.assertEqual(first,self.call('daily_close',data,key))
        self.assertEqual(str(frappe.db.get_value('HS Property',self.prop.name,'business_date')),str(self.start.date()+timedelta(days=1)))
        with self.assertRaises(frappe.ValidationError):self.call('daily_close',data)
        self.assertEqual(frappe.db.count('HS Daily Close',{'property':self.prop.name}),1)
        self.call('reopen_day',dict(close=first['close'],reason='Revisión sintética'))
        reopened=self.call('daily_close',dict(confirm=False))
        self.call('daily_close',dict(confirm=True,review_acceptance=reopened['review_acceptance']))
        self.assertEqual(len(self.rows(entered['stay'])),3)
        self.assertEqual(frappe.db.count('Sales Invoice'),1)
        self.assertEqual(frappe.db.count('Payment Entry'),1)
        self.assertEqual(frappe.db.count('HS Payment'),1)

    def test_failed_invoice_restores_future_nights_before_native_retry(self):
        entered=self.enter()
        with patch('hospitality_suite.accounting.post_standard',side_effect=RuntimeError('synthetic invoice failure')):
            with self.assertRaises(RuntimeError):self.call('invoice',dict(folio=entered['folio']))
        self.assertEqual({r.status for r in self.rows(entered['stay'])},{'Scheduled'})
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual(accounting.folio_balance(entered['folio'])['outstanding'],'4500.00')
        self.assertTrue(self.call('invoice',dict(folio=entered['folio']))['invoice'])

    def draft_native_invoice(self,entered,origins=True):
        return frappe.get_doc(dict(doctype='Sales Invoice',company=self.prop.company,customer=self.guest.customer,currency=self.prop.currency,
                    debit_to=self.prop.receivable_account,cost_center=self.prop.cost_center,hs_property=self.prop.name,
                    hs_stay=entered['stay'],hs_folio=entered['folio'],update_stock=0,
                    items=[dict(item_code=row.item,qty=row.quantity,rate=row.rate,cost_center=self.prop.cost_center,
                                hs_charge=row.name if origins else None) for row in self.rows(entered['stay'])]))

    def test_native_invoice_can_post_explicit_scheduled_sources_without_new_charges(self):
        entered=self.enter()
        keys={row.period_key for row in self.rows(entered['stay'])}
        invoice=self.draft_native_invoice(entered)
        invoice.insert().submit()
        self.assertEqual(invoice.grand_total,4500)
        self.assertEqual({row.period_key for row in self.rows(entered['stay'])},keys)
        self.assertEqual({row.status for row in self.rows(entered['stay'])},{'Invoiced'})
        self.assertTrue(all(row.posted_at for row in self.rows(entered['stay'])))
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        self.assertEqual(frappe.db.count('Sales Invoice'),1)

    def test_native_invoice_must_reference_scheduled_sources_to_avoid_double_billing(self):
        entered=self.enter()
        invoice=self.draft_native_invoice(entered,origins=False)
        with self.assertRaises(frappe.ValidationError):invoice.insert()
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual(len(self.rows(entered['stay'])),3)
        self.assertEqual({row.status for row in self.rows(entered['stay'])},{'Scheduled'})

    def test_zero_price_extension_still_preserves_its_accepted_night_and_origin(self):
        entered=self.enter(1)
        rate=frappe.get_doc('HS Rate',{'property':self.prop.name})
        with operation():rate.amount=0;rate.save()
        stay=frappe.get_doc('HS Stay',entered['stay'])
        data=dict(stay=stay.name,folio=entered['folio'],ends_at=str(self.start+timedelta(days=2)),modified=str(stay.modified))
        data['acceptance']=api.preview(self.prop.name,data,action='extend')['acceptance']
        self.call('extend',data)
        rows=self.rows(stay.name)
        self.assertEqual([row.amount for row in rows],[1500,0])
        self.assertEqual(len({row.period_key for row in rows}),2)
        self.day(1)
        self.assertEqual(self.call('generate_lodging')['generated'],2)
        self.assertEqual(self.call('generate_lodging')['generated'],0)
        invoice=self.call('invoice',dict(folio=entered['folio']))
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice['invoice'],'grand_total'),1500)
        self.assertEqual(frappe.db.count('Sales Invoice Item',{'parent':invoice['invoice']}),2)
