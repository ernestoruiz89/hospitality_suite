from datetime import timedelta
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import canonical,operation


class TestGuestProfiles(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def create(self,**extra):
        return api.create_guest(self.prop.name,dict(full_name='Persona de prueba '+uuid.uuid4().hex[:6],**extra),uuid.uuid4().hex)

    def update(self,info,data,reason='Corrección de prueba',key=None):
        return api.update_guest(self.prop.name,info['guest'],info['modified'],data,reason,key or uuid.uuid4().hex,info['related_versions'])

    def hashes(self):
        return {dt:canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)) for dt in
                ('HS Guest','Customer','Contact','Contact Email','Contact Phone','Address','Dynamic Link','HS Request','HS Audit Event','Version',
                 'HS Booking','HS Stay','HS Allocation','HS Folio','HS Charge','HS Payment','Sales Invoice','Payment Entry','GL Entry','Stock Ledger Entry')}

    def policy(self,required):
        with operation():self.prop.guest_id_required=required;self.prop.save()

    def test_policy_is_projected_without_identity_data_and_required_registration_is_atomic(self):
        self.policy(1)
        data=api.bootstrap(self.prop.name)
        self.assertTrue(next(p for p in data['properties'] if p.name==self.prop.name).guest_id_required)
        self.assertTrue(all(set(g)=={'name','full_name','customer'} for g in data['guests']))
        before=self.hashes()
        with self.assertRaisesRegex(frappe.ValidationError,'requiere.*identificación'):self.create()
        self.assertEqual(self.hashes(),before)
        saved=self.create(identity_number='IDENTIFICACION-FICTICIA')
        self.assertEqual(api.guest_detail(saved['guest'])['values']['identity_number'],'IDENTIFICACION-FICTICIA')
        self.assertFalse(api.guest_detail(saved['guest'])['values']['identity_type'])
        before=self.hashes()
        with self.assertRaises(frappe.ValidationError):self.update(api.guest_detail(saved['guest']),{'identity_number':''})
        self.assertEqual(self.hashes(),before)

    def test_optional_registration_collects_no_unrequested_crm_or_identification(self):
        self.policy(0)
        counts={dt:frappe.db.count(dt) for dt in ('Contact','Address')}
        saved=self.create(country='Nicaragua')  # Old clients supplied this default without an address.
        guest=frappe.get_doc('HS Guest',saved['guest'])
        self.assertFalse(guest.identity_number or guest.contact or guest.address)
        self.assertEqual({dt:frappe.db.count(dt) for dt in counts},counts)
        self.assertEqual(api.guest_detail(guest.name)['values']['country'],'')

    def test_owned_crm_updates_in_place_and_omitted_profile_fields_are_retained(self):
        saved=self.create(email='first@example.invalid',phone='00000000',identity_number='FICTICIA',
                          address_line1='Calle ficticia',city='Ciudad ficticia',country='Nicaragua')
        guest=frappe.get_doc('HS Guest',saved['guest']);ids=(guest.name,guest.customer,guest.contact,guest.address)
        customer_name=frappe.db.get_value('Customer',guest.customer,'customer_name')
        counts={dt:frappe.db.count(dt) for dt in ('HS Guest','Customer','Contact','Address')}
        contact=frappe.get_doc('Contact',guest.contact)
        contact.append('email_ids',dict(email_id='secondary@example.invalid'));contact.phone_nos[0].is_primary_mobile_no=1;contact.save(ignore_permissions=True)
        info=api.guest_detail(guest.name)
        self.assertFalse(info['shared_contact'] or info['shared_address'])
        changed=self.update(info,dict(full_name='Nombre corregido de prueba',phone='11111111',city='Otra ciudad'))
        guest.reload();contact.reload()
        self.assertEqual((guest.name,guest.customer,guest.contact,guest.address),ids)
        self.assertEqual(guest.identity_number,'FICTICIA');self.assertEqual(guest.email,'first@example.invalid')
        self.assertEqual(contact.phone,'11111111');self.assertEqual(contact.full_name,'Nombre corregido de prueba')
        self.assertEqual(contact.mobile_no,'00000000')
        self.assertIn('secondary@example.invalid',[r.email_id for r in contact.email_ids])
        self.assertEqual(frappe.db.get_value('Address',guest.address,'city'),'Otra ciudad')
        self.assertEqual(frappe.db.get_value('Customer',guest.customer,'customer_name'),customer_name)
        self.assertEqual({dt:frappe.db.count(dt) for dt in counts},counts)
        self.assertEqual(changed['guest'],guest.name)
        self.update(api.guest_detail(guest.name),{'email':''})
        self.update(api.guest_detail(guest.name),{'full_name':'Otra corrección de nombre'})
        self.update(api.guest_detail(guest.name),{'email':'third@example.invalid'})
        contact.reload()
        self.assertEqual({r.email_id for r in contact.email_ids},{'secondary@example.invalid','third@example.invalid'})

    def test_update_retry_is_idempotent_and_stale_guest_or_crm_versions_roll_back(self):
        saved=self.create(phone='00000000');info=saved;key=uuid.uuid4().hex
        first=self.update(info,{'phone':'11111111'},key=key);before=self.hashes()
        self.assertEqual(self.update(info,{'phone':'11111111'},key=key),first)
        self.assertEqual(self.hashes(),before)
        with self.assertRaises(frappe.TimestampMismatchError):self.update(info,{'phone':'22222222'})
        self.assertEqual(self.hashes(),before)
        info=api.guest_detail(saved['guest']);guest=frappe.get_doc('HS Guest',saved['guest'])
        contact=frappe.get_doc('Contact',guest.contact);contact.designation='Cambio concurrente';contact.save(ignore_permissions=True)
        before=self.hashes()
        with self.assertRaises(frappe.TimestampMismatchError):self.update(info,{'phone':'33333333'})
        self.assertEqual(self.hashes(),before)

    def test_shared_and_legacy_crm_are_preserved_while_the_guest_identity_stays_the_same(self):
        saved=self.create(phone='00000000',address_line1='Dirección compartida ficticia',city='Ciudad ficticia',country='Nicaragua')
        guest=frappe.get_doc('HS Guest',saved['guest'])
        other=frappe.get_doc('HS Guest',{'property':self.prop.name,'name':['!=',guest.name]})
        with operation():other.contact=guest.contact;other.address=guest.address;other.customer=guest.customer;other.save()
        old_contact,old_address=frappe.get_doc('Contact',guest.contact).as_dict(),frappe.get_doc('Address',guest.address).as_dict()
        info=api.guest_detail(guest.name);self.assertTrue(info['shared_contact'] and info['shared_address'])
        self.update(info,dict(phone='11111111',city='Ciudad nueva'))
        guest.reload();other.reload()
        self.assertEqual(guest.name,saved['guest']);self.assertEqual(guest.customer,saved['customer'])
        self.assertNotEqual(guest.contact,other.contact);self.assertNotEqual(guest.address,other.address)
        self.assertEqual(frappe.get_doc('Contact',other.contact).as_dict(),old_contact)
        self.assertEqual(frappe.get_doc('Address',other.address).as_dict(),old_address)
        # A legacy record without a guest ownership link is also copied safely.
        contact=frappe.get_doc('Contact',guest.contact)
        contact.set('links',[r for r in contact.links if r.link_doctype!='HS Guest']);contact.save(ignore_permissions=True)
        legacy=contact.name;before=canonical(contact.as_dict())
        self.update(api.guest_detail(guest.name),{'phone':'22222222'})
        self.assertNotEqual(frappe.db.get_value('HS Guest',guest.name,'contact'),legacy)
        self.assertEqual(canonical(frappe.get_doc('Contact',legacy).as_dict()),before)

    def test_invalid_native_data_reason_and_protected_fields_leave_no_partial_corrections(self):
        saved=self.create(phone='00000000');info=api.guest_detail(saved['guest'])
        for data,reason in [({'email':'not an email'},'Prueba'),({'phone':'11111111'},''),({'customer':'forged'},'Prueba'),
                            ({'identity_file':'/private/files/forged'},'Prueba'),({'address_line1':'Incompleta'},'Prueba')]:
            before=self.hashes()
            with self.assertRaises(frappe.ValidationError):self.update(info,data,reason)
            self.assertEqual(self.hashes(),before)

    def test_clearing_profile_address_preserves_native_history_and_primary_contact_can_be_cleared(self):
        saved=self.create(phone='00000000',email='first@example.invalid',address_line1='Calle ficticia',city='Ciudad ficticia',country='Nicaragua')
        guest=frappe.get_doc('HS Guest',saved['guest']);address=canonical(frappe.get_doc('Address',guest.address).as_dict())
        address_name,contact_name=guest.address,guest.contact
        self.update(api.guest_detail(guest.name),dict(address_line1='',phone='',email=''))
        guest.reload();self.assertFalse(guest.address);self.assertEqual(guest.contact,contact_name)
        self.assertEqual(canonical(frappe.get_doc('Address',address_name).as_dict()),address)
        self.assertFalse(frappe.db.get_value('Contact',contact_name,'email_id') or frappe.db.get_value('Contact',contact_name,'phone'))

    def test_guest_role_scope_denies_cashier_guest_and_foreign_property_and_does_not_create_duplicate_people(self):
        saved=self.create(identity_number='FICTICIA');info=api.guest_detail(saved['guest'])
        for user in ('Guest','cashier@hospitality.example.invalid','housekeeping@hospitality.example.invalid'):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):api.guest_detail(saved['guest'])
            with self.assertRaises(frappe.PermissionError):self.update(info,{'full_name':'Forbidden'})
        frappe.set_user('receptionist@hospitality.example.invalid')
        self.assertEqual(api.guest_detail(saved['guest'])['guest'],saved['guest'])
        other=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        before=self.hashes()
        with self.assertRaises(frappe.PermissionError):api.update_guest(other.name,info['guest'],info['modified'],{'full_name':'Forbidden'},'Prueba',uuid.uuid4().hex,info['related_versions'])
        self.assertEqual(self.hashes(),before)
        frappe.set_user('Administrator')
        email='guest-scope-'+uuid.uuid4().hex[:8]+'@example.invalid'
        frappe.get_doc(dict(doctype='User',email=email,first_name='Usuario de alcance ficticio',user_type='System User',send_welcome_email=0,
                            roles=[dict(role='HS Receptionist')])).insert(ignore_permissions=True)
        from hospitality_suite.service import insert
        with operation():insert('HS Access',self.prop,user=email)
        foreign=frappe.get_doc('HS Guest',{'property':other.name})
        frappe.set_user(email)
        with self.assertRaises(frappe.PermissionError):api.guest_detail(foreign.name)
        self.assertEqual(api.guest_detail(saved['guest'])['guest'],saved['guest'])

    def test_identity_correction_preserves_existing_stay_and_companion_references(self):
        self.policy(1);saved=self.create(identity_number='FICTICIA')
        room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H101'})
        start=now_datetime().replace(microsecond=0)
        companion=self.create(identity_number='FICTICIA-ACOMPANANTE')
        data=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=saved['customer'],guest=saved['guest'],
                  rooms=[dict(room=room.name,category=room.category,people=2)])
        data['acceptance']=api.preview(self.prop.name,data)['acceptance']
        entered=api.execute(self.prop.name,'walk_in',uuid.uuid4().hex,data)
        api.execute(self.prop.name,'companions',uuid.uuid4().hex,dict(stay=entered['stay'],
            modified=str(frappe.db.get_value('HS Stay',entered['stay'],'modified')),guests=[companion['guest']]))
        watched={dt:canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True))
                 for dt in ('HS Stay','HS Stay Guest','HS Booking','HS Folio','HS Charge','GL Entry','Stock Ledger Entry')}
        self.update(api.guest_detail(saved['guest']),dict(full_name='Nombre corregido',identity_number='FICTICIA-CORREGIDA'))
        self.update(api.guest_detail(companion['guest']),dict(full_name='Acompañante corregido',identity_number='FICTICIA-ACOMP-CORREGIDA'))
        self.assertEqual(frappe.db.get_value('HS Stay',entered['stay'],'guest'),saved['guest'])
        for dt,expected in watched.items():self.assertEqual(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)),expected)

    def test_native_versions_and_audit_record_the_correction_without_copying_identification_into_audit_details(self):
        saved=self.create(identity_number='FICTICIA-ANTERIOR');info=api.guest_detail(saved['guest'])
        with patch.object(frappe,'in_test',False):
            self.update(info,{'identity_number':'FICTICIA-CORREGIDA'},reason='Corrección autorizada de datos')
        event=frappe.get_doc('HS Audit Event',{'action':'Update guest','source_name':saved['guest']})
        self.assertEqual(event.reason,'Corrección autorizada de datos')
        self.assertEqual(frappe.parse_json(event.details),{'fields':['identity_number']})
        self.assertNotIn('FICTICIA',event.details)
        version=frappe.get_doc('Version',{'ref_doctype':'HS Guest','docname':saved['guest']})
        self.assertIn(['identity_number','FICTICIA-ANTERIOR','FICTICIA-CORREGIDA'],frappe.parse_json(version.data)['changed'])

    def test_delegated_registration_rejects_unregistered_payer_and_forged_crm_links(self):
        other=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        foreign=frappe.get_doc('HS Guest',{'property':other.name})
        before=self.hashes()
        with self.assertRaises(frappe.PermissionError):self.create(customer=foreign.customer)
        with self.assertRaises(frappe.ValidationError):self.create(contact='forged')
        self.assertEqual(self.hashes(),before)

    def test_native_guest_without_a_payer_can_be_corrected_without_creating_a_customer(self):
        from hospitality_suite.service import insert
        from hospitality_suite.security import party_names
        with operation():guest=insert('HS Guest',self.prop,full_name='Persona ficticia sin pagador')
        info=api.guest_detail(guest.name)
        self.assertEqual(info['customer_label'],'Sin cliente vinculado')
        count=frappe.db.count('Customer')
        self.update(info,dict(phone='00000000',address_line1='Calle ficticia',city='Ciudad ficticia',country='Nicaragua'))
        guest.reload()
        self.assertFalse(guest.customer);self.assertEqual(frappe.db.count('Customer'),count)
        self.assertEqual([(r.link_doctype,r.link_name) for r in frappe.get_doc('Contact',guest.contact).links],[('HS Guest',guest.name)])
        self.assertIn(guest.contact,party_names('Contact','receptionist@hospitality.example.invalid'))
        self.assertIn(guest.address,party_names('Address','receptionist@hospitality.example.invalid'))
