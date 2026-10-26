"""Authorization is enforced before every query/mutation, including direct REST access."""
from contextlib import contextmanager
import frappe
from frappe import _

from hospitality_suite.schema import SCOPED, MANAGERS,ROLES,STANDARD_SCOPED

ACTIONS = {
    "setup": MANAGERS, "reserve": MANAGERS + ["HS Receptionist"],
    "stay": MANAGERS + ["HS Receptionist"],
    "finance": MANAGERS + ["HS Cashier", "HS Accountant"],
    "journal": ["HS Administrator", "HS Manager", "HS Accountant"],
    "chart": ["HS Administrator", "HS Manager", "HS Accountant"],
    "commission": MANAGERS + ["HS Accountant"],
    "petty": [role for role in ROLES if role != "HS Auditor"],
    "clean": MANAGERS + ["HS Housekeeping"], "inspect": MANAGERS,
    "maintain": MANAGERS + ["HS Maintenance"],
    "block": MANAGERS + ["HS Receptionist"],
    "service": MANAGERS + ["HS Receptionist", "HS Cashier"],
    "laundry": MANAGERS + ["HS Receptionist", "HS Housekeeping", "HS Accountant"],
    "report": MANAGERS + ["HS Accountant", "HS Auditor"], "approve": MANAGERS[:2],
    "cash_approve": MANAGERS,
    "guest": MANAGERS + ["HS Receptionist"],
    "incident": MANAGERS + ["HS Housekeeping","HS Maintenance"],
    "inventory":MANAGERS+["HS Accountant"],
    "ticket": MANAGERS + ["HS Receptionist", "HS Housekeeping", "HS Maintenance"],
}


def is_system(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def allowed_properties(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return []
    if is_system(user):
        return frappe.get_all("HS Property", pluck="name")
    rows = frappe.get_all("HS Access", filters={"user": user}, fields=["property", "company"])
    result = []
    for row in rows:
        company = frappe.db.get_value("HS Property", row.property, "company")
        if company and company == row.company:
            result.append(row.property)
    return result


def can_receive_petty_cash(prop, user):
    """A handover recipient must be able to accept it in this property."""
    return bool(user and user != "Guest" and
        frappe.db.get_value("User", user, "enabled") and
        prop.name in allowed_properties(user) and
        (is_system(user) or set(ACTIONS["petty"]).intersection(frappe.get_roles(user))))


def petty_handover_users(prop):
    """Only show active recipients with this property's access and petty role."""
    access_users = set(frappe.get_all("HS Access", filters={
        "property": prop.name, "company": prop.company}, pluck="user"))
    petty_users = set(frappe.get_all("Has Role", filters={
        "parenttype": "User", "parent": ["in", list(access_users)],
        "role": ["in", ACTIONS["petty"]]}, pluck="parent")) if access_users else set()
    system_users = set(frappe.get_all("Has Role", filters={
        "parenttype": "User", "role": "System Manager"}, pluck="parent"))
    names = (access_users & petty_users) | system_users | {"Administrator"}
    names.discard("Guest")
    return frappe.get_all("User", filters={"name": ["in", list(names)],
        "enabled": 1}, fields=["name", "full_name"],
        order_by="full_name asc, name asc")


def app_permission():
    """Expose the Frappe 16 app tile only to Suite users with a visible property."""
    user = frappe.session.user
    return user != "Guest" and (is_system(user) or bool(set(frappe.get_roles(user)).intersection(ROLES) and allowed_properties(user)))


def require(property_name, action=None):
    if frappe.session.user == "Guest" or property_name not in allowed_properties():
        frappe.throw(_("No tiene acceso a este establecimiento"), frappe.PermissionError)
    if action and not is_system() and not set(ACTIONS[action]).intersection(frappe.get_roles()):
        frappe.throw(_("No tiene permiso para esta operación"), frappe.PermissionError)
    return frappe.get_doc("HS Property", property_name)


def warehouse_allowed(prop, name):
    """A configured shared warehouse may be unowned, but never owned by another hotel."""
    if not name:
        return False
    warehouse = frappe.db.get_value("Warehouse", name,
        ["company", "is_group", "hs_property"], as_dict=True)
    return bool(warehouse and warehouse.company == prop.company and
        not warehouse.is_group and warehouse.hs_property in (None, "", prop.name) and
        (warehouse.hs_property == prop.name or
         name in (prop.get("warehouse"), prop.get("laundry_warehouse"))))


@contextmanager
def selected_property(prop):
    """Bind a command/quote to one property, even for multi-property administrators."""
    before=getattr(frappe.local,"hs_selected_property",None)
    scope=(prop.name,prop.company)
    if before and before!=scope:
        frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)
    frappe.local.hs_selected_property=scope
    try:
        yield
    finally:
        frappe.local.hs_selected_property=before


def check_selected_reference(dt,name):
    scope=getattr(frappe.local,"hs_selected_property",None)
    if scope and dt in SCOPED:
        filters={"name":name,"company":scope[1]}
        filters["name" if dt=="HS Property" else "property"]=scope[0]
        if (dt=="HS Property" and name!=scope[0]) or not frappe.db.exists(dt,filters):
            frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)


def check_selected_document(doc):
    scope=getattr(frappe.local,"hs_selected_property",None)
    if scope and doc.doctype in SCOPED:
        if (doc.name if doc.doctype=="HS Property" else doc.property)!=scope[0] or doc.company!=scope[1]:
            frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)


def document(dt, name, action=None):
    check_selected_reference(dt,name)
    doc = frappe.get_doc(dt, name, for_update=bool(getattr(frappe.local, "hs_operation", False)))
    check_selected_document(doc)
    require(doc.name if dt == "HS Property" else doc.property, action)
    doc.check_permission("read")
    return doc


def property_document(prop,dt,name,action=None):
    """A multi-property user still must act inside the selected command scope."""
    if not frappe.db.get_value(dt,{"name":name,"property":prop.name,"company":prop.company},"name"):
        frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)
    doc=document(dt,name,action)
    if doc.property!=prop.name or doc.company!=prop.company:
        frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)
    return doc


def has_scope_permission(doc, user=None, permission_type=None, **kwargs):
    user = user or frappe.session.user
    prop = doc.name if doc.doctype == "HS Property" else doc.get("property")
    if not prop or prop not in allowed_properties(user):
        return False
    if doc.doctype != "HS Property":
        company = frappe.db.get_value("HS Property", prop, "company")
        if not company or doc.get("company") != company:
            return False
    if doc.doctype in ("HS Petty Cash Expense", "HS Petty Cash Rendition", "HS Petty Cash Handover") and not is_system(user) and not set(frappe.get_roles(user)).intersection(ACTIONS["finance"] + ACTIONS["report"]):
        if doc.doctype == "HS Petty Cash Handover":
            return user in (doc.outgoing, doc.incoming)
        return user == doc.responsible or user == frappe.db.get_value("HS Property", prop, "petty_cash_responsible")
    return True  # Controller hooks can restrict; native role permissions still apply.


def scope_query(dt, user=None):
    user = user or frappe.session.user
    props = allowed_properties(user)
    if not props:
        return "1=0"
    field = "name" if dt == "HS Property" else "property"
    names = ",".join(frappe.db.escape(v) for v in props)
    rule=f"`tab{dt}`.`{field}` IN ({names})"
    if dt != "HS Property":
        rule += (f" AND `tab{dt}`.`company`=(SELECT p.`company` FROM `tabHS Property` p "
                 f"WHERE p.`name`=`tab{dt}`.`property`)")
    if dt in ("HS Petty Cash Expense", "HS Petty Cash Rendition", "HS Petty Cash Handover") and not is_system(user) and not set(frappe.get_roles(user)).intersection(ACTIONS["finance"] + ACTIONS["report"]):
        escaped=frappe.db.escape(user)
        if dt == "HS Petty Cash Handover":
            rule+=f" AND (`tab{dt}`.`outgoing`={escaped} OR `tab{dt}`.`incoming`={escaped})"
        else:
            rule+=f" AND (`tab{dt}`.`responsible`={escaped} OR EXISTS(SELECT name FROM `tabHS Property` p WHERE p.name=`tab{dt}`.`property` AND p.petty_cash_responsible={escaped}))"
    return rule


for _dt in SCOPED:
    globals()["query_" + _dt.lower().replace(" ", "_")] = lambda user=None, dt=_dt: scope_query(dt, user)


def validate_file(doc, method=None):
    old = doc.get_doc_before_save()
    if ((doc.attached_to_doctype == "HS Historical Fiscal Document" or
            (old and old.attached_to_doctype == "HS Historical Fiscal Document")) and
            not getattr(frappe.local, "hs_fiscal_archive_import", False)):
        frappe.throw(_("El PDF fiscal histórico no admite cambios"), frappe.PermissionError)
    if doc.attached_to_doctype=="Asset":
        target=frappe.get_doc("Asset",doc.attached_to_name)
        if target.hs_property:
            from hospitality_suite.equipment import asset_permission
            if not asset_permission(target) or not doc.is_private:
                frappe.throw(frappe._("El archivo del activo debe ser privado y accesible por el rol y establecimiento"),frappe.PermissionError)
            target.check_permission("write")
    if doc.attached_to_doctype in ("Customer","Supplier","Contact","Address") and set(frappe.get_roles()).intersection(ROLES):
        target=frappe.get_doc(doc.attached_to_doctype,doc.attached_to_name)
        if not party_permission(target):
            frappe.throw(frappe._("El archivo no pertenece a una persona o proveedor autorizado"),frappe.PermissionError)
        if not doc.is_private:
            frappe.throw(frappe._("Los archivos de personas y proveedores de alojamiento deben ser privados"))
        target.check_permission("write")
    if doc.attached_to_doctype and (doc.attached_to_doctype.startswith("HS ") or doc.attached_to_doctype in STANDARD_SCOPED):
        target=frappe.get_doc(doc.attached_to_doctype,doc.attached_to_name)
        if doc.attached_to_doctype in STANDARD_SCOPED:
            if not target.get("hs_property"):
                return
            require(target.hs_property)
        else:
            require(target.name if target.doctype=="HS Property" else target.property)
        if not doc.is_private:
            frappe.throw(_("Los archivos de Hospitality Suite deben ser privados"))
        target.check_permission("write")


def private_evidence(url,target):
    if not url:
        return None
    files=frappe.get_all("File",filters={"file_url":url,"is_private":1,"attached_to_doctype":target.doctype,"attached_to_name":target.name},pluck="name")
    if not files or not url.startswith("/private/files/"):
        frappe.throw(frappe._("Adjunte una evidencia privada a este documento"))
    frappe.get_doc("File",files[0]).check_permission("read")
    return url


def file_permission(doc,user=None,permission_type=None,**kwargs):
    """A file's owner must not bypass the current parent scope or role."""
    if is_system(user):
        return True
    permission_type=permission_type or kwargs.get("ptype")
    dt,name=doc.get("attached_to_doctype"),doc.get("attached_to_name")
    if not dt or not name:
        return True
    roles=set(frappe.get_roles(user))
    if dt=="HS Property" or (dt.startswith("HS ") and frappe.get_meta(dt).has_field("property")):
        prop=name if dt=="HS Property" else frappe.db.get_value(dt,name,"property")
        if prop not in allowed_properties(user):
            return False
        if roles.intersection(ROLES):
            actions={"HS Guest":["guest","finance","report"],"HS Maintenance Order":["maintain","inspect","report"],"HS Incident":["incident","inspect","report"]}.get(dt)
            if actions and not any(roles.intersection(ACTIONS[action]) for action in actions):
                return False
        if dt in ("HS Petty Cash Expense", "HS Petty Cash Rendition", "HS Petty Cash Handover") and not has_scope_permission(frappe.get_doc(dt,name),user,permission_type):
            return False
    if dt in STANDARD_SCOPED and not standard_permission(frappe.get_doc(dt,name),user,permission_type):
        return False
    if dt in ("Customer","Supplier","Contact","Address") and not party_permission(frappe.get_doc(dt,name),user):
        return False
    if dt=="Asset":
        from hospitality_suite.equipment import asset_permission
        if not asset_permission(frappe.get_doc("Asset",name),user,permission_type):
            return False
    return True  # Frappe's native File hook still decides owner/parent permission.


def file_query(user=None):
    if is_system(user):
        return ""
    from hospitality_suite.schema import SCHEMA
    roles=set(frappe.get_roles(user))
    targets=",".join(frappe.db.escape(dt) for dt in SCOPED)
    branches=[]
    for dt in SCOPED:
        if not roles.intersection(SCHEMA[dt].get("roles",[])):
            continue
        actions={"HS Guest":["guest","finance","report"],"HS Maintenance Order":["maintain","inspect","report"],"HS Incident":["incident","inspect","report"]}.get(dt)
        if actions and not any(roles.intersection(ACTIONS[a]) for a in actions):
            continue
        branches.append(f"(`tabFile`.attached_to_doctype={frappe.db.escape(dt)} AND EXISTS(SELECT name FROM `tab{dt}` WHERE name=`tabFile`.attached_to_name AND ({scope_query(dt,user)})))")
    conditions=[f"(COALESCE(`tabFile`.attached_to_doctype,'') NOT IN ({targets}) OR ({' OR '.join(branches) or '1=0'}))"]
    for dt in STANDARD_SCOPED:
        rule=standard_query(dt,user)
        if rule:
            conditions.append(f"(COALESCE(`tabFile`.attached_to_doctype,'')!={frappe.db.escape(dt)} OR EXISTS(SELECT name FROM `tab{dt}` WHERE name=`tabFile`.attached_to_name AND ({rule})))")
    for dt in ("Customer","Supplier","Contact","Address","Asset"):
        if dt=="Asset":
            from hospitality_suite.equipment import asset_query
            rule=asset_query(user)
        else:
            rule=party_query(dt,user)
        if rule:
            conditions.append(f"(COALESCE(`tabFile`.attached_to_doctype,'')!={frappe.db.escape(dt)} OR EXISTS(SELECT name FROM `tab{dt}` WHERE name=`tabFile`.attached_to_name AND ({rule})))")
    return " AND ".join(conditions)


def realtime(property_name):
    users = frappe.get_all("HS Access", filters={"property": property_name}, pluck="user")
    users.append("Administrator")
    for user in set(users):
        # Events contain no document names, guests, financial values or room details.
        frappe.publish_realtime("hospitality_changed", {"property": property_name}, user=user, after_commit=True)


def standard_permission(doc, user=None, permission_type=None, **kwargs):
    permission_type=permission_type or kwargs.get("ptype")
    roles=set(frappe.get_roles(user))
    if not is_system(user) and roles.intersection(ROLES) and not roles.intersection(set(ROLES)-{"HS Housekeeping","HS Maintenance"}) and doc.doctype!="Stock Entry":
        return False
    if "HS Auditor" in roles and not roles.intersection(set(ROLES)-{"HS Auditor"}) and not is_system(user) and permission_type not in (None,"read","select","print","export","report"):
        return False
    prop = doc.get("hs_property")
    if doc.get("hs_stay"):
        prop = frappe.db.get_value("HS Stay", doc.hs_stay, "property")
    elif doc.get("hs_booking"):
        prop = frappe.db.get_value("HS Booking", doc.hs_booking, "property")
    if not prop and not is_system(user) and set(frappe.get_roles(user)).intersection(ROLES):
        return False
    if prop and prop not in allowed_properties(user):
        return False
    return True


def standard_query(dt, user=None):
    if is_system(user):
        return ""
    roles=set(frappe.get_roles(user))
    if roles.intersection(ROLES) and not roles.intersection(set(ROLES)-{"HS Housekeeping","HS Maintenance"}) and dt!="Stock Entry":
        return "1=0"
    props = allowed_properties(user)
    permitted = ",".join(frappe.db.escape(v) for v in props) or "NULL"
    # Hospitality operators only see standard documents belonging to their scope.
    if set(frappe.get_roles(user)).intersection(ROLES):
        return f"`tab{dt}`.hs_property IN ({permitted})"
    return f"(`tab{dt}`.hs_property IS NULL OR `tab{dt}`.hs_property='' OR `tab{dt}`.hs_property IN ({permitted}))"


for _standard in STANDARD_SCOPED:
    globals()["query_" + _standard.lower().replace(" ", "_")] = lambda user=None, dt=_standard: standard_query(dt, user)


def validate_standard(doc, method=None):
    original=doc.get_doc_before_save()
    if original and original.get("hs_property") and not doc.get("hs_property") and not doc.get("hs_stay"):
        frappe.throw(frappe._("No puede quitar el origen de un documento vinculado a alojamiento"))
    if not doc.get("hs_property") and not doc.get("hs_stay") and not doc.get("hs_booking") and not is_system() and set(frappe.get_roles()).intersection(ROLES):
        properties=frappe.get_all("HS Property",filters={"name":["in",allowed_properties()],"company":doc.company},pluck="name")
        if len(properties)==1:
            doc.hs_property=properties[0]
        else:
            frappe.throw(frappe._("Seleccione un establecimiento autorizado para este documento"))
    if not doc.get("hs_stay") and not doc.get("hs_property") and not doc.get("hs_booking"):
        return
    prop_name = doc.get("hs_property")
    if doc.get("hs_stay"):
        stay = frappe.get_doc("HS Stay", doc.hs_stay)
        if prop_name and prop_name != stay.property:
            frappe.throw(frappe._("La estancia y el establecimiento no coinciden"))
        prop_name = stay.property
    if doc.get("hs_booking"):
        booking=document("HS Booking",doc.hs_booking)
        if doc.docstatus != 2 and (booking.status == 'Draft' or (booking.get('draft_data') and not booking.quote_snapshot)):
            frappe.throw(frappe._('Un borrador de reserva no admite documentos financieros; confirme la reserva primero'))
        if prop_name and prop_name!=booking.property:
            frappe.throw(frappe._("La reserva y el establecimiento no coinciden"))
        prop_name=booking.property
        party=doc.get("customer") or doc.get("party")
        payers=[booking.customer]+frappe.get_all("HS Folio",filters={"booking":booking.name},pluck="customer")
        if party and party not in payers:
            frappe.throw(frappe._("El pagador no coincide con la reserva o sus cuentas"))
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms" and not getattr(frappe.local, "hs_cutover_opening", False):
        frappe.throw(frappe._("Este establecimiento sigue usando el libro PMS; los documentos ERPNext de alojamiento requieren el corte verificado"))
    prop = require(prop_name)
    scope=getattr(frappe.local,"hs_selected_property",None)
    if scope and (prop.name,prop.company)!=scope:
        frappe.throw(_("El documento no pertenece al establecimiento seleccionado"),frappe.PermissionError)
    if doc.company != prop.company:
        frappe.throw(frappe._("El documento contable pertenece a otra compañía"))
    if doc.doctype in ("Purchase Order","Purchase Receipt","Purchase Invoice") and doc.get("supplier"):
        if not frappe.db.exists("HS Supplier",{"property":prop.name,"supplier":doc.supplier,"active":1}):
            frappe.throw(frappe._("El proveedor no está habilitado en este establecimiento"))
    for row in [doc]+list(doc.get("items") or []):
        for field in ("warehouse","s_warehouse","t_warehouse","set_warehouse","set_from_warehouse"):
            if row.get(field) and not warehouse_allowed(prop, row.get(field)):
                frappe.throw(frappe._("El almacén no está asignado a este establecimiento"),frappe.PermissionError)
    doc.hs_property = prop.name
    from hospitality_suite.service_accounting import apply_defaults
    apply_defaults(doc,prop,original)
    old=doc.get_doc_before_save()
    if old and old.get("hs_property") and (old.hs_property!=doc.hs_property or old.get("hs_stay")!=doc.get("hs_stay")):
        frappe.throw(frappe._("No puede quitar ni cambiar el origen de un documento vinculado a alojamiento"))
    if not getattr(frappe.local, "hs_operation", False):
        require(prop_name,"approve" if doc.doctype=="Stock Reconciliation" else "inventory" if doc.doctype in ("Stock Entry","Purchase Order","Purchase Receipt","Purchase Invoice") else "finance")
    from hospitality_suite.payment_policies import validate_native
    validate_native(doc,prop,original)
    if doc.get("hs_folio"):
        folio = document("HS Folio", doc.hs_folio)
        if not doc.get("hs_booking") and folio.booking:
            doc.hs_booking=folio.booking
        belongs=folio.stay==doc.get("hs_stay") if folio.stay else (folio.booking==doc.get("hs_booking") or (doc.get("hs_stay") and folio.booking==frappe.db.get_value("HS Stay",doc.hs_stay,"booking")))
        if folio.property != prop.name or not belongs:
            frappe.throw(frappe._("Cuenta y estancia incompatibles"))
        party = doc.get("customer") or doc.get("party")
        if party and party != folio.customer:
            frappe.throw(frappe._("El cliente del documento no es el pagador de la cuenta"))
    if doc.get("hs_shift"):
        shift = document("HS Shift", doc.hs_shift)
        reconciles=reference_reconciliation(doc,original)
        if shift.property != prop.name or (shift.status != "Open" and not reconciles):
            frappe.throw(frappe._("No puede registrar movimientos en un turno cerrado"))
    if doc.doctype == "Sales Invoice":
        from hospitality_suite.native_pos import validate as validate_pos
        validate_pos(doc,prop)
        if doc.discount_amount or doc.additional_discount_percentage:
            frappe.throw(frappe._("Registre los descuentos y cortesías mediante un ajuste autorizado de la cuenta"))
        used_sources=set()
        for row in doc.items:
            if row.get("hs_charge"):
                charge = document("HS Charge", row.hs_charge)
                folio=document("HS Folio",charge.folio)
                if charge.property!=prop.name or (doc.get("hs_stay") and charge.stay!=doc.hs_stay) or charge.folio!=doc.get("hs_folio") or folio.customer!=doc.customer:
                    frappe.throw(frappe._("La línea de factura no corresponde a esta cuenta"))
                if doc.update_stock:
                    frappe.throw(frappe._("El inventario de cargos de estancia se descuenta al entregar; no active actualizar stock"))
                from hospitality_suite.pricing import decimal,money
                sources=frappe.parse_json(row.get("hs_charge_sources") or "[]") or [charge.name]
                if not isinstance(sources,list) or charge.name not in sources or len(sources)!=len(set(sources)):
                    frappe.throw(frappe._("Referencias de cargos inválidas"))
                linked=[document("HS Charge",name) for name in sources]
                if charge.applies_to_charge or any(c.folio!=charge.folio or c.currency!=doc.currency or c.item!=charge.item or (c.name!=charge.name and c.applies_to_charge!=charge.name) for c in linked):
                    frappe.throw(frappe._("Los ajustes no pertenecen al cargo de esta línea"))
                if any(c.status not in ("Pending","Invoiced","Scheduled") for c in linked):
                    frappe.throw(frappe._("No puede facturar un cargo revertido"))
                if any(c.status=="Invoiced" and c.sales_invoice!=doc.name for c in linked):
                    frappe.throw(frappe._("Un cargo de esta línea ya está facturado en otro documento"))
                from hospitality_suite.service import current_all
                adjustments=set(current_all("HS Charge",filters={"applies_to_charge":charge.name,"status":["!=","Reversed"]},pluck="name"))
                if set(sources)!={charge.name}|adjustments or used_sources.intersection(sources):
                    frappe.throw(frappe._("Incluya el cargo y todos sus ajustes una sola vez en la misma línea"))
                used_sources.update(sources)
                total=sum(decimal(c.amount) for c in linked)
                if total!=money(total,currency=doc.currency):
                    frappe.throw(frappe._("La precisión monetaria cambió respecto al cargo aceptado; revise la configuración antes de facturar"))
                expected_rate=total/decimal(charge.quantity)
                if decimal(row.qty)!=decimal(charge.quantity) or money(row.rate,currency=doc.currency)!=money(expected_rate,currency=doc.currency):
                    frappe.throw(frappe._("La cantidad y tarifa deben coincidir con el cargo; use un ajuste autorizado"))
            elif doc.get("hs_stay") and not doc.is_return:
                pending=frappe.get_all("HS Charge",filters={"stay":doc.hs_stay,"item":row.item_code,"status":["in",["Pending","Scheduled"]]},pluck="name")
                if pending:
                    frappe.throw(frappe._("Existen cargos pendientes de este artículo. Seleccione su cargo de origen para evitar facturarlo dos veces"))


def guard_cancel(doc,method=None):
    prop_name=(doc.get("hs_property") or
               (frappe.db.get_value("HS Stay", doc.hs_stay, "property") if doc.get("hs_stay") else None) or
               (frappe.db.get_value("HS Booking", doc.hs_booking, "property") if doc.get("hs_booking") else None))
    if prop_name:
        from hospitality_suite.standalone_accounting import provider
        if provider() == "pms" and not getattr(frappe.local, "hs_cutover_opening", False):
            frappe.throw(frappe._("Este establecimiento sigue usando el libro PMS; no cancele documentos ERPNext de alojamiento"))
        require(prop_name,"approve")
        reversal_service = getattr(frappe.local,
            "hs_erp_historical_direct_reversal", None)
        if (doc.doctype == "Sales Invoice" and (linked := frappe.db.exists(
                "HS Service Request", {"credit_note": doc.name,
                    "status": "Returned", "erp_return_refund": ["is", "set"]})) and
                linked != reversal_service):
            frappe.throw(frappe._(
                "La nota histórica de la venta PMS está vinculada a su devolución"))
        if (doc.doctype == "Stock Entry" and (linked := frappe.db.exists(
                "HS Service Request", {"return_stock_entry": doc.name,
                    "status": "Returned", "erp_return_refund": ["is", "set"]})) and
                linked != reversal_service):
            frappe.throw(frappe._(
                "El reingreso histórico de la venta PMS está vinculado a su devolución"))
        if (doc.doctype == "Payment Entry" and (linked := frappe.db.sql(
                "SELECT s.name FROM `tabHS Service Request` s "
                "JOIN `tabHS Payment` payment ON payment.name=s.erp_return_refund "
                "WHERE s.status='Returned' AND payment.payment_entry=%s LIMIT 1",
                (doc.name,))) and linked[0][0] != reversal_service):
            frappe.throw(frappe._(
                "El reembolso histórico de la venta PMS está vinculado a su devolución"))
        if doc.doctype=="Sales Invoice":
            day_reversal = getattr(frappe.local,
                "hs_erp_historical_day_pass_reversal", None)
            if frappe.db.exists("HS Day Pass", {
                    "erp_opening_invoice": doc.name}):
                frappe.throw(frappe._(
                    "La factura de apertura de este Day Pass conserva el saldo trasladado"))
            if (linked := frappe.db.exists("HS Day Pass", {
                    "erp_return_credit_note": doc.name})) and linked != day_reversal:
                frappe.throw(frappe._(
                    "La nota histórica del Day Pass está vinculada a su devolución; use una corrección integral"))
            bookings=frappe.get_all("HS Charge",filters={"sales_invoice":doc.name,"kind":"Lodging"},pluck="stay")
            for stay_name in set(bookings):
                booking_name=frappe.db.get_value("HS Stay",stay_name,"booking") if stay_name else None
                if booking_name and frappe.db.get_value("HS Booking",booking_name,"agent_commission_invoice"):
                    frappe.throw(frappe._("Revierta primero la factura de comisión de la agencia"))
            if doc.is_return and frappe.db.sql(
                    "SELECT pe.name FROM `tabPayment Entry Reference` r "
                    "JOIN `tabPayment Entry` pe ON pe.name=r.parent "
                    "WHERE pe.docstatus=1 AND r.reference_doctype='Sales Invoice' "
                    "AND r.reference_name=%s AND r.allocated_amount!=0 LIMIT 1",
                    (doc.name,), as_list=True):
                frappe.throw(frappe._(
                    "Revierta primero el reembolso vinculado a esta nota de crédito"))
        if (doc.doctype == "Payment Entry" and (linked := frappe.db.sql(
                "SELECT pass.name FROM `tabHS Day Pass` pass "
                "JOIN `tabHS Payment` payment ON payment.name=pass.erp_return_refund "
                "WHERE payment.payment_entry=%s LIMIT 1", (doc.name,))) and
                linked[0][0] != getattr(frappe.local,
                    "hs_erp_historical_day_pass_reversal", None)):
            frappe.throw(frappe._(
                "El reembolso histórico del Day Pass está vinculado a su devolución"))
        if not doc.get("hs_correction_reason"):
            frappe.throw(frappe._("Indique el motivo de corrección antes de cancelar un documento de alojamiento"))
        if doc.doctype=='Sales Invoice' and doc.is_return and doc.return_against and frappe.db.get_value('Sales Invoice',doc.return_against,'is_pos'):
            if frappe.db.exists('Journal Entry Account',{'reference_type':'Sales Invoice','reference_name':doc.name,'docstatus':1}):
                frappe.throw(frappe._('Revierta primero el asiento de devolución vinculado a esta nota POS'))
        field={"Payment Entry":"payment_entry","Journal Entry":"journal_entry"}.get(doc.doctype)
        if field:
            originals=frappe.get_all("HS Payment",filters={field:doc.name,"status":"Posted"},pluck="name")
            if originals and frappe.db.exists("HS Payment",{"source_payment":["in",originals],"status":"Posted"}):
                frappe.throw(frappe._("Revierta primero las aplicaciones, devoluciones o liquidaciones dependientes de este movimiento"))
        if doc.doctype == "Journal Entry":
            from hospitality_suite.pricing import decimal
            from hospitality_suite.financial_movements import balance
            for movement in frappe.get_all("HS Treasury Movement", filters={"journal_entry": doc.name, "status": "Posted"}, fields=["name", "kind", "rendition"]):
                row = frappe.get_doc("HS Treasury Movement", movement.name)
                if str(row.business_date) != str(frappe.db.get_value("HS Property", prop_name, "business_date")):
                    frappe.throw(frappe._("No revierta movimientos financieros de una fecha operativa cerrada"))
                if row.shift and frappe.db.get_value("HS Shift", row.shift, "status") != "Open":
                    frappe.throw(frappe._("No revierta movimientos de un turno cerrado"))
                if movement.kind in ("Initial Fund", "Replenishment") and balance(frappe.get_doc("HS Property", prop_name)) < decimal(row.amount):
                    frappe.throw(frappe._("La reversión dejaría Caja Chica con saldo negativo"))
                if row.shift and movement.kind in ("Other Income", "Loan Received", "Capital Contribution"):
                    from hospitality_suite.cashier import expected
                    shift = frappe.get_doc("HS Shift", row.shift)
                    if decimal(expected(shift).get(row.currency, 0)) < decimal(row.amount):
                        frappe.throw(frappe._("La reversión dejaría el turno sin efectivo suficiente"))
                if movement.kind in ("Loan Received", "Capital Contribution") and frappe.db.exists("HS Treasury Movement", {"source_movement": movement.name, "status": ["!=", "Cancelled"]}):
                    frappe.throw(frappe._("Revierta primero las devoluciones vinculadas a esta entrada"))
                if movement.kind == "Initial Fund" and (
                        frappe.db.exists("HS Petty Cash Expense", {
                            "property": prop_name, "status": "Posted"}) or
                        frappe.db.exists("HS Treasury Movement", {
                            "property": prop_name, "kind": "Replenishment",
                            "status": "Posted"})):
                    frappe.throw(frappe._("Revierta primero los gastos y reposiciones del fondo inicial"))
            expense = frappe.db.get_value("HS Petty Cash Expense", {"journal_entry": doc.name, "status": "Posted"}, ["name", "rendition", "business_date"], as_dict=True)
            if expense and str(expense.business_date) != str(frappe.db.get_value("HS Property", prop_name, "business_date")):
                frappe.throw(frappe._("No revierta gastos de Caja Chica de una fecha operativa cerrada"))
            if expense and expense.rendition and frappe.db.get_value("HS Petty Cash Rendition", expense.rendition, "status") not in ("Returned",):
                frappe.throw(frappe._("Devuelva la rendición antes de revertir este gasto"))
            variance = frappe.db.get_value("HS Petty Cash Rendition", {"variance_journal": doc.name}, ["name", "variance", "status", "approved_business_date"], as_dict=True)
            if variance:
                if str(variance.approved_business_date) != str(frappe.db.get_value("HS Property", prop_name, "business_date")):
                    frappe.throw(frappe._("No revierta diferencias de una fecha operativa cerrada"))
                if decimal(variance.variance) > 0 and balance(frappe.get_doc("HS Property", prop_name)) < decimal(variance.variance):
                    frappe.throw(frappe._("La reversión del sobrante dejaría Caja Chica negativa"))
            if frappe.db.exists("HS Petty Cash Rendition", {"variance_journal": doc.name, "status": ["in", ["Partially Reimbursed", "Reimbursed"]]}):
                frappe.throw(frappe._("Revierta primero las reposiciones antes de cancelar el ajuste"))


def reference_reconciliation(doc,original):
    """Applying a historical advance may update references on a closed shift, but
    cannot change cash, party, accounts, currency or the original posting amount.
    """
    if not original or original.docstatus!=1 or doc.docstatus!=1:
        return False
    if doc.doctype=="Payment Entry":
        fields=("company","party","party_type","payment_type","paid_from","paid_to","paid_amount","received_amount","source_exchange_rate","target_exchange_rate")
        return all(original.get(k)==doc.get(k) for k in fields)
    if doc.doctype=="Journal Entry":
        from decimal import Decimal
        def aggregate(rows):
            result={}
            for row in rows:
                key=(row.account,row.party_type,row.party,row.account_currency,row.exchange_rate)
                debit,credit=result.get(key,(Decimal(0),Decimal(0)))
                result[key]=(debit+Decimal(str(row.debit_in_account_currency or 0)),credit+Decimal(str(row.credit_in_account_currency or 0)))
            return result
        return original.company==doc.company and aggregate(original.accounts)==aggregate(doc.accounts)
    return False


def query_gl_entry(user=None):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return ""
    if not set(frappe.get_roles(user)).intersection(ACTIONS["finance"]+ACTIONS["report"]+ACTIONS["stay"]):
        return "1=0"
    props=allowed_properties(user)
    names=",".join(frappe.db.escape(p) for p in props) or "NULL"
    parts=[f"(`tabGL Entry`.voucher_type={frappe.db.escape(dt)} AND EXISTS (SELECT name FROM `tab{dt}` h WHERE h.name=`tabGL Entry`.voucher_no AND h.hs_property IN ({names})))" for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)]
    return "("+" OR ".join(parts)+")" if parts else "1=0"


def gl_permission(doc,user=None,**kwargs):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return True
    if not set(frappe.get_roles(user)).intersection(ACTIONS["finance"]+ACTIONS["report"]+ACTIONS["stay"]):
        return False
    if doc.voucher_type not in STANDARD_SCOPED:
        return False
    prop=frappe.db.get_value(doc.voucher_type,doc.voucher_no,"hs_property")
    return prop in allowed_properties(user)


def guard_report(report_name,filters):
    if is_system() or not set(frappe.get_roles()).intersection(ROLES):
        return
    filters=frappe.parse_json(filters) if isinstance(filters,str) else filters or {}
    if report_name!="General Ledger" or not filters.get("voucher_no"):
        frappe.throw(frappe._("Use los reportes de Gerencia o abra el mayor de un documento autorizado"),frappe.PermissionError)
    matches=[]
    for dt in STANDARD_SCOPED:
        if not frappe.db.exists("DocType",dt):
            continue
        row=frappe.db.get_value(dt,filters["voucher_no"],["hs_property","company"],as_dict=True)
        if row and row.hs_property in allowed_properties() and row.company==filters.get("company"):
            matches.append(row)
    if len(matches)!=1:
        frappe.throw(frappe._("El documento del mayor no pertenece a un establecimiento autorizado"),frappe.PermissionError)


@frappe.whitelist()
def run_scoped_report(report_name,filters=None,user=None,**kwargs):
    guard_report(report_name,filters)
    from frappe.desk.query_report import run
    return run(report_name=report_name,filters=filters,**kwargs)


@frappe.whitelist()
def export_scoped_report():
    guard_report(frappe.form_dict.get("report_name"),frappe.form_dict.get("filters"))
    from frappe.desk.query_report import export_query
    return export_query()


def master_permission(doc,user=None,**kwargs):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return True
    companies=frappe.get_all("HS Property",filters={"name":["in",allowed_properties(user)]},pluck="company")
    if doc.doctype=="Warehouse":
        return doc.name in inventory_warehouses(user)
    return (doc.name if doc.doctype=="Company" else doc.company) in companies


def master_query(dt,user=None):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return ""
    companies=frappe.get_all("HS Property",filters={"name":["in",allowed_properties(user)]},pluck="company")
    if dt=="Warehouse":
        values=",".join(frappe.db.escape(w) for w in inventory_warehouses(user)) or "NULL"
        return f"`tabWarehouse`.`name` IN ({values})"
    values=",".join(frappe.db.escape(c) for c in set(companies)) or "NULL"
    field="name" if dt=="Company" else "company"
    return f"`tab{dt}`.`{field}` IN ({values})"


for _master in ("Account","Company","Cost Center","Warehouse","Sales Taxes and Charges Template"):
    globals()["query_master_"+_master.lower().replace(" ","_")]=lambda user=None,dt=_master:master_query(dt,user)


def inventory_warehouses(user=None):
    props=allowed_properties(user)
    configured=frappe.get_all("HS Property",filters={"name":["in",props]},
        fields=["name","warehouse","laundry_warehouse","company"])
    names={p.get(field) for p in configured for field in ("warehouse","laundry_warehouse") if p.get(field)}
    names.update(frappe.get_all("Warehouse",filters={"hs_property":["in",props]},pluck="name"))
    return [w for w in sorted(names) if any(warehouse_allowed(p,w) for p in configured)]


def stock_permission(doc,user=None,**kwargs):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return True
    return doc.warehouse in inventory_warehouses(user)


def stock_query(dt,user=None):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return ""
    values=",".join(frappe.db.escape(w) for w in inventory_warehouses(user)) or "NULL"
    return f"`tab{dt}`.`warehouse` IN ({values})"


def query_bin(user=None):
    return stock_query("Bin",user)


def query_stock_ledger_entry(user=None):
    return stock_query("Stock Ledger Entry",user)


def party_names(dt,user=None):
    props=allowed_properties(user)
    if dt=="Supplier":
        return set(frappe.get_all("HS Supplier",filters={"property":["in",props]},pluck="supplier"))
    if dt=="Customer":
        return set(frappe.get_all("HS Guest",filters={"property":["in",props],"customer":["is","set"]},pluck="customer"))|set(frappe.get_all("HS Billing Party",filters={"property":["in",props]},pluck="customer"))
    names=set()
    for linked in ("Customer","Supplier"):
        allowed=party_names(linked,user)
        names.update(frappe.get_all("Dynamic Link",filters={"parenttype":dt,"link_doctype":linked,"link_name":["in",list(allowed)]},pluck="parent"))
    if dt in ('Contact','Address'):
        field='contact' if dt=='Contact' else 'address'
        guests=frappe.get_all('HS Guest',filters={'property':['in',props],'customer':['is','not set'],field:['is','set']},fields=['name',field])
        expected={(row[field],row.name) for row in guests}
        if expected:
            links=frappe.get_all('Dynamic Link',filters={'parenttype':dt,'parentfield':'links','parent':['in',[p for p,_ in expected]]},fields=['parent','link_doctype','link_name'])
            foreign={row.parent for row in links if row.link_doctype in ('Customer','Supplier')}
            names.update(row.parent for row in links if row.link_doctype=='HS Guest' and (row.parent,row.link_name) in expected and row.parent not in foreign)
    return names


def party_permission(doc,user=None,**kwargs):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return True
    if not set(frappe.get_roles(user)).intersection(set(ACTIONS["guest"]+ACTIONS["finance"]+ACTIONS["report"]+ACTIONS["inventory"])):
        return False
    return doc.name in party_names(doc.doctype,user)


def party_query(dt,user=None):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return ""
    if not set(frappe.get_roles(user)).intersection(set(ACTIONS["guest"]+ACTIONS["finance"]+ACTIONS["report"]+ACTIONS["inventory"])):
        return "1=0"
    values=",".join(frappe.db.escape(n) for n in sorted(party_names(dt,user))) or "NULL"
    return f"`tab{dt}`.`name` IN ({values})"


for _party in ("Customer","Supplier","Contact","Address"):
    globals()["query_party_"+_party.lower()]=lambda user=None,dt=_party:party_query(dt,user)


@frappe.whitelist()
def scoped_account_balance(*args,**kwargs):
    if not is_system() and set(frappe.get_roles()).intersection(ROLES):
        frappe.throw(frappe._("Use los saldos y reportes del establecimiento; el saldo agregado de una cuenta puede incluir otros establecimientos"),frappe.PermissionError)
    from erpnext.accounts.utils import get_balance_on
    return get_balance_on(*args,**kwargs)


@frappe.whitelist()
def scoped_stock_balance(item_code,warehouse=None,**kwargs):
    if not is_system() and set(frappe.get_roles()).intersection(ROLES):
        if not warehouse or warehouse not in inventory_warehouses():
            frappe.throw(frappe._("Seleccione un almacén de su establecimiento"),frappe.PermissionError)
    from erpnext.stock.utils import get_stock_balance
    return get_stock_balance(item_code,warehouse,**kwargs)
