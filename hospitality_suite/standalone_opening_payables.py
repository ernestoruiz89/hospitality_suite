"""Settlement of supplier invoices imported as PMS opening balances."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (account,
    account_currency_balance, post, require_pms)
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, latest_rate


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _label(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique un texto válido de hasta {0} caracteres").format(maximum))
    return value.strip()


def _balances(prop, opening):
    if opening.property != prop.name or opening.status != "Posted":
        frappe.throw(_("La deuda inicial pertenece a otro establecimiento"), frappe.PermissionError)
    paid_rows = current_all("HS Payment",
        filters={"property": prop.name, "pms_opening_payable": opening.name,
                 "kind": "Supplier Payment", "status": "Posted",
                 "pms_journal": ["is", "set"]},
        fields=["base_amount", "pms_settled_amount", "pms_released_base_amount",
                "pms_settlement_currency"])
    opening_base = Decimal(str(opening.base_amount or 0))
    if not opening_base and opening.currency == prop.currency:
        opening_base = Decimal(str(opening.amount))
    if opening_base <= 0:
        frappe.throw(_("La deuda inicial no conserva su saldo en moneda base"))
    foreign = opening.currency != prop.currency
    if foreign and any(not row.pms_settled_amount or
            row.pms_settlement_currency != opening.currency or
            not row.pms_released_base_amount for row in paid_rows):
        frappe.throw(_("Un pago extranjero no conserva la deuda liquidada"))
    paid_original = sum((Decimal(str(row.pms_settled_amount or row.base_amount))
        for row in paid_rows), Decimal(0))
    paid_base = sum((Decimal(str(row.pms_released_base_amount or row.base_amount))
        for row in paid_rows), Decimal(0))
    from hospitality_suite.standalone_opening_supplier_credits import applied_balances_to
    credited, credited_base = applied_balances_to(prop, "Opening Payable", opening.name)
    remaining = Decimal(str(opening.amount)) - paid_original - credited
    base_remaining = opening_base - paid_base - credited_base
    if remaining < 0 or base_remaining < 0 or (remaining == 0) != (base_remaining == 0):
        frappe.throw(_("Los pagos superan el saldo inicial del proveedor"))
    return remaining, base_remaining


def outstanding(prop, payable_name):
    opening = locked_doc("HS PMS Opening Payable", payable_name)
    return _balances(prop, opening)[0]


def payment_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {
            "payable", "method", "shift", "amount", "settled_amount",
            "reference", "reason"}:
        frappe.throw(_("Revise el pago de la deuda inicial"))
    opening = locked_doc("HS PMS Opening Payable", data.get("payable"))
    if (opening.property != prop.name or opening.organization != prop.organization or
            opening.status != "Posted"):
        frappe.throw(_("Seleccione una deuda inicial del establecimiento"))
    remaining, base_remaining = _balances(prop, opening)
    if remaining <= 0:
        frappe.throw(_("La deuda inicial ya está pagada"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de pago del establecimiento"))
    cash_account = account(prop, method.account)
    payable = account(prop, opening.payable_account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank) or
            payable.root_type != "Liability" or payable.account_type != "Payable" or
            payable.account_currency != opening.currency):
        frappe.throw(_("Las cuentas del pago inicial ya no son válidas"))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("El pago debe ser positivo"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0:
        frappe.throw(_("El pago es demasiado pequeño para la moneda base"))
    foreign = opening.currency != prop.currency
    if foreign:
        raw_settled = data.get("settled_amount")
        if raw_settled in (None, "") and method.currency == opening.currency:
            settled = value
        elif raw_settled in (None, ""):
            frappe.throw(_("Indique cuánto saldo de la deuda extranjera liquida este pago"))
        else:
            try:
                settled = amount(raw_settled)
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
        if settled <= 0 or settled > remaining:
            frappe.throw(_("El pago supera el saldo original del proveedor"))
        release = (base_remaining if settled == remaining else
            (base_remaining * settled / remaining).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        if release <= 0 or (release >= base_remaining and settled < remaining):
            frappe.throw(_("El abono no puede liberar ese importe del pasivo"))
        try:
            payable_rate = rate_for_base(settled, release)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
    else:
        if base > remaining:
            frappe.throw(_("El pago supera el saldo inicial del proveedor"))
        settled = release = base
        payable_rate = "1"
        if data.get("settled_amount") not in (None, ""):
            try:
                stated_settled = amount(data["settled_amount"])
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
            if stated_settled != base:
                frappe.throw(_("La deuda en moneda base se liquida por el importe convertido"))
    variance = base - release
    variance_account = None
    if variance:
        if not prop.pms_exchange_variance_account:
            frappe.throw(_("Configure la cuenta PMS de diferencia cambiaria"))
        variance_account = account(prop, prop.pms_exchange_variance_account)
        if (variance_account.root_type not in ("Income", "Expense") or
                variance_account.account_currency != prop.currency or
                variance_account.is_cash or variance_account.is_bank):
            frappe.throw(_("La cuenta de diferencia cambiaria ya no es válida"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("Se requiere turno abierto propio para pagar en efectivo"),
                         frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data.get("shift"):
        frappe.throw(_("El pago bancario no se asigna a un turno"))
    if value > Decimal(account_currency_balance(prop, cash_account.name)["balance"]):
        frappe.throw(_("Caja o banco no tiene saldo contable suficiente"))
    reference = _label(data.get("reference"), 140)
    reason = _label(data.get("reason"), 500)
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "kind": "Supplier Payment", "pms_opening_payable": opening.name,
            "reference": reference, "status": "Posted"}):
        frappe.throw(_("La referencia ya se aplicó a esta deuda inicial"))
    signature = {"property": prop.name, "payable": opening.name,
        "payable_modified": str(opening.modified), "remaining": _money(remaining),
        "base_remaining": _money(base_remaining),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": str(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "settled": _money(settled),
        "release": _money(release), "payable_rate": payable_rate,
        "variance": _money(variance),
        "variance_account": variance_account.name if variance_account else None,
        "reference": reference, "reason": reason}
    return {"payable": opening.name, "supplier": opening.supplier,
        "payable_account": payable.name, "cash_account": cash_account.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "settled_amount": _money(settled), "settlement_currency": opening.currency,
        "payable_release_base": _money(release),
        "payable_exchange_rate": payable_rate,
        "exchange_variance_base": _money(variance),
        "exchange_variance_account": variance_account.name if variance_account else None,
        "outstanding_before": _money(remaining),
        "outstanding_after": _money(remaining - settled),
        "base_outstanding_before": _money(base_remaining),
        "base_outstanding_after": _money(base_remaining - release),
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def pay(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "payable", "method", "shift", "amount", "settled_amount",
            "reference", "reason",
            "acceptance"}:
        frappe.throw(_("Revise el pago de la deuda inicial"))
    reviewed = payment_quote(prop, {key: value for key, value in data.items()
                                    if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("El saldo, el medio o el cambio variaron; revise el pago"))
    payment = insert("HS Payment", prop, shift=reviewed["shift"],
        method=reviewed["method"], currency=reviewed["currency"],
        amount=reviewed["amount"], exchange_rate=reviewed["exchange_rate"],
        base_amount=reviewed["base_amount"], kind="Supplier Payment",
        pms_settlement_currency=reviewed["settlement_currency"],
        pms_settled_amount=reviewed["settled_amount"],
        pms_released_base_amount=reviewed["payable_release_base"],
        pms_exchange_variance_account=reviewed["exchange_variance_account"],
        status="Posted", reference=reviewed["reference"],
        reason=reviewed["reason"], pms_party=reviewed["supplier"],
        pms_counter_account=reviewed["payable_account"],
        pms_opening_payable=reviewed["payable"])
    lines = [{"account": reviewed["payable_account"],
              "debit": reviewed["payable_release_base"], "credit": 0,
              "party": reviewed["supplier"],
              "account_currency": reviewed["settlement_currency"],
              "exchange_rate": reviewed["payable_exchange_rate"],
              "debit_in_account_currency": reviewed["settled_amount"],
              "credit_in_account_currency": 0},
             {"account": reviewed["cash_account"], "debit": 0,
              "credit": reviewed["base_amount"],
              "account_currency": reviewed["currency"],
              "exchange_rate": reviewed["exchange_rate"],
              "debit_in_account_currency": 0,
              "credit_in_account_currency": reviewed["amount"]}]
    variance = Decimal(reviewed["exchange_variance_base"])
    if variance:
        lines.append({"account": reviewed["exchange_variance_account"],
                      "debit": _money(max(variance, Decimal(0))),
                      "credit": _money(max(-variance, Decimal(0)))})
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
        purpose="Supplier Payment", memo=reviewed["reason"],
        lines=lines)
    payment.pms_journal = journal.name
    payment.save()
    audit(prop, "pms_opening_supplier_paid", payment,
          reason=reviewed["reason"],
          details={"payable": reviewed["payable"], "journal": journal.name,
                   "base_amount": reviewed["base_amount"],
                   "settled_amount": reviewed["settled_amount"],
                   "payable_release_base": reviewed["payable_release_base"],
                   "exchange_variance_base": reviewed["exchange_variance_base"],
                   "rate_record": reviewed["rate_record"]})
    return {"payment": payment.name, "journal": journal.name,
            "payable": reviewed["payable"],
            "base_amount": reviewed["base_amount"],
            "settled_amount": reviewed["settled_amount"],
            "settlement_currency": reviewed["settlement_currency"],
            "exchange_variance_base": reviewed["exchange_variance_base"],
            "outstanding": reviewed["outstanding_after"]}


def snapshot(prop):
    rows = frappe.get_all("HS PMS Opening Payable",
        filters={"property": prop.name, "status": "Posted"},
        fields=["name", "supplier", "opening_source_name", "business_date",
                "due_date", "currency", "amount", "base_amount", "payable_account"],
        order_by="creation desc", limit_page_length=200)
    for row in rows:
        row["outstanding"], row["base_outstanding"] = map(_money,
            _balances(prop, locked_doc("HS PMS Opening Payable", row.name)))
    return rows
