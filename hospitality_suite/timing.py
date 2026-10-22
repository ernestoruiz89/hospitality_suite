from datetime import datetime,timedelta,UTC
from decimal import ROUND_CEILING
import hashlib
import json

import frappe
from frappe.utils import get_datetime,get_time,now_datetime

from hospitality_suite.pricing import decimal,money,calculate
from hospitality_suite.service import canonical,current_all,locked_doc,audit
from hospitality_suite.security import document
from hospitality_suite.time import local,to_site,aware


def fee(minutes,rate,prop):
    beyond=max(decimal(0),decimal(minutes)-decimal(prop.schedule_grace_minutes))
    step=decimal(prop.schedule_rounding_minutes or 60)
    return money((beyond/step).to_integral_value(rounding=ROUND_CEILING)*step/60*decimal(rate))


def arrival(prop,booking,line,at=None):
    now=local(at or now_datetime(),prop)
    planned=local(booking.starts_at,prop)
    if now.date()<planned.date():
        frappe.throw(frappe._("Para ingresar antes de la fecha reservada, modifique el intervalo y acepte su nueva cotización"))
    if line["rules"]["mode"]!="Hotel":
        return dict(early="0.00",late="0.00",acceptance="")
    boundary=aware(datetime.combine(planned.date(),get_time(prop.check_in_time)),prop.time_zone)
    early_minutes=max(0,(boundary.astimezone(UTC)-now.astimezone(UTC)).total_seconds()/60)
    checkout_day=get_datetime(line["start"]).date()+timedelta(days=int(line.get("units") or 1))
    checkout=aware(datetime.combine(checkout_day,get_time(prop.check_out_time)),prop.time_zone)
    late_minutes=max(0,(local(booking.ends_at,prop).astimezone(UTC)-checkout.astimezone(UTC)).total_seconds()/60)
    result=dict(early=str(fee(early_minutes,prop.early_hour_rate,prop)),late=str(fee(late_minutes,prop.late_hour_rate,prop)),
                explanation=frappe._("Entrada anticipada y salida tardía programada según horario, tolerancia y fracción del establecimiento."))
    result["acceptance"]=hashlib.sha256(canonical(dict(booking=booking.name,modified=str(booking.modified),**result)).encode()).hexdigest()
    return result


def departure(prop,data):
    stay=document("HS Stay",data["stay"],"stay")
    if stay.status!="Active":
        frappe.throw(frappe._("La estancia ya terminó"))
    segments=current_all("HS Allocation",filters={"stay":stay.name,"status":"Active"},fields=["*"],order_by="starts_at desc")
    current=segments[0]
    snapshot=json.loads(current.quote_snapshot or stay.quote_snapshot)
    end=max(now_datetime(),get_datetime(stay.ends_at))
    from hospitality_suite.mode import is_time_mode
    if is_time_mode(snapshot["rules"]["mode"]):
        start=to_site(snapshot["start"],prop) if snapshot.get("start") else current.starts_at
        quote=calculate(snapshot["rules"],local(start,prop),local(end,prop),snapshot.get("people",1),extra_beds=snapshot.get("extra_beds",0),precision=snapshot.get("precision",2))
        difference=max(decimal(0),decimal(quote["amount"])-decimal(current.accepted_amount))
        kind="Lodging"
        from hospitality_suite.item_configuration import bindings
        quote["charge_items"]=bindings(prop,snapshot)
    else:
        day=get_datetime(snapshot["start"]).date()+timedelta(days=int(snapshot.get("units") or len(snapshot.get("nightly") or []) or 1))
        boundary=aware(datetime.combine(day,get_time(prop.check_out_time)),prop.time_zone)
        minutes=max(0,(local(end,prop).astimezone(UTC)-boundary.astimezone(UTC)).total_seconds()/60)
        difference=max(decimal(0),fee(minutes,prop.late_hour_rate,prop)-decimal(stay.late_fee))
        quote=dict(explanation=[frappe._("Salida tardía: tolerancia y fracción configuradas")],start=snapshot["start"],end=local(end,prop).isoformat(),rules=snapshot["rules"])
        kind="Service"
        from hospitality_suite.item_configuration import bindings
        quote["charge_items"]=bindings(prop,snapshot)
    result=dict(stay=stay.name,amount=str(money(difference)),currency=prop.currency,kind=kind,quote=quote,
                explanation=quote["explanation"],inspection_required=bool(prop.checkout_inspection_required),
                inspected=bool(stay.departure_inspected_by))
    # Economic acceptance remains valid while the rounded amount is unchanged.
    result["acceptance"]=hashlib.sha256(canonical(dict(stay=stay.name,modified=str(stay.modified),amount=result["amount"],kind=kind,charge_items=quote["charge_items"])).encode()).hexdigest()
    return result


def prepare_departure(prop,data):
    from hospitality_suite.operations import charge
    quote=departure(prop,data)
    if data.get("acceptance")!=quote["acceptance"]:
        frappe.throw(frappe._("Revise nuevamente la liquidación de salida"))
    stay=document("HS Stay",data["stay"],"stay")
    folio=document("HS Folio",data["folio"],"stay")
    if (folio.stay!=stay.name if folio.stay else folio.booking!=stay.booking) or folio.status!="Open":
        frappe.throw(frappe._("Seleccione una cuenta abierta de esta estancia"))
    amount=decimal(quote["amount"])
    if amount:
        from hospitality_suite.item_configuration import bound_item,hours_quantity
        timed=quote["kind"]=="Lodging"
        item=bound_item(prop,quote["quote"],"extra_hour_item" if timed else "timing_item")
        hour_rate=decimal(quote["quote"]["rules"].get("extra_hour_rate")) if timed else 0
        charge(prop,stay,folio,item,amount,quote["kind"],"Liquidación de tiempo de estancia",quote["quote"],quantity=hours_quantity(prop,quote["quote"],amount/hour_rate) if hour_rate else 1)
        if quote["kind"]=="Lodging":
            segments=current_all("HS Allocation",filters={"stay":stay.name,"status":"Active"},fields=["name"],order_by="starts_at desc")
            segment=locked_doc("HS Allocation",segments[0].name)
            segment.accepted_amount=money(decimal(segment.accepted_amount)+amount)
            segment.ends_at=max(get_datetime(segment.ends_at),now_datetime())
            snapshot=frappe.parse_json(segment.quote_snapshot or stay.quote_snapshot)
            snapshot.update({key:quote["quote"][key] for key in ("end","lodging_amount","extra_hours_amount","extra_hours_quantity","charge_items")})
            snapshot["amount"]=str(segment.accepted_amount)
            segment.quote_snapshot=canonical(snapshot)
            segment.save(ignore_permissions=True)
            stay.quote_snapshot=canonical(snapshot)
            stay.amount=money(decimal(stay.amount)+amount)
        else:
            stay.late_fee=money(decimal(stay.late_fee)+amount)
    stay.departure_expires_at=now_datetime()+timedelta(minutes=prop.checkout_quote_minutes or 5)
    stay.save()
    audit(prop,"Prepare departure",stay,details=quote)
    return dict(stay=stay.name,amount=str(amount),expires_at=str(stay.departure_expires_at),modified=str(stay.modified))


def inspect_departure(prop,data):
    stay=document("HS Stay",data["stay"],"inspect")
    if stay.status!="Active" or not data.get("notes"):
        frappe.throw(frappe._("Seleccione una estancia activa e indique la revisión realizada"))
    stay.departure_inspected_by=frappe.session.user
    stay.departure_inspected_at=now_datetime()
    stay.departure_notes=data["notes"]
    stay.save()
    audit(prop,"Inspect departure",stay,data["notes"])
    return dict(stay=stay.name)
