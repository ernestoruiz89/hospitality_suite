"""Base-currency customer credits imported from ERPNext opening balances.

An opening credit is an AR credit already present in the source GL. Applying
it to another receivable transfers value between AR accounts only when needed;
refunding it posts a real cash or bank payment. Neither action records a new
sale or pretends that the original receipt happened in the PMS shift.
"""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from uuid import uuid4

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (
    account, account_currency_balance, post, require_pms)
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, latest_rate
from hospitality_suite.standalone_receivables import outstanding


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique un texto válido de hasta {0} caracteres").format(maximum))
    return value.strip()


def _value(value):
    try:
        result = amount(value)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if result <= 0:
        frappe.throw(_("El importe debe ser positivo"))
    return result


def _credit(prop, name):
    credit = locked_doc("HS PMS Opening Credit", name)
    if (credit.property != prop.name or credit.organization != prop.organization or
            credit.status != "Posted"):
        frappe.throw(_("El crédito inicial pertenece a otro establecimiento"),
                     frappe.PermissionError)
    return credit


def balances(prop, name):
    credit = _credit(prop, name)
    foreign = credit.currency != prop.currency
    if foreign and (credit.base_currency != prop.currency or
            Decimal(str(credit.base_amount or 0)) <= 0):
        frappe.throw(_("El crédito extranjero no conserva su valor base"))
    applications = current_all("HS PMS Allocation",
        filters={"property": prop.name, "opening_credit": credit.name,
                 "kind": ["in", ["Opening Credit Applied", "Opening Credit Reversed"]]},
        fields=["kind", "amount", "settlement_currency", "settled_amount",
                "opening_credit_base_amount"])
    refunds = current_all(
        "HS Payment", filters={"property": prop.name,
            "pms_opening_credit": credit.name, "kind": "Refund", "status": "Posted"},
        fields=["base_amount", "pms_settlement_currency", "pms_settled_amount",
                "pms_released_base_amount"])
    if foreign and (any(row.settlement_currency != credit.currency or
            Decimal(str(row.settled_amount or 0)) <= 0 or
            Decimal(str(row.opening_credit_base_amount or 0)) <= 0
            for row in applications) or
            any(row.pms_settlement_currency != credit.currency or
                Decimal(str(row.pms_settled_amount or 0)) <= 0 for row in refunds)):
        frappe.throw(_("El crédito extranjero tiene una aplicación incompatible"))
    applied_original = sum(((-1 if row.kind == "Opening Credit Reversed" else 1) *
        Decimal(str(row.settled_amount if foreign else row.amount))
        for row in applications), Decimal(0))
    applied_base = sum(((-1 if row.kind == "Opening Credit Reversed" else 1) *
        Decimal(str(row.opening_credit_base_amount if foreign else row.amount))
        for row in applications), Decimal(0))
    refunded_original = sum((Decimal(str(row.pms_settled_amount if foreign else
        row.base_amount)) for row in refunds), Decimal(0))
    refunded_base = sum((Decimal(str(row.pms_released_base_amount if foreign else
        row.base_amount)) for row in refunds), Decimal(0))
    left = Decimal(str(credit.amount)) - applied_original - refunded_original
    base_left = Decimal(str(credit.base_amount or credit.amount)) - applied_base - refunded_base
    if (left < 0 or base_left < 0 or (left == 0) != (base_left == 0)):
        frappe.throw(_("El crédito inicial tiene aplicaciones o devoluciones excesivas"))
    return left, base_left


def available(prop, name):
    return balances(prop, name)[0]


def receivable_due(prop, name):
    return outstanding(prop, name)


def application_balances(prop, name):
    original = locked_doc("HS PMS Allocation", name)
    if original.property != prop.name or original.kind != "Opening Credit Applied":
        frappe.throw(_("Seleccione una aplicación inicial válida"))
    credit = _credit(prop, original.opening_credit)
    foreign = credit.currency != prop.currency
    reversed_rows = current_all(
        "HS PMS Allocation", filters={"property": prop.name, "reverses": name,
            "kind": "Opening Credit Reversed"},
        fields=["amount", "settled_amount", "opening_credit_base_amount"])
    original_left = Decimal(str(original.settled_amount if foreign else
        original.amount)) - sum((Decimal(str(row.settled_amount if foreign else
            row.amount)) for row in reversed_rows), Decimal(0))
    source_base_left = Decimal(str(original.opening_credit_base_amount if foreign
        else original.amount)) - sum((Decimal(str(row.opening_credit_base_amount
        if foreign else row.amount)) for row in reversed_rows), Decimal(0))
    target_base_left = Decimal(str(original.amount)) - sum((Decimal(str(row.amount))
        for row in reversed_rows), Decimal(0))
    if (original_left < 0 or source_base_left < 0 or target_base_left < 0 or
            (original_left == 0) != (source_base_left == 0) or
            (original_left == 0) != (target_base_left == 0)):
        frappe.throw(_("La aplicación inicial tiene reversiones excesivas"))
    return original_left, source_base_left, target_base_left


def remaining_application(prop, name):
    return application_balances(prop, name)[0]


def _foreign_apply_quote(prop, data, credit):
    from hospitality_suite.standalone_receivables import opening_balances

    receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
    if (receivable.property != prop.name or
            receivable.organization != prop.organization or
            receivable.status != "Posted" or
            receivable.party != credit.customer or
            receivable.currency != credit.currency):
        frappe.throw(_("Seleccione cartera extranjera del mismo cliente y moneda"))
    value = _value(data.get("amount"))
    left, source_base_left = balances(prop, credit.name)
    due, target_base_left = opening_balances(prop, receivable.name)
    if value > left or value > due:
        frappe.throw(_("La aplicación supera el crédito o la cartera pendiente"))
    source_release = (source_base_left if value == left else
        (source_base_left * value / left).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    target_release = (target_base_left if value == due else
        (target_base_left * value / due).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    if (source_release <= 0 or target_release <= 0 or
            (source_release >= source_base_left and value < left) or
            (target_release >= target_base_left and value < due)):
        frappe.throw(_("La fracción no puede liberar ambos valores base"))
    try:
        source_rate = rate_for_base(value, source_release)
        target_rate = rate_for_base(value, target_release)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    source_account = account(prop, credit.receivable_account)
    target_account = account(prop, receivable.receivable_account)
    if any(row.root_type != "Asset" or row.account_type != "Receivable" or
            row.account_currency != credit.currency for row in
            (source_account, target_account)):
        frappe.throw(_("Las cuentas extranjeras del cliente no son válidas"))
    difference = source_release - target_release
    variance_account = None
    if difference:
        if not prop.pms_exchange_variance_account:
            frappe.throw(_("Configure la cuenta PMS de diferencia cambiaria"))
        variance_account = account(prop, prop.pms_exchange_variance_account)
        if (variance_account.root_type not in ("Income", "Expense") or
                variance_account.account_currency != prop.currency or
                variance_account.is_cash or variance_account.is_bank):
            frappe.throw(_("La cuenta PMS de diferencia cambiaria no es válida"))
    reason = _text(data.get("reason"), 500)
    signature = {"property": prop.name, "credit": credit.name,
        "credit_modified": str(credit.modified), "available": _money(left),
        "source_base_left": _money(source_base_left),
        "receivable": receivable.name,
        "receivable_modified": str(receivable.modified),
        "due": _money(due), "target_base_left": _money(target_base_left),
        "amount": _money(value), "source_base": _money(source_release),
        "target_base": _money(target_release), "variance": _money(difference),
        "variance_account": variance_account.name if variance_account else None,
        "debit": source_account.name, "credit_account": target_account.name,
        "reason": reason}
    return {"opening_credit": credit.name, "receivable": receivable.name,
        "amount": _money(value), "currency": credit.currency,
        "settlement_currency": credit.currency,
        "source_base_amount": _money(source_release),
        "target_base_amount": _money(target_release),
        "source_exchange_rate": source_rate,
        "target_exchange_rate": target_rate,
        "exchange_variance_base": _money(difference),
        "exchange_variance_account": variance_account.name if variance_account else None,
        "available_after": _money(left - value),
        "outstanding_after": _money(due - value),
        "debit": source_account.name, "credit": target_account.name,
        "journal_required": source_account.name != target_account.name or bool(difference),
        "reason": reason, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def apply_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"credit", "receivable", "amount", "reason"}:
        frappe.throw(_("Revise la aplicación del crédito inicial"))
    credit = _credit(prop, data.get("credit"))
    if credit.currency != prop.currency:
        return _foreign_apply_quote(prop, data, credit)
    receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
    if (receivable.property != prop.name or receivable.organization != prop.organization or
            receivable.status != "Posted" or receivable.party != credit.customer or
            receivable.currency != prop.currency):
        frappe.throw(_("El crédito y la cuenta no pertenecen al mismo cliente"))
    value = _value(data.get("amount"))
    left = available(prop, credit.name)
    due = outstanding(prop, receivable.name)
    if value > left or value > due:
        frappe.throw(_("La aplicación supera el crédito o la cuenta pendiente"))
    source_account = account(prop, credit.receivable_account)
    target_account = account(prop, receivable.receivable_account)
    if any(row.root_type != "Asset" or row.account_type != "Receivable" or
           row.account_currency != prop.currency for row in
           (source_account, target_account)):
        frappe.throw(_("Las cuentas por cobrar originales ya no son válidas"))
    reason = _text(data.get("reason"), 500)
    signature = {"property": prop.name, "credit": credit.name,
        "credit_modified": str(credit.modified), "available": _money(left),
        "receivable": receivable.name, "receivable_modified": str(receivable.modified),
        "due": _money(due), "debit": source_account.name,
        "credit_account": target_account.name, "amount": _money(value),
        "reason": reason}
    return {"opening_credit": credit.name, "receivable": receivable.name,
        "amount": _money(value), "currency": prop.currency,
        "available_after": _money(left - value), "outstanding_after": _money(due - value),
        "debit": source_account.name, "credit": target_account.name,
        "journal_required": source_account.name != target_account.name,
        "reason": reason, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def apply(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "credit", "receivable", "amount", "reason", "acceptance"}:
        frappe.throw(_("Revise la aplicación del crédito inicial"))
    quote = apply_quote(prop, {key: value for key, value in data.items()
                               if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("El crédito o la cuenta cambiaron; revise la aplicación"))
    if quote.get("settlement_currency"):
        customer = _credit(prop, quote["opening_credit"]).customer
        journal = None
        if quote["journal_required"]:
            lines = [
                {"account": quote["debit"], "party": customer,
                 "debit": quote["source_base_amount"], "credit": "0",
                 "account_currency": quote["currency"],
                 "exchange_rate": quote["source_exchange_rate"],
                 "debit_in_account_currency": quote["amount"],
                 "credit_in_account_currency": "0"},
                {"account": quote["credit"], "party": customer,
                 "debit": "0", "credit": quote["target_base_amount"],
                 "account_currency": quote["currency"],
                 "exchange_rate": quote["target_exchange_rate"],
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": quote["amount"]}]
            difference = Decimal(quote["exchange_variance_base"])
            if difference:
                lines.append({"account": quote["exchange_variance_account"],
                    "debit": _money(max(-difference, Decimal(0))),
                    "credit": _money(max(difference, Decimal(0)))})
            journal = post(prop, source_doctype="HS PMS Allocation",
                source_name=uuid4().hex, purpose="Opening Credit Applied",
                memo=quote["reason"], lines=lines)
        before = getattr(frappe.local, "hs_opening_credit_application", False)
        frappe.local.hs_opening_credit_application = True
        try:
            row = insert("HS PMS Allocation", prop, organization=prop.organization,
                receivable=quote["receivable"],
                opening_credit=quote["opening_credit"],
                kind="Opening Credit Applied", business_date=prop.business_date,
                currency=prop.currency, amount=quote["target_base_amount"],
                settlement_currency=quote["currency"],
                settled_amount=quote["amount"],
                opening_credit_base_amount=quote["source_base_amount"],
                opening_credit_exchange_account=quote["exchange_variance_account"],
                journal=journal.name if journal else None)
        finally:
            frappe.local.hs_opening_credit_application = before
        audit(prop, "pms_opening_credit_applied", row, reason=quote["reason"],
            details={"journal": journal.name if journal else None,
                "principal": quote["amount"],
                "source_base": quote["source_base_amount"],
                "target_base": quote["target_base_amount"],
                "exchange_variance_base": quote["exchange_variance_base"]})
        return {"allocation": row.name,
            "journal": journal.name if journal else None,
            "credit_available": quote["available_after"],
            "receivable_outstanding": quote["outstanding_after"]}
    journal = None
    if quote["journal_required"]:
        customer = _credit(prop, quote["opening_credit"]).customer
        journal = post(prop, source_doctype="HS PMS Allocation",
            source_name=uuid4().hex, purpose="Opening Credit Applied",
            memo=quote["reason"], lines=[
                {"account": quote["debit"], "party": customer,
                 "debit": quote["amount"], "credit": "0"},
                {"account": quote["credit"], "party": customer,
                 "debit": "0", "credit": quote["amount"]}])
    before = getattr(frappe.local, "hs_opening_credit_application", False)
    frappe.local.hs_opening_credit_application = True
    try:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
            receivable=quote["receivable"], opening_credit=quote["opening_credit"],
            kind="Opening Credit Applied", business_date=prop.business_date,
            currency=prop.currency, amount=quote["amount"],
            journal=journal.name if journal else None)
    finally:
        frappe.local.hs_opening_credit_application = before
    audit(prop, "pms_opening_credit_applied", row, reason=quote["reason"],
          details={"journal": journal.name if journal else None,
                   "remaining": quote["available_after"]})
    return {"allocation": row.name, "journal": journal.name if journal else None,
        "credit_available": quote["available_after"],
        "receivable_outstanding": quote["outstanding_after"]}


def unapply(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"allocation", "amount", "reason"}:
        frappe.throw(_("Revise la reversión del crédito inicial"))
    original = locked_doc("HS PMS Allocation", data.get("allocation"))
    if original.property != prop.name or original.kind != "Opening Credit Applied":
        frappe.throw(_("Seleccione una aplicación inicial del establecimiento"))
    value = _value(data.get("amount"))
    if value > remaining_application(prop, original.name):
        frappe.throw(_("La reversión supera la aplicación pendiente"))
    credit = _credit(prop, original.opening_credit)
    receivable = locked_doc("HS PMS Receivable", original.receivable)
    if receivable.property != prop.name or receivable.status != "Posted":
        frappe.throw(_("La cuenta por cobrar original ya no está vigente"))
    source_account = account(prop, credit.receivable_account)
    target_account = account(prop, receivable.receivable_account)
    reason = _text(data.get("reason"), 500)
    if credit.currency != prop.currency:
        nominal_left, source_left, target_left = application_balances(
            prop, original.name)
        source_restore = (source_left if value == nominal_left else
            (source_left * value / nominal_left).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        target_restore = (target_left if value == nominal_left else
            (target_left * value / nominal_left).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        if (source_restore <= 0 or target_restore <= 0 or
                (source_restore >= source_left and value < nominal_left) or
                (target_restore >= target_left and value < nominal_left)):
            frappe.throw(_("La fracción no puede revertir ambos valores base"))
        try:
            source_rate = rate_for_base(value, source_restore)
            target_rate = rate_for_base(value, target_restore)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        difference = target_restore - source_restore
        journal = None
        if source_account.name != target_account.name or difference:
            lines = [
                {"account": target_account.name, "party": credit.customer,
                 "debit": _money(target_restore), "credit": "0",
                 "account_currency": credit.currency,
                 "exchange_rate": target_rate,
                 "debit_in_account_currency": _money(value),
                 "credit_in_account_currency": "0"},
                {"account": source_account.name, "party": credit.customer,
                 "debit": "0", "credit": _money(source_restore),
                 "account_currency": credit.currency,
                 "exchange_rate": source_rate,
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": _money(value)}]
            if difference:
                variance_account = account(prop,
                    original.opening_credit_exchange_account)
                if variance_account.root_type not in ("Income", "Expense") or \
                        variance_account.account_currency != prop.currency:
                    frappe.throw(_("La cuenta PMS de cambio no es válida"))
                lines.append({"account": variance_account.name,
                    "debit": _money(max(-difference, Decimal(0))),
                    "credit": _money(max(difference, Decimal(0)))})
            journal = post(prop, source_doctype="HS PMS Allocation",
                source_name=uuid4().hex, purpose="Opening Credit Reversed",
                memo=reason, lines=lines)
        before = getattr(frappe.local, "hs_opening_credit_application", False)
        frappe.local.hs_opening_credit_application = True
        try:
            row = insert("HS PMS Allocation", prop, organization=prop.organization,
                receivable=receivable.name, opening_credit=credit.name,
                kind="Opening Credit Reversed", reverses=original.name,
                business_date=prop.business_date, currency=prop.currency,
                amount=_money(target_restore),
                settlement_currency=credit.currency, settled_amount=_money(value),
                opening_credit_base_amount=_money(source_restore),
                opening_credit_exchange_account=original.opening_credit_exchange_account,
                journal=journal.name if journal else None)
        finally:
            frappe.local.hs_opening_credit_application = before
        audit(prop, "pms_opening_credit_unapplied", row, reason=reason,
            details={"original": original.name,
                "journal": journal.name if journal else None,
                "principal": _money(value),
                "source_base": _money(source_restore),
                "target_base": _money(target_restore)})
        return {"allocation": row.name,
            "credit_available": _money(available(prop, credit.name)),
            "receivable_outstanding": _money(outstanding(prop, receivable.name))}
    journal = None
    if source_account.name != target_account.name:
        journal = post(prop, source_doctype="HS PMS Allocation",
            source_name=uuid4().hex, purpose="Opening Credit Reversed",
            memo=reason, lines=[
                {"account": target_account.name, "party": credit.customer,
                 "debit": str(value), "credit": "0"},
                {"account": source_account.name, "party": credit.customer,
                 "debit": "0", "credit": str(value)}])
    before = getattr(frappe.local, "hs_opening_credit_application", False)
    frappe.local.hs_opening_credit_application = True
    try:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
            receivable=receivable.name, opening_credit=credit.name,
            kind="Opening Credit Reversed", reverses=original.name,
            business_date=prop.business_date, currency=prop.currency,
            amount=str(value), journal=journal.name if journal else None)
    finally:
        frappe.local.hs_opening_credit_application = before
    audit(prop, "pms_opening_credit_unapplied", row, reason=reason,
          details={"original": original.name,
                   "journal": journal.name if journal else None})
    return {"allocation": row.name,
        "credit_available": _money(available(prop, credit.name)),
        "receivable_outstanding": _money(outstanding(prop, receivable.name))}


def refund_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {
            "credit", "method", "shift", "amount", "settled_amount",
            "reference", "reason"}:
        frappe.throw(_("Revise la devolución del crédito inicial"))
    credit = _credit(prop, data.get("credit"))
    foreign = credit.currency != prop.currency
    left, base_left = balances(prop, credit.name)
    if left <= 0:
        frappe.throw(_("El crédito inicial ya fue consumido"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio del establecimiento"))
    cash_account = account(prop, method.account)
    receivable_account = account(prop, credit.receivable_account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank) or
            receivable_account.root_type != "Asset" or
            receivable_account.account_type != "Receivable" or
            receivable_account.account_currency != credit.currency):
        frappe.throw(_("Las cuentas de la devolución no son válidas"))
    value = _value(data.get("amount"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0 or (not foreign and base > left):
        frappe.throw(_("La devolución supera el crédito disponible"))
    settled = released = variance = None
    variance_account = None
    counter_rate = "1"
    if foreign:
        raw_settled = data.get("settled_amount")
        if raw_settled in (None, "") and method.currency == credit.currency:
            settled = value
        elif raw_settled in (None, ""):
            frappe.throw(_("Indique cuánto crédito extranjero devuelve"))
        else:
            settled = _value(raw_settled)
        if settled <= 0 or settled > left:
            frappe.throw(_("La devolución supera el crédito original disponible"))
        released = (base_left if settled == left else
            (base_left * settled / left).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        if released <= 0 or (released >= base_left and settled < left):
            frappe.throw(_("La devolución no puede liberar ese valor base"))
        try:
            counter_rate = rate_for_base(settled, released)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        variance = base - released
        if variance:
            if not prop.pms_exchange_variance_account:
                frappe.throw(_("Configure la cuenta PMS de diferencia cambiaria"))
            variance_account = account(prop, prop.pms_exchange_variance_account)
            if (variance_account.root_type not in ("Income", "Expense") or
                    variance_account.account_currency != prop.currency or
                    variance_account.is_cash or variance_account.is_bank):
                frappe.throw(_("La cuenta PMS de diferencia cambiaria no es válida"))
    elif data.get("settled_amount") not in (None, ""):
        frappe.throw(_("El crédito en moneda base no requiere principal extranjero"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("La devolución en efectivo requiere turno propio abierto"),
                         frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data.get("shift"):
        frappe.throw(_("La devolución bancaria no se asigna a turno"))
    if value > Decimal(account_currency_balance(prop, cash_account.name)["balance"]):
        frappe.throw(_("Caja o banco no tiene saldo contable suficiente"))
    reference = _text(data.get("reference"), 140)
    reason = _text(data.get("reason"), 500)
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "kind": "Refund", "pms_opening_credit": credit.name,
            "reference": reference, "status": "Posted"}):
        frappe.throw(_("La referencia ya se aplicó a este crédito"))
    signature = {"property": prop.name, "credit": credit.name,
        "credit_modified": str(credit.modified), "available": _money(left),
        "base_available": _money(base_left),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": str(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "settled": _money(settled) if foreign else None,
        "released": _money(released) if foreign else None,
        "variance": _money(variance) if foreign else None,
        "variance_account": variance_account.name if variance_account else None,
        "reference": reference, "reason": reason}
    return {"credit": credit.name, "customer": credit.customer,
        "receivable_account": receivable_account.name,
        "cash_account": cash_account.name, "method": method.name,
        "shift": shift.name if shift else None, "amount": str(value),
        "currency": method.currency, "exchange_rate": str(rate),
        "rate_record": rate_record, "base_amount": _money(base),
        "base_currency": prop.currency,
        "available_after": _money(left - settled if foreign else left - base),
        "base_available_after": _money(base_left - released if foreign else base_left - base),
        "settlement_currency": credit.currency if foreign else None,
        "settled_amount": _money(settled) if foreign else None,
        "released_base_amount": _money(released) if foreign else None,
        "counter_exchange_rate": counter_rate,
        "exchange_variance_base": _money(variance) if foreign else None,
        "exchange_variance_account": variance_account.name if variance_account else None,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def refund(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "credit", "method", "shift", "amount", "settled_amount",
            "reference", "reason",
            "acceptance"}:
        frappe.throw(_("Revise la devolución del crédito inicial"))
    quote = refund_quote(prop, {key: value for key, value in data.items()
                                if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("El crédito, el medio o el cambio variaron; revise la devolución"))
    before = getattr(frappe.local, "hs_opening_credit_refund", False)
    frappe.local.hs_opening_credit_refund = True
    try:
        payment = insert("HS Payment", prop, shift=quote["shift"],
            method=quote["method"], currency=quote["currency"],
            amount=quote["amount"], exchange_rate=quote["exchange_rate"],
            base_amount=quote["base_amount"], kind="Refund", status="Posted",
            reference=quote["reference"], reason=quote["reason"],
            pms_party=quote["customer"],
            pms_counter_account=quote["receivable_account"],
            pms_opening_credit=quote["credit"],
            pms_settlement_currency=quote["settlement_currency"],
            pms_settled_amount=quote["settled_amount"],
            pms_released_base_amount=quote["released_base_amount"],
            pms_exchange_variance_account=quote["exchange_variance_account"])
        foreign = bool(quote["settlement_currency"])
        receivable_line = {"account": quote["receivable_account"],
            "party": quote["customer"],
            "debit": quote["released_base_amount"] if foreign else quote["base_amount"],
            "credit": "0"}
        if foreign:
            receivable_line.update(account_currency=quote["settlement_currency"],
                exchange_rate=quote["counter_exchange_rate"],
                debit_in_account_currency=quote["settled_amount"],
                credit_in_account_currency="0")
        lines = [receivable_line,
            {"account": quote["cash_account"], "debit": "0",
             "credit": quote["base_amount"],
             "account_currency": quote["currency"],
             "exchange_rate": quote["exchange_rate"],
             "debit_in_account_currency": "0",
             "credit_in_account_currency": quote["amount"]}]
        if foreign and Decimal(quote["exchange_variance_base"]):
            difference = Decimal(quote["exchange_variance_base"])
            lines.append({"account": quote["exchange_variance_account"],
                "debit": _money(max(difference, Decimal(0))),
                "credit": _money(max(-difference, Decimal(0)))})
        journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
            purpose="Opening Credit Refund", memo=quote["reason"], lines=lines)
        payment.pms_journal = journal.name
        payment.save()
    finally:
        frappe.local.hs_opening_credit_refund = before
    audit(prop, "pms_opening_credit_refunded", payment, reason=quote["reason"],
          details={"credit": quote["credit"], "journal": journal.name,
                   "base_amount": quote["base_amount"],
                   "settled_amount": quote["settled_amount"],
                   "released_base_amount": quote["released_base_amount"],
                   "exchange_variance_base": quote["exchange_variance_base"]})
    return {"payment": payment.name, "journal": journal.name,
        "credit_available": quote["available_after"]}


def snapshot(prop):
    credits = frappe.get_all("HS PMS Opening Credit",
        filters={"property": prop.name, "status": "Posted"},
        fields=["name", "credit_kind", "customer", "opening_source_site",
                "opening_source_doctype", "opening_source_name",
                "business_date", "currency", "amount", "base_currency",
                "base_amount", "receivable_account"],
        order_by="creation desc", limit_page_length=200)
    for row in credits:
        nominal, base = balances(prop, row.name)
        row["available"] = _money(nominal)
        row["base_available"] = _money(base)
        if row.opening_source_doctype == "Sales Invoice":
            row["historical_document"] = frappe.db.get_value(
                "HS Historical Fiscal Document", {"property": prop.name,
                    "source_site": row.opening_source_site,
                    "source_doctype": "Sales Invoice",
                    "source_name": row.opening_source_name}, "name")
        else:
            row["historical_document"] = None
    applications = frappe.get_all("HS PMS Allocation",
        filters={"property": prop.name, "kind": "Opening Credit Applied"},
        fields=["name", "opening_credit", "receivable", "amount"],
        order_by="creation desc", limit_page_length=200)
    for row in applications:
        row["remaining"] = _money(remaining_application(prop, row.name))
    return {"credits": credits,
            "applications": [row for row in applications if Decimal(row["remaining"]) > 0]}
