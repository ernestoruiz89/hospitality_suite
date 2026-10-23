"""Explicit setup actions; no implicit financial masters or broad ERP roles."""
import frappe
from datetime import timedelta
import hashlib
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from frappe.utils import getdate, now_datetime

from hospitality_suite.schema import ROLES
from hospitality_suite.security import is_system,require
from hospitality_suite.service import insert,audit


def initial_business_date(time_zone,close_time,at=None):
    """Before the local cutoff, a newly opened property still belongs to D-1."""
    from hospitality_suite.time import cutoff_time,local
    prop=frappe._dict(time_zone=time_zone)
    moment=local(at or now_datetime(),prop)
    return moment.date()-timedelta(days=moment.time()<cutoff_time(close_time))


def create_property(values,request_key):
    from hospitality_suite.service import canonical,operation
    from hospitality_suite.mode import normalize_mode
    from hospitality_suite.time import cutoff_time
    from hospitality_suite.standalone_accounting import provider
    pms = provider() == "pms"
    if not is_system():
        frappe.throw(frappe._("Se requiere administración del sistema"),frappe.PermissionError)
    allowed={"property_name","company","organization","mode","currency","time_zone","business_date","close_time"}
    if not isinstance(request_key,str) or not request_key.strip() or len(request_key)>140 or any(k not in allowed for k in values):
        frappe.throw(frappe._("Configuración no válida"))
    submitted=values
    values={**values,"mode":normalize_mode(values["mode"])} if "mode" in values else values
    if pms:
        organization = frappe.get_doc("HS Organization", values.get("organization"), for_update=True)
        if not organization.active or organization.base_currency != values.get("currency"):
            frappe.throw(frappe._("La entidad legal debe estar activa y usar la moneda indicada"))
        values = {**values, "company": organization.name}
    elif values.get("organization"):
        frappe.throw(frappe._("La vinculación de una entidad propia requiere migración contable"))
    for field in ("property_name","company","currency"):
        if not isinstance(values.get(field),str) or not values[field].strip():
            frappe.throw(frappe._("Indique nombre, compañía y moneda del establecimiento"))
    time_zone=values.get("time_zone")
    if time_zone in (None,""):
        time_zone="America/Managua"
    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError,ValueError,TypeError):
        frappe.throw(frappe._("Seleccione una zona horaria IANA válida"))
    close_time=cutoff_time(values.get("close_time")).isoformat()
    business_date=values.get("business_date")
    if business_date not in (None,""):
        try:
            if not isinstance(business_date,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",business_date):
                raise ValueError()
            business_date=getdate(business_date)
        except (ValueError,TypeError):
            frappe.throw(frappe._("Indique una fecha operativa inicial válida (AAAA-MM-DD)"))
    # Serialize the absence of a request as well as its completed result. There
    # is no HS Property to lock yet; Company is the existing parent resource.
    if not pms:
        frappe.get_doc("Company",values["company"],for_update=True).check_permission("read")
    key=hashlib.sha256(f"{frappe.session.user}|{values['company']}|create_property|{request_key}".encode()).hexdigest()
    digest=hashlib.sha256(canonical(submitted).encode()).hexdigest()
    prior=frappe.db.sql("SELECT payload_hash,result FROM `tabHS Request` WHERE request_key=%s FOR UPDATE",(key,),as_dict=True)
    if prior:
        if prior[0].payload_hash!=digest:
            frappe.throw(frappe._("La clave ya fue utilizada con otros datos"))
        return frappe.parse_json(prior[0].result)
    savepoint="hs_create_"+key[:24]
    frappe.db.savepoint(savepoint)
    try:
        with operation():
            doc=frappe.get_doc(dict(doctype="HS Property",**{k:v for k,v in values.items() if k not in {"time_zone","close_time","business_date"}},
                                    time_zone=time_zone,close_time=close_time,
                                    business_date=business_date or initial_business_date(time_zone,close_time)))
            doc.insert()
            result=dict(property=doc.name)
            audit(doc,"Create property",doc,details=dict(business_date=doc.business_date,close_time=close_time,time_zone=time_zone))
            insert("HS Request",doc,request_key=key,payload_hash=digest,operation="create_property",result=canonical(result))
        return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def assign_user(prop,data):
    if not is_system():
        frappe.throw(frappe._("Solo administración del sistema puede conceder accesos"),frappe.PermissionError)
    roles=data.get("roles") or []
    if not isinstance(roles,list) or not roles or any(r not in ROLES for r in roles):
        frappe.throw(frappe._("Seleccione roles operativos de Hospitality Suite"))
    email=data.get("email") or ""
    frappe.utils.validate_email_address(email,throw=True)
    if email in ("Administrator","Guest"):
        frappe.throw(frappe._("Seleccione un usuario operativo"))
    if frappe.db.exists("User",email):
        user=frappe.get_doc("User",email)
        if not user.enabled or user.user_type!="System User":
            frappe.throw(frappe._("El usuario debe estar habilitado para Desk"))
        user.add_roles(*roles)
    else:
        if not data.get("first_name"):
            frappe.throw(frappe._("Indique el nombre del usuario"))
        user=frappe.get_doc(dict(doctype="User",email=email,first_name=data["first_name"],send_welcome_email=0,
                                user_type="System User",language="es",time_zone=prop.time_zone,
                                roles=[dict(role=r) for r in roles])).insert()
    if not frappe.db.exists("HS Access",{"user":user.name,"property":prop.name}):
        insert("HS Access",prop,user=user.name)
    audit(prop,"Grant operational access",prop,data.get("reason"),dict(user=user.name,roles=roles))
    return dict(user=user.name,property=prop.name,message="Acceso concedido. El administrador gestiona el inicio de sesión por los mecanismos estándar de Frappe.")


def document_settings(prop):
    from hospitality_suite.security import require
    require(prop.name,"setup")
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms":
        return dict(series={}, formats={}, roles=ROLES, can_manage_users=is_system())
    series={dt:[r for r in (frappe.get_meta(dt).get_field("naming_series").options or "").splitlines() if r] for dt in ("Sales Invoice","Payment Entry")}
    formats={dt:["Standard"]+frappe.get_all("Print Format",filters={"doc_type":dt,"disabled":0},pluck="name") for dt in ("Sales Invoice","HS Payment","HS Booking","HS Stay","HS Shift")}
    return dict(series=series,formats=formats,roles=ROLES,can_manage_users=is_system())


def validate_document_settings(prop):
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms":
        return
    for field,dt in (("invoice_series","Sales Invoice"),("payment_series","Payment Entry")):
        value=prop.get(field)
        options=(frappe.get_meta(dt).get_field("naming_series").options or "").splitlines()
        if value and value not in options:
            frappe.throw(frappe._("Seleccione una serie existente de ")+dt+frappe._("; registre nuevas series mediante Naming Series de Frappe"))
    for field,dt in (("invoice_print_format","Sales Invoice"),("receipt_print_format","HS Payment")):
        value=prop.get(field)
        if value and value!="Standard" and not frappe.db.exists("Print Format",{"name":value,"doc_type":dt,"disabled":0}):
            frappe.throw(frappe._("Seleccione un formato habilitado para ")+dt)
