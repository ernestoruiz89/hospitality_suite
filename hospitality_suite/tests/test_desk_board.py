from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation,canonical


class TestDeskBoard(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category'],order_by='room_number')
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.start=now_datetime().replace(microsecond=0)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def command(self,action,data):return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def reserve(self,indices=(0,),start=None,hold=False,roomless=False):
        values=dict(starts_at=str(start or self.start),ends_at=str((start or self.start)+timedelta(days=1)),guest=self.guest.name,customer=self.guest.customer,
                    hold=hold,rooms=[dict(category=self.rooms[i].category,room=None if roomless else self.rooms[i].name,people=1) for i in indices])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return self.command('reserve',values)

    def enter(self,booking,room=None):
        doc=frappe.get_doc('HS Booking',booking['booking'])
        return self.command('check_in',dict(booking=doc.name,modified=str(doc.modified),guest=self.guest.name,room=room))

    def board(self,view='hosted',date=None,**kwargs):return api.stay_board(self.prop.name,date,view,**kwargs)

    def test_future_arrival_is_not_occupancy_and_bootstrap_has_no_guest_in_card_projection(self):
        future=self.start+timedelta(days=4)
        booking=self.reserve(start=future)
        result=self.board('arrivals',str(future.date()))
        self.assertEqual(result['counts'],dict(hosted=0,arrivals=1,departures=0,accounts=0))
        self.assertEqual(result['rows'][0]['booking'],booking['booking'])
        boot=api.bootstrap(self.prop.name)
        self.assertEqual(boot['occupied'],[])
        self.assertEqual(len(boot['room_arrivals']),1)
        self.assertEqual(set(boot['room_arrivals'][0]),{'room','booking','starts_at','ends_at','status'})
        self.assertEqual(boot['room_arrivals'][0]['room'],self.rooms[0].name)
        self.assertEqual(frappe.db.count('HS Stay'),0)

    def test_partial_group_only_lists_unentered_rooms_and_keeps_roomless_demand_visible(self):
        booked=self.reserve((0,1),roomless=True)
        self.enter(booked,self.rooms[0].name)
        result=self.board('arrivals')
        self.assertEqual(result['counts']['hosted'],1)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['rows'][0]['room_label'],'Por asignar')
        self.assertEqual(result['rows'][0]['category_label'],'Estándar')
        self.assertEqual(api.bootstrap(self.prop.name)['room_arrivals'],[])

    def test_expired_hold_is_hidden_without_expiring_or_releasing_it_in_a_read(self):
        # Retention is an explicit reserve option, not a client-written status.
        values=dict(starts_at=str(self.start+timedelta(days=1)),ends_at=str(self.start+timedelta(days=2)),guest=self.guest.name,customer=self.guest.customer,
                    hold=True,rooms=[dict(category=self.rooms[0].category,room=self.rooms[0].name,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        booked=self.command('reserve',values)
        with operation():
            doc=frappe.get_doc('HS Booking',booked['booking']);doc.hold_until=self.start-timedelta(minutes=1);doc.save()
        before=canonical(frappe.get_all('HS Allocation',fields=['*']))
        self.assertEqual(self.board('arrivals',str((self.start+timedelta(days=2)).date()))['total'],0)
        self.assertEqual(frappe.db.get_value('HS Booking',booked['booking'],'status'),'Hold')
        self.assertEqual(canonical(frappe.get_all('HS Allocation',fields=['*'])),before)

    def test_calendar_end_is_exclusive_in_property_zone_across_dst(self):
        with operation():self.prop.time_zone='America/New_York';self.prop.save()
        # All three requests use unambiguous explicit offsets around the 25-hour day.
        from datetime import datetime
        for i,start in enumerate(('2026-11-01T00:00:00-04:00','2026-11-01T23:00:00-05:00','2026-11-02T00:00:00-05:00')):
            self.reserve((i,),datetime.fromisoformat(start))
        result=self.board('arrivals','2026-11-01')
        self.assertEqual(result['total'],2)
        self.assertEqual(self.board('arrivals','2026-11-02')['total'],3)

    def test_shared_account_is_shown_once_and_zero_accounts_are_still_open(self):
        booked=self.reserve((0,1))
        one=self.enter(booked);two=self.enter(booked)
        shared=self.command('create_folio',dict(stay=one['stay'],group=1,customer=self.guest.customer,label='Cuenta grupo'))['folio']
        for charge in frappe.get_all('HS Charge',fields=['name']):
            self.command('move_charge',dict(charge=charge.name,folio=shared,reason='Consolidación sintética'))
        result=self.board('accounts')
        group=[r for r in result['rows'] if r['name']==shared]
        self.assertEqual(len(group),1)
        self.assertTrue(group[0]['shared'])
        self.assertEqual(group[0]['room_label'],'H101, H102')
        self.assertIn(group[0]['detail_stay'],[one['stay'],two['stay']])
        self.assertEqual(group[0]['balance']['outstanding'],'3000.00')
        self.assertEqual(sorted(r['balance']['outstanding'] for r in result['rows']),['0.00','0.00','3000.00'])

    def test_paging_is_complete_and_invalid_filters_do_not_silently_show_a_different_view(self):
        self.reserve((0,1,2))
        first=self.board('arrivals',page_length=2)
        second=self.board('arrivals',offset=2,page_length=2)
        self.assertEqual((first['total'],len(first['rows']),first['has_more']),(3,2,True))
        self.assertEqual(len(second['rows']),1)
        self.assertTrue({r['allocation'] for r in first['rows']}.isdisjoint(r['allocation'] for r in second['rows']))
        for params in (dict(view='bad'),dict(date='2026-02-30'),dict(date='20/10/2026'),dict(offset=-1),dict(page_length=0)):
            with self.assertRaises(frappe.ValidationError):api.stay_board(self.prop.name,**params)

    def test_roles_scope_discreet_names_and_read_only_posting_guards(self):
        self.enter(self.reserve())
        watched=('HS Request','HS Charge','HS Booking','HS Stay','Sales Invoice','Payment Entry','Journal Entry','GL Entry','Version')
        counts={dt:frappe.db.count(dt) for dt in watched}
        for user in ('receptionist@hospitality.example.invalid','cashier@hospitality.example.invalid','auditor@hospitality.example.invalid'):
            frappe.set_user(user)
            self.assertEqual(self.board()['counts']['hosted'],1)
            self.assertEqual(self.board('accounts')['total'],1)
        frappe.set_user('housekeeping@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.board()
        self.assertNotIn('room_arrivals',api.bootstrap(self.prop.name))
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):self.board()
        frappe.set_user('Administrator')
        with operation():self.prop.discreet_mode=1;self.prop.save()
        result=self.board()
        self.assertEqual(result['rows'][0]['guest_label'],'Huésped registrado')
        self.assertEqual(result['rows'][0]['customer_label'],'Cliente registrado')
        # The property edit is explicit; the subsequent board reads add no writes.
        counts['Version']=frappe.db.count('Version')
        self.board('accounts');self.board('departures');self.board('arrivals')
        self.assertEqual({dt:frappe.db.count(dt) for dt in watched},counts)

    def test_departures_include_overdue_and_active_stays_ignore_the_selected_date(self):
        entered=self.enter(self.reserve())
        stay=frappe.get_doc('HS Stay',entered['stay'])
        day=(self.start+timedelta(days=2)).date()
        self.assertEqual(self.board('departures',str(day))['total'],1)
        self.assertEqual(self.board('hosted','2020-01-01')['total'],1)
        # Ending exactly at the next local midnight belongs to the next date.
        from hospitality_suite.time import to_site
        from datetime import datetime,time
        with operation():stay.ends_at=to_site(datetime.combine(day+timedelta(days=1),time()),self.prop);stay.save()
        self.assertEqual(self.board('departures',str(day))['total'],0)

    def test_a_reception_user_cannot_read_a_property_without_an_access_record(self):
        user='board-'+uuid.uuid4().hex[:8]+'@example.invalid'
        frappe.get_doc(dict(doctype='User',email=user,first_name='Board test',send_welcome_email=0,user_type='System User',roles=[dict(role='HS Receptionist')])).insert()
        with operation():frappe.get_doc(dict(doctype='HS Access',property=self.prop.name,company=self.prop.company,user=user)).insert()
        other=frappe.db.get_value('HS Property',{'property_name':'Motel Luna Demo'})
        frappe.set_user(user)
        self.assertEqual(self.board()['total'],0)
        with self.assertRaises(frappe.PermissionError):api.stay_board(other)
