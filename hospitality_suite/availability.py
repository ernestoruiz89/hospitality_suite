from hospitality_suite.service import current_all, locked_doc
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime


def overlapping(start, end, other_start, other_end):
    return get_datetime(start) < get_datetime(other_end) and get_datetime(end) > get_datetime(other_start)


def active_allocations(prop, start, end, exclude=None):
    rows = current_all("HS Allocation", filters={"property": prop.name, "status": "Active"}, fields=["*"])
    excluded = set(exclude or [])
    result=[]
    for row in rows:
        if row.name in excluded:
            continue
        if row.kind=="Maintenance" and not row.ends_at:
            # Project an open block only to this query's horizon; never store a
            # fabricated deadline or silently release it as time passes.
            row.ends_at=get_datetime(end)
        if row.kind=="Stay" and row.stay and get_datetime(row.ends_at)<=now_datetime():
            stay=locked_doc("HS Stay",row.stay)
            if stay.status=="Active" and stay.room==row.room:
                row.ends_at=max(get_datetime(row.ends_at),get_datetime(end))
        if overlapping(start,end,row.starts_at,get_datetime(row.ends_at)+timedelta(minutes=row.buffer_minutes or 0)):
            result.append(row)
    return result


def capacity(prop, category, start, end, exclude=None, proposed=None,buffer_minutes=None):
    """The same interval sweep serves reports, quotes and locked mutations.

    Physical candidates are alternatives: roomless demand reduces category
    capacity even when it has not selected any particular candidate yet.
    """
    start, end = get_datetime(start), get_datetime(end)
    if start >= end:
        frappe.throw(frappe._("El intervalo debe tener duración positiva"))
    cat = locked_doc("HS Category", category)
    if cat.property != prop.name:
        frappe.throw(frappe._("Categoría de otro establecimiento"), frappe.PermissionError)
    rooms = current_all("HS Room", filters={"property": prop.name, "category": category, "active": 1}, fields=["name", "cleaning_status"])
    end_buffer = end + timedelta(minutes=(prop.cleaning_minutes or 0) if buffer_minutes is None else buffer_minutes)
    rows = active_allocations(prop, start, end_buffer, exclude) + list(proposed or [])
    rows = [r for r in rows if r.category == category and overlapping(start, end_buffer, r.starts_at, get_datetime(r.ends_at)+timedelta(minutes=r.buffer_minutes or 0))]
    events = []
    for row in rows:
        a, b = max(start, get_datetime(row.starts_at)), min(end_buffer, get_datetime(row.ends_at) + timedelta(minutes=row.buffer_minutes or 0))
        if a < b:
            events.extend([(a, 1), (b, -1)])
    count = peak = 0
    for _, delta in sorted(events):
        count += delta
        peak = max(peak, count)
    candidates = [r.name for r in rooms if not any(a.room == r.name for a in rows)]
    return dict(rooms=rooms, candidates=candidates, available=max(0, len(rooms)-peak))


def check(prop, category, start, end, room=None, exclude=None, for_entry=False, proposed=None,buffer_minutes=None):
    inventory = capacity(prop, category, start, end, exclude, proposed,buffer_minutes)
    by_name = {r.name: r for r in inventory["rooms"]}
    if room:
        if room not in by_name:
            frappe.throw(frappe._("La habitación no pertenece a la categoría o está deshabilitada"))
        if for_entry and by_name[room].cleaning_status != "Clean":
            frappe.throw(frappe._("La habitación debe estar limpia e inspeccionada"))
        if for_entry and current_all("HS Stay",filters={"property":prop.name,"room":room,"status":"Active"}):
            frappe.throw(frappe._("La habitación conserva una estancia activa; registre la salida antes de asignarla"))
    if room and room not in inventory["candidates"]:
        frappe.throw(frappe._("La habitación tiene una reserva, estancia o bloqueo en ese intervalo"))
    # Sweep all demand, including roomless reservations and maintenance; half-open
    # endpoints sort releases (-1) before arrivals (+1). No double counting.
    if not inventory["available"]:
        frappe.throw(frappe._("No queda cupo de esta categoría en el intervalo solicitado"))
    return inventory["candidates"]


def check_until_reopened(prop,category,start,room):
    """Check every known future obligation before adding a permanent block.

    Beyond the last finite endpoint only open allocations remain, so checking
    through that frontier also checks the continuing category demand.
    """
    endpoints=[get_datetime(start),now_datetime()]
    for row in current_all("HS Allocation",filters={"property":prop.name,"status":"Active"},fields=["starts_at","ends_at","buffer_minutes"]):
        endpoints.append(get_datetime(row.ends_at or row.starts_at)+timedelta(minutes=row.buffer_minutes or 0))
    try:
        horizon=max(endpoints)+timedelta(days=1)
    except OverflowError:
        frappe.throw(frappe._("Revise las fechas fuera del horizonte de planificación"))
    return check(prop,category,start,horizon,room,buffer_minutes=0)


def expire_locked(prop):
    from hospitality_suite.service import audit
    holds = current_all("HS Booking", filters={"property": prop.name, "status": "Hold", "hold_until": ["<=", now_datetime()]}, pluck="name")
    for name in holds:
        doc = locked_doc("HS Booking", name)
        doc.status, doc.reason = "Cancelled", "Retención temporal vencida"
        doc.save(ignore_permissions=True)
        release(booking=name)
        audit(prop, "Hold expired", doc, doc.reason)
    portal=current_all("HS Portal Request",filters={"property":prop.name,"status":"Hold","hold_until":["<=",now_datetime()]},pluck="name")
    for name in portal:
        doc=locked_doc("HS Portal Request",name)
        doc.status="Expired"
        doc.save(ignore_permissions=True)
        release(portal_request=name)
        audit(prop,"Portal hold expired",doc)
    requested=current_all("HS Portal Request",filters={"property":prop.name,"status":"Requested","request_until":["<=",now_datetime()]},pluck="name")
    for name in requested:
        doc=locked_doc("HS Portal Request",name)
        doc.status="Expired"
        doc.save(ignore_permissions=True)
        audit(prop,"Portal request expired",doc)
    return len(holds)+len(portal)+len(requested)


def release(**filters):
    for name in current_all("HS Allocation", filters={**filters, "status": "Active"}, pluck="name"):
        doc = locked_doc("HS Allocation", name)
        doc.status = "Released"
        doc.save(ignore_permissions=True)  # internal resource records, never a public document action
