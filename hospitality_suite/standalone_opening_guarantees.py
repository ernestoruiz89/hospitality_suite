"""Imported guest guarantees: opening liability and traceable refunds."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from uuid import uuid4

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (
    account, account_currency_balance, post, require_pms,
)
from hospitality_suite.standalone_currency import enabled, latest_rate
from hospitality_suite.standalone_cash import expected


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _positive(value):
    try:
        result = amount(value)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if result <= 0:
        frappe.throw(_("El importe debe ser positivo"))
    return result


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique un texto válido"))
    return value.strip()


def _guarantee(prop, name):
    row = locked_doc("HS PMS Opening Guarantee", name)
    if (row.property != prop.name or row.organization != prop.organization or
            row.status != "Posted"):
        frappe.throw(_("La garantía pertenece a otro establecimiento"),
                     frappe.PermissionError)
    return row


def available(prop, name):
    row = _guarantee(prop, name)
    applied = sum(((-1 if item.kind == "Opening Guarantee Reversed" else 1) *
        Decimal(str(item.amount)) for item in current_all("HS PMS Allocation",
        filters={"property": prop.name, "opening_guarantee": row.name,
            "kind": ["in", ["Opening Guarantee Applied",
                            "Opening Guarantee Reversed"]]},
        fields=["kind", "amount"])), Decimal(0))
    refunded = sum((Decimal(str(item.base_amount)) for item in current_all(
        "HS Payment", filters={"property": prop.name,
            "pms_opening_guarantee": row.name, "kind": "Guarantee Refund",
            "status": "Posted"}, fields=["base_amount"])), Decimal(0))
    balance = Decimal(str(row.amount)) - applied - refunded
    if balance < 0:
        frappe.throw(_("Las aplicaciones y devoluciones superan la garantía inicial"))
    return balance


def matches(prop, guarantee, receivable):
    """Opening guarantees follow the restored folio, stay or booking identity."""
    if not receivable.folio:
        return False
    folio = frappe.db.get_value("HS Folio", receivable.folio,
        ["property", "company", "customer", "booking", "stay"], as_dict=True)
    if (not folio or folio.property != prop.name or folio.company != prop.company or
            folio.customer != guarantee.customer or
            receivable.party != guarantee.customer):
        return False
    if guarantee.source_folio:
        return guarantee.source_folio == receivable.folio
    if guarantee.source_stay:
        return guarantee.source_stay == folio.stay
    if guarantee.source_booking:
        booking = folio.booking or (frappe.db.get_value("HS Stay", folio.stay,
            "booking") if folio.stay else None)
        return guarantee.source_booking == booking
    return False


def receivable_due(prop, name):
    from hospitality_suite.standalone_receivables import outstanding
    return outstanding(prop, name)


def remaining_application(prop, name):
    original = locked_doc("HS PMS Allocation", name)
    if original.property != prop.name or original.kind != "Opening Guarantee Applied":
        frappe.throw(_("Seleccione una aplicación inicial de garantía válida"))
    reversed_amount = sum((Decimal(str(row.amount)) for row in current_all(
        "HS PMS Allocation", filters={"property": prop.name, "reverses": name,
            "kind": "Opening Guarantee Reversed"}, fields=["amount"])), Decimal(0))
    left = Decimal(str(original.amount)) - reversed_amount
    if left < 0:
        frappe.throw(_("La aplicación de garantía tiene reversiones excesivas"))
    return left


def apply_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {
            "guarantee", "receivable", "amount", "reason"}:
        frappe.throw(_("Revise la aplicación de la garantía inicial"))
    guarantee = _guarantee(prop, data.get("guarantee"))
    receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
    if (receivable.property != prop.name or
            receivable.organization != prop.organization or
            receivable.status != "Posted" or
            receivable.currency != prop.currency or
            not matches(prop, guarantee, receivable)):
        frappe.throw(_("La garantía no corresponde al cliente y la cuenta de estancia"))
    value = _positive(data.get("amount"))
    left, due = available(prop, guarantee.name), receivable_due(prop, receivable.name)
    if value > left or value > due:
        frappe.throw(_("La aplicación supera la garantía o la cuenta pendiente"))
    liability = account(prop, guarantee.liability_account)
    ar = account(prop, receivable.receivable_account)
    if (liability.root_type != "Liability" or ar.root_type != "Asset" or
            ar.account_type != "Receivable" or
            liability.account_currency != prop.currency or
            ar.account_currency != prop.currency):
        frappe.throw(_("Las cuentas originales de garantía o cartera no son válidas"))
    reason = _text(data.get("reason"), 500)
    signature = {"property": prop.name, "guarantee": guarantee.name,
        "guarantee_modified": str(guarantee.modified),
        "available": _money(left), "receivable": receivable.name,
        "receivable_modified": str(receivable.modified), "due": _money(due),
        "debit": liability.name, "credit": ar.name,
        "amount": _money(value), "reason": reason}
    return {"opening_guarantee": guarantee.name, "receivable": receivable.name,
        "amount": _money(value), "currency": prop.currency,
        "available_after": _money(left - value),
        "outstanding_after": _money(due - value),
        "debit": liability.name, "credit": ar.name,
        "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def apply(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "guarantee", "receivable", "amount", "reason", "acceptance"}:
        frappe.throw(_("Revise la aplicación de la garantía inicial"))
    quote = apply_quote(prop, {key: value for key, value in data.items()
                               if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("La garantía o la cuenta cambió; revise la aplicación"))
    customer = _guarantee(prop, quote["opening_guarantee"]).customer
    journal = post(prop, source_doctype="HS PMS Allocation",
        source_name=uuid4().hex, purpose="Opening Guarantee Applied",
        memo=quote["reason"], lines=[
            {"account": quote["debit"], "debit": quote["amount"], "credit": "0"},
            {"account": quote["credit"], "party": customer,
             "debit": "0", "credit": quote["amount"]}])
    before = getattr(frappe.local, "hs_opening_guarantee_application", False)
    frappe.local.hs_opening_guarantee_application = True
    try:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
            receivable=quote["receivable"],
            opening_guarantee=quote["opening_guarantee"],
            kind="Opening Guarantee Applied", business_date=prop.business_date,
            currency=prop.currency, amount=quote["amount"], journal=journal.name)
    finally:
        frappe.local.hs_opening_guarantee_application = before
    audit(prop, "pms_opening_guarantee_applied", row, reason=quote["reason"],
          details={"journal": journal.name, "remaining": quote["available_after"]})
    return {"allocation": row.name, "journal": journal.name,
        "guarantee_available": quote["available_after"],
        "receivable_outstanding": quote["outstanding_after"]}


def unapply(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"allocation", "amount", "reason"}:
        frappe.throw(_("Revise la reversión de la garantía inicial"))
    original = locked_doc("HS PMS Allocation", data.get("allocation"))
    if original.property != prop.name or original.kind != "Opening Guarantee Applied":
        frappe.throw(_("Seleccione una aplicación inicial de garantía"))
    value = _positive(data.get("amount"))
    if value > remaining_application(prop, original.name):
        frappe.throw(_("La reversión supera la aplicación pendiente"))
    guarantee = _guarantee(prop, original.opening_guarantee)
    receivable = locked_doc("HS PMS Receivable", original.receivable)
    if (receivable.property != prop.name or receivable.status != "Posted" or
            not matches(prop, guarantee, receivable)):
        frappe.throw(_("La garantía o la cuenta original ya no coincide"))
    liability = account(prop, guarantee.liability_account)
    ar = account(prop, receivable.receivable_account)
    if (liability.root_type != "Liability" or ar.root_type != "Asset" or
            ar.account_type != "Receivable" or
            liability.account_currency != prop.currency or
            ar.account_currency != prop.currency):
        frappe.throw(_("Las cuentas originales de garantía o cartera no son válidas"))
    reason = _text(data.get("reason"), 500)
    journal = post(prop, source_doctype="HS PMS Allocation",
        source_name=uuid4().hex, purpose="Opening Guarantee Reversed",
        memo=reason, lines=[
            {"account": ar.name, "party": guarantee.customer,
             "debit": str(value), "credit": "0"},
            {"account": liability.name, "debit": "0", "credit": str(value)}])
    before = getattr(frappe.local, "hs_opening_guarantee_application", False)
    frappe.local.hs_opening_guarantee_application = True
    try:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
            receivable=receivable.name, opening_guarantee=guarantee.name,
            kind="Opening Guarantee Reversed", reverses=original.name,
            business_date=prop.business_date, currency=prop.currency,
            amount=str(value), journal=journal.name)
    finally:
        frappe.local.hs_opening_guarantee_application = before
    audit(prop, "pms_opening_guarantee_unapplied", row, reason=reason,
          details={"journal": journal.name, "original": original.name})
    return {"allocation": row.name, "journal": journal.name,
        "guarantee_available": _money(available(prop, guarantee.name)),
        "receivable_outstanding": _money(receivable_due(prop, receivable.name))}


def refund_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {
            "guarantee", "method", "shift", "amount", "reference", "reason"}:
        frappe.throw(_("Revise la devolución de la garantía inicial"))
    guarantee = _guarantee(prop, data.get("guarantee"))
    left = available(prop, guarantee.name)
    if left <= 0:
        frappe.throw(_("La garantía ya fue devuelta"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio del establecimiento"))
    cash_account = account(prop, method.account)
    liability = account(prop, guarantee.liability_account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank) or
            liability.root_type != "Liability" or
            liability.account_currency != prop.currency):
        frappe.throw(_("Las cuentas de devolución no son válidas"))
    value = _positive(data.get("amount"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0 or base > left:
        frappe.throw(_("La devolución supera la garantía disponible"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("Se requiere turno propio abierto"), frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("Efectivo insuficiente en el turno"))
    elif data.get("shift"):
        frappe.throw(_("La devolución bancaria no se asigna a un turno"))
    if value > Decimal(account_currency_balance(prop, cash_account.name)["balance"]):
        frappe.throw(_("Saldo contable insuficiente en Caja o banco"))
    reference = _text(data.get("reference"), 140)
    reason = _text(data.get("reason"), 500)
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "kind": "Guarantee Refund", "pms_opening_guarantee": guarantee.name,
            "reference": reference, "status": "Posted"}):
        frappe.throw(_("La referencia ya se aplicó a esta garantía"))
    signature = {"property": prop.name, "guarantee": guarantee.name,
        "modified": str(guarantee.modified), "available": _money(left),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": _money(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "reference": reference, "reason": reason}
    return {"guarantee": guarantee.name, "customer": guarantee.customer,
        "liability_account": liability.name, "cash_account": cash_account.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": _money(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "available_after": _money(left - base), "reference": reference,
        "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def refund(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "guarantee", "method", "shift", "amount", "reference", "reason",
            "acceptance"}:
        frappe.throw(_("Revise la devolución de la garantía"))
    quote = refund_quote(prop, {key: value for key, value in data.items()
                                if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("La garantía, medio o cambio varió; revise la devolución"))
    before = getattr(frappe.local, "hs_opening_guarantee_refund", False)
    frappe.local.hs_opening_guarantee_refund = True
    try:
        payment = insert("HS Payment", prop, shift=quote["shift"],
            method=quote["method"], currency=quote["currency"],
            amount=quote["amount"], exchange_rate=quote["exchange_rate"],
            base_amount=quote["base_amount"], kind="Guarantee Refund",
            status="Posted", reference=quote["reference"], reason=quote["reason"],
            pms_counter_account=quote["liability_account"],
            pms_opening_guarantee=quote["guarantee"])
        journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
            purpose="Opening Guarantee Refund", memo=quote["reason"], lines=[
                {"account": quote["liability_account"],
                 "debit": quote["base_amount"], "credit": "0"},
                {"account": quote["cash_account"], "debit": "0",
                 "credit": quote["base_amount"],
                 "account_currency": quote["currency"],
                 "exchange_rate": quote["exchange_rate"],
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": quote["amount"]}])
        payment.pms_journal = journal.name
        payment.save()
    finally:
        frappe.local.hs_opening_guarantee_refund = before
    audit(prop, "pms_opening_guarantee_refunded", payment,
        reason=quote["reason"], details={"guarantee": quote["guarantee"],
                                          "journal": journal.name})
    return {"payment": payment.name, "journal": journal.name,
            "guarantee_available": quote["available_after"]}


def snapshot(prop):
    rows = frappe.get_all("HS PMS Opening Guarantee",
        filters={"property": prop.name, "status": "Posted"},
        fields=["name", "customer", "opening_source_site", "opening_source_name",
                "source_booking", "source_stay", "source_folio", "business_date",
                "currency", "amount", "liability_account"],
        order_by="creation desc", limit_page_length=200)
    for row in rows:
        row["available"] = _money(available(prop, row.name))
    return rows
