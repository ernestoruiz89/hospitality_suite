"""Quantity queries must agree with reservation capacity without writing data."""
from datetime import timedelta
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.availability import check
from hospitality_suite.service import canonical, insert, operation


class TestAvailabilitySearch(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
        self.category = frappe.get_doc('HS Category', {'property': self.prop.name})
        self.guest = frappe.get_doc('HS Guest', {'property': self.prop.name})
        self.rooms = frappe.get_all('HS Room', filters={'property': self.prop.name, 'category': self.category.name, 'active': 1}, fields=['name'])
        self.start = now_datetime().replace(microsecond=0)
        self.end = self.start + timedelta(days=1)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def search(self, quantity=1, **values):
        query = dict(property_name=self.prop.name, starts_at=str(self.start), ends_at=str(self.end),
            category=self.category.name, people=1, quantity=quantity)
        query.update(values)
        return api.availability_search(**query)

    def book(self, count):
        values = dict(starts_at=str(self.start), ends_at=str(self.end), customer=self.guest.customer,
            guest=self.guest.name, rooms=[dict(category=self.category.name, people=1) for _ in range(count)])
        values['acceptance'] = api.preview(self.prop.name, values)['acceptance']
        return api.execute(self.prop.name, 'reserve', uuid.uuid4().hex, values)

    def snapshot(self):
        return {dt:canonical(frappe.db.sql('SELECT * FROM `tab' + dt + '` ORDER BY name', as_dict=True))
            for dt in ('HS Booking', 'HS Allocation', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift',
                'HS Request', 'HS Audit Event', 'Sales Invoice', 'Payment Entry', 'Journal Entry', 'GL Entry', 'Version')}

    def test_quantity_and_people_query_is_read_only_and_has_human_room_labels(self):
        before = self.snapshot()
        response = self.search(3, people=2)
        self.assertTrue(response['enough'])
        self.assertEqual((response['available'], response['quantity'], response['people']), (len(self.rooms), 3, 2))
        self.assertEqual(response['category_label'], self.category.category_name)
        self.assertEqual(response['physical_available'], len(self.rooms))
        self.assertFalse(response['needs_assignment_review'])
        self.assertEqual({r.name for r in response['rooms']}, {r.name for r in self.rooms})
        self.assertIn('H101', [r.room_number for r in response['rooms']])
        self.assertTrue(all(r.room_number != r.name for r in response['rooms']))
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('guests', response)

    def test_roomless_group_reduces_quota_and_conversion_does_not_count_twice(self):
        booking = self.book(len(self.rooms) - 1)
        before = self.snapshot()
        response = self.search(2)
        self.assertEqual((response['available'], response['physical_available']), (1, len(self.rooms)))
        self.assertFalse(response['enough'])
        self.assertTrue(self.search(1)['enough'])
        self.assertEqual(self.snapshot(), before)
        api.execute(self.prop.name, 'check_in', uuid.uuid4().hex, dict(booking=booking['booking'],
            modified=booking['modified'], guest=self.guest.name, room=self.rooms[0].name))
        after_entry = self.search(1)
        self.assertEqual((after_entry['available'], after_entry['physical_available']), (1, len(self.rooms) - 1))
        self.assertTrue(after_entry['enough'])
        self.assertEqual(frappe.db.count('HS Allocation', {'booking': booking['booking'], 'status': 'Active'}), len(self.rooms) - 1)

    def test_full_roomless_category_returns_zero_without_a_validation_error(self):
        self.book(len(self.rooms))
        before = self.snapshot()
        response = self.search(1)
        self.assertEqual((response['available'], response['physical_available']), (0, len(self.rooms)))
        self.assertFalse(response['enough'])
        self.assertFalse(response['needs_assignment_review'])
        self.assertEqual(self.snapshot(), before)

    def test_category_capacity_does_not_promise_a_fixed_room_for_the_whole_interval(self):
        with operation():
            self.prop.cleaning_minutes = 0
            self.prop.save()
            step = timedelta(hours=2) / len(self.rooms)
            for index, room in enumerate(self.rooms):
                start = self.start + step * index
                insert('HS Allocation', self.prop, category=self.category.name, room=room.name,
                    starts_at=start, ends_at=start + step, buffer_minutes=0,
                    kind='Reservation', status='Active')
        response = self.search(2, ends_at=str(self.start + timedelta(hours=2)))
        self.assertEqual((response['available'], response['physical_available']), (len(self.rooms) - 1, 0))
        self.assertTrue(response['enough'])
        self.assertTrue(response['needs_assignment_review'])
        self.assertEqual(response['rooms'], [])

    def test_half_open_cleaning_buffer_edges_use_the_shared_capacity_engine(self):
        with operation():
            self.prop.cleaning_minutes = 30
            self.prop.save()
            category = insert('HS Category', self.prop, category_name='Límites consulta ' + uuid.uuid4().hex[:6], capacity=2)
            room = insert('HS Room', self.prop, category=category.name, room_number='QA-BUFFER', active=1, cleaning_status='Clean')
            start = self.start.replace(hour=10, minute=0, second=0) + timedelta(days=2)
            allocation = insert('HS Allocation', self.prop, category=category.name, room=room.name,
                starts_at=start, ends_at=start + timedelta(hours=1), buffer_minutes=30, kind='Reservation', status='Active')
        for offset_start, offset_end, available in ((5399, 8999, 0), (5400, 9000, 1),
                (-3600, -1800, 1), (-3600, -1799, 0)):
            with self.subTest(offset_start=offset_start, offset_end=offset_end):
                result = self.search(1, category=category.name, starts_at=str(start + timedelta(seconds=offset_start)),
                    ends_at=str(start + timedelta(seconds=offset_end)))
                self.assertEqual(result['available'], available)
                self.assertEqual(result['enough'], bool(available))
                begins, finishes = start + timedelta(seconds=offset_start), start + timedelta(seconds=offset_end)
                if available:
                    self.assertIn(room.name, check(self.prop, category.name, begins, finishes, room.name))
                else:
                    with self.assertRaises(frappe.ValidationError):
                        check(self.prop, category.name, begins, finishes, room.name)
        with operation():
            self.prop.cleaning_minutes = 0
            self.prop.save()
            allocation.buffer_minutes = 0
            allocation.save()
        for offset_start, offset_end, available in ((3599, 7199, 0), (3600, 7200, 1),
                (-3600, 0, 1), (-3600, 1, 0)):
            with self.subTest(no_buffer=True, offset_start=offset_start, offset_end=offset_end):
                begins, finishes = start + timedelta(seconds=offset_start), start + timedelta(seconds=offset_end)
                result = self.search(1, category=category.name, starts_at=str(begins), ends_at=str(finishes))
                self.assertEqual(result['available'], available)
                self.assertEqual(result['enough'], bool(available))
                if available:
                    self.assertIn(room.name, check(self.prop, category.name, begins, finishes, room.name))
                else:
                    with self.assertRaises(frappe.ValidationError):
                        check(self.prop, category.name, begins, finishes, room.name)

    def test_invalid_numbers_and_nonpositive_intervals_are_rejected_without_rounding(self):
        for field in ('quantity', 'people'):
            for value in (0, -1, '1.5', 1.5, 'NaN', 'Infinity', '1e50', True, '', None):
                with self.subTest(field=field, value=value), self.assertRaises(frappe.ValidationError):
                    self.search(**{field:value})
        with self.assertRaises(frappe.ValidationError):
            self.search(1, people=self.category.capacity + 1)
        for end in (self.start, self.start - timedelta(seconds=1)):
            with self.assertRaises(frappe.ValidationError):
                self.search(1, ends_at=str(end))

    def test_scope_and_roles_are_enforced_without_exposing_other_property_inventory(self):
        foreign = frappe.db.get_value('HS Property', {'property_name': 'Luna Demo · Por tiempo'})
        category = frappe.db.get_value('HS Category', {'property': foreign})
        with self.assertRaises(frappe.PermissionError):
            self.search(1, category=category)
        with operation():
            private = frappe.copy_doc(self.prop)
            private.property_name = 'Establecimiento sin acceso ' + uuid.uuid4().hex[:6]
            private.insert()
            private_category = insert('HS Category', private, category_name='Categoría sin acceso', capacity=2)
        for user in ('housekeeping@hospitality.example.invalid', 'accountant@hospitality.example.invalid', 'Guest'):
            frappe.set_user(user)
            with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                self.search()
        frappe.set_user('receptionist@hospitality.example.invalid')
        self.assertTrue(self.search(2)['enough'])
        with self.assertRaises(frappe.PermissionError):
            self.search(1, property_name=private.name, category=private_category.name)

    def assigned(self,index=0,enter=False,start=None,end=None):
        values=dict(starts_at=str(start or self.start),ends_at=str(end or self.end),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.category.name,room=self.rooms[index].name,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return api.execute(self.prop.name,'walk_in' if enter else 'reserve',uuid.uuid4().hex,values)

    def state_map(self,**query):
        return {row['name']:row for row in self.search(**query)['room_states']}

    def test_interval_states_distinguish_real_booking_stay_block_and_inactive_room_without_writes(self):
        self.assigned();self.assigned(1,enter=True)
        api.execute(self.prop.name,'maintenance',uuid.uuid4().hex,dict(room=self.rooms[2].name,title='Estado de prueba',starts_at=str(self.start),until_reopened=1))
        room=frappe.get_doc('HS Room',self.rooms[3].name);room.active=0;room.save()
        before=self.snapshot();states=self.state_map()
        self.assertEqual([states[self.rooms[i].name]['status'] for i in range(4)],['Reserved','Occupied','Blocked','Inactive'])
        self.assertTrue(all(row['status']=='Available' for name,row in states.items() if name not in {r.name for r in self.rooms[:4]}))
        self.assertEqual(self.snapshot(),before)

    def test_interval_state_follows_requested_dates_and_native_cancellation(self):
        start=self.start+timedelta(days=3);end=start+timedelta(days=1)
        booked=self.assigned(start=start,end=end);name=self.rooms[0].name
        self.assertEqual(self.state_map()[name]['status'],'Available')
        self.assertEqual(self.state_map(starts_at=str(start),ends_at=str(end))[name]['status'],'Reserved')
        booking=frappe.get_doc('HS Booking',booked['booking'])
        api.execute(self.prop.name,'booking_status',uuid.uuid4().hex,dict(booking=booking.name,modified=str(booking.modified),status='Cancelled',reason='Cancelación sintética para comprobar el intervalo'))
        before=self.snapshot();self.assertEqual(self.state_map(starts_at=str(start),ends_at=str(end))[name]['status'],'Available');self.assertEqual(self.snapshot(),before)

    def test_full_roomless_category_does_not_promise_each_physical_room_as_available(self):
        self.book(len(self.rooms));response=self.search()
        self.assertEqual(response['available'],0);self.assertEqual(response['physical_available'],len(self.rooms))
        self.assertEqual({row['status'] for row in response['room_states']},{'Category Full'})

    def test_buffer_only_conflict_has_its_own_label_and_preserves_exclusive_end(self):
        start=self.start+timedelta(days=3)
        with operation():
            self.prop.cleaning_minutes=30;self.prop.save()
            insert('HS Allocation',self.prop,category=self.category.name,room=self.rooms[0].name,starts_at=start,ends_at=start+timedelta(hours=1),
                   buffer_minutes=30,kind='Reservation',status='Active')
        for minutes,status in ((74,'Buffer'),(90,'Available')):
            states=self.state_map(starts_at=str(start+timedelta(minutes=minutes)),ends_at=str(start+timedelta(hours=3)))
            self.assertEqual(states[self.rooms[0].name]['status'],status)

    def test_open_block_remains_blocked_in_distant_query_until_authorized_reopening(self):
        result=api.execute(self.prop.name,'maintenance',uuid.uuid4().hex,dict(room=self.rooms[0].name,title='Bloqueo sin fecha de fin',starts_at=str(self.start),until_reopened=1))
        future=dict(starts_at=str(self.start+timedelta(days=90)),ends_at=str(self.end+timedelta(days=90)))
        self.assertEqual(self.state_map(**future)[self.rooms[0].name]['status'],'Blocked')
        order=frappe.get_doc('HS Maintenance Order',result['order']);self.assertFalse(order.ends_at)
        api.execute(self.prop.name,'maintenance',uuid.uuid4().hex,dict(order=order.name,modified=str(order.modified),status='Completed'))
        self.assertEqual(self.state_map(**future)[self.rooms[0].name]['status'],'Available')

    def test_cleaning_is_current_information_separate_from_future_physical_availability(self):
        room=frappe.get_doc('HS Room',self.rooms[0].name)
        for cleaning in ('Clean','Dirty','Cleaning','Inspection'):
            with operation():room.cleaning_status=cleaning;room.save()
            states=self.state_map(starts_at=str(self.start+timedelta(days=30)),ends_at=str(self.end+timedelta(days=30)))
            self.assertEqual(states[room.name]['status'],'Available');self.assertEqual(states[room.name]['cleaning_status'],cleaning)

    def test_interval_projection_omits_guest_booking_financial_and_other_property_data(self):
        self.assigned();response=self.search();other=frappe.db.get_value('HS Property',{'mode':'Por tiempo'})
        foreign=set(frappe.get_all('HS Room',filters={'property':other},pluck='name'))
        self.assertFalse(foreign.intersection(row['name'] for row in response['room_states']))
        self.assertTrue(all(set(row)=={'name','room_number','status','label','cleaning_status'} for row in response['room_states']))
        self.assertNotIn(self.guest.name,json.dumps(response['room_states']))
