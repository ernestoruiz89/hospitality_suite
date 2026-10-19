"""Explicit setup actions; no implicit financial masters or broad ERP roles."""
import frappe

from hospitality_suite.schema import ROLES
from hospitality_suite.security import is_system,require
from hospitality_suite.service import insert,audit


def assign_user(prop,data):
    if not is_system():
        frappe.throw("Solo administración del sistema puede conceder accesos",frappe.PermissionError)
    roles=data.get("roles") or []
    if not isinstance(roles,list) or not roles or any(r not in ROLES for r in roles):
        frappe.throw("Seleccione roles operativos de Hospitality Suite")
    email=data.get("email") or ""
    frappe.utils.validate_email_address(email,throw=True)
    if email in ("Administrator","Guest"):
        frappe.throw("Seleccione un usuario operativo")
    if frappe.db.exists("User",email):
        user=frappe.get_doc("User",email)
        if not user.enabled or user.user_type!="System User":
            frappe.throw("El usuario debe estar habilitado para Desk")
        user.add_roles(*roles)
    else:
        if not data.get("first_name"):
            frappe.throw("Indique el nombre del usuario")
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
    series={dt:[r for r in (frappe.get_meta(dt).get_field("naming_series").options or "").splitlines() if r] for dt in ("Sales Invoice","Payment Entry")}
    formats={dt:["Standard"]+frappe.get_all("Print Format",filters={"doc_type":dt,"disabled":0},pluck="name") for dt in ("Sales Invoice","HS Payment","HS Booking","HS Stay","HS Shift")}
    return dict(series=series,formats=formats,roles=ROLES,can_manage_users=is_system())


def validate_document_settings(prop):
    for field,dt in (("invoice_series","Sales Invoice"),("payment_series","Payment Entry")):
        value=prop.get(field)
        options=(frappe.get_meta(dt).get_field("naming_series").options or "").splitlines()
        if value and value not in options:
            frappe.throw("Seleccione una serie existente de "+dt+"; registre nuevas series mediante Naming Series de Frappe")
    for field,dt in (("invoice_print_format","Sales Invoice"),("receipt_print_format","HS Payment")):
        value=prop.get(field)
        if value and value!="Standard" and not frappe.db.exists("Print Format",{"name":value,"doc_type":dt,"disabled":0}):
            frappe.throw("Seleccione un formato habilitado para "+dt)
