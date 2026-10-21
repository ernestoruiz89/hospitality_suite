"""Combined reception/cashier workflow with separate cleaning and accounting roles."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api


class TestRoleAcceptance(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.user='role-acceptance@hospitality.example.invalid'
        self.call('assign_user',dict(email=self.user,first_name='Recepción y caja de pruebas',roles=['HS Receptionist','HS Cashier'],reason='Aceptación funcional explícita'))

    def tearDown(self):frappe.set_user('Administrator');super().tearDown()
    def call(self,action,data):return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def test_combined_operator_completes_visit_then_cleaning_and_accounting_follow_the_same_documents(self):
        guest=frappe.get_doc('HS Guest',{'property':self.prop.name});room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H101'})
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1})
        now=now_datetime().replace(microsecond=0)
        frappe.set_user(self.user)
        values=dict(guest=guest.name,customer=guest.customer,starts_at=str(now),ends_at=str(now+timedelta(days=1)),rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance'];reserved=self.call('reserve',values)
        booking=frappe.get_doc('HS Booking',reserved['booking']);entered=self.call('check_in',dict(booking=booking.name,modified=str(booking.modified),guest=guest.name))
        requested=self.call('request_service',dict(stay=entered['stay'],folio=entered['folio'],item='HS-DEMO-WATER',quantity=1))
        service=frappe.get_doc('HS Service Request',requested['service']);self.call('update_service',dict(service=service.name,modified=str(service.modified),status='Delivered'))
        stay=frappe.get_doc('HS Stay',entered['stay']);values=dict(stay=stay.name,folio=entered['folio'],ends_at=str(now+timedelta(days=2)),reason='Extensión ficticia solicitada')
        values['acceptance']=api.preview(self.prop.name,values,'extend')['acceptance'];self.call('extend',{**values,'modified':str(stay.modified)})
        shift=self.call('open_shift',dict(opening_amount=0))['shift']
        paid=self.call('payment',dict(stay=stay.name,folio=entered['folio'],shift=shift,method=method,kind='Payment',amount=3030,tendered=3030))
        payment=frappe.get_doc('Payment Entry',paid['payment_entry']);invoice=payment.references[0].reference_name
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'outstanding_amount'),0)
        stay.reload();self.call('check_out',dict(stay=stay.name,modified=str(stay.modified)))
        current=frappe.get_doc('HS Shift',shift);self.call('close_shift',dict(shift=shift,modified=str(current.modified),denominations={'NIO':[dict(value=1,count=3030)]}))
        self.assertEqual(frappe.db.get_value('HS Stay',stay.name,'status'),'Checked Out');self.assertEqual(frappe.db.get_value('HS Shift',shift,'difference'),0)
        task=frappe.get_doc('HS Cleaning Task',{'room':room.name,'status':'Pending'})
        checks={key:True for key in ('baño','cama','minibar','superficies')}
        frappe.set_user('housekeeping@hospitality.example.invalid')
        self.call('cleaning',dict(task=task.name,modified=str(task.modified),status='In Progress'))
        task.reload();self.call('cleaning',dict(task=task.name,modified=str(task.modified),status='Inspection',checklist=checks))
        self.assertEqual(frappe.db.get_value('HS Room',room.name,'cleaning_status'),'Inspection')
        frappe.set_user('supervisor@hospitality.example.invalid');task.reload()
        self.call('cleaning',dict(task=task.name,modified=str(task.modified),status='Completed',checklist=checks))
        self.assertEqual(frappe.db.get_value('HS Room',room.name,'cleaning_status'),'Clean')
        frappe.set_user('accountant@hospitality.example.invalid')
        rows=api.report(self.prop.name,'Conciliación',dict(stay=stay.name))
        self.assertTrue(rows);self.assertTrue(all(row['status']=='OK' for row in rows));self.assertIn(invoice,{row['erp_document'] for row in rows});self.assertIn(payment.name,{row['erp_document'] for row in rows})
        frappe.set_user('manager@hospitality.example.invalid')
        rows=api.report(self.prop.name,'Producción',dict(room=room.name))
        self.assertEqual(sum(float(row['amount']) for row in rows),3030)
        frappe.set_user('receptionist@hospitality.example.invalid')
        self.assertNotIn('HS Cashier',frappe.get_roles())
        with self.assertRaises(frappe.PermissionError):self.call('open_shift',dict(opening_amount=0))
