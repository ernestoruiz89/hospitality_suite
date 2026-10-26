"""Rollback-only incident workflow on the ERPNext authority site."""

from datetime import timedelta
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_accounting import provider


def run():
    if provider() != "erpnext" or not frappe.local.site.startswith("hs-cutover-race"):
        frappe.throw("Use únicamente el sitio ERPNext descartable de ensayo")
    previous_user = frappe.session.user
    frappe.set_user("Administrator")
    prop = frappe.get_doc("HS Property", frappe.get_all("HS Property", pluck="name", limit=1)[0])
    for doctype, field in (("HS Incident", "stock_entry"),
                           ("HS Maintenance Order", "stock_entry"),
                           ("HS Maintenance Part", "stock_entry"),
                           ("HS Service Request", "stock_entry"),
                           ("HS Service Request", "return_stock_entry")):
        assert frappe.get_meta(doctype).get_field(field).fieldtype == "Data"
    suffix = uuid4().hex[:8]
    try:
        def fixture(locked):
            category = insert("HS Category", locked, category_name="Incidentes " + suffix,
                capacity=2)
            return insert("HS Room", locked, room_number="INC-" + suffix,
                category=category.name, active=1, cleaning_status="Clean").name

        room = command(prop.name, "setup", "incident-room-" + suffix,
            {"operation": "incident_room_smoke"}, fixture)
        assert any(row["name"] == room for row in api.erp_room_operations(prop.name)["rooms"])
        def maintenance_fixture(locked):
            start = frappe.utils.now_datetime() + timedelta(days=80)
            return insert("HS Maintenance Order", locked, room=room,
                title="Repuestos ERP " + suffix, starts_at=start,
                ends_at=start + timedelta(hours=1), kind="Corrective",
                blocks_room=0, status="Open").name
        order = command(prop.name, "setup", "erp-parts-order-" + suffix,
            {"operation": "erp_parts_board_smoke"}, maintenance_fixture)
        parts = api.maintenance_parts_board(prop.name, order)
        assert parts["provider"] == "erpnext" and parts["order"] == order
        assert parts["cost"] in ("0", "0.0", "0.00") and not parts["parts"]
        linen_board = api.linen_board(prop.name, "Send", page_length=5)
        assert linen_board["provider"] == "erpnext"
        assert linen_board["direction"] == "Send" and "history" in linen_board
        details = {"room": room, "kind": "Damage", "description": "Daño de prueba"}
        created = api.execute(prop.name, "incident", "incident-erp-" + suffix, details)
        assert created == api.execute(prop.name, "incident", "incident-erp-" + suffix, details)
        page = api.room_incident_page(prop.name, room=room)
        row = next(row for row in page["rows"]
            if row["name"] == created["incident"])
        assert row["kind"] == "Damage" and row["room"] == room
        assert page["total"] >= 1
        evidence = frappe.get_doc({"doctype": "File",
            "file_name": "incident-" + suffix + ".txt",
            "content": ("Hospitality Suite incident evidence " + suffix).encode(),
            "is_private": 1, "attached_to_doctype": "HS Incident",
            "attached_to_name": created["incident"]}).insert(ignore_permissions=True)
        api.execute(prop.name, "incident", "incident-erp-evidence-" + suffix,
            {"incident": row["name"], "modified": str(row["modified"]),
             "evidence": evidence.file_url})
        row = next(row for row in api.room_incident_page(prop.name, room=room)["rows"]
            if row["name"] == created["incident"])
        assert row["evidence"] == evidence.file_url
        api.execute(prop.name, "incident", "incident-erp-resolve-" + suffix,
            {"incident": row["name"], "modified": str(row["modified"]),
             "resolve": True, "resolution": "Inspección documentada"})
        assert not any(row["name"] == created["incident"] for row in
            api.room_incident_page(prop.name, room=room)["rows"])
        resolved = next(row for row in api.room_incident_page(prop.name,
            status="Resolved", room=room)["rows"]
            if row["name"] == created["incident"])
        assert resolved["resolution"] == "Inspección documentada"
        assert resolved["evidence"] == evidence.file_url and resolved["resolved_at"]
        frappe.delete_doc("File", evidence.name, ignore_permissions=True)
        return {"provider": provider(), "incident": "created_and_resolved"}
    finally:
        frappe.db.rollback()
        frappe.set_user(previous_user)
