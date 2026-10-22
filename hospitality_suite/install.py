import frappe
import json
from pathlib import Path
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hospitality_suite.schema import ROLES, SCOPED,STANDARD_SCOPED


def after_install():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc(dict(doctype="Role", role_name=role, desk_access=1)).insert()
    after_migrate()


def after_migrate():
    custom = []
    for name, target, label in [("hs_property", "HS Property", "Establecimiento de alojamiento"), ("hs_stay", "HS Stay", "Estancia de alojamiento"), ("hs_shift", "HS Shift", "Turno de caja"), ("hs_folio", "HS Folio", "Cuenta de estancia"), ("hs_booking", "HS Booking", "Reserva de alojamiento")]:
        custom.append(dict(fieldname=name, label=label, fieldtype="Link", options=target, insert_after="company", no_copy=1,print_hide=1))
    create_custom_fields({dt: custom for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)})
    create_custom_fields({dt:[dict(fieldname="hs_correction_reason",label="Motivo de corrección de alojamiento",fieldtype="Small Text",allow_on_submit=1,print_hide=1)] for dt in STANDARD_SCOPED if frappe.db.exists("DocType",dt)})
    create_custom_fields({"Sales Invoice Item": [dict(fieldname="hs_charge", label="Cargo de estancia", fieldtype="Link", options="HS Charge", no_copy=1,print_hide=1)]})
    create_custom_fields({"Sales Invoice Item":[dict(fieldname="hs_charge_sources",label="Cargos que componen la línea",fieldtype="Code",options="JSON",read_only=1,no_copy=1,print_hide=1)]})
    create_custom_fields({"Warehouse":[dict(fieldname="hs_property",label="Establecimiento de alojamiento",fieldtype="Link",options="HS Property")]})
    create_custom_fields({"Asset":[dict(fieldname="hs_property",label="Establecimiento de alojamiento",fieldtype="Link",options="HS Property",allow_on_submit=1,print_hide=1)]})
    create_custom_fields({"Stock Entry":[dict(fieldname="hs_stock_purpose",label="Uso operativo",fieldtype="Select",options="\nSale\nCleaning\nWaste\nLinen Replacement\nMaintenance\nTransfer\nAdjustment\nLaundry",print_hide=1)]})
    from frappe.permissions import add_permission
    for dt in ("Account","Item","Company","Cost Center","Warehouse","Mode of Payment","Price List","Sales Taxes and Charges Template","Customer","Supplier","Currency"):
        for role in ("HS Administrator","HS Manager","HS Supervisor","HS Receptionist","HS Cashier","HS Accountant"):
            if frappe.db.exists("Role",role) and not frappe.db.exists("Custom DocPerm",{"parent":dt,"role":role}):
                add_permission(dt,role,0,"select")
    for role in ("HS Administrator","HS Manager","HS Accountant","HS Auditor"):
        if frappe.db.exists("Role",role) and not frappe.db.exists("Custom DocPerm",{"parent":"GL Entry","role":role}):
            add_permission("GL Entry",role,0,"read")
    for dt in ("Sales Invoice", "Payment Entry", "Journal Entry", "Stock Entry","Stock Reconciliation","Purchase Order","Purchase Receipt","Purchase Invoice"):
        for role in ("HS Administrator", "HS Manager", "HS Supervisor", "HS Receptionist", "HS Cashier", "HS Accountant", "HS Auditor"):
            if frappe.db.exists("Role", role) and not frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
                add_permission(dt, role, 0, "read")
    for dt in SCOPED:
        if dt != "HS Property":
            frappe.db.add_index(dt, ["property", "modified"], f"hs_scope_{dt.lower().replace(' ', '_')}")
    frappe.db.add_index("HS Allocation", ["property", "status", "starts_at", "ends_at"], "hs_allocation_interval")
    frappe.db.add_unique("HS Access", ["user", "property"], "hs_access_unique")
    frappe.db.add_unique("HS Room", ["property", "room_number"], "hs_room_unique")
    frappe.db.add_unique("HS Daily Close", ["property", "business_date"], "hs_close_unique")
    frappe.db.add_unique("HS Billing Party",["property","customer"],"hs_billing_party_unique")
    frappe.db.add_unique("HS Supplier",["property","supplier"],"hs_supplier_unique")
    frappe.db.add_unique("HS Stock Policy",["property","item","warehouse"],"hs_stock_policy_unique")
    frappe.db.add_unique("HS Equipment",["property","equipment_code"],"hs_equipment_unique")
    frappe.db.add_index("HS Guest Ticket", ["property", "status", "due_at"], "hs_ticket_queue")
    frappe.db.add_index("HS Ticket Event", ["ticket", "occurred_at"], "hs_ticket_timeline")
    sync_print_formats()


def sync_print_formats():
    """Refresh app-owned formats by content, including a site's future timestamp."""
    from frappe.modules.import_file import import_file_by_path
    folder=Path(frappe.get_app_path("hospitality_suite","hospitality_suite","print_format"))
    for path in sorted(folder.glob('*/*.json')):
        source=json.loads(path.read_text(encoding='utf-8'))
        if frappe.db.exists('Print Format',source['name']):
            current=frappe.get_doc('Print Format',source['name'])
            if current.standard!='Yes' or current.module!='Hospitality Suite':
                continue
            if all(current.get(field)==source.get(field) for field in ('doc_type','html','css','print_format_type','custom_format')):
                continue
        import_file_by_path(str(path),force=True,ignore_version=True)
        frappe.clear_document_cache('Print Format',source['name'])


def validate_financial_configuration(prop):
    from hospitality_suite.service_accounting import validate_configuration
    validate_configuration(prop)
    from hospitality_suite.item_configuration import validate_bindings
    validate_bindings(prop)
    required = ["cost_center", "warehouse", "receivable_account", "guarantee_account", "lodging_item"]
    missing = [f for f in required if not prop.get(f)]
    if missing or not prop.tax_policy_confirmed:
        frappe.throw(frappe._("Complete la configuración contable y confirme la política tributaria antes de operar: ") + ", ".join(missing))
    for field in ["cost_center", "warehouse", "receivable_account", "guarantee_account", "tax_template"]:
        value = prop.get(field)
        if value:
            doc = frappe.get_doc(prop.meta.get_field(field).options, value)
            if doc.company != prop.company or doc.get("is_group"):
                frappe.throw(frappe._("Configuración contable de otra compañía o cuenta agrupadora: ") + field)
    rec = frappe.get_doc("Account", prop.receivable_account)
    guarantee = frappe.get_doc("Account", prop.guarantee_account)
    if rec.account_type != "Receivable" or guarantee.root_type != "Liability":
        frappe.throw(frappe._("Configure una cuenta por cobrar y un pasivo para garantías"))
    if rec.account_currency != prop.currency or guarantee.account_currency != prop.currency:
        frappe.throw(frappe._("Las cuentas de cliente y garantías deben usar la moneda del establecimiento"))
