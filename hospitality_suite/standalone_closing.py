"""Immutable, property-scoped business-day close for the PMS ledger."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from hospitality_suite.security import document, require
from hospitality_suite.service import audit, canonical, current_all, insert
from hospitality_suite.standalone_accounting import require_pms, trial_balance


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _records(doctype, prop, fields, **filters):
    return [dict(row) for row in current_all(doctype,
        filters={"property": prop.name, **filters}, fields=fields,
        order_by="creation asc,name asc")]


def _summarize(rows, keys, amount="amount", base="base_amount"):
    totals = defaultdict(lambda: [Decimal(0), Decimal(0), 0])
    for row in rows:
        key = tuple(row.get(field) or "" for field in keys)
        totals[key][0] += Decimal(str(row.get(amount) or 0))
        totals[key][1] += Decimal(str(row.get(base) or row.get(amount) or 0))
        totals[key][2] += 1
    return [{**dict(zip(keys, key)), "amount": _money(value[0]),
             "base_amount": _money(value[1]), "count": value[2]}
            for key, value in sorted(totals.items())]


def _blockers(prop):
    day = prop.business_date
    result = []
    for doctype, filters, label in (
        ("HS Shift", {"status": ["in", ["Open", "Review"]]}, "Turnos sin arquear"),
        ("HS Charge", {"status": "Pending", "business_date": ["<=", day]},
         "Cargos pendientes de contabilizar"),
        ("HS Charge", {"status": "Scheduled", "service_date": ["<=", day]},
         "Cargos programados sin generar"),
        ("HS Petty Cash Rendition", {"status": ["in", ["Submitted", "Returned"]]},
         "Rendiciones de Caja Chica sin resolver"),
    ):
        names = current_all(doctype, filters={"property": prop.name, **filters}, pluck="name")
        if names:
            result.append({"type": label, "count": len(names), "documents": sorted(names)})
    return result


def build(prop):
    require_pms(prop)
    day = prop.business_date
    receivables = _records("HS PMS Receivable", prop,
        ["name", "party", "folio", "experience_order", "reference", "currency", "net_amount", "tax_amount",
         "amount", "base_amount", "income_account", "tax_account", "receivable_account", "journal",
         "opening_source_name"],
        business_date=day, status="Posted")
    opening_payables = _records("HS PMS Opening Payable", prop,
        ["name", "supplier", "opening_source_name", "currency", "amount",
         "base_amount",
         "payable_account", "journal"], business_date=day, status="Posted")
    opening_credits = _records("HS PMS Opening Credit", prop,
        ["name", "credit_kind", "customer", "opening_source_name", "currency",
         "amount", "base_amount", "receivable_account", "journal"],
        business_date=day, status="Posted")
    opening_guarantees = _records("HS PMS Opening Guarantee", prop,
        ["name", "customer", "opening_source_site", "opening_source_name",
         "source_booking", "source_stay", "source_folio", "currency", "amount",
         "liability_account", "journal"], business_date=day, status="Posted")
    opening_supplier_credits = _records("HS PMS Opening Supplier Credit", prop,
        ["name", "supplier", "opening_source_name", "currency", "amount",
         "base_currency", "base_amount", "payable_account", "journal"],
        business_date=day, status="Posted")
    supplier_credit_applications = _records("HS PMS Supplier Credit Allocation", prop,
        ["name", "kind", "opening_credit", "target_type", "opening_payable",
         "purchase", "currency", "amount", "base_currency",
         "source_base_amount", "target_base_amount",
         "exchange_variance_account", "journal", "reverses"],
        business_date=day)
    opening_credit_applications = _records("HS PMS Allocation", prop,
        ["name", "kind", "opening_credit", "receivable", "currency",
         "amount", "settlement_currency", "settled_amount",
         "opening_credit_base_amount", "opening_credit_exchange_account",
         "journal", "reverses"], business_date=day,
        kind=["in", ["Opening Credit Applied", "Opening Credit Reversed"]])
    opening_guarantee_applications = _records("HS PMS Allocation", prop,
        ["name", "kind", "opening_guarantee", "receivable", "currency",
         "amount", "journal", "reverses"], business_date=day,
        kind=["in", ["Opening Guarantee Applied", "Opening Guarantee Reversed"]])
    fiscal = _records("HS PMS Fiscal Document", prop,
        ["name", "document_type", "document_number", "currency", "net_amount",
         "tax_amount", "total_amount", "party", "source_invoice",
         "historical_source_invoice", "historical_day_pass", "journal"],
        business_date=day, status="Posted")
    payments = _records("HS Payment", prop,
        ["name", "kind", "currency", "amount", "base_amount", "exchange_rate",
         "pms_settlement_currency", "pms_settled_amount",
         "pms_released_base_amount", "pms_exchange_variance_account",
         "method", "shift", "pms_counter_account", "pms_concept", "pms_receivable",
         "pms_purchase", "pms_purchase_return", "pms_agent_commission",
         "pms_opening_payable", "pms_opening_credit",
         "pms_historical_day_pass",
         "pms_opening_guarantee",
         "pms_opening_supplier_credit",
         "reference", "pms_journal", "source_payment"],
        business_date=day, status="Posted", pms_journal=["is", "set"])
    methods = {row.name: row for row in current_all("HS Payment Method",
        filters={"property": prop.name}, fields=["name", "account", "is_cash"])}
    for row in payments:
        method = methods.get(row["method"])
        row["cash_account"] = method.account if method else None
        row["channel"] = "Cash" if method and method.is_cash else "Bank"
    treasury = _records("HS Treasury Movement", prop,
        ["name", "kind", "concept", "concept_label", "source_movement", "rendition",
         "cash_account", "counter_account", "currency", "amount", "base_amount",
         "exchange_rate", "method", "shift", "reference", "pms_journal"],
        business_date=day, status="Posted", pms_journal=["is", "set"])
    for row in treasury:
        row["channel"] = "Cash" if row["shift"] else "Bank"
    petty_expenses = _records("HS Petty Cash Expense", prop,
        ["name", "category", "category_label", "beneficiary", "receipt_reference",
         "currency", "amount", "expense_account", "petty_account", "pms_journal",
         "rendition"], business_date=day, status="Posted", pms_journal=["is", "set"])
    supplier_returns = _records("HS PMS Purchase Return", prop,
        ["name", "purchase", "supplier", "kind", "invoice_currency", "credit_amount",
         "base_currency", "base_credit", "stock_value", "variance",
         "payable_applied", "supplier_credit"], business_date=day, status="Posted")
    agency_commissions = _records("HS PMS Agency Commission", prop,
        ["name", "booking", "agent", "supplier", "agent_name", "currency",
         "base_amount", "percent", "amount", "expense_account", "payable_account",
         "journal"], business_date=day, status=["in", ["Posted", "Cancelled"]])
    agency_commission_cancellations = _records("HS PMS Agency Commission", prop,
        ["name", "booking", "agent", "supplier", "currency", "amount",
         "reversal_journal", "cancel_reason"],
        cancelled_business_date=day, status="Cancelled")
    petty_variances = _records("HS Petty Cash Rendition", prop,
        ["name", "currency", "variance", "variance_account", "pms_variance_journal",
         "responsible"], approved_business_date=day,
        status=["in", ["Approved", "Partially Reimbursed", "Reimbursed"]],
        pms_variance_journal=["is", "set"], pms_variance_reversal_journal=["is", "not set"])
    journals = _records("HS Journal", prop,
        ["name", "source_doctype", "source_name", "purpose", "reversal_of",
         "posting_date", "total_debit", "total_credit"], business_date=day, status="Posted")
    debit = sum((Decimal(str(row["total_debit"])) for row in journals), Decimal(0))
    credit = sum((Decimal(str(row["total_credit"])) for row in journals), Decimal(0))
    if debit != credit:
        frappe.throw(_("El mayor PMS no cuadra en esta fecha operativa"))
    accounts = trial_balance(prop.name, day)["rows"]
    if sum((Decimal(row["balance"]) for row in accounts), Decimal(0)) != 0:
        frappe.throw(_("El balance acumulado PMS no cuadra"))
    control = [row for row in accounts if row["account"] == prop.petty_cash_account or
        frappe.db.get_value("HS Account", row["account"], "is_cash") or
        frappe.db.get_value("HS Account", row["account"], "is_bank")]
    closed_names = current_all("HS Audit Event", filters={"property": prop.name,
        "business_date": day, "action": "pms_shift_closed"}, pluck="source_name")
    shifts = (_records("HS Shift", prop,
        ["name", "cashier", "status", "opened_at", "closed_at", "denominations"],
        name=["in", closed_names]) if closed_names else [])
    new_receivables = [row for row in receivables if not row["opening_source_name"]]
    production = _summarize(new_receivables,
        ("currency", "income_account"), amount="net_amount", base="net_amount")
    taxes = _summarize(new_receivables,
        ("currency", "tax_account"), amount="tax_amount", base="tax_amount")
    credits = _summarize([row for row in fiscal if row["document_type"] == "Credit Note"],
        ("currency",), amount="total_amount", base="total_amount")
    breakdown = {
        "production": production,
        "taxes": taxes,
        "fiscal_documents": _summarize(fiscal, ("document_type", "currency"),
                                      amount="total_amount", base="total_amount"),
        "credit_notes": credits,
        "opening_receivables": _summarize([row for row in receivables
            if row["opening_source_name"]],
            ("currency", "party", "receivable_account")),
        "opening_payables": _summarize(opening_payables,
            ("currency", "supplier", "payable_account")),
        "opening_customer_credits": _summarize(opening_credits,
            ("credit_kind", "currency", "customer", "receivable_account")),
        "opening_guarantees": _summarize(opening_guarantees,
            ("currency", "customer", "liability_account")),
        "opening_supplier_credits": _summarize(opening_supplier_credits,
            ("currency", "supplier", "payable_account")),
        "supplier_credit_applications": _summarize(supplier_credit_applications,
            ("kind", "currency", "opening_credit", "target_type",
             "opening_payable", "purchase"), base="source_base_amount"),
        "foreign_supplier_credit_applications": _summarize([{
            **row, "base_amount": row["target_base_amount"]}
            for row in supplier_credit_applications
            if row["currency"] != prop.currency],
            ("kind", "currency", "opening_credit", "target_type",
             "opening_payable")),
        "supplier_credit_exchange_variance": _summarize([{
            "kind": row["kind"], "currency": prop.currency,
            "account": row["exchange_variance_account"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in supplier_credit_applications
            if row["currency"] != prop.currency
            for difference in [Decimal(str(row["source_base_amount"])) -
                Decimal(str(row["target_base_amount"]))]
            if difference], ("kind", "currency", "account")),
        "opening_credit_applications": _summarize(opening_credit_applications,
            ("kind", "currency", "opening_credit", "receivable")),
        "foreign_opening_credit_applications": _summarize([{
            "kind": row["kind"], "currency": row["settlement_currency"],
            "opening_credit": row["opening_credit"],
            "receivable": row["receivable"],
            "amount": row["settled_amount"], "base_amount": row["amount"]}
            for row in opening_credit_applications if row["settlement_currency"]],
            ("kind", "currency", "opening_credit", "receivable")),
        "foreign_opening_credit_source_release": _summarize([{
            "kind": row["kind"], "currency": row["settlement_currency"],
            "opening_credit": row["opening_credit"],
            "amount": row["settled_amount"],
            "base_amount": row["opening_credit_base_amount"]}
            for row in opening_credit_applications if row["settlement_currency"]],
            ("kind", "currency", "opening_credit")),
        "foreign_opening_credit_exchange_differences": _summarize([{
            "kind": "Gain" if (difference > 0) ==
                (row["kind"] == "Opening Credit Applied") else "Loss",
            "direction": row["kind"], "currency": prop.currency,
            "account": row["opening_credit_exchange_account"],
            "opening_credit": row["opening_credit"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in opening_credit_applications if row["settlement_currency"]
            for difference in [Decimal(str(row["opening_credit_base_amount"])) -
                Decimal(str(row["amount"]))]
            if difference],
            ("direction", "kind", "currency", "account", "opening_credit")),
        "opening_guarantee_applications": _summarize(
            opening_guarantee_applications,
            ("kind", "currency", "opening_guarantee", "receivable")),
        "customer_cash": _summarize([row for row in payments if row["kind"] in
            ("Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund")],
            ("kind", "currency", "channel", "cash_account")),
        "other_cash": _summarize([row for row in payments if row["kind"] in
            ("Other Income", "Expense", "Supplier Payment", "Supplier Refund")
            and not row["pms_agent_commission"]],
            ("kind", "currency", "channel", "cash_account", "pms_counter_account", "pms_concept")),
        "opening_credit_refunds": _summarize([row for row in payments
            if row["pms_opening_credit"]],
            ("currency", "channel", "cash_account", "pms_counter_account",
             "pms_opening_credit")),
        "foreign_opening_credit_refunds": _summarize([{
            "currency": row["pms_settlement_currency"],
            "amount": row["pms_settled_amount"],
            "base_amount": row["pms_released_base_amount"],
            "pms_opening_credit": row["pms_opening_credit"],
            "receivable_account": row["pms_counter_account"]}
            for row in payments if row["pms_opening_credit"] and
                row["pms_settlement_currency"]],
            ("currency", "pms_opening_credit", "receivable_account")),
        "foreign_opening_credit_refund_exchange_differences": _summarize([{
            "kind": "Loss" if difference > 0 else "Gain",
            "currency": prop.currency,
            "account": row["pms_exchange_variance_account"],
            "pms_opening_credit": row["pms_opening_credit"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in payments if row["pms_opening_credit"] and
                row["pms_settlement_currency"]
            for difference in [Decimal(str(row["base_amount"])) -
                Decimal(str(row["pms_released_base_amount"]))]
            if difference],
            ("kind", "currency", "account", "pms_opening_credit")),
        "opening_guarantee_refunds": _summarize([row for row in payments
            if row["pms_opening_guarantee"]],
            ("currency", "channel", "cash_account", "pms_counter_account",
             "pms_opening_guarantee")),
        "opening_supplier_payments": _summarize([row for row in payments
            if row["pms_opening_payable"]],
            ("currency", "channel", "cash_account", "pms_counter_account",
             "pms_opening_payable")),
        "opening_supplier_settlements": _summarize([{
            "currency": row["pms_settlement_currency"] or prop.currency,
            "amount": row["pms_settled_amount"] or row["base_amount"],
            "base_amount": row["pms_released_base_amount"] or row["base_amount"],
            "pms_opening_payable": row["pms_opening_payable"],
            "payable_account": row["pms_counter_account"]}
            for row in payments if row["pms_opening_payable"]],
            ("currency", "pms_opening_payable", "payable_account")),
        "opening_customer_settlements": _summarize([{
            "currency": row["pms_settlement_currency"],
            "amount": row["pms_settled_amount"],
            "base_amount": row["pms_released_base_amount"],
            "pms_receivable": row["pms_receivable"],
            "receivable_account": row["pms_counter_account"]}
            for row in payments if row["kind"] == "Payment" and
                row["pms_settlement_currency"] and row["pms_receivable"]],
            ("currency", "pms_receivable", "receivable_account")),
        "opening_customer_refunds": _summarize([{
            "currency": row["pms_settlement_currency"],
            "amount": row["pms_settled_amount"],
            "base_amount": row["pms_released_base_amount"],
            "pms_receivable": row["pms_receivable"],
            "receivable_account": row["pms_counter_account"]}
            for row in payments if row["kind"] == "Refund" and
                row["pms_settlement_currency"] and row["pms_receivable"]],
            ("currency", "pms_receivable", "receivable_account")),
        "opening_exchange_differences": _summarize([{
            "kind": "Loss" if difference > 0 else "Gain",
            "currency": prop.currency,
            "account": row["pms_exchange_variance_account"],
            "pms_opening_payable": row["pms_opening_payable"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in payments if row["pms_opening_payable"]
            for difference in [Decimal(str(row["base_amount"])) -
                Decimal(str(row["pms_released_base_amount"] or row["base_amount"]))]
            if difference],
            ("kind", "currency", "account", "pms_opening_payable")),
        "opening_customer_exchange_differences": _summarize([{
            "kind": "Gain" if difference > 0 else "Loss",
            "currency": prop.currency,
            "account": row["pms_exchange_variance_account"],
            "pms_receivable": row["pms_receivable"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in payments if row["kind"] == "Payment" and
                row["pms_settlement_currency"] and row["pms_receivable"]
            for difference in [Decimal(str(row["base_amount"])) -
                Decimal(str(row["pms_released_base_amount"]))]
            if difference],
            ("kind", "currency", "account", "pms_receivable")),
        "opening_customer_refund_exchange_differences": _summarize([{
            "kind": "Gain Reversed" if difference > 0 else "Loss Reversed",
            "currency": prop.currency,
            "account": row["pms_exchange_variance_account"],
            "pms_receivable": row["pms_receivable"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in payments if row["kind"] == "Refund" and
                row["pms_settlement_currency"] and row["pms_receivable"]
            for difference in [Decimal(str(row["base_amount"])) -
                Decimal(str(row["pms_released_base_amount"]))]
            if difference],
            ("kind", "currency", "account", "pms_receivable")),
        "opening_supplier_credit_refunds": _summarize([row for row in payments
            if row["pms_opening_supplier_credit"]],
            ("currency", "channel", "cash_account", "pms_counter_account",
             "pms_opening_supplier_credit")),
        "foreign_supplier_credit_refunds": _summarize([{
            "currency": row["pms_settlement_currency"],
            "opening_credit": row["pms_opening_supplier_credit"],
            "amount": row["pms_settled_amount"],
            "base_amount": row["pms_released_base_amount"]}
            for row in payments if row["pms_opening_supplier_credit"] and
                row["pms_settlement_currency"]],
            ("currency", "opening_credit")),
        "supplier_credit_refund_exchange_variance": _summarize([{
            "currency": prop.currency,
            "account": row["pms_exchange_variance_account"],
            "opening_credit": row["pms_opening_supplier_credit"],
            "amount": abs(difference), "base_amount": abs(difference)}
            for row in payments if row["pms_opening_supplier_credit"] and
                row["pms_settlement_currency"]
            for difference in [Decimal(str(row["base_amount"])) -
                Decimal(str(row["pms_released_base_amount"]))]
            if difference], ("currency", "account", "opening_credit")),
        "supplier_returns": _summarize(supplier_returns,
            ("kind", "invoice_currency", "supplier", "purchase"),
            amount="credit_amount", base="base_credit"),
        "agency_commissions": _summarize(agency_commissions,
            ("currency", "agent", "supplier", "expense_account", "payable_account"),
            base="amount"),
        "agency_commission_cancellations": _summarize(agency_commission_cancellations,
            ("currency", "agent", "supplier")),
        "agency_commission_payments": _summarize([row for row in payments
            if row["pms_agent_commission"]],
            ("currency", "channel", "cash_account", "pms_counter_account",
             "pms_agent_commission")),
        "treasury": _summarize(treasury, ("kind", "currency", "channel", "cash_account",
                                         "counter_account", "concept", "concept_label")),
        "petty_expenses": _summarize(petty_expenses,
            ("currency", "category", "category_label", "expense_account", "petty_account")),
        "petty_variances": _summarize([{"currency": row["currency"],
            "kind": "Overage" if Decimal(str(row["variance"])) > 0 else "Shortage",
            "account": row["variance_account"], "amount": abs(Decimal(str(row["variance"]))) }
            for row in petty_variances if Decimal(str(row["variance"])) != 0],
            ("kind", "currency", "account")),
    }
    return {"version": 8, "property": prop.name, "organization": prop.organization,
        "base_currency": prop.currency, "business_date": str(day),
        "breakdown": breakdown, "sources": {"receivables": receivables,
            "opening_payables": opening_payables,
            "opening_credits": opening_credits,
            "opening_guarantees": opening_guarantees,
            "opening_supplier_credits": opening_supplier_credits,
            "opening_credit_applications": opening_credit_applications,
            "opening_guarantee_applications": opening_guarantee_applications,
            "supplier_credit_applications": supplier_credit_applications,
            "fiscal_documents": fiscal, "payments": payments, "treasury": treasury,
            "supplier_returns": supplier_returns,
            "agency_commissions": agency_commissions,
            "agency_commission_cancellations": agency_commission_cancellations,
            "petty_expenses": petty_expenses, "petty_variances": petty_variances,
            "journals": journals, "closed_shifts": shifts},
        "ledger": {"day_debit": _money(debit), "day_credit": _money(credit),
                   "balances": accounts, "control_accounts": control}}


def preview(property_name):
    prop = require(property_name, "report")
    require_pms(prop)
    captured = frappe.parse_json(canonical(build(prop)))
    problems = _blockers(prop)
    signature = sha256(canonical({"snapshot": captured, "blockers": problems}).encode()).hexdigest()
    return {"snapshot": captured, "blockers": problems, "review_acceptance": signature}


def close(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"review_acceptance", "reason"}:
        frappe.throw(_("Revise la confirmación del cierre PMS"))
    reason = data.get("reason") or ""
    if not isinstance(reason, str) or len(reason.strip()) > 1000:
        frappe.throw(_("La observación de cierre admite hasta 1000 caracteres"))
    review = preview(prop.name)
    if not data.get("review_acceptance") or data["review_acceptance"] != review["review_acceptance"]:
        frappe.throw(_("El resumen del cierre cambió; revíselo de nuevo"))
    if review["blockers"]:
        frappe.throw(_("Resuelva los pendientes antes de cerrar el día"))
    if frappe.db.exists("HS Daily Close", {"property": prop.name,
            "business_date": prop.business_date, "status": "Closed"}):
        frappe.throw(_("La fecha operativa ya tiene un cierre confirmado"))
    latest = frappe.db.sql("SELECT COALESCE(MAX(revision),0) FROM `tabHS Daily Close` "
                           "WHERE property=%s AND business_date=%s",
                           (prop.name, prop.business_date), as_list=True)[0][0]
    doc = insert("HS Daily Close", prop, business_date=prop.business_date,
        revision=int(latest) + 1, status="Closed", summary=canonical(review["snapshot"]),
        blockers=canonical([]), closed_at=now_datetime(), reason=reason.strip())
    audit(prop, "pms_daily_closed", doc, reason=reason.strip() or "Cierre diario confirmado",
          details={"review_acceptance": review["review_acceptance"],
                   "ledger_debit": review["snapshot"]["ledger"]["day_debit"]})
    prop.business_date = add_days(prop.business_date, 1)
    prop.save()
    return {"close": doc.name, "status": doc.status,
            "business_date": str(doc.business_date), "next_business_date": str(prop.business_date)}


def history(property_name):
    prop = require(property_name, "report")
    require_pms(prop)
    rows = current_all("HS Daily Close", filters={"property": prop.name},
        fields=["name", "business_date", "revision", "status", "closed_at", "reason"],
        order_by="business_date desc,revision desc")
    return [dict(row) for row in rows]


def detail(property_name, name):
    prop = require(property_name, "report")
    require_pms(prop)
    doc = document("HS Daily Close", name, "report")
    if doc.property != prop.name:
        frappe.throw(_("El cierre pertenece a otro establecimiento"), frappe.PermissionError)
    return {"name": doc.name, "business_date": str(doc.business_date),
            "revision": doc.revision,
            "status": doc.status, "closed_at": str(doc.closed_at),
            "reason": doc.reason, "snapshot": frappe.parse_json(doc.summary or "{}")}
