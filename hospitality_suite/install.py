import frappe
import json
from pathlib import Path
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hospitality_suite.schema import ROLES, SCOPED, STANDARD_SCOPED, ERP_LINK_TARGETS


def after_install():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc(dict(doctype="Role", role_name=role, desk_access=1)).insert()
    after_migrate()


def after_migrate():
    if not frappe.db.get_single_value("HS Site Mode", "provider"):
        frappe.db.set_single_value("HS Site Mode", "provider",
            "ERPNext" if "erpnext" in frappe.get_installed_apps() else "PMS")
    from hospitality_suite.standalone_accounting import provider
    erp_mode = provider() == "erpnext"
    erp_installed = "erpnext" in frappe.get_installed_apps()
    if erp_mode and not erp_installed:
        frappe.throw(frappe._("El modo ERPNext requiere instalar ERPNext antes de sincronizar la Suite"))
    if erp_mode:
        restore_erp_links()
    elif erp_installed:
        restore_pms_data_fields()
    custom = []
    for name, target, label in [("hs_property", "HS Property", "Establecimiento de alojamiento"), ("hs_stay", "HS Stay", "Estancia de alojamiento"), ("hs_shift", "HS Shift", "Turno de caja"), ("hs_folio", "HS Folio", "Cuenta de estancia"), ("hs_booking", "HS Booking", "Reserva de alojamiento")]:
        custom.append(dict(fieldname=name, label=label, fieldtype="Link", options=target, insert_after="company", no_copy=1,print_hide=1))
    if erp_installed:
        create_custom_fields({dt: custom for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)})
        create_custom_fields({dt:[dict(fieldname="hs_correction_reason",label="Motivo de corrección de alojamiento",fieldtype="Small Text",allow_on_submit=1,print_hide=1)] for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)})
        create_custom_fields({"Sales Invoice Item": [dict(fieldname="hs_charge", label="Cargo de estancia", fieldtype="Link", options="HS Charge", no_copy=1,print_hide=1)]})
        create_custom_fields({"Sales Invoice Item":[dict(fieldname="hs_charge_sources",label="Cargos que componen la línea",fieldtype="Code",options="JSON",read_only=1,no_copy=1,print_hide=1)]})
        create_custom_fields({"Warehouse":[dict(fieldname="hs_property",label="Establecimiento de alojamiento",fieldtype="Link",options="HS Property")]})
        create_custom_fields({"Asset":[dict(fieldname="hs_property",label="Establecimiento de alojamiento",fieldtype="Link",options="HS Property",allow_on_submit=1,print_hide=1)]})
        create_custom_fields({"Stock Entry":[dict(fieldname="hs_stock_purpose",label="Uso operativo",fieldtype="Select",options="\nSale\nCleaning\nWaste\nLinen Replacement\nMaintenance\nTransfer\nAdjustment\nLaundry",print_hide=1)]})
    from frappe.permissions import add_permission
    for dt in (("Account","Item","Company","Cost Center","Warehouse","Mode of Payment","Price List","Sales Taxes and Charges Template","Customer","Supplier","Currency") if erp_mode else ()):
        for role in ("HS Administrator","HS Manager","HS Supervisor","HS Receptionist","HS Cashier","HS Accountant"):
            if frappe.db.exists("Role",role) and not frappe.db.exists("Custom DocPerm",{"parent":dt,"role":role}):
                add_permission(dt,role,0,"select")
    for role in (("HS Administrator","HS Manager","HS Accountant","HS Auditor") if erp_mode else ()):
        if frappe.db.exists("Role",role) and not frappe.db.exists("Custom DocPerm",{"parent":"GL Entry","role":role}):
            add_permission("GL Entry",role,0,"read")
    for dt in (("Sales Invoice", "Payment Entry", "Journal Entry", "Stock Entry","Stock Reconciliation","Purchase Order","Purchase Receipt","Purchase Invoice") if erp_mode else ()):
        for role in ("HS Administrator", "HS Manager", "HS Supervisor", "HS Receptionist", "HS Cashier", "HS Accountant", "HS Auditor"):
            if frappe.db.exists("Role", role) and not frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
                add_permission(dt, role, 0, "read")
    for dt in SCOPED:
        if dt != "HS Property":
            frappe.db.add_index(dt, ["property", "modified"], f"hs_scope_{dt.lower().replace(' ', '_')}")
    frappe.db.add_index("HS Allocation", ["property", "status", "starts_at", "ends_at"], "hs_allocation_interval")
    frappe.db.add_unique("HS Access", ["user", "property"], "hs_access_unique")
    frappe.db.add_unique("HS Room", ["property", "room_number"], "hs_room_unique")
    if frappe.db.sql("SHOW INDEX FROM `tabHS Daily Close` WHERE Key_name='hs_close_unique'"):
        frappe.db.sql_ddl("ALTER TABLE `tabHS Daily Close` DROP INDEX `hs_close_unique`")
    frappe.db.sql("UPDATE `tabHS Daily Close` SET revision=1 WHERE revision IS NULL OR revision<1")
    frappe.db.add_unique("HS Daily Close", ["property", "business_date", "revision"],
                         "hs_close_revision_unique")
    frappe.db.add_unique("HS Billing Party",["property","customer"],"hs_billing_party_unique")
    frappe.db.add_unique("HS Supplier",["property","supplier"],"hs_supplier_unique")
    frappe.db.add_unique("HS Stock Policy",["property","item","warehouse"],"hs_stock_policy_unique")
    frappe.db.add_unique("HS Equipment",["property","equipment_code"],"hs_equipment_unique")
    frappe.db.add_unique("HS Laundry Rate",["property","garment","service_type"],"hs_laundry_rate_unique")
    frappe.db.add_unique("HS Travel Agent",["property","agent_name"],"hs_travel_agent_unique")
    frappe.db.add_unique("HS Experience",["property","experience_name"],"hs_experience_unique")
    frappe.db.add_index("HS Experience Order",["property","booking","status"],"hs_experience_booking")
    frappe.db.add_index("HS Laundry Order",["property","status","ready_by"],"hs_laundry_queue")
    frappe.db.add_index("HS Room Block",["property","status","starts_at","ends_at"],"hs_room_block_interval")
    frappe.db.add_index("HS Guest Ticket", ["property", "status", "due_at"], "hs_ticket_queue")
    frappe.db.add_index("HS Ticket Event", ["ticket", "occurred_at"], "hs_ticket_timeline")
    frappe.db.add_unique("HS Account", ["property", "account_code"], "hs_account_code_unique")
    frappe.db.add_unique("HS Product", ["property", "product_code"], "hs_product_code_unique")
    frappe.db.add_unique("HS Warehouse", ["property", "warehouse_code"], "hs_warehouse_code_unique")
    frappe.db.add_index("HS Journal", ["property", "posting_date"], "hs_journal_period")
    frappe.db.add_unique("HS Exchange Rate", ["property", "from_currency", "effective_at"], "hs_exchange_rate_unique")
    sync_print_formats()


POLYMORPHIC_STOCK_REFERENCES = (
    ("HS Incident", "stock_entry"),
    ("HS Maintenance Order", "stock_entry"),
    ("HS Maintenance Part", "stock_entry"),
    ("HS Service Request", "stock_entry"),
    ("HS Service Request", "return_stock_entry"),
)


def _restore_polymorphic_stock_references():
    """Preserve PMS movement IDs and native Stock Entry IDs in the same fields."""
    touched = set()
    for doctype, field in POLYMORPHIC_STOCK_REFERENCES:
        setters = frappe.get_all("Property Setter", filters={
            "doc_type": doctype, "field_name": field,
            "property": ["in", ["fieldtype", "options"]]},
            fields=["name", "is_system_generated"])
        if any(not row.is_system_generated for row in setters):
            frappe.throw(frappe._("Revise la personalización de {0}.{1} antes de migrar").format(doctype, field))
        for row in setters:
            frappe.db.delete("Property Setter", {"name": row.name})
            touched.add(doctype)
    for doctype in touched:
        frappe.clear_cache(doctype=doctype)


def restore_erp_links():
    """ERP sites retain link controls although core JSON stores portable data."""
    _restore_polymorphic_stock_references()
    touched = set()
    for (doctype, field), target in ERP_LINK_TARGETS.items():
        if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("DocType", target):
            continue
        touched.add(doctype)
        for prop, value in (("fieldtype", "Link"), ("options", target)):
            existing = frappe.db.get_value("Property Setter",
                {"doc_type": doctype, "field_name": field, "property": prop},
                ["name", "value", "is_system_generated"], as_dict=True)
            if existing and existing.value != value and not existing.is_system_generated:
                frappe.throw(frappe._("Revise la personalización existente de {0}.{1} antes de migrar").format(doctype, field))
            if existing and existing.value != value:
                frappe.db.set_value("Property Setter", existing.name, "value", value)
            elif not existing:
                # The fields and targets come from the Suite schema. Insert directly
                # so cache invalidation happens once per DocType, rather than once
                # per Property Setter validation and again after every field.
                frappe.get_doc({"doctype": "Property Setter",
                    "doctype_or_field": "DocField", "doc_type": doctype,
                    "field_name": field, "property": prop, "value": value,
                    "property_type": "Data", "is_system_generated": 1}).db_insert()
    for doctype in touched:
        frappe.clear_cache(doctype=doctype)


def restore_pms_data_fields():
    """Keep PMS identifiers writable while ERPNext is installed for a future cutover.

    Only remove the system-generated link overrides owned by Suite. The core
    DocType JSON remains portable Data; activation restores the ERP links after
    rewriting every surviving source reference to its ERPNext destination.
    """
    _restore_polymorphic_stock_references()
    for (doctype, field), target in ERP_LINK_TARGETS.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        setters = frappe.get_all("Property Setter", filters={
            "doc_type": doctype, "field_name": field,
            "property": ["in", ["fieldtype", "options"]]},
            fields=["name", "property", "value", "is_system_generated"])
        for setter in setters:
            expected = "Link" if setter.property == "fieldtype" else target
            if setter.value != expected or not setter.is_system_generated:
                frappe.throw(frappe._("Revise la personalización de {0}.{1} antes de operar en PMS").format(doctype, field))
        for setter in setters:
            # These generated metadata overrides have no document links.
            # Document.delete enqueues dynamic-link cleanup for each row,
            # including in a reversible cutover rehearsal.
            frappe.db.delete("Property Setter", {"name": setter.name})
        if setters:
            frappe.clear_cache(doctype=doctype)


def sync_print_formats():
    """Refresh app-owned formats by content, including a site's future timestamp."""
    from frappe.modules.import_file import import_file_by_path
    folder=Path(frappe.get_app_path("hospitality_suite","hospitality_suite","print_format"))
    paths = sorted(folder.glob('*/*.json'))
    from hospitality_suite.standalone_accounting import provider
    if provider() == "erpnext":
        paths.extend(Path(frappe.get_app_path("hospitality_suite", "erpnext_assets", "print_format")).glob("*.json"))
    for path in paths:
        source=json.loads(path.read_text(encoding='utf-8'))
        if not frappe.db.exists("DocType", source["doc_type"]):
            continue
        if frappe.db.exists('Print Format',source['name']):
            current=frappe.get_doc('Print Format',source['name'])
            if current.standard!='Yes' or current.module!='Hospitality Suite':
                continue
            if all(current.get(field)==source.get(field) for field in ('doc_type','html','css','print_format_type','custom_format')):
                continue
        import_file_by_path(str(path),force=True,ignore_version=True)
        frappe.clear_document_cache('Print Format',source['name'])


def validate_financial_configuration(prop):
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms":
        frappe.throw(frappe._("Configure las cuentas financieras propias antes de habilitar operaciones monetarias"))
    from hospitality_suite.service_accounting import validate_configuration
    validate_configuration(prop)
    from hospitality_suite.item_configuration import validate_bindings
    validate_bindings(prop)
    required = ["cost_center", "warehouse", "receivable_account", "guarantee_account", "lodging_item"]
    missing = [f for f in required if not prop.get(f)]
    if missing:
        frappe.throw(frappe._("Complete la configuración contable antes de operar: ") + ", ".join(missing))
    from hospitality_suite.security import warehouse_allowed
    for field in ("warehouse", "laundry_warehouse"):
        if prop.get(field) and not warehouse_allowed(prop, prop.get(field)):
            frappe.throw(frappe._("El almacén configurado no pertenece a este establecimiento: ") + field)
    for field in ["cost_center", "warehouse", "receivable_account", "guarantee_account",
                  "cash_transfer_account", "tax_template"]:
        value = prop.get(field)
        if value:
            doc = frappe.get_doc(prop.meta.get_field(field).options, value)
            if (doc.company != prop.company or doc.get("is_group") or
                    doc.get("disabled")):
                frappe.throw(frappe._("Configuración contable de otra compañía o cuenta agrupadora: ") + field)
    rec = frappe.get_doc("Account", prop.receivable_account)
    guarantee = frappe.get_doc("Account", prop.guarantee_account)
    if rec.account_type != "Receivable" or guarantee.root_type != "Liability":
        frappe.throw(frappe._("Configure una cuenta por cobrar y un pasivo para garantías"))
    if rec.account_currency != prop.currency or guarantee.account_currency != prop.currency:
        frappe.throw(frappe._("Las cuentas de cliente y garantías deben usar la moneda del establecimiento"))
    if prop.cash_transfer_account:
        transfer = frappe.get_doc("Account", prop.cash_transfer_account)
        if (transfer.root_type != "Asset" or transfer.get("disabled") or
                transfer.account_currency != frappe.db.get_value(
                    "Company", prop.company, "default_currency")):
            frappe.throw(frappe._("La cuenta de traslado de efectivo debe ser un activo habilitado en moneda base"))
