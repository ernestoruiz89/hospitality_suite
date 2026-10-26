"""Operational room board, scoped detail, interval agenda and use measures."""

from datetime import datetime, time, timedelta
from decimal import Decimal
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.time import now_local
from hospitality_suite.time import local


class TestRoomView(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name":"Hotel Jardín Demo"})
        self.rooms = frappe.get_all("HS Room", filters={"property":self.prop.name},
                                    fields=["name","room_number","category"], order_by="room_number")
        self.guest = frappe.get_doc("HS Guest", {"property":self.prop.name})

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def command(self, action, data):
        return api.execute(self.prop.name, action, uuid.uuid4().hex, data)

    def test_board_detail_people_permissions_and_scope(self):
        start = now_datetime().replace(microsecond=0)
        data = dict(starts_at=str(start), ends_at=str(start+timedelta(days=1)),
                    guest=self.guest.name, customer=self.guest.customer,
                    rooms=[dict(room=self.rooms[0].name, category=self.rooms[0].category, people=1)])
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        entered = self.command("walk_in", data)
        board = api.room_board_snapshot(self.prop.name)
        row = next(r for r in board["rooms"] if r["name"] == self.rooms[0].name)
        self.assertTrue(row["occupied"])
        self.assertEqual(row["stay"], entered["stay"])
        detail = api.room_snapshot(self.prop.name, self.rooms[0].name)
        self.assertEqual(detail["current"]["name"], entered["stay"])
        self.assertEqual(detail["current"]["service_stay"], entered["stay"])
        self.assertIn("account_balances", detail["current"])
        self.assertTrue(detail["current"]["accounts"])
        self.assertTrue(all(row["name"] and "pending" in row and "outstanding" in row
                            for row in detail["current"]["accounts"]))
        self.assertTrue(all(row["folio"] in {account["name"] for account in detail["current"]["accounts"]}
                            and row["currency"] == self.prop.currency
                            for row in detail["current"]["recent_charges"]))
        services = api.erp_service_snapshot(self.prop.name, entered["stay"])
        self.assertEqual([row["name"] for row in services["stays"]], [entered["stay"]])
        self.assertIn(entered["folio"],
                      [row["name"] for row in services["stays"][0]["folios"]])
        other_property = frappe.db.get_value("HS Property",
                                             {"name": ["!=", self.prop.name]}, "name")
        with self.assertRaises(frappe.PermissionError):
            api.erp_service_snapshot(other_property, entered["stay"])
        self.assertEqual(detail["room"]["category"], self.rooms[0].category)
        frappe.set_user("housekeeping@hospitality.example.invalid")
        clean_row = next(r for r in api.room_board_snapshot(self.prop.name)["rooms"]
                         if r["name"] == self.rooms[0].name)
        self.assertTrue(clean_row["occupied"])
        self.assertIsNone(clean_row["guest_label"])
        self.assertIsNone(clean_row["stay"])
        clean_detail = api.room_snapshot(self.prop.name, self.rooms[0].name)
        self.assertNotIn("account_balances", clean_detail["current"])
        self.assertNotIn("accounts", clean_detail["current"])
        self.assertNotIn("recent_charges", clean_detail["current"])
        self.assertIsNone(clean_detail["current"]["service_stay"])
        other = frappe.db.get_value("HS Room", {"property":["!=",self.prop.name]}, "name")
        with self.assertRaises(frappe.PermissionError):
            api.room_snapshot(self.prop.name, other)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.room_board_snapshot(self.prop.name)

    def test_role_projection_and_discreet_mode(self):
        start = now_datetime().replace(microsecond=0)
        data = dict(starts_at=str(start), ends_at=str(start+timedelta(days=1)),
                    guest=self.guest.name, customer=self.guest.customer,
                    rooms=[dict(room=self.rooms[0].name, category=self.rooms[0].category, people=1)])
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        self.command("walk_in", data)
        cases = [
            ("receptionist@hospitality.example.invalid", True, True, True),
            ("cashier@hospitality.example.invalid", True, True, False),
            ("auditor@hospitality.example.invalid", True, False, False),
            ("housekeeping@hospitality.example.invalid", False, False, False),
            ("maintenance@hospitality.example.invalid", False, False, False),
            ("supervisor@hospitality.example.invalid", True, True, True),
        ]
        for user, people, account, stay_link in cases:
            with self.subTest(user=user):
                frappe.set_user(user)
                detail = api.room_snapshot(self.prop.name, self.rooms[0].name)
                self.assertEqual(bool(detail["room"]["guest_label"]), people)
                self.assertEqual("account_balances" in detail["current"], account)
                self.assertEqual("accounts" in detail["current"], account)
                self.assertEqual("recent_charges" in detail["current"], account)
                self.assertEqual(bool(detail["current"]["name"]), stay_link)
                self.assertEqual(bool(detail["current"]["service_stay"]),
                                 user not in ("auditor@hospitality.example.invalid",
                                              "housekeeping@hospitality.example.invalid",
                                              "maintenance@hospitality.example.invalid"))
        frappe.set_user("Administrator")
        frappe.db.set_value("HS Property", self.prop.name, "discreet_mode", 1)
        frappe.set_user("receptionist@hospitality.example.invalid")
        hidden = api.room_snapshot(self.prop.name, self.rooms[0].name)
        self.assertEqual(hidden["room"]["guest_label"], "Huésped registrado")
        self.assertEqual(hidden["current"]["guest_label"], "Huésped registrado")

    def test_delivered_consumption_updates_room_account(self):
        start = now_datetime().replace(microsecond=0)
        data = dict(starts_at=str(start), ends_at=str(start + timedelta(days=1)),
                    guest=self.guest.name, customer=self.guest.customer,
                    rooms=[dict(room=self.rooms[0].name,
                                category=self.rooms[0].category, people=1)])
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        entered = self.command("walk_in", data)
        before = api.room_snapshot(self.prop.name, self.rooms[0].name)
        account = next(row for row in before["current"]["accounts"]
                       if row["name"] == entered["folio"])
        requested = self.command("request_service", dict(
            stay=entered["stay"], folio=entered["folio"],
            item="HS-DEMO-WATER", quantity=1, included=False))
        service = frappe.get_doc("HS Service Request", requested["service"])
        delivery = dict(service=service.name, modified=str(service.modified),
                        status="Delivered")
        delivery_key = uuid.uuid4().hex
        delivered = api.execute(self.prop.name, "update_service", delivery_key, delivery)
        self.assertEqual(delivered["status"], "Delivered")
        self.assertEqual(api.execute(self.prop.name, "update_service", delivery_key,
                                     delivery), delivered)
        charge = frappe.db.get_value("HS Service Request", service.name, "charge")
        self.assertTrue(charge)
        delivery_snapshot = api.erp_service_snapshot(self.prop.name, entered["stay"])
        delivered_row = next(row for row in delivery_snapshot["requests"]
                             if row["name"] == service.name)
        self.assertEqual(delivered_row["status"], "Delivered")
        self.assertEqual(delivered_row["charge"], charge)
        self.assertEqual(frappe.db.count("HS Charge", {"stay": entered["stay"],
                         "item": "HS-DEMO-WATER", "kind": "Service"}), 1)
        after = api.room_snapshot(self.prop.name, self.rooms[0].name)
        updated = next(row for row in after["current"]["accounts"]
                       if row["name"] == entered["folio"])
        self.assertEqual(Decimal(updated["pending"]) - Decimal(account["pending"]),
                         Decimal(str(service.amount)))
        visible_charge = next(row for row in after["current"]["recent_charges"]
                              if row["name"] == charge)
        self.assertEqual(visible_charge["folio"], entered["folio"])
        self.assertEqual(visible_charge["status"], "Pending")
        self.assertEqual(Decimal(str(visible_charge["amount"])),
                         Decimal(str(service.amount)))

    def test_schedule_keeps_short_motel_block_across_midnight(self):
        self.prop = frappe.get_doc("HS Property", {"property_name":"Luna Demo · Por tiempo"})
        room = frappe.get_all("HS Room", filters={"property":self.prop.name}, fields=["name"], limit=1)[0].name
        day = now_local(self.prop).date()+timedelta(days=20)
        start = datetime.combine(day,time(23,30))
        end = start+timedelta(hours=2)
        self.command("maintenance", dict(room=room,title="Bloqueo de prueba",kind="Corrective",
                                         starts_at=start.isoformat(),ends_at=end.isoformat()))
        result = api.room_schedule(self.prop.name,room,
                                   datetime.combine(day,time()).isoformat(),
                                   datetime.combine(day+timedelta(days=2),time()).isoformat())
        self.assertEqual(result["time_zone"], self.prop.time_zone)
        self.assertTrue(any(row["kind"] == "Maintenance" and
                            row["starts_at"].startswith(str(day)) and
                            row["ends_at"].startswith(str(day+timedelta(days=1))) for row in result["rows"]))
        with self.assertRaises(frappe.ValidationError):
            api.room_schedule(self.prop.name,room,"2026-01-02","2026-01-01")

    def test_schedule_keeps_overdue_active_stay_blocked(self):
        now = now_datetime().replace(microsecond=0)
        room = self.rooms[0]
        data = dict(starts_at=str(now), ends_at=str(now+timedelta(days=1)),
                    guest=self.guest.name, customer=self.guest.customer,
                    rooms=[dict(room=room.name, category=room.category, people=1)])
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        entered = self.command("walk_in", data)
        past = now-timedelta(hours=2)
        frappe.db.set_value("HS Stay", entered["stay"], "ends_at", past)
        frappe.db.set_value("HS Allocation", {"stay": entered["stay"], "status": "Active"}, "ends_at", past)
        after = now+timedelta(hours=3)
        result = api.room_schedule(self.prop.name, room.name,
                                   local(now-timedelta(hours=1), self.prop).isoformat(),
                                   local(after, self.prop).isoformat())
        self.assertTrue(any(row["kind"] == "Stay" and
                            row["ends_at"] == local(after, self.prop).isoformat()
                            for row in result["rows"]))

    def test_room_change_does_not_extend_released_old_room(self):
        now = now_datetime().replace(microsecond=0)
        room = self.rooms[0]
        data = dict(starts_at=str(now), ends_at=str(now+timedelta(days=1)),
                    guest=self.guest.name, customer=self.guest.customer,
                    rooms=[dict(room=room.name, category=room.category, people=1)])
        data["acceptance"] = api.preview(self.prop.name, data)["acceptance"]
        entered = self.command("walk_in", data)
        stay = frappe.get_doc("HS Stay", entered["stay"])
        change = dict(stay=stay.name, folio=entered["folio"], room=self.rooms[1].name,
                      modified=str(stay.modified), reason="Cambio de prueba")
        change["acceptance"] = api.preview(self.prop.name, change, "change_room")["acceptance"]
        self.command("change_room", change)
        old = frappe.db.get_value("HS Allocation", {"stay": stay.name, "room": room.name}, "name")
        frappe.db.set_value("HS Allocation", old,
                            {"starts_at": now-timedelta(hours=5), "ends_at": now-timedelta(hours=2)})
        frappe.db.set_value("HS Stay", stay.name, "actual_check_in", now-timedelta(hours=6))
        result = api.room_schedule(self.prop.name, room.name,
                                   local(now, self.prop).isoformat(),
                                   local(now+timedelta(hours=3), self.prop).isoformat())
        self.assertFalse(any(row["kind"] == "Stay" for row in result["rows"]))

    def test_reopening_blocked_room_creates_cleaning_inside_same_command(self):
        room = self.rooms[-1].name
        start = now_datetime().replace(microsecond=0)+timedelta(days=25)
        created = self.command("maintenance",dict(room=room,title="Reparación de prueba",kind="Preventive",
                                                   starts_at=str(start),ends_at=str(start+timedelta(hours=2))))
        order = frappe.get_doc("HS Maintenance Order",created["order"])
        self.command("maintenance",dict(order=order.name,modified=str(order.modified),status="Completed"))
        self.assertEqual(frappe.db.get_value("HS Allocation",{"maintenance":order.name},"status"),"Released")
        self.assertEqual(frappe.db.get_value("HS Room",room,"cleaning_status"),"Dirty")
        self.assertTrue(frappe.db.exists("HS Cleaning Task",{"room":room,"status":"Pending"}))

    def test_insights_are_scoped_and_do_not_invent_revenue(self):
        result = api.room_insights(self.prop.name,7)
        self.assertEqual(result["property"],self.prop.name)
        self.assertFalse(result["revenue_available"])
        self.assertEqual(len(result["rooms"]),len(self.rooms))
        self.assertTrue(all("used_hours" in row and "avg_clean_minutes" in row for row in result["rooms"]))
        with self.assertRaises(frappe.ValidationError):
            api.room_insights(self.prop.name,365)
        frappe.set_user("housekeeping@hospitality.example.invalid")
        self.assertTrue(api.room_insights(self.prop.name,7)["rooms"])
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.room_insights(self.prop.name,7)
