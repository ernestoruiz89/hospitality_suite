from datetime import timedelta
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,add_days

from hospitality_suite import api
from hospitality_suite.service import operation
from hospitality_suite.jobs import expire_property


class TestLifecycle(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["*"],order_by="room_number")[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]
        self.start=now_datetime().replace(microsecond=0)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def command(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def values(self,**extra):
        values=dict(starts_at=str(self.start),ends_at=str(self.start+timedelta(days=2)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)],**extra)
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        return values

    def test_group_split_folios_has_no_duplicate_charges(self):
        values=self.values()
        other=frappe.get_all("HS Room",filters={"property":self.prop.name,"name":["!=",self.room.name]},fields=["name","category"])[0]
        values["rooms"].append(dict(category=other.category,room=other.name,people=2))
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        booking=self.command("reserve",values)
        one=self.command("check_in",dict(booking=booking["booking"],modified=booking["modified"],guest=self.guest.name))
        booking_doc=frappe.get_doc("HS Booking",booking["booking"])
        two=self.command("check_in",dict(booking=booking_doc.name,modified=str(booking_doc.modified),guest=self.guest.name))
        self.assertNotEqual(one["stay"],two["stay"])
        company_payer=frappe.get_all("HS Guest",filters={"property":self.prop.name,"name":["!=",self.guest.name]},pluck="customer")[0]
        folio=self.command("create_folio",dict(stay=one["stay"],customer=company_payer,label="Empresa"))["folio"]
        charge=frappe.db.get_value("HS Charge",{"stay":one["stay"]})
        self.command("move_charge",dict(charge=charge,folio=folio,reason="Empresa paga alojamiento"))
        inv=self.command("invoice",dict(folio=folio))
        self.assertEqual(frappe.db.get_value("Sales Invoice",inv["invoice"],"customer"),company_payer)
        self.assertEqual(frappe.db.count("HS Charge",{"stay":one["stay"]}),1)

    def test_modify_reservation_quotes_and_releases_old_interval(self):
        result=self.command("reserve",self.values())
        doc=frappe.get_doc("HS Booking",result["booking"])
        values=dict(booking=doc.name,modified=str(doc.modified),starts_at=str(self.start+timedelta(days=5)),ends_at=str(self.start+timedelta(days=8)),reason="Cambio de fechas solicitado")
        values["acceptance"]=api.preview(self.prop.name,values,"modify_reservation")["acceptance"]
        self.command("modify_reservation",values)
        doc.reload()
        self.assertEqual(doc.amount,4500)
        self.assertEqual(frappe.db.count("HS Allocation",{"booking":doc.name,"status":"Active"}),1)
        self.assertTrue(api.preview(self.prop.name,self.values())["acceptance"])

    def test_group_single_invoice_single_balance_and_checkout(self):
        values=self.values()
        room=frappe.get_all("HS Room",filters={"property":self.prop.name,"name":["!=",self.room.name]},fields=["name","category"])[0]
        values["rooms"].append(dict(category=room.category,room=room.name,people=1))
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        booked=self.command("reserve",values)
        first=self.command("check_in",dict(booking=booked["booking"],modified=booked["modified"],guest=self.guest.name))
        booking=frappe.get_doc("HS Booking",booked["booking"])
        second=self.command("check_in",dict(booking=booking.name,modified=str(booking.modified),guest=self.guest.name))
        folio=self.command("create_folio",dict(stay=first["stay"],customer=self.guest.customer,label="Cuenta del grupo",group=1))["folio"]
        for charge in frappe.get_all("HS Charge",filters={"stay":["in",[first["stay"],second["stay"]]]},pluck="name"):
            self.command("move_charge",dict(charge=charge,folio=folio,reason="Facturación consolidada del grupo"))
        shift=self.command("open_shift",dict(opening_amount=0))["shift"]
        method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name})
        self.command("payment",dict(booking=booking.name,folio=folio,shift=shift,method=method,amount=500,kind="Advance"))
        result=self.command("invoice",dict(folio=folio))
        invoice=frappe.get_doc("Sales Invoice",result["invoice"])
        self.assertEqual(len(invoice.items),2)
        self.assertEqual(invoice.total_advance,500)
        self.assertEqual(invoice.grand_total,6000)
        self.command("payment",dict(booking=booking.name,folio=folio,shift=shift,method=method,amount=5500,kind="Payment"))
        self.assertEqual(api.stay_detail(first["stay"])["folios"][-1]["balance"]["outstanding"],"0.00")
        for entry in [first,second]:
            stay=frappe.get_doc("HS Stay",entry["stay"])
            self.command("check_out",dict(stay=stay.name,modified=str(stay.modified)))
        self.assertEqual(frappe.db.get_value("HS Folio",folio,"status"),"Closed")
        self.assertEqual(frappe.db.count("Sales Invoice",{"hs_folio":folio,"docstatus":1}),1)

    def test_hold_expiry_is_idempotent(self):
        result=self.command("reserve",self.values(hold=True))
        with operation():
            booking=frappe.get_doc("HS Booking",result["booking"])
            booking.hold_until=now_datetime()-timedelta(minutes=1)
            booking.save()
        self.assertEqual(expire_property(self.prop.name),1)
        self.assertEqual(expire_property(self.prop.name),0)
        self.assertEqual(frappe.db.get_value("HS Booking",booking.name,"status"),"Cancelled")
        self.assertEqual(frappe.db.count("HS Allocation",{"booking":booking.name,"status":"Active"}),0)

    def test_room_change_retains_segments_and_price(self):
        stay=self.command("walk_in",self.values())
        doc=frappe.get_doc("HS Stay",stay["stay"])
        room=frappe.get_all("HS Room",filters={"property":self.prop.name,"name":["!=",self.room.name]},pluck="name")[0]
        values=dict(stay=doc.name,modified=str(doc.modified),room=room,folio=stay["folio"],reason="Cambio solicitado")
        values["acceptance"]=api.preview(self.prop.name,values,"change_room")["acceptance"]
        self.command("change_room",values)
        self.assertEqual(frappe.db.count("HS Allocation",{"stay":doc.name,"kind":"Stay"}),2)
        self.assertEqual(frappe.db.get_value("HS Stay",doc.name,"amount"),3000)
        self.assertEqual(frappe.db.get_value("HS Room",self.room.name,"cleaning_status"),"Dirty")

    def test_category_change_applies_accepted_price_difference(self):
        with operation():
            cat=frappe.get_doc(dict(doctype="HS Category",company=self.prop.company,property=self.prop.name,category_name="Suite prueba",capacity=3)).insert()
            room=frappe.get_doc(dict(doctype="HS Room",company=self.prop.company,property=self.prop.name,category=cat.name,room_number="TEST-SUITE",active=1,cleaning_status="Clean")).insert()
            frappe.get_doc(dict(doctype="HS Rate",company=self.prop.company,property=self.prop.name,category=cat.name,title="Suite",mode="Hotel",currency="NIO",amount=2000,block_hours=3,rounding_minutes=60,active=1)).insert()
        stay=self.command("walk_in",self.values())
        doc=frappe.get_doc("HS Stay",stay["stay"])
        values=dict(stay=doc.name,modified=str(doc.modified),room=room.name,folio=stay["folio"],reason="Ascenso aceptado")
        quote=api.preview(self.prop.name,values,"change_room")
        self.assertEqual(quote["difference"],"1000.00")
        values["acceptance"]=quote["acceptance"]
        self.command("change_room",values)
        self.assertEqual(frappe.db.get_value("HS Stay",doc.name,"amount"),4000)
        self.assertEqual(frappe.db.count("HS Charge",{"stay":doc.name}),2)

    def test_cancellation_penalty_uses_invoice_and_advance(self):
        with operation():
            self.prop.cancellation_fee_mode="Fixed"
            self.prop.cancellation_fee_value=100
            self.prop.penalty_item=self.prop.lodging_item
            self.prop.save()
        booking=self.command("reserve",self.values())
        shift=self.command("open_shift",dict(opening_amount=0))["shift"]
        method=frappe.db.get_value("HS Payment Method",{"property":self.prop.name})
        self.command("payment",dict(booking=booking["booking"],shift=shift,method=method,amount=500,kind="Advance"))
        doc=frappe.get_doc("HS Booking",booking["booking"])
        values=dict(booking=doc.name,modified=str(doc.modified),status="Cancelled",reason="Cancelación solicitada")
        values["fee_acceptance"]=api.preview(self.prop.name,values,"booking_status")["acceptance"]
        self.command("booking_status",values)
        doc.reload()
        invoice=frappe.get_doc("Sales Invoice",doc.fee_invoice)
        self.assertEqual(invoice.total_advance,100)
        self.assertEqual(invoice.outstanding_amount,0)

    def test_repeated_daily_close_advances_business_date_once(self):
        key=uuid.uuid4().hex
        result=self.command("daily_close",dict(confirm=False),key)
        self.assertEqual(self.command("daily_close",dict(confirm=False),key),result)
        old=self.prop.business_date
        key=uuid.uuid4().hex
        closed=self.command("daily_close",dict(confirm=True),key)
        self.assertEqual(self.command("daily_close",dict(confirm=True),key),closed)
        self.assertEqual(str(frappe.db.get_value("HS Property",self.prop.name,"business_date")),str(add_days(old,1)))

    def test_reopen_last_day_requires_authorization_reason_and_preserves_snapshot(self):
        first=self.command("daily_close",dict(confirm=True))["close"]
        snapshot=frappe.db.get_value("HS Daily Close",first,"summary")
        second=self.command("daily_close",dict(confirm=True))["close"]
        with self.assertRaises(frappe.ValidationError):
            self.command("reopen_day",dict(close=first,reason="Intento de reabrir un día anterior"))
        with self.assertRaises(frappe.ValidationError):
            self.command("reopen_day",dict(close=second))
        frappe.set_user("supervisor@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.command("reopen_day",dict(close=second,reason="Intento sin gerencia"))
        frappe.set_user("Administrator")
        date=frappe.db.get_value("HS Daily Close",second,"business_date")
        self.command("reopen_day",dict(close=second,reason="Corrección sintética del último día"))
        self.assertEqual(frappe.db.get_value("HS Property",self.prop.name,"business_date"),date)
        self.assertEqual(frappe.db.get_value("HS Daily Close",first,"summary"),snapshot)
        self.assertEqual(frappe.db.get_value("HS Daily Close",second,"status"),"Reopened")
