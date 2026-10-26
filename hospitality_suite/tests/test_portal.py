from datetime import timedelta
import hashlib
import json
import time
import uuid
from unittest.mock import patch

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

    def test_guest_portal_requires_signed_booking_claim_and_matching_account(self):
        with operation():
            self.prop.portal_enabled = 1
            self.prop.save()
        guest = frappe.get_doc("HS Guest", {"property": self.prop.name})
        owner_email = f"portal-{uuid.uuid4().hex}@example.invalid"
        other_email = f"portal-{uuid.uuid4().hex}@example.invalid"
        with operation(self.prop):
            guest.email = owner_email
            guest.save()
        for email in (other_email,):
            frappe.get_doc({"doctype": "User", "email": email, "first_name": "Portal",
                            "enabled": 1, "user_type": "Website User",
                            "send_welcome_email": 0}).insert(ignore_permissions=True)
        room = frappe.get_doc("HS Room", {"property": self.prop.name, "active": 1})
        start = now_datetime().replace(microsecond=0) + timedelta(days=35)
        values = {"starts_at": str(start), "ends_at": str(start + timedelta(days=2)),
                  "customer": guest.customer, "guest": guest.name,
                  "rooms": [{"category": room.category, "room": room.name, "people": 2}]}
        values["acceptance"] = api.preview(self.prop.name, values)["acceptance"]
        booking = api.execute(self.prop.name, "reserve", uuid.uuid4().hex, values)["booking"]
        with operation(self.prop):
            token = portal.link(self.prop, {"booking": booking})["url"].split("token=")[1]
        self.assertTrue(portal.confirmation(token)["can_link_guest"])
        guest.reload()
        guest.portal_user = other_email
        with operation(self.prop), self.assertRaises(frappe.PermissionError):
            guest.save()
        guest.reload()

        from frappe.website.page_renderers.template_page import TemplatePage
        frappe.set_user("Guest")
        html = TemplatePage("hospitality-guest").get_html()
        self.assertIn('window.hs_guest_session = {"logged_in": false}', html)
        self.assertIn("guest-", html)
        self.assertNotIn(owner_email, html)
        previous_form = frappe.local.form_dict
        try:
            frappe.local.form_dict = frappe._dict(token=token)
            confirmation_html = TemplatePage("hospitality-confirmation").get_html()
            self.assertIn('"can_link_guest": true', confirmation_html)
            self.assertIn("window.csrf_token", confirmation_html)
            self.assertNotIn(owner_email, confirmation_html)
        finally:
            frappe.local.form_dict = previous_form
        with self.assertRaises(frappe.PermissionError):
            api.request_guest_portal_account(portal.sign({"doctype": "HS Portal Request",
                "name": booking, "expires": int(time.time()) + 600}))
        unavailable_email = f"portal-{uuid.uuid4().hex}@example.invalid"
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Guest", guest.name, "email", unavailable_email)
        frappe.set_user("Guest")
        frappe.db.savepoint("guest_portal_mail_failure")
        with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user",
                   side_effect=frappe.OutgoingEmailError):
            with self.assertRaises(frappe.ValidationError):
                api.request_guest_portal_account(token)
        frappe.db.rollback(save_point="guest_portal_mail_failure")
        self.assertFalse(frappe.db.exists("User", unavailable_email))
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Guest", guest.name, "email", owner_email)
        frappe.set_user("Guest")
        with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user") as send:
            self.assertTrue(api.request_guest_portal_account(token)["requested"])
            send.assert_called_once()
        self.assertEqual(frappe.db.get_value("User", owner_email, "user_type"), "Website User")
        with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user") as send:
            self.assertTrue(api.request_guest_portal_account(token)["requested"])
            send.assert_not_called()
        self.assertIsNone(frappe.db.get_value("HS Guest", guest.name, "portal_user"))

        with self.assertRaises(frappe.PermissionError):
            api.guest_portal_records()
        with self.assertRaises(frappe.PermissionError):
            api.claim_guest_booking(token)
        frappe.set_user(other_email)
        self.assertEqual(api.guest_portal_records()["records"], [])
        with self.assertRaises(frappe.PermissionError):
            api.claim_guest_booking(token)
        self.assertIsNone(frappe.db.get_value("HS Guest", guest.name, "portal_user"))

        frappe.set_user(owner_email)
        self.assertEqual(api.guest_portal_records()["records"], [])
        with self.assertRaises(frappe.PermissionError):
            api.claim_guest_booking(portal.sign({"doctype": "HS Portal Request",
                "name": booking, "expires": int(time.time()) + 600}))
        self.assertEqual(api.claim_guest_booking(token)["booking"], booking)
        self.assertEqual(api.claim_guest_booking(token)["booking"], booking)
        rows = api.guest_portal_records(0, 1)
        self.assertEqual([row["name"] for row in rows["records"]], [booking])
        self.assertEqual(rows["records"][0]["property_name"], self.prop.property_name)
        self.assertFalse(rows["has_more"])
        with self.assertRaises(frappe.ValidationError):
            api.guest_portal_records(0, 51)

        frappe.set_user(other_email)
        self.assertEqual(api.guest_portal_records()["records"], [])
        with self.assertRaises(frappe.PermissionError):
            api.claim_guest_booking(token)
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Guest", guest.name, "email", other_email)
        frappe.set_user(owner_email)
        self.assertEqual(api.guest_portal_records()["records"], [])
        frappe.set_user(other_email)
        self.assertEqual(api.claim_guest_booking(token)["booking"], booking)
        self.assertEqual([row["name"] for row in api.guest_portal_records()["records"]], [booking])
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Guest", guest.name, "email", owner_email)
        frappe.db.set_value("HS Property", self.prop.name, "portal_enabled", 0)
        frappe.set_user(owner_email)
        self.assertEqual(api.guest_portal_records()["records"], [])

    def test_public_category_content_rejects_missing_private_and_unbounded_assets(self):
        category=frappe.get_doc("HS Category",{"property":self.prop.name})
        name=category.name
        category.portal_description="x"*501
        with self.assertRaises(frappe.ValidationError):
            category.save()
        for image in ("/private/files/identity.png","https://example.invalid/room.png","/files/missing-room.png"):
            category=frappe.get_doc("HS Category",name)
            category.portal_description="Vista al jardín"
            category.portal_image=image
            with self.assertRaises(frappe.ValidationError):
                category.save()
        category=frappe.get_doc("HS Category",name)
        category.portal_description="Vista al jardín"
        category.portal_image=None
        category.save()
        with operation():
            self.prop.portal_enabled=1
            self.prop.save()
        frappe.set_user("Guest")
        public=next(item for item in portal.catalog() if item.name==self.prop.name)
        visible=next(item for item in public.categories if item.name==category.name)
        self.assertEqual(visible.portal_description,"Vista al jardín")
        self.assertFalse(visible.portal_image)

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
        self.assertGreaterEqual(float(quote["estimated_total"]),float(quote["amount"]))
        self.assertTrue(quote["explanation"])
        self.assertNotIn("rules",quote)
        data["acceptance"]=quote["acceptance"]
        key=uuid.uuid4().hex
        request=portal.request(self.prop.name,data,key)
        legacy=portal.request_values(data)
        legacy.pop("request_mode")
        name=portal.verify(request["confirmation_url"].split("token=")[1])["name"]
        frappe.db.set_value("HS Portal Request",name,"payload_hash",hashlib.sha256(portal.canonical(legacy).encode()).hexdigest())
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
            self.assertIn("window.hs_confirmation",html)
            self.assertIn("confirmation-",html)
            self.assertIn('"status": "Hold"',html)
            self.assertIn(result["hold_until"].strftime("%Y-%m-%d %H:%M"),html)
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
        queue=api.portal_request_queue(self.prop.name,0,1,"Solicitante ficticio")
        self.assertEqual(queue["total"],1)
        self.assertEqual(queue["rows"][0]["name"],request_doc.name)
        self.assertFalse(queue["rows"][0]["expired"])
        self.assertEqual(queue["rows"][0]["status"],"Hold")
        self.assertEqual(api.portal_request_queue(self.prop.name,1,1,"Solicitante ficticio")["rows"],[])
        self.assertEqual(api.portal_request_queue(self.prop.name,0,1,"missing@example.invalid")["total"],0)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.portal_request_queue(self.prop.name)
        frappe.set_user("Administrator")
        guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["name","customer"])[0]
        values=dict(portal_request=request_doc.name,guest=guest.name,customer=guest.customer)
        values["acceptance"]=api.preview(self.prop.name,values,"convert_portal")["acceptance"]
        converted=api.execute(self.prop.name,"convert_portal",uuid.uuid4().hex,values)
        self.assertTrue(converted["booking"])
        self.assertEqual(frappe.db.count("HS Allocation",{"portal_request":request_doc.name,"status":"Active"}),0)
        self.assertEqual(frappe.db.count("HS Allocation",{"booking":converted["booking"],"status":"Active"}),2)
        self.assertEqual(api.portal_request_queue(self.prop.name,0,25,"Solicitante ficticio")["total"],0)
        frappe.set_user("Guest")
        previous_form=frappe.local.form_dict
        try:
            frappe.local.form_dict=frappe._dict(token=token)
            html=TemplatePage("hospitality-confirmation").get_html()
            self.assertIn('"status": "Converted"',html)
            self.assertIn("window.hs_confirmation",html)
            self.assertNotIn(data["email"],html)
            self.assertNotIn(data["full_name"],html)
        finally:
            frappe.set_user("Administrator")
            frappe.local.form_dict=previous_form

    def test_two_requests_without_hold_compete_at_conversion_and_rejection_is_idempotent(self):
        from hospitality_suite import availability
        with operation():
            self.prop.portal_enabled=1
            self.prop.save()
        cat=frappe.db.get_value("HS Category",{"property":self.prop.name})
        start=now_datetime().replace(microsecond=0)+timedelta(days=40)
        end=start+timedelta(days=2)
        capacity=availability.capacity(self.prop,cat,start,end)["available"]
        self.assertGreater(capacity,0)
        self.assertLessEqual(capacity,10)
        base=dict(category=cat,starts_at=str(start),ends_at=str(end),quantity=capacity,people=1,
                  full_name="Solicitante sin retención",email="request@example.invalid",request_mode="Requested")
        frappe.set_user("Guest")
        first_data=dict(base,acceptance=portal.quote(self.prop.name,base)["acceptance"])
        first=portal.request(self.prop.name,first_data,uuid.uuid4().hex)
        second_key=uuid.uuid4().hex
        second=portal.request(self.prop.name,first_data,second_key)
        self.assertEqual(portal.request(self.prop.name,first_data,second_key)["confirmation_url"],second["confirmation_url"])
        self.assertEqual((first["status"],second["status"]),("Requested","Requested"))
        self.assertIsNone(first["hold_until"])
        self.assertTrue(first["request_until"])
        token=first["confirmation_url"].split("token=")[1]
        names=[portal.verify(url.split("token=")[1])["name"] for url in (first["confirmation_url"],second["confirmation_url"])]
        self.assertEqual(frappe.db.count("HS Allocation",{"portal_request":["in",names]}),0)
        confirmation=portal.confirmation(token)
        self.assertEqual(confirmation["status"],"Requested")
        self.assertIsNone(confirmation["hold_until"])
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.count("HS Portal Request",{"name":["in",names],"status":"Requested"}),2)
        self.assertEqual({row.name for row in api.bootstrap(self.prop.name)["portal_requests"]},set(names))
        guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["name","customer"])[0]
        values=dict(portal_request=names[0],guest=guest.name,customer=guest.customer)
        values["acceptance"]=api.preview(self.prop.name,values,"convert_portal")["acceptance"]
        booked=api.execute(self.prop.name,"convert_portal",uuid.uuid4().hex,values)
        self.assertTrue(booked["booking"])
        self.assertEqual(frappe.db.count("HS Allocation",{"booking":booked["booking"],"status":"Active"}),capacity)
        second_values=dict(values,portal_request=names[1])
        with self.assertRaises(frappe.ValidationError):
            api.preview(self.prop.name,second_values,"convert_portal")
        key=uuid.uuid4().hex
        rejected=api.execute(self.prop.name,"reject_portal",key,{"portal_request":names[1],"reason":"Sin cupo vigente"})
        self.assertEqual(rejected,api.execute(self.prop.name,"reject_portal",key,{"portal_request":names[1],"reason":"Sin cupo vigente"}))
        self.assertEqual(frappe.db.get_value("HS Portal Request",names[1],"status"),"Rejected")

    def test_request_without_hold_expires_without_releasing_other_inventory(self):
        from hospitality_suite import availability
        with operation():
            self.prop.portal_enabled=1
            self.prop.save()
        cat=frappe.db.get_value("HS Category",{"property":self.prop.name})
        start=now_datetime().replace(microsecond=0)+timedelta(days=25)
        data=dict(category=cat,starts_at=str(start),ends_at=str(start+timedelta(days=1)),quantity=1,people=1,
                  full_name="Solicitud vencible",email="expiry@example.invalid",request_mode="Requested")
        frappe.set_user("Guest")
        data["acceptance"]=portal.quote(self.prop.name,data)["acceptance"]
        result=portal.request(self.prop.name,data,uuid.uuid4().hex)
        token=result["confirmation_url"].split("token=")[1]
        name=portal.verify(token)["name"]
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Portal Request",name,"request_until",now_datetime()-timedelta(seconds=1))
        with operation():
            self.assertGreaterEqual(availability.expire_locked(self.prop),1)
        self.assertEqual(frappe.db.get_value("HS Portal Request",name,"status"),"Expired")
        self.assertEqual(frappe.db.count("HS Allocation",{"portal_request":name}),0)
        frappe.set_user("Guest")
        self.assertEqual(portal.confirmation(token)["status"],"Expired")
