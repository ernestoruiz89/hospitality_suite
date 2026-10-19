from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api


class TestRoleFlow(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["*"],order_by="room_number")[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def test_reception_cashier_cleaning_supervisor_end_to_end(self):
        frappe.set_user("receptionist@hospitality.example.invalid")
        start=now_datetime().replace(microsecond=0)
        data=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        data["acceptance"]=api.preview(self.prop.name,data)["acceptance"]
        entered=self.call("walk_in",data)
        service=self.call("request_service",dict(stay=entered["stay"],folio=entered["folio"],item="HS-DEMO-WATER",quantity=1))
        request=frappe.get_doc("HS Service Request",service["service"])
        self.call("update_service",dict(service=request.name,status="Delivered",modified=str(request.modified)))
        frappe.set_user("cashier@hospitality.example.invalid")
        shift=self.call("open_shift",dict(opening_amount=0))["shift"]
        method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name})
        quote=api.preview(self.prop.name,dict(method=method,amount=1530,tendered=1600),"payment")
        self.assertEqual(quote["change"],"70.00")
        paid=self.call("payment",dict(stay=entered["stay"],folio=entered["folio"],shift=shift,method=method,amount=1530,kind="Payment"))
        self.assertTrue(paid["payment_entry"])
        frappe.set_user("receptionist@hospitality.example.invalid")
        stay=frappe.get_doc("HS Stay",entered["stay"])
        exited=self.call("check_out",dict(stay=stay.name,modified=str(stay.modified)))
        frappe.set_user("housekeeping@hospitality.example.invalid")
        task=frappe.get_doc("HS Cleaning Task",exited["cleaning_task"])
        self.call("cleaning",dict(task=task.name,status="In Progress",modified=str(task.modified)))
        task.reload()
        self.call("cleaning",dict(task=task.name,status="Inspection",modified=str(task.modified),checklist={"baño":True,"cama":True,"minibar":True,"superficies":True}))
        task.reload()
        with self.assertRaises(frappe.PermissionError):
            self.call("cleaning",dict(task=task.name,status="Completed",modified=str(task.modified),checklist={"baño":True,"cama":True,"minibar":True,"superficies":True}))
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.call("cleaning",dict(task=task.name,status="Completed",modified=str(task.modified),checklist={"baño":True,"cama":True,"minibar":True,"superficies":True}))
        self.assertEqual(frappe.db.get_value("HS Room",self.room.name,"cleaning_status"),"Clean")
