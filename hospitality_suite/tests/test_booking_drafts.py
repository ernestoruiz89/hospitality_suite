"""Draft persistence, current-price confirmation and absence of operational effects."""
from datetime import timedelta
import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import canonical, insert, operation


class TestBookingDrafts(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop = frappe.get_doc('HS Property', {'property_name':'Hotel Jardín Demo'})
        self.room = frappe.get_doc('HS Room', {'property':self.prop.name,'room_number':'H101'})
        self.guest = frappe.get_doc('HS Guest', {'property':self.prop.name})
        self.start = now_datetime().replace(microsecond=0) + timedelta(days=3)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def command(self, action, data, key=None, prop=None):
        return api.execute(prop or self.prop.name, action, key or uuid.uuid4().hex, data)

    def values(self, **changes):
        result = dict(mode='Hotel', starts_at=str(self.start), ends_at=str(self.start+timedelta(days=1)),
            guest=self.guest.name, customer=self.guest.customer,
            rooms=[dict(category=self.room.category,room=self.room.name,people=1,extra_beds=0)])
        result.update(changes)
        return result

    def draft(self, values=None, key=None):
        return self.command('save_booking_draft', dict(values=values or {}), key)

    def review(self, draft, values=None):
        data = dict(booking=draft['booking'], modified=draft['modified'])
        if values is not None:
            data['values'] = values
        return api.preview(self.prop.name, data, 'confirm_booking_draft')

    def confirm(self, draft, values=None, key=None):
        quote = self.review(draft, values)
        data = dict(booking=draft['booking'], modified=draft['modified'], draft_acceptance=quote['draft_acceptance'])
        if values is not None:
            data['values'] = values
        return self.command('confirm_booking_draft', data, key)

    def unchanged_operations(self):
        return {dt:canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True))
            for dt in ('HS Allocation','HS Stay','HS Folio','HS Charge','HS Payment','HS Shift','HS Daily Close',
                'Sales Invoice','Payment Entry','Journal Entry','GL Entry','Stock Ledger Entry')}

    def test_partial_draft_round_trip_preserves_incomplete_data_without_duplicate_personal_text(self):
        before = self.unchanged_operations()
        result = self.draft(dict(starts_at=str(self.start), instructions='Nota sintética parcial',
            rooms=[dict(category=self.room.category, people=None, extra_beds=0)], amount=99999, currency='USD', status='Confirmed'))
        booking = frappe.get_doc('HS Booking', result['booking'])
        self.assertEqual((booking.status, booking.amount, booking.currency), ('Draft',0,'NIO'))
        self.assertFalse(booking.customer or booking.guest or booking.ends_at or booking.quote_snapshot or booking.rooms)
        detail = api.booking_detail(booking.name)['draft']
        self.assertEqual(detail['instructions'], 'Nota sintética parcial')
        self.assertIsNone(detail['rooms'][0]['people'])
        self.assertNotIn('instructions',json.loads(booking.draft_data))
        self.assertNotIn('guest',json.loads(booking.draft_data))
        self.assertNotIn('amount',json.loads(booking.draft_data))
        self.assertEqual(self.unchanged_operations(), before)
        self.assertEqual(api.stay_board(self.prop.name, str(self.start.date()), 'arrivals')['total'],0)

    def test_save_retry_is_one_draft_and_edits_require_the_current_version(self):
        key = uuid.uuid4().hex
        first = self.draft(dict(instructions='Inicial'),key)
        self.assertEqual(self.draft(dict(instructions='Inicial'),key), first)
        self.assertEqual(frappe.db.count('HS Booking'),1)
        with self.assertRaises(frappe.ValidationError):
            self.draft(dict(instructions='Cambiado'),key)
        # Frappe 16 disables Version writes in tests by default. Exercise the
        # production save path here, without changing application flags.
        with patch.object(frappe, 'in_test', False):
            changed = self.command('save_booking_draft', dict(booking=first['booking'],modified=first['modified'],values=dict(instructions='Editado')))
        self.assertEqual(changed['booking'],first['booking'])
        with self.assertRaises(frappe.TimestampMismatchError):
            self.command('save_booking_draft',dict(booking=first['booking'],modified=first['modified'],values={}))
        self.assertEqual(api.booking_detail(first['booking'])['draft']['instructions'],'Editado')
        self.assertTrue(frappe.db.exists('Version',{'ref_doctype':'HS Booking','docname':first['booking']}))

    def test_review_is_read_only_and_confirmation_keeps_the_same_record_and_retries(self):
        draft = self.draft(dict(instructions='Pendiente de completar'))
        values = self.values()
        before = self.unchanged_operations()
        stored = canonical(frappe.get_doc('HS Booking',draft['booking']).as_dict())
        one = self.review(draft,values)
        self.assertEqual(self.review(draft,values)['draft_acceptance'],one['draft_acceptance'])
        self.assertEqual(one['amount'],'1500.00')
        self.assertEqual(self.unchanged_operations(),before)
        self.assertEqual(canonical(frappe.get_doc('HS Booking',draft['booking']).as_dict()),stored)
        data = dict(booking=draft['booking'],modified=draft['modified'],values=values,draft_acceptance=one['draft_acceptance'])
        key = uuid.uuid4().hex
        result = self.command('confirm_booking_draft',data,key)
        self.assertEqual(self.command('confirm_booking_draft',data,key),result)
        doc = frappe.get_doc('HS Booking',draft['booking'])
        self.assertEqual((doc.status,doc.amount,len(doc.rooms)),('Confirmed',1500,1))
        self.assertFalse(doc.draft_data)
        self.assertEqual(frappe.db.count('HS Booking'),1)
        self.assertEqual(frappe.db.count('HS Allocation',{'booking':doc.name,'status':'Active'}),1)
        self.assertEqual(frappe.db.count('HS Stay'),0)

    def test_changed_master_price_requires_review_and_does_not_reprice_the_saved_draft(self):
        draft = self.draft(self.values())
        quote = self.review(draft)
        rate = frappe.get_doc('HS Rate',{'property':self.prop.name,'category':self.room.category,'mode':'Hotel'})
        with operation():
            rate.amount = 2000
            rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        with self.assertRaises(frappe.ValidationError):
            self.command('confirm_booking_draft',dict(booking=draft['booking'],modified=draft['modified'],draft_acceptance=quote['draft_acceptance']))
        self.assertEqual(frappe.db.get_value('HS Booking',draft['booking'],'status'),'Draft')
        self.assertEqual(frappe.db.get_value('HS Booking',draft['booking'],'amount'),0)
        self.assertEqual(frappe.db.count('HS Allocation'),0)
        self.confirm(draft)
        self.assertEqual(frappe.db.get_value('HS Booking',draft['booking'],'amount'),2000)

    def test_a_conflicting_room_does_not_prevent_saving_but_blocks_confirmation(self):
        values = self.values()
        draft = self.draft(values)
        other = dict(values,acceptance=api.preview(self.prop.name,values)['acceptance'])
        self.command('reserve',other)
        with self.assertRaises(frappe.ValidationError):
            self.review(draft)
        self.command('save_booking_draft',dict(booking=draft['booking'],modified=draft['modified'],values=dict(values,instructions='Sigue pendiente')))
        self.assertEqual(frappe.db.count('HS Allocation',{'booking':draft['booking']}),0)
        self.assertEqual(frappe.db.count('HS Booking'),2)

    def test_hold_and_metadata_are_bound_to_the_review_before_the_existing_hold_flow(self):
        values = self.values(hold=True)
        draft = self.draft(values)
        quote = self.review(draft)
        with self.assertRaises(frappe.ValidationError):
            self.command('confirm_booking_draft',dict(booking=draft['booking'],modified=draft['modified'],
                values=dict(values,hold=False),draft_acceptance=quote['draft_acceptance']))
        held = self.confirm(draft)
        doc = frappe.get_doc('HS Booking',held['booking'])
        self.assertEqual(doc.status,'Hold')
        self.assertGreater(doc.hold_until,now_datetime())
        self.command('booking_status',dict(booking=doc.name,modified=str(doc.modified),status='Confirmed'))
        self.assertEqual(frappe.db.get_value('HS Booking',doc.name,'status'),'Confirmed')

    def test_generic_status_edit_and_entry_cannot_bypass_draft_confirmation(self):
        draft = self.draft(self.values())
        for action,values in (
            ('booking_status',dict(status='Confirmed')),
            ('booking_status',dict(status='No Show',reason='No debe generar cargo')),
            ('check_in',dict(guest=self.guest.name))):
            with self.subTest(action=action),self.assertRaises(frappe.ValidationError):
                self.command(action,dict(booking=draft['booking'],modified=draft['modified'],**values))
        with self.assertRaises(frappe.ValidationError):
            api.preview(self.prop.name,dict(booking=draft['booking']),'modify_reservation')
        self.assertEqual(frappe.db.count('HS Allocation'),0)
        self.assertEqual(frappe.db.count('Sales Invoice'),0)

    def test_discard_incomplete_draft_has_reason_audit_and_no_cancellation_penalty(self):
        with operation():
            self.prop.cancellation_fee_mode='Fixed'
            self.prop.cancellation_fee_value=100
            self.prop.penalty_item=self.prop.lodging_item
            self.prop.save()
        draft = self.draft(dict(instructions='Borrador sin fechas ni pagador'))
        before = self.unchanged_operations()
        with self.assertRaises(frappe.ValidationError):
            self.command('discard_booking_draft',dict(booking=draft['booking'],modified=draft['modified']))
        self.command('discard_booking_draft',dict(booking=draft['booking'],modified=draft['modified'],reason='Solicitud no continuada'))
        doc = frappe.get_doc('HS Booking',draft['booking'])
        self.assertEqual((doc.status,doc.reason),('Cancelled','Solicitud no continuada'))
        self.assertTrue(doc.draft_data)
        self.assertEqual(self.unchanged_operations(),before)
        self.assertFalse(api.report(self.prop.name,'Cancelaciones y no presentaciones'))
        self.assertTrue(frappe.db.exists('HS Audit Event',{'action':'Discard booking draft','source_name':doc.name}))

    def test_financial_documents_cannot_reference_an_unconfirmed_draft(self):
        draft = self.draft(self.values())
        shift = self.command('open_shift',dict(opening_amount=0))['shift']
        method = frappe.db.get_value('HS Payment Method',{'property':self.prop.name})
        for kind in ('Advance','Guarantee'):
            with self.subTest(kind=kind),self.assertRaises(frappe.ValidationError):
                self.command('payment',dict(booking=draft['booking'],shift=shift,method=method,kind=kind,amount=100))
        invoice = frappe.get_doc(dict(doctype='Sales Invoice',company=self.prop.company,customer=self.guest.customer,
            currency=self.prop.currency,party_account_currency=self.prop.currency,
            hs_property=self.prop.name,hs_booking=draft['booking'],debit_to=self.prop.receivable_account,
            items=[dict(item_code=self.prop.lodging_item,qty=1,rate=1500,cost_center=self.prop.cost_center)]))
        with self.assertRaisesRegex(frappe.ValidationError,'borrador de reserva'):
            invoice.insert()
        self.assertEqual(frappe.db.count('Payment Entry'),0)
        self.assertEqual(frappe.db.count('Journal Entry'),0)
        self.assertEqual(frappe.db.count('Sales Invoice'),0)

    def test_partial_permissions_and_scope_do_not_relax_confirmed_or_direct_write_rules(self):
        for user in ('housekeeping@hospitality.example.invalid','cashier@hospitality.example.invalid',
                'accountant@hospitality.example.invalid','auditor@hospitality.example.invalid','Guest'):
            frappe.set_user(user)
            with self.subTest(user=user),self.assertRaises(frappe.PermissionError):
                self.draft()
        frappe.set_user('receptionist@hospitality.example.invalid')
        draft = self.draft()
        foreign = frappe.db.get_value('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        with self.assertRaises(frappe.PermissionError):
            self.command('save_booking_draft',dict(booking=draft['booking'],modified=draft['modified'],values={}),prop=foreign)
        room = frappe.db.get_value('HS Room',{'property':foreign})
        with self.assertRaises(frappe.PermissionError):
            self.draft(dict(rooms=[dict(room=room)]))
        frappe.set_user('Administrator')
        with operation(),self.assertRaises(frappe.ValidationError):
            insert('HS Booking',self.prop,status='Confirmed',currency='NIO',amount=0)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(dict(doctype='HS Booking',property=self.prop.name,company=self.prop.company,
                status='Draft',currency='NIO',amount=0)).insert()

    def test_offset_dates_survive_draft_round_trip_and_zero_people_cannot_be_confirmed(self):
        with operation():
            self.prop.time_zone='America/New_York'
            self.prop.save()
        values = self.values(starts_at='2026-11-01T01:30:00-04:00',ends_at='2026-11-01T01:30:00-05:00')
        draft = self.draft(values)
        detail = api.booking_detail(draft['booking'])['draft']
        self.assertTrue(detail['starts_at'].endswith('-04:00'))
        self.assertTrue(detail['ends_at'].endswith('-05:00'))
        self.confirm(draft)
        doc = frappe.get_doc('HS Booking',draft['booking'])
        self.assertEqual(doc.ends_at-doc.starts_at,timedelta(hours=1))
        values['rooms'][0]['people']=0
        second = self.draft(values)
        with self.assertRaisesRegex(frappe.ValidationError,'entero mayor que cero'):
            self.review(second)

    def test_incomplete_print_is_a_draft_and_guest_can_be_selected_only_at_entry(self):
        partial = self.draft()
        html = frappe.get_print('HS Booking',partial['booking'],print_format='HS Confirmación de reserva',as_pdf=False)
        self.assertIn('BORRADOR DE RESERVA',html)
        self.assertIn('Precio pendiente de cotizar',html)
        self.assertNotIn('CONFIRMACIÓN DE RESERVA',html)
        values = self.values(guest=None,starts_at=str(now_datetime().replace(microsecond=0)))
        values['ends_at']=str(now_datetime().replace(microsecond=0)+timedelta(days=1))
        confirmed = self.confirm(partial,values)
        with self.assertRaisesRegex(frappe.ValidationError,'huésped principal'):
            self.command('check_in',dict(booking=confirmed['booking'],modified=confirmed['modified']))
        entered = self.command('check_in',dict(booking=confirmed['booking'],modified=confirmed['modified'],guest=self.guest.name))
        self.assertEqual(frappe.db.get_value('HS Stay',entered['stay'],'guest'),self.guest.name)
