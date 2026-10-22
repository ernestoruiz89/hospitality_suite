"""Independent, property-scoped holds that remove a physical room from sale."""
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from hospitality_suite import availability
from hospitality_suite.security import require
from hospitality_suite.service import assert_version, audit, current_all, insert, locked_doc
from hospitality_suite.time import to_site


REASONS = ("House Use", "VIP Hold", "Owner", "Maintenance", "Other")


def create(prop, data):
    room = locked_doc("HS Room", data.get("room"))
    if room.property != prop.name or room.company != prop.company or not room.active:
        frappe.throw(frappe._("Seleccione una habitación activa del establecimiento"))
    reason = data.get("reason")
    note = str(data.get("note") or "").strip()
    if reason not in REASONS or (reason == "Other" and not note):
        frappe.throw(frappe._("Seleccione un motivo de bloqueo y explique los otros motivos"))
    values = (data.get("starts_at"), data.get("ends_at"))
    if any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in values):
        frappe.throw(frappe._("Indique inicio y fin del bloqueo"))
    try:
        start, end = (to_site(value, prop) for value in values)
    except (ValueError, TypeError, OverflowError):
        frappe.throw(frappe._("Indique fechas y horas válidas para el bloqueo"))
    if end <= start or end <= now_datetime():
        frappe.throw(frappe._("El bloqueo debe terminar después de su inicio y en el futuro"))
    availability.check(prop, room.category, start, end, room.name, buffer_minutes=0)
    doc = insert("HS Room Block", prop, room=room.name, reason=reason, starts_at=start,
                 ends_at=end, status="Active", note=note[:500], created_by=frappe.session.user)
    allocation = insert("HS Allocation", prop, category=room.category, room=room.name,
                        starts_at=start, ends_at=end, buffer_minutes=0, kind="Room Block",
                        status="Active", room_block=doc.name)
    audit(prop, "Room block created", doc, details=dict(allocation=allocation.name))
    return dict(block=doc.name, status=doc.status, modified=str(doc.modified))


def release(prop, data):
    doc = locked_doc("HS Room Block", data.get("block"))
    assert_version(doc, data.get("modified"))
    if doc.property != prop.name or doc.company != prop.company or doc.status != "Active":
        frappe.throw(frappe._("El bloqueo ya no está activo en este establecimiento"))
    note = str(data.get("reason") or "").strip()
    if not note:
        frappe.throw(frappe._("Explique por qué libera la habitación"))
    allocations = current_all("HS Allocation", filters={"property": prop.name, "company": prop.company,
                               "room_block": doc.name, "kind": "Room Block", "status": "Active"}, pluck="name")
    if len(allocations) != 1:
        frappe.throw(frappe._("El bloqueo no tiene una asignación activa única"))
    doc.status, doc.released_by, doc.released_on = "Released", frappe.session.user, now_datetime()
    doc.release_note = note[:500]
    doc.save()
    allocation = locked_doc("HS Allocation", allocations[0])
    allocation.status = "Released"
    allocation.save(ignore_permissions=True)
    audit(prop, "Room block released", doc, note)
    return dict(block=doc.name, status=doc.status, modified=str(doc.modified))


def board(prop):
    require(prop.name, "block")
    fields = ["name", "room", "reason", "starts_at", "ends_at", "status", "note",
              "created_by", "released_by", "released_on", "release_note", "modified"]
    scope = {"property": prop.name, "company": prop.company}
    active = frappe.get_all("HS Room Block", filters={**scope, "status": "Active"},
                            fields=fields, order_by="starts_at asc", limit=2000)
    recent = frappe.get_all("HS Room Block", filters={**scope, "status": "Released",
                           "released_on": [">=", now_datetime() - timedelta(days=30)]},
                            fields=fields, order_by="released_on desc", limit=100)
    return dict(active=active, recently_released=recent)
