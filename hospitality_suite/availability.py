from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime


def overlapping(start, end, other_start, other_end):
    return get_datetime(start) < get_datetime(other_end) and get_datetime(end) > get_datetime(other_start)


def active_allocations(prop, start, end, exclude=None):
    rows = frappe.get_all("HS Allocation", filters={"property": prop.name, "status": "Active"}, fields=["*"])
    excluded = set(exclude or [])
    return [r for r in rows if r.name not in excluded and overlapping(start, end, r.starts_at, get_datetime(r.ends_at) + timedelta(minutes=r.buffer_minutes or 0))]


def check(prop, category, start, end, room=None, exclude=None, for_entry=False, proposed=None):
    start, end = get_datetime(start), get_datetime(end)
    if start >= end:
        frappe.throw("El intervalo debe tener duración positiva")
    cat = frappe.get_doc("HS Category", category)
    if cat.property != prop.name:
        frappe.throw("Categoría de otro establecimiento", frappe.PermissionError)
    rooms = frappe.get_all("HS Room", filters={"property": prop.name, "category": category, "active": 1}, fields=["name", "cleaning_status"])
    by_name = {r.name: r for r in rooms}
    if room:
        if room not in by_name:
            frappe.throw("La habitación no pertenece a la categoría o está deshabilitada")
        if for_entry and by_name[room].cleaning_status != "Clean":
            frappe.throw("La habitación debe estar limpia e inspeccionada")
    end_buffer = end + timedelta(minutes=prop.cleaning_minutes or 0)
    rows = active_allocations(prop, start, end_buffer, exclude) + list(proposed or [])
    rows = [r for r in rows if r.category == category]
    if room and any(r.room == room and overlapping(start, end_buffer, r.starts_at, get_datetime(r.ends_at) + timedelta(minutes=r.buffer_minutes or 0)) for r in rows):
        frappe.throw("La habitación tiene una reserva, estancia o bloqueo en ese intervalo")
    # Sweep all demand, including roomless reservations and maintenance; half-open
    # endpoints sort releases (-1) before arrivals (+1). No double counting.
    events = [(start, 1), (end_buffer, -1)]
    for row in rows:
        a, b = max(start, get_datetime(row.starts_at)), min(end_buffer, get_datetime(row.ends_at) + timedelta(minutes=row.buffer_minutes or 0))
        if a < b:
            events.extend([(a, 1), (b, -1)])
    count = 0
    for _, delta in sorted(events):
        count += delta
        if count > len(rooms):
            frappe.throw("No queda cupo de esta categoría en el intervalo solicitado")
    return [r.name for r in rooms if not any(a.room == r.name for a in rows)]


def expire_locked(prop):
    from hospitality_suite.service import audit
    holds = frappe.get_all("HS Booking", filters={"property": prop.name, "status": "Hold", "hold_until": ["<=", now_datetime()]}, pluck="name")
    for name in holds:
        doc = frappe.get_doc("HS Booking", name)
        doc.status, doc.reason = "Cancelled", "Retención temporal vencida"
        doc.save()
        release(booking=name)
        audit(prop, "Hold expired", doc, doc.reason)
    return len(holds)


def release(**filters):
    for name in frappe.get_all("HS Allocation", filters={**filters, "status": "Active"}, pluck="name"):
        doc = frappe.get_doc("HS Allocation", name)
        doc.status = "Released"
        doc.save(ignore_permissions=True)  # internal resource records, never a public document action
