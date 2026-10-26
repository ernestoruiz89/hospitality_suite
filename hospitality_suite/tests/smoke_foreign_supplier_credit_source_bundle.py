"""Export a native ERPNext USD supplier credit from a rollback-only fixture."""

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import erp_fiscal_history, erp_to_pms_preflight
from hospitality_suite.pms_cutover_writer import _migration_posting
from hospitality_suite.service import operation


def run():
    if ("erpnext" not in frappe.get_installed_apps() or
            not frappe.local.site.startswith("hs-erp-smoke")):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex[:8].upper()
    savepoint = "hs_real_foreign_vendor_source"
    frappe.db.savepoint(savepoint)
    bundle_path = metadata_path = None
    try:
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type",
                "name": "Transit"}).insert(ignore_permissions=True)
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
                "must_be_whole_number": 1, "enabled": 1}).insert(
                    ignore_permissions=True)
        company = frappe.get_doc({"doctype": "Company",
            "company_name": "HS FX Vendor " + suffix,
            "abbr": "FV" + suffix, "country": "Nicaragua",
            "default_currency": "NIO"}).insert(ignore_permissions=True)
        year = frappe.utils.today()[:4]
        frappe.get_doc({"doctype": "Fiscal Year",
            "year": "HS FX Vendor FY " + suffix,
            "year_start_date": year + "-01-01",
            "year_end_date": year + "-12-31",
            "companies": [{"company": company.name}]}).insert(
                ignore_permissions=True)
        organization = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "HS FX Vendor " + suffix,
            "base_currency": "NIO", "active": 1}).insert(
                ignore_permissions=True)
        from frappe.model.naming import make_autoname

        prop = frappe.get_doc({"doctype": "HS Property",
            "name": make_autoname("ESTAB-.#####"),
            "property_name": "HS FX Vendor " + suffix,
            "company": company.name, "organization": organization.name,
            "currency": "NIO", "mode": "Hotel",
            "time_zone": "America/Managua", "close_time": "06:00:00",
            "business_date": frappe.utils.today()})
        prop.db_insert()
        ap_parent = frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Accounts Payable",
            "is_group": 1}, "name") or frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Current Liabilities",
            "is_group": 1}, "name")
        ap = frappe.get_doc({"doctype": "Account",
            "account_name": "HS FX USD AP " + suffix,
            "parent_account": ap_parent, "company": company.name,
            "account_type": "Payable", "account_currency": "USD",
            "is_group": 0}).insert(ignore_permissions=True)
        expense = frappe.db.get_value("Account", {
            "company": company.name, "root_type": "Expense",
            "is_group": 0}, "name")
        center = frappe.db.get_value("Cost Center", {
            "company": company.name, "is_group": 0}, "name")
        supplier = frappe.get_doc({"doctype": "Supplier",
            "supplier_name": "HS FX Vendor " + suffix,
            "supplier_group": frappe.db.get_value("Supplier Group", {
                "is_group": 0}, "name")}).insert(ignore_permissions=True)
        with operation(prop):
            frappe.get_doc({"doctype": "HS Supplier",
                "company": company.name, "property": prop.name,
                "supplier": supplier.name, "active": 1}).insert(
                    ignore_permissions=True)
        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc({"doctype": "Item Group",
                "item_group_name": "All Item Groups", "is_group": 1}).insert(
                    ignore_permissions=True)
        group = frappe.get_doc({"doctype": "Item Group",
            "item_group_name": "HS FX Vendor " + suffix,
            "parent_item_group": "All Item Groups",
            "is_group": 0}).insert(ignore_permissions=True)
        item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-FX-VENDOR-" + suffix,
            "item_name": "HS FX Vendor Service " + suffix,
            "is_stock_item": 0, "item_group": group.name,
            "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        frappe.db.set_single_value("HS Site Mode", "provider", "ERPNext")
        with _migration_posting():
            note = frappe.get_doc({"doctype": "Purchase Invoice",
                "company": company.name, "supplier": supplier.name,
                "hs_property": prop.name,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "is_return": 1, "currency": "USD",
                "conversion_rate": 36, "credit_to": ap.name,
                "items": [{"item_code": item.name, "qty": -1,
                           "rate": 50, "expense_account": expense,
                           "cost_center": center}]})
            note.set_missing_values()
            note.insert(ignore_permissions=True)
            note.submit()
        preflight = erp_to_pms_preflight.preflight()
        blockers = [row for row in preflight["blockers"]
                    if row.get("code") != "reverse_transfer_not_implemented"]
        hotel = next((row for row in preflight["properties"]
                      if row["property"] == prop.name), None)
        opened = next((row for row in hotel["open_payables"]
                       if row["name"] == note.name), None) if hotel else None
        if (blockers or not hotel or not opened or
                Decimal(opened["outstanding_amount"]) != -50 or
                Decimal(opened["base_outstanding_amount"]) != -1800):
            frappe.throw("El diagnóstico del crédito real no concilia: " +
                         frappe.as_json(blockers))
        exported = erp_fiscal_history.export_bundle(
            preflight["source_sha256"])
        bundle_path = Path(frappe.get_site_path("private", "files",
                                               exported["file_name"]))
        with erp_fiscal_history.ZipFile(bundle_path) as archive:
            manifest, inventory = erp_fiscal_history._manifest(archive,
                preflight["source_sha256"], exported["manifest_sha256"])
        if (manifest["documents"] or
                inventory["properties"][0]["open_payables"][0]["name"] !=
                    note.name):
            frappe.throw("El paquete ERPNext omitió el crédito de proveedor")
        result = {"bundle_file": exported["file_name"],
            "source_sha256": preflight["source_sha256"],
            "manifest_sha256": exported["manifest_sha256"],
            "source_property": prop.name, "source_note": note.name,
            "source_ap": ap.name, "source_supplier": supplier.name,
            "base_currency": "NIO", "credit_currency": "USD",
            "principal": "50.00", "base_amount": "1800.00"}
        metadata_path = Path(frappe.get_site_path("private", "files",
            "hs-real-fx-vendor-" + uuid4().hex + ".json"))
        metadata_path.write_text(json.dumps(result, sort_keys=True),
                                 encoding="utf-8")
        return {**result, "metadata_file": metadata_path.name}
    except Exception:
        if bundle_path is not None:
            bundle_path.unlink(missing_ok=True)
        if metadata_path is not None:
            metadata_path.unlink(missing_ok=True)
        raise
    finally:
        frappe.db.rollback(save_point=savepoint)
