"""Opening vendor credits imported from ERPNext, with no fictional stock return."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from uuid import uuid4

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, post, require_pms
from hospitality_suite.standalone_currency import enabled, latest_rate


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _value(raw):
    try:
        value = amount(raw)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("El importe debe ser positivo"))
    return value


def _text(raw, maximum):
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > maximum:
        frappe.throw(_("Indique un texto válido"))
    return raw.strip()


def _credit(prop, name):
    credit = locked_doc("HS PMS Opening Supplier Credit", name)
    if (credit.property != prop.name or credit.organization != prop.organization or
            credit.status != "Posted"):
        frappe.throw(_("El crédito pertenece a otro establecimiento"), frappe.PermissionError)
    return credit


def available(prop, name):
    return balances(prop, name)[0]


def balances(prop, name):
    credit = _credit(prop, name)
    foreign = credit.currency != prop.currency
    opening_base = Decimal(str(credit.base_amount or credit.amount))
    if foreign and (credit.base_currency != prop.currency or opening_base <= 0):
        frappe.throw(_("El crédito extranjero no conserva su valor base"))
    applications = current_all("HS PMS Supplier Credit Allocation",
        filters={"property": prop.name, "opening_credit": credit.name},
        fields=["amount", "kind", "source_base_amount", "base_currency"])
    refunds = current_all("HS Payment",
        filters={"property": prop.name, "pms_opening_supplier_credit": credit.name,
                 "kind": "Supplier Refund", "status": "Posted"},
        fields=["base_amount", "pms_settlement_currency", "pms_settled_amount",
                "pms_released_base_amount"])
    if foreign and (any(row.base_currency != prop.currency or
            Decimal(str(row.source_base_amount or 0)) <= 0 for row in applications) or
            any(row.pms_settlement_currency != credit.currency or
                Decimal(str(row.pms_settled_amount or 0)) <= 0 or
                Decimal(str(row.pms_released_base_amount or 0)) <= 0 for row in refunds)):
        frappe.throw(_("El crédito extranjero tiene movimientos incompatibles"))
    used_original = sum((Decimal(str(row.amount)) *
        (1 if row.kind == "Applied" else -1) for row in applications), Decimal(0))
    used_base = sum((Decimal(str(row.source_base_amount if foreign else row.amount)) *
        (1 if row.kind == "Applied" else -1) for row in applications), Decimal(0))
    refunded_original = sum((Decimal(str(row.pms_settled_amount if foreign else
        row.base_amount)) for row in refunds), Decimal(0))
    refunded_base = sum((Decimal(str(row.pms_released_base_amount if foreign else
        row.base_amount)) for row in refunds), Decimal(0))
    left = Decimal(str(credit.amount)) - used_original - refunded_original
    base_left = opening_base - used_base - refunded_base
    if left < 0 or base_left < 0 or (left == 0) != (base_left == 0):
        frappe.throw(_("El crédito del proveedor supera su saldo inicial"))
    return left, base_left


def remaining_application(prop, name):
    return application_balances(prop, name)[0]


def application_balances(prop, name):
    original = locked_doc("HS PMS Supplier Credit Allocation", name)
    if original.property != prop.name or original.kind != "Applied":
        frappe.throw(_("Seleccione una aplicación válida"))
    credit = _credit(prop, original.opening_credit)
    foreign = credit.currency != prop.currency
    reversed_rows = current_all(
        "HS PMS Supplier Credit Allocation", filters={"property": prop.name,
            "reverses": original.name, "kind": "Reversed"},
        fields=["amount", "source_base_amount", "target_base_amount"])
    left = Decimal(str(original.amount)) - sum((Decimal(str(row.amount))
        for row in reversed_rows), Decimal(0))
    source_left = Decimal(str(original.source_base_amount if foreign else
        original.amount)) - sum((Decimal(str(row.source_base_amount if foreign else
        row.amount)) for row in reversed_rows), Decimal(0))
    target_left = Decimal(str(original.target_base_amount if foreign else
        original.amount)) - sum((Decimal(str(row.target_base_amount if foreign else
        row.amount)) for row in reversed_rows), Decimal(0))
    if (left < 0 or source_left < 0 or target_left < 0 or
            (left == 0) != (source_left == 0) or
            (left == 0) != (target_left == 0)):
        frappe.throw(_("Las reversiones superan la aplicación"))
    return left, source_left, target_left


def applied_to(prop, target_type, name):
    return applied_balances_to(prop, target_type, name)[0]


def applied_balances_to(prop, target_type, name):
    field = "opening_payable" if target_type == "Opening Payable" else "purchase"
    rows = current_all("HS PMS Supplier Credit Allocation",
        filters={"property": prop.name, "target_type": target_type,
                 field: name}, fields=["kind", "amount", "target_base_amount"])
    original = sum((Decimal(str(row.amount)) *
        (1 if row.kind == "Applied" else -1) for row in rows), Decimal(0))
    base = sum((Decimal(str(row.target_base_amount or row.amount)) *
        (1 if row.kind == "Applied" else -1) for row in rows), Decimal(0))
    return original, base


def target_outstanding(prop, target_type, name):
    if target_type == "Opening Payable":
        from hospitality_suite.standalone_opening_payables import outstanding
    elif target_type == "Purchase":
        from hospitality_suite.standalone_purchases import outstanding
    else:
        frappe.throw(_("Seleccione una deuda de proveedor válida"))
    return outstanding(prop, name)


def _target(prop, target_type, name):
    doctype = {"Opening Payable": "HS PMS Opening Payable",
               "Purchase": "HS PMS Purchase"}.get(target_type)
    if not doctype:
        frappe.throw(_("Seleccione una deuda de proveedor válida"))
    row = locked_doc(doctype, name)
    if (row.property != prop.name or row.organization != prop.organization or
            row.status != "Posted"):
        frappe.throw(_("La deuda no pertenece a este establecimiento"))
    return row


def _allocation(prop, credit, target_type, target, kind, value, reason,
                reverses=None, source_base=None, target_base=None,
                variance_account=None):
    source_account = account(prop, credit.payable_account)
    target_account = account(prop, target.payable_account)
    foreign = credit.currency != prop.currency
    if any(row.root_type != "Liability" or row.account_type != "Payable" or
           row.account_currency != credit.currency for row in
           (source_account, target_account)):
        frappe.throw(_("Las cuentas por pagar ya no son válidas"))
    if foreign:
        if target_type != "Opening Payable" or target.currency != credit.currency:
            frappe.throw(_("El crédito extranjero requiere deuda en la misma moneda"))
        source_base = Decimal(str(source_base))
        target_base = Decimal(str(target_base))
        difference = source_base - target_base
        if (difference and not variance_account) or (
                kind == "Applied" and not difference and variance_account):
            frappe.throw(_("La diferencia cambiaria no coincide"))
        if variance_account:
            variance = account(prop, variance_account)
            if (variance.root_type not in ("Income", "Expense") or
                    variance.account_currency != prop.currency or
                    variance.is_cash or variance.is_bank):
                frappe.throw(_("La cuenta de cambio no es válida"))
        debit_account = target_account.name if kind == "Applied" else source_account.name
        credit_account = source_account.name if kind == "Applied" else target_account.name
        debit_base = target_base if kind == "Applied" else source_base
        credit_base = source_base if kind == "Applied" else target_base
        debit_rate = rate_for_base(value, debit_base)
        credit_rate = rate_for_base(value, credit_base)
        journal = None
        if source_account.name != target_account.name or difference:
            lines = [
                {"account": debit_account, "party": credit.supplier,
                 "debit": _money(debit_base), "credit": "0",
                 "account_currency": credit.currency, "exchange_rate": debit_rate,
                 "debit_in_account_currency": _money(value),
                 "credit_in_account_currency": "0"},
                {"account": credit_account, "party": credit.supplier,
                 "debit": "0", "credit": _money(credit_base),
                 "account_currency": credit.currency, "exchange_rate": credit_rate,
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": _money(value)}]
            variance_value = (difference if kind == "Applied" else -difference)
            if variance_value:
                lines.append({"account": variance_account,
                    "debit": _money(max(variance_value, Decimal(0))),
                    "credit": _money(max(-variance_value, Decimal(0)))})
            journal = post(prop, source_doctype="HS PMS Supplier Credit Allocation",
                source_name=uuid4().hex, purpose="Supplier Credit " + kind,
                memo=reason, lines=lines)
        previous = getattr(frappe.local, "hs_supplier_credit_allocation", False)
        frappe.local.hs_supplier_credit_allocation = True
        try:
            row = insert("HS PMS Supplier Credit Allocation", prop,
                organization=prop.organization, opening_credit=credit.name,
                target_type=target_type, opening_payable=target.name,
                kind=kind, reverses=reverses, business_date=prop.business_date,
                currency=credit.currency, amount=_money(value),
                base_currency=prop.currency,
                source_base_amount=_money(source_base),
                target_base_amount=_money(target_base),
                exchange_variance_account=variance_account,
                journal=journal.name if journal else None, reason=reason)
        finally:
            frappe.local.hs_supplier_credit_allocation = previous
        return row, journal
    journal = None
    if source_account.name != target_account.name:
        debit = target_account.name if kind == "Applied" else source_account.name
        credit_account = source_account.name if kind == "Applied" else target_account.name
        journal = post(prop, source_doctype="HS PMS Supplier Credit Allocation",
            source_name=uuid4().hex, purpose="Supplier Credit " + kind,
            memo=reason, lines=[
                {"account": debit, "party": credit.supplier,
                 "debit": str(value), "credit": "0"},
                {"account": credit_account, "party": credit.supplier,
                 "debit": "0", "credit": str(value)}])
    previous = getattr(frappe.local, "hs_supplier_credit_allocation", False)
    frappe.local.hs_supplier_credit_allocation = True
    try:
        row = insert("HS PMS Supplier Credit Allocation", prop,
            organization=prop.organization, opening_credit=credit.name,
            target_type=target_type,
            opening_payable=target.name if target_type == "Opening Payable" else None,
            purchase=target.name if target_type == "Purchase" else None,
            kind=kind, reverses=reverses, business_date=prop.business_date,
            currency=prop.currency, amount=str(value),
            journal=journal.name if journal else None, reason=reason)
    finally:
        frappe.local.hs_supplier_credit_allocation = previous
    return row, journal


def apply_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {
            "credit", "target_type", "target", "amount", "reason"}:
        frappe.throw(_("Revise la aplicación del crédito del proveedor"))
    credit = _credit(prop, data.get("credit"))
    target_type = data.get("target_type")
    target = _target(prop, target_type, data.get("target"))
    if credit.supplier != target.supplier:
        frappe.throw(_("El crédito y la deuda deben pertenecer al mismo proveedor"))
    if credit.currency != prop.currency:
        if target_type != "Opening Payable" or target.currency != credit.currency:
            frappe.throw(_("El crédito extranjero solo aplica a deuda inicial de la misma moneda"))
        from hospitality_suite.standalone_opening_payables import _balances
        value = _value(data.get("amount"))
        left, source_base_left = balances(prop, credit.name)
        due, target_base_left = _balances(prop, target)
        if value > left or value > due:
            frappe.throw(_("La aplicación supera el crédito o la deuda pendiente"))
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
            rate_for_base(value, source_release)
            rate_for_base(value, target_release)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
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
            "target": target.name, "target_modified": str(target.modified),
            "due": _money(due), "target_base_left": _money(target_base_left),
            "amount": _money(value), "source_base": _money(source_release),
            "target_base": _money(target_release),
            "variance_account": variance_account.name if variance_account else None,
            "reason": reason}
        return {"credit": credit.name, "target_type": target_type,
            "target": target.name, "supplier": credit.supplier,
            "amount": _money(value), "currency": credit.currency,
            "source_account": credit.payable_account,
            "target_account": target.payable_account,
            "source_base_amount": _money(source_release),
            "target_base_amount": _money(target_release),
            "exchange_variance_base": _money(difference),
            "exchange_variance_account":
                variance_account.name if variance_account else None,
            "journal_required": credit.payable_account != target.payable_account
                or bool(difference),
            "available_after": _money(left - value),
            "outstanding_after": _money(due - value),
            "reason": reason,
            "acceptance": sha256(canonical(signature).encode()).hexdigest()}
    value = _value(data.get("amount"))
    left = available(prop, credit.name)
    due = target_outstanding(prop, target_type, target.name)
    if value > left or value > due:
        frappe.throw(_("La aplicación supera el crédito o la deuda pendiente"))
    reason = _text(data.get("reason"), 500)
    signature = {"property": prop.name, "credit": credit.name,
        "credit_modified": str(credit.modified), "available": _money(left),
        "target_type": target_type, "target": target.name,
        "target_modified": str(target.modified), "due": _money(due),
        "source_account": credit.payable_account,
        "target_account": target.payable_account,
        "amount": _money(value), "reason": reason}
    return {"credit": credit.name, "target_type": target_type,
        "target": target.name, "supplier": credit.supplier,
        "amount": _money(value), "currency": prop.currency,
        "source_account": credit.payable_account,
        "target_account": target.payable_account,
        "journal_required": credit.payable_account != target.payable_account,
        "available_after": _money(left - value),
        "outstanding_after": _money(due - value), "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def apply(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "credit", "target_type", "target", "amount", "reason", "acceptance"}:
        frappe.throw(_("Revise la aplicación del crédito"))
    quote = apply_quote(prop, {key: value for key, value in data.items()
                               if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("El saldo cambió; revise la aplicación"))
    credit = _credit(prop, quote["credit"])
    target = _target(prop, quote["target_type"], quote["target"])
    row, journal = _allocation(prop, credit, quote["target_type"], target,
        "Applied", Decimal(quote["amount"]), quote["reason"],
        source_base=quote.get("source_base_amount"),
        target_base=quote.get("target_base_amount"),
        variance_account=quote.get("exchange_variance_account"))
    audit(prop, "pms_opening_supplier_credit_applied", row,
        reason=quote["reason"], details={"journal": journal.name if journal else None})
    return {"allocation": row.name, "journal": journal.name if journal else None,
        "credit_available": quote["available_after"],
        "target_outstanding": quote["outstanding_after"]}


def unapply(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"allocation", "amount", "reason"}:
        frappe.throw(_("Revise la reversión de la aplicación"))
    original = locked_doc("HS PMS Supplier Credit Allocation", data.get("allocation"))
    if original.property != prop.name or original.kind != "Applied":
        frappe.throw(_("Seleccione una aplicación vigente"))
    value = _value(data.get("amount"))
    if value > remaining_application(prop, original.name):
        frappe.throw(_("La reversión supera la aplicación pendiente"))
    credit = _credit(prop, original.opening_credit)
    target_name = original.opening_payable or original.purchase
    target = _target(prop, original.target_type, target_name)
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
        row, journal = _allocation(prop, credit, original.target_type, target,
            "Reversed", value, reason, reverses=original.name,
            source_base=source_restore, target_base=target_restore,
            variance_account=original.exchange_variance_account)
        audit(prop, "pms_opening_supplier_credit_unapplied", row,
            reason=reason, details={"original": original.name,
                                    "journal": journal.name if journal else None})
        return {"allocation": row.name,
            "journal": journal.name if journal else None,
            "credit_available": _money(available(prop, credit.name)),
            "target_outstanding": _money(target_outstanding(prop,
                original.target_type, target.name))}
    row, journal = _allocation(prop, credit, original.target_type, target,
        "Reversed", value, reason, reverses=original.name)
    audit(prop, "pms_opening_supplier_credit_unapplied", row,
        reason=reason, details={"original": original.name,
                                "journal": journal.name if journal else None})
    return {"allocation": row.name, "journal": journal.name if journal else None,
        "credit_available": _money(available(prop, credit.name)),
        "target_outstanding": _money(target_outstanding(prop, original.target_type,
                                                         target.name))}


def refund_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {
            "credit", "method", "shift", "amount", "settled_amount",
            "reference", "reason"}:
        frappe.throw(_("Revise el reintegro del crédito del proveedor"))
    credit = _credit(prop, data.get("credit"))
    foreign = credit.currency != prop.currency
    left, base_left = balances(prop, credit.name)
    if left <= 0:
        frappe.throw(_("El crédito del proveedor ya fue consumido"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio del establecimiento"))
    cash_account = account(prop, method.account)
    payable = account(prop, credit.payable_account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank) or
            payable.root_type != "Liability" or payable.account_type != "Payable" or
            payable.account_currency != credit.currency):
        frappe.throw(_("Las cuentas del reintegro no son válidas"))
    value = _value(data.get("amount"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0 or (not foreign and base > left):
        frappe.throw(_("El reintegro supera el crédito disponible"))
    settled = released = variance = None
    variance_account = None
    counter_rate = "1"
    if foreign:
        raw_settled = data.get("settled_amount")
        if raw_settled in (None, "") and method.currency == credit.currency:
            settled = value
        elif raw_settled in (None, ""):
            frappe.throw(_("Indique cuánto crédito extranjero reintegra"))
        else:
            settled = _value(raw_settled)
        if settled <= 0 or settled > left:
            frappe.throw(_("El reintegro supera el crédito original disponible"))
        released = (base_left if settled == left else
            (base_left * settled / left).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        if released <= 0 or (released >= base_left and settled < left):
            frappe.throw(_("El reintegro no puede liberar ese valor base"))
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
            frappe.throw(_("Se requiere turno propio abierto"), frappe.PermissionError)
    elif data.get("shift"):
        frappe.throw(_("El reintegro bancario no se asigna a un turno"))
    reference = _text(data.get("reference"), 140)
    reason = _text(data.get("reason"), 500)
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "kind": "Supplier Refund", "pms_opening_supplier_credit": credit.name,
            "reference": reference, "status": "Posted"}):
        frappe.throw(_("La referencia ya se aplicó a este crédito"))
    signature = {"property": prop.name, "credit": credit.name,
        "credit_modified": str(credit.modified), "available": _money(left),
        "base_available": _money(base_left),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": _money(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base),
        "settled": _money(settled) if foreign else None,
        "released": _money(released) if foreign else None,
        "variance_account": variance_account.name if variance_account else None,
        "reference": reference, "reason": reason}
    return {"credit": credit.name, "supplier": credit.supplier,
        "payable_account": payable.name, "cash_account": cash_account.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": _money(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "available_after": _money(left - settled if foreign else left - base),
        "base_available_after": _money(base_left - released if foreign else base_left - base),
        "settlement_currency": credit.currency if foreign else None,
        "settled_amount": _money(settled) if foreign else None,
        "released_base_amount": _money(released) if foreign else None,
        "counter_exchange_rate": counter_rate,
        "exchange_variance_base": _money(variance) if foreign else None,
        "exchange_variance_account":
            variance_account.name if variance_account else None,
        "reference": reference,
        "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def refund(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "credit", "method", "shift", "amount", "settled_amount",
            "reference", "reason",
            "acceptance"}:
        frappe.throw(_("Revise el reintegro del proveedor"))
    quote = refund_quote(prop, {key: value for key, value in data.items()
                                if key != "acceptance"})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("El crédito, medio o cambio varió; revise el reintegro"))
    before = getattr(frappe.local, "hs_opening_supplier_credit_refund", False)
    frappe.local.hs_opening_supplier_credit_refund = True
    try:
        payment = insert("HS Payment", prop, shift=quote["shift"],
            method=quote["method"], currency=quote["currency"],
            amount=quote["amount"], exchange_rate=quote["exchange_rate"],
            base_amount=quote["base_amount"], kind="Supplier Refund",
            status="Posted", reference=quote["reference"], reason=quote["reason"],
            pms_settlement_currency=quote["settlement_currency"],
            pms_settled_amount=quote["settled_amount"],
            pms_released_base_amount=quote["released_base_amount"],
            pms_exchange_variance_account=quote["exchange_variance_account"],
            pms_party=quote["supplier"],
            pms_counter_account=quote["payable_account"],
            pms_opening_supplier_credit=quote["credit"])
        payable_line = {"account": quote["payable_account"],
            "party": quote["supplier"], "debit": "0",
            "credit": (quote["released_base_amount"] if quote["settlement_currency"]
                else quote["base_amount"])}
        if quote["settlement_currency"]:
            payable_line.update(account_currency=quote["settlement_currency"],
                exchange_rate=quote["counter_exchange_rate"],
                debit_in_account_currency="0",
                credit_in_account_currency=quote["settled_amount"])
        lines = [{"account": quote["cash_account"],
                    "debit": quote["base_amount"], "credit": "0",
                    "account_currency": quote["currency"],
                    "exchange_rate": quote["exchange_rate"],
                    "debit_in_account_currency": quote["amount"],
                    "credit_in_account_currency": "0"},
                   payable_line]
        if quote["settlement_currency"] and Decimal(quote["exchange_variance_base"]):
            difference = Decimal(quote["exchange_variance_base"])
            lines.append({"account": quote["exchange_variance_account"],
                "debit": _money(max(-difference, Decimal(0))),
                "credit": _money(max(difference, Decimal(0)))})
        journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
            purpose="Opening Supplier Credit Refund", memo=quote["reason"],
            lines=lines)
        payment.pms_journal = journal.name
        payment.save()
    finally:
        frappe.local.hs_opening_supplier_credit_refund = before
    audit(prop, "pms_opening_supplier_credit_refunded", payment,
        reason=quote["reason"], details={"credit": quote["credit"],
            "journal": journal.name, "settled_amount": quote["settled_amount"],
            "released_base_amount": quote["released_base_amount"],
            "exchange_variance_base": quote["exchange_variance_base"]})
    return {"payment": payment.name, "journal": journal.name,
            "credit_available": quote["available_after"]}


def snapshot(prop):
    credits = frappe.get_all("HS PMS Opening Supplier Credit",
        filters={"property": prop.name, "status": "Posted"},
        fields=["name", "supplier", "opening_source_site", "opening_source_name",
                "business_date", "currency", "amount", "base_currency",
                "base_amount", "payable_account"],
        order_by="creation desc", limit_page_length=200)
    for row in credits:
        row["available"], row["base_available"] = map(_money,
            balances(prop, row.name))
    applications = frappe.get_all("HS PMS Supplier Credit Allocation",
        filters={"property": prop.name, "kind": "Applied"},
        fields=["name", "opening_credit", "target_type", "opening_payable",
                "purchase", "currency", "amount", "source_base_amount",
                "target_base_amount"], order_by="creation desc", limit_page_length=200)
    for row in applications:
        row["remaining"] = _money(remaining_application(prop, row.name))
    return {"credits": credits,
            "applications": [row for row in applications
                             if Decimal(row["remaining"]) > 0]}
