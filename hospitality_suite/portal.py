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
from hospitality_suite.inputs import object_payload
from hospitality_suite.time import to_site, local


def enabled(name):
    prop=frappe.get_doc("HS Property",name)
    if not prop.portal_enabled:
        frappe.throw(frappe._("El portal no está habilitado"),frappe.PermissionError)
    return prop


def sign(data):
    from frappe.utils.password import get_encryption_key
    key=get_encryption_key()
    raw=base64.urlsafe_b64encode(canonical(data).encode()).decode().rstrip("=")
    signature=hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+"."+signature


def verify(token):
    try:
        if not isinstance(token,str) or len(token)>4096:
            raise ValueError()
        if not frappe.conf.get("encryption_key"):
            raise ValueError()
        raw,signature=token.split(".")
        data=json.loads(base64.urlsafe_b64decode(raw+"="*(-len(raw)%4)))
        expected=sign(data).split(".")[1]
        if not hmac.compare_digest(signature,expected) or data["expires"]<time.time():
            raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):
        frappe.throw(frappe._("Enlace inválido o vencido"),frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30,seconds=60)
def catalog():
    result=[]
    for prop in frappe.get_all("HS Property",filters={"portal_enabled":1},fields=["name","property_name","mode","time_zone","currency"]):
        prop["categories"]=frappe.get_all("HS Category",filters={"property":prop.name},fields=["name","category_name","capacity","amenities","portal_description","portal_image"])
        images=[row.portal_image for row in prop["categories"] if row.portal_image]
        public=set(frappe.get_all("File",filters={"file_url":["in",images],"is_private":0},pluck="file_url")) if images else set()
        for row in prop["categories"]:
            if row.portal_image not in public:
                row.portal_image=None
        result.append(prop)
    return result


def request_values(data):
    data=object_payload(data)
    from hospitality_suite.mode import normalize_mode
    if data.get("mode"):
        data["mode"]=normalize_mode(data["mode"])
    if any(data.get(key) is not None and not isinstance(data[key],str) for key in
           ("full_name","email","phone","starts_at","ends_at","category","mode","acceptance","request_mode")):
        frappe.throw(frappe._("Revise los datos de la solicitud"))
    request_mode=data.get("request_mode") or "Hold"
    if request_mode not in ("Hold","Requested"):
        frappe.throw(frappe._("Seleccione una modalidad de solicitud válida"))
    if len(data.get("phone") or "")>140:
        frappe.throw(frappe._("El teléfono es demasiado largo"))
    try:
        if isinstance(data.get("quantity"),bool) or isinstance(data.get("people"),bool):
            raise ValueError()
        quantity=data.get("quantity") if data.get("quantity") not in (None,"") else 1
        persons=data.get("people") if data.get("people") not in (None,"") else 1
        count=int(quantity)
        people=int(persons)
        if float(quantity)!=count or float(persons)!=people:
            raise ValueError()
    except (ValueError,TypeError,OverflowError):
        frappe.throw(frappe._("Cantidad de habitaciones o personas inválida"))
    if not 1<=count<=10 or not 1<=people<=20:
        frappe.throw(frappe._("Cantidad de habitaciones o personas inválida"))
    values={k:data.get(k) for k in ("full_name","email","phone","starts_at","ends_at","category","mode","quantity","people","acceptance")}
    values["request_mode"]=request_mode
    return {**values,"rooms":[dict(category=data["category"],people=people) for _ in range(count)]}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30,seconds=60)
def quote(property_name,data):
    calculation=operations.quote_request(enabled(property_name),request_values(data))
    # Public explanation is plain text from the same server quote, without
    # exposing internal rate identifiers or guest/account records.
    return {**{k:calculation[k] for k in ("amount","currency","acceptance","estimated_total")},
            "explanation":list(calculation["lines"][0]["explanation"])}


@frappe.whitelist(allow_guest=True,methods=["POST"])
@rate_limit(limit=5,seconds=60)
def request(property_name,data,request_key):
    prop=enabled(property_name)
    if not isinstance(request_key,str) or not request_key.strip() or len(request_key)>100:
        frappe.throw(frappe._("Clave de solicitud inválida"))
    values=request_values(data)
    if not values.get("full_name") or not values.get("email"):
        frappe.throw(frappe._("Indique nombre y correo para la confirmación"))
    validate_email_address(values["email"],throw=True)
    if len(values["full_name"])>120 or len(values["email"])>140:
        frappe.throw(frappe._("Nombre o correo demasiado largo"))
    digest=hashlib.sha256((property_name+"|"+request_key).encode()).hexdigest()
    payload_hash=hashlib.sha256(canonical(values).encode()).hexdigest()
    from hospitality_suite.mode import LEGACY_TIME_MODE, TIME_MODE
    accepted_hashes={payload_hash}
    versions=[values]
    if values.get("mode")==TIME_MODE:
        versions.append({**values,"mode":LEGACY_TIME_MODE})
    for version in versions:
        if values["request_mode"]=="Hold":
            accepted_hashes.add(hashlib.sha256(canonical({key:value for key,value in version.items() if key!="request_mode"}).encode()).hexdigest())
        accepted_hashes.add(hashlib.sha256(canonical(version).encode()).hexdigest())
    frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(prop.name,))
    with operation():
        old=current_all("HS Portal Request",filters={"request_key":digest},fields=["name","hold_until","request_until"])
        if old:
            doc=frappe.get_doc("HS Portal Request",old[0].name,for_update=True)
            if doc.payload_hash not in accepted_hashes:
                frappe.throw(frappe._("La clave ya fue usada para otra solicitud"))
        else:
            availability.expire_locked(prop)
            calculation=operations.quote_request(prop,values)
            if calculation["acceptance"]!=values.get("acceptance"):
                frappe.throw(frappe._("Vuelva a consultar el precio y disponibilidad"))
            doc=frappe.get_doc(dict(doctype="HS Portal Request",property=prop.name,company=prop.company,
                                   full_name=values["full_name"],email=values["email"],phone=values.get("phone"),
                                   starts_at=to_site(values["starts_at"],prop),ends_at=to_site(values["ends_at"],prop),
                                   category=values["category"],rooms=len(values["rooms"]),people=int(values.get("people") or 1),
                                   mode=values.get("mode") or (prop.mode if prop.mode!="Mixed" else "Hotel"),status=values["request_mode"],
                                   hold_until=now_datetime()+timedelta(minutes=prop.hold_minutes or 15) if values["request_mode"]=="Hold" else None,
                                   request_until=now_datetime()+timedelta(days=1) if values["request_mode"]=="Requested" else None,currency=prop.currency,
                                   amount=calculation["amount"],quote_snapshot=canonical(calculation),request_key=digest,payload_hash=payload_hash))
            doc.insert(ignore_permissions=True)  # bounded request; no guest/finance/account creation
            if doc.status=="Hold":
                for row in values["rooms"]:
                    insert("HS Allocation",prop,category=row["category"],starts_at=doc.starts_at,ends_at=doc.ends_at,
                           buffer_minutes=prop.cleaning_minutes,kind="Reservation",status="Active",portal_request=doc.name)
            audit(prop,"Portal request",doc)
    token=sign(dict(doctype="HS Portal Request",name=doc.name,expires=int(time.time())+(86400*7 if doc.status=="Requested" else 86400)))
    return dict(status=doc.status,hold_until=str(doc.hold_until) if doc.hold_until else None,
                request_until=str(doc.request_until) if doc.request_until else None,
                confirmation_url="/hospitality-confirmation?token="+token)


def confirmation(token):
    data=verify(token)
    if data["doctype"] not in ("HS Portal Request","HS Booking"):
        frappe.throw(frappe._("Confirmación inválida"),frappe.PermissionError)
    doc=frappe.get_doc(data["doctype"],data["name"])
    prop=enabled(doc.property)
    status="Expired" if doc.status=="Requested" and doc.request_until<=now_datetime() else doc.status
    return dict(property_name=prop.property_name,status=status,starts_at=local(doc.starts_at,prop),ends_at=local(doc.ends_at,prop),
                hold_until=local(doc.hold_until,prop) if doc.get("hold_until") else None,
                request_until=local(doc.request_until,prop) if doc.get("request_until") else None,
                currency=doc.currency,amount=doc.amount,time_zone=prop.time_zone)


def link(prop,data):
    enabled(prop.name)
    booking=document("HS Booking",data["booking"],"reserve")
    token=sign(dict(doctype="HS Booking",name=booking.name,expires=int(time.time())+86400*7))
    audit(prop,"Create confirmation link",booking)
    return dict(url="/hospitality-confirmation?token="+token)


def conversion_values(prop,data):
    request_doc=document("HS Portal Request",data["portal_request"],"reserve")
    if request_doc.status=="Hold":
        if request_doc.hold_until<=now_datetime():
            frappe.throw(frappe._("La solicitud ya no conserva una retención vigente"))
    elif request_doc.status=="Requested":
        if request_doc.request_until<=now_datetime():
            frappe.throw(frappe._("La solicitud sin retención ya venció"))
    else:
        frappe.throw(frappe._("La solicitud ya no está pendiente"))
    values=dict(starts_at=local(request_doc.starts_at,prop).isoformat(),ends_at=local(request_doc.ends_at,prop).isoformat(),mode=request_doc.mode,
                customer=data["customer"],guest=data["guest"],rooms=[dict(category=request_doc.category,people=request_doc.people) for _ in range(request_doc.rooms)],
                channel="Web",acceptance=data.get("acceptance"))
    return request_doc,values


def convert(prop,data):
    request_doc,values=conversion_values(prop,data)
    if request_doc.status=="Hold":
        availability.release(portal_request=request_doc.name)
    result=operations.reserve(prop,values)
    request_doc.status,request_doc.booking="Converted",result["booking"]
    request_doc.save()
    audit(prop,"Convert portal request",request_doc)
    return result


def reject(prop,data):
    request_doc=document("HS Portal Request",data["portal_request"],"reserve")
    reason=data.get("reason")
    if request_doc.status not in ("Hold","Requested") or not isinstance(reason,str) or not reason.strip() or len(reason)>500:
        frappe.throw(frappe._("Indique un motivo válido para rechazar la solicitud pendiente"))
    if request_doc.status=="Hold":
        availability.release(portal_request=request_doc.name)
    request_doc.status="Rejected"
    request_doc.save(ignore_permissions=True)
    audit(prop,"Reject portal request",request_doc,reason.strip())
    return dict(portal_request=request_doc.name,status=request_doc.status)
