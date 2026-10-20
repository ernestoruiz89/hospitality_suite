from hospitality_suite.service import current_all, locked_doc
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


def quote_request(prop, data, exclude=None):
    start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
    rooms = data.get("rooms") or [data]
    results = []
    proposed = []
    for row in rooms:
        people = int(row.get("people") or 1)
        beds=int(row.get("extra_beds") or 0)
        if beds<0 or beds>(frappe.db.get_value("HS Category",row["category"],"max_extra_beds") or 0):
            frappe.throw(frappe._("Las camas extra superan la configuración de la categoría"))
        if people > frappe.db.get_value("HS Category", row["category"], "capacity"):
            frappe.throw(frappe._("La cantidad de personas supera la capacidad de la categoría"))
        availability.check(prop, row["category"], start, end, row.get("room"), proposed=proposed,exclude=exclude)
        result = quote(prop, row["category"], start, end, people, row.get("rate"), data.get("customer"),data.get("mode"),extra_beds=beds)
        if result["currency"] != prop.currency:
            frappe.throw(frappe._("La tarifa debe estar expresada en la moneda del establecimiento"))
        result.update(category=row["category"], room=row.get("room"), people=people)
        if result["rules"]["mode"]=="Hotel":
            from hospitality_suite.timing import arrival
            estimate=arrival(prop,frappe._dict(name="quotation",modified="",starts_at=start,ends_at=end),result,at=start)
            result["timing_estimate"]=estimate
            if decimal(estimate["early"]) or decimal(estimate["late"]):
                result["explanation"].append(frappe._("Cargos estimados por horario: entrada anticipada {0}; salida tardía {1}").format(estimate['early'],estimate['late']))
        results.append(result)
        proposed.append(frappe._dict(category=row["category"], room=row.get("room"), starts_at=start, ends_at=end, buffer_minutes=prop.cleaning_minutes))
    response = dict(lines=results, amount=str(money(sum(decimal(r["amount"]) for r in results))), currency=prop.currency)
    response["estimated_total"]=str(money(decimal(response["amount"])+sum(decimal(r.get("timing_estimate",{}).get("early"))+decimal(r.get("timing_estimate",{}).get("late")) for r in results)))
    response["acceptance"] = hashlib.sha256(canonical(response).encode()).hexdigest()
    return response


def reserve(prop, data):
    data = {**data, "rooms": [{k: r.get(k) for k in ("category", "room", "people", "rate","extra_beds")} for r in (data.get("rooms") or [data])]}
    availability.expire_locked(prop)
    calculation = quote_request(prop, data)
    if data.get("acceptance") != calculation["acceptance"]:
        frappe.throw(frappe._("Revise y acepte la cotización vigente antes de reservar"))
    for row, result in zip(data["rooms"], calculation["lines"]):
        row["rate"] = result["rules"]["name"]
    status = "Hold" if data.get("hold") else "Confirmed"
    doc = insert("HS Booking", prop, customer=data["customer"], guest=data.get("guest"),
                 starts_at=to_site(data["starts_at"], prop), ends_at=to_site(data["ends_at"], prop),
                 status=status, rooms=data["rooms"], currency=prop.currency, amount=calculation["amount"],
                 quote_snapshot=canonical(calculation), channel=data.get("channel") or "Recepción", instructions=data.get("instructions"),
                 hold_until=now_datetime() + timedelta(minutes=prop.hold_minutes or 15) if status == "Hold" else None)
    for index,row in enumerate(doc.rooms):
        line=calculation["lines"][index]
        insert("HS Allocation", prop, category=row.category, room=row.room, starts_at=doc.starts_at, ends_at=doc.ends_at,
               buffer_minutes=prop.cleaning_minutes, kind="Reservation", status="Active", booking=doc.name, booking_room=row.name,
               rate=line["rules"]["name"],currency=line["currency"],accepted_amount=line["amount"],quote_snapshot=canonical(line))
    audit(prop, "Reserve", doc, details=calculation)
    return dict(booking=doc.name, status=doc.status, modified=str(doc.modified))


def update_booking(prop, data):
    doc = document("HS Booking", data["booking"], "reserve")
    assert_version(doc, data.get("modified"))
    if doc.status not in ("Hold", "Confirmed", "Draft"):
        frappe.throw(frappe._("La reserva no admite esta transición"))
    target = data["status"]
    if target not in ("Confirmed", "Cancelled", "No Show"):
        frappe.throw(frappe._("Transición de reserva inválida"))
    if target in ("Cancelled", "No Show") and not data.get("reason"):
        frappe.throw(frappe._("Indique el motivo"))
    if target == "No Show" and get_datetime(doc.starts_at) > now_datetime():
        frappe.throw(frappe._("La llegada todavía no está vencida"))
    if doc.status == "Hold" and get_datetime(doc.hold_until) <= now_datetime():
        frappe.throw(frappe._("La retención ya venció; cree una nueva reserva"))
    if target in ("Cancelled","No Show"):
        from hospitality_suite.accounting import cancellation_fee,invoice_cancellation
        fee=cancellation_fee(prop,doc,target)
        if decimal(fee["amount"]):
            if data.get("fee_acceptance")!=fee["acceptance"]:
                frappe.throw(frappe._("Revise y acepte el cargo de cancelación o no presentación"))
            invoice=invoice_cancellation(prop,doc,fee,data["reason"])
            doc.fee_invoice,doc.fee_amount=invoice.name,fee["amount"]
    doc.status, doc.reason = target, data.get("reason")
    if target in ("Cancelled", "No Show"):
        availability.release(booking=doc.name)
    doc.save()
    audit(prop, target, doc, doc.reason)
    return dict(booking=doc.name, status=doc.status)


def modification_values(prop,data):
    doc=document("HS Booking",data["booking"],"reserve")
    if doc.status not in ("Draft","Hold","Confirmed") or current_all("HS Stay",filters={"booking":doc.name}):
        frappe.throw(frappe._("Solo puede modificar una reserva antes de registrar la primera entrada"))
    from hospitality_suite.time import local
    values=dict(starts_at=data.get("starts_at") or local(doc.starts_at,prop).isoformat(),
                ends_at=data.get("ends_at") or local(doc.ends_at,prop).isoformat(),customer=data.get("customer") or doc.customer,
                guest=data.get("guest") or doc.guest,mode=data.get("mode") or json.loads(doc.quote_snapshot)["lines"][0]["rules"]["mode"],
                rooms=data.get("rooms") or [dict(category=r.category,room=r.room,people=r.people,extra_beds=r.extra_beds) for r in doc.rooms],
                channel=data.get("channel") or doc.channel,instructions=data.get("instructions",doc.instructions))
    if values["customer"]!=doc.customer and current_all("HS Payment",filters={"booking":doc.name,"status":"Posted"}):
        frappe.throw(frappe._("Revierta o concilie los movimientos existentes antes de cambiar el pagador"))
    excluded=current_all("HS Allocation",filters={"booking":doc.name,"status":"Active"},pluck="name")
    return doc,values,excluded


def modify_reservation(prop,data):
    doc,values,excluded=modification_values(prop,data)
    assert_version(doc,data.get("modified"))
    if not data.get("reason"):
        frappe.throw(frappe._("Indique el motivo de modificación"))
    calculation=quote_request(prop,values,exclude=excluded)
    if calculation["acceptance"]!=data.get("acceptance"):
        frappe.throw(frappe._("Revise y acepte la nueva cotización"))
    before=dict(starts_at=str(doc.starts_at),ends_at=str(doc.ends_at),amount=doc.amount,quote=doc.quote_snapshot)
    availability.release(booking=doc.name)
    doc.update(dict(starts_at=to_site(values["starts_at"],prop),ends_at=to_site(values["ends_at"],prop),customer=values["customer"],guest=values["guest"],
                    instructions=values["instructions"],channel=values["channel"],amount=calculation["amount"],quote_snapshot=canonical(calculation),reason=data["reason"]))
    doc.set("rooms",[dict(category=r["category"],room=r.get("room"),people=r.get("people") or 1,extra_beds=r.get("extra_beds") or 0,rate=q["rules"]["name"]) for r,q in zip(values["rooms"],calculation["lines"])])
    doc.save()
    for row,q in zip(doc.rooms,calculation["lines"]):
        insert("HS Allocation",prop,category=row.category,room=row.room,starts_at=doc.starts_at,ends_at=doc.ends_at,
               buffer_minutes=prop.cleaning_minutes,kind="Reservation",status="Active",booking=doc.name,booking_room=row.name,
               rate=q["rules"]["name"],currency=q["currency"],accepted_amount=q["amount"],quote_snapshot=canonical(q))
    audit(prop,"Modify reservation",doc,data["reason"],dict(before=before,after=calculation))
    return dict(booking=doc.name,status=doc.status,modified=str(doc.modified))


def charge(prop, stay, folio, item, amount, kind, description, snapshot=None, quantity=1, reason=None,applies_to=None):
    if decimal(amount)<0 and not applies_to:
        candidates=current_all("HS Charge",filters={"stay":stay.name,"folio":folio.name,"item":item,"status":"Pending","amount":[">",0],"applies_to_charge":["is","not set"]},fields=["name","amount"])
        for candidate in candidates:
            previous=sum(decimal(r.amount) for r in current_all("HS Charge",filters={"applies_to_charge":candidate.name,"status":"Pending"},fields=["amount"]))
            if decimal(candidate.amount)+previous>=abs(decimal(amount)):
                applies_to=candidate.name
                break
        if not applies_to:
            frappe.throw(frappe._("El crédito supera los cargos pendientes; emita una nota de crédito sobre la factura de origen"))
    return insert("HS Charge", prop, stay=stay.name, folio=folio.name, item=item, quantity=quantity,
                  rate=decimal(amount) / decimal(quantity), amount=amount, currency=folio.currency,
                  business_date=prop.business_date, status="Pending", kind=kind, description=description,
                  quote_snapshot=canonical(snapshot or {}), reason=reason,applies_to_charge=applies_to)


def credit_pending_lodging(prop,stay,folio,amount,snapshot,reason):
    """A room-change credit can span the base and accepted overtime articles."""
    remaining=abs(decimal(amount))
    sources=current_all("HS Charge",filters={"property":prop.name,"stay":stay.name,"folio":folio.name,"kind":"Lodging",
                        "status":"Pending","amount":[">",0],"applies_to_charge":["is","not set"]},fields=["name","item","amount"],order_by="creation asc,name asc")
    for source in sources:
        adjustments=current_all("HS Charge",filters={"applies_to_charge":source.name,"status":"Pending"},fields=["amount"])
        available=max(decimal(0),decimal(source.amount)+sum(decimal(row.amount) for row in adjustments))
        portion=min(remaining,available)
        if portion:
            charge(prop,stay,folio,source.item,-portion,"Lodging","Cambio de habitación y tarifa",snapshot,reason=reason,applies_to=source.name)
            remaining-=portion
        if not remaining:
            return
    frappe.throw(frappe._("El crédito supera los cargos pendientes; emita una nota de crédito sobre la factura de origen"))


def check_in(prop, data,accept_timing=False):
    availability.expire_locked(prop)
    booking = document("HS Booking", data["booking"], "stay")
    assert_version(booking, data.get("modified"))
    if booking.status not in ("Confirmed", "Checked In"):
        frappe.throw(frappe._("Confirme la reserva antes de registrar entrada"))
    guest = document("HS Guest", data.get("guest") or booking.guest, "stay")
    if prop.guest_id_required and not guest.identity_number:
        frappe.throw(frappe._("La política requiere identificación del huésped principal"))
    allocations = current_all("HS Allocation", filters={"booking": booking.name, "kind": "Reservation", "status": "Active"}, fields=["*"])
    selected = data.get("allocation")
    alloc = next((r for r in allocations if not selected or r.name == selected), None)
    if not alloc:
        frappe.throw(frappe._("No queda una habitación pendiente de entrada en esta reserva"))
    room_name = data.get("room") or alloc.room
    if not room_name:
        frappe.throw(frappe._("Seleccione la habitación para esta entrada"))
    start = min(get_datetime(booking.starts_at), now_datetime())
    if get_datetime(booking.ends_at) <= now_datetime():
        frappe.throw(frappe._("El intervalo reservado ha terminado; modifique la reserva"))
    availability.check(prop, alloc.category, start, booking.ends_at, room_name, exclude=[alloc.name], for_entry=True)
    accepted = json.loads(booking.quote_snapshot)
    requested = next((r for r in booking.rooms if r.name == alloc.booking_room), None)
    if not requested:
        frappe.throw(frappe._("La asignación no conserva la línea de reserva de origen"))
    line = accepted["lines"][requested.idx-1]
    from hospitality_suite.timing import arrival
    fees=arrival(prop,booking,line)
    from hospitality_suite.item_configuration import bound_item
    timing_total=decimal(fees["early"])+decimal(fees["late"])
    if timing_total:
        bound_item(prop,line,"timing_item")
        if accept_timing:
            estimate=line.get("timing_estimate") or {}
            if timing_total>decimal(estimate.get("early"))+decimal(estimate.get("late")):
                frappe.throw(frappe._("Los cargos por horario cambiaron; vuelva a cotizar la entrada"))
        elif data.get("timing_acceptance")!=fees["acceptance"]:
            frappe.throw(frappe._("Revise y acepte los cargos por entrada anticipada y salida tardía programada"))
    stay = insert("HS Stay", prop, booking=booking.name, guest=guest.name, customer=booking.customer, room=room_name,
                  starts_at=start, ends_at=booking.ends_at, actual_check_in=now_datetime(), status="Active",
                  rate=line["rules"]["name"], currency=prop.currency, amount=line["amount"], quote_snapshot=canonical(line),
                  guests=[dict(guest=guest.name, relationship="Principal")])
    stay.early_fee,stay.late_fee=fees["early"],fees["late"]
    stay.service_entitlements=canonical(line.get("included_services") or [])
    stay.save()
    folio = insert("HS Folio", prop, stay=stay.name,booking=stay.booking, customer=stay.customer, currency=prop.currency, status="Open", label="Cuenta principal")
    resource = locked_doc("HS Allocation", alloc.name)
    resource.kind, resource.stay, resource.room, resource.starts_at = "Stay", stay.name, room_name, start
    resource.save(ignore_permissions=True)
    booking.status = "Checked In"
    booking.save()
    extra=decimal(line.get("extra_hours_amount")) if line.get("charge_items") else decimal(0)
    base=decimal(line["amount"])-extra
    if base or not extra:
        charge(prop,stay,folio,bound_item(prop,line,"lodging_item"),base,"Lodging","Alojamiento",line)
    if extra:
        from hospitality_suite.item_configuration import hours_quantity
        charge(prop,stay,folio,bound_item(prop,line,"extra_hour_item"),extra,"Lodging","Horas adicionales de motel",line,
               quantity=hours_quantity(prop,line,line["extra_hours_quantity"]))
    if decimal(fees["early"]):
        charge(prop,stay,folio,bound_item(prop,line,"timing_item"),fees["early"],"Service","Entrada anticipada",fees)
    if decimal(fees["late"]):
        charge(prop,stay,folio,bound_item(prop,line,"timing_item"),fees["late"],"Service","Salida tardía programada",fees)
    audit(prop, "Check in", stay)
    return dict(stay=stay.name, folio=folio.name, room=room_name)


def walk_in(prop, data):
    result = reserve(prop, data)
    return check_in(prop, {**data, "booking": result["booking"], "modified": result["modified"]},accept_timing=True)


def arrival_quote(prop,data):
    from hospitality_suite.timing import arrival
    booking=document("HS Booking",data["booking"],"stay")
    allocations=current_all("HS Allocation",filters={"booking":booking.name,"status":"Active","kind":"Reservation"},fields=["*"])
    allocation=next((a for a in allocations if not data.get("allocation") or a.name==data["allocation"]),None)
    if not allocation:
        frappe.throw(frappe._("Seleccione una habitación pendiente de entrada"))
    row=next(r for r in booking.rooms if r.name==allocation.booking_room)
    return arrival(prop,booking,json.loads(booking.quote_snapshot)["lines"][row.idx-1])


def extension_quote(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    if stay.status != "Active":
        frappe.throw(frappe._("La estancia ya terminó"))
    end = to_site(data["ends_at"], prop)
    if end <= get_datetime(stay.ends_at):
        frappe.throw(frappe._("La nueva salida debe ser posterior a la actual"))
    allocations = current_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["*"])
    current = max(allocations, key=lambda a: a.starts_at)
    availability.check(prop, current.category, current.starts_at, end, stay.room, exclude=[a.name for a in allocations])
    from hospitality_suite.pricing import calculate
    from hospitality_suite.time import local
    original = json.loads(current.quote_snapshot or stay.quote_snapshot)
    if original["rules"]["mode"]=="Hotel":
        calculation=quote(prop,current.category,stay.ends_at,end,original.get("people",1),customer=stay.customer,mode="Hotel",extra_beds=original.get("extra_beds",0))
        from hospitality_suite.pricing import included_services
        calculation["included_services"]=included_services(calculation,night_only=True)
        calculation["explanation"]=calculation["base_explanation"]+[frappe._("Incluido en extensión: {0} × {1}").format(frappe.db.get_value("Item",r['item'],"item_name") or r['item'],r['quantity']) for r in calculation["included_services"]]
        calculation["difference"]=calculation["amount"]
        calculation["amount"]=str(money(decimal(stay.amount)+decimal(calculation["difference"])))
    else:
        clock_start=to_site(original["start"],prop) if original.get("start") else current.starts_at
        calculation = calculate(original["rules"], local(clock_start, prop), local(end, prop), original.get("people", 1),extra_beds=original.get("extra_beds",0), precision=original.get("precision", 2))
        calculation["difference"] = str(money(decimal(calculation["amount"]) - decimal(current.accepted_amount or stay.amount)))
        calculation["segment_amount"]=calculation["amount"]
        calculation["amount"]=str(money(decimal(stay.amount)+decimal(calculation["difference"])))
        from hospitality_suite.item_configuration import bindings
        calculation["charge_items"]=bindings(prop,original)
    calculation["service_start"]=local(stay.ends_at,prop).isoformat()
    calculation["service_end"]=local(end,prop).isoformat()
    calculation["acceptance"] = hashlib.sha256(canonical(calculation).encode()).hexdigest()
    return calculation


def extend(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    result = extension_quote(prop, data)
    if result["acceptance"] != data.get("acceptance"):
        frappe.throw(frappe._("Revise y acepte la nueva cotización"))
    if result["rules"]["mode"]=="Hotel":
        from hospitality_suite.pricing import included_services
        benefits={r["item"]:decimal(r["quantity"]) for r in json.loads(stay.service_entitlements or "[]")}
        for row in included_services(result,night_only=True):
            benefits[row["item"]]=benefits.get(row["item"],decimal(0))+decimal(row["quantity"])
        stay.service_entitlements=canonical([dict(item=item,quantity=str(quantity)) for item,quantity in sorted(benefits.items())])
    stay.ends_at, stay.amount = to_site(data["ends_at"], prop), result["amount"]
    stay.save()
    active = current_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["name", "starts_at"], order_by="starts_at desc")
    alloc = locked_doc("HS Allocation", active[0].name)
    alloc.ends_at = stay.ends_at
    alloc.accepted_amount=money(decimal(alloc.accepted_amount)+decimal(result["difference"]))
    snapshot=json.loads(alloc.quote_snapshot or stay.quote_snapshot)
    snapshot.update(end=result["end"],amount=str(alloc.accepted_amount))
    if result["rules"]["mode"]=="Motel":
        snapshot.update({key:result[key] for key in ("lodging_amount","extra_hours_amount","extra_hours_quantity","charge_items")})
    if result.get("nightly"):
        snapshot["nightly"]=snapshot.get("nightly",[])+result["nightly"]
        snapshot["units"]=len(snapshot["nightly"])
    alloc.quote_snapshot=canonical(snapshot)
    alloc.save(ignore_permissions=True)
    stay.quote_snapshot=canonical(snapshot)
    stay.save()
    folio = locked_doc("HS Folio", data["folio"])
    if (folio.stay!=stay.name if folio.stay else folio.booking!=stay.booking) or folio.status != "Open":
        frappe.throw(frappe._("Cuenta inválida"))
    if decimal(result["difference"]):
        from hospitality_suite.item_configuration import bound_item,hours_quantity
        motel=result["rules"]["mode"]=="Motel"
        quantity=decimal(result["difference"])/decimal(result["rules"]["extra_hour_rate"]) if motel and decimal(result["rules"].get("extra_hour_rate")) else 1
        charge(prop,stay,folio,bound_item(prop,result,"extra_hour_item" if motel else "lodging_item"),result["difference"],"Lodging","Extensión de estancia",result,quantity=hours_quantity(prop,result,quantity) if motel else 1)
    audit(prop, "Extend", stay, data.get("reason"), result)
    return dict(stay=stay.name, amount=result["amount"])


def cleaning_task(prop, room, stay=None):
    doc = locked_doc("HS Room", room)
    doc.cleaning_status = "Dirty"
    doc.save()
    return insert("HS Cleaning Task", prop, room=room, stay=stay, kind="Departure", priority="High", status="Pending",
                  checklist=canonical({"baño": False, "cama": False, "minibar": False, "superficies": False}))


def companions(prop,data):
    stay=document("HS Stay",data["stay"],"guest")
    assert_version(stay,data.get("modified"))
    if stay.status!="Active":
        frappe.throw(frappe._("Registre acompañantes durante una estancia activa"))
    guests=data.get("guests") or []
    if not isinstance(guests,list) or len(guests)!=len(set(guests)) or stay.guest in guests:
        frappe.throw(frappe._("La lista de acompañantes contiene duplicados"))
    snapshot=frappe.parse_json(stay.quote_snapshot)
    if len(guests)+1>int(snapshot.get("people") or 1):
        frappe.throw(frappe._("La lista supera la ocupación aceptada; revise primero la tarifa y capacidad de la reserva"))
    for name in guests:
        guest=document("HS Guest",name,"guest")
        if prop.guest_id_required and not guest.identity_number:
            frappe.throw(frappe._("Complete la identificación requerida del acompañante"))
    previous=[r.guest for r in stay.guests]
    stay.set("guests",[dict(guest=stay.guest,relationship="Principal")]+[dict(guest=g,relationship="Acompañante") for g in guests])
    stay.save()
    audit(prop,"Update companions",stay,details=dict(previous=previous,current=[r.guest for r in stay.guests]))
    return dict(stay=stay.name,modified=str(stay.modified))


def change_room(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    if stay.status != "Active" or not data.get("reason"):
        frappe.throw(frappe._("Seleccione una estancia activa e indique el motivo"))
    room = document("HS Room", data["room"], "stay")
    calculation=room_change_quote(prop,data)
    if data.get("acceptance")!=calculation["acceptance"]:
        frappe.throw(frappe._("Revise y acepte el efecto tarifario del cambio de habitación"))
    if decimal(calculation["difference"])<0:
        require(prop.name,"approve")
    now = now_datetime()
    availability.check(prop, room.category, now, stay.ends_at, room.name, for_entry=True)
    for row in current_all("HS Allocation", filters={"stay": stay.name, "status": "Active"}, fields=["name", "ends_at"]):
        alloc = locked_doc("HS Allocation", row.name)
        alloc.ends_at = now
        alloc.save(ignore_permissions=True)
    insert("HS Allocation", prop, category=room.category, room=room.name, starts_at=now, ends_at=stay.ends_at,
           buffer_minutes=prop.cleaning_minutes, kind="Stay", status="Active", booking=stay.booking, stay=stay.name,
           rate=calculation["quote"]["rules"]["name"],currency=prop.currency,accepted_amount=calculation["quote"]["amount"],quote_snapshot=canonical(calculation["quote"]))
    cleaning_task(prop, stay.room, stay.name)
    before = stay.room
    stay.room = room.name
    stay.rate=calculation["quote"]["rules"]["name"]
    stay.quote_snapshot=canonical(calculation["quote"])
    stay.amount=money(decimal(stay.amount)+decimal(calculation["difference"]))
    stay.save()
    if decimal(calculation["difference"]):
        folio=document("HS Folio",data["folio"],"stay")
        if (folio.stay!=stay.name if folio.stay else folio.booking!=stay.booking) or folio.status!="Open":
            frappe.throw(frappe._("Seleccione una cuenta abierta de la estancia"))
        if decimal(calculation["difference"])<0:
            credit_pending_lodging(prop,stay,folio,calculation["difference"],calculation["quote"],data["reason"])
        else:
            from hospitality_suite.item_configuration import bound_item
            charge(prop,stay,folio,bound_item(prop,calculation["quote"],"lodging_item"),calculation["difference"],"Lodging","Cambio de habitación y tarifa",calculation["quote"],reason=data["reason"])
    audit(prop, "Change room", stay, data["reason"], {"from": before, "to": room.name})
    return dict(stay=stay.name, room=room.name)


def room_change_quote(prop,data):
    from hospitality_suite.time import local
    from hospitality_suite.pricing import calculate
    stay=document("HS Stay",data["stay"],"stay")
    room=document("HS Room",data["room"],"stay")
    if stay.status!="Active" or room.name==stay.room or get_datetime(stay.ends_at)<=now_datetime():
        frappe.throw(frappe._("Seleccione otra habitación para una estancia activa dentro de su intervalo"))
    actual_now=now_datetime()
    now=actual_now.replace(second=0,microsecond=0)
    availability.check(prop,room.category,actual_now,stay.ends_at,room.name,for_entry=True)
    segments=current_all("HS Allocation",filters={"stay":stay.name,"status":"Active"},fields=["*"],order_by="starts_at desc")
    current=segments[0]
    original=json.loads(current.quote_snapshot or stay.quote_snapshot)
    mode=data.get("mode") or original["rules"]["mode"]
    if room.category==current.category and mode==original["rules"]["mode"]:
        q=dict(original)
        difference=decimal(0)
        explanation=frappe._("Misma categoría y modalidad: se conserva el importe aceptado.")
    else:
        if original.get("people",1)>frappe.db.get_value("HS Category",room.category,"capacity") or original.get("extra_beds",0)>(frappe.db.get_value("HS Category",room.category,"max_extra_beds") or 0):
            frappe.throw(frappe._("La habitación de destino no admite esta ocupación o camas extra"))
        q=quote(prop,room.category,now,stay.ends_at,original.get("people",1),customer=stay.customer,mode=mode,extra_beds=original.get("extra_beds",0))
        if original["rules"]["mode"]=="Hotel":
            days=original.get("nightly") or []
            unused=sum(decimal(r["amount"]) for r in days if get_datetime(r["date"]).date()>=local(now,prop).date()) if days else decimal(current.accepted_amount)
            explanation=frappe._("Se acredita la noche actual y las futuras no trasladadas a otro segmento; se cotiza la categoría y modalidad de destino.")
        else:
            duration=(get_datetime(current.ends_at)-get_datetime(current.starts_at)).total_seconds()
            fraction=max(0,min(1,(get_datetime(current.ends_at)-now).total_seconds()/duration)) if duration else 0
            unused=money(decimal(current.accepted_amount)*decimal(fraction))
            explanation=frappe._("Se acredita proporcionalmente el tiempo restante del segmento anterior y se cotiza el bloque de destino.")
        difference=money(decimal(q["amount"])-unused)
    result=dict(quote=q,difference=str(difference),explanation=explanation+" "+frappe._("Los servicios incluidos ya aceptados se conservan, sin duplicarlos por el cambio. El prorrateo se calcula por minuto iniciado; revise nuevamente si cambia el minuto de la cotización."),valid_until=str(now+timedelta(minutes=1)))
    result["acceptance"]=hashlib.sha256(canonical(dict(stay=stay.name,modified=str(stay.modified),room=room.name,
                                                          amount=result["difference"],rate=q["rules"]["name"],mode=mode)).encode()).hexdigest()
    return result


def create_folio(prop, data):
    stay = document("HS Stay", data["stay"], "stay")
    if stay.status != "Active":
        frappe.throw(frappe._("La estancia debe estar activa"))
    doc = insert("HS Folio", prop, stay=None if data.get("group") else stay.name,booking=stay.booking, customer=data["customer"], currency=prop.currency, label=data.get("label"), status="Open")
    audit(prop, "Create folio", doc)
    return dict(folio=doc.name)


def move_charge(prop, data):
    doc = document("HS Charge", data["charge"], "stay")
    target = document("HS Folio", data["folio"], "stay")
    stay=locked_doc("HS Stay",doc.stay)
    matches=target.stay==doc.stay if target.stay else bool(target.booking and target.booking==stay.booking)
    if doc.status != "Pending" or target.status != "Open" or not matches or not data.get("reason"):
        frappe.throw(frappe._("Solo puede trasladar cargos pendientes de la misma estancia o grupo con un motivo"))
    if doc.applies_to_charge:
        frappe.throw(frappe._("Traslade el cargo principal; sus descuentos y cortesías se trasladan con él"))
    for related in current_all("HS Charge",filters={"applies_to_charge":doc.name,"status":"Pending"},pluck="name"):
        adjustment=locked_doc("HS Charge",related)
        adjustment.folio=target.name
        adjustment.save()
    doc.folio = target.name
    doc.save()
    for name in current_all("HS Service Request",filters={"charge":doc.name},pluck="name"):
        service=locked_doc("HS Service Request",name)
        service.folio=target.name
        service.save()
    audit(prop, "Move charge", doc, data["reason"])
    return dict(charge=doc.name, folio=target.name)


def adjustment(prop,data):
    source=document("HS Charge",data["charge"],"approve")
    folio=document("HS Folio",source.folio,"approve")
    if source.status!="Pending" or folio.status!="Open" or not data.get("reason"):
        frappe.throw(frappe._("Ajuste cargos pendientes con un motivo; para cargos facturados use una nota de crédito"))
    kind=data["adjustment_type"]
    if kind not in ("Discount","Courtesy","Surcharge"):
        frappe.throw(frappe._("Tipo de ajuste inválido"))
    previous=current_all("HS Charge",filters={"applies_to_charge":source.name,"status":["!=","Reversed"]},fields=["amount"])
    available=decimal(source.amount)+sum(decimal(r.amount) for r in previous)
    amount=available if kind=="Courtesy" else money(data.get("amount"))
    if amount<=0 or (kind!="Surcharge" and amount>available):
        frappe.throw(frappe._("El descuento o cortesía supera el cargo disponible"))
    signed=amount if kind=="Surcharge" else -amount
    stay=locked_doc("HS Stay",source.stay)
    record=charge(prop,stay,folio,source.item,signed,source.kind,
                  {"Discount":"Descuento autorizado","Courtesy":"Cortesía autorizada","Surcharge":"Recargo autorizado"}[kind],
                  snapshot=json.loads(source.quote_snapshot or "{}"),reason=data["reason"],applies_to=source.name)
    record.applies_to_charge,record.adjustment_type=source.name,kind
    record.save()
    audit(prop,"Adjustment "+kind,record,data["reason"],dict(source=source.name,amount=str(signed)))
    return dict(charge=record.name,amount=str(signed))


def check_out(prop, data):
    from hospitality_suite.accounting import folio_balance, invoice_folio,folios_for_stay
    stay = document("HS Stay", data["stay"], "stay")
    assert_version(stay, data.get("modified"))
    if stay.status != "Active":
        frappe.throw(frappe._("La estancia ya tiene salida registrada"))
    if prop.checkout_inspection_required and not stay.departure_inspected_by:
        frappe.throw(frappe._("La política requiere una inspección antes de la salida"))
    from hospitality_suite.timing import departure
    valid=stay.departure_expires_at and get_datetime(stay.departure_expires_at)>=now_datetime()
    if not valid and decimal(departure(prop,{"stay":stay.name})["amount"])>0:
        frappe.throw(frappe._("Prepare y liquide los cargos por tiempo antes de registrar salida"))
    folios = [r.name for r in folios_for_stay(stay)]
    for name in folios:
        invoice_folio(prop, {"folio": name})
        balance = folio_balance(name)
        if decimal(balance["outstanding"]) > 0:
            require(prop.name, "approve")
            if not prop.allow_credit or not data.get("credit_reason"):
                frappe.throw(frappe._("Liquiden el saldo antes de registrar salida o autoricen crédito con motivo"))
            from frappe.utils import nowdate
            folio=locked_doc("HS Folio",name)
            grants=current_all("HS Billing Party",filters={"property":prop.name,"customer":folio.customer,"credit_authorized":1},fields=["credit_limit","valid_until"])
            if not grants or (grants[0].valid_until and str(grants[0].valid_until)<nowdate()):
                frappe.throw(frappe._("El cliente no tiene autorización de crédito vigente"))
            invoices=current_all("Sales Invoice",filters={"company":prop.company,"customer":folio.customer,"docstatus":1,"outstanding_amount":[">",0]},fields=["outstanding_amount"])
            if sum(decimal(r.outstanding_amount) for r in invoices)>decimal(grants[0].credit_limit):
                frappe.throw(frappe._("El saldo del cliente supera su límite de crédito autorizado"))
    guarantee = sum(decimal(p.amount) * (-1 if p.kind in ("Guarantee Refund", "Guarantee Applied") else 1)
                    for p in current_all("HS Payment", filters={"stay": stay.name, "status": "Posted", "kind": ["in", ["Guarantee", "Guarantee Refund", "Guarantee Applied"]]}, fields=["amount", "kind"]))
    if guarantee:
        frappe.throw(frappe._("Devuelva o aplique la garantía antes de registrar salida"))
    if frappe.db.exists("HS Service Request", {"stay": stay.name, "status": ["in", ["Requested", "In Progress"]]}):
        frappe.throw(frappe._("Revise los servicios pendientes antes de registrar salida"))
    stay.status, stay.actual_check_out, stay.reason = "Checked Out", now_datetime(), data.get("credit_reason")
    stay.save()
    availability.release(stay=stay.name)
    task = cleaning_task(prop, stay.room, stay.name)
    for name in folios:
        doc = locked_doc("HS Folio", name)
        if not doc.stay and (current_all("HS Stay",filters={"booking":stay.booking,"status":"Active"}) or current_all("HS Allocation",filters={"booking":stay.booking,"kind":"Reservation","status":"Active"})):
            continue
        doc.status = "Closed"
        doc.save()
    if stay.booking:
        booking = locked_doc("HS Booking", stay.booking)
        if not frappe.db.exists("HS Stay", {"booking": stay.booking, "status": "Active"}) and not frappe.db.exists("HS Allocation", {"booking": stay.booking, "kind": "Reservation", "status": "Active"}):
            booking.status = "Completed"
            booking.save()
    audit(prop, "Check out", stay, stay.reason)
    return dict(stay=stay.name, cleaning_task=task.name)
