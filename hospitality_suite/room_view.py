"""Scoped, read-only projections for the operational room view."""

from datetime import datetime, time, timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.security import is_system, property_document, require, ACTIONS
from hospitality_suite.time import local, now_local, to_site


VIEW_ACTIONS = ("stay", "finance", "report", "clean", "maintain", "inspect", "ticket", "block", "service")


def _access(property_name):
    prop = require(property_name)
    roles = set(frappe.get_roles())
    if not is_system() and not any(roles.intersection(ACTIONS[action]) for action in VIEW_ACTIONS):
        frappe.throw(frappe._("No tiene acceso a la vista de habitaciones"), frappe.PermissionError)
    return prop


def _capabilities(prop):
    roles = set(frappe.get_roles())
    can = lambda action: is_system() or bool(roles.intersection(ACTIONS[action]))
    return dict(people=can("stay") or can("finance") or can("report"),
                account=can("stay") or can("finance"),
                clean=can("clean"), maintain=can("maintain"), block=can("block"), ticket=can("ticket"),
                inspect=can("inspect"), stay=can("stay"), service=can("service"),
                reserve=can("reserve"), history=can("stay") or can("finance") or can("report"),
                discreet=bool(prop.discreet_mode))


def _rows(dt, prop, fields, **filters):
    return frappe.get_all(dt, filters={"property": prop.name, "company": prop.company, **filters},
                          fields=fields)


def _context(prop, can):
    now = now_datetime()
    day = now_local(prop).date()
    tomorrow = to_site(datetime.combine(day + timedelta(days=1), time()), prop)
    rooms = _rows("HS Room", prop, ["name", "room_number", "category", "floor", "zone", "beds",
                                   "parking", "active", "cleaning_status", "modified"])
    categories = {row.name: row for row in _rows("HS Category", prop,
        ["name", "category_name", "capacity", "max_extra_beds", "amenities", "portal_description", "portal_image"])}
    stays = _rows("HS Stay", prop, ["name", "room", "guest", "booking", "starts_at", "ends_at",
                                   "status", "actual_check_in"], status="Active")
    active = {row.room: row for row in stays if row.room}
    bookings = {row.name: row for row in _rows("HS Booking", prop,
        ["name", "guest", "status", "starts_at", "ends_at", "hold_until"], status=["in", ["Confirmed", "Hold"]])
        if row.status != "Hold" or not row.hold_until or get_datetime(row.hold_until) > now}
    arrivals = {}
    for row in _rows("HS Allocation", prop,
            ["name", "room", "booking", "starts_at", "ends_at"], kind="Reservation", status="Active"):
        booking = bookings.get(row.booking)
        if not row.room or not booking or get_datetime(row.starts_at) >= tomorrow:
            continue
        if row.room not in arrivals or get_datetime(row.starts_at) < get_datetime(arrivals[row.room]["starts_at"]):
            arrivals[row.room] = dict(booking=booking.name, guest=booking.guest, status=booking.status,
                                      starts_at=row.starts_at, ends_at=row.ends_at)
    blocks = {}
    for row in _rows("HS Allocation", prop,
            ["name", "room", "kind", "maintenance", "room_block", "starts_at", "ends_at"],
            kind=["in", ["Maintenance", "Room Block"]], status="Active"):
        if row.room and get_datetime(row.starts_at) <= now and (not row.ends_at or get_datetime(row.ends_at) > now):
            blocks.setdefault(row.room, row)
    tasks = {}
    for row in _rows("HS Cleaning Task", prop,
            ["name", "room", "kind", "priority", "status", "assigned_to", "started_at", "modified"],
            status=["in", ["Pending", "In Progress", "Inspection"]]):
        if row.room:
            tasks.setdefault(row.room, []).append(row)
    orders = {}
    for row in _rows("HS Maintenance Order", prop,
            ["name", "room", "title", "status", "assigned_to", "blocks_room", "starts_at", "ends_at",
             "until_reopened", "modified"], status=["in", ["Open", "In Progress"]]):
        if row.room:
            orders.setdefault(row.room, []).append(row)
    tickets = {}
    if can["ticket"]:
        for row in _rows("HS Guest Ticket", prop,
                ["name", "room", "subject", "priority", "status", "assigned_to", "due_at"],
                status=["in", ["Open", "In Progress"]]):
            if row.room:
                tickets.setdefault(row.room, []).append(row)
    return dict(now=now, day=day, rooms=rooms, categories=categories, active=active,
                arrivals=arrivals, blocks=blocks, tasks=tasks, orders=orders, tickets=tickets)


def _people(prop, ctx, can):
    if not can["people"] or can["discreet"]:
        return {}
    names = {row.guest for row in ctx["active"].values() if row.guest}
    names.update(row["guest"] for row in ctx["arrivals"].values() if row["guest"])
    if not names:
        return {}
    return {row.name: row.full_name for row in _rows("HS Guest", prop,
        ["name", "full_name"], name=["in", list(names)])}


def _summary(room, ctx, can, names):
    stay = ctx["active"].get(room.name)
    arrival = ctx["arrivals"].get(room.name)
    blocked = ctx["blocks"].get(room.name)
    tasks = ctx["tasks"].get(room.name, [])
    orders = ctx["orders"].get(room.name, [])
    tickets = ctx["tickets"].get(room.name, [])
    category = ctx["categories"].get(room.category)
    label = lambda guest: names.get(guest) or frappe._("Huésped registrado")
    return dict(name=room.name, room_number=room.room_number, category=room.category,
                category_label=category.category_name if category else room.category,
                floor=room.floor, zone=room.zone, active=bool(room.active),
                cleaning_status=room.cleaning_status, occupied=bool(stay), blocked=bool(blocked),
                block_kind=blocked.kind if blocked else None,
                arrival=bool(arrival), departure=bool(stay and get_datetime(stay.ends_at) <
                               to_site(datetime.combine(ctx["day"] + timedelta(days=1), time()),
                                       ctx["prop"])),
                overdue_arrival=bool(arrival and get_datetime(arrival["starts_at"]) < ctx["now"]),
                overdue_departure=bool(stay and get_datetime(stay.ends_at) < ctx["now"]),
                work=bool(tasks or orders or tickets), task_count=len(tasks), maintenance_count=len(orders), ticket_count=len(tickets),
                guest_label=label(stay.guest) if stay and can["people"] else None,
                arrival_label=label(arrival["guest"]) if arrival and can["people"] else None,
                stay_start=local(stay.starts_at, ctx["prop"]).isoformat() if stay and can["stay"] else None,
                stay_end=local(stay.ends_at, ctx["prop"]).isoformat() if stay and can["stay"] else None,
                arrival_start=local(arrival["starts_at"], ctx["prop"]).isoformat() if arrival and can["reserve"] else None,
                arrival_end=local(arrival["ends_at"], ctx["prop"]).isoformat() if arrival and can["reserve"] else None,
                stay=stay.name if stay and can["stay"] else None,
                booking=arrival["booking"] if arrival and can["reserve"] else None)


def board_snapshot(property_name):
    prop = _access(property_name)
    can = _capabilities(prop)
    ctx = _context(prop, can)
    ctx["prop"] = prop
    names = _people(prop, ctx, can)
    rooms = [_summary(room, ctx, can, names) for room in ctx["rooms"]]
    rooms.sort(key=lambda row: (str(row["floor"] or ""), str(row["room_number"])))
    return dict(property=prop.name, time_zone=prop.time_zone,
                checked_at=local(ctx["now"], prop).isoformat(), rooms=rooms,
                counts={key:sum(bool(row[key]) for row in rooms) for key in
                        ("occupied", "arrival", "departure", "work", "blocked")})


def room_snapshot(property_name, room_name):
    prop = _access(property_name)
    room = property_document(prop, "HS Room", room_name)
    can = _capabilities(prop)
    ctx = _context(prop, can)
    ctx["prop"] = prop
    names = _people(prop, ctx, can)
    summary = _summary(room, ctx, can, names)
    stay = ctx["active"].get(room.name)
    arrival = ctx["arrivals"].get(room.name)
    category = ctx["categories"].get(room.category)
    current = None
    if stay:
        current = dict(name=stay.name if can["stay"] else None,
                       service_stay=stay.name if can["service"] else None,
                       guest_label=summary["guest_label"], starts_at=local(stay.starts_at, prop).isoformat(),
                       ends_at=local(stay.ends_at, prop).isoformat(), overdue=summary["overdue_departure"])
        if can["account"]:
            from hospitality_suite.accounting import folios_for_stay, folio_balance
            values = {}
            shared = False
            accounts = []
            for folio in folios_for_stay(frappe.get_doc("HS Stay", stay.name)):
                balance = folio_balance(folio.name)
                currency = balance["currency"]
                values[currency] = values.get(currency, 0) + float(balance["outstanding"])
                shared = shared or not bool(folio.stay)
                accounts.append(dict(name=folio.name, label=folio.label,
                                     shared=not bool(folio.stay), **balance))
            current["account_balances"] = [dict(currency=key, outstanding=value)
                                           for key, value in sorted(values.items())]
            current["accounts"] = sorted(accounts, key=lambda row: row["name"])
            current["shared_account"] = shared
            folio_names = [row["name"] for row in accounts]
            current["recent_charges"] = (frappe.get_all("HS Charge", filters={
                "property": prop.name, "company": prop.company, "stay": stay.name,
                "folio": ["in", folio_names],
                "status": ["in", ["Pending", "Scheduled", "Invoiced", "Posted"]]},
                fields=["name", "folio", "description", "amount", "currency", "status"],
                order_by="creation desc, name desc", limit_page_length=8)
                if folio_names else [])
    pending = None
    if arrival:
        pending = dict(booking=arrival["booking"] if can["reserve"] else None,
                       guest_label=summary["arrival_label"], status=arrival["status"],
                       starts_at=local(arrival["starts_at"], prop).isoformat(),
                       ends_at=local(arrival["ends_at"], prop).isoformat(),
                       overdue=summary["overdue_arrival"])
    tasks = [dict(name=row.name, kind=row.kind, status=row.status, priority=row.priority,
                  assigned_to=row.assigned_to, started_at=local(row.started_at, prop).isoformat() if row.started_at else None)
             for row in ctx["tasks"].get(room.name, [])]
    orders = [dict(name=row.name, title=row.title, status=row.status,
                   assigned_to=row.assigned_to, blocks_room=bool(row.blocks_room),
                   until_reopened=bool(row.until_reopened), modified=str(row.modified))
              for row in ctx["orders"].get(room.name, [])]
    tickets = [dict(name=row.name, subject=row.subject, priority=row.priority, status=row.status,
                    assigned_to=row.assigned_to, due_at=local(row.due_at, prop).isoformat() if row.due_at else None)
               for row in ctx["tickets"].get(room.name, [])]
    blocks = _rows("HS Room Block", prop,
                   ["name", "reason", "starts_at", "ends_at", "note", "modified"],
                   room=room.name, status="Active") if can["block"] else []
    details = dict(floor=room.floor, zone=room.zone, beds=room.beds, parking=room.parking,
                   capacity=category.capacity if category else None,
                   max_extra_beds=category.max_extra_beds if category else None,
                   amenities=category.amenities if category else None,
                   description=category.portal_description if category else None,
                   image=category.portal_image if category else None)
    return dict(property=prop.name, room=summary, checked_at=local(ctx["now"], prop).isoformat(),
                time_zone=prop.time_zone, mode=prop.mode, can=can, current=current,
                next_arrival=pending, tasks=tasks, maintenance=orders, room_blocks=blocks,
                tickets=tickets, details=details)


def room_schedule(property_name, room_name, starts_at, ends_at):
    prop = _access(property_name)
    property_document(prop, "HS Room", room_name)
    can = _capabilities(prop)
    if any(not isinstance(value,str) or not value.strip() or len(value)>128 for value in (starts_at,ends_at)):
        frappe.throw(frappe._("Indique fechas válidas para la agenda"))
    try:
        start, end = to_site(starts_at, prop), to_site(ends_at, prop)
    except (ValueError,TypeError,OverflowError):
        frappe.throw(frappe._("Indique fechas válidas para la agenda"))
    if end <= start or end - start > timedelta(days=31):
        frappe.throw(frappe._("Consulte un intervalo positivo de hasta 31 días"))
    from hospitality_suite.housekeeping import maintenance_finished_at
    rows = []
    for row in _rows("HS Allocation", prop,
            ["name", "kind", "status", "booking", "stay", "maintenance", "room_block", "starts_at", "ends_at"],
            room=room_name, starts_at=["<", end]):
        if row.status == "Released" and row.kind == "Reservation":
            continue
        actual_start = get_datetime(row.starts_at)
        actual_end = get_datetime(row.ends_at) if row.ends_at else end
        if row.kind == "Stay" and row.stay:
            stay = frappe.db.get_value("HS Stay", row.stay,
                                      ["room", "status", "actual_check_in", "actual_check_out"], as_dict=True)
            if stay:
                if stay.actual_check_in:
                    actual_start = max(actual_start, get_datetime(stay.actual_check_in))
                if stay.actual_check_out:
                    actual_end = min(actual_end, get_datetime(stay.actual_check_out))
                elif row.status == "Active" and stay.status == "Active" and stay.room == room_name and actual_end < now_datetime():
                    # An overdue, occupied room remains blocked until check-out.
                    actual_end = end
        if row.kind == "Maintenance" and row.status == "Released":
            order = frappe.get_doc("HS Maintenance Order", row.maintenance) if row.maintenance else None
            if not order or order.status != "Completed":
                continue
            actual_end = min(actual_end, maintenance_finished_at(order))
        reason = None
        if row.kind == "Room Block":
            block = frappe.db.get_value("HS Room Block", {"name": row.room_block, "property": prop.name},
                                        ["reason", "status", "released_on"], as_dict=True) if row.room_block else None
            if not block or (row.status == "Released" and block.status != "Released"):
                continue
            reason = block.reason
            if row.status == "Released":
                actual_end = min(actual_end, get_datetime(block.released_on))
        if actual_end <= start or actual_start >= end or actual_end <= actual_start:
            continue
        rows.append(dict(kind=row.kind, status=row.status, starts_at=local(max(start, actual_start), prop).isoformat(),
                         ends_at=local(min(end, actual_end), prop).isoformat(),
                         until_reopened=bool(row.kind == "Maintenance" and not row.ends_at and row.status == "Active"),
                         stay=row.stay if can["stay"] else None,
                         booking=row.booking if can["reserve"] else None,
                         maintenance=row.maintenance if can["maintain"] else None,
                         room_block=row.room_block if can["block"] else None,
                         block_reason=reason))
    rows.sort(key=lambda row: row["starts_at"])
    return dict(property=prop.name, room=room_name, starts_at=local(start, prop).isoformat(),
                ends_at=local(end, prop).isoformat(), time_zone=prop.time_zone, rows=rows)


def _merged_minutes(intervals):
    total = 0
    last_start = last_end = None
    for start, end in sorted(intervals):
        if last_start is None:
            last_start, last_end = start, end
        elif start <= last_end:
            last_end = max(last_end, end)
        else:
            total += (last_end - last_start).total_seconds() / 60
            last_start, last_end = start, end
    if last_start is not None:
        total += (last_end - last_start).total_seconds() / 60
    return total


def room_insights(property_name, days=30):
    """Historical use per physical room; money needs charge-to-room attribution."""
    prop = _access(property_name)
    try:
        days = int(days)
    except (ValueError, TypeError):
        frappe.throw(frappe._("Seleccione un período válido"))
    if days not in (7, 30, 90):
        frappe.throw(frappe._("Seleccione 7, 30 o 90 días"))
    end_day = now_local(prop).date()
    start_day = end_day - timedelta(days=days)
    start = to_site(datetime.combine(start_day, time()), prop)
    end = to_site(datetime.combine(end_day, time()), prop)
    rooms = _rows("HS Room", prop, ["name", "room_number", "category", "floor", "active"])
    categories = {row.name: row.category_name for row in _rows("HS Category", prop, ["name", "category_name"])}
    stats = {room.name: dict(room=room.name, room_number=room.room_number,
                             category_label=categories.get(room.category, room.category), floor=room.floor,
                             active=bool(room.active), usage=[], blocks=[], stays=set(), clean_minutes=[])
             for room in rooms}
    allocations = _rows("HS Allocation", prop,
        ["name", "room", "kind", "status", "stay", "maintenance", "room_block", "starts_at", "ends_at"],
        starts_at=["<", end])
    stay_names = {row.stay for row in allocations if row.kind == "Stay" and row.stay}
    stays = {row.name: row for row in _rows("HS Stay", prop,
        ["name", "room", "status", "actual_check_in", "actual_check_out"], name=["in", list(stay_names)])} if stay_names else {}
    released_orders = {row.maintenance for row in allocations if row.kind == "Maintenance" and
                       row.status == "Released" and row.maintenance}
    orders = {row.name: row for row in _rows("HS Maintenance Order", prop,
        ["name", "status", "modified"], name=["in", list(released_orders)])} if released_orders else {}
    released_blocks = {row.room_block for row in allocations if row.kind == "Room Block" and
                       row.status == "Released" and row.room_block}
    blocks = {row.name: row for row in _rows("HS Room Block", prop,
        ["name", "status", "released_on"], name=["in", list(released_blocks)])} if released_blocks else {}
    from hospitality_suite.housekeeping import maintenance_finished_at
    now = now_datetime()
    for row in allocations:
        target = stats.get(row.room)
        if not target or row.kind not in ("Stay", "Maintenance", "Room Block"):
            continue
        a = get_datetime(row.starts_at)
        b = get_datetime(row.ends_at) if row.ends_at else end
        if row.kind == "Stay":
            stay = stays.get(row.stay)
            if not stay:
                continue
            if stay.actual_check_in:
                a = max(a, get_datetime(stay.actual_check_in))
            if stay.actual_check_out:
                b = min(b, get_datetime(stay.actual_check_out))
            elif row.status == "Active" and stay.status == "Active" and stay.room == row.room and b < now:
                b = max(b, min(now, end))
            bucket = "usage"
        else:
            if row.kind == "Maintenance" and row.status == "Released":
                order = orders.get(row.maintenance)
                if not order or order.status != "Completed":
                    continue
                b = min(b, maintenance_finished_at(order))
            if row.kind == "Room Block" and row.status == "Released":
                block = blocks.get(row.room_block)
                if not block or block.status != "Released" or not block.released_on:
                    continue
                b = min(b, get_datetime(block.released_on))
            bucket = "blocks"
        a, b = max(a, start), min(b, end)
        if a >= b:
            continue
        target[bucket].append((a, b))
        if bucket == "usage":
            target["stays"].add(row.stay)
    for task in _rows("HS Cleaning Task", prop,
            ["room", "status", "started_at", "completed_at"], status="Completed"):
        target = stats.get(task.room)
        if not target or not task.completed_at:
            continue
        finished = get_datetime(task.completed_at)
        if not start <= finished < end:
            continue
        if task.started_at:
            minutes = (finished - get_datetime(task.started_at)).total_seconds() / 60
            if 1 <= minutes <= 480:
                target["clean_minutes"].append(minutes)
        target.setdefault("completed_cleans", 0)
        target["completed_cleans"] += 1
    checkpoints = [to_site(datetime.combine(start_day + timedelta(days=i+1), time()), prop) -
                   timedelta(seconds=1) for i in range(days)]
    period_minutes = (end - start).total_seconds() / 60
    result = []
    for row in stats.values():
        used = _merged_minutes(row["usage"])
        blocked = _merged_minutes(row["blocks"])
        available = max(0, period_minutes - blocked)
        nights = sum(any(a <= point < b for a, b in row["usage"]) for point in checkpoints)
        blocked_nights = sum(any(a <= point < b for a, b in row["blocks"]) for point in checkpoints)
        cleans = row.pop("clean_minutes")
        row.pop("usage")
        row.pop("blocks")
        row["rotations"] = len(row.pop("stays"))
        row["occupied_nights"] = nights
        row["blocked_nights"] = blocked_nights
        row["used_hours"] = round(used / 60, 1)
        row["blocked_hours"] = round(blocked / 60, 1)
        row["sellable_hours"] = round(available / 60, 1)
        row["utilization_pct"] = round(100 * used / available, 1) if available else None
        row["completed_cleans"] = row.get("completed_cleans", 0)
        row["timed_cleans"] = len(cleans)
        row["avg_clean_minutes"] = round(sum(cleans) / len(cleans), 1) if cleans else None
        result.append(row)
    result.sort(key=lambda row: (-row["used_hours"], row["room_number"]))
    return dict(property=prop.name, days=days, mode=prop.mode, time_zone=prop.time_zone,
                from_date=str(start_day), through_date=str(end_day - timedelta(days=1)),
                checked_at=local(now, prop).isoformat(),
                denominator="Horas calendario menos bloqueos de mantenimiento y operativos; no descuenta limpieza ni inactividad histórica",
                revenue_available=False, rooms=result)
