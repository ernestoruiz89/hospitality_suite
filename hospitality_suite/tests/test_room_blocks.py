"""Operational room holds share the booking capacity ledger and keep release history."""
from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api, availability


class TestRoomBlocks(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        self.other = frappe.get_doc("HS Property", {"property_name": "Luna Demo · Por tiempo"})
        self.room = frappe.get_all("HS Room", filters={"property": self.prop.name},
                                   fields=["name", "category"], order_by="room_number")[0]
        self.start = now_datetime().replace(microsecond=0) + timedelta(days=100)
        self.end = self.start + timedelta(days=2)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self, action, data, key=None, prop=None):
        return api.execute((prop or self.prop).name, action, key or uuid.uuid4().hex, data)

    def payload(self, **extra):
        values = dict(room=self.room.name, reason="VIP Hold", starts_at=str(self.start),
                      ends_at=str(self.end), note="Visita confirmada por gerencia")
        values.update(extra)
        return values

    def test_block_removes_sale_and_release_restores_it_without_erasing_history(self):
        frappe.set_user("receptionist@hospitality.example.invalid")
        data = self.payload()
        key = uuid.uuid4().hex
        created = self.call("room_block", data, key)
        self.assertEqual(self.call("room_block", data, key), created)
        block = frappe.get_doc("HS Room Block", created["block"])
        allocation = frappe.get_doc("HS Allocation", {"room_block": block.name})
        self.assertEqual((allocation.kind, allocation.status, allocation.room),
                         ("Room Block", "Active", self.room.name))
        self.assertEqual(frappe.db.count("HS Room Block", {"property": self.prop.name}), 1)
        with self.assertRaises(frappe.ValidationError):
            availability.check(self.prop, self.room.category, self.start, self.end, self.room.name)
        self.assertNotIn(self.room.name, availability.capacity(self.prop, self.room.category,
                          self.start, self.end)["candidates"])
        found = api.availability_search(self.prop.name, str(self.start), str(self.end), self.room.category)
        self.assertEqual(next(r["status"] for r in found["room_states"] if r["name"] == self.room.name), "Blocked")
        calendar = api.calendar(self.prop.name, str(self.start), str(self.end))
        self.assertEqual([(r.room_block, r.block_reason) for r in calendar if r.kind == "Room Block"],
                         [(block.name, "VIP Hold")])
        schedule = api.room_schedule(self.prop.name, self.room.name, str(self.start), str(self.end))
        self.assertEqual([(r["room_block"], r["block_reason"]) for r in schedule["rows"]
                          if r["kind"] == "Room Block"], [(block.name, "VIP Hold")])
        snapshot = api.room_snapshot(self.prop.name, self.room.name)
        self.assertTrue(snapshot["can"]["block"])
        self.assertEqual([r.name for r in snapshot["room_blocks"]], [block.name])
        from hospitality_suite.reports import summary
        self.assertEqual(summary(self.prop, str(self.start), str(self.end))["available_hours"], 432)
        board = api.bootstrap(self.prop.name)
        self.assertIn(block.name, [r.name for r in board["room_blocks"]["active"]])
        self.assertIn(self.room.name, [r.room for r in board["blocks"] if r.kind == "Room Block"])
        release_data = dict(block=block.name, modified=str(block.modified), reason="Ya no se necesita")
        release_key = uuid.uuid4().hex
        instant = self.start + timedelta(hours=5)
        with patch("hospitality_suite.room_blocks.now_datetime", return_value=instant):
            released = self.call("room_unblock", release_data, release_key)
        self.assertEqual(self.call("room_unblock", release_data, release_key), released)
        block.reload()
        self.assertEqual((block.status, block.released_by, block.release_note),
                         ("Released", frappe.session.user, "Ya no se necesita"))
        self.assertEqual(frappe.db.get_value("HS Allocation", allocation.name, "status"), "Released")
        self.assertEqual(frappe.db.count("HS Audit Event", {"source_name": block.name,
                          "action": "Room block released"}), 1)
        availability.check(self.prop, self.room.category, self.start, self.end, self.room.name)
        self.assertEqual(summary(self.prop, str(self.start), str(self.end))["available_hours"], 475)
        past = api.calendar(self.prop.name, str(self.start), str(self.end))
        row = next(r for r in past if r.room_block == block.name)
        self.assertEqual(row.ends_at[:16], api.room_schedule(self.prop.name, self.room.name,
                         str(self.start), str(self.end))["rows"][0]["ends_at"][:16])
        self.assertEqual(api.calendar(self.prop.name, str(instant + timedelta(hours=1)),
                         str(instant + timedelta(hours=2))), [])
        history = api.room_history(self.prop.name, self.room.name, str(self.start), str(self.end),
                                   view="periods")
        self.assertTrue(any(r["title"] == "Bloqueo liberado" for r in history["rows"]))

    def test_conflicts_invalid_intervals_roles_and_cross_property_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.call("room_block", self.payload(ends_at=str(self.start)))
        with self.assertRaises(frappe.ValidationError):
            self.call("room_block", self.payload(reason="Other", note=""))
        frappe.set_user("cashier@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("room_block", self.payload())
        frappe.set_user("receptionist@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("room_block", self.payload(), prop=self.other)
        block_name = self.call("room_block", self.payload())["block"]
        with self.assertRaises(frappe.ValidationError):
            self.call("room_block", self.payload(reason="Owner"))
        other_room = frappe.get_all("HS Room", filters={"property": self.other.name}, pluck="name")[0]
        with self.assertRaises(frappe.PermissionError):
            self.call("room_block", self.payload(room=other_room))
        block = frappe.get_doc("HS Room Block", block_name)
        with self.assertRaises(frappe.PermissionError):
            self.call("room_unblock", dict(block=block_name, modified=str(block.modified),
                                            reason="Intento cruzado"), prop=self.other)
        self.assertEqual(frappe.db.get_value("HS Room Block", block_name, "status"), "Active")
