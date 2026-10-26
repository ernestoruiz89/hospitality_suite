"""Explicit operational demo data, native stock and safe repeat/rollback semantics."""
from datetime import timedelta
import hashlib
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.demo_scenario import build
from hospitality_suite.schema import SCHEMA
from hospitality_suite.service import canonical


class TestDemoScenario(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.old_flag=frappe.conf.get('hospitality_allow_demo');frappe.conf.hospitality_allow_demo=True

    def tearDown(self):
        frappe.conf.hospitality_allow_demo=self.old_flag;frappe.set_user('Administrator');super().tearDown()

    def snapshot(self):
        names=set(SCHEMA)|{'Version','Sales Invoice','Sales Invoice Item','Payment Entry','Payment Entry Reference','Journal Entry','Journal Entry Account','GL Entry','Payment Ledger Entry','Stock Entry','Stock Entry Detail','Stock Ledger Entry','Bin'}
        result={}
        for dt in names:
            rows=frappe.db.get_singles_dict(dt) if frappe.get_meta(dt).issingle else frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            result[dt]=hashlib.sha256(canonical(rows).encode()).hexdigest()
        return result

    def test_demo_is_explicit_local_admin_only_and_never_a_public_endpoint(self):
        before=self.snapshot();frappe.conf.hospitality_allow_demo=False
        with self.assertRaises(frappe.PermissionError):build()
        frappe.conf.hospitality_allow_demo=True
        for user in ('receptionist@hospitality.example.invalid','manager@hospitality.example.invalid','Guest'):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):build()
        self.assertEqual(self.snapshot(),before)
        self.assertNotIn(build,frappe.whitelisted)

    def test_two_properties_have_reproducible_reservations_consumptions_and_native_stock(self):
        initial=frappe.db.count('Stock Entry');result=build()
        self.assertTrue(result['synthetic']);self.assertFalse(result['external_providers_active']);self.assertEqual(len(result['properties']),2)
        self.assertEqual({row['mode'] for row in result['properties']},{'Hotel','Por tiempo'})
        for row in result['properties']:
            self.assertGreaterEqual(frappe.db.count('HS Room',{'property':row['property']}),10)
            self.assertEqual(row['current'],dict(reservation='Confirmed',stay='Active',service='Delivered'))
            self.assertEqual(frappe.db.get_value('HS Booking',row['booking'],'channel'),'Demostración ficticia')
            service=frappe.get_doc('HS Service Request',row['service']);self.assertTrue(service.stock_entry)
            self.assertEqual(frappe.db.get_value('Stock Entry',service.stock_entry,'docstatus'),1)
            self.assertEqual(frappe.db.get_value('HS Charge',service.charge,'amount'),30)
        self.assertEqual(frappe.db.count('Stock Entry'),initial+2)
        self.assertTrue(all(frappe.db.count(dt)==0 for dt in ('Sales Invoice','Payment Entry','HS Payment','HS Shift')))

    def test_repeat_returns_the_same_references_without_any_business_write(self):
        original=build();before=self.snapshot();repeated=build()
        self.assertEqual(original,repeated);self.assertEqual(self.snapshot(),before)

    def test_a_failure_in_the_second_property_rolls_back_the_whole_scenario_including_native_stock(self):
        before=self.snapshot();execute=api.execute;delivered=0
        def interrupted(prop,action,*args,**kwargs):
            nonlocal delivered
            result=execute(prop,action,*args,**kwargs)
            if action=='update_service':
                delivered+=1
                if delivered==2:raise RuntimeError('Injected demo interruption after native stock')
            return result
        with patch.object(api,'execute',side_effect=interrupted),self.assertRaisesRegex(RuntimeError,'Injected demo interruption'):
            build()
        self.assertEqual(delivered,2);self.assertEqual(self.snapshot(),before)
        self.assertEqual(len(build()['properties']),2)

    def test_repeat_preserves_operations_changed_later_instead_of_recreating_or_resetting_them(self):
        result=build();row=result['properties'][0];booking=frappe.get_doc('HS Booking',row['booking'])
        api.execute(row['property'],'booking_status',uuid.uuid4().hex,dict(booking=booking.name,modified=str(booking.modified),status='Cancelled',reason='Cancelación ficticia posterior a la carga'))
        before=self.snapshot();repeated=build()
        self.assertEqual(repeated['properties'][0]['current']['reservation'],'Cancelled');self.assertEqual(self.snapshot(),before)

    def test_first_run_rejects_existing_unrelated_operations_without_partial_creation(self):
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});guest=frappe.get_doc('HS Guest',{'property':prop.name})
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'});start=now_datetime()
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance'];api.execute(prop.name,'reserve',uuid.uuid4().hex,values)
        before=self.snapshot()
        with self.assertRaises(frappe.ValidationError):build()
        self.assertEqual(self.snapshot(),before)

    def test_corrupt_saved_reference_fails_without_creating_another_demo(self):
        result=build();row=result['properties'][0];request=frappe.get_doc('HS Request',{'property':row['property'],'operation':'demo_scenario_v1'})
        data=frappe.parse_json(request.result);data['stay']=result['properties'][1]['stay'];frappe.db.set_value('HS Request',request.name,'result',canonical(data))
        before=self.snapshot()
        with self.assertRaises(frappe.ValidationError):build()
        self.assertEqual(self.snapshot(),before)
