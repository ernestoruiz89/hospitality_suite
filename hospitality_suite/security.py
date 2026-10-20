"""Authorization is enforced before every query/mutation, including direct REST access."""
import frappe
from frappe import _

from hospitality_suite.schema import SCOPED, MANAGERS,ROLES,STANDARD_SCOPED

ACTIONS = {
    "setup": MANAGERS, "reserve": MANAGERS + ["HS Receptionist"],
    "stay": MANAGERS + ["HS Receptionist"],
    "finance": MANAGERS + ["HS Cashier", "HS Accountant"],
    "clean": MANAGERS + ["HS Housekeeping"], "inspect": MANAGERS,
    "maintain": MANAGERS + ["HS Maintenance"],
    "service": MANAGERS + ["HS Receptionist", "HS Cashier"],
    "report": MANAGERS + ["HS Accountant", "HS Auditor"], "approve": MANAGERS[:2],
    "cash_approve": MANAGERS,
    "guest": MANAGERS + ["HS Receptionist"],
    "incident": MANAGERS + ["HS Housekeeping","HS Maintenance"],
    "inventory":MANAGERS+["HS Accountant"],
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
    return [r.property for r in rows if frappe.db.get_value("HS Property", r.property, "company") == r.company]


def require(property_name, action=None):
    if frappe.session.user == "Guest" or property_name not in allowed_properties():
        frappe.throw(_("No tiene acceso a este establecimiento"), frappe.PermissionError)
    if action and not is_system() and not set(ACTIONS[action]).intersection(frappe.get_roles()):
        frappe.throw(_("No tiene permiso para esta operación"), frappe.PermissionError)
    return frappe.get_doc("HS Property", property_name)


def document(dt, name, action=None):
    doc = frappe.get_doc(dt, name, for_update=bool(getattr(frappe.local, "hs_operation", False)))
    require(doc.name if dt == "HS Property" else doc.property, action)
    doc.check_permission("read")
    return doc


def has_scope_permission(doc, user=None, permission_type=None, **kwargs):
    prop = doc.name if doc.doctype == "HS Property" else doc.get("property")
    if not prop or prop not in allowed_properties(user):
        return False
    return True  # Controller hooks can restrict; native role permissions still apply.


def scope_query(dt, user=None):
    props = allowed_properties(user)
    if not props:
        return "1=0"
    field = "name" if dt == "HS Property" else "property"
    names = ",".join(frappe.db.escape(v) for v in props)
    return f"`tab{dt}`.`{field}` IN ({names})"


for _dt in SCOPED:
    globals()["query_" + _dt.lower().replace(" ", "_")] = lambda user=None, dt=_dt: scope_query(dt, user)


def validate_file(doc, method=None):
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
    props=",".join(frappe.db.escape(p) for p in allowed_properties(user)) or "NULL"
    targets=",".join(frappe.db.escape(dt) for dt in SCOPED)
    branches=[]
    for dt in SCOPED:
        if not roles.intersection(SCHEMA[dt].get("roles",[])):
            continue
        actions={"HS Guest":["guest","finance","report"],"HS Maintenance Order":["maintain","inspect","report"],"HS Incident":["incident","inspect","report"]}.get(dt)
        if actions and not any(roles.intersection(ACTIONS[a]) for a in actions):
            continue
        field="name" if dt=="HS Property" else "property"
        branches.append(f"(`tabFile`.attached_to_doctype={frappe.db.escape(dt)} AND EXISTS(SELECT name FROM `tab{dt}` WHERE name=`tabFile`.attached_to_name AND `{field}` IN ({props})))")
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
        if prop_name and prop_name!=booking.property:
            frappe.throw(frappe._("La reserva y el establecimiento no coinciden"))
        prop_name=booking.property
        party=doc.get("customer") or doc.get("party")
        payers=[booking.customer]+frappe.get_all("HS Folio",filters={"booking":booking.name},pluck="customer")
        if party and party not in payers:
            frappe.throw(frappe._("El pagador no coincide con la reserva o sus cuentas"))
    prop = require(prop_name)
    if doc.company != prop.company:
        frappe.throw(frappe._("El documento contable pertenece a otra compañía"))
    if doc.doctype in ("Purchase Order","Purchase Receipt","Purchase Invoice") and doc.get("supplier"):
        if not frappe.db.exists("HS Supplier",{"property":prop.name,"supplier":doc.supplier,"active":1}):
            frappe.throw(frappe._("El proveedor no está habilitado en este establecimiento"))
    if not is_system():
        owned=set(frappe.get_all("Warehouse",filters={"hs_property":prop.name},pluck="name"))|{prop.warehouse,prop.laundry_warehouse}
        for row in [doc]+list(doc.get("items") or []):
            for field in ("warehouse","s_warehouse","t_warehouse","set_warehouse","set_from_warehouse"):
                if row.get(field) and row.get(field) not in owned:
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
    prop_name=doc.get("hs_property") or (frappe.db.get_value("HS Stay",doc.hs_stay,"property") if doc.get("hs_stay") else None)
    if prop_name:
        require(prop_name,"approve")
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
    configured=frappe.get_all("HS Property",filters={"name":["in",props]},fields=["warehouse","laundry_warehouse","company"])
    companies={p.company for p in configured}
    names={p.get(field) for p in configured for field in ("warehouse","laundry_warehouse") if p.get(field)}
    names.update(frappe.get_all("Warehouse",filters={"hs_property":["in",props]},pluck="name"))
    return [w for w in sorted(names) if frappe.db.get_value("Warehouse",w,"company") in companies]


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
