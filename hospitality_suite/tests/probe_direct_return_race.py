"""Two-connection historical counter-sale races on a disposable ERPNext clone."""

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api, cashier
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider
from hospitality_suite.tests.financial_race import race_command
from hospitality_suite.tests.probe_persistent_direct_return_cutover import SITE, SALE


SITES = Path("/home/frappe/frappe-bench/sites")


def _audit_count(prop_name, service_name, action):
    return frappe.db.count("HS Audit Event", {"property": prop_name,
        "source_doctype": "HS Service Request", "source_name": service_name,
        "action": action})


def run():
    if (frappe.local.site != SITE or
            Path(frappe.local.sites_path).resolve() != SITES or
            provider() != "erpnext"):
        frappe.throw("Use only the isolated historical direct-return site")
    frappe.set_user("Administrator")
    sale = frappe.get_doc("HS Service Request", SALE)
    if (sale.status != "Delivered" or sale.credit_note or
            sale.erp_return_refund or not sale.erp_cutover_snapshot):
        frappe.throw("The isolated sale must be ready for a new return")
    outcomes = []
    for same_key in (True, False):
        tag = uuid4().hex[:12]
        sale.reload()
        old_history = (frappe.parse_json(sale.erp_return_corrections)
            if sale.erp_return_corrections else [])
        prop = frappe.get_doc("HS Property", sale.property)
        method = frappe.db.get_value("HS Payment", {
            "service": sale.name, "kind": "Payment", "status": "Posted"},
            "method")
        shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
            "company": prop.company, "status": "Open",
            "currency": sale.currency}, pluck="name", limit_page_length=0)
        if not method or len(shifts) != 1:
            raise AssertionError("The disposable clone lost its cash setup")
        request = {"service": sale.name, "modified": str(sale.modified),
            "method": method, "shift": shifts[0],
            "reference": "QA-DIRECT-RETURN-RACE-" + tag,
            "reason": "Ensayo concurrente de devolución histórica"}
        quote = api.erp_historical_direct_sale_return_quote(
            prop.name, canonical(request))
        before_return = _audit_count(prop.name, sale.name,
            "erp_historical_direct_sale_return")
        frappe.db.commit()
        returned = race_command(SITE, SITES, prop.name,
            "erp_historical_direct_sale_return",
            {**request, "acceptance": quote["acceptance"]},
            "qa-direct-return-race-" + tag, same_key=same_key)
        frappe.db.rollback()
        sale.reload()
        if (sale.status != "Returned" or
                sale.credit_note != returned["credit_note"] or
                sale.erp_return_refund != returned["refund"] or
                cashier.expected(frappe.get_doc("HS Shift", shifts[0]))[
                    sale.currency] != "92.00" or
                _audit_count(prop.name, sale.name,
                    "erp_historical_direct_sale_return") !=
                    before_return + 1):
            raise AssertionError("The concurrent return did not reconcile")
        correction = {"service": sale.name, "modified": str(sale.modified),
            "reason": "Corrección concurrente de venta histórica " + tag}
        reviewed = api.erp_historical_direct_sale_return_reversal_quote(
            prop.name, canonical(correction))
        before_correction = _audit_count(prop.name, sale.name,
            "erp_historical_direct_sale_return_reversal")
        frappe.db.commit()
        corrected = race_command(SITE, SITES, prop.name,
            "erp_historical_direct_sale_return_reversal",
            {**correction, "acceptance": reviewed["acceptance"]},
            "qa-direct-correction-race-" + tag, same_key=same_key)
        frappe.db.rollback()
        sale.reload()
        refund = frappe.get_doc("HS Payment", returned["refund"])
        history = frappe.parse_json(sale.erp_return_corrections)
        if (sale.status != "Delivered" or sale.credit_note or
                sale.erp_return_refund or sale.return_stock_entry or
                len(history) != len(old_history) + 1 or
                history[:-1] != old_history or
                history[-1]["credit_note"] != returned["credit_note"] or
                sha256(sale.erp_return_corrections.encode()).hexdigest() !=
                    sale.erp_return_corrections_sha256 or
                frappe.db.get_value("Sales Invoice", returned["credit_note"],
                    "docstatus") != 2 or
                refund.status != "Cancelled" or
                frappe.db.get_value("Payment Entry", refund.payment_entry,
                    "docstatus") != 2 or
                (returned["stock_entry"] and frappe.db.get_value(
                    "Stock Entry", returned["stock_entry"], "docstatus") != 2) or
                cashier.expected(frappe.get_doc("HS Shift", shifts[0]))[
                    sale.currency] != "100.00" or
                _audit_count(prop.name, sale.name,
                    "erp_historical_direct_sale_return_reversal") !=
                    before_correction + 1 or
                corrected["credit_note"] != returned["credit_note"] or
                Decimal(str(sale.amount)) != 8):
            raise AssertionError("The concurrent correction did not reconcile")
        outcomes.append({"same_key": same_key,
            "return_second": "same_result" if same_key else "rejected",
            "correction_second": "same_result" if same_key else "rejected",
            "correction_count": len(history), "cash_expected": "100.00"})
    return {"independent_session_races_verified": True,
        "site": SITE, "outcomes": outcomes}
