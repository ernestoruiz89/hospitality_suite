"""Selected-property authorization with real documents and multi-property actors."""
from datetime import timedelta
import hashlib
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api, security, portal
from hospitality_suite.service import operation, canonical, locked_doc


class TestPermissionsAudit(IntegrationTestCase):
    def setUp(self):
        super().setUp(); self.addCleanup(frappe.db.rollback); frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})

    def tearDown(self):
        frappe.set_user('Administrator'); super().tearDown()

    def call(self,prop,action,data,key=None):
        return api.execute(prop.name,action,uuid.uuid4().hex if key is None else key,data)

    def values(self,prop,index=0):
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        room=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','category'],order_by='room_number')[index]
        start=now_datetime().replace(microsecond=0)
        return dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(category=room.category,room=room.name,people=1)])

    def book(self,prop,walk_in=False,index=0):
        values=self.values(prop,index); values['acceptance']=api.preview(prop.name,values)['acceptance']
        return self.call(prop,'walk_in' if walk_in else 'reserve',values)

    def snapshot(self):
        from hospitality_suite.schema import SCHEMA
        names=set(SCHEMA)|{'Version','Sales Invoice','Payment Entry','Journal Entry','GL Entry','Payment Ledger Entry','Stock Entry','Stock Ledger Entry'}
        return {dt:hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest() for dt in names}

    def rejected(self,callback):
        before=self.snapshot()
        with self.assertRaises(frappe.PermissionError): callback()
        self.assertEqual(self.snapshot(),before)

    def test_multi_property_actor_cannot_cancel_a_booking_from_another_selected_property(self):
        name=self.book(self.other)['booking']; booking=frappe.get_doc('HS Booking',name)
        for user in ('Administrator','receptionist@hospitality.example.invalid'):
            frappe.set_user(user)
            self.assertIn(self.prop.name,security.allowed_properties()); self.assertIn(self.other.name,security.allowed_properties())
            self.rejected(lambda:self.call(self.prop,'booking_status',dict(booking=name,modified=str(booking.modified),status='Cancelled',reason='Contexto incorrecto')))

    def test_foreign_booking_previews_never_disclose_its_fee_or_arrival_quote(self):
        name=self.book(self.other)['booking']
        for action,data in (
            ('booking_status',dict(booking=name,status='Cancelled')),
            ('modify_reservation',dict(booking=name)),
            ('check_in',dict(booking=name))):
            with self.subTest(action=action): self.rejected(lambda:api.preview(self.prop.name,data,action))

    def test_foreign_stay_operations_fail_before_modification(self):
        result=self.book(self.other,walk_in=True); stay=frappe.get_doc('HS Stay',result['stay'])
        base=dict(stay=stay.name,modified=str(stay.modified),reason='Contexto incorrecto',notes='Revisión sintética')
        for action in ('prepare_departure','inspect_departure','check_out','create_folio','companions'):
            with self.subTest(action=action): self.rejected(lambda:self.call(self.prop,action,base))
        for action in ('extend','change_room','departure'):
            with self.subTest(action=action): self.rejected(lambda:api.preview(self.prop.name,base,action))

    def test_foreign_shift_method_folio_and_service_are_rejected(self):
        result=self.book(self.other,walk_in=True)
        shift=self.call(self.other,'open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.other.name})
        service=self.call(self.other,'request_service',dict(stay=result['stay'],folio=result['folio'],item='HS-DEMO-WATER',quantity=1))['service']
        cases=(('close_shift',dict(shift=shift)),('withdrawal',dict(shift=shift,method=method,amount=1,reason='Prueba')),
               ('invoice',dict(folio=result['folio'])),('update_service',dict(service=service,status='Delivered')),
               ('payment',dict(method=method,shift=shift,folio=result['folio'],stay=result['stay'],amount=1,kind='Payment')))
        for action,data in cases:
            with self.subTest(action=action): self.rejected(lambda:self.call(self.prop,action,data))

    def test_property_context_is_restored_after_error_and_same_key_can_be_retried_correctly(self):
        name=self.book(self.other)['booking']; booking=frappe.get_doc('HS Booking',name); key=uuid.uuid4().hex
        values=dict(booking=name,modified=str(booking.modified),status='Cancelled',reason='Cancelación autorizada de prueba')
        self.rejected(lambda:self.call(self.prop,'booking_status',values,key))
        self.assertIsNone(getattr(frappe.local,'hs_selected_property',None)); self.assertFalse(getattr(frappe.local,'hs_operation',False))
        # A document-only authorized read does not inherit a failed command's selection.
        self.assertEqual(api.booking_detail(name)['booking']['name'],name)
        result=self.call(self.other,'booking_status',values,key)
        self.assertEqual(result['status'],'Cancelled'); self.assertEqual(self.call(self.other,'booking_status',values,key),result)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':name,'action':'Cancelled'}),1)

    def test_confirmed_operational_documents_cannot_be_deleted_even_by_administrator(self):
        result=self.book(self.prop,walk_in=True)
        shift=self.call(self.prop,'open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        paid=self.call(self.prop,'payment',dict(stay=result['stay'],folio=result['folio'],shift=shift,method=method,kind='Payment',amount=100))
        names=[('HS Payment',paid['payment']),('HS Charge',frappe.db.get_value('HS Charge',{'stay':result['stay']})),
               ('HS Shift',shift),('HS Audit Event',frappe.db.get_value('HS Audit Event',{'source_name':result['stay']}))]
        before=self.snapshot()
        for dt,name in names:
            with self.subTest(doctype=dt), self.assertRaises(frappe.ValidationError): frappe.delete_doc(dt,name,ignore_permissions=True)
        self.assertEqual(self.snapshot(),before)

    def test_foreign_folio_discovered_after_stay_changes_rolls_back_the_whole_extension(self):
        own=self.book(self.prop,walk_in=True); other=self.book(self.other,walk_in=True)
        stay=frappe.get_doc('HS Stay',own['stay'])
        values=dict(stay=stay.name,folio=other['folio'],ends_at=str(stay.ends_at+timedelta(days=1)),modified=str(stay.modified),reason='Extensión sintética')
        values['acceptance']=api.preview(self.prop.name,values,'extend')['acceptance']
        self.rejected(lambda:self.call(self.prop,'extend',values))

    def test_nested_operations_cannot_change_selection_or_save_a_foreign_document(self):
        room=frappe.get_doc('HS Room',{'property':self.other.name})
        before=self.snapshot()
        with operation(self.prop):
            with self.assertRaises(frappe.PermissionError), operation(self.other): pass
            with self.assertRaises(frappe.PermissionError): locked_doc('HS Room',room.name)
            with self.assertRaises(frappe.PermissionError):
                room.floor='Cambio no permitido'; room.save()
            with operation():
                self.assertEqual(frappe.local.hs_selected_property,(self.prop.name,self.prop.company))
        self.assertIsNone(getattr(frappe.local,'hs_selected_property',None))
        self.assertFalse(getattr(frappe.local,'hs_operation',False)); self.assertEqual(self.snapshot(),before)

    def test_nonexistent_and_injected_references_get_the_same_scope_rejection(self):
        for name in ('no-existe',"' OR 1=1 --",'`tabHS Booking`',self.other.name):
            self.rejected(lambda:self.call(self.prop,'booking_status',dict(booking=name,status='Cancelled',reason='Referencia inválida')))

    def test_all_nine_roles_advertise_only_authorized_actions_and_enforce_them_before_handlers(self):
        managers={'setup','reserve','stay','finance','petty','clean','inspect','maintain','service','report','approve','cash_approve','guest','incident','inventory','ticket'}
        matrix={
            'administrator':managers,'manager':managers,'supervisor':managers-{'approve'},
            'receptionist':{'reserve','stay','service','guest','ticket','petty'},'cashier':{'finance','service','petty'},
            'housekeeping':{'clean','incident','ticket','petty'},'maintenance':{'maintain','incident','ticket','petty'},
            'accountant':{'finance','report','inventory','petty'},'auditor':{'report'}}
        for account,actions in matrix.items():
            with self.subTest(role=account):
                frappe.set_user(account+'@hospitality.example.invalid')
                self.assertEqual(set(api.bootstrap()['actions']),actions)
                for action in actions: security.require(self.prop.name,action)
                for action in set(security.ACTIONS)-actions:
                    with self.assertRaises(frappe.PermissionError): security.require(self.prop.name,action)
                # Read-only auditor and operational roles cannot invoke a financial command.
                if 'finance' not in actions:
                    self.rejected(lambda:self.call(self.prop,'open_shift',dict(opening_amount=0)))

    def test_malformed_oversized_nonfinite_and_deep_json_fail_without_database_changes(self):
        deep={}; node=deep
        for _ in range(34): node['nested']={}; node=node['nested']
        cases=['{','[]',{'notes':'a'*100001},{'amount':float('nan')},'{"amount": Infinity}',deep,{'quantity':object()}]
        before=self.snapshot()
        for values in cases:
            with self.subTest(kind=type(values).__name__), self.assertRaises(frappe.ValidationError): api.payload(values)
        for key in ([],{},1,' ','x'*141):
            with self.assertRaises(frappe.ValidationError): self.call(self.prop,'open_shift',dict(opening_amount=0),key=key)
        self.assertEqual(self.snapshot(),before)

    def test_public_request_boundary_rejects_invalid_quantities_and_json(self):
        for values in ('{','[]',{'quantity':[1]},{'quantity':0},{'people':0},{'people':False},{'quantity':1.5},{'people':'NaN'},{'quantity':11},{'notes':'a'*100001}):
            with self.subTest(values=type(values).__name__), self.assertRaises(frappe.ValidationError): portal.request_values(values)
