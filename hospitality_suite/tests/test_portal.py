from datetime import timedelta
import json
import time
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import portal,api
from hospitality_suite.service import operation


class TestPortal(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_portal_disabled_by_default(self):
        frappe.set_user("Guest")
        self.assertNotIn(self.prop.name,[p.name for p in portal.catalog()])
        with self.assertRaises(frappe.PermissionError):
            portal.enabled(self.prop.name)

    def test_request_hold_signature_conversion_and_expiry(self):
        with operation():
            self.prop.portal_enabled=1
            self.prop.save()
        cat=frappe.db.get_value("HS Category",{"property":self.prop.name})
        start=now_datetime().replace(microsecond=0)+timedelta(days=20)
        data=dict(category=cat,starts_at=str(start),ends_at=str(start+timedelta(days=2)),quantity=2,people=1,
                  full_name="Solicitante ficticio",email="portal@example.invalid")
        frappe.set_user("Guest")
        quote=portal.quote(self.prop.name,data)
        data["acceptance"]=quote["acceptance"]
        key=uuid.uuid4().hex
        request=portal.request(self.prop.name,data,key)
        repeat=portal.request(self.prop.name,data,key)
        self.assertEqual(request["status"],"Hold")
        self.assertEqual(request["hold_until"],repeat["hold_until"])
        token=request["confirmation_url"].split("token=")[1]
        result=portal.confirmation(token)
        # Exercise Frappe's hyphen-to-underscore website controller discovery,
        # including the real template, rather than only the service method.
        from frappe.website.page_renderers.template_page import TemplatePage
        previous_form=frappe.local.form_dict
        try:
            frappe.local.form_dict=frappe._dict(token=token)
            page=TemplatePage("hospitality-confirmation")
            html=page.get_html()
            self.assertIn("Solicitud recibida; pendiente de confirmación manual",html)
            self.assertIn("Esta página no acredita un pago",html)
            self.assertIn("Cupo conservado hasta",html)
            self.assertIn(result["hold_until"].strftime("%d/%m/%Y %H:%M"),html)
            self.assertNotIn(data["email"],html)
        finally:
            frappe.local.form_dict=previous_form
        self.assertNotIn("full_name",result)
        self.assertNotIn("email",result)
        self.assertEqual(result["amount"],6000)
        with self.assertRaises(frappe.PermissionError):
            portal.confirmation(token[:-1]+("0" if token[-1]!="0" else "1"))
        expired=portal.sign(dict(doctype="HS Portal Request",name="unreachable",expires=int(time.time())-10))
        with self.assertRaises(frappe.PermissionError):
            portal.confirmation(expired)
        frappe.set_user("Administrator")
        request_doc=frappe.get_doc("HS Portal Request",{"request_key":frappe.utils.cstr(__import__('hashlib').sha256((self.prop.name+"|"+key).encode()).hexdigest())})
        guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["name","customer"])[0]
        values=dict(portal_request=request_doc.name,guest=guest.name,customer=guest.customer)
        values["acceptance"]=api.preview(self.prop.name,values,"convert_portal")["acceptance"]
        converted=api.execute(self.prop.name,"convert_portal",uuid.uuid4().hex,values)
        self.assertTrue(converted["booking"])
        self.assertEqual(frappe.db.count("HS Allocation",{"portal_request":request_doc.name,"status":"Active"}),0)
        self.assertEqual(frappe.db.count("HS Allocation",{"booking":converted["booking"],"status":"Active"}),2)
