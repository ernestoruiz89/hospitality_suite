from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation,canonical


class TestInvoicePage(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H101'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        with operation():self.prop.lodging_charge_policy='Nightly';self.prop.save()

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def command(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def enter(self,free=False):
        if free:
            rate=frappe.get_doc('HS Rate',{'property':self.prop.name})
            with operation():rate.amount=0;rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        start=now_datetime().replace(microsecond=0)
        data=dict(starts_at=str(start),ends_at=str(start+timedelta(days=2)),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        data['acceptance']=api.preview(self.prop.name,data)['acceptance']
        return self.command('walk_in',data)

    def quote(self,folio):
        return api.preview(self.prop.name,dict(folio=folio),action='invoice')

    def emit(self,quote,key=None):
        return self.command('invoice',dict(folio=quote['folio'],invoice_acceptance=quote['acceptance']),key)

    def charges(self,stay):
        return frappe.get_all('HS Charge',filters={'stay':stay},fields=['*'],order_by='name asc')

    def test_preview_is_read_only_and_reproducible_before_any_posting(self):
        entered=self.enter()
        watched=('HS Charge','HS Request','Sales Invoice','Sales Invoice Item','Payment Entry','Journal Entry','GL Entry','Item Price','Version')
        counts={dt:frappe.db.count(dt) for dt in watched}
        before=canonical(self.charges(entered['stay']))
        first=self.quote(entered['folio'])
        second=self.quote(entered['folio'])
        self.assertTrue(first['ready'])
        self.assertEqual(first['acceptance'],second['acceptance'])
        self.assertEqual((first['total'],first['scheduled'],first['outstanding']),('3000.00','3000.00','3000.00'))
        self.assertEqual({dt:frappe.db.count(dt) for dt in watched},counts)
        self.assertEqual(canonical(self.charges(entered['stay'])),before)

    def test_emission_without_cash_or_departure_preserves_the_stay_and_retries(self):
        entered=self.enter()
        quote=self.quote(entered['folio'])
        key=uuid.uuid4().hex
        result=self.emit(quote,key)
        self.assertEqual(result,self.emit(quote,key))
        invoice=frappe.get_doc('Sales Invoice',result['invoice'])
        self.assertEqual(invoice.docstatus,1)
        self.assertEqual(invoice.grand_total,3000)
        self.assertEqual(invoice.outstanding_amount,3000)
        self.assertEqual(frappe.db.get_value('HS Stay',entered['stay'],'status'),'Active')
        self.assertEqual(frappe.db.count('HS Cleaning Task'),0)
        self.assertEqual(frappe.db.count('HS Shift'),0)
        self.assertEqual(frappe.db.count('HS Payment'),0)
        self.assertEqual(frappe.db.count('Payment Entry'),0)
        self.assertEqual(frappe.db.count('Sales Invoice'),1)
        self.assertFalse(self.quote(entered['folio'])['ready'])
        with self.assertRaises(frappe.ValidationError):self.emit(quote)
        self.assertEqual(frappe.db.count('Sales Invoice'),1)

    def test_zero_invoice_is_ready_and_posts_without_a_fake_payment(self):
        entered=self.enter(free=True)
        quote=self.quote(entered['folio'])
        self.assertTrue(quote['ready'])
        self.assertEqual(quote['total'],'0.00')
        result=self.emit(quote)
        invoice=frappe.get_doc('Sales Invoice',result['invoice'])
        self.assertEqual(invoice.docstatus,1)
        self.assertEqual(invoice.grand_total,0)
        self.assertEqual(len(invoice.items),2)
        self.assertEqual(frappe.db.count('Payment Entry'),0)
        self.assertEqual(frappe.db.count('HS Payment'),0)
        self.assertEqual(frappe.db.get_value('HS Stay',entered['stay'],'status'),'Active')

    def test_changed_charge_requires_a_new_review_before_settling_scheduled_nights(self):
        entered=self.enter()
        quote=self.quote(entered['folio'])
        source=self.charges(entered['stay'])[0]
        self.command('adjustment',dict(charge=source.name,adjustment_type='Discount',amount=100,reason='Descuento sintético autorizado'))
        before=canonical(self.charges(entered['stay']))
        with self.assertRaises(frappe.ValidationError):self.emit(quote)
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual(canonical(self.charges(entered['stay'])),before)
        current=self.quote(entered['folio'])
        self.assertEqual(current['total'],'2900.00')
        invoice=self.emit(current)['invoice']
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'grand_total'),2900)

    def test_review_includes_existing_advance_and_uses_it_without_another_receipt(self):
        entered=self.enter()
        shift=self.command('open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1})
        self.command('payment',dict(stay=entered['stay'],shift=shift,method=method,kind='Advance',amount=500))
        quote=self.quote(entered['folio'])
        self.assertEqual((quote['advance'],quote['outstanding']),('500.00','2500.00'))
        invoice=frappe.get_doc('Sales Invoice',self.emit(quote)['invoice'])
        self.assertEqual(invoice.total_advance,500)
        self.assertEqual(invoice.outstanding_amount,2500)
        self.assertEqual(frappe.db.count('HS Payment'),1)
        self.assertEqual(frappe.db.count('Payment Entry'),1)
        self.assertEqual(frappe.db.get_value('HS Shift',shift,'status'),'Open')

    def test_preview_rejects_reception_role_and_another_property_context(self):
        entered=self.enter()
        frappe.set_user('receptionist@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.quote(entered['folio'])
        frappe.set_user('Administrator')
        motel=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        with self.assertRaises(frappe.PermissionError):api.preview(motel.name,dict(folio=entered['folio']),action='invoice')
        self.assertEqual(frappe.db.count('Sales Invoice'),0)

    def tax_template(self,included):
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'root_type':'Liability','is_group':1})
        account=frappe.get_doc(dict(doctype='Account',company=self.prop.company,account_name='Impuesto revisión sintética '+uuid.uuid4().hex[:6],
                                   parent_account=parent,account_type='Tax',account_currency='NIO')).insert()
        template=frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',title='Impuesto revisión '+uuid.uuid4().hex[:6],company=self.prop.company,
                      taxes=[dict(charge_type='On Net Total',account_head=account.name,description='Impuesto sintético',rate=15,included_in_print_rate=int(included),cost_center=self.prop.cost_center)])).insert()
        with operation():self.prop.tax_template=template.name;self.prop.save()
        return template

    def test_included_tax_review_matches_the_native_posted_invoice(self):
        self.tax_template(True)
        entered=self.enter()
        quote=self.quote(entered['folio'])
        self.assertEqual((quote['net_total'],quote['taxes'],quote['total']),('2608.70','391.30','3000.00'))
        invoice=frappe.get_doc('Sales Invoice',self.emit(quote)['invoice'])
        self.assertAlmostEqual(invoice.net_total,2608.70,places=2)
        self.assertAlmostEqual(invoice.total_taxes_and_charges,391.30,places=2)
        self.assertEqual(invoice.grand_total,3000)

    def test_changed_tax_template_requires_a_new_review_even_when_the_property_did_not_change(self):
        template=self.tax_template(False)
        entered=self.enter()
        quote=self.quote(entered['folio'])
        self.assertEqual((quote['net_total'],quote['taxes'],quote['total']),('3000.00','450.00','3450.00'))
        property_version=frappe.db.get_value('HS Property',self.prop.name,'modified')
        template.taxes[0].rate=10
        template.save()
        self.assertEqual(frappe.db.get_value('HS Property',self.prop.name,'modified'),property_version)
        with self.assertRaises(frappe.ValidationError):self.emit(quote)
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        self.assertEqual({row.status for row in self.charges(entered['stay'])},{'Scheduled'})
        current=self.quote(entered['folio'])
        self.assertEqual(current['total'],'3300.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',self.emit(current)['invoice'],'grand_total'),3300)

    def test_no_new_charge_preview_does_not_reconcile_an_existing_receipt(self):
        entered=self.enter()
        invoice=self.command('invoice',dict(folio=entered['folio']))['invoice']
        shift=self.command('open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1})
        payment=self.command('payment',dict(stay=entered['stay'],shift=shift,method=method,kind='Advance',amount=500))['payment_entry']
        before=frappe.db.get_value('Payment Entry',payment,'unallocated_amount')
        self.assertFalse(self.quote(entered['folio'])['ready'])
        self.assertEqual(frappe.db.get_value('Payment Entry',payment,'unallocated_amount'),before)
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'outstanding_amount'),3000)
