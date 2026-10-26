"""Operational-window boundaries and actionable, frozen pending work."""
from datetime import timedelta
from unittest.mock import patch
import hashlib
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,getdate

from hospitality_suite import api,closing
from hospitality_suite.close_checks import period_labels
from hospitality_suite.service import canonical,operation
from hospitality_suite.time import business_window


class TestClosingChecks(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        with operation():self.prop.business_date=getdate(now_datetime());self.prop.save()
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','room_number','category'],order_by='room_number')
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name});self.window=business_window(self.prop)

    def tearDown(self):frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def reserve(self,indices,start=None,end=None,hold=False):
        start=start or self.window['ends_at']-timedelta(minutes=30);end=end or self.window['ends_at']+timedelta(days=1)
        values=dict(starts_at=str(start),ends_at=str(end),guest=self.guest.name,customer=self.guest.customer,hold=hold,
            rooms=[dict(room=self.rooms[n].name,category=self.rooms[n].category,people=1) for n in indices])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance'];return self.call('reserve',values)['booking']

    def enter(self,index=0,end=None):
        name=self.reserve([index],start=now_datetime().replace(microsecond=0),end=end)
        return self.enter_booking(name,index)

    def enter_booking(self,name,index):
        doc=frappe.get_doc('HS Booking',name)
        allocation=frappe.db.get_value('HS Allocation',{'booking':name,'kind':'Reservation','status':'Active','room':self.rooms[index].name},'name')
        return self.call('check_in',dict(booking=name,modified=str(doc.modified),allocation=allocation,guest=self.guest.name,room=self.rooms[index].name))

    def fingerprints(self):
        from hospitality_suite.schema import SCHEMA
        names=set(SCHEMA)|{'Version','Sales Invoice','Sales Invoice Item','Payment Entry','Payment Entry Reference','Journal Entry','Journal Entry Account','GL Entry','Payment Ledger Entry','Stock Entry','Stock Ledger Entry','Bin'}
        result={}
        for dt in names:
            rows=frappe.db.get_singles_dict(dt) if frappe.get_meta(dt).issingle else frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            result[dt]=hashlib.sha256(canonical(rows).encode()).hexdigest()
        return result

    def groups(self):return {row['type']:row for row in closing.blockers(self.prop)}

    def test_operational_date_does_not_follow_clock_and_cutoff_changes_only_the_window(self):
        with operation():self.prop.business_date='2020-05-15';self.prop.close_time='04:30:00';self.prop.save()
        original=business_window(self.prop);before=self.fingerprints()
        for clock in ('2026-10-20 23:59:59','2026-10-21 00:00:01'):
            with patch('hospitality_suite.close_checks.now_datetime',return_value=frappe.utils.get_datetime(clock)):
                self.assertEqual(business_window(self.prop),original);self.assertEqual(closing.blockers(self.prop),[])
        self.assertEqual(self.fingerprints(),before)
        api.save_setup(self.prop.name,'property',dict(close_time='07:15:00'),uuid.uuid4().hex,str(self.prop.modified));self.prop.reload()
        labels=period_labels(self.prop);self.assertEqual(labels['date_label'],'15/05/2020');self.assertEqual(labels['close_time'],'07:15:00')
        self.assertEqual(str(self.prop.business_date),'2020-05-15');self.assertNotEqual(business_window(self.prop)['starts_at'],original['starts_at'])

    def test_native_cutoff_configuration_keeps_23_and_25_hour_local_days(self):
        for day,hours in (('2026-03-07',23),('2026-10-31',25)):
            with operation():self.prop.time_zone='America/New_York';self.prop.close_time='06:00:00';self.prop.business_date=day;self.prop.save()
            window=business_window(self.prop);self.assertEqual((window['ends_at']-window['starts_at']).total_seconds()/3600,hours)
            labels=period_labels(self.prop);self.assertEqual(labels['time_zone'],'America/New_York');self.assertTrue(labels['starts_at'].endswith('06:00'));self.assertTrue(labels['ends_at'].endswith('06:00'))
        for value in ('24:00:00','240000','T24:00:00','25:00:00','06:00:00+02:00'):
            self.prop.reload()
            with self.assertRaises(frappe.ValidationError):api.save_setup(self.prop.name,'property',dict(close_time=value),uuid.uuid4().hex,str(self.prop.modified))

    def test_arrivals_include_future_work_inside_the_day_and_remaining_group_rooms(self):
        group=self.reserve([0,1],start=now_datetime()-timedelta(minutes=15));self.enter_booking(group,0)
        confirmed=self.reserve([2]);at_cutoff=self.reserve([3],start=self.window['ends_at']);hold=self.reserve([4],hold=True)
        cancelled=self.reserve([5]);doc=frappe.get_doc('HS Booking',cancelled)
        self.call('booking_status',dict(booking=cancelled,modified=str(doc.modified),status='Cancelled',reason='No se espera esta llegada'))
        before=self.fingerprints();arrivals=self.groups()['Llegadas pendientes']
        self.assertEqual(set(arrivals['documents']),{group,confirmed});self.assertFalse(set(arrivals['documents'])&{at_cutoff,hold,cancelled})
        row=next(r for r in arrivals['items'] if r['name']==group)
        self.assertIn(self.rooms[1].room_number,row['label']);self.assertNotIn(self.rooms[0].room_number,row['label']);self.assertIn('pendientes: 1',row['detail'])
        self.assertEqual(self.fingerprints(),before)
        self.enter_booking(group,1);self.assertNotIn(group,self.groups()['Llegadas pendientes']['documents'])

    def test_departures_and_overdue_stays_use_the_exclusive_cutoff_and_do_not_include_another_property(self):
        pending=self.enter(0,end=self.window['ends_at']-timedelta(seconds=1));at_cutoff=self.enter(1,end=self.window['ends_at']);after=self.enter(2,end=self.window['ends_at']+timedelta(seconds=1))
        clock=now_datetime().replace(microsecond=0);expired=self.enter(3,end=clock+timedelta(minutes=1))
        before=self.fingerprints()
        with patch('hospitality_suite.close_checks.now_datetime',return_value=clock+timedelta(minutes=2)):
            groups=self.groups()
        self.assertEqual(groups['Salidas pendientes']['documents'],[pending['stay']]);self.assertEqual(groups['Estancias vencidas']['documents'],[expired['stay']])
        self.assertFalse({at_cutoff['stay'],after['stay']}&{n for g in groups.values() for n in g['documents']})
        self.assertEqual(self.fingerprints(),before)
        other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        self.assertFalse(any(g['type'] in ('Salidas pendientes','Estancias vencidas') for g in closing.blockers(other)))

    def test_pending_and_scheduled_charges_and_open_review_shifts_are_listed_with_readable_context(self):
        pending=self.enter();pending_charge=frappe.db.get_value('HS Charge',{'stay':pending['stay']})
        with operation():self.prop.lodging_charge_policy='Nightly';self.prop.save()
        nightly=self.enter(1);scheduled=frappe.get_all('HS Charge',filters={'stay':nightly['stay'],'status':'Scheduled'},fields=['name','service_date'])
        shift=self.call('open_shift',dict(opening_amount=100))['shift'];groups=self.groups()
        self.assertIn(pending_charge,groups['Cargos sin facturar']['documents']);self.assertIn(shift,groups['Turnos sin cerrar']['documents'])
        self.assertEqual(set(groups['Cargos nocturnos sin generar']['documents']),{r.name for r in scheduled if getdate(r.service_date)<=getdate(self.prop.business_date)})
        self.assertIn('H101',groups['Cargos sin facturar']['items'][0]['label']);self.assertIn('NIO',groups['Cargos sin facturar']['items'][0]['detail'])
        doc=frappe.get_doc('HS Shift',shift);self.call('close_shift',dict(shift=shift,modified=str(doc.modified),denominations={'NIO':[dict(value=10,count=9)]},reason='Diferencia de conteo por revisar'))
        self.assertIn(shift,self.groups()['Turnos sin cerrar']['documents'])
        review=self.call('daily_close',dict(confirm=False));self.assertNotIn('Cargos nocturnos sin generar',{g['type'] for g in review['blockers']})
        self.assertTrue(frappe.db.count('HS Charge',{'stay':nightly['stay'],'status':'Scheduled'}))

    def test_a_real_native_cancellation_after_count_creates_a_difference_and_blocks_confirmation(self):
        stay=self.enter();self.call('invoice',dict(folio=stay['folio']))
        shift=self.call('open_shift',dict(opening_amount=0))['shift'];method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        paid=self.call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=method,amount=100,kind='Advance'))
        doc=frappe.get_doc('HS Shift',shift);self.call('close_shift',dict(shift=shift,modified=str(doc.modified),denominations={'NIO':[dict(value=100,count=1)]}))
        native=frappe.get_doc('Payment Entry',paid['payment_entry']);native.hs_correction_reason='Anulación nativa después del arqueo';native.cancel()
        review=self.call('daily_close',dict(confirm=False));group=next(g for g in review['blockers'] if g['type']=='Diferencias entre PMS y ERPNext')
        self.assertIn(shift,group['documents']);self.assertIn('-100.00 NIO',group['items'][0]['detail'])
        before=self.fingerprints()
        with self.assertRaises(frappe.ValidationError):self.call('daily_close',dict(confirm=True,review_acceptance=review['review_acceptance']))
        self.assertEqual(self.fingerprints(),before);self.assertEqual(str(self.prop.business_date),str(frappe.db.get_value('HS Property',self.prop.name,'business_date')))

    def test_resolving_a_pending_arrival_requires_fresh_review_and_keeps_the_old_execution_snapshot(self):
        name=self.reserve([0]);review=self.call('daily_close',dict(confirm=False))
        event=frappe.get_last_doc('HS Audit Event',filters={'source_name':review['close'],'action':'Daily close Review'})
        frozen=event.details;doc=frappe.get_doc('HS Booking',name)
        self.call('booking_status',dict(booking=name,modified=str(doc.modified),status='Cancelled',reason='Reserva cancelada antes de cerrar'))
        with self.assertRaises(frappe.ValidationError):self.call('daily_close',dict(confirm=True,review_acceptance=review['review_acceptance']))
        updated=self.call('daily_close',dict(confirm=False));self.assertFalse(updated['blockers'])
        self.call('daily_close',dict(confirm=True,review_acceptance=updated['review_acceptance']))
        self.assertEqual(frappe.db.get_value('HS Audit Event',event.name,'details'),frozen)
        detail=api.audit_detail(self.prop.name,event.name);self.assertIn(name,detail['close_blockers'][0]['documents']);self.assertIn('H101',detail['close_blockers'][0]['items'][0]['label'])

    def test_read_only_auditor_cannot_create_a_preparation_or_change_an_existing_one(self):
        before=self.fingerprints();frappe.set_user('auditor@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.call('daily_close',dict(confirm=False))
        self.assertEqual(self.fingerprints(),before);frappe.set_user('Administrator');self.call('daily_close',dict(confirm=False))
        before=self.fingerprints();frappe.set_user('auditor@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.call('daily_close',dict(confirm=False))
        self.assertEqual(self.fingerprints(),before)
