"""Laundry money, physical counts, roles, scope and command retries."""
from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api


class TestGuestLaundry(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        room = frappe.get_all("HS Room", filters={"property": self.prop.name},
                              fields=["name", "category"], order_by="room_number")[0]
        guest = frappe.get_doc("HS Guest", {"property": self.prop.name})
        start = now_datetime().replace(microsecond=0)
        values = dict(starts_at=str(start), ends_at=str(start + timedelta(days=2)),
                      guest=guest.name, customer=guest.customer,
                      rooms=[dict(room=room.name, category=room.category, people=1)])
        values["acceptance"] = api.preview(self.prop.name, values)["acceptance"]
        entered = self.call("walk_in", values)
        self.stay, self.folio = entered["stay"], entered["folio"]
        company = frappe.get_doc("Company", self.prop.company)
        item_name = "HS-TEST-LAUNDRY-" + uuid.uuid4().hex[:10]
        self.item = frappe.get_doc(dict(doctype="Item", item_code=item_name,
            item_name="Servicio de lavandería sintético", item_group="Services", stock_uom="Nos",
            is_stock_item=0, is_sales_item=1,
            item_defaults=[dict(company=company.name, income_account=company.default_income_account)])).insert().name
        self.rate = self.call("laundry_rate", dict(garment="Camisa sintética", service_type="Wash & Iron",
                                                   item=self.item, rate=40, express_rate=60))["rate"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self, action, data, key=None, prop=None):
        return api.execute((prop or self.prop).name, action, key or uuid.uuid4().hex, data)

    def _bag(self, quantity=2, express=False, notes=None):
        requested = self.call("laundry_request", dict(stay=self.stay, express=express, notes=notes))
        order = frappe.get_doc("HS Laundry Order", requested["order"])
        self.call("laundry_collect", dict(order=order.name, modified=str(order.modified),
                                          items=[dict(rate=self.rate, quantity=quantity)]))
        for status in ("In Process", "Ready"):
            order.reload()
            self.call("laundry_advance", dict(order=order.name, modified=str(order.modified), status=status))
        order.reload()
        return order

    def test_full_bag_price_snapshot_single_charge_and_retry(self):
        frappe.set_user("housekeeping@hospitality.example.invalid")
        order = self._bag(express=True, notes="<script>alert('laundry')</script>")
        self.assertEqual(order.total, 120)
        self.assertEqual(order.items[0].rate, 60)
        counts = {order.items[0].name: 2}
        self.call("laundry_return", dict(order=order.name, modified=str(order.modified), counts=counts))
        order.reload()
        self.assertEqual(api.bootstrap(self.prop.name)["laundry"]["orders"][0]["name"], order.name)
        frappe.set_user("manager@hospitality.example.invalid")
        rate = frappe.get_doc("HS Laundry Rate", self.rate)
        self.call("laundry_rate", dict(rate_name=rate.name, modified=str(rate.modified), garment=rate.garment,
                                       service_type=rate.service_type, item=self.item, rate=80, express_rate=100))
        frappe.set_user("receptionist@hospitality.example.invalid")
        payload = dict(order=order.name, modified=str(order.modified))
        key = uuid.uuid4().hex
        result = self.call("laundry_deliver", payload, key)
        self.assertEqual(self.call("laundry_deliver", payload, key), result)
        order.reload()
        self.assertEqual(order.billed_total, 120)
        charges = frappe.get_all("HS Charge", filters={"stay": self.stay, "item": self.item}, fields=["name", "amount"])
        self.assertEqual([(row.name, row.amount) for row in charges], [(order.items[0].charge, 120)])
        self.assertEqual(order.items[0].returned_quantity, 2)
        view = api.bootstrap(self.prop.name)["laundry"]["last_30_days"]
        self.assertEqual(view["charges"], 120)
        self.assertEqual([(row.service_type, row.pieces, row.charges) for row in view["by_service"]],
                         [("Wash & Iron", 2, 120)])
        rendered = frappe.get_print("HS Laundry Order", order.name, print_format="HS Comprobante de lavandería")
        self.assertIn("Camisa sintética", rendered)
        self.assertNotIn("<script>alert('laundry')</script>", rendered)
        frappe.set_user("manager@hospitality.example.invalid")
        invoice = self.call("invoice", dict(folio=self.folio))["invoice"]
        invoice_lines = frappe.get_doc("Sales Invoice", invoice).items
        self.assertEqual([(line.item_code, line.amount) for line in invoice_lines if line.item_code == self.item],
                         [(self.item, 120)])
        self.assertEqual(frappe.db.get_value("HS Charge", order.items[0].charge, "status"), "Invoiced")
        frappe.set_user("receptionist@hospitality.example.invalid")
        with self.assertRaises(frappe.ValidationError):
            self.call("laundry_deliver", dict(order=order.name, modified=str(order.modified)))

    def test_shortage_requires_manager_and_bills_returned_quantity(self):
        order = self._bag(quantity=3)
        with self.assertRaisesRegex(frappe.ValidationError, "lavandería pendiente"):
            stay = frappe.get_doc("HS Stay", self.stay)
            self.call("check_out", dict(stay=self.stay, modified=str(stay.modified)))
        self.call("laundry_return", dict(order=order.name, modified=str(order.modified),
                                         counts={order.items[0].name: 2}))
        order.reload()
        frappe.set_user("receptionist@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("laundry_deliver", dict(order=order.name, modified=str(order.modified),
                                               shortage_note="Prenda faltante en custodia"))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("laundry_deliver", dict(order=order.name, modified=str(order.modified),
                                          shortage_note="Prenda faltante en custodia"))
        order.reload()
        self.assertEqual(order.total, 120)
        self.assertEqual(order.billed_total, 80)
        self.assertEqual(frappe.db.get_value("HS Charge", order.items[0].charge, "amount"), 80)
        self.assertEqual(order.shortage_note, "Prenda faltante en custodia")

    def test_scope_invalid_item_and_collected_cancellation(self):
        with self.assertRaises(frappe.ValidationError):
            self.call("laundry_rate", dict(garment="Agua", service_type="Wash & Iron",
                                           item="HS-DEMO-WATER", rate=10))
        other = frappe.get_doc("HS Property", {"property_name": "Luna Demo · Por tiempo"})
        with self.assertRaises(frappe.PermissionError):
            self.call("laundry_request", dict(stay=self.stay), prop=other)
        order = self._bag()
        frappe.set_user("housekeeping@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("laundry_cancel", dict(order=order.name, modified=str(order.modified), reason="Bolsa en proceso"))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("laundry_cancel", dict(order=order.name, modified=str(order.modified), reason="Pérdida supervisada"))
        self.assertEqual(frappe.db.get_value("HS Laundry Order", order.name, "status"), "Cancelled")

    def test_direct_complimentary_bag_keeps_folio_uncharged(self):
        started = self.call("laundry_collect", dict(stay=self.stay, complimentary=True,
                            items=[dict(rate=self.rate, quantity=1)]))
        order = frappe.get_doc("HS Laundry Order", started["order"])
        for status in ("In Process", "Ready"):
            self.call("laundry_advance", dict(order=order.name, modified=str(order.modified), status=status))
            order.reload()
        self.call("laundry_return", dict(order=order.name, modified=str(order.modified),
                                         counts={order.items[0].name: 1}))
        order.reload()
        self.call("laundry_deliver", dict(order=order.name, modified=str(order.modified)))
        order.reload()
        self.assertTrue(order.complimentary)
        self.assertEqual(order.billed_total, 0)
        self.assertFalse(order.items[0].charge)
