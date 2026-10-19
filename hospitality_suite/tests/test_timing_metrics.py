from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api,timing,reports,reconciliation
from hospitality_suite.service import operation


class TestTimingMetrics(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["*"],order_by="room_number")[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]

    def call(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def enter(self,people=1):
        start=now_datetime().replace(microsecond=0)
        data=dict(starts_at=str(start),ends_at=str(start+(timedelta(hours=3) if self.prop.mode=="Motel" else timedelta(days=1))),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=people)])
        data["acceptance"]=api.preview(self.prop.name,data)["acceptance"]
        return self.call("walk_in",data)

    def test_motel_midnight_grace_overtime_and_prepare_retry(self):
        self.prop=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name,"room_number":"M110"},fields=["*"])[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]
        entered=self.enter()
        stay=frappe.get_doc("HS Stay",entered["stay"])
        end=stay.ends_at
        with patch("hospitality_suite.timing.now_datetime",return_value=end+timedelta(minutes=10)):
            self.assertEqual(timing.departure(self.prop,dict(stay=stay.name))["amount"],"0.00")
        with patch("hospitality_suite.timing.now_datetime",return_value=end+timedelta(minutes=10,seconds=1)):
            quote=timing.departure(self.prop,dict(stay=stay.name))
            self.assertEqual(quote["amount"],"150.00")
            data=dict(stay=stay.name,folio=entered["folio"],acceptance=quote["acceptance"])
            key=uuid.uuid4().hex
            first=api.execute(self.prop.name,"prepare_departure",key,data)
            self.assertEqual(first,api.execute(self.prop.name,"prepare_departure",key,data))
            self.assertEqual(timing.departure(self.prop,dict(stay=stay.name))["amount"],"0.00")
            self.assertEqual(frappe.db.count("HS Charge",{"stay":stay.name,"description":"Liquidación de tiempo de estancia"}),1)

    def test_hotel_late_rounding_and_inspection_gate(self):
        with operation():
            self.prop.late_hour_rate=120
            self.prop.timing_item=self.prop.lodging_item
            self.prop.schedule_grace_minutes=10
            self.prop.schedule_rounding_minutes=30
            self.prop.checkout_inspection_required=1
            self.prop.save()
        entered=self.enter()
        stay=frappe.get_doc("HS Stay",entered["stay"])
        # The night ends at the configured checkout boundary, even with an earlier planned departure.
        boundary=stay.starts_at.replace(hour=12,minute=0,second=0,microsecond=0)+timedelta(days=1)
        with patch("hospitality_suite.timing.now_datetime",return_value=boundary+timedelta(minutes=10,seconds=1)):
            q=timing.departure(self.prop,dict(stay=stay.name))
            self.assertEqual(q["amount"],"60.00")
            self.call("prepare_departure",dict(stay=stay.name,folio=entered["folio"],acceptance=q["acceptance"]))
        stay.reload()
        with self.assertRaises(frappe.ValidationError):
            self.call("check_out",dict(stay=stay.name,modified=str(stay.modified)))
        self.call("inspect_departure",dict(stay=stay.name,notes="Minibar y daños revisados"))
        self.assertTrue(frappe.db.get_value("HS Stay",stay.name,"departure_inspected_by"))

    def test_courtesy_occupies_without_revenue_and_zero_denominator(self):
        entered=self.enter(people=2)
        charge=frappe.db.get_value("HS Charge",{"stay":entered["stay"],"kind":"Lodging"},"name")
        self.call("adjustment",dict(charge=charge,adjustment_type="Courtesy",reason="Cortesía autorizada de prueba"))
        self.call("invoice",dict(folio=entered["folio"]))
        today=str(now_datetime().date())
        result=reports.summary(self.prop,today+" 00:00:00",str(now_datetime().date()+timedelta(days=1))+" 00:00:00")
        self.assertEqual(result["room_nights"],1)
        self.assertEqual(result["hotel_lodging_net"],"0.00")
        self.assertEqual(result["ADR"],"0.00")
        self.assertFalse(reconciliation.differences(self.prop))
        with operation():
            for name in frappe.get_all("HS Room",filters={"property":self.prop.name,"name":["!=",self.room.name]},pluck="name"):
                room=frappe.get_doc("HS Room",name)
                room.active=0
                room.save()
        # Explicit whole-period maintenance on all available rooms is covered by the denominator's union.
        with patch("hospitality_suite.reports.current_all",side_effect=lambda dt,**kw: []):
            zero=reports.summary(self.prop,today+" 00:00:00",str(now_datetime().date()+timedelta(days=1))+" 00:00:00")
        self.assertEqual(zero["ADR"],"0.00")
        self.assertEqual(zero["RevPAR"],"0.00")
        self.assertEqual(zero["utilization"],0)

    def test_companions_scoped_capacity_and_incomplete_cleaning(self):
        entered=self.enter(people=2)
        companion=frappe.get_all("HS Guest",filters={"property":self.prop.name,"name":["!=",self.guest.name]},pluck="name")[0]
        stay=frappe.get_doc("HS Stay",entered["stay"])
        self.call("companions",dict(stay=stay.name,modified=str(stay.modified),guests=[companion]))
        self.assertEqual(len(frappe.get_doc("HS Stay",stay.name).guests),2)
        task=self.call("schedule_cleaning",dict(room=self.room.name,kind="Stay",priority="High"))["task"]
        doc=frappe.get_doc("HS Cleaning Task",task)
        self.call("cleaning",dict(task=task,status="In Progress",modified=str(doc.modified)))
        doc.reload()
        with self.assertRaises(frappe.ValidationError):
            self.call("cleaning",dict(task=task,status="Inspection",modified=str(doc.modified),checklist={"baño":True}))

    def test_motel_actual_arrival_hours_and_maintenance_capacity(self):
        self.prop=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name,"room_number":"M110"},fields=["*"])[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]
        entered=self.enter()
        now=now_datetime().replace(microsecond=0)
        with operation():
            stay=frappe.get_doc("HS Stay",entered["stay"])
            stay.actual_check_in=now-timedelta(hours=2)
            stay.save()
            segment=frappe.get_doc("HS Allocation",{"stay":stay.name,"status":"Active"})
            segment.starts_at=now-timedelta(hours=4)
            segment.save(ignore_permissions=True)
        blocked=frappe.db.get_value("HS Room",{"property":self.prop.name,"room_number":"M109"},"name")
        self.call("maintenance",dict(room=blocked,title="Mantenimiento de referencia",starts_at=str(now-timedelta(hours=1)),ends_at=str(now+timedelta(hours=1))))
        with patch("hospitality_suite.reports.now_datetime",return_value=now):
            result=reports.summary(self.prop,str(now-timedelta(hours=3)),str(now+timedelta(hours=21)))
        self.assertEqual(result["occupied_hours"],2)
        self.assertEqual(result["available_hours"],238)
        self.assertLessEqual(result["utilization"],100)

    def test_business_cutoff_clips_motel_hours_and_is_saved_in_close(self):
        from hospitality_suite.time import business_window
        self.prop=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name,"room_number":"M110"},fields=["*"])[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]
        entered=self.enter()
        with operation():
            self.prop.close_time="06:45:00"
            self.prop.save()
            cutoff=business_window(self.prop)["starts_at"]
            stay=frappe.get_doc("HS Stay",entered["stay"])
            stay.actual_check_in=cutoff-timedelta(minutes=30)
            stay.actual_check_out=cutoff+timedelta(minutes=30)
            stay.status="Checked Out"
            stay.save()
            segment=frappe.get_doc("HS Allocation",{"stay":stay.name})
            segment.starts_at=stay.actual_check_in
            segment.ends_at=stay.actual_check_out
            segment.save(ignore_permissions=True)
        result=reports.summary(self.prop)
        self.assertEqual(result["occupied_hours"],0.5)
        self.assertEqual(result["rotations"],0)
        self.assertEqual(result["close_time"],"06:45:00")
        self.assertIn("T06:45:00",result["local_starts_at"])
        day=str(self.prop.business_date)
        calendar=reports.summary(self.prop,day+" 00:00:00",str(now_datetime().date()+timedelta(days=1))+" 00:00:00")
        self.assertEqual(calendar["occupied_hours"],1)
        self.assertEqual(calendar["rotations"],1)
        close=self.call("daily_close",dict(confirm=False))
        snapshot=frappe.parse_json(frappe.db.get_value("HS Daily Close",close["close"],"summary"))
        self.assertEqual(snapshot["occupied_hours"],0.5)
        self.assertEqual(snapshot["local_ends_at"],result["local_ends_at"])
        self.assertEqual(close["period"]["close_time"],"06:45:00")
        for invalid in ("25:00:00","06:00:00+02:00"):
            with self.assertRaises(frappe.ValidationError):
                api.save_setup(self.prop.name,"property",dict(close_time=invalid),uuid.uuid4().hex,str(self.prop.modified))
        self.assertEqual(str(frappe.db.get_value("HS Property",self.prop.name,"close_time")),"6:45:00")
