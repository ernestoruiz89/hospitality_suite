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
    "guest": MANAGERS + ["HS Receptionist"],
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


def realtime(property_name):
    users = frappe.get_all("HS Access", filters={"property": property_name}, pluck="user")
    users.append("Administrator")
    for user in set(users):
        # Events contain no document names, guests, financial values or room details.
        frappe.publish_realtime("hospitality_changed", {"property": property_name}, user=user, after_commit=True)


def standard_permission(doc, user=None, permission_type=None, **kwargs):
    permission_type=permission_type or kwargs.get("ptype")
    roles=set(frappe.get_roles(user))
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
        frappe.throw("No puede quitar el origen de un documento vinculado a alojamiento")
    if not doc.get("hs_property") and not doc.get("hs_stay") and not doc.get("hs_booking") and not is_system() and set(frappe.get_roles()).intersection(ROLES):
        properties=frappe.get_all("HS Property",filters={"name":["in",allowed_properties()],"company":doc.company},pluck="name")
        if len(properties)==1:
            doc.hs_property=properties[0]
        else:
            frappe.throw("Seleccione un establecimiento autorizado para este documento")
    if not doc.get("hs_stay") and not doc.get("hs_property") and not doc.get("hs_booking"):
        return
    prop_name = doc.get("hs_property")
    if doc.get("hs_stay"):
        stay = frappe.get_doc("HS Stay", doc.hs_stay)
        if prop_name and prop_name != stay.property:
            frappe.throw("La estancia y el establecimiento no coinciden")
        prop_name = stay.property
    if doc.get("hs_booking"):
        booking=document("HS Booking",doc.hs_booking)
        if prop_name and prop_name!=booking.property:
            frappe.throw("La reserva y el establecimiento no coinciden")
        prop_name=booking.property
        party=doc.get("customer") or doc.get("party")
        payers=[booking.customer]+frappe.get_all("HS Folio",filters={"booking":booking.name},pluck="customer")
        if party and party not in payers:
            frappe.throw("El pagador no coincide con la reserva o sus cuentas")
    prop = require(prop_name)
    if doc.company != prop.company:
        frappe.throw("El documento contable pertenece a otra compañía")
    if not is_system():
        owned=set(frappe.get_all("Warehouse",filters={"hs_property":prop.name},pluck="name"))|{prop.warehouse,prop.laundry_warehouse}
        for row in [doc]+list(doc.get("items") or []):
            for field in ("warehouse","s_warehouse","t_warehouse","set_warehouse","set_from_warehouse"):
                if row.get(field) and row.get(field) not in owned:
                    frappe.throw("El almacén no está asignado a este establecimiento",frappe.PermissionError)
    doc.hs_property = prop.name
    old=doc.get_doc_before_save()
    if old and old.get("hs_property") and (old.hs_property!=doc.hs_property or old.get("hs_stay")!=doc.get("hs_stay")):
        frappe.throw("No puede quitar ni cambiar el origen de un documento vinculado a alojamiento")
    if not getattr(frappe.local, "hs_operation", False):
        require(prop_name, "finance")
    if doc.get("hs_folio"):
        folio = document("HS Folio", doc.hs_folio)
        if not doc.get("hs_booking") and folio.booking:
            doc.hs_booking=folio.booking
        belongs=folio.stay==doc.get("hs_stay") if folio.stay else (folio.booking==doc.get("hs_booking") or (doc.get("hs_stay") and folio.booking==frappe.db.get_value("HS Stay",doc.hs_stay,"booking")))
        if folio.property != prop.name or not belongs:
            frappe.throw("Cuenta y estancia incompatibles")
        party = doc.get("customer") or doc.get("party")
        if party and party != folio.customer:
            frappe.throw("El cliente del documento no es el pagador de la cuenta")
    if doc.get("hs_shift"):
        shift = document("HS Shift", doc.hs_shift)
        reconciles=reference_reconciliation(doc,original)
        if shift.property != prop.name or (shift.status != "Open" and not reconciles):
            frappe.throw("No puede registrar movimientos en un turno cerrado")
    if doc.doctype == "Sales Invoice":
        if doc.discount_amount or doc.additional_discount_percentage:
            frappe.throw("Registre los descuentos y cortesías mediante un ajuste autorizado de la cuenta")
        for row in doc.items:
            if row.get("hs_charge"):
                charge = document("HS Charge", row.hs_charge)
                folio=document("HS Folio",charge.folio)
                if charge.property!=prop.name or (doc.get("hs_stay") and charge.stay!=doc.hs_stay) or charge.folio!=doc.get("hs_folio") or folio.customer!=doc.customer:
                    frappe.throw("La línea de factura no corresponde a esta cuenta")
                if doc.update_stock:
                    frappe.throw("El inventario de cargos de estancia se descuenta al entregar; no active actualizar stock")
                from hospitality_suite.pricing import decimal,money
                sources=frappe.parse_json(row.get("hs_charge_sources") or "[]") or [charge.name]
                if not isinstance(sources,list) or charge.name not in sources or len(sources)!=len(set(sources)):
                    frappe.throw("Referencias de cargos inválidas")
                linked=[document("HS Charge",name) for name in sources]
                if any(c.folio!=charge.folio or c.item!=charge.item or (c.name!=charge.name and c.applies_to_charge!=charge.name) for c in linked):
                    frappe.throw("Los ajustes no pertenecen al cargo de esta línea")
                if any(c.status=="Invoiced" and c.sales_invoice!=doc.name for c in linked):
                    frappe.throw("Un cargo de esta línea ya está facturado en otro documento")
                total=sum(decimal(c.amount) for c in linked)
                expected_rate=total/decimal(charge.quantity)
                if decimal(row.qty)!=decimal(charge.quantity) or money(row.rate)!=money(expected_rate):
                    frappe.throw("La cantidad y tarifa deben coincidir con el cargo; use un ajuste autorizado")
            elif doc.get("hs_stay") and not doc.is_return:
                pending=frappe.get_all("HS Charge",filters={"stay":doc.hs_stay,"item":row.item_code,"status":"Pending"},pluck="name")
                if pending:
                    frappe.throw("Existen cargos pendientes de este artículo. Seleccione su cargo de origen para evitar facturarlo dos veces")


def guard_cancel(doc,method=None):
    prop_name=doc.get("hs_property") or (frappe.db.get_value("HS Stay",doc.hs_stay,"property") if doc.get("hs_stay") else None)
    if prop_name:
        require(prop_name,"approve")
        if not doc.get("hs_correction_reason"):
            frappe.throw("Indique el motivo de corrección antes de cancelar un documento de alojamiento")


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
    props=allowed_properties(user)
    names=",".join(frappe.db.escape(p) for p in props) or "NULL"
    parts=[f"(`tabGL Entry`.voucher_type={frappe.db.escape(dt)} AND EXISTS (SELECT name FROM `tab{dt}` h WHERE h.name=`tabGL Entry`.voucher_no AND h.hs_property IN ({names})))" for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)]
    return "("+" OR ".join(parts)+")" if parts else "1=0"


def gl_permission(doc,user=None,**kwargs):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return True
    if doc.voucher_type not in STANDARD_SCOPED:
        return False
    prop=frappe.db.get_value(doc.voucher_type,doc.voucher_no,"hs_property")
    return prop in allowed_properties(user)


def guard_report(report_name,filters):
    if is_system() or not set(frappe.get_roles()).intersection(ROLES):
        return
    filters=frappe.parse_json(filters) if isinstance(filters,str) else filters or {}
    if report_name!="General Ledger" or not filters.get("voucher_no"):
        frappe.throw("Use los reportes de Gerencia o abra el mayor de un documento autorizado",frappe.PermissionError)
    matches=[]
    for dt in STANDARD_SCOPED:
        if not frappe.db.exists("DocType",dt):
            continue
        row=frappe.db.get_value(dt,filters["voucher_no"],["hs_property","company"],as_dict=True)
        if row and row.hs_property in allowed_properties() and row.company==filters.get("company"):
            matches.append(row)
    if len(matches)!=1:
        frappe.throw("El documento del mayor no pertenece a un establecimiento autorizado",frappe.PermissionError)


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
    return (doc.name if doc.doctype=="Company" else doc.company) in companies


def master_query(dt,user=None):
    if is_system(user) or not set(frappe.get_roles(user)).intersection(ROLES):
        return ""
    companies=frappe.get_all("HS Property",filters={"name":["in",allowed_properties(user)]},pluck="company")
    values=",".join(frappe.db.escape(c) for c in set(companies)) or "NULL"
    field="name" if dt=="Company" else "company"
    return f"`tab{dt}`.`{field}` IN ({values})"


for _master in ("Account","Company","Cost Center","Warehouse","Sales Taxes and Charges Template"):
    globals()["query_master_"+_master.lower().replace(" ","_")]=lambda user=None,dt=_master:master_query(dt,user)
