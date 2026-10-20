"""Declarative schema; generated JSON is committed and installed by Frappe sync."""

ROLES = ["HS Administrator", "HS Manager", "HS Supervisor", "HS Receptionist", "HS Cashier",
         "HS Housekeeping", "HS Maintenance", "HS Accountant", "HS Auditor"]
OPERATORS = ROLES[:5] + ["HS Accountant", "HS Auditor"]
MANAGERS = ROLES[:3]
FINANCE = ROLES[:3] + ["HS Cashier", "HS Accountant", "HS Auditor"]
STANDARD_SCOPED=("Sales Invoice","Payment Entry","Journal Entry","Stock Entry","Stock Reconciliation","Purchase Invoice","Purchase Receipt","Purchase Order","Material Request","Delivery Note","Sales Order")


def f(name, kind="Data", options=None, required=False, **kwargs):
    labels = {"property": "Establecimiento", "company": "Compañía", "status": "Estado",
              "room": "Habitación", "category": "Categoría", "customer": "Cliente pagador",
              "starts_at": "Desde", "ends_at": "Hasta", "currency": "Moneda"}
    out = dict(fieldname=name, label=labels.get(name, name.replace("_", " ").capitalize()), fieldtype=kind)
    if kind in ("Currency","Float"):
        out["default"]=0
    if options is not None:
        out["options"] = options
    if required:
        out["reqd"] = 1
    out.update(kwargs)
    return out


def link(name, dt, required=True, **kw):
    return f(name, "Link", dt, required, **kw)


def select(name, options, default=None, **kw):
    return f(name, "Select", "\n".join(options), True, default=default or options[0], **kw)


SCOPE = [link("company", "Company"), link("property", "HS Property")]
SPAN = [f("starts_at", "Datetime", required=True), f("ends_at", "Datetime", required=True)]
MONEY = [link("currency", "Currency"), f("amount", "Currency", "currency", True)]

SCHEMA = {
    "HS Access": dict(roles=["System Manager"], writable=True, fields=[link("user", "User"), *SCOPE]),
    "HS Property": dict(roles=ROLES, writable=True, fields=[
        f("property_name", required=True), link("company", "Company"),
        select("mode", ["Hotel", "Motel", "Mixed"]), f("time_zone", default="America/Managua", reqd=1),
        f("business_date", "Date", required=True), f("close_time", "Time", default="06:00:00"),
        link("currency", "Currency"), f("check_in_time", "Time", default="14:00:00"),
        f("check_out_time", "Time", default="12:00:00"), f("cleaning_minutes", "Int", default=30),
        f("inspection_required", "Check", default=1), f("discreet_mode", "Check"),
        select("lodging_charge_policy",["Arrival","Nightly"],default="Arrival",label="Generación de cargos de alojamiento"),
        f("portal_enabled", "Check"), f("financial_enabled", "Check"), f("allow_credit", "Check"),
        select("advance_policy",["Manual","Approval","Disabled"],default="Manual",label="Política de anticipos"),
        select("guarantee_policy",["Manual","Approval","Disabled"],default="Manual",label="Política de garantías"),
        f("guest_id_required", "Check"), f("hold_minutes", "Int", default=15),
        link("cost_center", "Cost Center", False), link("warehouse", "Warehouse", False), link("laundry_warehouse", "Warehouse", False),
        link("income_account","Account",False,label="Cuenta de ingresos del establecimiento"),
        link("expense_account","Account",False,label="Cuenta de gastos del establecimiento"),
        f("service_accounts","Table","HS Service Account",label="Contabilidad por servicio"),
        link("receivable_account", "Account", False), link("guarantee_account", "Account", False),
        link("cash_transfer_account","Account",False),
        link("lodging_item", "Item", False), link("extra_hour_item","Item",False,label="Artículo de horas adicionales por tiempo"), link("tax_template", "Sales Taxes and Charges Template", False),
        link("price_list","Price List",False),
        f("tax_policy_confirmed", "Check"), f("brand_name"), f("retention_days", "Int", default=365),
        select("cancellation_fee_mode",["None","Fixed","First Night","Percent"]),f("cancellation_fee_value","Currency","currency"),
        select("no_show_fee_mode",["None","Fixed","First Night","Percent"]),f("no_show_fee_value","Currency","currency"),
        link("penalty_item","Item",False),
        f("early_hour_rate","Currency","currency"),f("late_hour_rate","Currency","currency"),
        f("schedule_grace_minutes","Int",default=0),f("schedule_rounding_minutes","Int",default=60),link("timing_item","Item",False),
        f("checkout_inspection_required","Check"),f("checkout_quote_minutes","Int",default=5),
        f("cash_denominations","Code","JSON"),
        f("invoice_series"),f("payment_series"),link("invoice_print_format","Print Format",False),link("receipt_print_format","Print Format",False),
    ]),
    "HS Service Account":dict(child=True,fields=[link("item","Item",label="Artículo o servicio",in_list_view=1),
        link("income_account","Account",False,label="Cuenta de ingresos",in_list_view=1),
        link("expense_account","Account",False,label="Cuenta de gastos",in_list_view=1),
        link("cost_center","Cost Center",False,label="Centro de costo",in_list_view=1)]),
    "HS Category": dict(roles=ROLES, writable=True, fields=[*SCOPE, f("category_name", required=True), f("capacity", "Int", default=2),f("max_extra_beds","Int",default=0), f("amenities", "Small Text")]),
    "HS Room": dict(roles=ROLES, writable=True, fields=[*SCOPE, f("room_number", required=True), link("category", "HS Category"),
        f("floor"), f("zone"), f("beds", "Int", default=1), f("parking"), f("active", "Check", default=1),
        select("cleaning_status", ["Clean", "Dirty", "Cleaning", "Inspection"])]),
    "HS Rate": dict(roles=OPERATORS, writable=True, fields=[*SCOPE, f("title", required=True), link("category", "HS Category"),
        select("mode", ["Hotel", "Motel"]), *MONEY, f("block_hours", "Float", default=3),
        f("extra_hour_rate", "Currency", "currency"), f("grace_minutes", "Int", default=0),
        f("rounding_minutes", "Int", default=60), f("additional_person_rate", "Currency", "currency"),
        f("included_people", "Int", default=2), f("extra_bed_rate", "Currency", "currency"),
        f("priority", "Int", default=10), f("valid_from", "Date"), f("valid_to", "Date"),
        f("weekdays", description="0=lunes ... 6=domingo; vacío=todos"), link("customer", "Customer", False),
        f("night_start", "Time"), f("night_end", "Time"),f("included_services","Table","HS Rate Service"), f("active", "Check", default=1)]),
    "HS Rate Service":dict(child=True,fields=[link("item","Item"),f("quantity","Float",default=1,required=True),select("basis",["Stay","Night"])]),
    "HS Guest": dict(roles=OPERATORS, writable=True, fields=[*SCOPE, f("full_name", required=True), f("email", "Data", options="Email"),
        f("phone", "Data"), f("identity_type"), f("identity_number"), f("nationality"),
        f("identity_file", "Attach"), link("customer", "Customer", False),link("contact","Contact",False),link("address","Address",False)]),
    "HS Booking Room": dict(child=True, fields=[link("category", "HS Category"), link("room", "HS Room", False), f("people", "Int", default=1),f("extra_beds","Int",default=0), link("rate", "HS Rate")]),
    "HS Booking": dict(roles=OPERATORS, fields=[*SCOPE, link("customer", "Customer", False), link("guest", "HS Guest", False), f("starts_at", "Datetime"), f("ends_at", "Datetime"),
        select("status", ["Draft", "Hold", "Confirmed", "Checked In", "Completed", "Cancelled", "No Show"]),
        f("hold_until", "Datetime"), f("channel", default="Recepción",label="Canal"), f("instructions", "Small Text"),
        f("rooms", "Table", "HS Booking Room"), f("reason", "Small Text"), *MONEY,
        f("draft_data", "Code", "JSON", hidden=1, print_hide=1, read_only=1,label="Datos del borrador"),
        f("quote_snapshot", "Code", "JSON"),link("fee_invoice","Sales Invoice",False),f("fee_amount","Currency","currency"), f("portal_token_hash", hidden=1), f("portal_expires_at", "Datetime", hidden=1)]),
    "HS Allocation": dict(roles=OPERATORS, fields=[*SCOPE, link("category", "HS Category"), link("room", "HS Room", False),
        f("starts_at","Datetime",required=True),f("ends_at","Datetime"),f("buffer_minutes", "Int"), select("kind", ["Reservation", "Stay", "Maintenance"]),
        select("status", ["Active", "Released"]), link("booking", "HS Booking", False), link("stay", "HS Stay", False),
        f("booking_room"),
        link("portal_request","HS Portal Request",False),
        link("rate","HS Rate",False),link("currency","Currency",False),f("accepted_amount","Currency","currency"),f("quote_snapshot","Code","JSON"),
        link("maintenance", "HS Maintenance Order", False)]),
    "HS Stay Guest": dict(child=True, fields=[link("guest", "HS Guest"), select("relationship", ["Principal", "Acompañante"])]),
    "HS Stay": dict(roles=OPERATORS, fields=[*SCOPE, link("booking", "HS Booking", False), link("guest", "HS Guest"),
        select("lodging_charge_policy",["Arrival","Nightly"],default="Arrival",read_only=1,label="Política de cargos aceptada"),
        link("customer", "Customer"), link("room", "HS Room"), *SPAN, f("actual_check_in", "Datetime"), f("actual_check_out", "Datetime"),
        select("status", ["Active", "Checked Out"]), link("rate", "HS Rate"), *MONEY,
        f("quote_snapshot", "Code", "JSON"),f("service_entitlements","Code","JSON"), f("guests", "Table", "HS Stay Guest"), f("reason", "Small Text"),
        f("early_fee","Currency","currency"),f("late_fee","Currency","currency"),f("departure_expires_at","Datetime"),
        link("departure_inspected_by","User",False),f("departure_inspected_at","Datetime"),f("departure_notes","Small Text")]),
    "HS Folio": dict(roles=OPERATORS, fields=[*SCOPE, link("stay", "HS Stay",False),link("booking","HS Booking",False), link("customer", "Customer"),
        link("currency", "Currency"), select("status", ["Open", "Closed"]), f("label", default="Cuenta principal")]),
    "HS Charge": dict(roles=OPERATORS, fields=[*SCOPE, link("stay", "HS Stay"), link("folio", "HS Folio"), link("item", "Item"),
        f("description", "Small Text"), f("quantity", "Float", default=1), f("rate", "Currency", "currency"), *MONEY,
        f("business_date", "Date", required=True), select("kind", ["Lodging", "Service", "Adjustment"]),
        select("status", ["Pending", "Invoiced", "Reversed", "Scheduled"]), link("sales_invoice", "Sales Invoice", False),
        f("period_key",unique=1,read_only=1,hidden=1,print_hide=1),
        f("service_date","Date",read_only=1,label="Noche de alojamiento"),
        f("posted_at","Datetime",read_only=1,label="Cargo generado el"),
        f("invoice_item"), f("reason", "Small Text"), f("quote_snapshot", "Code", "JSON"),link("applies_to_charge","HS Charge",False),
        f("adjustment_type","Select","\nDiscount\nCourtesy\nSurcharge")]),
    "HS Payment Method": dict(roles=FINANCE, writable=True, fields=[*SCOPE, link("mode_of_payment", "Mode of Payment"),
        link("account", "Account"), link("currency", "Currency"), f("reference_required", "Check"), f("is_cash", "Check"),
        f("fee_percent","Percent"),f("fee_fixed","Currency","currency"),link("fee_account","Account",False),
        f("refund_fee_percent","Percent"),f("refund_fee_fixed","Currency","currency"),
        f("withholding_percent","Percent"),link("withholding_account","Account",False),link("settlement_account","Account",False)]),
    "HS Expense Category":dict(roles=FINANCE,writable=True,fields=[*SCOPE,f("label",required=True),link("account","Account"),
        link("currency","Currency",read_only=1),f("max_amount","Currency","currency"),f("active","Check",default=1)]),
    "HS Supplier":dict(roles=FINANCE,writable=True,fields=[*SCOPE,link("supplier","Supplier"),f("active","Check",default=1)]),
    "HS Stock Policy":dict(roles=FINANCE,writable=True,fields=[*SCOPE,link("item","Item"),link("warehouse","Warehouse"),
        select("purpose",["Merchandise","Cleaning","Linen","Parts","Asset"])]),
    "HS Shift": dict(roles=FINANCE, fields=[*SCOPE, link("cashier", "User"), f("opened_at", "Datetime"), f("closed_at", "Datetime"),
        select("status", ["Open", "Review", "Closed"]), link("currency", "Currency"), f("opening_amount", "Currency", "currency"),
        f("expected_amount", "Currency", "currency"), f("counted_amount", "Currency", "currency"), f("difference", "Currency", "currency"),
        f("denominations", "Code", "JSON"), f("reason", "Small Text"), link("approved_by", "User", False)]),
    "HS Payment": dict(roles=FINANCE, fields=[*SCOPE, link("stay", "HS Stay", False), link("booking", "HS Booking", False),
        f("business_date","Date",read_only=1,label="Fecha operativa"),f("business_date_source",read_only=1,hidden=1,print_hide=1),
        link("folio", "HS Folio", False), link("customer", "Customer",False), link("shift", "HS Shift"), link("method", "HS Payment Method"),
        *MONEY, f("exchange_rate", "Float", default=1), f("base_amount", "Currency"),
        select("kind", ["Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund", "Guarantee Applied", "Withdrawal","Expense","Supplier Payment","Settlement"]),
        select("status", ["Posted", "Cancelled"]), link("payment_entry", "Payment Entry", False), link("journal_entry", "Journal Entry", False),
        f("reference"), link("source_payment", "HS Payment", False), f("reason", "Small Text"),
        f("tendered","Currency","currency"),f("change_amount","Currency","currency"),link("service","HS Service Request",False),link("sales_invoice","Sales Invoice",False),
        link("expense_category","HS Expense Category",False),link("supplier","Supplier",False),link("purchase_invoice","Purchase Invoice",False),
        f("fee_snapshot","Code","JSON",hidden=1,print_hide=1),f("fee_amount","Currency","currency"),f("withholding_amount","Currency","currency"),f("net_amount","Currency","currency"),f("clearing_base_amount","Currency"),f("settlement_direction","Select","\nReceive\nPay")]),
    "HS Cleaning Task": dict(roles=ROLES, fields=[*SCOPE, link("room", "HS Room"), link("stay", "HS Stay", False),
        select("kind", ["Departure", "Stay", "Deep"]), select("priority", ["Normal", "High", "Urgent"]), link("assigned_to", "User", False),
        select("status", ["Pending", "In Progress", "Inspection", "Completed"]), f("started_at", "Datetime"), f("completed_at", "Datetime"),
        f("checklist", "Code", "JSON"), f("notes", "Small Text"), link("inspected_by", "User", False)]),
    "HS Equipment":dict(roles=ROLES,writable=True,fields=[*SCOPE,f("equipment_code",required=True),f("label",required=True),link("room","HS Room",False),
        link("asset","Asset",False),f("active","Check",default=1),f("instructions","Small Text")]),
    "HS Maintenance Order": dict(roles=ROLES, fields=[*SCOPE, link("room", "HS Room",False),link("equipment","HS Equipment",False),f("blocks_room","Check",default=1), f("title", required=True),
        f("starts_at","Datetime",required=True),f("until_reopened","Check",default=0,label="Hasta reapertura autorizada"),
        f("ends_at","Datetime",mandatory_depends_on="eval:!doc.until_reopened",depends_on="eval:!doc.until_reopened"),
        select("kind", ["Corrective", "Preventive"]), select("status", ["Open", "In Progress", "Completed"]),
        link("assigned_to", "User", False), f("notes", "Small Text"), f("evidence", "Attach"), f("cost", "Currency"),
        link("stock_entry", "Stock Entry", False),f("parts","Table","HS Maintenance Part"), link("reopened_by", "User", False)]),
    "HS Maintenance Part": dict(child=True,fields=[link("item","Item"),f("quantity","Float",required=True),
        link("stock_entry","Stock Entry"),f("cost","Currency"),select("status",["Issued","Returned"])]),
    "HS Service Request": dict(roles=OPERATORS, fields=[*SCOPE, link("stay", "HS Stay", False), link("folio", "HS Folio", False),
        link("customer", "Customer", False), link("item", "Item"), f("quantity", "Float", default=1),f("included","Check"), *MONEY,
        select("status", ["Requested", "In Progress", "Delivered", "Cancelled", "Returned"]),
        link("charge", "HS Charge", False), link("stock_entry", "Stock Entry", False), link("return_stock_entry", "Stock Entry", False), link("credit_note", "Sales Invoice", False),link("sales_invoice","Sales Invoice",False), f("notes", "Small Text")]),
    "HS Incident": dict(roles=ROLES, fields=[*SCOPE, link("room", "HS Room"), select("kind", ["Damage", "Lost Property", "Linen"]),
        f("description", "Small Text", required=True), f("evidence", "Attach"), link("item", "Item", False), f("quantity", "Float"),
        select("status", ["Open", "Resolved"]), link("stock_entry", "Stock Entry", False),f("resolution","Small Text"),
        link("resolved_by","User",False),f("resolved_at","Datetime")]),
    "HS Daily Close": dict(roles=FINANCE, fields=[*SCOPE, f("business_date", "Date", required=True),
        select("status", ["Review", "Closed", "Reopened"]), f("summary", "Code", "JSON"), f("blockers", "Code", "JSON"),
        f("closed_at", "Datetime"), f("reason", "Small Text")]),
    "HS Audit Event": dict(roles=["HS Administrator", "HS Manager", "HS Accountant", "HS Auditor"], fields=[*SCOPE, f("action", required=True),
        f("source_doctype", required=True), f("source_name", required=True), link("actor", "User"), f("occurred_at", "Datetime"),
        f("business_date", "Date"), f("reason", "Small Text"), f("details", "Code", "JSON")]),
    "HS Request": dict(roles=["System Manager"], fields=[*SCOPE, f("request_key", required=True, unique=1), f("payload_hash", required=True),
        f("operation", required=True), f("result", "Code", "JSON")]),
    "HS Integration Event": dict(roles=MANAGERS, fields=[*SCOPE, f("provider", required=True), f("event_id", required=True, unique=1),
        select("status", ["Received", "Processed", "Failed"]), f("attempts", "Int"), f("last_error", "Small Text"), f("payload", "Code", "JSON")]),
    "HS Portal Request": dict(roles=OPERATORS, fields=[*SCOPE,f("full_name",required=True),f("email",options="Email"),f("phone"),*SPAN,
        link("category","HS Category"),f("rooms","Int",default=1),f("people","Int",default=1),select("mode",["Hotel","Motel"]),
        select("status",["Hold","Converted","Expired","Cancelled"]),f("hold_until","Datetime"),*MONEY,
        f("quote_snapshot","Code","JSON"),f("request_key",unique=1,hidden=1),f("payload_hash",hidden=1),link("booking","HS Booking",False)]),
    "HS Billing Party": dict(roles=OPERATORS,writable=True,fields=[*SCOPE,link("customer","Customer"),select("kind",["Company","Agency","Individual"]),
        f("credit_authorized","Check"),f("credit_limit","Currency"),f("valid_until","Date"),f("reason","Small Text",required=True)]),
    "HS Retention Run":dict(roles=ROLES[:2],fields=[*SCOPE,select("status",["Pending","Completed","Failed"]),link("approved_by","User"),
        f("approved_at","Datetime"),f("cutoff","Datetime"),f("retention_days","Int"),f("reason","Small Text",required=True),f("plan","Code","JSON"),
        f("files","Table","HS Retention File"),f("attempts","Int",default=0),f("last_error","Small Text"),f("completed_at","Datetime")]),
    "HS Retention File":dict(child=True,fields=[f("source_file",required=True),f("file_url",hidden=1,print_hide=1),f("thumbnail_url",hidden=1,print_hide=1),
        f("content_hash",hidden=1,print_hide=1),select("status",["Pending","Deleted","Shared","Failed"]),f("last_error","Small Text")]),
}

SCOPED = [name for name, spec in SCHEMA.items() if not spec.get("child") and name != "HS Access"]
WRITABLE = [name for name, spec in SCHEMA.items() if spec.get("writable")]
PAGES = {
    "hospitality-home": ("Inicio", ROLES), "hospitality-reception": ("Recepción", OPERATORS),
    "hospitality-reservations": ("Reservas", OPERATORS), "hospitality-stays": ("Estancias", OPERATORS),
    "hospitality-cashier": ("Caja", FINANCE), "hospitality-housekeeping": ("Limpieza", ROLES),
    "hospitality-maintenance": ("Mantenimiento", ROLES), "hospitality-services": ("Consumos e inventario", OPERATORS),
    "hospitality-guests": ("Clientes y huéspedes", OPERATORS), "hospitality-management": ("Gerencia", MANAGERS+["HS Accountant","HS Auditor"]),
    "hospitality-setup": ("Configuración", MANAGERS),
}
