"""Real native documents and authorized installed operational print formats."""
from datetime import timedelta
import hashlib
from html import unescape
import json
from pathlib import Path
import uuid

from bs4 import BeautifulSoup
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation
from hospitality_suite.time import local


FORMATS = {
    'reservation': ('HS Booking', 'HS Confirmación de reserva', 'receptionist'),
    'registration': ('HS Stay', 'HS Registro de huésped', 'receptionist'),
    'folio': ('HS Stay', 'HS Cuenta de estancia', 'receptionist'),
    'invoice': ('Sales Invoice', 'HS Factura', 'cashier'),
    'receipt': ('HS Payment', 'HS Recibo', 'cashier'),
    'shift': ('HS Shift', 'HS Arqueo', 'cashier'),
    'cleaning': ('HS Cleaning Task', 'HS Orden de limpieza', 'housekeeping'),
    'maintenance': ('HS Maintenance Order', 'HS Orden de mantenimiento', 'maintenance'),
    'daily_close': ('HS Daily Close', 'HS Cierre diario', 'manager'),
}


def make_scenario():
    """Synthetic API scenario only; caller owns rollback and the designated site."""
    assert frappe.local.site == 'hospitality-acceptance.localhost'
    assert frappe.conf.allow_tests and frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
    frappe.set_user('Administrator')
    prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
    now = now_datetime().replace(microsecond=0)
    with operation():
        prop.business_date = local(now, prop).date()
        prop.close_time = '00:00:00'
        prop.save()
    rooms = frappe.get_all('HS Room', filters={'property': prop.name}, fields=['name', 'category'], order_by='room_number')
    guest = frappe.get_doc('HS Guest', {'property': prop.name})
    call = lambda action, data: api.execute(prop.name, action, uuid.uuid4().hex, data)
    values = dict(starts_at=str(now), ends_at=str(now+timedelta(days=1)), customer=guest.customer, guest=guest.name,
                  rooms=[dict(category=rooms[0].category, room=rooms[0].name, people=2)])
    booked = call('reserve', dict(values, acceptance=api.preview(prop.name, values)['acceptance']))
    entered = call('check_in', dict(booking=booked['booking'], modified=booked['modified'], guest=guest.name))
    invoice = call('invoice', dict(folio=entered['folio']))['invoice']
    shift = call('open_shift', dict(opening_amount=0))['shift']
    method = frappe.db.get_value('HS Payment Method', {'property': prop.name, 'is_cash': 1, 'currency': 'NIO'})
    payment = call('payment', dict(stay=entered['stay'], folio=entered['folio'], shift=shift, method=method,
                                   kind='Payment', amount=500))['payment']
    task = call('schedule_cleaning', dict(room=rooms[1].name, kind='Deep', priority='High',
                                        assigned_to='housekeeping@hospitality.example.invalid', notes='Revisar baño y ropa'))['task']
    order = call('maintenance', dict(room=rooms[2].name, title='Revisión preventiva de aire acondicionado', kind='Preventive',
                                    starts_at=str(now+timedelta(days=3)), ends_at=str(now+timedelta(days=3, hours=2)),
                                    assigned_to='maintenance@hospitality.example.invalid'))['order']
    shift_doc = frappe.get_doc('HS Shift', shift)
    call('close_shift', dict(shift=shift, modified=str(shift_doc.modified), denominations={'NIO': [dict(value=100, count=5)]}))
    review = call('daily_close', dict(confirm=False))
    assert not review['blockers'], review['blockers']
    close = call('daily_close', dict(confirm=True, review_acceptance=review['review_acceptance']))['close']
    return dict(property=prop.name, customer=guest.customer, folio_name=entered['folio'],
                reservation=booked['booking'], registration=entered['stay'], folio=entered['stay'], invoice=invoice,
                receipt=payment, shift=shift, cleaning=task, maintenance=order, daily_close=close)


def fingerprints():
    result = {}
    for doctype in ['HS Booking', 'HS Stay', 'HS Folio', 'HS Charge', 'HS Payment', 'HS Shift', 'HS Cleaning Task',
                    'HS Maintenance Order', 'HS Daily Close', 'Sales Invoice', 'Payment Entry', 'Journal Entry',
                    'GL Entry', 'Payment Ledger Entry', 'Stock Ledger Entry']:
        rows = frappe.db.sql('SELECT * FROM `tab'+doctype+'` ORDER BY name', as_dict=True)
        result[doctype] = hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()
    return result


class TestPrintDelivery(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        self.scenario = make_scenario()
        frappe.local.lang = 'es'

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def text(self, slug, doc=None):
        doctype, fmt, actor = FORMATS[slug]
        frappe.set_user(actor+'@hospitality.example.invalid')
        html = frappe.get_print(doctype, self.scenario[slug], print_format=fmt, doc=doc)
        return BeautifulSoup(html, 'html.parser').get_text(' ', strip=True), html

    def test_all_nine_installed_formats_render_for_the_operational_role_without_business_writes(self):
        before = fingerprints()
        for slug in FORMATS:
            source = Path(frappe.get_app_path('hospitality_suite', 'templates', 'print', slug+'.html')).read_text()
            self.assertEqual(frappe.db.get_value('Print Format', FORMATS[slug][1], 'html'), source)
            text, html = self.text(slug)
            self.assertIn('Hotel Jardín Demo', text)
            self.assertNotIn('Traceback', text)
            self.assertNotIn('Cálculo histórico del precio', text)
            self.assertNotIn('hs_charge_sources', text)
            self.assertGreater(len(text), 200)
        self.assertEqual(fingerprints(), before)

    def test_customer_labels_are_escaped_and_compact_account_has_no_historical_calculation(self):
        customer = frappe.get_doc('Customer', self.scenario['customer'])
        customer.customer_name = 'Cliente ficticio <Norte> & acompañantes'
        customer.save()
        customer.reload()
        expected = unescape(customer.customer_name)
        for slug in ['reservation', 'registration', 'receipt', 'folio']:
            text, html = self.text(slug)
            self.assertIn(expected, text)
            self.assertNotIn('&amp;amp;', html)
            self.assertNotIn('<Norte>', html)
        text, _ = self.text('folio')
        for caption in ['Cuentas y saldo', 'Facturas y notas de crédito', 'Cobros, anticipos y garantías', '1,500.00', '500.00', '1,000.00']:
            self.assertIn(caption, text)
        self.assertNotIn('Importe histórico de referencia', text)
        from hospitality_suite.printing import hs_print_text
        self.assertEqual(str(hs_print_text('&lt;img src=x onerror=bad&gt; &amp; Norte')), '&lt;img src=x onerror=bad&gt; &amp; Norte')
        self.assertEqual(hs_print_text(None), '')

    def test_guest_and_wrong_operational_role_cannot_print_financial_or_guest_documents(self):
        before = fingerprints()
        for slug, (doctype, fmt, _) in FORMATS.items():
            frappe.set_user('Guest')
            with self.assertRaises(frappe.PermissionError):
                frappe.get_print(doctype, self.scenario[slug], print_format=fmt)
        frappe.set_user('housekeeping@hospitality.example.invalid')
        for slug in ['registration', 'invoice', 'receipt', 'shift']:
            doctype, fmt, _ = FORMATS[slug]
            with self.assertRaises(frappe.PermissionError):
                frappe.get_print(doctype, self.scenario[slug], print_format=fmt)
        self.assertEqual(fingerprints(), before)

    def test_invoice_presentation_uses_native_payable_rounding_pos_and_party_currency_fields(self):
        # Transient copies prove the print projection for the native field
        # combinations, without changing the submitted invoice or its ledgers.
        original = frappe.get_doc('Sales Invoice', self.scenario['invoice'])
        before = fingerprints()
        for total, rounded in [(60.15, 60), (-60.15, -60), (0, 0)]:
            doc = frappe.get_doc(original.as_dict())
            doc.grand_total, doc.rounded_total = total, rounded
            doc.is_return = int(total < 0)
            doc.paid_amount = rounded if total > 0 else 0
            doc.write_off_amount = 0
            doc.outstanding_amount = 0
            doc.party_account_currency = 'USD'
            text, html = self.text('invoice', doc)
            self.assertIn('Saldo pendiente en ERPNext', text)
            self.assertIn('$ 0.00', text)
            if total:
                self.assertIn('Total antes del redondeo', text)
                self.assertIn('Redondeo', text)
                self.assertIn('NOTA DE CRÉDITO' if total < 0 else 'Cobrado en esta factura', text)
                self.assertIn('60.00', text)
            else:
                self.assertNotIn('Total antes del redondeo', text)
        self.assertEqual(fingerprints(), before)

    def test_configured_formats_are_projected_and_user_owned_format_is_preserved_by_sync(self):
        from hospitality_suite.install import sync_print_formats
        for slug, field in [('invoice', 'invoice_print_format'), ('receipt', 'receipt_print_format')]:
            source = frappe.get_doc('Print Format', FORMATS[slug][1])
            custom = frappe.copy_doc(source)
            custom.name = 'Formato ficticio '+slug+' '+uuid.uuid4().hex[:6]
            custom.standard = 'No'
            custom.html = '<div>Formato local configurado</div>'
            custom.insert()
            prop = frappe.get_doc('HS Property', self.scenario['property'])
            with operation():
                prop.set(field, custom.name)
                prop.save()
            self.assertEqual(api.bootstrap(prop.name)['print_formats'][slug], custom.name)
            sync_print_formats()
            self.assertEqual(frappe.get_doc('Print Format', custom.name).html, custom.html)

    def test_registration_lists_only_companions_and_explains_an_empty_list(self):
        text, _ = self.text('registration')
        self.assertIn('Sin acompañantes registrados.', text)
        frappe.set_user('Administrator')
        stay = frappe.get_doc('HS Stay', self.scenario['registration'])
        other = frappe.get_doc('HS Guest', frappe.db.get_value('HS Guest', {'property': stay.property, 'name': ['!=', stay.guest]}))
        api.execute(stay.property, 'companions', uuid.uuid4().hex, dict(stay=stay.name, modified=str(stay.modified), guests=[other.name]))
        text, _ = self.text('registration')
        self.assertNotIn('Sin acompañantes registrados.', text)
        self.assertEqual(text.count(other.full_name), 1)
        self.assertEqual(text.count(frappe.db.get_value('HS Guest', stay.guest, 'full_name')), 1)
