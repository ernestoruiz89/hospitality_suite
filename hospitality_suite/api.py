"""Authenticated API for Desk Pages. Every mutation is POST + scoped + idempotent."""
import json

import frappe
from frappe.utils import now_datetime

from hospitality_suite import operations, cashier, housekeeping, inventory, accounting, closing, linen, portal,timing,direct_sales,treasury,procurement,privacy
from hospitality_suite.security import allowed_properties, require, document, ACTIONS, is_system
from hospitality_suite.service import command, insert, audit, canonical
from hospitality_suite.time import to_site, now_local
from hospitality_suite.schema import PAGES
from hospitality_suite import setup
from hospitality_suite import service_accounting
from hospitality_suite import periodic
from hospitality_suite import booking_drafts

COMMANDS = {
    'save_booking_draft':('reserve',booking_drafts.save),
    'confirm_booking_draft':('reserve',booking_drafts.confirm),
    'discard_booking_draft':('reserve',booking_drafts.discard),
    "generate_lodging":("finance",periodic.generate_command),
    "service_accounting":("setup",service_accounting.save),
    "reserve": ("reserve", operations.reserve), "booking_status": ("reserve", operations.update_booking),
    "check_in": ("stay", operations.check_in), "walk_in": ("stay", operations.walk_in),
    "extend": ("stay", operations.extend), "change_room": ("stay", operations.change_room),
    "check_out": ("stay", operations.check_out), "create_folio": ("stay", operations.create_folio),
    "move_charge": ("stay", operations.move_charge), "invoice": ("finance", accounting.invoice_folio),
    "payment": ("finance", accounting.payment), "open_shift": ("finance", cashier.open_shift),
    "close_shift": ("finance", cashier.close_shift), "cleaning": ("clean", housekeeping.update_cleaning),
    "maintenance": ("maintain", housekeeping.maintenance), "request_service": ("service", inventory.request_service),
    "maintenance_parts":("maintain",housekeeping.maintenance_parts),
    "update_service": ("service", inventory.update_service), "daily_close": ("report", closing.daily_close),
    "reopen_day": ("approve", closing.reopen),
    "credit_note": ("approve", accounting.credit_note),
    "apply_guarantee": ("approve", accounting.apply_guarantee),
    "incident": ("incident", linen.incident), "linen": ("clean", linen.move_linen),
    "convert_portal": ("reserve", portal.convert), "portal_link": ("reserve", portal.link),
    "withdrawal": ("finance",cashier.withdrawal),
    "modify_reservation": ("reserve",operations.modify_reservation),
    "prepare_departure":("stay",timing.prepare_departure),"inspect_departure":("inspect",timing.inspect_departure),
    "adjustment":("approve",operations.adjustment),
    "schedule_cleaning":("inspect",housekeeping.schedule_cleaning),
    "direct_sale":("finance",direct_sales.sell),"return_direct_sale":("approve",direct_sales.return_sale),
    "assign_user":("setup",setup.assign_user),"companions":("guest",operations.companions),
    "cash_expense":("finance",treasury.expense),"settle_payment":("finance",treasury.settle),
    "purchase_order":("inventory",procurement.purchase_order),"receive_purchase":("inventory",procurement.receive_purchase),
    "purchase_invoice":("inventory",procurement.purchase_invoice),"supplier_payment":("finance",procurement.supplier_payment),
    "move_stock":("inventory",procurement.move_stock),"adjust_stock":("approve",procurement.adjust_stock),
    "register_supplier":("inventory",procurement.register_supplier),
    "create_warehouse":("inventory",procurement.create_warehouse),"stock_policy":("setup",procurement.stock_policy),
    "retire_sensitive":("approve",privacy.retire),"retry_retention":("approve",privacy.retry),
}


def payload(value):
    if isinstance(value, str):
        if len(value) > 100000:
            frappe.throw(frappe._("Solicitud demasiado grande"))
        value = json.loads(value)
    if not isinstance(value, dict):
        frappe.throw(frappe._("Se requiere un objeto JSON"))
    return value


@frappe.whitelist(methods=["POST"])
def execute(property_name, action, request_key, data=None):
    data = payload(data or {})
    if action not in COMMANDS:
        frappe.throw(frappe._("Acción desconocida"))
    permission, handler = COMMANDS[action]
    body = {**data, "operation": action}
    return command(property_name, permission, request_key, body, lambda prop: handler(prop, data))


@frappe.whitelist()
def preview(property_name, data, action="reserve"):
    if action == 'confirm_booking_draft':
        return booking_drafts.preview(require(property_name,'reserve'),payload(data))
    permission="inventory" if action=="purchase_order" else "approve" if action in ("adjust_stock","retire_sensitive","credit_note") else "finance" if action in ("invoice","payment","direct_sale","settle_payment","supplier_payment") else "reserve" if action in ("reserve","booking_status","modify_reservation","convert_portal") else "stay"
    prop = require(property_name, permission)
    data = payload(data)
    if action=='invoice':
        return accounting.invoice_quote(prop,data)
    if action == "reserve":
        return operations.quote_request(prop, data)
    if action == "extend":
        return operations.extension_quote(prop, data)
    if action=="change_room":
        return operations.room_change_quote(prop,data)
    if action=="modify_reservation":
        doc,values,excluded=operations.modification_values(prop,data)
        return operations.quote_request(prop,values,exclude=excluded)
    if action=="booking_status":
        booking=document("HS Booking",data["booking"],"reserve")
        return accounting.cancellation_fee(prop,booking,data["status"])
    if action=="check_in":
        return operations.arrival_quote(prop,data)
    if action=="departure":
        return timing.departure(prop,data)
    if action=="direct_sale":
        require(prop.name,"finance")
        return direct_sales.quote(prop,data)
    if action=="payment":
        require(prop.name,"finance")
        return accounting.payment_quote(prop,data)
    if action=='credit_note':
        return accounting.credit_note_quote(prop,data)
    if action=="settle_payment":
        return treasury.settlement_quote(prop,data)
    if action=="supplier_payment":
        return procurement.supplier_payment_quote(prop,data)
    if action=="adjust_stock":
        return procurement.adjustment_quote(prop,data)
    if action=="purchase_order":
        return procurement.purchase_order_quote(prop,data)
    if action=="retire_sensitive":
        return privacy.quote(prop,data)
    if action=="convert_portal":
        request_doc,values=portal.conversion_values(prop,data)
        excluded=frappe.get_all("HS Allocation",filters={"portal_request":request_doc.name,"status":"Active"},pluck="name")
        return operations.quote_request(prop,values,exclude=excluded)
    frappe.throw(frappe._("Cotización desconocida"))


@frappe.whitelist()
def service_configuration(property_name,item=None):
    from hospitality_suite.item_configuration import configuration
    return configuration(property_name,item)


@frappe.whitelist()
def service_accounting_configuration(property_name):
    return service_accounting.configuration(property_name)


def may(action):
    return is_system() or bool(set(ACTIONS[action]).intersection(frappe.get_roles()))


@frappe.whitelist()
def stay_board(property_name,date=None,view='hosted',offset=0,page_length=25):
    from hospitality_suite.desk_board import board
    return board(property_name,date,view,offset,page_length)


def project(dt, prop, fields=None, filters=None):
    from hospitality_suite.paging import permitted_all
    return permitted_all(dt, filters={"property": prop.name, **(filters or {})}, fields=fields or ["*"])


@frappe.whitelist()
def bootstrap(property_name=None):
    names = allowed_properties()
    props = frappe.get_all("HS Property", filters={"name": ["in", names]}, fields=["name", "company", "property_name", "brand_name", "mode", "time_zone", "currency", "business_date", "discreet_mode", "inspection_required", "guest_id_required"])
    roles = frappe.get_roles()
    pages = [dict(route=route, title=title) for route, (title, accepted) in PAGES.items() if is_system() or set(roles).intersection(accepted)]
    result = dict(properties=props, pages=pages, actions=[a for a in ACTIONS if may(a)], server_time=str(now_datetime()))
    result["can_create_property"]=is_system()
    result["system_timezone"] = frappe.utils.get_system_timezone()
    if not property_name:
        return result
    prop = require(property_name)
    result["inventory_currency"]=frappe.db.get_value("Company",prop.company,"default_currency")
    result["default_warehouse"]=prop.warehouse
    result["property_now"] = now_local(prop).isoformat()
    result["print_formats"]=dict(invoice=prop.invoice_print_format or "HS Factura",receipt=prop.receipt_print_format or "HS Recibo")
    result["rooms"] = project("HS Room", prop, ["name", "room_number", "category", "floor", "zone", "cleaning_status", "active", "parking"])
    result["categories"] = project("HS Category", prop, ["name", "category_name", "capacity"])
    # Minimal operational projection is intentionally separate from stay documents.
    active = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"}, fields=["name", "room", "starts_at", "ends_at"])
    result["occupied"] = active
    result["blocks"] = frappe.get_all("HS Allocation", filters={"property": prop.name, "kind": "Maintenance", "status": "Active"}, fields=["room", "starts_at", "ends_at"])
    result["rooms"].sort(key=lambda r: r.room_number)
    if may("stay") or may("finance"):
        from hospitality_suite.desk_board import room_arrivals
        result["room_arrivals"]=room_arrivals(prop)
        result["stays"] = project("HS Stay", prop)
        result["bookings"] = project("HS Booking", prop)
        result["guests"] = project("HS Guest", prop, ["name", "full_name", "customer"])
        result["rates"] = project("HS Rate", prop, ["name", "title", "category", "mode", "currency", "amount", "block_hours"])
        result["folios"] = project("HS Folio", prop)
        result["portal_requests"] = project("HS Portal Request",prop,filters={"status":"Hold"})
        result["services"] = project("HS Service Request", prop)
        result["billing_parties"]=project("HS Billing Party",prop)
        customers = set(r.customer for r in result["guests"] + result["folios"] + result["bookings"] + result["billing_parties"] if r.get("customer"))
        result["customers"] = [dict(name=n, customer_name=frappe.db.get_value("Customer", n, "customer_name")) for n in sorted(customers)]
    if may("finance") or may("report"):
        from hospitality_suite.payment_policies import policies
        result["payment_policies"]=policies(prop)
        result["denominations"]=frappe.parse_json(prop.get("cash_denominations") or "{}")
        result["shifts"] = project("HS Shift", prop)
        for shift in result["shifts"]:
            shift["current_expected"]=cashier.expected(shift)
            frozen=frappe.parse_json(shift.denominations or "{}")
            shift["expected_by_currency"] = frozen.get("expected",shift["current_expected"]) if shift.status=="Closed" else shift["current_expected"]
        result["payment_methods"] = project("HS Payment Method", prop)
        result["payments"] = project("HS Payment", prop)
        from hospitality_suite.native_pos import movements
        result["native_pos"]=[{**row,"amount":str(row["amount"])} for row in movements(prop.name)]
        result["expense_categories"]=project("HS Expense Category",prop)
        result["suppliers"]=project("HS Supplier",prop)
        result["purchase_orders"]=frappe.get_list("Purchase Order",filters={"hs_property":prop.name,"docstatus":1,"status":["not in",["Closed","Cancelled","Completed"]]},fields=["name","supplier","currency","grand_total","schedule_date"],limit=500)
        for order in result["purchase_orders"]:
            order["items"]=[dict(name=r.name,item=r.item_code,quantity=r.qty,received_quantity=r.received_qty,rate=r.rate) for r in frappe.get_doc("Purchase Order",order.name).items]
        result["purchase_receipts"]=frappe.get_list("Purchase Receipt",filters={"hs_property":prop.name,"docstatus":1,"per_billed":["<",100],"is_return":0},fields=["name","supplier","currency","grand_total"],limit=500)
        result["purchase_invoices"]=frappe.get_list("Purchase Invoice",filters={"hs_property":prop.name,"docstatus":1,"outstanding_amount":[">",0],"is_return":0},fields=["name","supplier","currency","outstanding_amount","bill_no"],limit=500)
    if any(may(a) for a in ("inventory","clean","maintain","report","service")):
        result["warehouses"]=[dict(name=n,warehouse_name=frappe.db.get_value("Warehouse",n,"warehouse_name")) for n in procurement.warehouses(prop)]
    result["cleaning"] = project("HS Cleaning Task", prop, ["name", "room", "kind", "status", "priority", "assigned_to", "modified", "checklist", "notes","started_at","completed_at","inspected_by"])
    for task in result["cleaning"]:
        task["assigned_label"]=frappe.db.get_value("User",task.assigned_to,"full_name") if task.assigned_to else None
    result["equipment"]=project("HS Equipment",prop,["name","equipment_code","label","room","active","instructions"])
    result["maintenance"] = project("HS Maintenance Order", prop, ["name", "room","equipment","blocks_room","until_reopened", "title", "starts_at", "ends_at", "status", "modified", "notes","assigned_to"])
    if may("setup"):
        result["assets"] = frappe.get_all("Asset",filters={"hs_property":prop.name,"company":prop.company,"docstatus":["!=",2]},fields=["name","asset_name"],limit=500)
    result["incidents"]=project("HS Incident",prop,["name","room","kind","description","status","evidence","resolution","modified"])
    if may("maintain") or may("report"):
        for order in result["maintenance"]:
            doc=frappe.get_doc("HS Maintenance Order",order.name)
            order["cost"]=doc.cost
            order["evidence"]=doc.evidence
            order["parts"]=[r.as_dict() for r in doc.parts]
    if may("report"):
        from hospitality_suite.reports import summary, REPORTS
        from hospitality_suite.close_financials import display_groups
        result["close_financial_groups"]=display_groups()
        from hospitality_suite.report_formatting import LABELS
        from hospitality_suite.printing import VALUE_LABELS
        result["summary"] = summary(prop)
        result["reports"] = list(REPORTS)
        result["report_labels"]={key:frappe._(value) for key,value in LABELS.items()}
        result["report_values"]={key:frappe._(value) for key,value in VALUE_LABELS.items()}
        result["closes"] = project("HS Daily Close", prop)
    if may("approve"):
        result["retention_runs"]=project("HS Retention Run",prop,["name","status","approved_by","approved_at","attempts","last_error","modified"])
        for run in result["retention_runs"]:
            counts=current_all_retention_files(run.name)
            run["file_counts"]={status:sum(r.status==status for r in counts) for status in ("Pending","Deleted","Shared","Failed")}
    if any(may(a) for a in ("clean","service","maintain","inventory")):
        from hospitality_suite.catalog import bootstrap_items
        result["items"]=bootstrap_items(result)
    return result


@frappe.whitelist()
def catalog_search(property_name,txt="",purpose="any"):
    from hospitality_suite.catalog import search
    return search(property_name,txt,purpose)


def current_all_retention_files(name):
    from hospitality_suite.service import current_all
    return current_all("HS Retention File",filters={"parent":name,"parenttype":"HS Retention Run"},fields=["status"])


@frappe.whitelist()
def retention_candidates(property_name):
    return privacy.candidates(require(property_name,"approve"))


@frappe.whitelist()
def stay_detail(name):
    doc = document("HS Stay", name)
    prop = require(doc.property)
    folios = accounting.folios_for_stay(doc)
    for folio in folios:
        folio["balance"] = accounting.folio_balance(folio.name)
    from hospitality_suite.tariff_explanations import describe_charge
    charges=project("HS Charge",prop,filters={"stay":name})
    for row in charges:
        row['pricing']=describe_charge(row)
        from hospitality_suite.display_labels import generated_label
        row['description_label']=generated_label(row.description)
    return dict(stay=doc.as_dict(), folios=folios, charges=charges,
                segments=project("HS Allocation", prop, filters={"stay": name}))


@frappe.whitelist()
def availability_search(property_name, starts_at, ends_at, category, people=1, quantity=1):
    from hospitality_suite.availability_search import search
    return search(property_name, starts_at, ends_at, category, people, quantity)


@frappe.whitelist()
def report(property_name, report_name, filters=None):
    from hospitality_suite.reports import rows
    from hospitality_suite.report_queries import scopes,metadata,validate,reconciliation_scopes
    filters=payload(filters or {})
    selected=scopes(property_name,filters.get("company"))
    meta=metadata(report_name)
    validate(filters,meta)
    if meta["base"]=="Conciliación":
        selected=reconciliation_scopes(selected,filters)
    records=[]
    for prop in selected:
        batch=rows(prop,report_name,filters)
        if not property_name:
            for row in batch:
                row.update(company=prop.company,property=prop.name,time_zone=prop.time_zone)
                row.setdefault("_display",{})["property"]=prop.property_name
        records.extend(batch)
    return records


@frappe.whitelist()
def report_options(property_name,report_name,company=None):
    """Return only applicable filters and options from authorized properties."""
    from hospitality_suite.report_queries import scopes,metadata
    selected=scopes(property_name,company)
    meta=metadata(report_name)
    from hospitality_suite.reports import REPORTS
    base_dt=REPORTS[meta["base"]][0]
    meta["statuses"]=(frappe.get_meta(base_dt).get_field("status").options or "").splitlines() if base_dt and frappe.get_meta(base_dt).has_field("status") else ["OK","Difference"] if meta["base"]=="Conciliación" else []
    meta["kinds"]=(frappe.get_meta(base_dt).get_field("kind").options or "").splitlines() if base_dt and frappe.get_meta(base_dt).has_field("kind") else []
    props=frappe.get_all("HS Property",filters={"name":["in",allowed_properties()]},fields=["name","property_name","company"])
    result=dict(meta,properties=props,companies=sorted({p.company for p in props}),rooms=[],categories=[],shifts=[],stays=[],methods=[],warehouses=[],users=[],channels=[])
    users=set()
    for prop in selected:
        for key,dt,fields in (("rooms","HS Room",["name","room_number","category"]),("categories","HS Category",["name","category_name"]),
                              ("shifts","HS Shift",["name","cashier","opened_at","status"]),("methods","HS Payment Method",["name","mode_of_payment","currency"])):
            if ("method" if key=="methods" else "shift" if key=="shifts" else "category" if key=="categories" else "room") not in meta["filters"]:
                continue
            for row in project(dt,prop,fields):
                row["property_label"]=prop.property_name
                if key=="shifts":
                    row["label"]=f"{row.cashier} · {local_report_time(row.opened_at,prop)} · {row.name}"
                result[key].append(row)
        if "stay" in meta["filters"]:
            from hospitality_suite.report_presentation import Descriptions
            descriptions=Descriptions([prop])
            from hospitality_suite.printing import hs_label
            for row in project("HS Stay",prop,["name","actual_check_in","status"]):
                row["label"]=f"{descriptions.stay(row.name,include_time=True)} · {hs_label(row.status)}"
                row["property_label"]=prop.property_name
                result["stays"].append(row)
        if "warehouse" in meta["filters"]:
            from hospitality_suite.procurement import warehouses
            result["warehouses"] += [dict(name=n,warehouse_name=n,property_label=prop.property_name) for n in warehouses(prop)]
        if "user" in meta["filters"]:
            dt=REPORTS[meta["base"]][0]
            if dt:
                users.update((r.actor if dt=="HS Audit Event" else r.owner) for r in permitted_report_owners(dt,prop))
                if meta["base"]=="Producción":
                    users.update(r.owner for r in permitted_report_owners("HS Service Request",prop))
                    from hospitality_suite.paging import permitted_all
                    users.update(r.actor for r in permitted_all("HS Audit Event",filters={"property":prop.name,"source_doctype":"Sales Invoice","action":"on_submit"},fields=["actor"]))
            else:
                for native in ("Stock Entry","Stock Reconciliation","Purchase Receipt","Sales Invoice"):
                    users.update(r.owner for r in permitted_report_owners(native,prop))
        result["channels"] += [r.channel for r in project("HS Booking",prop,["channel"]) if r.channel]
        if "assigned_to" in meta["filters"]:
            users.update(r.assigned_to for r in project(base_dt,prop,["assigned_to"]) if r.assigned_to)
    users.discard(None)
    result["users"]=frappe.get_all("User",filters={"name":["in",list(users)]},fields=["name","full_name"])
    result["channels"]=sorted(set(result["channels"]+["Venta directa"]))
    return result


def local_report_time(value,prop):
    from hospitality_suite.time import local
    return local(value,prop).strftime("%d/%m/%Y %H:%M") if value else "—"


def permitted_report_owners(dt,prop):
    from hospitality_suite.paging import permitted_all
    field="hs_property" if not dt.startswith("HS ") else "property"
    return permitted_all(dt,filters={field:prop.name},fields=["owner"]+(["actor"] if dt=="HS Audit Event" else []))


@frappe.whitelist()
def report_page(property_name,report_name,filters=None,offset=0,page_length=50):
    from hospitality_suite.paging import page
    from hospitality_suite.report_presentation import prepare
    from hospitality_suite.report_queries import scopes
    selected=payload(filters or {})
    records,columns=prepare(report_name,report(property_name,report_name,selected),scopes(property_name,selected.get("company")),selected.get("detail_level") or "operational")
    result=page(records,offset,page_length)
    result["columns"]=columns
    return result


@frappe.whitelist()
def guest_history(name,offset=0,page_length=50):
    from hospitality_suite.paging import permitted_all,page
    guest=document("HS Guest",name)
    companions=frappe.get_all("HS Stay Guest",filters={"guest":guest.name},fields=["parent","relationship"])
    relation={row.parent:row.relationship for row in companions}
    records=permitted_all("HS Stay",filters={"property":guest.property},
                          or_filters={"guest":guest.name,"name":["in",list(relation) or [""]]},
                          fields=["name","guest","room","starts_at","ends_at","actual_check_in","actual_check_out","status"])
    for row in records:
        row["relationship"]="Principal" if row.pop("guest")==guest.name else relation[row.name]
    from hospitality_suite.report_presentation import prepare
    records,columns=prepare("Historial de estancias",records,[require(guest.property)])
    result=page(records,offset,page_length)
    result["columns"]=columns
    return result


@frappe.whitelist()
def export_report(property_name, report_name, filters=None, file_format="xlsx"):
    from hospitality_suite.report_queries import scopes,metadata,describe_filters
    selected=scopes(property_name,payload(filters or {}).get("company"))
    if not is_system() and not set(frappe.get_roles()).intersection(["HS Administrator","HS Manager","HS Accountant"]):
        frappe.throw(frappe._("La exportación requiere gerencia o contabilidad"),frappe.PermissionError)
    from hospitality_suite.report_presentation import prepare
    records,headers=prepare(report_name,report(property_name,report_name,filters),selected,payload(filters or {}).get("detail_level") or "operational")
    headers=headers or ["Sin datos"]
    from hospitality_suite.report_formatting import xlsx_data,pdf_html
    if file_format=="xlsx":
        from frappe.utils.xlsxutils import make_xlsx
        data,widths,styles=xlsx_data(records,headers)
        content=make_xlsx(data,"Reporte",column_widths=widths,styles=styles).getvalue()
    elif file_format=="pdf":
        from frappe.utils.pdf import get_pdf,is_wkhtmltopdf_valid
        if not is_wkhtmltopdf_valid():
            frappe.throw(frappe._("El generador PDF del servidor requiere wkhtmltopdf con Qt parcheado. Solicite a administración revisar la instalación."))
        scope_label=selected[0].property_name+" · "+selected[0].time_zone if property_name else selected[0].company+" · establecimientos autorizados"
        note=metadata(report_name)['note']+" "+describe_filters(selected,report_name,payload(filters or {}))
        content=get_pdf(pdf_html(report_name,scope_label,records,headers,note),{"orientation":"Landscape","footer-right":"[page] / [topage]","footer-font-size":"8","footer-spacing":"5"})
    else:
        frappe.throw(frappe._("Formato no permitido"))
    frappe.local.response.update(filename="hospitality-report."+file_format,filecontent=content,type="binary")


@frappe.whitelist(methods=["POST"])
def save_setup(property_name, section, data, request_key, expected_modified=None):
    values = payload(data)
    allowed = {
        "property": ["lodging_charge_policy", "brand_name", "mode", "time_zone", "check_in_time", "check_out_time", "cleaning_minutes", "inspection_required", "discreet_mode", "hold_minutes", "guest_id_required", "allow_credit", "close_time", "retention_days", "portal_enabled", "cost_center", "warehouse", "laundry_warehouse", "receivable_account", "guarantee_account", "cash_transfer_account", "price_list", "lodging_item", "tax_template", "tax_policy_confirmed", "financial_enabled", "cancellation_fee_mode", "cancellation_fee_value", "no_show_fee_mode", "no_show_fee_value", "penalty_item", "early_hour_rate", "late_hour_rate", "schedule_grace_minutes", "schedule_rounding_minutes", "timing_item", "checkout_inspection_required", "checkout_quote_minutes", "cash_denominations"],
        "room": ["room_number", "category", "floor", "zone", "beds", "parking", "active"],
        "category": ["category_name", "capacity", "amenities","max_extra_beds"],
        "rate": ["title", "category", "mode", "currency", "amount", "block_hours", "extra_hour_rate", "grace_minutes", "rounding_minutes", "additional_person_rate", "included_people","extra_bed_rate", "priority", "valid_from", "valid_to", "weekdays", "customer", "night_start","night_end","active"],
        "payment_method": ["mode_of_payment", "account", "currency", "reference_required", "is_cash"],
        "billing_party": ["customer","kind","credit_authorized","credit_limit","valid_until","reason"],
    }
    allowed["property"] += ["invoice_series","payment_series","invoice_print_format","receipt_print_format"]
    allowed["property"] += ["advance_policy","guarantee_policy","extra_hour_item"]
    allowed["rate"].append("included_services")
    allowed["payment_method"]+=list(treasury.METHOD_FIELDS)
    allowed["expense_category"]=["label","account","max_amount","active"]
    allowed["supplier"]=["supplier","active"]
    allowed["equipment"]=["equipment_code","label","room","asset","active","instructions"]
    if "included_services" in values:
        services=values["included_services"]
        if not isinstance(services,list) or len(services)>100:
            frappe.throw(frappe._("Revise la lista de servicios incluidos"))
        values["included_services"]=[{key:row.get(key) for key in ("item","quantity","basis")} for row in services]
    if section not in allowed or any(k not in allowed[section] for k in values):
        frappe.throw(frappe._("Campo de configuración no admitido"))
    def save(prop):
        if section == "property":
            from hospitality_suite.service import assert_version
            assert_version(prop,expected_modified)
            prop.update(values)
            prop.save()
            doc = prop
        else:
            dt = {"room": "HS Room", "category": "HS Category", "rate": "HS Rate", "payment_method": "HS Payment Method","billing_party":"HS Billing Party","expense_category":"HS Expense Category","supplier":"HS Supplier","equipment":"HS Equipment"}[section]
            doc = insert(dt, prop, **values)
        audit(prop, "Setup " + section, doc)
        return dict(name=doc.name)
    return command(property_name, "setup", request_key, dict(operation="setup_" + section, **values), save)


@frappe.whitelist(methods=["POST"])
def create_guest(property_name, data, request_key):
    values = payload(data)
    from hospitality_suite.guest_profiles import create
    return command(property_name, "guest", request_key, dict(operation="create_guest", **values), lambda prop:create(prop,values))


@frappe.whitelist()
def guest_detail(name):
    from hospitality_suite.guest_profiles import detail
    return detail(name)


@frappe.whitelist(methods=["POST"])
def update_guest(property_name, name, modified, data, reason, request_key, related_versions=None):
    from hospitality_suite.guest_profiles import update
    values,versions=payload(data),payload(related_versions or {})
    body=dict(operation='update_guest',guest=name,modified=modified,values=values,reason=reason,related_versions=versions)
    return command(property_name,'guest',request_key,body,lambda prop:update(prop,name,modified,values,reason,versions))


@frappe.whitelist(methods=["POST"])
def create_property(data, request_key):
    return setup.create_property(payload(data),request_key)


@frappe.whitelist()
def configuration(property_name):
    return require(property_name,"setup").as_dict()


@frappe.whitelist()
def setup_options(property_name):
    return setup.document_settings(require(property_name,"setup"))


@frappe.whitelist()
def booking_detail(name):
    doc = document("HS Booking",name)
    prop = require(doc.property)
    from hospitality_suite.booking_presentation import summary
    return dict(booking=doc.as_dict(), summary=summary(doc,prop), draft=booking_drafts.values_for(doc,prop) if doc.status=='Draft' else None, allocations=project("HS Allocation",prop,
                fields=["name","room","category","booking_room"],filters={"booking":name,"kind":"Reservation","status":"Active"}))


@frappe.whitelist()
def calendar(property_name,starts_at,ends_at):
    from hospitality_suite.time import local
    prop=require(property_name)
    start,end=to_site(starts_at,prop),to_site(ends_at,prop)
    if end<=start or (end-start).days>31:
        frappe.throw(frappe._("Consulte un intervalo de hasta 31 días"))
    rows=project("HS Allocation",prop,fields=["name","room","category","starts_at","ends_at","kind","status","booking","stay","maintenance"],
                 filters={"starts_at":["<",end]})
    result=[]
    for row in rows:
        if row.ends_at and frappe.utils.get_datetime(row.ends_at)<=start:
            continue
        row["until_reopened"]=row.kind=="Maintenance" and not row.ends_at
        if not row.ends_at:
            row.ends_at=end
        if row.status=="Released" and row.kind not in ("Stay","Maintenance"):
            continue
        if row.status=="Released" and row.kind=="Maintenance":
            order=frappe.get_doc("HS Maintenance Order",row.maintenance) if row.maintenance else None
            if not order or order.status!="Completed":
                continue
            row.ends_at=min(frappe.utils.get_datetime(row.ends_at),housekeeping.maintenance_finished_at(order))
            if row.ends_at<=frappe.utils.get_datetime(row.starts_at):
                continue
        if row.kind=="Stay" and row.stay:
            stay=frappe.get_doc("HS Stay",row.stay)
            row.starts_at=max(frappe.utils.get_datetime(row.starts_at),frappe.utils.get_datetime(stay.actual_check_in))
            if stay.actual_check_out:
                row.ends_at=min(frappe.utils.get_datetime(row.ends_at),frappe.utils.get_datetime(stay.actual_check_out))
            if row.ends_at<=row.starts_at:
                continue
        if frappe.utils.get_datetime(row.ends_at)<=start:
            continue
        row.starts_at=local(row.starts_at,prop).isoformat()
        row.ends_at=local(row.ends_at,prop).isoformat()
        result.append(row)
    return result


@frappe.whitelist()
def room_balances(property_name):
    prop=require(property_name)
    if not may("stay") and not may("finance"):
        frappe.throw(frappe._("No tiene acceso a saldos"),frappe.PermissionError)
    result={}
    for stay in project("HS Stay",prop,fields=["name"],filters={"status":"Active"}):
        total=0
        shared=False
        stay_doc=frappe.get_doc("HS Stay",stay.name)
        for folio in accounting.folios_for_stay(stay_doc):
            total+=float(accounting.folio_balance(folio.name)["outstanding"])
            shared=shared or not bool(folio.stay)
        result[stay.name]=dict(amount=total,shared=shared)
    return result


@frappe.whitelist()
def inventory_status(property_name,warehouse_name=None):
    prop=require(property_name)
    if not any(may(a) for a in ("service","report","inventory","clean","maintain")):
        frappe.throw(frappe._("No tiene permiso para consultar existencias"),frappe.PermissionError)
    if not prop.warehouse:
        return dict(warehouse=None,items=[])
    target=procurement.warehouse(prop,warehouse_name)
    bins=frappe.get_all("Bin",filters={"warehouse":target},fields=["item_code","actual_qty","projected_qty"])
    minimums={r.parent:r for r in frappe.get_all("Item Reorder",filters={"warehouse":target},fields=["parent","warehouse_reorder_level","warehouse_reorder_qty"])}
    existing={r.item_code for r in bins}
    bins += [frappe._dict(item_code=item,actual_qty=0,projected_qty=0) for item in minimums if item not in existing]
    purposes={r.item:r.purpose for r in frappe.get_all("HS Stock Policy",filters={"property":prop.name,"warehouse":target},fields=["item","purpose"])}
    existing={r.item_code for r in bins}
    bins += [frappe._dict(item_code=item,actual_qty=0,projected_qty=0) for item in purposes if item not in existing]
    for row in bins:
        row["item_name"]=frappe.db.get_value("Item",row.item_code,"item_name")
        setting=minimums.get(row.item_code)
        row["minimum"]=setting.warehouse_reorder_level if setting else None
        row["reorder_quantity"]=setting.warehouse_reorder_qty if setting else None
        row["purpose"]=purposes.get(row.item_code) or ("Asset" if frappe.db.get_value("Item",row.item_code,"is_fixed_asset") else "Merchandise")
        row["stock_managed"]=row["purpose"]!="Asset"
        if not row["stock_managed"]:
            row["actual_qty"],row["projected_qty"],row["minimum"]=None,None,None
        row["needs_restock"]=bool(setting and row.actual_qty<setting.warehouse_reorder_level)
    return dict(warehouse=target,items=bins)
