"""Persistent ERPNext source fixture on one isolated smoke clone only."""

import frappe

from hospitality_suite import (erp_fiscal_history, erp_to_pms_freeze,
                               erp_to_pms_preflight, pms_cutover_cli, setup)
from hospitality_suite.pms_cutover_writer import _migration_posting


SITE = "hs-erp-smoke-reverse.local"
COMPANY = "HS Reverse Source 2026"
PROPERTY = "Hotel ERP fuente inversa"
INVOICE_MARKER = "HS reverse real source lodging 2026"
BACKUP_FILE = "reverse-real-source-backup-20261026.json"


def seed():
    if frappe.local.site != SITE or "erpnext" not in frappe.get_installed_apps():
        frappe.throw("Use únicamente el clon ERPNext aislado para el corte inverso")
    frappe.set_user("Administrator")
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
            ignore_permissions=True)
    if not frappe.db.exists("Company", COMPANY):
        frappe.get_doc({"doctype": "Company", "company_name": COMPANY,
            "abbr": "HRS26", "country": "Nicaragua",
            "default_currency": "NIO",
            "enable_perpetual_inventory": 1}).insert(ignore_permissions=True)
    existing = frappe.db.get_value("HS Property", {"property_name": PROPERTY,
        "company": COMPANY}, "name")
    if existing:
        prop = frappe.get_doc("HS Property", existing)
    else:
        created = setup.create_property({"property_name": PROPERTY,
            "company": COMPANY, "currency": "NIO", "mode": "Hotel",
            "time_zone": "America/Managua", "close_time": "06:00"},
            "reverse-real-source-property")
        prop = frappe.get_doc("HS Property", created["property"])
    if frappe.db.count("HS Property") != 1:
        frappe.throw("El clon ERPNext no está aislado a un establecimiento")
    source = erp_to_pms_preflight.preflight()
    frappe.db.commit()
    return {"site": SITE, "company": COMPANY, "property": prop.name,
        "provider": source["provider"], "source_sha256": source["source_sha256"],
        "blockers": source["blockers"],
        "company_gl_coverage": source["gl_coverage"]}


def seed_invoice():
    if frappe.local.site != SITE or "erpnext" not in frappe.get_installed_apps():
        frappe.throw("Use únicamente el clon ERPNext aislado para el corte inverso")
    frappe.set_user("Administrator")
    prop_name = frappe.db.get_value("HS Property", {"property_name": PROPERTY,
        "company": COMPANY}, "name")
    if not prop_name or frappe.db.count("HS Property") != 1:
        frappe.throw("Cree primero el establecimiento ERPNext aislado")
    existing = frappe.db.get_value("Sales Invoice", {"hs_property": prop_name,
        "remarks": INVOICE_MARKER, "docstatus": 1}, "name")
    if existing:
        source = erp_to_pms_preflight.preflight()
        return {"invoice": existing, "source_sha256": source["source_sha256"],
            "blockers": source["blockers"]}
    year = frappe.utils.today()[:4]
    if not frappe.db.exists("Fiscal Year", "HS Reverse Source FY " + year):
        frappe.get_doc({"doctype": "Fiscal Year",
            "year": "HS Reverse Source FY " + year,
            "year_start_date": year + "-01-01",
            "year_end_date": year + "-12-31",
            "companies": [{"company": COMPANY}]}).insert(ignore_permissions=True)
    if not frappe.db.exists("UOM", "Nos"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
            "must_be_whole_number": 1, "enabled": 1}).insert(ignore_permissions=True)
    if not frappe.db.exists("Item Group", "All Item Groups"):
        frappe.get_doc({"doctype": "Item Group",
            "item_group_name": "All Item Groups", "is_group": 1}).insert(
            ignore_permissions=True)
    group_name = "HS Reverse Source Services"
    if not frappe.db.exists("Item Group", group_name):
        frappe.get_doc({"doctype": "Item Group",
            "item_group_name": group_name, "is_group": 0,
            "parent_item_group": "All Item Groups"}).insert(ignore_permissions=True)
    item_code = "HS-REVERSE-LODGING-2026"
    if not frappe.db.exists("Item", item_code):
        frappe.get_doc({"doctype": "Item", "item_code": item_code,
            "item_name": "Alojamiento fuente ERPNext", "is_stock_item": 0,
            "item_group": group_name, "stock_uom": "Nos", "uom": "Nos"}).insert(
            ignore_permissions=True)
    customer_name = "HS Reverse Source Guest"
    customer = frappe.db.get_value("Customer", {"customer_name": customer_name},
                                   "name")
    if not customer:
        customer = frappe.get_doc({"doctype": "Customer",
            "customer_name": customer_name, "customer_type": "Individual",
            "customer_group": frappe.db.get_value("Customer Group",
                {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0},
                "name")}).insert(ignore_permissions=True).name
    price_list = "HS Reverse Source NIO"
    if not frappe.db.exists("Price List", price_list):
        frappe.get_doc({"doctype": "Price List",
            "price_list_name": price_list, "enabled": 1,
            "selling": 1, "currency": "NIO"}).insert(ignore_permissions=True)
    ar = frappe.db.get_value("Account", {"company": COMPANY,
        "account_type": "Receivable", "is_group": 0}, "name")
    income = frappe.db.get_value("Account", {"company": COMPANY,
        "root_type": "Income", "is_group": 0}, "name")
    center = frappe.db.get_value("Cost Center", {"company": COMPANY,
        "is_group": 0}, "name")
    if not all((ar, income, center)):
        frappe.throw("La compañía ERPNext no tiene cuentas de venta completas")
    prop = frappe.get_doc("HS Property", prop_name)
    prop.update({"cost_center": center, "receivable_account": ar,
                 "income_account": income, "lodging_item": item_code,
                 "price_list": price_list})
    prop.save()
    with _migration_posting():
        invoice = frappe.get_doc({"doctype": "Sales Invoice",
            "company": COMPANY, "customer": customer,
            "hs_property": prop.name,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": "NIO", "conversion_rate": 1,
            "debit_to": ar, "selling_price_list": price_list,
            "price_list_currency": "NIO", "plc_conversion_rate": 1,
            "remarks": INVOICE_MARKER,
            "items": [{"item_code": item_code, "qty": 1,
                "rate": 100, "income_account": income,
                "cost_center": center}]})
        invoice.set_missing_values()
        invoice.insert(ignore_permissions=True)
        invoice.submit()
    source = erp_to_pms_preflight.preflight()
    frappe.db.commit()
    return {"invoice": invoice.name, "outstanding": str(invoice.outstanding_amount),
        "gl_entries": frappe.db.count("GL Entry", {"voucher_type": "Sales Invoice",
            "voucher_no": invoice.name, "is_cancelled": 0}),
        "source_sha256": source["source_sha256"],
        "blockers": source["blockers"],
        "company_gl_coverage": source["gl_coverage"]}


def export_real_bundle():
    if frappe.local.site != SITE:
        frappe.throw("Use únicamente el clon ERPNext aislado")
    frappe.set_user("Administrator")
    source = erp_to_pms_preflight.preflight()
    if source["blockers"] or not frappe.db.exists("Sales Invoice", {
            "hs_property": source["properties"][0]["property"],
            "remarks": INVOICE_MARKER, "docstatus": 1}):
        frappe.throw("La factura ERPNext real aún no está lista para exportar")
    result = erp_fiscal_history.export_bundle(source["source_sha256"])
    return {"source_sha256": source["source_sha256"], **result}


def mapping_requirements():
    if frappe.local.site != SITE:
        frappe.throw("Use únicamente el clon ERPNext aislado")
    frappe.set_user("Administrator")
    source = erp_to_pms_preflight.preflight()
    if source["blockers"] or len(source["properties"]) != 1:
        frappe.throw("La fuente no está lista para mapear")
    hotel = source["properties"][0]
    requirements = hotel["mapping_requirements"]
    return {"property": hotel["property"], "business_date": hotel["business_date"],
        "source_sha256": source["source_sha256"],
        "requirements": requirements,
        "open_receivables": hotel["open_receivables"]}


def prepare_backup_and_freeze():
    if frappe.local.site != SITE or "erpnext" not in frappe.get_installed_apps():
        frappe.throw("Use únicamente el clon ERPNext aislado")
    frappe.set_user("Administrator")
    source = erp_to_pms_preflight.preflight()
    if source["blockers"]:
        frappe.throw("La fuente conserva bloqueos")
    prepared = pms_cutover_cli.prepare_backup_file(BACKUP_FILE)
    frozen = erp_to_pms_freeze.export_frozen_file(BACKUP_FILE,
        source["source_sha256"])
    return {"backup": prepared, "freeze": frozen}
