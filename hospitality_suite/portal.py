"""Optional public requests. Holds use the reception engine; staff confirms manually."""
import base64
from datetime import timedelta
import hashlib
import hmac
import json
import time

import frappe
from frappe.utils import now_datetime, validate_email_address
from frappe.rate_limiter import rate_limit

from hospitality_suite import operations, availability
from hospitality_suite.service import operation, canonical, insert, audit, current_all
from hospitality_suite.security import document
from hospitality_suite.time import to_site, local


def enabled(name):
    prop=frappe.get_doc("HS Property",name)
    if not prop.portal_enabled:
        frappe.throw("El portal no está habilitado",frappe.PermissionError)
    return prop


def sign(data):
    from frappe.utils.password import get_encryption_key
    key=get_encryption_key()
    raw=base64.urlsafe_b64encode(canonical(data).encode()).decode().rstrip("=")
    signature=hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+"."+signature


def verify(token):
    try:
        if not frappe.conf.get("encryption_key"):
            raise ValueError()
        raw,signature=token.split(".")
        data=json.loads(base64.urlsafe_b64decode(raw+"="*(-len(raw)%4)))
        expected=sign(data).split(".")[1]
        if not hmac.compare_digest(signature,expected) or data["expires"]<time.time():
            raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):
        frappe.throw("Enlace inválido o vencido",frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30,seconds=60)
def catalog():
    result=[]
    for prop in frappe.get_all("HS Property",filters={"portal_enabled":1},fields=["name","property_name","mode","time_zone","currency"]):
        prop["categories"]=frappe.get_all("HS Category",filters={"property":prop.name},fields=["name","category_name","capacity","amenities"])
        result.append(prop)
    return result


def request_values(data):
    if isinstance(data,str):
        data=json.loads(data)
    count=int(data.get("quantity") or 1)
    people=int(data.get("people") or 1)
    if not 1<=count<=10 or not 1<=people<=20:
        frappe.throw("Cantidad de habitaciones o personas inválida")
    values={k:data.get(k) for k in ("full_name","email","phone","starts_at","ends_at","category","mode","quantity","people","acceptance")}
    return {**values,"rooms":[dict(category=data["category"],people=people) for _ in range(count)]}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30,seconds=60)
def quote(property_name,data):
    calculation=operations.quote_request(enabled(property_name),request_values(data))
    return {k:calculation[k] for k in ("amount","currency","acceptance")}


@frappe.whitelist(allow_guest=True,methods=["POST"])
@rate_limit(limit=5,seconds=60)
def request(property_name,data,request_key):
    prop=enabled(property_name)
    if not request_key or len(request_key)>100:
        frappe.throw("Clave de solicitud inválida")
    values=request_values(data)
    if not values.get("full_name") or not values.get("email"):
        frappe.throw("Indique nombre y correo para la confirmación")
    validate_email_address(values["email"],throw=True)
    if len(values["full_name"])>120 or len(values["email"])>140:
        frappe.throw("Nombre o correo demasiado largo")
    digest=hashlib.sha256((property_name+"|"+request_key).encode()).hexdigest()
    payload_hash=hashlib.sha256(canonical(values).encode()).hexdigest()
    frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(prop.name,))
    with operation():
        old=current_all("HS Portal Request",filters={"request_key":digest},fields=["name","hold_until"])
        if old:
            doc=frappe.get_doc("HS Portal Request",old[0].name,for_update=True)
            if doc.payload_hash!=payload_hash:
                frappe.throw("La clave ya fue usada para otra solicitud")
        else:
            availability.expire_locked(prop)
            calculation=operations.quote_request(prop,values)
            if calculation["acceptance"]!=values.get("acceptance"):
                frappe.throw("Vuelva a consultar el precio y disponibilidad")
            doc=frappe.get_doc(dict(doctype="HS Portal Request",property=prop.name,company=prop.company,
                                   full_name=values["full_name"],email=values["email"],phone=values.get("phone"),
                                   starts_at=to_site(values["starts_at"],prop),ends_at=to_site(values["ends_at"],prop),
                                   category=values["category"],rooms=len(values["rooms"]),people=int(values.get("people") or 1),
                                   mode=values.get("mode") or (prop.mode if prop.mode!="Mixed" else "Hotel"),status="Hold",
                                   hold_until=now_datetime()+timedelta(minutes=prop.hold_minutes or 15),currency=prop.currency,
                                   amount=calculation["amount"],quote_snapshot=canonical(calculation),request_key=digest,payload_hash=payload_hash))
            doc.insert(ignore_permissions=True)  # bounded request; no guest/finance/account creation
            for row in values["rooms"]:
                insert("HS Allocation",prop,category=row["category"],starts_at=doc.starts_at,ends_at=doc.ends_at,
                       buffer_minutes=prop.cleaning_minutes,kind="Reservation",status="Active",portal_request=doc.name)
            audit(prop,"Portal request",doc)
    token=sign(dict(doctype="HS Portal Request",name=doc.name,expires=int(time.time())+86400))
    return dict(status=doc.status,hold_until=str(doc.hold_until),confirmation_url="/hospitality-confirmation?token="+token)


def confirmation(token):
    data=verify(token)
    if data["doctype"] not in ("HS Portal Request","HS Booking"):
        frappe.throw("Confirmación inválida",frappe.PermissionError)
    doc=frappe.get_doc(data["doctype"],data["name"])
    prop=enabled(doc.property)
    return dict(property_name=prop.property_name,status=doc.status,starts_at=local(doc.starts_at,prop),ends_at=local(doc.ends_at,prop),
                hold_until=local(doc.hold_until,prop) if doc.get("hold_until") else None,
                currency=doc.currency,amount=doc.amount,time_zone=prop.time_zone)


def link(prop,data):
    enabled(prop.name)
    booking=document("HS Booking",data["booking"],"reserve")
    token=sign(dict(doctype="HS Booking",name=booking.name,expires=int(time.time())+86400*7))
    audit(prop,"Create confirmation link",booking)
    return dict(url="/hospitality-confirmation?token="+token)


def conversion_values(prop,data):
    request_doc=document("HS Portal Request",data["portal_request"],"reserve")
    if request_doc.status!="Hold" or request_doc.hold_until<=now_datetime():
        frappe.throw("La solicitud ya no conserva una retención vigente")
    values=dict(starts_at=local(request_doc.starts_at,prop).isoformat(),ends_at=local(request_doc.ends_at,prop).isoformat(),mode=request_doc.mode,
                customer=data["customer"],guest=data["guest"],rooms=[dict(category=request_doc.category,people=request_doc.people) for _ in range(request_doc.rooms)],
                channel="Web",acceptance=data.get("acceptance"))
    return request_doc,values


def convert(prop,data):
    request_doc,values=conversion_values(prop,data)
    availability.release(portal_request=request_doc.name)
    result=operations.reserve(prop,values)
    request_doc.status,request_doc.booking="Converted",result["booking"]
    request_doc.save()
    audit(prop,"Convert portal request",request_doc)
    return result
