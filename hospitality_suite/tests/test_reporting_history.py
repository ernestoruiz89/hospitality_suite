"""History remains complete beyond former limits and respects role/property."""
from datetime import timedelta
from unittest.mock import patch
import io
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime
from openpyxl import load_workbook

from hospitality_suite import api


class TestReportingHistory(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def test_all_report_pages_and_xlsx_include_more_than_1000_records(self):
        prefix='page-'+uuid.uuid4().hex[:8]+'-'
        stamp=now_datetime()
        # Bulk fixture data exercises reads, not the operational command service.
        fields=['name','company','property','action','actor','occurred_at','business_date','owner','creation','modified']
        values=[(prefix+str(i),self.prop.company,self.prop.name,'History fixture','Administrator',stamp,self.prop.business_date,'Administrator',stamp,stamp) for i in range(1105)]
        frappe.db.bulk_insert('HS Audit Event',fields=fields,values=values)
        direct=api.report(self.prop.name,'Auditoría')
        self.assertEqual(len([r for r in direct if r.name.startswith(prefix)]),1105)
        self.assertEqual(len(api.project('HS Audit Event',self.prop)),len(direct))
        names=[]
        offset=0
        while True:
            result=api.report_page(self.prop.name,'Auditoría',offset=offset,page_length=200)
            self.assertLessEqual(len(result['rows']),200)
            self.assertEqual(result['total'],len(direct))
            names.extend(r.name for r in result['rows'])
            if not result['has_more']:
                break
            offset+=result['page_length']
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(set(names),{r.name for r in direct})
        frappe.local.response=frappe._dict()
        api.export_report(self.prop.name,'Auditoría',file_format='xlsx')
        workbook=load_workbook(io.BytesIO(frappe.local.response.filecontent),read_only=True)
        self.assertEqual(sum(1 for _ in workbook.active.rows),len(direct)+1)
        workbook.close()
        for bad in (-1,0.5):
            with self.assertRaises(frappe.ValidationError):
                api.report_page(self.prop.name,'Auditoría',offset=bad)
        frappe.set_user('housekeeping@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):
            api.report_page(self.prop.name,'Auditoría')

    def test_calendar_keeps_more_than_500_assignments(self):
        prefix='calendar-'+uuid.uuid4().hex[:8]+'-'
        room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H110'})
        start=now_datetime().replace(microsecond=0)+timedelta(days=40)
        fields=['name','company','property','room','category','starts_at','ends_at','kind','status','owner','creation','modified']
        values=[(prefix+str(i),self.prop.company,self.prop.name,room.name,room.category,start+timedelta(minutes=i*30),start+timedelta(minutes=i*30+15),'Maintenance','Active','Administrator',start,start) for i in range(610)]
        frappe.db.bulk_insert('HS Allocation',fields=fields,values=values)
        result=api.calendar(self.prop.name,str(start),str(start+timedelta(days=14)))
        self.assertEqual(len([r for r in result if r.name.startswith(prefix)]),610)
        self.assertEqual(len({r.name for r in result}),len(result))

    def test_guest_history_includes_companion_and_denies_other_property(self):
        guests=frappe.get_all('HS Guest',filters={'property':self.prop.name},fields=['name','customer'])
        rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category'],order_by='room_number')
        stays=[]
        start=now_datetime().replace(microsecond=0)
        for guest,room in zip(guests[:2],rooms[:2]):
            values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                        rooms=[dict(room=room.name,category=room.category,people=2)])
            values['acceptance']=api.preview(self.prop.name,values)['acceptance']
            stays.append(api.execute(self.prop.name,'walk_in',uuid.uuid4().hex,values)['stay'])
        second=frappe.get_doc('HS Stay',stays[1])
        api.execute(self.prop.name,'companions',uuid.uuid4().hex,dict(stay=second.name,modified=str(second.modified),guests=[guests[0].name]))
        result=api.guest_history(guests[0].name)
        self.assertEqual({r.name:r.relationship for r in result['rows']},{stays[0]:'Principal',stays[1]:'Acompañante'})
        user='history-'+uuid.uuid4().hex[:8]+'@example.invalid'
        frappe.get_doc(dict(doctype='User',email=user,first_name='History test',send_welcome_email=0,user_type='System User',roles=[dict(role='HS Receptionist')])).insert()
        from hospitality_suite.service import operation
        with operation():
            frappe.get_doc(dict(doctype='HS Access',property=self.prop.name,company=self.prop.company,user=user)).insert()
        other=frappe.db.get_value('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        foreign=frappe.db.get_value('HS Guest',{'property':other})
        frappe.set_user(user)
        self.assertEqual(api.guest_history(guests[0].name)['total'],2)
        with self.assertRaises(frappe.PermissionError):
            api.guest_history(foreign)

    def test_completed_maintenance_remains_in_history_after_later_document_edit(self):
        room=frappe.db.get_value('HS Room',{'property':self.prop.name,'room_number':'H109'},'name')
        now=now_datetime()
        created=api.execute(self.prop.name,'maintenance',uuid.uuid4().hex,dict(room=room,title='Historical maintenance fixture',starts_at=str(now-timedelta(hours=2)),ends_at=str(now+timedelta(hours=1))))
        order=frappe.get_doc('HS Maintenance Order',created['order'])
        api.execute(self.prop.name,'maintenance',uuid.uuid4().hex,dict(order=order.name,modified=str(order.modified),status='Completed'))
        finished=frappe.db.get_value('HS Audit Event',{'source_doctype':'HS Maintenance Order','source_name':order.name,'action':'Maintenance Completed'},'occurred_at')
        # A later evidence/retention edit must not extend the historical block.
        frappe.db.set_value('HS Maintenance Order',order.name,'modified',now+timedelta(days=10),update_modified=False)
        records=api.calendar(self.prop.name,str(now-timedelta(hours=3)),str(now+timedelta(hours=2)))
        result=[r for r in records if r.maintenance==order.name]
        self.assertEqual(len(result),1)
        from hospitality_suite.time import local
        self.assertEqual(result[0].ends_at,local(finished,self.prop).isoformat())

    def test_pdf_rejects_incompatible_renderer_instead_of_returning_a_broken_report(self):
        with patch('frappe.utils.pdf.is_wkhtmltopdf_valid',return_value=False),patch('frappe.utils.pdf.get_pdf') as renderer:
            with self.assertRaises(frappe.ValidationError):
                api.export_report(self.prop.name,'Auditoría',file_format='pdf')
            renderer.assert_not_called()
