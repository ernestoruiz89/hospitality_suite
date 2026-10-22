from datetime import datetime, time, timedelta

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api, pricing
from hospitality_suite.service import operation
from hospitality_suite.time import now_local, to_site


class TestRateCalendar(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
        self.category = frappe.get_doc('HS Category', {'property': self.prop.name})
        self.day = now_local(self.prop).date() + timedelta(days=2)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def test_daily_amount_uses_the_same_quote_and_keeps_capacity_separate(self):
        result = api.rate_calendar(self.prop.name, self.category.name, str(self.day), days=3)
        self.assertTrue(result['read_only'])
        self.assertEqual((result['property'], result['category'], result['days']),
                         (self.prop.name, self.category.name, 3))
        row = result['rows'][0]
        start = to_site(datetime.combine(self.day, time(14)), self.prop)
        end = to_site(datetime.combine(self.day + timedelta(days=1), time(11)), self.prop)
        quote = pricing.quote(self.prop, self.category.name, start, end, 1, mode='Hotel')
        self.assertEqual((row['amount'], row['currency'], row['rate']),
                         (quote['amount'], quote['currency'], quote['rules']['name']))
        self.assertGreaterEqual(row['available'], 0)

    def test_no_rate_is_distinct_from_inventory_and_invalid_inputs_are_rejected(self):
        rates = frappe.get_all('HS Rate', filters={'property': self.prop.name, 'category': self.category.name}, pluck='name')
        with operation():
            for name in rates:
                doc = frappe.get_doc('HS Rate', name)
                doc.active = 0
                doc.change_reason = 'Prueba de tarifa no disponible'
                doc.save()
        row = api.rate_calendar(self.prop.name, self.category.name, str(self.day), days=1)['rows'][0]
        self.assertEqual(row['rate_status'], 'no_rate')
        self.assertIsNone(row['amount'])
        self.assertIn('available', row)
        for args in ({'days': 32}, {'days': 0}, {'people': self.category.capacity + 1}, {'from_date': '2026-02-30'},
                     {'from_date': '9999-12-31'}, {'mode': 'Por tiempo'}):
            with self.assertRaises(frappe.ValidationError):
                api.rate_calendar(self.prop.name, self.category.name, **{'from_date': str(self.day), **args})

    def test_property_and_guest_boundaries_apply_before_rate_reads(self):
        other = frappe.get_doc('HS Property', {'property_name': 'Luna Demo · Por tiempo'})
        foreign = frappe.get_doc('HS Category', {'property': other.name})
        with self.assertRaises(frappe.PermissionError):
            api.rate_calendar(self.prop.name, foreign.name, str(self.day))
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):
            api.rate_calendar(self.prop.name, self.category.name, str(self.day))

    def test_priority_collision_and_wrong_currency_are_visible_without_a_price(self):
        base=frappe.get_doc('HS Rate',{'property':self.prop.name,'category':self.category.name,'active':1})
        duplicate=frappe.copy_doc(base)
        duplicate.title='Otra tarifa con igual prioridad'
        with operation():
            duplicate.insert()
        row=api.rate_calendar(self.prop.name,self.category.name,str(self.day),days=1)['rows'][0]
        self.assertEqual(row['rate_status'],'collision')
        self.assertIsNone(row['amount'])
        with operation():
            duplicate.active=0
            duplicate.change_reason='Desactivar duplicado de prueba'
            duplicate.save()
            base=frappe.get_doc('HS Rate',base.name)
            base.currency='USD'
            base.change_reason='Probar tarifa en otra moneda'
            base.save()
        row=api.rate_calendar(self.prop.name,self.category.name,str(self.day),days=1)['rows'][0]
        self.assertEqual(row['rate_status'],'wrong_currency')
        self.assertIsNone(row['amount'])
