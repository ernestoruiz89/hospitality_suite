import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hospitality_suite.schema import ROLES, SCOPED


def after_install():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc(dict(doctype="Role", role_name=role, desk_access=1)).insert()
    after_migrate()


def after_migrate():
    custom = []
    for name, target in [("hs_property", "HS Property"), ("hs_stay", "HS Stay"), ("hs_shift", "HS Shift")]:
        custom.append(dict(fieldname=name, label=name.replace("_", " ").title(), fieldtype="Link", options=target, insert_after="company", no_copy=1))
    create_custom_fields({dt: custom for dt in ["Sales Invoice", "Payment Entry", "Journal Entry", "Stock Entry"]})
    for dt in SCOPED:
        if dt != "HS Property":
            frappe.db.add_index(dt, ["property", "modified"], f"hs_scope_{dt.lower().replace(' ', '_')}")
    frappe.db.add_index("HS Allocation", ["property", "status", "starts_at", "ends_at"], "hs_allocation_interval")
    frappe.db.add_unique("HS Access", ["user", "property"], "hs_access_unique")
    frappe.db.add_unique("HS Room", ["property", "room_number"], "hs_room_unique")
    frappe.db.add_unique("HS Daily Close", ["property", "business_date"], "hs_close_unique")


def validate_financial_configuration(prop):
    required = ["cost_center", "warehouse", "receivable_account", "guarantee_account", "lodging_item"]
    missing = [f for f in required if not prop.get(f)]
    if missing or not prop.tax_policy_confirmed:
        frappe.throw("Complete la configuración contable y confirme la política tributaria antes de operar: " + ", ".join(missing))
    for field in ["cost_center", "warehouse", "receivable_account", "guarantee_account", "tax_template"]:
        value = prop.get(field)
        if value:
            doc = frappe.get_doc(prop.meta.get_field(field).options, value)
            if doc.company != prop.company or doc.get("is_group"):
                frappe.throw("Configuración contable de otra compañía o cuenta agrupadora: " + field)
    rec = frappe.get_doc("Account", prop.receivable_account)
    guarantee = frappe.get_doc("Account", prop.guarantee_account)
    if rec.account_type != "Receivable" or guarantee.root_type != "Liability":
        frappe.throw("Configure una cuenta por cobrar y un pasivo para garantías")
    if rec.account_currency != prop.currency or guarantee.account_currency != prop.currency:
        frappe.throw("Las cuentas de cliente y garantías deben usar la moneda del establecimiento")
