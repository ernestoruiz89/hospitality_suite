"""Complete operational room history, raw identity snapshots and narrow read access."""
from datetime import timedelta
import hashlib
import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime, get_datetime

from hospitality_suite import api
from hospitality_suite.schema import SCHEMA
from hospitality_suite.service import canonical, insert, operation
from hospitality_suite.time import to_site


class TestRoomHistory(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category','room_number'],order_by='room_number')
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name});self.now=now_datetime().replace(microsecond=0)
        self.checklist={key:True for key in ('baño','cama','minibar','superficies')}

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data):
        # Frappe 16 suppresses Version in tests by default. Exercise native
        # tracking as it runs in requests, rather than fabricate change rows.
        with patch.object(frappe,'in_test',False):
            return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def reserve(self,index=0,enter=False):
        values=dict(starts_at=str(self.now),ends_at=str(self.now+timedelta(days=2)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(room=self.rooms[index].name,category=self.rooms[index].category,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance'];return self.call('walk_in' if enter else 'reserve',values)

    def history(self,index=0,**query):
        values=dict(property_name=self.prop.name,room=self.rooms[index].name,starts_at=str(self.now-timedelta(hours=1)),
                    ends_at=str(self.now+timedelta(days=4)),view='all',page_length=200)
        values.update(query);return api.room_history(**values)

    def snapshot(self):
        names=set(SCHEMA)|{'Version','Sales Invoice','Sales Invoice Item','Payment Entry','Payment Entry Reference','Journal Entry','Journal Entry Account','GL Entry','Payment Ledger Entry','Stock Entry','Stock Ledger Entry'}
        return {dt:hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest() for dt in names}

    def test_modified_and_cancelled_reservation_keeps_both_rooms_without_attributing_cancellation_to_the_old_room(self):
        result=self.reserve();booking=frappe.get_doc('HS Booking',result['booking'])
        values=dict(booking=booking.name,modified=str(booking.modified),rooms=[dict(room=self.rooms[1].name,category=self.rooms[1].category,people=1)],reason='Cambio de habitación solicitada')
        values['acceptance']=api.preview(self.prop.name,values,'modify_reservation')['acceptance'];self.call('modify_reservation',values)
        booking.reload();self.call('booking_status',dict(booking=booking.name,modified=str(booking.modified),status='Cancelled',reason='Cancelación sintética autorizada'))
        event=frappe.get_last_doc('HS Audit Event',filters={'source_name':booking.name,'action':'Cancelled'})
        before=self.snapshot();old,new=self.history(),self.history(1)
        self.assertNotIn('event:'+event.name,{r['id'] for r in old['rows']});self.assertIn('event:'+event.name,{r['id'] for r in new['rows']})
        self.assertTrue(any(r['kind']=='period' and 'liberada' in r['title'] for r in old['rows']))
        self.assertTrue(any(r['kind']=='operation' and 'modificada' in r['title'] for r in old['rows']))
        self.assertEqual(self.snapshot(),before)

    def test_stay_change_and_all_cleaning_states_are_visible_with_before_after_values(self):
        result=self.reserve(enter=True);stay=frappe.get_doc('HS Stay',result['stay'])
        values=dict(stay=stay.name,folio=result['folio'],room=self.rooms[1].name,modified=str(stay.modified),reason='Cambio de habitación de prueba')
        values['acceptance']=api.preview(self.prop.name,values,'change_room')['acceptance'];self.call('change_room',values)
        task=frappe.get_doc('HS Cleaning Task',{'room':self.rooms[0].name,'status':'Pending'})
        for status in ('In Progress','Inspection','Completed'):
            task.reload();self.call('cleaning',dict(task=task.name,modified=str(task.modified),status=status,checklist=self.checklist,notes='Revisión registrada'))
        first,second=self.history(),self.history(1)
        for data in (first,second):self.assertTrue(any(r['title']=='Cambio de habitación' for r in data['rows']))
        text=canonical(first);self.assertIn('Sucia',text);self.assertIn('En limpieza',text);self.assertIn('Pendiente de inspección',text);self.assertIn('Limpia',text)
        self.assertGreaterEqual(first['counts']['change'],4)

    def test_room_rename_records_raw_values_when_native_version_is_skipped(self):
        room=frappe.get_doc('HS Room',self.rooms[0].name);original=room.room_number
        room.room_number='HIST-'+uuid.uuid4().hex[:8];room.save(ignore_version=True)
        event=frappe.get_last_doc('HS Audit Event',filters={'source_name':room.name,'action':'Room changed'})
        stored=frappe.parse_json(event.details)['_values']
        self.assertEqual(stored['before']['room_number'],original);self.assertEqual(stored['after']['room_number'],room.room_number)
        room.room_number='HIST-'+uuid.uuid4().hex[:8];room.save()
        data=self.history(view='operations');row=next(r for r in data['rows'] if r['id']=='event:'+event.name)
        self.assertTrue(any(value['before']==original for value in row['fields']));self.assertEqual(data['room_label'],room.room_number)

    def test_open_block_and_completed_block_keep_the_immutable_completion_time_after_later_edits(self):
        result=self.call('maintenance',dict(room=self.rooms[0].name,title='Bloqueo para historial',starts_at=str(self.now-timedelta(hours=2)),until_reopened=1))
        periods=self.history(view='periods');self.assertEqual(len(periods['rows']),1);self.assertIsNone(periods['rows'][0]['ends_at'])
        order=frappe.get_doc('HS Maintenance Order',result['order']);self.call('maintenance',dict(order=order.name,modified=str(order.modified),status='Completed'))
        event=frappe.get_last_doc('HS Audit Event',filters={'source_name':order.name,'action':'Maintenance Completed'})
        frappe.db.set_value('HS Maintenance Order',order.name,'modified',self.now+timedelta(days=20),update_modified=False)
        periods=self.history(view='periods');self.assertEqual(len(periods['rows']),1)
        self.assertEqual(to_site(periods['rows'][0]['ends_at'],self.prop),get_datetime(event.occurred_at))
        self.assertEqual(self.history(view='periods',starts_at=str(self.now+timedelta(days=1)))['rows'],[])

    def test_imported_room_segments_use_actual_late_checkout_only_for_the_last_segment(self):
        result=self.reserve(enter=True)
        first=frappe.get_doc('HS Allocation',{'stay':result['stay'],'kind':'Stay'})
        # Explicit synthetic historical resource fixture, not an executed checkout.
        frappe.db.set_value('HS Stay',result['stay'],dict(status='Checked Out',actual_check_in=self.now-timedelta(hours=3),actual_check_out=self.now-timedelta(minutes=10),ends_at=self.now-timedelta(minutes=30)))
        frappe.db.set_value('HS Allocation',first.name,dict(status='Released',starts_at=self.now-timedelta(hours=3),ends_at=self.now-timedelta(hours=2)))
        with operation(self.prop):
            middle=insert('HS Allocation',self.prop,room=self.rooms[1].name,category=self.rooms[1].category,stay=result['stay'],kind='Stay',status='Released',starts_at=self.now-timedelta(hours=2),ends_at=self.now-timedelta(hours=1))
            last=insert('HS Allocation',self.prop,room=self.rooms[0].name,category=self.rooms[0].category,stay=result['stay'],kind='Stay',status='Released',starts_at=self.now-timedelta(hours=1),ends_at=self.now-timedelta(minutes=30))
        data=self.history(view='periods',starts_at=str(self.now-timedelta(minutes=25)),ends_at=str(self.now-timedelta(minutes=5)))
        self.assertEqual([r['id'] for r in data['rows']],['allocation:'+last.name])
        self.assertEqual(to_site(data['rows'][0]['ends_at'],self.prop),self.now-timedelta(minutes=10))
        old=self.history(view='periods',starts_at=str(self.now-timedelta(hours=4)))
        self.assertEqual(len(old['rows']),2);self.assertNotIn('allocation:'+middle.name,{r['id'] for r in old['rows']})

    def test_point_events_use_inclusive_start_and_exclusive_end(self):
        room=frappe.get_doc('HS Room',self.rooms[0].name);room.floor='Rango-'+uuid.uuid4().hex[:5];room.save()
        event=frappe.get_last_doc('HS Audit Event',filters={'source_name':room.name,'action':'Room changed'});at=get_datetime(event.occurred_at)
        data=self.history(view='operations',starts_at=str(at),ends_at=str(at+timedelta(microseconds=1)))
        self.assertEqual([r['id'] for r in data['rows']],['event:'+event.name])
        data=self.history(view='operations',starts_at=str(at-timedelta(microseconds=1)),ends_at=str(at))
        self.assertNotIn('event:'+event.name,{r['id'] for r in data['rows']})

    def test_complete_pagination_includes_more_than_500_versions(self):
        with operation(self.prop):room=insert('HS Room',self.prop,room_number='HIST-'+uuid.uuid4().hex[:7],category=self.rooms[0].category,active=1,cleaning_status='Clean')
        prefix='history-'+uuid.uuid4().hex[:8]+'-';stamp=now_datetime()
        fields=['name','ref_doctype','docname','owner','creation','modified','data']
        values=[(prefix+str(i),'HS Room',room.name,'Administrator',stamp+timedelta(microseconds=i),stamp,
                 canonical(dict(changed=[['floor',str(i),str(i+1)]]))) for i in range(610)]
        frappe.db.bulk_insert('Version',fields=fields,values=values)
        seen=[];offset=0
        while True:
            result=self.history(room=room.name,view='changes',offset=offset,page_length=200)
            seen.extend(r['id'] for r in result['rows'])
            if not result['has_more']:break
            offset+=result['page_length']
        self.assertEqual(len([name for name in seen if name.startswith('version:'+prefix)]),610)
        self.assertEqual(len(seen),len(set(seen)));self.assertEqual(result['total'],611)

    def test_operator_projection_denies_other_roles_and_general_audit_access_without_leaking_payloads(self):
        with operation(self.prop):
            event=insert('HS Audit Event',self.prop,action='Room changed',source_doctype='HS Room',source_name=self.rooms[0].name,actor='Administrator',occurred_at=now_datetime(),business_date=self.prop.business_date,
                details=canonical(dict(provider_secret='NEVER-EXPOSE-THIS',_values=dict(version=1,doctype='HS Room',name=self.rooms[0].name,before={'floor':'1'},after={'floor':'2','identity_number':'PRIVATE-IDENTITY','evidence':'/private/files/secret'}))))
        before=self.snapshot()
        frappe.set_user('receptionist@hospitality.example.invalid');data=self.history();self.assertIn('event:'+event.name,{r['id'] for r in data['rows']})
        text=canonical(data)
        for secret in ('NEVER-EXPOSE-THIS','PRIVATE-IDENTITY','/private/files/secret','identity_number','provider_secret'):self.assertNotIn(secret,text)
        with self.assertRaises(frappe.PermissionError):api.audit_detail(self.prop.name,event.name)
        other=frappe.db.get_value('HS Property',{'mode':'Motel'});foreign=frappe.db.get_value('HS Room',{'property':other})
        with self.assertRaises(frappe.PermissionError):self.history(room=foreign)
        for user in ('housekeeping@hospitality.example.invalid','maintenance@hospitality.example.invalid','Guest'):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):self.history()
        self.assertEqual(self.snapshot(),before)

    def test_invalid_filters_and_empty_dates_fail_without_writes(self):
        before=self.snapshot()
        for query in ({'view':'raw-json'},{'starts_at':''},{'ends_at':None},{'ends_at':str(self.now-timedelta(days=2))},{'offset':-1},{'page_length':201},{'room':{}}):
            with self.subTest(query=query),self.assertRaises(frappe.ValidationError):self.history(**query)
        self.assertEqual(self.snapshot(),before)

    def test_old_versions_do_not_cross_a_property_boundary(self):
        room=frappe.get_doc('HS Room',self.rooms[9].name);old=room.room_number
        room.floor='PRIVATE-OLD-SCOPE';room.save(ignore_version=False)
        other=frappe.get_doc('HS Property',{'mode':'Motel'});category=frappe.db.get_value('HS Category',{'property':other.name})
        room.update(dict(property=other.name,company=other.company,category=category,room_number='TRANSFER-'+uuid.uuid4().hex[:5],floor='3'));room.save(ignore_version=False)
        data=self.history(property_name=other.name,room=room.name)
        text=canonical(data);self.assertNotIn('PRIVATE-OLD-SCOPE',text);self.assertNotIn(old,text)
        self.assertTrue(any(r['title']=='Ficha incorporada al establecimiento' for r in data['rows']))

    def test_scope_boundary_without_native_version_does_not_reassign_creation_or_prior_changes(self):
        room=frappe.get_doc('HS Room',self.rooms[9].name)
        room.floor='PRIVATE-OLD-SCOPE';room.save(ignore_version=False)
        other=frappe.get_doc('HS Property',{'mode':'Motel'});category=frappe.db.get_value('HS Category',{'property':other.name})
        room.update(dict(property=other.name,company=other.company,category=category,room_number='TRANSFER-'+uuid.uuid4().hex[:5],floor='3'));room.save(ignore_version=True)
        data=self.history(property_name=other.name,room=room.name)
        self.assertNotIn('PRIVATE-OLD-SCOPE',canonical(data))
        self.assertFalse(any(r['id'].startswith(('created:','version:')) for r in data['rows']))
        self.assertTrue(any(r['title']=='Ficha incorporada al establecimiento' for r in data['rows']))

    def test_malformed_legacy_payloads_are_explicit_without_crashing_or_leaking_fields(self):
        result=self.reserve(enter=True);stamp=now_datetime()
        booking=frappe.db.get_value('HS Stay',result['stay'],'booking')
        frappe.get_doc(dict(doctype='Version',ref_doctype='HS Booking',docname=booking,data=canonical(dict(
            changed=[['status',{'bad':'PRIVATE-LEGACY'},['bad']]],removed=[['rooms',{'name':'legacy-child','room':{'bad':'PRIVATE-LEGACY'}}]],
            row_changed=[['rooms',0,{},[['room','bad','bad']]]])))).insert(ignore_permissions=True)
        with operation(self.prop):
            insert('HS Audit Event',self.prop,action='Change room',source_doctype='HS Stay',source_name=result['stay'],actor='Administrator',occurred_at=stamp,business_date=self.prop.business_date,
                details=canonical({'from':[],'to':{},'_values':dict(version=1,doctype='HS Stay',name=result['stay'],before={'room':self.rooms[0].name},after={'room':self.rooms[0].name,'status':{'private':'PRIVATE-LEGACY'}})}))
        before=self.snapshot();data=self.history()
        self.assertIn('Valor conservado sin formato recuperable',canonical(data));self.assertNotIn('PRIVATE-LEGACY',canonical(data));self.assertEqual(self.snapshot(),before)

    def test_native_link_title_that_matches_another_room_id_never_attributes_a_change_to_that_other_room(self):
        # A visible room number may coincide with another room's internal ID.
        # Native Version stores that title; operational snapshots store raw IDs.
        room=frappe.get_doc('HS Room',self.rooms[0].name);room.room_number=self.rooms[1].name;room.save(ignore_version=False)
        result=self.reserve(2,enter=True)
        for index in (0,3):
            stay=frappe.get_doc('HS Stay',result['stay'])
            values=dict(stay=stay.name,folio=result['folio'],room=self.rooms[index].name,modified=str(stay.modified),reason='Prueba de títulos históricos ambiguos')
            values['acceptance']=api.preview(self.prop.name,values,'change_room')['acceptance'];self.call('change_room',values)
        versions=set(frappe.get_all('Version',filters={'ref_doctype':'HS Stay','docname':result['stay']},pluck='name'))
        self.assertTrue(versions)
        data=self.history(1)
        self.assertFalse(any(r['id'] in {'version:'+name for name in versions} for r in data['rows']))
        correct=self.history(0,view='operations')
        self.assertEqual(len([r for r in correct['rows'] if r['title']=='Cambio de habitación']),2)
