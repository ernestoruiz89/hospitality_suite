"""Inspect or export a native ERPNext USD customer advance in a rollback-only fixture."""

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import erp_fiscal_history, erp_to_pms_preflight
from hospitality_suite.erp_to_pms_preflight import _deposits
from hospitality_suite.pms_cutover_writer import _migration_posting


def run(export_bundle=False):
    if ("erpnext" not in frappe.get_installed_apps() or
            not frappe.local.site.startswith("hs-erp-smoke")):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex[:8].upper()
    marker = "hs_foreign_advance_source_probe"
    frappe.db.savepoint(marker)
    bundle_path = metadata_path = None
    try:
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type",
                "name": "Transit"}).insert(ignore_permissions=True)
        company = frappe.get_doc({"doctype": "Company",
            "company_name": "HS FX Advance " + suffix,
            "abbr": "FA" + suffix, "country": "Nicaragua",
            "default_currency": "NIO"}).insert(ignore_permissions=True)
        year = frappe.utils.today()[:4]
        frappe.get_doc({"doctype": "Fiscal Year",
            "year": "HS FX Advance FY " + suffix,
            "year_start_date": year + "-01-01",
            "year_end_date": year + "-12-31",
            "companies": [{"company": company.name}]}).insert(
                ignore_permissions=True)
        from frappe.model.naming import make_autoname

        prop = frappe.get_doc({"doctype": "HS Property",
            "name": make_autoname("ESTAB-.#####"),
            "property_name": "HS FX Advance " + suffix,
            "company": company.name, "currency": "NIO", "mode": "Hotel",
            "time_zone": "America/Managua", "close_time": "06:00:00",
            "business_date": frappe.utils.today()})
        prop.db_insert()
        ar_parent = frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Accounts Receivable",
            "is_group": 1}, "name") or frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Current Assets",
            "is_group": 1}, "name")
        ar = frappe.get_doc({"doctype": "Account",
            "account_name": "HS FX Advance AR " + suffix,
            "parent_account": ar_parent, "company": company.name,
            "account_type": "Receivable", "account_currency": "USD",
            "is_group": 0}).insert(ignore_permissions=True)
        bank_parent = frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Bank Accounts",
            "is_group": 1}, "name")
        bank = frappe.get_doc({"doctype": "Account",
            "account_name": "HS FX Advance Bank " + suffix,
            "parent_account": bank_parent, "company": company.name,
            "account_type": "Bank", "account_currency": "USD",
            "is_group": 0}).insert(ignore_permissions=True)
        customer = frappe.get_doc({"doctype": "Customer",
            "customer_name": "HS FX Advance Customer " + suffix,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_value("Customer Group", {
                "is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {
                "is_group": 0}, "name")}).insert(ignore_permissions=True)
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
                "must_be_whole_number": 1, "enabled": 1}).insert(
                    ignore_permissions=True)
        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc({"doctype": "Item Group",
                "item_group_name": "All Item Groups", "is_group": 1}).insert(
                    ignore_permissions=True)
        group = frappe.get_doc({"doctype": "Item Group",
            "item_group_name": "HS FX Advance " + suffix,
            "parent_item_group": "All Item Groups",
            "is_group": 0}).insert(ignore_permissions=True)
        item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-FX-ADV-" + suffix,
            "item_name": "HS FX Advance Service " + suffix,
            "is_stock_item": 0, "item_group": group.name,
            "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        prices = frappe.get_doc({"doctype": "Price List",
            "price_list_name": "HS FX Advance USD " + suffix,
            "enabled": 1, "selling": 1, "currency": "USD"}).insert(
                ignore_permissions=True)
        income = frappe.db.get_value("Account", {
            "company": company.name, "root_type": "Income",
            "is_group": 0}, "name")
        center = frappe.db.get_value("Cost Center", {
            "company": company.name, "is_group": 0}, "name")
        frappe.db.set_single_value("HS Site Mode", "provider", "ERPNext")
        with _migration_posting():
            invoice = frappe.get_doc({"doctype": "Sales Invoice",
                "company": company.name, "customer": customer.name,
                "hs_property": prop.name,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "USD", "conversion_rate": 36,
                "debit_to": ar.name,
                "selling_price_list": prices.name,
                "price_list_currency": "USD", "plc_conversion_rate": 1,
                "items": [{"item_code": item.name, "qty": 1,
                           "rate": 20, "income_account": income,
                           "cost_center": center}]})
            invoice.set_missing_values()
            invoice.insert(ignore_permissions=True)
            invoice.submit()
            payment = frappe.get_doc({"doctype": "Payment Entry",
                "company": company.name, "hs_property": prop.name,
                "posting_date": frappe.utils.today(),
                "payment_type": "Receive", "party_type": "Customer",
                "party": customer.name, "paid_from": ar.name,
                "paid_to": bank.name, "paid_amount": 50,
                "received_amount": 50, "source_exchange_rate": 36,
                "target_exchange_rate": 36,
                "references": [{"reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name, "allocated_amount": 20}],
                "reference_no": "FX-ADV-" + suffix,
                "reference_date": frappe.utils.today()})
            payment.set_missing_values()
            payment.insert(ignore_permissions=True)
            payment.submit()
        ple = frappe.get_all("Payment Ledger Entry",
            filters={"company": company.name, "delinked": 0,
                     "voucher_no": payment.name},
            fields=["voucher_type", "voucher_no", "against_voucher_type",
                    "against_voucher_no", "account", "party_type", "party",
                    "account_currency", "amount", "amount_in_account_currency"],
            limit_page_length=0)
        blockers = []
        deposits = _deposits(prop, blockers)
        advance = next((row for row in deposits["customer_credits"]
                        if row["voucher"] == payment.name), None)
        if (not advance or Decimal(str(payment.unallocated_amount)) != 30 or
                Decimal(advance["available"]) != 30 or
                Decimal(advance["base_available"]) != 1080 or
                blockers or not ple):
            frappe.throw("El anticipo nativo no conserva ambos saldos: " +
                         frappe.as_json(blockers))
        review = erp_to_pms_preflight.preflight()
        hotel = next((row for row in review["properties"]
                      if row["property"] == prop.name), None)
        full_advance = next((row for row in hotel["deposits"]["customer_credits"]
                             if row["voucher"] == payment.name), None) if hotel else None
        unexpected = [row for row in review["blockers"]
                      if row.get("code") != "reverse_transfer_not_implemented"]
        if (unexpected or not full_advance or
                Decimal(full_advance["available"]) != 30 or
                Decimal(full_advance["base_available"]) != 1080):
            frappe.throw("El diagnóstico completo del anticipo no concilia: " +
                         frappe.as_json(unexpected))
        frappe.db.savepoint("hs_foreign_advance_ledger_tamper")
        try:
            frappe.db.set_value("Payment Entry", payment.name,
                "unallocated_amount", 31, update_modified=False)
            altered_blockers = []
            _deposits(prop, altered_blockers)
            if not any(row["code"] == "customer_credit_payment_ledger_mismatch"
                       for row in altered_blockers):
                frappe.throw("El inventario aceptó un saldo distinto al libro de pagos")
        finally:
            frappe.db.rollback(save_point="hs_foreign_advance_ledger_tamper")
        result = {"payment": payment.name,
            "source_property": prop.name,
            "source_ar": ar.name, "source_customer": customer.name,
            "source_invoice": invoice.name,
            "currency": payment.party_account_currency,
            "paid_amount": str(payment.paid_amount),
            "unallocated_amount": str(payment.unallocated_amount),
            "base_paid_amount": str(payment.base_paid_amount),
            "advance": advance, "payment_ledger": [dict(row) for row in ple],
            "blockers": blockers, "preflight_verified": True,
            "rolled_back": True}
        if export_bundle:
            exported = erp_fiscal_history.export_bundle(review["source_sha256"])
            bundle_path = Path(frappe.get_site_path("private", "files",
                                                   exported["file_name"]))
            with erp_fiscal_history.ZipFile(bundle_path) as archive:
                manifest, inventory = erp_fiscal_history._manifest(archive,
                    review["source_sha256"], exported["manifest_sha256"])
            source = inventory["properties"][0]
            if (len(manifest["documents"]) != 1 or
                    source["deposits"]["customer_credits"][0]["voucher"] !=
                        payment.name):
                frappe.throw("El paquete no conservó el anticipo y su factura")
            result.update(bundle_file=exported["file_name"],
                source_sha256=review["source_sha256"],
                manifest_sha256=exported["manifest_sha256"])
            metadata_path = Path(frappe.get_site_path("private", "files",
                "hs-real-fx-advance-" + uuid4().hex + ".json"))
            metadata_path.write_text(json.dumps(result, sort_keys=True),
                                     encoding="utf-8")
            result["metadata_file"] = metadata_path.name
        return result
    except Exception:
        if bundle_path is not None:
            bundle_path.unlink(missing_ok=True)
        if metadata_path is not None:
            metadata_path.unlink(missing_ok=True)
        raise
    finally:
        frappe.db.rollback(save_point=marker)
