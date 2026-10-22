"""Real history for the seven critical action families, not just event counts."""
from datetime import timedelta
from unittest.mock import patch
import hashlib
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation,insert,canonical


class TestAuditHistory(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category'],order_by='room_number')
        self.method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})

    def tearDown(self):frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def booking(self,index=0,enter=False,days=1,early_minutes=10):
        start=now_datetime().replace(microsecond=0);room=self.rooms[index]
        values=dict(starts_at=str(start-timedelta(minutes=early_minutes)),ends_at=str(start+timedelta(days=days)),guest=self.guest.name,customer=self.guest.customer,
            rooms=[dict(category=room.category,room=room.name,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return self.call('walk_in' if enter else 'reserve',values)

    def event(self,action,source=None):
        filters={'property':self.prop.name,'action':action}
        if source:filters['source_name']=source
        event=frappe.get_last_doc('HS Audit Event',filters=filters)
        self.assertEqual(event.company,self.prop.company);self.assertEqual(event.actor,frappe.session.user)
        self.assertTrue(event.occurred_at);self.assertTrue(event.source_doctype);self.assertTrue(event.source_name)
        self.assertTrue(event.reason)
        return event,frappe.parse_json(event.details)['_values']

    def fingerprints(self):
        from hospitality_suite.schema import SCHEMA
        names=set(SCHEMA)|{'Version','Sales Invoice','Payment Entry','Journal Entry','GL Entry','Payment Ledger Entry'}
        return {dt:hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest() for dt in names}

    def test_native_rate_update_requires_reason_and_keeps_values_without_copying_identity(self):
        rate=frappe.get_doc('HS Rate',{'property':self.prop.name,'mode':'Hotel'})
        original=rate.amount;rate.amount=1900
        with self.assertRaises(frappe.ValidationError):rate.save()
        self.assertEqual(frappe.db.get_value('HS Rate',rate.name,'amount'),original)
        for reason in ([1],{'text':'No es texto'},'x'*1001):
            rate.reload();rate.amount=1900;rate.change_reason=reason
            with self.assertRaises(frappe.ValidationError):rate.save()
        rate.reload();rate.amount=1900
        rate.change_reason='Temporada sintética aceptada';rate.flags.ignore_version=True;rate.save()
        event,values=self.event('Rate changed',rate.name)
        self.assertEqual(event.reason,'Temporada sintética aceptada');self.assertEqual(values['before']['amount'],original);self.assertEqual(values['after']['amount'],1900)
        self.assertNotIn('change_reason',values['after']);self.assertNotIn('identity_number',json.dumps(values))
        count=frappe.db.count('HS Audit Event',{'source_name':rate.name,'action':'Rate changed'});rate.save()
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':rate.name,'action':'Rate changed'}),count)
        rate.amount=2100;rate.change_reason='Otro precio posterior';rate.save()
        detail=api.audit_detail(self.prop.name,event.name)
        self.assertNotIn(rate.name,detail['values_document']);self.assertIn(rate.title,detail['values_document'])
        amount=next(row for row in detail['values'] if row['field']=='amount')
        self.assertIn('1,900.00',amount['after']);self.assertIn('NIO',amount['after']);self.assertTrue(amount['changed'])

    def test_discount_courtesy_and_extension_record_reason_original_values_and_idempotent_history(self):
        stay=self.booking(enter=True);doc=frappe.get_doc('HS Stay',stay['stay'])
        charge=frappe.db.get_value('HS Charge',{'stay':doc.name})
        for kind,amount in [('Discount',100),('Courtesy',None)]:
            result=self.call('adjustment',dict(charge=charge,adjustment_type=kind,amount=amount,reason='Ajuste sintético autorizado'))
            event,value=self.event('Adjustment '+kind,result['charge']);self.assertEqual(value['after']['applies_to_charge'],charge)
            self.assertLess(float(value['after']['amount']),0);self.assertEqual(event.reason,'Ajuste sintético autorizado')
        values=dict(stay=doc.name,folio=stay['folio'],modified=str(doc.modified),ends_at=str(doc.ends_at+timedelta(days=1)),reason='Salida ampliada por solicitud')
        values['acceptance']=api.preview(self.prop.name,values,'extend')['acceptance'];key=uuid.uuid4().hex
        result=self.call('extend',values,key);self.assertEqual(self.call('extend',values,key),result)
        event,value=self.event('Extend',doc.name);self.assertEqual(str(value['before']['ends_at']),str(doc.ends_at))
        self.assertEqual(float(value['before']['amount']),doc.amount);self.assertGreater(float(value['after']['amount']),doc.amount)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':doc.name,'action':'Extend'}),1)

    def test_cancel_and_no_show_preserve_actor_time_status_reason_and_penalty_values(self):
        for index,target in enumerate(('Cancelled','No Show')):
            name=self.booking(index)['booking'];booking=frappe.get_doc('HS Booking',name)
            frappe.set_user('receptionist@hospitality.example.invalid')
            self.call('booking_status',dict(booking=name,modified=str(booking.modified),status=target,reason='Decisión de recepción documentada'))
            frappe.set_user('Administrator')
            event=frappe.get_last_doc('HS Audit Event',filters={'source_name':name,'action':target})
            value=frappe.parse_json(event.details)['_values'];self.assertEqual(event.actor,'receptionist@hospitality.example.invalid')
            self.assertEqual(value['before']['status'],'Confirmed');self.assertEqual(value['after']['status'],target)
            self.assertEqual(value['after']['currency'],'NIO');self.assertEqual(value['after']['fee_amount'],0)
            self.assertTrue(event.occurred_at);self.assertEqual(event.reason,'Decisión de recepción documentada')

    def test_credit_refund_and_native_cancellation_record_actual_native_documents_and_amounts(self):
        stay=self.booking(enter=True);shift=self.call('open_shift',dict(opening_amount=0))['shift']
        paid=self.call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=self.method,kind='Payment',amount=500))
        invoice=frappe.db.get_value('HS Charge',{'stay':stay['stay'],'status':'Invoiced'},'sales_invoice')
        credit=self.call('credit_note',dict(invoice=invoice,reason='Devolución autorizada sintética'))['credit_note']
        event,value=self.event('Credit note',stay['folio']);self.assertEqual(value['name'],credit)
        self.assertEqual(value['doctype'],'Sales Invoice');self.assertLess(float(value['after']['grand_total']),0)
        refund=self.call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=self.method,kind='Refund',amount=100,source_payment=paid['payment'],credit_note=credit,reason='Devolución parcial al huésped'))
        event,value=self.event('Refund',refund['payment']);self.assertEqual(float(value['after']['amount']),100);self.assertEqual(value['after']['source_payment'],paid['payment'])
        native=frappe.get_doc('Payment Entry',refund['payment_entry']);native.hs_correction_reason='Corregir devolución duplicada';native.cancel()
        event=frappe.get_last_doc('HS Audit Event',filters={'property':self.prop.name,'action':'on_cancel'})
        value=frappe.parse_json(event.details)['_values'];self.assertEqual(value['before']['docstatus'],1);self.assertEqual(value['after']['docstatus'],2)
        self.assertEqual(value['name'],native.name);self.assertEqual(event.reason,'Corregir devolución duplicada')

    def test_shift_difference_captures_all_counts_and_approval_in_the_event(self):
        name=self.call('open_shift',dict(opening_amount=100))['shift'];shift=frappe.get_doc('HS Shift',name)
        self.call('close_shift',dict(shift=name,modified=str(shift.modified),denominations={'NIO':[dict(value=10,count=9)]},reason='Faltante de prueba aprobado',approve=1))
        event,value=self.event('Close shift',name);self.assertEqual(value['before']['status'],'Open');self.assertEqual(value['after']['status'],'Closed')
        self.assertEqual(float(value['after']['expected_amount']),100);self.assertEqual(float(value['after']['counted_amount']),90)
        self.assertEqual(float(value['after']['difference']),-10);self.assertEqual(value['after']['approved_by'],'Administrator')
        detail=api.audit_detail(self.prop.name,event.name);text=next(row['after'] for row in detail['values'] if row['field']=='denominations')
        self.assertIn('Esperado: 100.00',text);self.assertIn('Contado: 90.0',text)

    def test_close_and_reopen_keep_original_operational_day_and_historical_review(self):
        rate=frappe.get_doc('HS Rate',{'property':self.prop.name,'mode':'Hotel'});rate.amount=1600;rate.change_reason='Revisión manual para el cierre';rate.save()
        review=self.call('daily_close',dict(confirm=False));day=str(self.prop.business_date)
        self.assertTrue(review['period']['audit_review']['rows']);frozen=canonical(review['period']['audit_review'])
        before=self.fingerprints()
        for account in ('receptionist','accountant','auditor','supervisor'):
            frappe.set_user(account+'@hospitality.example.invalid')
            with self.assertRaises(frappe.PermissionError):self.call('daily_close',dict(confirm=True,review_acceptance=review['review_acceptance']))
            self.assertEqual(self.fingerprints(),before)
        frappe.set_user('Administrator')
        result=self.call('daily_close',dict(confirm=True,review_acceptance=review['review_acceptance']));event,value=self.event('Daily close Closed',result['close'])
        closed_event=event.name
        self.assertEqual(str(event.business_date),day);self.assertEqual(value['before']['status'],'Review');self.assertEqual(value['after']['status'],'Closed')
        self.assertEqual(str(value['after']['business_date']),day)
        summary=frappe.db.get_value('HS Daily Close',result['close'],'summary')
        self.assertEqual(canonical(frappe.parse_json(summary)['audit_review']),frozen)
        close=frappe.get_doc('HS Daily Close',result['close'])
        source=open(frappe.get_app_path('hospitality_suite','templates','print','daily_close.html'),encoding='utf-8').read()
        html=frappe.render_template(source,dict(doc=close))
        with operation():
            prop=frappe.get_doc('HS Property',self.prop.name);prop.property_name='Nombre posterior al cierre';prop.time_zone='America/New_York';prop.save()
        self.assertEqual(frappe.render_template(source,dict(doc=close)),html)
        rate.amount=1700;rate.change_reason='Precio después del cierre';rate.save()
        self.assertEqual(frappe.db.get_value('HS Daily Close',result['close'],'summary'),summary)
        self.call('reopen_day',dict(close=result['close'],reason='Revisión autorizada de datos del día'))
        event,value=self.event('Reopen day',result['close']);self.assertEqual(value['before']['status'],'Closed');self.assertEqual(value['after']['status'],'Reopened')
        self.assertEqual(str(frappe.db.get_value('HS Property',self.prop.name,'business_date')),day)
        updated=self.call('daily_close',dict(confirm=False,reason='Nota de la nueva ejecución'))
        self.call('daily_close',dict(confirm=True,reason='Nota de la nueva ejecución',review_acceptance=updated['review_acceptance']))
        self.assertEqual(frappe.parse_json(frappe.db.get_value('HS Daily Close',result['close'],'summary'))['presentation']['reason'],'Nota de la nueva ejecución')
        self.assertNotEqual(frappe.db.get_value('HS Daily Close',result['close'],'summary'),summary)
        old=api.audit_detail(self.prop.name,closed_event)
        self.assertEqual(canonical(old['close_snapshot']),canonical(frappe.parse_json(summary)))
        historic=frappe._dict(doctype='HS Daily Close',name=result['close'],property=self.prop.name,status='Closed',business_date=day,
            closed_at=value['after']['closed_at'],summary=canonical(old['close_snapshot']),blockers=canonical(old['close_blockers']))
        self.assertEqual(frappe.render_template(source,dict(doc=historic)),html)

    def test_review_groups_all_exception_families_and_rejects_a_changed_confirmation(self):
        for index,target in enumerate(('Cancelled','No Show')):
            name=self.booking(index)['booking'];doc=frappe.get_doc('HS Booking',name)
            self.call('booking_status',dict(booking=name,modified=str(doc.modified),status=target,reason='Cambio de prueba para auditoría'))
        stay=self.booking(2,enter=True);charge=frappe.db.get_value('HS Charge',{'stay':stay['stay']})
        for kind in ('Discount','Courtesy'):self.call('adjustment',dict(charge=charge,adjustment_type=kind,amount=10,reason='Ajuste para revisión'))
        shift=self.call('open_shift',dict(opening_amount=0))['shift']
        paid=self.call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=self.method,kind='Advance',amount=100))
        self.call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=self.method,kind='Refund',amount=20,source_payment=paid['payment'],reason='Anticipo devuelto para revisión'))
        review=self.call('daily_close',dict(confirm=False))
        actions={row['action'] for row in review['period']['audit_review']['rows']}
        self.assertTrue({'Reserva cancelada','Reserva sin presentación','Ajuste: Descuento','Ajuste: Cortesía'}.issubset(actions))
        self.assertIn('Devoluciones',{row['category'] for row in review['period']['audit_review']['rows']})
        rate=frappe.get_doc('HS Rate',{'property':self.prop.name,'mode':'Hotel'});rate.amount=1800;rate.change_reason='Cambio después de revisar';rate.save()
        with self.assertRaises(frappe.ValidationError):self.call('daily_close',dict(confirm=True,review_acceptance=review['review_acceptance']))
        self.assertEqual(str(frappe.db.get_value('HS Property',self.prop.name,'business_date')),str(self.prop.business_date))

    def test_detail_is_scoped_read_only_and_never_echoes_arbitrary_legacy_payload(self):
        with operation(self.prop):
            event=insert('HS Audit Event',self.prop,action='Legacy record',source_doctype='HS Property',source_name=self.prop.name,
                actor='Administrator',occurred_at=now_datetime(),business_date=self.prop.business_date,reason='Registro histórico',details='{"identity_number":"NEVER-ECHO-THIS","provider_secret":"NEVER-ECHO-THIS"}')
        before=self.fingerprints();detail=api.audit_detail(self.prop.name,event.name)
        self.assertFalse(detail['historical_values_available']);self.assertNotIn('NEVER-ECHO-THIS',json.dumps(detail));self.assertEqual(self.fingerprints(),before)
        other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        with self.assertRaises(frappe.PermissionError):api.audit_detail(other.name,event.name)
        for account in ('Guest','receptionist@hospitality.example.invalid','housekeeping@hospitality.example.invalid','maintenance@hospitality.example.invalid'):
            frappe.set_user(account)
            with self.assertRaises(frappe.PermissionError):api.audit_detail(self.prop.name,event.name)
        for account in ('supervisor','auditor','accountant'):
            frappe.set_user(account+'@hospitality.example.invalid');self.assertEqual(api.audit_detail(self.prop.name,event.name)['name'],event.name)

    def test_interrupted_confirmation_rolls_back_the_day_and_recovers_the_same_request(self):
        review=self.call('daily_close',dict(confirm=False));before=self.fingerprints();key=uuid.uuid4().hex
        values=dict(confirm=True,review_acceptance=review['review_acceptance'])
        with patch('hospitality_suite.closing.audit',side_effect=RuntimeError('Interrupted after advancing the day')):
            with self.assertRaises(RuntimeError):self.call('daily_close',values,key)
        self.assertEqual(self.fingerprints(),before)
        self.assertEqual(frappe.db.get_value('HS Daily Close',review['close'],'status'),'Review')
        result=self.call('daily_close',values,key);after=self.fingerprints()
        self.assertEqual(result['status'],'Closed');self.assertEqual(self.call('daily_close',values,key),result)
        self.assertEqual(self.fingerprints(),after)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':review['close'],'action':'Daily close Closed'}),1)
        self.assertEqual(frappe.db.count('HS Daily Close'),1)

    def test_interrupted_preparation_rolls_back_nightly_work_and_retry_reports_only_completed_work(self):
        with operation():
            self.prop.lodging_charge_policy='Nightly';self.prop.business_date=frappe.utils.nowdate();self.prop.save()
        # This scenario needs exactly two calendar nights. Subtracting ten
        # minutes crosses into a third date just after midnight.
        self.booking(enter=True,days=2,early_minutes=0)
        self.assertEqual(frappe.db.count('HS Charge',{'status':'Scheduled'}),2)
        before=self.fingerprints();key=uuid.uuid4().hex
        with patch('hospitality_suite.close_financials.snapshot',side_effect=RuntimeError('Interrupted after generating nightly charges')):
            with self.assertRaises(RuntimeError):self.call('daily_close',dict(confirm=False),key)
        self.assertEqual(self.fingerprints(),before);self.assertEqual(frappe.db.count('HS Charge',{'status':'Pending'}),0)
        result=self.call('daily_close',dict(confirm=False),key);after=self.fingerprints()
        self.assertEqual(result['status'],'Review');self.assertEqual(self.call('daily_close',dict(confirm=False),key),result)
        self.assertEqual(self.fingerprints(),after)
        self.assertEqual(frappe.db.count('HS Charge',{'status':'Scheduled'}),1);self.assertEqual(frappe.db.count('HS Charge',{'status':'Pending'}),1)
        self.assertEqual(frappe.db.count('HS Audit Event',{'action':'Generate nightly charges'}),1)
        self.assertEqual(frappe.db.count('HS Audit Event',{'action':'Daily close Review'}),1)
