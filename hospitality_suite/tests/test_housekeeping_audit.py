"""Cleaning, indefinite blocks and linen against real Frappe/ERPNext state."""
from datetime import timedelta
from unittest.mock import patch
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime
from hospitality_suite import api,availability
from hospitality_suite.service import operation


class TestHousekeepingAudit(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category'],order_by='room_number')
        self.room=self.rooms[0];self.start=now_datetime().replace(microsecond=0)
        self.checklist={name:True for name in ('baño','cama','minibar','superficies')}

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def cleaning(self,kind='Deep',index=0,**extra):
        return self.call('schedule_cleaning',dict(room=self.rooms[index].name,kind=kind,priority='Urgent',notes='Revisar esquina y conservar instrucciones',**extra))['task']

    def update(self,name,status,**extra):
        task=frappe.get_doc('HS Cleaning Task',name)
        return self.call('cleaning',dict(task=name,modified=str(task.modified),status=status,**extra))

    def order(self,**extra):
        values=dict(room=self.room.name,title='Bloqueo sintético sin vencimiento',kind='Corrective',starts_at=str(self.start),until_reopened=1)
        values.update(extra);return self.call('maintenance',values)

    def booking(self,days=10,room=True,quantity=1):
        guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        start=self.start+timedelta(days=days)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
            rooms=[dict(category=self.room.category,room=self.room.name if room else None,people=1) for _ in range(quantity)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return values

    def test_all_cleaning_types_hold_assignment_and_notes_and_mark_room_unavailable_until_clean(self):
        cleaner='housekeeping@hospitality.example.invalid'
        for index,kind in enumerate(('Departure','Stay','Deep')):
            task=self.cleaning(kind,index,assigned_to=cleaner)
            self.assertEqual(frappe.db.get_value('HS Room',self.rooms[index].name,'cleaning_status'),'Dirty')
            with self.assertRaises(frappe.ValidationError):
                availability.check(self.prop,self.room.category,self.start,self.start+timedelta(days=1),self.rooms[index].name,for_entry=True)
            frappe.set_user(cleaner);self.update(task,'In Progress')
            row=frappe.get_doc('HS Cleaning Task',task)
            self.assertEqual(row.assigned_to,cleaner);self.assertTrue(row.started_at)
            self.assertIn('conservar instrucciones',row.notes)
            self.update(task,'Inspection',checklist=self.checklist)
            frappe.set_user('supervisor@hospitality.example.invalid');self.update(task,'Completed',checklist=self.checklist)
            row.reload();self.assertTrue(row.completed_at);self.assertEqual(row.inspected_by,frappe.session.user)
            self.assertEqual(row.kind,kind);self.assertEqual(row.priority,'Urgent')
            self.assertEqual(frappe.db.get_value('HS Room',self.rooms[index].name,'cleaning_status'),'Clean')
            frappe.set_user('Administrator')

    def test_optional_inspection_allows_direct_completion_and_repeated_command_is_one_event(self):
        with operation():self.prop.inspection_required=0;self.prop.save()
        name=self.cleaning();task=frappe.get_doc('HS Cleaning Task',name)
        frappe.set_user('housekeeping@hospitality.example.invalid')
        values=dict(task=name,modified=str(task.modified),status='In Progress');key=uuid.uuid4().hex
        first=self.call('cleaning',values,key);self.assertEqual(first,self.call('cleaning',values,key))
        with self.assertRaises(frappe.ValidationError):self.update(name,'Completed',checklist={'baño':True})
        self.update(name,'Completed',checklist=self.checklist)
        task.reload();self.assertFalse(task.inspected_by)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':name,'action':'Cleaning In Progress'}),1)

    def test_supervisor_rework_requires_reason_clears_completion_and_preserves_the_cleaner(self):
        name=self.cleaning(assigned_to='housekeeping@hospitality.example.invalid')
        frappe.set_user('housekeeping@hospitality.example.invalid');self.update(name,'In Progress')
        self.update(name,'Inspection',checklist=self.checklist)
        for target in ('In Progress','Completed'):
            with self.assertRaises(frappe.PermissionError):self.update(name,target,notes='Intento no autorizado',checklist=self.checklist)
        frappe.set_user('supervisor@hospitality.example.invalid')
        with self.assertRaises(frappe.ValidationError):self.update(name,'In Progress')
        self.update(name,'In Progress',notes='Repetir revisión del baño')
        task=frappe.get_doc('HS Cleaning Task',name)
        self.assertFalse(task.completed_at);self.assertFalse(any(json.loads(task.checklist).values()))
        self.assertEqual(task.assigned_to,'housekeeping@hospitality.example.invalid')
        frappe.set_user(task.assigned_to);self.update(name,'Inspection',checklist=self.checklist)
        frappe.set_user('supervisor@hospitality.example.invalid');self.update(name,'Completed',checklist=self.checklist)
        self.assertEqual(frappe.db.get_value('HS Room',self.room.name,'cleaning_status'),'Clean')

    def test_until_reopened_blocks_distant_dates_and_category_capacity_without_fabricated_end(self):
        result=self.order();order=frappe.get_doc('HS Maintenance Order',result['order'])
        self.assertTrue(order.until_reopened);self.assertFalse(order.ends_at)
        self.assertFalse(frappe.db.get_value('HS Allocation',{'maintenance':order.name},'ends_at'))
        for days in (0,36500):
            start=self.start+timedelta(days=days);end=start+timedelta(days=1)
            capacity=availability.capacity(self.prop,self.room.category,start,end)
            self.assertEqual(capacity['available'],9);self.assertNotIn(self.room.name,capacity['candidates'])
            with self.assertRaises(frappe.ValidationError):availability.check(self.prop,self.room.category,start,end,self.room.name)
            calendar=api.calendar(self.prop.name,str(start),str(end))
            block=next(row for row in calendar if row.maintenance==order.name)
            self.assertTrue(block.until_reopened)
        self.assertIn('Hasta reapertura autorizada',api.report_page(self.prop.name,'Mantenimiento')['rows'][0]['_display']['ends_at'])

    def test_maintenance_audit_labels_describe_the_work_and_schedule_without_changing_recorded_values(self):
        name=self.order()['order'];before=frappe.get_doc('HS Maintenance Order',name).as_dict()
        event=frappe.db.get_value('HS Audit Event',{'source_name':name,'source_doctype':'HS Maintenance Order','action':'Maintenance Open'},'name')
        frappe.set_user('auditor@hospitality.example.invalid');detail=api.audit_detail(self.prop.name,event)
        rows={row['field']:row for row in detail['values']}
        self.assertEqual(rows['title']['label'],'Trabajo requerido');self.assertEqual(rows['title']['after'],before['title'])
        self.assertEqual(rows['starts_at']['label'],'Inicio del trabajo');self.assertEqual(rows['ends_at']['label'],'Fin previsto')
        self.assertEqual(rows['ends_at']['after'],'Sin dato');self.assertFalse(rows['ends_at']['changed'])
        self.assertEqual(frappe.get_doc('HS Maintenance Order',name).as_dict(),before)
        from hospitality_suite.audit_trail import LABELS
        self.assertEqual(LABELS['title'],'Nombre de tarifa','tariff history keeps its own caption')

    def test_full_block_checks_all_future_room_and_roomless_reservations_without_cancelling_them(self):
        booking=self.call('reserve',self.booking(days=3650));before=frappe.get_doc('HS Booking',booking['booking']).as_dict()
        with self.assertRaises(frappe.ValidationError):self.order()
        self.assertEqual(frappe.get_doc('HS Booking',booking['booking']).as_dict(),before)
        values=self.booking(days=4000,room=False,quantity=10);self.call('reserve',values)
        with self.assertRaises(frappe.ValidationError):self.order()
        self.assertEqual(frappe.db.count('HS Maintenance Order'),0)

    def test_authorized_release_clips_calendar_and_kpis_at_the_immutable_completion_time(self):
        order=frappe.get_doc('HS Maintenance Order',self.order()['order'])
        frappe.set_user('maintenance@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.call('maintenance',dict(order=order.name,modified=str(order.modified),status='Completed'))
        frappe.set_user('supervisor@hospitality.example.invalid')
        completed=self.start+timedelta(hours=2)
        with patch('hospitality_suite.service.now_datetime',return_value=completed):
            self.call('maintenance',dict(order=order.name,modified=str(order.modified),status='Completed'))
        order.reload();self.assertEqual(order.reopened_by,frappe.session.user)
        self.assertEqual(frappe.db.get_value('HS Allocation',{'maintenance':order.name},'status'),'Released')
        from hospitality_suite.reports import summary
        result=summary(self.prop,str(self.start),str(self.start+timedelta(days=1)))
        self.assertEqual(result['available_hours'],238)
        calendar=api.calendar(self.prop.name,str(self.start),str(self.start+timedelta(days=1)))
        row=next(row for row in calendar if row.maintenance==order.name)
        self.assertTrue(row.ends_at.startswith(str(completed.date())))
        self.assertEqual(api.calendar(self.prop.name,str(completed+timedelta(days=1)),str(completed+timedelta(days=2))),[])
        availability.check(self.prop,self.room.category,completed,completed+timedelta(days=1),self.room.name)

    def test_roomless_equipment_open_ended_order_rejects_overlap_without_blocking_room_stock(self):
        result=api.save_setup(self.prop.name,'equipment',dict(equipment_code=uuid.uuid4().hex,label='Equipo de prueba',active=1),uuid.uuid4().hex)
        name=result['name'];self.order(room=None,equipment=name,blocks_room=0)
        self.assertEqual(availability.capacity(self.prop,self.room.category,self.start,self.start+timedelta(days=1))['available'],10)
        with self.assertRaises(frappe.ValidationError):self.order(room=None,equipment=name,blocks_room=0,starts_at=str(self.start+timedelta(days=36500)))

    def test_interval_can_end_at_a_future_arrival_but_cannot_overlap_it(self):
        values=self.booking(days=10);self.call('reserve',values)
        end=frappe.utils.get_datetime(values['starts_at']);start=end-timedelta(hours=2)
        order=self.order(until_reopened=0,starts_at=str(start),ends_at=str(end))
        self.assertTrue(order['order'])
        with self.assertRaises(frappe.ValidationError):
            self.order(until_reopened=0,starts_at=str(end),ends_at=str(end+timedelta(hours=1)))
        self.assertEqual(frappe.db.get_value('HS Booking',{},'status'),'Confirmed')

    def test_live_stay_conflict_leaves_the_stay_and_its_reservation_unchanged(self):
        visit=self.call('walk_in',self.booking(days=0))
        before=frappe.get_doc('HS Stay',visit['stay']).as_dict()
        with self.assertRaises(frappe.ValidationError):self.order()
        with self.assertRaises(frappe.ValidationError):self.order(until_reopened=0,ends_at=str(self.start+timedelta(hours=1)))
        self.assertEqual(frappe.get_doc('HS Stay',visit['stay']).as_dict(),before)

    def test_interval_blocks_keep_half_open_endpoints_and_invalid_missing_dates_are_rejected(self):
        end=self.start+timedelta(hours=2)
        result=self.order(until_reopened=0,ends_at=str(end))
        availability.check(self.prop,self.room.category,end,end+timedelta(hours=1),self.room.name)
        with self.assertRaises(frappe.ValidationError):self.order(until_reopened=0)
        with self.assertRaises(frappe.ValidationError):self.order(ends_at=str(end))
        with operation():
            with self.assertRaises(frappe.ValidationError):
                frappe.get_doc(dict(doctype='HS Allocation',property=self.prop.name,company=self.prop.company,category=self.room.category,room=self.room.name,starts_at=self.start,kind='Stay',status='Active')).insert(ignore_permissions=True)

    def test_real_linen_send_receive_loss_and_replenishment_use_native_stock_only(self):
        parent=frappe.db.get_value('Warehouse',{'company':self.prop.company,'is_group':1},'name')
        def warehouse(label):return frappe.get_doc(dict(doctype='Warehouse',warehouse_name=label+' '+uuid.uuid4().hex[:7],company=self.prop.company,parent_warehouse=parent,hs_property=self.prop.name)).insert()
        laundry,destination=warehouse('Lavandería'),warehouse('Ropa de habitaciones')
        with operation():self.prop.laundry_warehouse=laundry.name;self.prop.save()
        item=frappe.get_doc(dict(doctype='Item',item_code='SABANA-'+uuid.uuid4().hex[:8],item_name='Sábana de prueba',item_group='Products',stock_uom='Nos',is_stock_item=1)).insert()
        from hospitality_suite.accounting import post_standard
        receipt=frappe.new_doc('Stock Entry');receipt.update(dict(company=self.prop.company,stock_entry_type='Material Receipt'))
        receipt.append('items',dict(item_code=item.name,qty=10,t_warehouse=self.prop.warehouse,basic_rate=20));post_standard(receipt,self.prop)
        def quantity(wh):return frappe.db.get_value('Bin',{'item_code':item.name,'warehouse':wh},'actual_qty') or 0
        frappe.set_user('housekeeping@hospitality.example.invalid')
        values=dict(room=self.room.name,item=item.name,quantity=3,direction='Send');key=uuid.uuid4().hex
        sent=self.call('linen',values,key);self.assertEqual(sent,self.call('linen',values,key));self.assertEqual(quantity(laundry.name),3)
        self.call('linen',dict(room=self.room.name,item=item.name,quantity=2,direction='Receive'))
        self.call('linen',dict(room=self.room.name,item=item.name,quantity=1,direction='Loss',reason='Rotura de prueba'))
        self.assertEqual((quantity(self.prop.warehouse),quantity(laundry.name)),(9,0))
        frappe.set_user('supervisor@hospitality.example.invalid')
        self.call('move_stock',dict(item=item.name,quantity=2,purpose='Linen Replacement',target_warehouse=destination.name,reason='Reposición en ubicación de habitaciones'))
        self.assertEqual((quantity(self.prop.warehouse),quantity(destination.name)),(7,2))
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        movements=api.report(self.prop.name,'Movimientos de inventario',dict(item=item.name))
        self.assertTrue(any(row['purpose']=='Linen Replacement' for row in movements))

    def test_incident_roles_and_cleaner_assignment_do_not_expose_guest_or_financial_data(self):
        task=self.cleaning()
        frappe.set_user('housekeeping@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.update(task,'In Progress',assigned_to='supervisor@hospitality.example.invalid')
        for kind in ('Damage','Lost Property'):
            result=self.call('incident',dict(room=self.room.name,kind=kind,description='Registro sintético '+kind))
            incident=frappe.get_doc('HS Incident',result['incident'])
            with self.assertRaises(frappe.PermissionError):
                self.call('incident',dict(incident=incident.name,modified=str(incident.modified),resolve=True,resolution='Intento de entrega'))
        projection=api.bootstrap(self.prop.name)
        self.assertFalse(projection.get('guests'));self.assertFalse(projection.get('payments'));self.assertFalse(projection.get('customers'))
        self.assertTrue(all('cost' not in row and 'evidence' not in row for row in projection['maintenance']))
        self.assertEqual({row.kind for row in projection['incidents']},{'Damage','Lost Property'})

    def test_multi_property_user_cannot_update_other_property_documents_through_selected_context(self):
        other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        room=frappe.db.get_value('HS Room',{'property':other.name},'name')
        def foreign(action,values):return api.execute(other.name,action,uuid.uuid4().hex,values)
        task=frappe.get_doc('HS Cleaning Task',foreign('schedule_cleaning',dict(room=room,kind='Deep',priority='Normal'))['task'])
        order=frappe.get_doc('HS Maintenance Order',foreign('maintenance',dict(room=room,title='Orden de otra propiedad',kind='Preventive',starts_at=str(self.start),until_reopened=1))['order'])
        incident=frappe.get_doc('HS Incident',foreign('incident',dict(room=room,kind='Damage',description='Novedad de otra propiedad'))['incident'])
        originals=[doc.as_dict() for doc in (task,order,incident)]
        counts={dt:frappe.db.count(dt) for dt in ('HS Request','HS Audit Event','Stock Entry','GL Entry','Stock Ledger Entry')}
        attempts=[('cleaning',dict(task=task.name,modified=str(task.modified),status='In Progress')),
            ('maintenance',dict(order=order.name,modified=str(order.modified),status='Completed')),
            ('maintenance_parts',dict(order=order.name,modified=str(order.modified),parts=[dict(item='HS-DEMO-WATER',quantity=1)])),
            ('incident',dict(incident=incident.name,modified=str(incident.modified),resolve=True,resolution='Intento ajeno')),
            ('linen',dict(room=room,item='HS-DEMO-WATER',quantity=1,direction='Send'))]
        for action,values in attempts:
            with self.assertRaises(frappe.PermissionError):self.call(action,values)
        self.assertEqual([frappe.get_doc(doc.doctype,doc.name).as_dict() for doc in (task,order,incident)],originals)
        self.assertEqual({dt:frappe.db.count(dt) for dt in counts},counts)
