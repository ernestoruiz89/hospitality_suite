from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api,security
from hospitality_suite.service import operation


class TestSecurityRecovery(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.other=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["*"],order_by="room_number")[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def invoke(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def stay(self):
        start=now_datetime().replace(microsecond=0)
        data=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=self.guest.name,customer=self.guest.customer,
                  rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        data["acceptance"]=api.preview(self.prop.name,data)["acceptance"]
        return self.invoke("walk_in",data)

    def test_scoped_lists_links_api_and_private_files(self):
        user="scope-"+uuid.uuid4().hex[:8]+"@example.invalid"
        frappe.get_doc(dict(doctype="User",email=user,first_name="Scope Test",send_welcome_email=0,user_type="System User",roles=[dict(role="HS Receptionist")])).insert()
        with operation():
            frappe.get_doc(dict(doctype="HS Access",company=self.prop.company,property=self.prop.name,user=user)).insert()
        other_guest=frappe.db.get_value("HS Guest",{"property":self.other.name})
        file=frappe.get_doc(dict(doctype="File",file_name="hs-test-"+uuid.uuid4().hex+".txt",content="Fictional private identity attachment",
                                 is_private=1,attached_to_doctype="HS Guest",attached_to_name=other_guest)).insert()
        frappe.set_user(user)
        self.assertEqual(security.allowed_properties(),[self.prop.name])
        self.assertTrue(frappe.has_permission("HS Guest",doc=frappe.get_doc("HS Guest",self.guest.name),ptype="read"))
        self.assertTrue(all(r.property==self.prop.name for r in frappe.get_list("HS Room",fields=["name","property"])))
        with self.assertRaises(frappe.PermissionError):
            api.bootstrap(self.other.name)
        with self.assertRaises(frappe.PermissionError):
            security.document("HS Guest",other_guest)
        self.assertFalse(file.has_permission("read"))
        self.assertFalse(frappe.has_permission("HS Guest",doc=frappe.get_doc("HS Guest",other_guest),ptype="read"))
        frappe.set_user("Administrator")
        file.delete()

    def test_failure_rolls_back_invoice_payment_and_retries_safely(self):
        stay=self.stay()
        shift=self.invoke("open_shift",dict(opening_amount=0))["shift"]
        method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name})
        data=dict(stay=stay["stay"],folio=stay["folio"],shift=shift,method=method,amount=1500,kind="Payment")
        key=uuid.uuid4().hex
        with patch("hospitality_suite.accounting.post_standard",side_effect=RuntimeError("Injected invoice failure")):
            with self.assertRaises(RuntimeError):
                self.invoke("payment",data,key)
        self.assertEqual(frappe.db.count("HS Payment",{"stay":stay["stay"]}),0)
        self.assertEqual(frappe.db.count("Sales Invoice",{"hs_stay":stay["stay"],"docstatus":1}),0)
        self.assertEqual(frappe.db.count("HS Charge",{"stay":stay["stay"],"status":"Pending"}),1)
        result=self.invoke("payment",data,key)
        self.assertTrue(result["payment_entry"])
        self.assertEqual(self.invoke("payment",data,key),result)

    def test_realtime_contains_only_scoped_invalidation(self):
        with patch("frappe.publish_realtime") as publish:
            security.realtime(self.prop.name)
        self.assertTrue(publish.call_count)
        for call in publish.call_args_list:
            self.assertEqual(call.args[1],{"property":self.prop.name})
            self.assertTrue(call.kwargs["after_commit"])
            self.assertIn(call.kwargs["user"],["Administrator"]+frappe.get_all("HS Access",filters={"property":self.prop.name},pluck="user"))

    def test_stale_version_rejected(self):
        stay=self.stay()
        room=frappe.get_all("HS Room",filters={"property":self.prop.name,"name":["!=",self.room.name]},pluck="name")[0]
        with self.assertRaises(frappe.TimestampMismatchError):
            self.invoke("change_room",dict(stay=stay["stay"],room=room,modified="2000-01-01 00:00:00",reason="stale request"))
