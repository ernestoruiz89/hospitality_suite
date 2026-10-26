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
from hospitality_suite.security import document, require
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
        from hospitality_suite.travel_experiences import quote_experiences
        internal_prop=frappe.get_doc("HS Property",prop.name)
        prop["experiences"]=[]
        for exp in frappe.get_all("HS Experience",filters={"property":prop.name,"active":1,"show_on_booking_page":1},
                                  fields=["name","experience_name","experience_category","duration","description","image_url"]):
            try:
                quote=quote_experiences(internal_prop,[{"experience":exp.name,"quantity":1}],public=True)[0]
            except frappe.ValidationError:
                continue
            exp["price"],exp["currency"]=quote["rate"],prop.currency
            prop["experiences"].append(exp)
        result.append(prop)
    return result


def staff_queue(property_name, offset=0, page_length=25, search=""):
    """A bounded reception queue, scoped before looking up guest contact data."""
    prop = require(property_name, "reserve")
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de solicitudes web"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(frappe._("Revise la paginación de solicitudes web"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de solicitudes web"))
    where = "property=%s AND company=%s AND status IN ('Hold','Requested')"
    values = [prop.name, prop.company]
    if search.strip():
        where += " AND (name LIKE %s OR full_name LIKE %s OR email LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 3)
    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabHS Portal Request` WHERE " + where,
        values, as_list=True)[0][0]
    rows = frappe.db.sql(
        "SELECT name,full_name,email,phone,category,mode,rooms,people,"
        "starts_at,ends_at,status,hold_until,request_until,amount,currency "
        "FROM `tabHS Portal Request` WHERE " + where +
        " ORDER BY creation ASC,name ASC LIMIT %s OFFSET %s",
        [*values, page_length, offset], as_dict=True)
    from hospitality_suite.time import local

    for row in rows:
        deadline = row.request_until if row.status == "Requested" else row.hold_until
        row["expired"] = not deadline or deadline <= now_datetime()
        for field in ("starts_at", "ends_at", "hold_until", "request_until"):
            row[field] = local(row[field], prop).strftime("%Y-%m-%d %H:%M") if row[field] else None
    return {"property": prop.name, "offset": offset, "page_length": page_length,
        "total": int(total), "has_more": offset + len(rows) < total, "rows": rows}


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
    extras=data.get("experiences") or []
    if not isinstance(extras,list) or len(extras)>20 or any(not isinstance(row,dict) for row in extras):
        frappe.throw(frappe._("Revise las experiencias seleccionadas"))
    values["experiences"]=[{"experience":row.get("experience"),"quantity":row.get("quantity")} for row in extras]
    values["request_mode"]=request_mode
    return {**values,"rooms":[dict(category=data["category"],people=people) for _ in range(count)]}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30,seconds=60)
def quote(property_name,data):
    calculation=operations.quote_request(enabled(property_name),request_values(data),public=True)
    # Public explanation is plain text from the same server quote, without
    # exposing internal rate identifiers or guest/account records.
    return {**{k:calculation[k] for k in ("amount","currency","acceptance","estimated_total","experiences_total")},
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
            calculation=operations.quote_request(prop,values,public=True)
            if calculation["acceptance"]!=values.get("acceptance"):
                frappe.throw(frappe._("Vuelva a consultar el precio y disponibilidad"))
            doc=frappe.get_doc(dict(doctype="HS Portal Request",property=prop.name,company=prop.company,
                                   full_name=values["full_name"],email=values["email"],phone=values.get("phone"),
                                   starts_at=to_site(values["starts_at"],prop),ends_at=to_site(values["ends_at"],prop),
                                   category=values["category"],rooms=len(values["rooms"]),people=int(values.get("people") or 1),
                                   mode=values.get("mode") or (prop.mode if prop.mode!="Mixed" else "Hotel"),status=values["request_mode"],
                                   hold_until=now_datetime()+timedelta(minutes=prop.hold_minutes or 15) if values["request_mode"]=="Hold" else None,
                                   request_until=now_datetime()+timedelta(days=1) if values["request_mode"]=="Requested" else None,currency=prop.currency,
                                   amount=calculation["amount"],quote_snapshot=canonical(calculation),experiences=canonical(values["experiences"]),
                                   request_key=digest,payload_hash=payload_hash))
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
    if doc.company != prop.company:
        frappe.throw(frappe._("Confirmación inválida"),frappe.PermissionError)
    status="Expired" if doc.status=="Requested" and doc.request_until<=now_datetime() else doc.status
    quoted=frappe.parse_json(doc.quote_snapshot or "{}")
    return dict(property_name=prop.property_name,status=status,starts_at=local(doc.starts_at,prop),ends_at=local(doc.ends_at,prop),
                hold_until=local(doc.hold_until,prop) if doc.get("hold_until") else None,
                request_until=local(doc.request_until,prop) if doc.get("request_until") else None,
                currency=doc.currency,amount=doc.amount,time_zone=prop.time_zone,
                experiences_total=quoted.get("experiences_total") or "0.00",
                estimated_total=quoted.get("estimated_total") or doc.amount,
                can_link_guest=data["doctype"]=="HS Booking" and bool(doc.guest)
                and bool(frappe.db.get_value("HS Guest", {"name": doc.guest,
                    "property": prop.name, "company": prop.company}, "email"))
                and status in ("Confirmed", "Checked In", "Completed"))


def _portal_identity():
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(frappe._("Inicie sesión para consultar sus reservas"), frappe.PermissionError)
    email = (frappe.db.get_value("User", user, "email") or "").strip().casefold()
    if not email:
        frappe.throw(frappe._("Su cuenta necesita un correo electrónico"), frappe.PermissionError)
    return user, email


@rate_limit(limit=5, seconds=3600)
def request_guest_account(token):
    """Offer a Website User only to the email on a signed confirmed booking."""
    data = verify(token)
    if data.get("doctype") != "HS Booking" or not data.get("name"):
        frappe.throw(frappe._("Use el enlace de una reserva confirmada"), frappe.PermissionError)
    booking = frappe.get_doc("HS Booking", data["name"])
    prop = enabled(booking.property)
    if booking.company != prop.company or booking.status not in ("Confirmed", "Checked In", "Completed") or not booking.guest:
        frappe.throw(frappe._("La reserva no admite acceso al portal"), frappe.PermissionError)
    guest = frappe.db.sql(
        "SELECT name,full_name,email FROM `tabHS Guest` WHERE name=%s AND property=%s AND company=%s",
        (booking.guest, prop.name, prop.company), as_dict=True)
    if not guest or not guest[0].email:
        frappe.throw(frappe._("Recepción debe registrar un correo para este huésped"))
    from frappe.utils import escape_html, random_string, validate_email_address

    email = guest[0].email.strip().lower()
    validate_email_address(email, throw=True)
    existing = frappe.db.sql("SELECT name FROM `tabUser` WHERE email=%s FOR UPDATE", (email,), as_dict=True)
    if not existing:
        account = frappe.get_doc({"doctype": "User", "email": email,
            "first_name": escape_html((guest[0].full_name or "Huésped").strip()[:140]),
            "enabled": 1, "user_type": "Website User", "send_welcome_email": 1,
            "new_password": random_string(20)})
        account.flags.ignore_permissions = True
        account.flags.ignore_password_policy = True
        account.insert()
        if not account.flags.email_sent:
            frappe.throw(frappe._("No se pudo enviar el acceso; recepción debe revisar el correo saliente"))
    # Identical response for an existing account, including a disabled one.
    return {"requested": True}


@rate_limit(limit=10, seconds=60)
def claim_booking(token):
    """A signed booking link plus matching login email explicitly links one guest."""
    user, email = _portal_identity()
    data = verify(token)
    if data.get("doctype") != "HS Booking" or not data.get("name"):
        frappe.throw(frappe._("Use el enlace de una reserva confirmada"), frappe.PermissionError)
    booking = frappe.get_doc("HS Booking", data["name"])
    prop = enabled(booking.property)
    if booking.company != prop.company or booking.status not in ("Confirmed", "Checked In", "Completed") or not booking.guest:
        frappe.throw(frappe._("La reserva no admite acceso al portal"), frappe.PermissionError)
    rows = frappe.db.sql(
        "SELECT name,property,company,email,portal_user FROM `tabHS Guest` WHERE name=%s FOR UPDATE",
        (booking.guest,), as_dict=True)
    if not rows:
        frappe.throw(frappe._("La reserva no tiene un huésped válido"), frappe.PermissionError)
    guest = rows[0]
    if guest.property != prop.name or guest.company != prop.company or (guest.email or "").strip().casefold() != email:
        frappe.throw(frappe._("El correo de su cuenta no coincide con el de la reserva"), frappe.PermissionError)
    if guest.portal_user != user:
        frappe.db.set_value("HS Guest", guest.name, "portal_user", user)
        from hospitality_suite.service import audit
        with operation(prop):
            audit(prop, "Claim guest portal", frappe._dict(doctype="HS Guest", name=guest.name),
                  details={"user": user, "previous_user": guest.portal_user,
                           "booking": booking.name})
    return {"booking": booking.name, "linked": True}


def guest_portal_records(offset=0, page_length=25):
    """Read only stays, bookings and passes for explicitly claimed guest records."""
    user, email = _portal_identity()
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación del portal"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(frappe._("Revise la paginación del portal"))
    rows = frappe.db.sql("""
        SELECT records.kind,records.name,records.property_name,records.status,
               records.starts_at,records.ends_at,records.currency,records.amount,records.time_zone
        FROM (
            SELECT 'Reserva' AS kind,b.name,p.property_name,b.status,b.starts_at,b.ends_at,
                   b.currency,b.amount,p.time_zone
              FROM `tabHS Booking` b
              JOIN `tabHS Guest` g ON g.name=b.guest AND g.property=b.property AND g.company=b.company
              JOIN `tabHS Property` p ON p.name=b.property AND p.company=b.company
             WHERE g.portal_user=%s AND LOWER(TRIM(g.email))=%s AND p.portal_enabled=1
               AND b.status IN ('Confirmed','Checked In','Completed','Cancelled','No Show')
            UNION ALL
            SELECT 'Estancia' AS kind,s.name,p.property_name,s.status,s.starts_at,s.ends_at,
                   s.currency,s.amount,p.time_zone
              FROM `tabHS Stay` s
              JOIN `tabHS Guest` g ON g.name=s.guest AND g.property=s.property AND g.company=s.company
              JOIN `tabHS Property` p ON p.name=s.property AND p.company=s.company
             WHERE g.portal_user=%s AND LOWER(TRIM(g.email))=%s AND p.portal_enabled=1
            UNION ALL
            SELECT 'Day Pass' AS kind,d.name,p.property_name,d.status,d.starts_at,d.ends_at,
                   p.currency,NULL AS amount,p.time_zone
              FROM `tabHS Day Pass` d
              JOIN `tabHS Guest` g ON g.name=d.guest AND g.property=d.property AND g.company=d.company
              JOIN `tabHS Property` p ON p.name=d.property AND p.company=d.company
             WHERE g.portal_user=%s AND LOWER(TRIM(g.email))=%s AND p.portal_enabled=1
        ) records
        ORDER BY records.starts_at DESC,records.kind,records.name
        LIMIT %s OFFSET %s
    """, [user, email] * 3 + [page_length + 1, offset], as_dict=True)
    more = len(rows) > page_length
    for row in rows[:page_length]:
        zone = frappe._dict(time_zone=row.pop("time_zone"))
        row.starts_at = local(row.starts_at, zone).strftime("%Y-%m-%d %H:%M")
        row.ends_at = local(row.ends_at, zone).strftime("%Y-%m-%d %H:%M")
    return {"user": user, "offset": offset, "page_length": page_length,
            "has_more": more, "records": rows[:page_length]}


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
                channel="Web",experiences=frappe.parse_json(request_doc.experiences or "[]"),acceptance=data.get("acceptance"))
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
