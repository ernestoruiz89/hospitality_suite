"""Inspect the committed Day Pass cutover on its disposable ERPNext site."""

from decimal import Decimal
from hashlib import sha256

import frappe

from hospitality_suite import api, cashier
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


SITE = "hs-erp-smoke-persistent.local"
REFERENCE = "HS-PERSISTENT-DAY-PASS-20261026"


def inspect():
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated persistent cutover site")
    frappe.set_user("Administrator")
    runs = frappe.get_all("HS Cutover Run", fields=["name", "result_json",
        "source_sha256", "plan_sha256", "link_sha256",
        "migration_reference"], limit_page_length=0)
    passes = frappe.get_all("HS Day Pass", fields=["name", "status",
        "pms_receivable", "erp_opening_invoice", "erp_opening_snapshot",
        "erp_opening_sha256", "erp_return_credit_note", "erp_return_refund",
        "sales_invoice", "payment"], limit_page_length=0)
    if provider() != "erpnext" or len(runs) != 1 or len(passes) != 1:
        frappe.throw("The persistent cutover has an unexpected authority or count")
    receipt, day_pass = runs[0], passes[0]
    if receipt.migration_reference != REFERENCE:
        frappe.throw("The persistent cutover receipt changed")
    result = frappe.parse_json(receipt.result_json)
    proof = frappe.parse_json(day_pass.erp_opening_snapshot)
    if (not result.get("cutover_performed") or
            not result.get("backup", {}).get("sha256") or
            proof.get("source") != day_pass.name or
            proof.get("opening_invoice") != day_pass.erp_opening_invoice or
            sha256(day_pass.erp_opening_snapshot.encode()).hexdigest() !=
                day_pass.erp_opening_sha256 or
            day_pass.sales_invoice or day_pass.payment or
            proof["accepted_sale"]["total_amount"] != "16" or
            proof["source_fiscal"]["credited_amount"] != "4" or
            proof["source_financial"]["outstanding_amount"] != "6" or
            len(proof["source_fiscal"]["credits"]) != 1):
        frappe.throw("The committed Day Pass proof does not reconcile")
    opening = frappe.get_doc("Sales Invoice", day_pass.erp_opening_invoice)
    gl = frappe.get_all("GL Entry", filters={"voucher_type": "Sales Invoice",
        "voucher_no": opening.name, "is_cancelled": 0},
        fields=["account", "debit", "credit"], limit_page_length=0)
    if (opening.docstatus != 1 or opening.is_return or
            Decimal(str(opening.grand_total)) != 6 or
            Decimal(str(opening.outstanding_amount)) !=
                (0 if day_pass.status == "Cancelled" else 6) or
            sum(Decimal(str(row.debit)) for row in gl) != 6 or
            sum(Decimal(str(row.credit)) for row in gl) != 6):
        frappe.throw("The committed opening invoice does not reconcile")
    if day_pass.status == "Cancelled":
        if not day_pass.erp_return_credit_note or not day_pass.erp_return_refund:
            frappe.throw("The persistent return lost its financial links")
    elif day_pass.status != "Issued" or day_pass.erp_return_credit_note:
        frappe.throw("The transferred access has an unexpected state")
    return {"persistent_cutover_verified": True,
        "provider": provider(), "cutover_run": receipt.name,
        "day_pass": day_pass.name, "status": day_pass.status,
        "opening_invoice": opening.name,
        "opening_outstanding": str(opening.outstanding_amount),
        "source_fiscal_invoice": proof["source_fiscal"]["invoice"]["document_number"],
        "source_fiscal_credit": proof["source_fiscal"]["credits"][0]["document_number"],
        "backup_sha256": result["backup"]["sha256"]}


def return_access():
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated persistent cutover site")
    before = inspect()
    if before["status"] != "Issued":
        frappe.throw("The isolated Day Pass has already been returned")
    day_pass = frappe.get_doc("HS Day Pass", before["day_pass"])
    prop = frappe.get_doc("HS Property", day_pass.property)
    method = frappe.db.get_value("HS Payment Method", {
        "property": prop.name, "company": prop.company,
        "is_cash": 1, "currency": prop.currency}, "name")
    if not method:
        frappe.throw("The migrated cash method is missing")
    shift = api.execute(prop.name, "open_shift",
        "persistent-day-pass-return-shift",
        {"currency": prop.currency, "opening_amount": "100"})
    request = {"day_pass": day_pass.name,
        "modified": str(day_pass.modified), "method": method,
        "shift": shift["shift"], "amount": "",
        "reference": "PERSISTENT-DAY-PASS-RETURN",
        "reason": "Ensayo persistente de devolución histórica"}
    quote = api.erp_historical_day_pass_return_quote(prop.name,
        canonical(request))
    if (Decimal(quote["credit_total"]) != 12 or
            Decimal(quote["opening_applied"]) != 6 or
            Decimal(quote["refund_base"]) != 6):
        frappe.throw("The persistent return quote does not reconcile")
    accepted = {**request, "amount": quote["refund_amount"],
        "acceptance": quote["acceptance"]}
    returned = api.execute(prop.name, "erp_historical_day_pass_return",
        "persistent-day-pass-return", accepted)
    if api.execute(prop.name, "erp_historical_day_pass_return",
            "persistent-day-pass-return", accepted) != returned:
        frappe.throw("Retrying the persistent return produced a second result")
    credit = frappe.get_doc("Sales Invoice", returned["credit_note"])
    refund = frappe.get_doc("HS Payment", returned["refund"])
    payment = frappe.get_doc("Payment Entry", refund.payment_entry)
    expected = cashier.expected(frappe.get_doc("HS Shift", shift["shift"]))
    fiscal = frappe.parse_json(day_pass.erp_opening_snapshot)[
        "source_fiscal"]["invoice"]
    if (credit.docstatus != 1 or Decimal(str(credit.grand_total)) != -12 or
            Decimal(str(credit.outstanding_amount)) != 0 or
            payment.docstatus != 1 or
            payment.references[0].reference_name != credit.name or
            Decimal(str(refund.base_amount)) != 6 or
            expected[prop.currency] != "94.00" or
            credit.name not in frappe.get_print("Sales Invoice", credit.name) or
            fiscal["document_number"] not in frappe.get_print(
                "HS PMS Fiscal Document", fiscal["document"],
                print_format="HS Documento fiscal PMS")):
        frappe.throw("The persistent return did not reconcile or print")
    frappe.db.commit()
    after = inspect()
    if after["status"] != "Cancelled" or after["opening_outstanding"] != "0.0":
        frappe.throw("The committed Day Pass still appears active")
    return {"persistent_return_verified": True,
        "cutover_run": after["cutover_run"],
        "credit_note": credit.name, "refund": refund.name,
        "shift_expected": expected[prop.currency],
        "same_result_on_retry": True}
