"""Property-scoped work queue for cleaning, maintenance and room blocks."""

import frappe
from frappe import _

from hospitality_suite.security import ACTIONS, is_system, require
from hospitality_suite.standalone_accounting import provider, require_pms
from hospitality_suite.time import local


def snapshot(property_name, accounting_provider="pms"):
    prop = require(property_name)
    if provider() != accounting_provider:
        frappe.throw(_("El trabajo de habitaciones no corresponde al modo contable activo"))
    if accounting_provider == "pms":
        require_pms(prop)
    roles = set(frappe.get_roles())
    can = {action: is_system() or bool(roles.intersection(ACTIONS[action]))
           for action in ("clean", "inspect", "maintain", "block", "incident")}
    if not any(can.values()):
        frappe.throw(_("No tiene acceso al trabajo de habitaciones"), frappe.PermissionError)
    scope = {"property": prop.name, "company": prop.company}
    rooms = frappe.get_all("HS Room", filters=scope,
        fields=["name", "room_number", "category", "active", "cleaning_status"],
        order_by="room_number asc", limit_page_length=1000)
    tasks = frappe.get_all("HS Cleaning Task", filters={**scope,
        "status": ["in", ["Pending", "In Progress", "Inspection"]]},
        fields=["name", "room", "kind", "priority", "status", "assigned_to",
                "checklist", "notes", "modified"],
        order_by="creation asc", limit_page_length=1000) if can["clean"] or can["inspect"] else []
    for task in tasks:
        task["checklist"] = frappe.parse_json(task.checklist or "{}")
        if not isinstance(task["checklist"], dict):
            frappe.throw(_("La lista de limpieza no es válida"))
    orders = frappe.get_all("HS Maintenance Order", filters={**scope,
        "status": ["in", ["Open", "In Progress"]]},
        fields=["name", "room", "equipment", "title", "kind", "status",
                "blocks_room", "until_reopened", "starts_at", "ends_at",
                "assigned_to", "notes", "evidence", "modified"],
        order_by="creation asc", limit_page_length=1000) if can["maintain"] or can["inspect"] else []
    for order in orders:
        order["starts_at"] = local(order.starts_at, prop).strftime("%Y-%m-%d %H:%M")
        order["ends_at"] = (local(order.ends_at, prop).strftime("%Y-%m-%d %H:%M")
                            if order.ends_at else None)
    blocks = []
    if can["block"]:
        from hospitality_suite.room_blocks import board
        blocks = board(prop)["active"]
        for block in blocks:
            block["starts_at"] = local(block.starts_at, prop).strftime("%Y-%m-%d %H:%M")
            block["ends_at"] = local(block.ends_at, prop).strftime("%Y-%m-%d %H:%M")
    return {"property": prop.name, "time_zone": prop.time_zone,
        "inspection_required": bool(prop.inspection_required),
        "can": can, "rooms": rooms, "tasks": tasks,
        "maintenance": orders, "room_blocks": blocks}


def incident_page(property_name, status="Open", offset=0, page_length=25,
                  search="", room=""):
    """Read open cases or resolved history without an unbounded snapshot."""
    prop = require(property_name)
    roles = set(frappe.get_roles())
    if not is_system() and not any(roles.intersection(ACTIONS[action])
            for action in ("incident", "inspect", "report")):
        frappe.throw(_("No tiene acceso a las novedades"), frappe.PermissionError)
    if status not in ("Open", "Resolved"):
        frappe.throw(_("Seleccione un estado válido de novedades"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación de novedades"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(_("Revise la paginación de novedades"))
    if (not isinstance(search, str) or len(search) > 100 or
            not isinstance(room, str) or len(room) > 140):
        frappe.throw(_("Revise los filtros de novedades"))
    if room and not frappe.db.exists("HS Room", {"name": room, "property": prop.name,
            "company": prop.company}):
        frappe.throw(_("Seleccione una habitación del establecimiento"),
            frappe.PermissionError)
    where = "property=%s AND company=%s AND status=%s AND kind IN ('Damage','Lost Property')"
    values = [prop.name, prop.company, status]
    if room:
        where += " AND room=%s"
        values.append(room)
    if search.strip():
        where += " AND (name LIKE %s OR description LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 2)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabHS Incident` WHERE " + where,
        values, as_list=True)[0][0]
    rows = frappe.db.sql(
        "SELECT name,room,kind,description,status,evidence,resolution,resolved_by,"
        "resolved_at,creation,modified FROM `tabHS Incident` WHERE " + where +
        " ORDER BY creation DESC,name DESC LIMIT %s OFFSET %s",
        [*values, page_length, offset], as_dict=True)
    for row in rows:
        row["created_at"] = local(row.pop("creation"), prop).strftime("%Y-%m-%d %H:%M")
        row["resolved_at"] = (local(row.resolved_at, prop).strftime("%Y-%m-%d %H:%M")
            if row.resolved_at else None)
    return {"property": prop.name, "status": status, "offset": offset,
        "page_length": page_length, "total": int(total),
        "has_more": offset + len(rows) < total, "rows": rows}
