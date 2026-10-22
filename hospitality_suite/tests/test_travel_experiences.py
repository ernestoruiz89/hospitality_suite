"""Agency commission snapshots and experience fulfillment use native ledgers."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api, portal
from hospitality_suite.service import operation


class TestTravelExperiences(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        self.other = frappe.get_doc("HS Property", {"property_name": "Luna Demo · Por tiempo"})
        room = frappe.get_all("HS Room", filters={"property": self.prop.name},
                              fields=["name", "category"], order_by="room_number")[0]
        self.room = room
        self.guest = frappe.get_doc("HS Guest", {"property": self.prop.name})
        code = "HS-EXP-" + uuid.uuid4().hex[:10]
        self.item = frappe.get_doc(dict(doctype="Item", item_code=code, item_name="Tour sintético",
            item_group="Services", stock_uom="Nos", is_stock_item=0, is_sales_item=1,
            is_purchase_item=1)).insert().name
        price_list = self.prop.price_list or frappe.db.get_single_value("Selling Settings", "selling_price_list")
        frappe.get_doc(dict(doctype="Item Price", item_code=self.item, price_list=price_list,
                            price_list_rate=75, currency=self.prop.currency, selling=1)).insert()
        self.agent = self.call("travel_agent", dict(agent_name="Agencia sintética " + uuid.uuid4().hex[:6],
            agent_type="Travel Agent", commission_pct=10, active=1))["agent"]
        self.experience = self.call("experience", dict(experience_name="Tour de prueba", experience_category="Tour",
            item=self.item, duration="2 horas", show_on_booking_page=1, active=1))["experience"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self, action, data, key=None, prop=None):
        return api.execute((prop or self.prop).name, action, key or uuid.uuid4().hex, data)

    def booking_values(self):
        start = now_datetime().replace(microsecond=0)
        return dict(starts_at=str(start), ends_at=str(start + timedelta(days=2)),
            guest=self.guest.name, customer=self.guest.customer,
            rooms=[dict(room=self.room.name, category=self.room.category, people=1)],
            travel_agent=self.agent, experiences=[dict(experience=self.experience, quantity=2)])

    def test_booking_snapshot_fulfillment_and_single_folio_charge(self):
        values = self.booking_values()
        quote = api.preview(self.prop.name, values)
        self.assertEqual(quote["experiences_total"], "150.00")
        self.assertEqual(float(quote["estimated_total"]), float(quote["amount"]) + 150)
        values["acceptance"] = quote["acceptance"]
        entered = self.call("walk_in", values)
        booking = frappe.get_doc("HS Booking", frappe.db.get_value("HS Stay", entered["stay"], "booking"))
        self.assertEqual(booking.travel_agent, self.agent)
        self.assertEqual(booking.agent_commission_pct, 10)
        self.assertEqual(booking.agent_commission_estimate, booking.amount * .1)
        contribution=next(row for row in api.bootstrap(self.prop.name)["travel_experiences"]["contribution"]
                          if row.travel_agent==self.agent)
        self.assertEqual((contribution.bookings,contribution.accepted_lodging,
                          contribution.estimated_commission),(1,booking.amount,booking.agent_commission_estimate))
        order = frappe.get_doc("HS Experience Order", {"booking": booking.name})
        self.assertEqual((order.amount, order.unit_rate, order.status), (150, 75, "Reserved"))
        agent = frappe.get_doc("HS Travel Agent", self.agent)
        self.call("travel_agent", dict(agent=agent.name, modified=str(agent.modified),
             agent_name=agent.agent_name, agent_type=agent.agent_type, commission_pct=25, active=1))
        self.assertEqual(frappe.db.get_value("HS Booking", booking.name, "agent_commission_pct"), 10)
        self.call("experience_status", dict(order=order.name, modified=str(order.modified),
             status="Confirmed", scheduled_at=str(now_datetime() + timedelta(hours=1))))
        order.reload()
        payload = dict(order=order.name, modified=str(order.modified), status="Delivered",
                       stay=entered["stay"], folio=entered["folio"])
        key = uuid.uuid4().hex
        delivered = self.call("experience_status", payload, key)
        self.assertEqual(self.call("experience_status", payload, key), delivered)
        order.reload()
        self.assertEqual(order.status, "Delivered")
        self.assertEqual(frappe.db.get_value("HS Charge", order.charge, "amount"), 150)
        with self.assertRaises(frappe.ValidationError):
            self.call("experience_status", payload)
        self.call("invoice", dict(folio=entered["folio"]))
        self.assertEqual(frappe.db.get_value("HS Charge", order.charge, "status"), "Invoiced")
        extra=dict(booking=booking.name,experience=self.experience,quantity=1)
        with self.assertRaises(frappe.ValidationError):
            self.call("experience_order",extra)
        extra["acceptance"]=api.preview(self.prop.name,extra,"experience_order")["acceptance"]
        created=self.call("experience_order",extra)
        self.assertEqual(frappe.db.get_value("HS Experience Order",created["order"],"amount"),75)
        with self.assertRaises(frappe.PermissionError):
            self.call("experience_order", dict(booking=booking.name, experience=self.experience, quantity=1),
                      prop=self.other)

    def test_public_visibility_and_commission_purchase_invoice(self):
        with operation():
            self.prop.portal_enabled = 1
            self.prop.save()
        public = next(row for row in portal.catalog() if row.name == self.prop.name)
        self.assertEqual([(row.name, row.price) for row in public.experiences], [(self.experience, "75.00")])
        start = now_datetime() + timedelta(days=80)
        data = dict(category=self.room.category, starts_at=str(start),
                    ends_at=str(start + timedelta(days=2)), quantity=1, people=1,
                    experiences=[dict(experience=self.experience, quantity=2)])
        frappe.set_user("Guest")
        public_quote=portal.quote(self.prop.name, data)
        self.assertEqual(public_quote["experiences_total"], "150.00")
        request=portal.request(self.prop.name,{**data,"acceptance":public_quote["acceptance"],
            "full_name":"Viaje público","email":"viaje@example.invalid"},uuid.uuid4().hex)
        request_name=portal.verify(request["confirmation_url"].split("token=")[1])["name"]
        frappe.set_user("Administrator")
        converted=dict(portal_request=request_name,customer=self.guest.customer,guest=self.guest.name)
        converted["acceptance"]=api.preview(self.prop.name,converted,"convert_portal")["acceptance"]
        reserved=self.call("convert_portal",converted)
        self.assertEqual(frappe.db.get_value("HS Experience Order",{"booking":reserved["booking"]},"amount"),150)
        exp = frappe.get_doc("HS Experience", self.experience)
        self.call("experience", dict(experience=exp.name, modified=str(exp.modified),
            experience_name=exp.experience_name, experience_category=exp.experience_category,
            item=self.item, show_on_booking_page=0, active=1))
        frappe.set_user("Guest")
        with self.assertRaises(frappe.ValidationError):
            portal.quote(self.prop.name, data)
        frappe.set_user("Administrator")
        supplier = self.call("register_supplier", dict(supplier_name="Agente proveedor " + uuid.uuid4().hex[:6]))["supplier"]
        agency = frappe.get_doc("HS Travel Agent", self.agent)
        self.call("travel_agent", dict(agent=agency.name, modified=str(agency.modified),
            agent_name=agency.agent_name, agent_type=agency.agent_type,
            commission_pct=agency.commission_pct, supplier=supplier, active=1))
        with operation():
            self.prop.agent_commission_item = self.item
            self.prop.expense_account = frappe.db.get_value("Account", {"company": self.prop.company,
                "root_type": "Expense", "is_group": 0}, "name")
            self.prop.save()
        values = self.booking_values()
        values["experiences"] = []
        values["acceptance"] = api.preview(self.prop.name, values)["acceptance"]
        entered = self.call("walk_in", values)
        booking_name = frappe.db.get_value("HS Stay", entered["stay"], "booking")
        self.call("invoice", dict(folio=entered["folio"]))
        with operation():
            stay = frappe.get_doc("HS Stay", entered["stay"])
            stay.status = "Checked Out"
            stay.save()
            booking = frappe.get_doc("HS Booking", booking_name)
            booking.status = "Completed"
            booking.save()
        frappe.set_user("cashier@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            api.preview(self.prop.name, dict(booking=booking_name), "agent_commission")
        frappe.set_user("Administrator")
        q = api.preview(self.prop.name, dict(booking=booking_name), "agent_commission")
        self.assertEqual(float(q["amount"]), float(q["base"]) * .1)
        key = uuid.uuid4().hex
        payload = dict(booking=booking_name, modified=q["modified"])
        result = self.call("agent_commission", payload, key)
        self.assertEqual(result, self.call("agent_commission", payload, key))
        invoice = frappe.get_doc("Purchase Invoice", result["invoice"])
        self.assertEqual(invoice.supplier, supplier)
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.items[0].expense_account, self.prop.expense_account)
        self.assertEqual(frappe.db.get_value("HS Booking", booking_name, "agent_commission_invoice"), invoice.name)
        source=frappe.get_doc("Sales Invoice",frappe.db.get_value("HS Charge",{"stay":entered["stay"],
            "kind":"Lodging"},"sales_invoice"))
        source.hs_correction_reason="Corregir alojamiento"
        with self.assertRaises(frappe.ValidationError):
            source.cancel()
        invoice.hs_correction_reason = "Comisión calculada incorrectamente"
        invoice.cancel()
        self.assertFalse(frappe.db.get_value("HS Booking", booking_name, "agent_commission_invoice"))
        self.assertEqual(api.preview(self.prop.name, dict(booking=booking_name), "agent_commission")["amount"], q["amount"])

    def test_draft_keeps_agent_and_experience_until_confirmation(self):
        values=self.booking_values()
        values["mode"]="Hotel"
        saved=self.call("save_booking_draft",dict(values=values))
        detail=api.booking_detail(saved["booking"])["draft"]
        self.assertEqual(detail["travel_agent"],self.agent)
        self.assertEqual(detail["experiences"],[{"experience":self.experience,"quantity":2}])
        review=api.preview(self.prop.name,dict(booking=saved["booking"],modified=saved["modified"]),
                           "confirm_booking_draft")
        payload=dict(booking=saved["booking"],modified=saved["modified"],draft_acceptance=review["draft_acceptance"])
        key=uuid.uuid4().hex
        confirmed=self.call("confirm_booking_draft",payload,key)
        self.assertEqual(confirmed,self.call("confirm_booking_draft",payload,key))
        booking=frappe.get_doc("HS Booking",saved["booking"])
        self.assertEqual((booking.travel_agent,booking.agent_commission_pct),(self.agent,10))
        self.assertEqual(frappe.db.count("HS Experience Order",{"booking":booking.name}),1)
