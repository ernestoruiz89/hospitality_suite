from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api,jobs
from hospitality_suite.service import operation


class TestHoldExpiry(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})

    def hold(self,prop,index=0):
        room=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','category'])[0]
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        start=now_datetime().replace(hour=14,minute=0,second=0,microsecond=0)+timedelta(days=80+index*3)
        data=dict(guest=guest.name,customer=guest.customer,hold=1,starts_at=str(start),
                  ends_at=str(start+timedelta(hours=3 if prop.mode=='Por tiempo' else 24)),
                  rooms=[dict(room=room.name,category=room.category,people=1)])
        data['acceptance']=api.preview(prop.name,data)['acceptance']
        return api.execute(prop.name,'reserve',uuid.uuid4().hex,data)['booking']

    def deadline(self,name,value):
        with operation():
            doc=frappe.get_doc('HS Booking',name)
            doc.hold_until=value
            doc.save()

    def test_expiry_releases_only_the_requested_property_and_repetition_has_no_effect(self):
        other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        own,foreign=self.hold(self.prop),self.hold(other)
        for name in (own,foreign):
            self.deadline(name,now_datetime()-timedelta(minutes=1))
        self.assertEqual(jobs.expire_property(self.prop.name),1)
        self.assertEqual(jobs.expire_property(self.prop.name),0)
        self.assertEqual(frappe.db.get_value('HS Booking',own,'status'),'Cancelled')
        self.assertEqual(frappe.db.get_value('HS Booking',foreign,'status'),'Hold')
        self.assertEqual(frappe.db.count('HS Allocation',{'booking':foreign,'status':'Active'}),1)
        self.assertEqual(jobs.expire_property(other.name),1)
        self.assertEqual(frappe.db.count('HS Allocation',{'booking':['in',[own,foreign]],'status':'Active'}),0)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':['in',[own,foreign]],'action':'Hold expired'}),2)

    def test_hold_expires_at_its_deadline_without_releasing_the_next_second(self):
        names=[self.hold(self.prop,index) for index in range(3)]
        boundary=now_datetime().replace(microsecond=0)
        for name,offset in zip(names,(-1,0,1)):
            self.deadline(name,boundary+timedelta(seconds=offset))
        with patch('hospitality_suite.availability.now_datetime',return_value=boundary):
            self.assertEqual(jobs.expire_property(self.prop.name),2)
            self.assertEqual(jobs.expire_property(self.prop.name),0)
        self.assertEqual(frappe.db.get_value('HS Booking',names[-1],'status'),'Hold')
        self.assertEqual(frappe.db.count('HS Allocation',{'booking':names[-1],'status':'Active'}),1)
        with patch('hospitality_suite.availability.now_datetime',return_value=boundary+timedelta(seconds=1)):
            self.assertEqual(jobs.expire_property(self.prop.name),1)
        self.assertEqual(frappe.db.count('HS Audit Event',{'source_name':['in',names],'action':'Hold expired'}),3)
