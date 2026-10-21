from datetime import timedelta
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation


class TestIncludedServices(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.rooms=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["name","category"])
        self.guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        self.rate=frappe.get_doc("HS Rate",{"property":self.prop.name,"category":self.rooms[0].category})
        with operation():
            self.rate.set("included_services",[dict(item="HS-DEMO-WATER",quantity=2,basis="Night"),dict(item="HS-DEMO-WATER",quantity=1,basis="Stay")])
            self.rate.change_reason='Preparación de tarifa sintética para la prueba';self.rate.save()
        start=now_datetime().replace(microsecond=0)
        self.end=start+timedelta(days=2)
        values=dict(starts_at=str(start),ends_at=str(self.end),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(room=self.rooms[0].name,category=self.rooms[0].category,people=1)])
        self.quote=api.preview(self.prop.name,values)
        self.entered=self.call("walk_in",dict(**values,acceptance=self.quote["acceptance"]))
        self.stay=frappe.get_doc("HS Stay",self.entered["stay"])

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def request(self,quantity):
        return self.call("request_service",dict(stay=self.stay.name,folio=self.entered["folio"],item="HS-DEMO-WATER",quantity=quantity,included=True))

    def test_included_delivery_stock_once_no_extra_invoice_and_return(self):
        self.assertEqual(json.loads(self.stay.service_entitlements),[dict(item="HS-DEMO-WATER",quantity="5.0")])
        initial=frappe.db.get_value("Bin",{"item_code":"HS-DEMO-WATER","warehouse":self.prop.warehouse},"actual_qty")
        request=self.request(4)
        service=frappe.get_doc("HS Service Request",request["service"])
        values=dict(service=service.name,modified=str(service.modified),status="Delivered")
        key=uuid.uuid4().hex
        self.call("update_service",values,key)
        self.call("update_service",values,key)
        service.reload()
        self.assertEqual(service.amount,0)
        self.assertFalse(service.charge)
        self.assertEqual(frappe.db.get_value("Bin",{"item_code":"HS-DEMO-WATER","warehouse":self.prop.warehouse},"actual_qty"),initial-4)
        invoice=self.call("invoice",dict(folio=self.entered["folio"]))["invoice"]
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"grand_total"),3000)
        with self.assertRaises(frappe.ValidationError):
            self.request(2)
        self.call("update_service",dict(service=service.name,modified=str(service.modified),status="Returned",reason="Artículos incluidos sin consumir"))
        self.assertEqual(frappe.db.get_value("Stock Entry",service.stock_entry,"docstatus"),2)
        self.assertTrue(self.request(5)["service"])

    def test_snapshot_room_move_and_extension_do_not_duplicate_stay_benefit(self):
        with operation():
            self.rate.included_services[0].quantity=3
            self.rate.included_services[1].quantity=20
            self.rate.change_reason='Preparación de tarifa sintética para la prueba';self.rate.save()
        self.assertEqual(json.loads(self.stay.service_entitlements)[0]["quantity"],"5.0")
        target=next(r for r in self.rooms if r.name!=self.stay.room)
        values=dict(stay=self.stay.name,room=target.name,folio=self.entered["folio"],modified=str(self.stay.modified),reason="Cambio ficticio")
        q=api.preview(self.prop.name,values,"change_room")
        self.call("change_room",dict(**values,acceptance=q["acceptance"]))
        self.stay.reload()
        self.assertEqual(json.loads(self.stay.service_entitlements)[0]["quantity"],"5.0")
        values=dict(stay=self.stay.name,folio=self.entered["folio"],modified=str(self.stay.modified),ends_at=str(self.end+timedelta(days=1)))
        q=api.preview(self.prop.name,values,"extend")
        self.assertEqual(q["included_services"],[dict(item="HS-DEMO-WATER",quantity="3.0")])
        self.call("extend",dict(**values,acceptance=q["acceptance"]))
        self.stay.reload()
        self.assertEqual(json.loads(self.stay.service_entitlements)[0]["quantity"],"8.0")

    def test_request_reserves_allowance_until_cancelled(self):
        service=frappe.get_doc("HS Service Request",self.request(5)["service"])
        with self.assertRaises(frappe.ValidationError):
            self.request(1)
        self.call("update_service",dict(service=service.name,modified=str(service.modified),status="Cancelled"))
        self.assertTrue(self.request(5)["service"])
