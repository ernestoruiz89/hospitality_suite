"""Transactional reservation and stay commands (caller locks the property)."""
from datetime import timedelta
import hashlib
import json

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite import availability
from hospitality_suite.pricing import quote, money, decimal
from hospitality_suite.service import insert, audit, canonical, assert_version
from hospitality_suite.security import document, require
from hospitality_suite.time import to_site


def quote_request(prop, data):
    start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
    rooms = data.get("rooms") or [data]
    results = []
    proposed = []
    for row in rooms:
        people = int(row.get("people") or 1)
        if people > frappe.db.get_value("HS Category", row["category"], "capacity"):
            frappe.throw("La cantidad de personas supera la capacidad de la categoría")
        availability.check(prop, row["category"], start, end, row.get("room"), proposed=proposed)
        result = quote(prop, row["category"], start, end, people, row.get("rate"), data.get("customer"))
        if result["currency"] != prop.currency:
            frappe.throw("La tarifa debe estar expresada en la moneda del establecimiento")
        result.update(category=row["category"], room=row.get("room"), people=people)
        results.append(result)
        proposed.append(frappe._dict(category=row["category"], room=row.get("room"), starts_at=start, ends_at=end, buffer_minutes=prop.cleaning_minutes))
    response = dict(lines=results, amount=str(money(sum(decimal(r["amount"]) for r in results))), currency=prop.currency)
    response["acceptance"] = hashlib.sha256(canonical(response).encode()).hexdigest()
    return response


def reserve(prop, data):
    availability.expire_locked(prop)
    calculation = quote_request(prop, data)
    if data.get("acceptance") != calculation["acceptance"]:
        frappe.throw("Revise y acepte la cotización vigente antes de reservar")
    if not data.get("rooms"):
        data["rooms"] = [{k: data.get(k) for k in ("category", "room", "people", "rate")}]
    for row, result in zip(data["rooms"], calculation["lines"]):
        row["rate"] = result["rules"]["name"]
    status = "Hold" if data.get("hold") else "Confirmed"
    doc = insert("HS Booking", prop, customer=data["customer"], guest=data.get("guest"),
                 starts_at=to_site(data["starts_at"], prop), ends_at=to_site(data["ends_at"], prop),
                 status=status, rooms=data["rooms"], currency=prop.currency, amount=calculation["amount"],
                 quote_snapshot=canonical(calculation), channel=data.get("channel") or "Recepción", instructions=data.get("instructions"),
                 hold_until=now_datetime() + timedelta(minutes=prop.hold_minutes or 15) if status == "Hold" else None)
    for row in doc.rooms:
        insert("HS Allocation", prop, category=row.category, room=row.room, starts_at=doc.starts_at, ends_at=doc.ends_at,
               buffer_minutes=prop.cleaning_minutes, kind="Reservation", status="Active", booking=doc.name)
    audit(prop, "Reserve", doc, details=calculation)
    return dict(booking=doc.name, status=doc.status, modified=str(doc.modified))


def update_booking(prop, data):
    doc = document("HS Booking", data["booking"], "reserve")
    assert_version(doc, data.get("modified"))
    if doc.status not in ("Hold", "Confirmed", "Draft"):
        frappe.throw("La reserva no admite esta transición")
    target = data["status"]
    if target not in ("Confirmed", "Cancelled", "No Show"):
        frappe.throw("Transición de reserva inválida")
    if target in ("Cancelled", "No Show") and not data.get("reason"):
        frappe.throw("Indique el motivo")
    if target == "No Show" and get_datetime(doc.starts_at) > now_datetime():
        frappe.throw("La llegada todavía no está vencida")
    if doc.status == "Hold" and get_datetime(doc.hold_until) <= now_datetime():
        frappe.throw("La retención ya venció; cree una nueva reserva")
    doc.status, doc.reason = target, data.get("reason")
    if target in ("Cancelled", "No Show"):
        availability.release(booking=doc.name)
    doc.save()
    audit(prop, target, doc, doc.reason)
    return dict(booking=doc.name, status=doc.status)


def charge(prop, stay, folio, item, amount, kind, description, snapshot=None, quantity=1, reason=None):
    return insert("HS Charge", prop, stay=stay.name, folio=folio.name, item=item, quantity=quantity,
                  rate=decimal(amount) / decimal(quantity), amount=amount, currency=folio.currency,
                  business_date=prop.business_date, status="Pending", kind=kind, description=description,
                  quote_snapshot=canonical(snapshot or {}), reason=reason)


def check_in(prop, data):
    availability.expire_locked(prop)
    booking = document("HS Booking", data["booking"], "stay")
    assert_version(booking, data.get("modified"))
    if booking.status not in ("Confirmed", "Checked In"):
        frappe.throw("Confirme la reserva antes de registrar entrada")
    guest = document("HS Guest", data.get("guest") or booking.guest, "stay")
    if prop.guest_id_required and not guest.identity_number:
        frappe.throw("La política requiere identificación del huésped principal")
    allocations = frappe.get_all("HS Allocation", filters={"booking": booking.name, "kind": "Reservation", "status": "Active"}, fields=["*"])
    selected = data.get("allocation")
    alloc = next((r for r in allocations if not selected or r.name == selected), None)
    if not alloc:
        frappe.throw("No queda una habitación pendiente de entrada en esta reserva")
    room_name = data.get("room") or alloc.room
    if not room_name:
        frappe.throw("Seleccione la habitación para esta entrada")
    start = min(get_datetime(booking.starts_at), now_datetime())
    if get_datetime(booking.ends_at) <= now_datetime():
        frappe.throw("El intervalo reservado ha terminado; modifique la reserva")
    availability.check(prop, alloc.category, start, booking.ends_at, room_name, exclude=[alloc.name], for_entry=True)
    accepted = json.loads(booking.quote_snapshot)
    lines = [r for r in accepted["lines"] if r["category"] == alloc.category and (not r.get("room") or r.get("room") == alloc.room)]
    line = lines[0]
    stay = insert("HS Stay", prop, booking=booking.name, guest=guest.name, customer=booking.customer, room=room_name,
                  starts_at=start, ends_at=booking.ends_at, actual_check_in=now_datetime(), status="Active",
                  rate=line["rules"]["name"], currency=prop.currency, amount=line["amount"], quote_snapshot=canonical(line),
                  guests=[dict(guest=guest.name, relationship="Principal")])
    folio = insert("HS Folio", prop, stay=stay.name, customer=stay.customer, currency=prop.currency, status="Open", label="Cuenta principal")
    resource = frappe.get_doc("HS Allocation", alloc.name)
    resource.kind, resource.stay, resource.room, resource.starts_at = "Stay", stay.name, room_name, start
    resource.save(ignore_permissions=True)
    booking.status = "Checked In"
    booking.save()
    if not prop.lodging_item:
        frappe.throw("Configure el artículo de alojamiento")
    charge(prop, stay, folio, prop.lodging_item, line["amount"], "Lodging", "Alojamiento", line)
    audit(prop, "Check in", stay)
    return dict(stay=stay.name, folio=folio.name, room=room_name)


def walk_in(prop, data):
    result = reserve(prop, data)
    return check_in(prop, {**data, "booking": result["booking"], "modified": result["modified"]})


def extension_quote(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    if stay.status != "Active":
        frappe.throw("La estancia ya terminó")
    end = to_site(data["ends_at"], prop)
    if end <= get_datetime(stay.ends_at):
        frappe.throw("La nueva salida debe ser posterior a la actual")
    allocations = frappe.get_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["*"])
    current = max(allocations, key=lambda a: a.starts_at)
    availability.check(prop, current.category, current.starts_at, end, stay.room, exclude=[a.name for a in allocations])
    from hospitality_suite.pricing import calculate
    from hospitality_suite.time import local
    original = json.loads(stay.quote_snapshot)
    calculation = calculate(original["rules"], local(stay.starts_at, prop), local(end, prop), original.get("people", 1), precision=original.get("precision", 2))
    calculation["difference"] = str(money(decimal(calculation["amount"]) - decimal(stay.amount)))
    calculation["acceptance"] = hashlib.sha256(canonical(calculation).encode()).hexdigest()
    return calculation


def extend(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    result = extension_quote(prop, data)
    if result["acceptance"] != data.get("acceptance"):
        frappe.throw("Revise y acepte la nueva cotización")
    stay.ends_at, stay.amount = to_site(data["ends_at"], prop), result["amount"]
    stay.save()
    active = frappe.get_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["name", "starts_at"], order_by="starts_at desc")
    alloc = frappe.get_doc("HS Allocation", active[0].name)
    alloc.ends_at = stay.ends_at
    alloc.save(ignore_permissions=True)
    folio = frappe.get_doc("HS Folio", data["folio"])
    if folio.stay != stay.name or folio.status != "Open":
        frappe.throw("Cuenta inválida")
    if decimal(result["difference"]):
        charge(prop, stay, folio, prop.lodging_item, result["difference"], "Lodging", "Extensión de estancia", result)
    audit(prop, "Extend", stay, data.get("reason"), result)
    return dict(stay=stay.name, amount=result["amount"])


def cleaning_task(prop, room, stay=None):
    doc = frappe.get_doc("HS Room", room)
    doc.cleaning_status = "Dirty"
    doc.save()
    return insert("HS Cleaning Task", prop, room=room, stay=stay, kind="Departure", priority="High", status="Pending",
                  checklist=canonical({"baño": False, "cama": False, "minibar": False, "superficies": False}))


def change_room(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    if stay.status != "Active" or not data.get("reason"):
        frappe.throw("Seleccione una estancia activa e indique el motivo")
    room = document("HS Room", data["room"], "stay")
    if room.category != frappe.db.get_value("HS Room", stay.room, "category"):
        frappe.throw("Para cambiar de categoría, cotice una reserva nueva con la tarifa correspondiente")
    now = now_datetime()
    availability.check(prop, room.category, now, stay.ends_at, room.name, for_entry=True)
    for row in frappe.get_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["name", "ends_at"]):
        alloc = frappe.get_doc("HS Allocation", row.name)
        alloc.ends_at = now
        alloc.save(ignore_permissions=True)
    insert("HS Allocation", prop, category=room.category, room=room.name, starts_at=now, ends_at=stay.ends_at,
           buffer_minutes=prop.cleaning_minutes, kind="Stay", status="Active", booking=stay.booking, stay=stay.name)
    cleaning_task(prop, stay.room, stay.name)
    before = stay.room
    stay.room = room.name
    stay.save()
    audit(prop, "Change room", stay, data["reason"], {"from": before, "to": room.name})
    return dict(stay=stay.name, room=room.name)


def create_folio(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    if stay.status != "Active":
        frappe.throw("La estancia debe estar activa")
    doc = insert("HS Folio", prop, stay=stay.name, customer=data["customer"], currency=prop.currency, label=data.get("label"), status="Open")
    audit(prop, "Create folio", doc)
    return dict(folio=doc.name)


def move_charge(prop, data):
    doc = document("HS Charge", data["charge"], "stay")
    target = document("HS Folio", data["folio"], "stay")
    if doc.status != "Pending" or target.status != "Open" or target.stay != doc.stay or not data.get("reason"):
        frappe.throw("Solo puede trasladar cargos pendientes de la misma estancia con un motivo")
    doc.folio = target.name
    doc.save()
    audit(prop, "Move charge", doc, data["reason"])
    return dict(charge=doc.name, folio=target.name)


def check_out(prop, data):
    from hospitality_suite.accounting import folio_balance, invoice_folio
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    if stay.status != "Active":
        frappe.throw("La estancia ya tiene salida registrada")
    folios = frappe.get_all("HS Folio", filters={"stay": stay.name}, pluck="name")
    for name in folios:
        invoice_folio(prop, {"folio": name})
        balance = folio_balance(name)
        if decimal(balance["outstanding"]) > 0:
            require(prop.name, "approve")
            if not prop.allow_credit or not data.get("credit_reason"):
                frappe.throw("Liquiden el saldo antes de registrar salida o autoricen crédito con motivo")
    guarantee = sum(decimal(p.amount) * (-1 if p.kind == "Guarantee Refund" else 1)
                    for p in frappe.get_all("HS Payment", filters={"stay": stay.name, "status": "Posted", "kind": ["in", ["Guarantee", "Guarantee Refund"]]}, fields=["amount", "kind"]))
    if guarantee:
        frappe.throw("Devuelva o aplique la garantía antes de registrar salida")
    if frappe.db.exists("HS Service Request", {"stay": stay.name, "status": ["in", ["Requested", "In Progress"]]}):
        frappe.throw("Revise los servicios pendientes antes de registrar salida")
    stay.status, stay.actual_check_out, stay.reason = "Checked Out", now_datetime(), data.get("credit_reason")
    stay.save()
    availability.release(stay=stay.name)
    task = cleaning_task(prop, stay.room, stay.name)
    for name in folios:
        doc = frappe.get_doc("HS Folio", name)
        doc.status = "Closed"
        doc.save()
    if stay.booking:
        booking = frappe.get_doc("HS Booking", stay.booking)
        if not frappe.db.exists("HS Stay", {"booking": stay.booking, "status": "Active"}) and not frappe.db.exists("HS Allocation", {"booking": stay.booking, "kind": "Reservation", "status": "Active"}):
            booking.status = "Completed"
            booking.save()
    audit(prop, "Check out", stay, stay.reason)
    return dict(stay=stay.name, cleaning_task=task.name)
