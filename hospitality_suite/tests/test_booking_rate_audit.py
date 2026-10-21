"""Acceptance gaps found while reviewing specification sections 6–8.

These use native documents and transactions; they do not seed or commit data.
"""
from datetime import datetime, timedelta
import json
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.pricing import quote
from hospitality_suite.printing import hs_account_context, hs_money
from hospitality_suite.service import operation
from hospitality_suite.time import aware, to_site
from hospitality_suite.timing import arrival


class TestBookingRateAudit(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
        self.room = frappe.get_doc('HS Room', {'property': self.prop.name, 'room_number': 'H101'})
        self.guest = frappe.get_doc('HS Guest', {'property': self.prop.name})
        self.now = now_datetime().replace(microsecond=0)
        with operation():
            self.category = frappe.get_doc(dict(doctype='HS Category', property=self.prop.name,
                company=self.prop.company, category_name='Tarifas auditadas ' + uuid.uuid4().hex[:8],
                capacity=4, max_extra_beds=1)).insert()

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def command(self, action, data):
        return api.execute(self.prop.name, action, uuid.uuid4().hex, data)

    def rate(self, **values):
        data = dict(doctype='HS Rate', property=self.prop.name, company=self.prop.company,
            category=self.category.name, title='Tarifa sintética ' + uuid.uuid4().hex[:8],
            mode='Hotel', currency='NIO', amount=1500, block_hours=3, rounding_minutes=15,
            included_people=2, priority=10, active=1)
        data.update(values)
        with operation():
            return frappe.get_doc(data).insert()

    def price(self, start, end, **values):
        return quote(self.prop, self.category.name, to_site(start, self.prop), to_site(end, self.prop), **values)

    def enter(self, **values):
        data = dict(starts_at=str(self.now), ends_at=str(self.now + timedelta(days=2)),
            guest=self.guest.name, customer=self.guest.customer,
            rooms=[dict(category=self.room.category, room=self.room.name, people=1)])
        data.update(values)
        data['acceptance'] = api.preview(self.prop.name, data)['acceptance']
        return self.command('walk_in', data)

    def test_season_weekday_payer_plan_and_priority_have_one_winner_per_night(self):
        # Monday's seasonal/occupancy price and Tuesday's negotiated plan differ.
        base = self.rate(additional_person_rate=50, extra_bed_rate=200)
        monday = self.rate(amount=1800, additional_person_rate=50, extra_bed_rate=200,
            priority=20, weekdays='0', valid_from='2026-12-28', valid_to='2026-12-28')
        negotiated = self.rate(amount=1200, priority=20, customer=self.guest.customer,
            valid_from='2026-12-29', valid_to='2026-12-29',
            included_services=[dict(item='HS-DEMO-WATER', quantity=1, basis='Night')])
        start, end = '2026-12-28 14:00:00', '2026-12-30 12:00:00'
        result = self.price(start, end, people=3, extra_beds=1, customer=self.guest.customer)
        self.assertEqual([r['rules']['name'] for r in result['nightly']], [monday.name, negotiated.name])
        self.assertEqual([r['amount'] for r in result['nightly']], ['2050.00', '1200.00'])
        self.assertEqual(result['amount'], '3250.00')
        self.assertEqual(result['included_services'], [dict(item='HS-DEMO-WATER', quantity='1.0')])
        without_contract = self.price(start, end, people=3, extra_beds=1)
        self.assertEqual([r['rules']['name'] for r in without_contract['nightly']], [monday.name, base.name])
        self.assertEqual(without_contract['amount'], '3800.00')
        # Equal priority prefers this payer's agreement over the general rate.
        with operation():
            negotiated.valid_from = '2026-12-28'
            negotiated.change_reason='Cambio de vigencia sintético para probar la prioridad'
            negotiated.save()
        self.assertEqual(self.price(start, end, customer=self.guest.customer)['amount'], '2400.00')
        self.rate(amount=999, priority=20, customer=self.guest.customer,
            valid_from='2026-12-28', valid_to='2026-12-29')
        with self.assertRaisesRegex(frappe.ValidationError, 'misma prioridad'):
            self.price(start, end, customer=self.guest.customer)

    def test_motel_blocks_fraction_boundaries_and_night_window(self):
        with operation():
            self.prop.mode = 'Mixed'
            self.prop.save()
        for hours in (2, 3, 6, 12, 24):
            rate = self.rate(mode='Motel', amount=400, block_hours=hours,
                extra_hour_rate=120, grace_minutes=10, priority=1)
            start = datetime(2026, 12, 31, 22)
            for minutes, seconds, expected in ((0, 0, '400.00'), (10, 0, '400.00'),
                    (10, 1, '430.00'), (25, 0, '430.00'), (25, 1, '460.00')):
                end = start + timedelta(hours=hours, minutes=minutes, seconds=seconds)
                with self.subTest(block=hours, minutes=minutes, seconds=seconds):
                    self.assertEqual(self.price(start, end, mode='Motel', rate_name=rate.name)['amount'], expected)
        regular = self.rate(mode='Motel', amount=450, priority=10)
        night = self.rate(mode='Motel', amount=600, block_hours=12, priority=20,
            night_start='21:00:00', night_end='06:00:00')
        for clock, expected in (('20:59:59', regular.name), ('21:00:00', night.name),
                ('05:59:59', night.name), ('06:00:00', regular.name)):
            start = datetime.fromisoformat('2026-12-31T' + clock)
            with self.subTest(clock=clock):
                self.assertEqual(self.price(start, start + timedelta(hours=2), mode='Motel')['rules']['name'], expected)

    def test_active_mode_change_requires_mixed_property_and_accepted_new_price(self):
        motel_rate = self.rate(category=self.room.category, mode='Motel', amount=450, block_hours=24)
        # Keep both operations on the same calendar night even when the suite
        # itself starts in the last minute before midnight.
        self.now = self.now.replace(hour=10, minute=0, second=0)
        with patch('hospitality_suite.operations.now_datetime', return_value=self.now), \
                patch('hospitality_suite.timing.now_datetime', return_value=self.now):
            entered = self.enter(ends_at=str(self.now + timedelta(days=1)))
        stay = frappe.get_doc('HS Stay', entered['stay'])
        target = frappe.get_doc('HS Room', {'property': self.prop.name, 'room_number': 'H102'})
        values = dict(stay=stay.name, room=target.name, mode='Motel', folio=entered['folio'],
            modified=str(stay.modified), reason='Cambio explícito de modalidad sintético')
        with self.assertRaisesRegex(frappe.ValidationError, 'no permite esa modalidad'):
            api.preview(self.prop.name, values, 'change_room')
        with operation():
            self.prop.mode = 'Mixed'
            self.prop.save()
        with patch('hospitality_suite.operations.now_datetime', return_value=self.now + timedelta(minutes=1)):
            proposal = api.preview(self.prop.name, values, 'change_room')
            self.assertEqual(proposal['difference'], '-1050.00')
            self.assertEqual(proposal['quote']['rules']['name'], motel_rate.name)
            with self.assertRaises(frappe.ValidationError):
                self.command('change_room', values)
            values['acceptance'] = proposal['acceptance']
            self.command('change_room', values)
        stay.reload()
        self.assertEqual((stay.status, stay.amount, stay.room), ('Active', 450, target.name))
        self.assertEqual(json.loads(stay.quote_snapshot)['rules']['mode'], 'Motel')
        segments = frappe.get_all('HS Allocation', filters={'stay': stay.name}, fields=['*'], order_by='creation')
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].ends_at, segments[1].starts_at)
        self.assertEqual(json.loads(segments[0].quote_snapshot)['rules']['mode'], 'Hotel')
        self.assertEqual(sum(r.amount for r in frappe.get_all('HS Charge', filters={'stay': stay.name}, fields=['amount'])), 450)

    def test_hotel_early_arrival_exact_grace_and_fraction_boundaries(self):
        self.rate()
        self.prop.check_in_time = '14:00:00'
        self.prop.check_out_time = '12:00:00'
        self.prop.early_hour_rate = 120
        self.prop.late_hour_rate = 0
        self.prop.schedule_grace_minutes = 10
        self.prop.schedule_rounding_minutes = 30
        booking = frappe._dict(starts_at=to_site('2026-12-31 14:00:00', self.prop),
            ends_at=to_site('2027-01-01 12:00:00', self.prop))
        accepted = self.price('2026-12-31 14:00:00', '2027-01-01 12:00:00')
        for clock, expected in (('13:50:00', '0.00'), ('13:49:59', '60.00'),
                ('13:20:00', '60.00'), ('13:19:59', '120.00'), ('14:00:00', '0.00')):
            with self.subTest(clock=clock):
                fees = arrival(self.prop, booking, accepted, at=to_site('2026-12-31 ' + clock, self.prop))
                self.assertEqual(fees['early'], expected)

    def test_calendar_month_year_and_dst_use_calendar_nights_and_explicit_instants(self):
        self.rate()
        self.prop.time_zone = 'America/New_York'
        for start, end in (('2026-11-30 14:00:00', '2026-12-02 12:00:00'),
                ('2026-12-31 14:00:00', '2027-01-02 12:00:00'),
                ('2026-03-07 14:00:00', '2026-03-09 12:00:00'),
                ('2026-10-31 14:00:00', '2026-11-02 12:00:00')):
            with self.subTest(start=start):
                result = self.price(start, end)
                self.assertEqual((result['units'], result['amount']), (2, '3000.00'))
        for clock in ('2026-03-08 02:30:00', '2026-11-01 01:30:00'):
            with self.assertRaisesRegex(frappe.ValidationError, 'ambigua o inexistente'):
                aware(clock, self.prop.time_zone)
        first = to_site('2026-11-01T01:30:00-04:00', self.prop)
        second = to_site('2026-11-01T01:30:00-05:00', self.prop)
        self.assertEqual(second - first, timedelta(hours=1))

    def test_printed_account_includes_native_tax_discount_services_payment_and_guarantee(self):
        parent = frappe.db.get_value('Account', {'company': self.prop.company, 'root_type': 'Liability', 'is_group': 1})
        account = frappe.get_doc(dict(doctype='Account', company=self.prop.company,
            account_name='Impuesto cuenta sintética ' + uuid.uuid4().hex[:8], parent_account=parent,
            account_type='Tax', account_currency='NIO')).insert()
        template = frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',
            title='Cuenta sintética ' + uuid.uuid4().hex[:8], company=self.prop.company,
            taxes=[dict(charge_type='On Net Total', account_head=account.name, description='Impuesto sintético',
                rate=15, cost_center=self.prop.cost_center)])).insert()
        with operation():
            self.prop.tax_template = template.name
            self.prop.save()
        entered = self.enter()
        source = frappe.db.get_value('HS Charge', {'stay': entered['stay'], 'kind': 'Lodging'})
        self.command('adjustment', dict(charge=source, adjustment_type='Discount', amount=100, reason='Descuento sintético'))
        service = self.command('request_service', dict(stay=entered['stay'], folio=entered['folio'], item='HS-DEMO-WATER', quantity=1))
        request = frappe.get_doc('HS Service Request', service['service'])
        self.command('update_service', dict(service=request.name, status='Delivered', modified=str(request.modified)))
        invoice = self.command('invoice', dict(folio=entered['folio']))['invoice']
        shift = self.command('open_shift', dict(opening_amount=0))['shift']
        method = frappe.db.get_value('HS Payment Method', {'property': self.prop.name, 'is_cash': 1})
        for kind, amount in (('Payment', 500), ('Guarantee', 200)):
            self.command('payment', dict(stay=entered['stay'], folio=entered['folio'], shift=shift,
                method=method, kind=kind, amount=amount))
        context = hs_account_context(entered['stay'])
        native = next(r for r in context['invoices'] if r.name == invoice)
        self.assertEqual((native.net_total, native.total_taxes_and_charges, native.grand_total,
            native.outstanding_amount), (2930, 439.5, 3369.5, 2870))
        # ERPNext's configured whole-currency rounding makes the payable 3370.
        invoice_doc = frappe.get_doc('Sales Invoice', invoice)
        self.assertEqual((invoice_doc.rounded_total, invoice_doc.rounding_adjustment), (3370, .5))
        self.assertEqual({r.kind for r in context['payments']}, {'Payment', 'Guarantee'})
        self.assertEqual(context['folios'][0].balance['outstanding'], '2870.00')
        html = frappe.get_print('HS Stay', entered['stay'], print_format='HS Cuenta de estancia', as_pdf=False)
        for amount in (3000, -100, 30, 2930, 439.5, 3369.5, 500, 200, 2870):
            self.assertIn(hs_money(amount, 'NIO'), html)
        for heading in ('Facturas y notas de crédito', 'Cobros, anticipos y garantías', 'Cuentas y saldo'):
            self.assertIn(heading, html)

    def test_after_checkout_credit_requires_permission_reason_native_return_and_audit(self):
        entered = self.enter(ends_at=str(self.now + timedelta(days=1)))
        shift = self.command('open_shift', dict(opening_amount=0))['shift']
        method = frappe.db.get_value('HS Payment Method', {'property': self.prop.name, 'is_cash': 1})
        paid = self.command('payment', dict(stay=entered['stay'], folio=entered['folio'], shift=shift,
            method=method, kind='Payment', amount=1500))
        invoice = frappe.get_doc('Payment Entry', paid['payment_entry']).references[0].reference_name
        stay = frappe.get_doc('HS Stay', entered['stay'])
        self.command('check_out', dict(stay=stay.name, modified=str(stay.modified)))
        frappe.set_user('receptionist@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):
            self.command('credit_note', dict(invoice=invoice, reason='Corrección posterior sintética'))
        frappe.set_user('manager@hospitality.example.invalid')
        with self.assertRaises(frappe.ValidationError):
            self.command('credit_note', dict(invoice=invoice))
        reason = 'Corrección posterior sintética autorizada'
        result = self.command('credit_note', dict(invoice=invoice, reason=reason))
        credit = frappe.get_doc('Sales Invoice', result['credit_note'])
        self.assertEqual((credit.docstatus, credit.is_return, credit.return_against, credit.grand_total), (1, 1, invoice, -1500))
        self.assertEqual(frappe.db.get_value('HS Stay', stay.name, 'status'), 'Checked Out')
        event = frappe.get_doc('HS Audit Event', {'action': 'Credit note', 'source_name': entered['folio']})
        self.assertEqual((event.reason, event.actor), (reason, 'manager@hospitality.example.invalid'))
        self.assertEqual(json.loads(event.details)['credit_note'], credit.name)
