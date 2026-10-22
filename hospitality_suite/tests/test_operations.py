from datetime import timedelta
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation


class TestOperations(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        self.motel = frappe.get_doc("HS Property", {"property_name": "Luna Demo · Por tiempo"})
        self.room = frappe.get_all("HS Room", filters={"property": self.prop.name}, fields=["*"], order_by="room_number")[0]
        self.guest = frappe.get_all("HS Guest", filters={"property": self.prop.name}, fields=["*"])[0]
        self.start = now_datetime().replace(microsecond=0)
        self.end = self.start + timedelta(days=2)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self, action, data, key=None, prop=None):
        return api.execute((prop or self.prop).name, action, key or uuid.uuid4().hex, data)

    def booking_data(self, room=None, start=None, end=None, prop=None):
        prop = prop or self.prop
        data = dict(starts_at=str(start or self.start), ends_at=str(end or self.end), customer=self.guest.customer,
                    guest=self.guest.name, rooms=[dict(category=(room or self.room).category, room=(room or self.room).name, people=2)])
        calculation = api.preview(prop.name, data)
        data["acceptance"] = calculation["acceptance"]
        return data

    def stay(self):
        data = self.booking_data()
        result = self.call("walk_in", data)
        return frappe.get_doc("HS Stay", result["stay"]), result["folio"]

    def test_01_hotel_advance_consumption_checkout_cleaning(self):
        data = self.booking_data()
        booking = self.call("reserve", data)
        shift = self.call("open_shift", dict(opening_amount=0))["shift"]
        method = frappe.db.get_value("HS Payment Method", {"property": self.prop.name})
        advance = self.call("payment", dict(booking=booking["booking"], shift=shift, method=method, amount=500, kind="Advance"))
        entered = self.call("check_in", dict(booking=booking["booking"], modified=booking["modified"], guest=self.guest.name))
        stay, folio = entered["stay"], entered["folio"]
        request = self.call("request_service", dict(stay=stay, folio=folio, item="HS-DEMO-WATER", quantity=2))
        service = frappe.get_doc("HS Service Request", request["service"])
        self.call("update_service", dict(service=service.name, status="Delivered", modified=str(service.modified)))
        invoice_result = self.call("invoice", dict(folio=folio))
        invoice = frappe.get_doc("Sales Invoice", invoice_result["invoice"])
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.total_advance, 500)
        self.assertEqual(invoice.grand_total, 3060)
        self.assertEqual(invoice.outstanding_amount, 2560)
        pe = frappe.get_doc("Payment Entry", advance["payment_entry"])
        self.assertEqual(pe.unallocated_amount, 0)
        self.call("payment", dict(stay=stay, folio=folio, shift=shift, method=method, amount=2560, kind="Payment"))
        doc = frappe.get_doc("HS Stay", stay)
        result = self.call("check_out", dict(stay=stay, modified=str(doc.modified)))
        self.assertEqual(frappe.db.get_value("HS Room", self.room.name, "cleaning_status"), "Dirty")
        task = frappe.get_doc("HS Cleaning Task", result["cleaning_task"])
        self.call("cleaning", dict(task=task.name, status="In Progress", modified=str(task.modified)))
        task.reload()
        self.call("cleaning", dict(task=task.name, status="Inspection", modified=str(task.modified), checklist={"baño":True,"cama":True,"minibar":True,"superficies":True}))
        task.reload()
        self.call("cleaning", dict(task=task.name, status="Completed", modified=str(task.modified), checklist={"baño":True,"cama":True,"minibar":True,"superficies":True}))
        self.assertEqual(frappe.db.get_value("HS Room", self.room.name, "cleaning_status"), "Clean")

    def test_idempotent_booking_and_changed_payload(self):
        data = self.booking_data()
        key = uuid.uuid4().hex
        first = self.call("reserve", data, key)
        second = self.call("reserve", data, key)
        self.assertEqual(first, second)
        with self.assertRaises(frappe.ValidationError):
            self.call("reserve", {**data, "channel":"Otro"}, key)

    def test_conflicting_room_is_rejected(self):
        data = self.booking_data()
        self.call("reserve", data)
        with self.assertRaises(frappe.ValidationError):
            self.call("reserve", data)

    def test_dirty_room_rejects_checkin(self):
        with operation():
            room = frappe.get_doc("HS Room", self.room.name)
            room.cleaning_status = "Dirty"
            room.save()
        data = self.booking_data()
        with self.assertRaises(frappe.ValidationError):
            self.call("walk_in", data)

    def test_category_last_unit_roomless_then_assign(self):
        rooms = frappe.get_all("HS Room", filters={"property": self.prop.name}, fields=["name", "category"])
        data = self.booking_data()
        data["rooms"] = [dict(category=self.room.category, people=1) for _ in rooms]
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        result = self.call("reserve", data)
        with self.assertRaises(frappe.ValidationError):
            api.preview(self.prop.name, self.booking_data())
        entered = self.call("check_in", dict(booking=result["booking"], modified=result["modified"], room=rooms[0].name, guest=self.guest.name))
        self.assertTrue(entered["stay"])
        self.assertEqual(frappe.db.count("HS Allocation", {"booking":result["booking"], "status":"Active"}), len(rooms))

    def test_extension_rejects_next_booking(self):
        stay, folio = self.stay()
        later = self.booking_data(start=self.end+timedelta(hours=1), end=self.end+timedelta(days=1))
        self.call("reserve", later)
        with self.assertRaises(frappe.ValidationError):
            api.preview(self.prop.name, dict(stay=stay.name, ends_at=str(self.end+timedelta(hours=2))), "extend")

    def test_stock_delivery_only_once_and_reversal(self):
        stay, folio = self.stay()
        result = self.call("request_service", dict(stay=stay.name, folio=folio, item="HS-DEMO-WATER", quantity=1))
        service = frappe.get_doc("HS Service Request", result["service"])
        data = dict(service=service.name, modified=str(service.modified), status="Delivered")
        key = uuid.uuid4().hex
        self.call("update_service", data, key)
        self.call("update_service", data, key)
        service.reload()
        entry = service.stock_entry
        self.assertEqual(frappe.db.get_value("Stock Entry", entry, "docstatus"), 1)
        self.call("update_service", dict(service=service.name, modified=str(service.modified), status="Returned", reason="Prueba de devolución"))
        self.assertEqual(frappe.db.get_value("Stock Entry", entry, "docstatus"), 2)

    def test_cross_property_references_rejected(self):
        data = self.booking_data()
        data["rooms"][0]["category"] = frappe.db.get_value("HS Category", {"property":self.motel.name})
        with self.assertRaises(frappe.PermissionError):
            api.preview(self.prop.name, data)

    def test_housekeeping_cannot_access_finance_or_guest_api(self):
        user = "housekeeping@hospitality.example.invalid"
        frappe.set_user(user)
        data = api.bootstrap(self.prop.name)
        self.assertNotIn("guests", data)
        self.assertNotIn("payments", data)
        with self.assertRaises(frappe.PermissionError):
            self.call("open_shift", dict(opening_amount=0))
        with self.assertRaises(frappe.PermissionError):
            api.report(self.prop.name, "Cobros")

    def test_direct_rest_mutation_cannot_bypass_engine(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(dict(doctype="HS Booking", company=self.prop.company, property=self.prop.name,
                                starts_at=str(self.start), ends_at=str(self.end), customer=self.guest.customer,
                                currency="NIO", amount=1, rooms=[dict(category=self.room.category)], status="Confirmed")).insert()
