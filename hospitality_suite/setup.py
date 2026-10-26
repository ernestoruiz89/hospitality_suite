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
    allowed={"property_name","company","organization","new_organization","mode","currency","time_zone","business_date","close_time"}
    if (not isinstance(values,dict) or not isinstance(request_key,str) or
            not request_key.strip() or len(request_key)>140 or any(k not in allowed for k in values)):
        frappe.throw(frappe._("Configuración no válida"))
    submitted=dict(values)
    values={**values,"mode":normalize_mode(values["mode"])} if "mode" in values else values
    new_organization=values.get("new_organization")
    if pms:
        if new_organization is not None:
            if (values.get("organization") or values.get("company") or
                    not isinstance(new_organization,dict) or
                    set(new_organization)-{"legal_name","tax_id","tax_regime"} or
                    not isinstance(new_organization.get("legal_name"),str) or
                    not new_organization["legal_name"].strip() or
                    len(new_organization["legal_name"].strip())>140 or
                    not isinstance(new_organization.get("tax_id") or "",str) or
                    len(new_organization.get("tax_id") or "")>140 or
                    new_organization.get("tax_regime","General") not in ("General","Cuota Fija")):
                frappe.throw(frappe._("Revise la entidad legal nueva"))
            scope="new-pms-organization"
        elif isinstance(values.get("organization"),str) and values["organization"].strip():
            scope=values["organization"]
        else:
            frappe.throw(frappe._("Seleccione o cree una entidad legal"))
    elif values.get("organization") or new_organization is not None:
        frappe.throw(frappe._("La vinculación de una entidad propia requiere migración contable"))
    else:
        scope=values.get("company")
    for field in ("property_name","currency") + (() if pms else ("company",)):
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
    key=hashlib.sha256(f"{frappe.session.user}|{scope}|create_property|{request_key}".encode()).hexdigest()
    digest=hashlib.sha256(canonical(submitted).encode()).hexdigest()
    lock_name="hs-property-"+hashlib.sha256(f"{frappe.local.site}|{key}".encode()).hexdigest()[:48]
    if frappe.db.sql("SELECT GET_LOCK(%s, 30)",lock_name)[0][0]!=1:
        frappe.throw(frappe._("No se pudo reservar el alta del establecimiento"))
    try:
        prior=frappe.db.sql("SELECT payload_hash,result FROM `tabHS Request` WHERE request_key=%s FOR UPDATE",(key,),as_dict=True)
        if prior:
            if prior[0].payload_hash!=digest:
                frappe.throw(frappe._("La clave ya fue utilizada con otros datos"))
            return frappe.parse_json(prior[0].result)
        savepoint="hs_create_"+key[:24]
        frappe.db.savepoint(savepoint)
        try:
            with operation():
                if pms:
                    if new_organization is not None:
                        organization=frappe.get_doc(dict(doctype="HS Organization",
                            legal_name=new_organization["legal_name"].strip(),
                            tax_id=(new_organization.get("tax_id") or "").strip(),
                            tax_regime=new_organization.get("tax_regime") or "General",
                            base_currency=values["currency"],active=1)).insert()
                    else:
                        organization=frappe.get_doc("HS Organization",values["organization"],for_update=True)
                        if not organization.active or organization.base_currency!=values["currency"]:
                            frappe.throw(frappe._("La entidad legal debe estar activa y usar la moneda indicada"))
                    values={**values,"organization":organization.name,"company":organization.name}
                else:
                    frappe.get_doc("Company",values["company"],for_update=True).check_permission("read")
                doc=frappe.get_doc(dict(doctype="HS Property",**{k:v for k,v in values.items() if k not in {"time_zone","close_time","business_date","new_organization"}},
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
    finally:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)",lock_name)


def onboarding_options():
    from hospitality_suite.standalone_accounting import provider

    if not is_system():
        frappe.throw(frappe._("Se requiere administración del sistema"),frappe.PermissionError)
    mode=provider()
    return dict(provider=mode,
        currencies=frappe.get_all("Currency",filters={"enabled":1},
            pluck="name",order_by="name asc"),
        organizations=frappe.get_all("HS Organization",filters={"active":1},
            fields=["name","legal_name","base_currency","tax_regime"],
            order_by="legal_name asc") if mode=="pms" else [],
        companies=frappe.get_all("Company",fields=["name","default_currency"],
            order_by="name asc") if mode=="erpnext" else [])


def create_operational_user(data):
    """Create an identity without assigning hotel access or operational roles."""
    if not is_system():
        frappe.throw(frappe._("Solo administración del sistema puede crear usuarios"),
                     frappe.PermissionError)
    if not isinstance(data, dict) or set(data) != {"email", "first_name"}:
        frappe.throw(frappe._("Revise los datos del usuario"))
    email, first_name = data["email"], data["first_name"]
    if not isinstance(email, str) or not isinstance(first_name, str):
        frappe.throw(frappe._("Revise los datos del usuario"))
    email, first_name = email.strip(), first_name.strip()
    frappe.utils.validate_email_address(email, throw=True)
    if not first_name or len(first_name) > 140:
        frappe.throw(frappe._("Indique un nombre de hasta 140 caracteres"))
    if frappe.db.exists("User", email):
        frappe.throw(frappe._("El usuario ya existe; conceda acceso desde Usuarios"))
    user = frappe.get_doc(dict(doctype="User", email=email,
        first_name=first_name, send_welcome_email=0,
        user_type="System User", roles=[dict(role="Desk User")])).insert()
    return dict(user=user.name, created=True)


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
        # Property commands lock different hotel rows. Serialize grants for the
        # same identity before reading its roles or other hotel assignments.
        frappe.db.sql("SELECT name FROM `tabUser` WHERE name=%s FOR UPDATE", (email,))
        user=frappe.get_doc("User",email,for_update=True)
        if not user.enabled or user.user_type!="System User":
            frappe.throw(frappe._("El usuario debe estar habilitado para Desk"))
        if is_system(email):
            frappe.throw(frappe._("Un administrador del sistema ya puede acceder a todos los establecimientos"))
        existing_roles = {row.role for row in frappe.db.sql(
            "SELECT role FROM `tabHas Role` WHERE parenttype='User' AND parent=%s FOR UPDATE",
            (email,), as_dict=True)}.intersection(ROLES)
        selected_roles = set(roles)
        if existing_roles - selected_roles:
            frappe.throw(frappe._("Incluya los roles HS que el usuario ya posee en la instancia"))
        other_access = frappe.db.sql(
            "SELECT name FROM `tabHS Access` WHERE user=%s AND property!=%s FOR UPDATE",
            (user.name, prop.name))
        if selected_roles - existing_roles and other_access:
            frappe.throw(frappe._("Agregar roles globales ampliaría permisos en otros establecimientos; use otro usuario o gestione su función para toda la instancia"))
        user.add_roles(*roles)
    else:
        if not data.get("first_name"):
            frappe.throw(frappe._("El usuario no existe; créelo primero en Usuarios > Nuevo usuario"))
        user=frappe.get_doc(dict(doctype="User",email=email,first_name=data["first_name"],send_welcome_email=0,
                                user_type="System User",language="es",time_zone=prop.time_zone,
                                roles=[dict(role=r) for r in roles])).insert()
    if not frappe.db.exists("HS Access",{"user":user.name,"property":prop.name}):
        insert("HS Access",prop,user=user.name)
    audit(prop,"Grant operational access",prop,data.get("reason"),dict(user=user.name,roles=roles))
    return dict(user=user.name,property=prop.name,message="Acceso concedido. El administrador gestiona el inicio de sesión por los mecanismos estándar de Frappe.")


def access_board(property_name, offset=0, page_length=50):
    prop = require(property_name, "setup")
    if not is_system():
        frappe.throw(frappe._("Solo administración del sistema puede consultar accesos"), frappe.PermissionError)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de accesos"))
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Revise la paginación de accesos"))
    rows = frappe.get_all("HS Access", filters={"property": prop.name,
        "company": prop.company}, fields=["name", "user"], order_by="user asc",
        limit_start=offset, limit_page_length=page_length + 1)
    result = []
    for row in rows[:page_length]:
        user = frappe.db.get_value("User", row.user,
            ["full_name", "enabled", "user_type"], as_dict=True)
        result.append(dict(name=row.name, user=row.user,
            full_name=user.full_name if user else row.user,
            enabled=bool(user and user.enabled),
            user_type=user.user_type if user else None,
            roles=[role for role in ROLES if role in frappe.get_roles(row.user)]))
    return dict(property=prop.name, roles=ROLES, users=result,
        offset=offset, has_more=len(rows) > page_length)


def revoke_user_access(prop, data):
    if not is_system():
        frappe.throw(frappe._("Solo administración del sistema puede retirar accesos"), frappe.PermissionError)
    if not isinstance(data, dict) or set(data) - {"user", "reason"}:
        frappe.throw(frappe._("Revise la solicitud de retiro de acceso"))
    user, reason = data.get("user"), data.get("reason")
    if (not isinstance(user, str) or not user or
            not isinstance(reason, str) or not reason.strip() or len(reason) > 1000):
        frappe.throw(frappe._("Indique usuario y motivo del retiro"))
    access = frappe.db.get_value("HS Access", {"user": user,
        "property": prop.name, "company": prop.company}, "name")
    if not access:
        frappe.throw(frappe._("El usuario no tiene acceso a este establecimiento"))
    frappe.delete_doc("HS Access", access)
    audit(prop, "Revoke operational access", prop, reason.strip(),
          dict(user=user, access=access))
    return dict(user=user, property=prop.name, revoked=True)


def document_settings(prop):
    from hospitality_suite.security import require
    require(prop.name,"setup")
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms":
        return dict(series={}, formats={}, roles=ROLES, can_manage_users=is_system())
    series={dt:[r for r in (frappe.get_meta(dt).get_field("naming_series").options or "").splitlines() if r] for dt in ("Sales Invoice","Payment Entry")}
    formats={dt:frappe.get_all("Print Format",filters={"doc_type":dt,"disabled":0},pluck="name") for dt in ("Sales Invoice","HS Payment","HS Booking","HS Stay","HS Shift")}
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
        if value and not frappe.db.exists("Print Format",{"name":value,"doc_type":dt,"disabled":0}):
            frappe.throw(frappe._("Seleccione un formato habilitado para ")+dt)
