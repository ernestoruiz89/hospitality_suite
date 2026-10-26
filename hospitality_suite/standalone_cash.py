"""Multicurrency cash/bank receipts, other income and expenses in PMS mode."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
from hospitality_suite.security import require
from hospitality_suite.service import assert_version, audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, account_currency_balance, post, require_pms
from hospitality_suite.standalone_currency import enabled, latest_rate


def _money(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _label(value, field):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 140:
        frappe.throw(_("Indique {0} de hasta 140 caracteres").format(field))
    return value.strip()


def validate_method(doc):
    prop = frappe.get_doc("HS Property", doc.property)
    if not enabled(prop, doc.currency):
        frappe.throw(_("La moneda del medio de pago no está habilitada"))
    selected = account(prop, doc.account)
    if selected.account_currency != doc.currency or not (selected.is_cash or selected.is_bank):
        frappe.throw(_("El medio requiere una cuenta de Caja o banco en su misma moneda"))
    if bool(doc.is_cash) != bool(selected.is_cash):
        frappe.throw(_("La clasificación de efectivo no coincide con la cuenta"))
    _label(doc.mode_of_payment, _("el nombre del medio de pago"))
    old = doc.get_doc_before_save()
    if old and any(old.get(field) != doc.get(field) for field in
                   ("property", "company", "account", "currency", "is_cash", "mode_of_payment")):
        if (frappe.db.exists("HS Payment", {"method": doc.name}) or
                frappe.db.exists("HS Treasury Movement", {"method": doc.name,
                    "pms_journal": ["is", "set"]})):
            frappe.throw(_("Conserve los datos del medio utilizado; cree otro medio de pago"))


def validate_category(doc):
    prop = frappe.get_doc("HS Property", doc.property)
    selected = account(prop, doc.account)
    try:
        doc.max_amount = str(amount(doc.max_amount or 0))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if selected.root_type != "Expense" or selected.account_currency != prop.currency:
        frappe.throw(_("La categoría requiere una cuenta de gasto en moneda base y límite no negativo"))
    doc.currency = prop.currency
    _label(doc.label, _("el nombre de la categoría"))


def validate_concept(doc):
    prop = frappe.get_doc("HS Property", doc.property)
    selected = account(prop, doc.account)
    expected = {"Other Income": "Income", "Loan": "Liability", "Capital": "Equity"}.get(doc.nature)
    if not expected or selected.root_type != expected or selected.account_currency != prop.currency:
        frappe.throw(_("El concepto requiere una cuenta de su naturaleza en moneda base"))
    doc.currency = prop.currency
    _label(doc.label, _("el nombre del concepto"))


def setup_method(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"label", "account"}:
        frappe.throw(_("Revise el medio de pago"))
    selected = account(prop, data.get("account"))
    if not (selected.is_cash or selected.is_bank):
        frappe.throw(_("Seleccione una cuenta de Caja o banco"))
    doc = insert("HS Payment Method", prop, mode_of_payment=_label(data.get("label"), "el medio"),
        account=selected.name, currency=selected.account_currency,
        is_cash=int(selected.is_cash), reference_required=int(selected.is_bank))
    audit(prop, "pms_payment_method_created", doc)
    return {"method": doc.name}


def setup_category(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"label", "account", "max_amount"}:
        frappe.throw(_("Revise la categoría de gasto"))
    doc = insert("HS Expense Category", prop, label=_label(data.get("label"), "la categoría"),
                 account=data.get("account"), max_amount=data.get("max_amount") or 0, active=1)
    audit(prop, "pms_expense_category_created", doc)
    return {"category": doc.name}


def setup_concept(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if (not isinstance(data, dict) or
            set(data) - {"label", "account", "nature", "active"} or
            data.get("active", 1) not in (0, 1, False, True)):
        frappe.throw(_("Revise el concepto financiero"))
    doc = insert("HS Treasury Concept", prop, label=_label(data.get("label"), "el concepto"),
                 account=data.get("account"), nature=data.get("nature"),
                 active=int(data.get("active", 1)))
    audit(prop, "pms_financial_concept_created", doc)
    return {"concept": doc.name}


def update_concept(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if (not isinstance(data, dict) or
            set(data) != {"concept", "modified", "label", "nature", "account", "active"} or
            data["active"] not in (0, 1, False, True)):
        frappe.throw(_("Revise el concepto financiero"))
    doc = locked_doc("HS Treasury Concept", data["concept"])
    if doc.property != prop.name or doc.company != prop.company:
        frappe.throw(_("El concepto no pertenece a este establecimiento"), frappe.PermissionError)
    assert_version(doc, data["modified"])
    doc.label = data["label"]
    doc.nature = data["nature"]
    doc.account = data["account"]
    doc.active = int(data["active"])
    doc.save()
    audit(prop, "pms_financial_concept_updated", doc)
    return {"concept": doc.name}


def create_customer(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"party_name", "tax_id"}:
        frappe.throw(_("Revise los datos del cliente"))
    tax_id = data.get("tax_id") or ""
    if not isinstance(tax_id, str) or len(tax_id.strip()) > 140:
        frappe.throw(_("Revise la identificación del cliente"))
    doc = insert("HS Party", prop, organization=prop.organization,
                 party_name=_label(data.get("party_name"), "el nombre del cliente"),
                 party_type="Customer", tax_id=tax_id.strip(), active=1)
    audit(prop, "pms_customer_created", doc)
    return {"party": doc.name}


def customers(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    return frappe.get_all("HS Party", filters={"property": prop.name, "active": 1,
                                              "party_type": ["in", ["Customer", "Both"]]},
                          fields=["name", "party_name", "tax_id"], order_by="party_name asc",
                          limit_page_length=500)


def open_shift(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if current_all("HS Shift", filters={"property": prop.name, "cashier": frappe.session.user,
                                        "status": "Open"}, pluck="name"):
        frappe.throw(_("Ya tiene un turno de Caja abierto"))
    opening = data.get("opening_by_currency") if isinstance(data, dict) else None
    if opening is None:
        opening = {prop.currency: "0.00"}
    if not isinstance(opening, dict) or not opening:
        frappe.throw(_("Indique el efectivo inicial por moneda"))
    normalized = {}
    for currency, value in opening.items():
        if not enabled(prop, currency):
            frappe.throw(_("El efectivo inicial usa una moneda no habilitada"))
        try:
            normalized[currency] = str(amount(value))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
    normalized.setdefault(prop.currency, "0.00")
    doc = insert("HS Shift", prop, cashier=frappe.session.user, opened_at=now_datetime(),
                 status="Open", currency=prop.currency,
                 opening_amount=normalized[prop.currency], opening_by_currency=canonical(normalized))
    audit(prop, "pms_shift_opened", doc, details={"opening_by_currency": normalized})
    return {"shift": doc.name, "expected": normalized}


def expected(shift):
    opening = frappe.parse_json(shift.opening_by_currency or "{}")
    amounts = {currency: Decimal(str(value)) for currency, value in opening.items()}
    for row in current_all("HS Payment", filters={"shift": shift.name, "status": "Posted"},
                           fields=["amount", "currency", "kind", "method"]):
        if not frappe.db.get_value("HS Payment Method", row.method, "is_cash"):
            continue
        sign = -1 if row.kind in ("Expense", "Refund", "Guarantee Refund", "Supplier Payment") else 1
        amounts[row.currency] = amounts.get(row.currency, Decimal(0)) + sign * Decimal(str(row.amount))
    for row in current_all("HS Treasury Movement", filters={"shift": shift.name,
            "status": "Posted", "pms_journal": ["is", "set"]},
            fields=["kind", "currency", "amount", "method"]):
        if not row.method or not frappe.db.get_value("HS Payment Method", row.method, "is_cash"):
            continue
        sign = -1 if row.kind in ("Loan Repayment", "Capital Withdrawal",
                                  "Initial Fund", "Replenishment") else 1
        amounts[row.currency] = amounts.get(row.currency, Decimal(0)) + sign * Decimal(str(row.amount))
    return {currency: _money(value) for currency, value in amounts.items()}


def close_shift(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"shift", "counted_by_currency"}:
        frappe.throw(_("Revise el arqueo de Caja"))
    shift = locked_doc("HS Shift", data.get("shift"))
    if shift.property != prop.name or shift.status != "Open" or shift.cashier != frappe.session.user:
        frappe.throw(_("Seleccione un turno abierto propio"), frappe.PermissionError)
    counted = data.get("counted_by_currency")
    if not isinstance(counted, dict):
        frappe.throw(_("Indique el efectivo contado por moneda"))
    actual = {}
    for currency, value in counted.items():
        if not enabled(prop, currency):
            frappe.throw(_("El arqueo contiene una moneda no habilitada"))
        try:
            actual[currency] = str(amount(value))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
    anticipated = expected(shift)
    if any(Decimal(actual.get(currency, "0")) != Decimal(anticipated.get(currency, "0"))
           for currency in set(actual) | set(anticipated)):
        frappe.throw(_("El arqueo no coincide. Registre y apruebe la diferencia antes de cerrar"))
    shift.expected_amount = anticipated.get(prop.currency, "0")
    shift.counted_amount = actual.get(prop.currency, "0")
    shift.difference = 0
    shift.denominations = canonical({"expected": anticipated, "counted": actual})
    shift.status = "Closed"
    shift.closed_at = now_datetime()
    shift.save()
    audit(prop, "pms_shift_closed", shift, details={"counted_by_currency": actual})
    return {"shift": shift.name, "status": "Closed", "expected": anticipated}


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"kind", "amount", "method", "shift", "reference",
                                              "reason", "party", "counter_account", "category", "concept",
                                              "receivable", "folio", "booking", "settled_amount",
                                              "expected_exchange_rate", "expected_rate_record",
                                              "expected_debit", "expected_credit",
                                              "expected_settled_amount", "expected_released_base_amount",
                                              "expected_exchange_variance_base"}:
        frappe.throw(_("Revise los datos del movimiento"))
    kind = data.get("kind")
    if kind not in ("Payment", "Advance", "Guarantee", "Other Income", "Expense"):
        frappe.throw(_("Seleccione cobro, anticipo, garantía, otro ingreso o gasto"))
    if kind != "Guarantee" and (data.get("folio") or data.get("booking")):
        frappe.throw(_("La reserva o la cuenta de estancia solo corresponden a una garantía"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name:
        frappe.throw(_("El medio pertenece a otro establecimiento"), frappe.PermissionError)
    selected = account(prop, method.account)
    if not enabled(prop, method.currency) or selected.account_currency != method.currency:
        frappe.throw(_("El medio o su moneda ya no están habilitados"))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("El importe debe ser mayor que cero"))
    rate, rate_ref = latest_rate(prop, method.currency)
    if data.get("expected_exchange_rate") is not None:
        try:
            reviewed_rate = Decimal(str(data["expected_exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError):
            frappe.throw(_("El tipo de cambio revisado no es válido"))
        if reviewed_rate != rate or data.get("expected_rate_record") != rate_ref:
            frappe.throw(_("El tipo de cambio cambió; revise nuevamente el asiento"))
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    reference = _label(data.get("reference"), "una referencia")
    reason = _label(data.get("reason"), "un motivo")
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if shift.property != prop.name or shift.status != "Open" or shift.cashier != frappe.session.user:
            frappe.throw(_("Se requiere un turno abierto propio para efectivo"), frappe.PermissionError)
        if kind == "Expense" and value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("Efectivo insuficiente en la moneda seleccionada"))
        if kind == "Expense" and value > Decimal(account_currency_balance(prop, selected.name)["balance"]):
            frappe.throw(_("El saldo contable de Caja en esta moneda es insuficiente"))
    elif data.get("shift"):
        frappe.throw(_("Los movimientos bancarios no se asignan a un turno"))
    party = category = concept = receivable = folio = booking = None
    foreign = False
    settled = released = base
    counter_rate = "1"
    variance = Decimal(0)
    variance_account = None
    if kind == "Payment":
        from hospitality_suite.standalone_receivables import opening_balances, outstanding
        receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
        if receivable.property != prop.name or receivable.status != "Posted":
            frappe.throw(_("Seleccione una cuenta por cobrar del establecimiento"))
        foreign = receivable.currency != prop.currency
        if foreign:
            remaining, base_remaining = opening_balances(prop, receivable.name)
            raw_settled = data.get("settled_amount")
            if raw_settled in (None, "") and method.currency == receivable.currency:
                settled = value
            elif raw_settled in (None, ""):
                frappe.throw(_("Indique cuánto saldo extranjero liquida el cobro"))
            else:
                try:
                    settled = amount(raw_settled)
                except LedgerValidationError as exc:
                    frappe.throw(str(exc))
            if settled <= 0 or settled > remaining:
                frappe.throw(_("El cobro supera el saldo original del cliente"))
            released = (base_remaining if settled == remaining else
                (base_remaining * settled / remaining).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP))
            if released <= 0 or (released >= base_remaining and settled < remaining):
                frappe.throw(_("El abono no puede liberar ese valor de cartera"))
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
                    frappe.throw(_("Configure una cuenta PMS válida de diferencia cambiaria"))
            if (data.get("expected_settled_amount") != _money(settled) or
                    data.get("expected_released_base_amount") != _money(released) or
                    data.get("expected_exchange_variance_base") != _money(variance)) and any(
                    key in data for key in ("expected_settled_amount",
                        "expected_released_base_amount", "expected_exchange_variance_base")):
                frappe.throw(_("La liquidación o el cambio variaron; revise el cobro"))
        elif base > outstanding(prop, receivable.name):
            frappe.throw(_("El cobro supera el saldo; registre el excedente como anticipo"))
        elif data.get("settled_amount") not in (None, ""):
            frappe.throw(_("La cartera en moneda base se liquida por el valor convertido"))
        counter = account(prop, receivable.receivable_account)
        party = receivable.party
    elif data.get("settled_amount") not in (None, ""):
        frappe.throw(_("El principal liquidado solo corresponde a una cuenta por cobrar"))
    elif kind in ("Advance", "Guarantee"):
        counter = account(prop, data.get("counter_account"))
        if counter.root_type != "Liability" or counter.account_currency != prop.currency:
            frappe.throw(_("El anticipo o garantía requiere una cuenta de pasivo en moneda base"))
        party = data.get("party")
        customer = frappe.db.get_value("HS Party", party,
            ["property", "party_type", "active"], as_dict=True) if party else None
        if not customer or customer.property != prop.name or not customer.active or customer.party_type not in ("Customer", "Both"):
            frappe.throw(_("Seleccione un cliente activo del establecimiento"))
        if kind == "Guarantee":
            if bool(data.get("folio")) == bool(data.get("booking")):
                frappe.throw(_("Vincule la garantía a una reserva o una cuenta de estancia"))
            if data.get("folio"):
                folio = locked_doc("HS Folio", data["folio"])
                if (folio.property != prop.name or folio.company != prop.company or
                        folio.customer != party or folio.status != "Open"):
                    frappe.throw(_("Seleccione una cuenta de estancia abierta del mismo cliente y establecimiento"))
            else:
                booking = locked_doc("HS Booking", data["booking"])
                if (booking.property != prop.name or booking.company != prop.company or
                        booking.customer != party or booking.status not in ("Hold", "Confirmed", "Checked In") or
                        (booking.status == "Hold" and
                         (not booking.hold_until or get_datetime(booking.hold_until) <= now_datetime()))):
                    frappe.throw(_("Seleccione una reserva vigente del mismo cliente y establecimiento"))
    elif kind == "Other Income":
        concept = locked_doc("HS Treasury Concept", data.get("concept"))
        if concept.property != prop.name or concept.nature != "Other Income" or not concept.active:
            frappe.throw(_("Seleccione un concepto de ingreso activo del establecimiento"))
        counter = account(prop, concept.account)
    else:
        category = locked_doc("HS Expense Category", data.get("category"))
        if category.property != prop.name or not category.active:
            frappe.throw(_("Seleccione una categoría de gasto activa del establecimiento"))
        counter = account(prop, category.account)
        if category.max_amount and base > Decimal(str(category.max_amount)):
            frappe.throw(_("El gasto supera el límite de la categoría"))
    if counter.account_currency != (receivable.currency if foreign else prop.currency):
        frappe.throw(_("La contrapartida debe usar la moneda base"))
    debit = selected.name if kind != "Expense" else counter.name
    credit = counter.name if kind != "Expense" else selected.name
    if (data.get("expected_debit") is not None and data["expected_debit"] != debit or
            data.get("expected_credit") is not None and data["expected_credit"] != credit):
        frappe.throw(_("Las cuentas cambiaron; revise nuevamente el asiento"))
    return {"kind": kind, "amount": str(value), "currency": method.currency,
            "exchange_rate": str(rate), "exchange_rate_record": rate_ref,
            "base_amount": str(base), "base_currency": prop.currency,
            "cash_account": selected.name, "counter_account": counter.name,
            "method": method.name, "shift": shift.name if shift else None,
            "reference": reference, "reason": reason, "party": party,
            "category": category.name if category else None,
            "concept": concept.name if concept else None,
            "receivable": receivable.name if receivable else None,
            "folio": folio.name if folio else None,
            "booking": booking.name if booking else None,
            "debit": debit, "credit": credit,
            "settlement_currency": receivable.currency if foreign else None,
            "settled_amount": _money(settled) if foreign else None,
            "released_base_amount": _money(released) if foreign else None,
            "counter_exchange_rate": counter_rate,
            "exchange_variance_base": _money(variance) if foreign else None,
            "exchange_variance_account": variance_account.name if variance_account else None}


def post_movement(prop, data):
    q = quote(prop, data)
    foreign = bool(q["settlement_currency"])
    if foreign and (data.get("expected_settled_amount") != q["settled_amount"] or
            data.get("expected_released_base_amount") != q["released_base_amount"] or
            data.get("expected_exchange_variance_base") != q["exchange_variance_base"]):
        frappe.throw(_("Revise el principal y la diferencia cambiaria antes de cobrar"))
    cash_line = {"account": q["cash_account"], "debit": q["base_amount"] if q["kind"] != "Expense" else "0",
                 "credit": q["base_amount"] if q["kind"] == "Expense" else "0",
                 "account_currency": q["currency"], "exchange_rate": q["exchange_rate"],
                 "debit_in_account_currency": q["amount"] if q["kind"] != "Expense" else "0",
                 "credit_in_account_currency": q["amount"] if q["kind"] == "Expense" else "0"}
    counter_line = {"account": q["counter_account"],
                    "debit": q["base_amount"] if q["kind"] == "Expense" else "0",
                    "credit": q["released_base_amount"] if foreign else
                              q["base_amount"] if q["kind"] != "Expense" else "0",
                    "party": q["party"]}
    if foreign:
        counter_line.update(account_currency=q["settlement_currency"],
            exchange_rate=q["counter_exchange_rate"],
            debit_in_account_currency="0",
            credit_in_account_currency=q["settled_amount"])
    payment = insert("HS Payment", prop, shift=q["shift"], method=q["method"],
                     folio=q["folio"], booking=q["booking"],
                     currency=q["currency"], amount=q["amount"],
                     exchange_rate=q["exchange_rate"], base_amount=q["base_amount"],
                     kind=q["kind"], status="Posted", reference=q["reference"], reason=q["reason"],
                     pms_party=q["party"], pms_counter_account=q["counter_account"],
                     pms_concept=q["concept"], pms_receivable=q["receivable"],
                     pms_settlement_currency=q["settlement_currency"],
                     pms_settled_amount=q["settled_amount"],
                     pms_released_base_amount=q["released_base_amount"],
                     pms_exchange_variance_account=q["exchange_variance_account"],
                     expense_category=q["category"])
    lines = [cash_line, counter_line]
    if foreign and Decimal(q["exchange_variance_base"]):
        difference = Decimal(q["exchange_variance_base"])
        lines.append({"account": q["exchange_variance_account"],
            "debit": _money(max(-difference, Decimal(0))),
            "credit": _money(max(difference, Decimal(0)))})
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
                   purpose=q["kind"], lines=lines, memo=q["reason"])
    payment.pms_journal = journal.name
    payment.save()
    allocation_name = None
    if q["receivable"]:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
                     receivable=q["receivable"], payment=payment.name, kind="Direct",
                     business_date=prop.business_date, currency=prop.currency,
                     amount=q["released_base_amount"] if foreign else q["base_amount"],
                     settlement_currency=q["settlement_currency"],
                     settled_amount=q["settled_amount"], journal=journal.name)
        allocation_name = row.name
    audit(prop, "pms_cash_movement_posted", payment, reason=q["reason"], details={
        "journal": journal.name, "currency": q["currency"], "amount": q["amount"],
        "exchange_rate": q["exchange_rate"], "rate_record": q["exchange_rate_record"],
        "settled_amount": q["settled_amount"],
        "released_base_amount": q["released_base_amount"],
        "exchange_variance_base": q["exchange_variance_base"]})
    return {"payment": payment.name, "journal": journal.name, "allocation": allocation_name,
            "kind": q["kind"],
            "amount": q["amount"], "currency": q["currency"], "base_amount": q["base_amount"],
            "settled_amount": q["settled_amount"],
            "released_base_amount": q["released_base_amount"],
            "exchange_variance_base": q["exchange_variance_base"]}


def refund_quote(prop, data):
    """Value a refund at its receipt's frozen FX rate and original accounts."""
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"source_payment", "amount", "shift", "reference", "reason",
                                              "expected_base_amount", "expected_debit", "expected_credit",
                                              "expected_settled_amount", "expected_released_base_amount",
                                              "expected_exchange_variance_base"}:
        frappe.throw(_("Revise los datos de la devolución"))
    source = locked_doc("HS Payment", data.get("source_payment"))
    if (source.property != prop.name or source.kind not in ("Payment", "Advance", "Guarantee") or
            source.status != "Posted" or not source.pms_journal or source.source_payment):
        frappe.throw(_("Seleccione un cobro, anticipo o garantía PMS vigente del establecimiento"))
    foreign = bool(source.pms_settlement_currency)
    if foreign and source.kind != "Payment":
        frappe.throw(_("Solo un cobro de cartera admite liquidación extranjera"))
    method = locked_doc("HS Payment Method", source.method)
    if method.property != prop.name or method.currency != source.currency:
        frappe.throw(_("El medio de pago original no coincide"))
    cash_account = account(prop, method.account)
    if cash_account.account_currency != source.currency or not (cash_account.is_cash or cash_account.is_bank):
        frappe.throw(_("La cuenta original de Caja o banco no es válida"))
    counter = account(prop, source.pms_counter_account)
    if (counter.account_currency != (source.pms_settlement_currency if foreign else prop.currency) or
            (source.kind in ("Advance", "Guarantee") and counter.root_type != "Liability") or
            (source.kind == "Payment" and (counter.root_type != "Asset" or
                                           counter.account_type != "Receivable"))):
        frappe.throw(_("La contrapartida original no es válida"))
    from hospitality_suite.standalone_receivables import deposit_available, remaining_allocation

    refunded = current_all("HS Payment", filters={"property": prop.name,
        "source_payment": source.name,
        "kind": "Guarantee Refund" if source.kind == "Guarantee" else "Refund",
        "status": "Posted"},
        fields=["amount", "base_amount", "pms_settled_amount",
                "pms_released_base_amount"])
    prior_currency = sum((Decimal(str(row.amount)) for row in refunded), Decimal(0))
    prior_base = sum((Decimal(str(row.base_amount)) for row in refunded), Decimal(0))
    remaining_currency = Decimal(str(source.amount)) - prior_currency
    remaining_cash_base = Decimal(str(source.base_amount)) - prior_base
    if source.kind == "Payment":
        allocations = current_all("HS PMS Allocation", filters={"property": prop.name,
            "payment": source.name, "kind": "Direct"}, fields=["name", "amount", "receivable"])
        if len(allocations) != 1 or allocations[0].receivable != source.pms_receivable:
            frappe.throw(_("El cobro original no tiene una aplicación directa única"))
        allocation = allocations[0]
        remaining_base = remaining_allocation(prop, allocation.name)
        if foreign:
            prior_settled = sum((Decimal(str(row.pms_settled_amount or 0))
                for row in refunded), Decimal(0))
            remaining_settled = Decimal(str(source.pms_settled_amount)) - prior_settled
            remaining_released = Decimal(str(source.pms_released_base_amount)) - sum(
                (Decimal(str(row.pms_released_base_amount or 0)) for row in refunded),
                Decimal(0))
            if (remaining_settled <= 0 or remaining_released != remaining_base or
                    remaining_currency <= 0 or remaining_cash_base <= 0):
                frappe.throw(_("La devolución extranjera no concilia con la aplicación original"))
        if frappe.db.get_value("HS PMS Receivable", allocation.receivable, "status") != "Posted":
            frappe.throw(_("La cuenta por cobrar original no está vigente"))
    else:
        allocation = None
        remaining_base = deposit_available(prop, source.name, source.kind)
        rate = Decimal(str(source.exchange_rate))
        remaining_currency = min(remaining_currency,
            (remaining_base / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0 or value > remaining_currency:
        frappe.throw(_("La devolución supera el importe original pendiente"))
    original_rate = Decimal(str(source.exchange_rate))
    base = (value * original_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value == remaining_currency:
        base = remaining_cash_base if foreign else remaining_base
    if base <= 0 or base > (remaining_cash_base if foreign else remaining_base):
        frappe.throw(_("La devolución supera el saldo contable disponible"))
    rate = original_rate
    if base != (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        rate = (base / value).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
        if (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != base:
            frappe.throw(_("El redondeo impide devolver este importe; ajuste la fracción"))
    settled = released = difference = None
    variance_account = None
    if foreign:
        settled = (remaining_settled if value == remaining_currency else
            (remaining_settled * value / remaining_currency).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        released = (remaining_released if value == remaining_currency else
            (remaining_released * settled / remaining_settled).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        if Decimal(str(source.base_amount)) == Decimal(str(source.pms_released_base_amount)):
            released = base
        if (settled <= 0 or settled >= remaining_settled and value < remaining_currency or
                released <= 0 or released >= remaining_released and
                value < remaining_currency):
            frappe.throw(_("La fracción no puede restaurar la cartera extranjera; aumente el importe"))
        difference = base - released
        if source.pms_exchange_variance_account:
            variance_account = account(prop, source.pms_exchange_variance_account)
            if (variance_account.root_type not in ("Income", "Expense") or
                    variance_account.account_currency != prop.currency or
                    variance_account.is_cash or variance_account.is_bank):
                frappe.throw(_("La cuenta original de diferencia cambiaria no es válida"))
        if difference and not variance_account:
            frappe.throw(_("El cambio original no permite contabilizar esta devolución"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if shift.property != prop.name or shift.status != "Open" or shift.cashier != frappe.session.user:
            frappe.throw(_("Se requiere un turno abierto propio para la devolución"), frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("Efectivo insuficiente en el turno"))
    elif data.get("shift"):
        frappe.throw(_("Las devoluciones bancarias no se asignan a un turno"))
    if value > Decimal(account_currency_balance(prop, cash_account.name)["balance"]):
        frappe.throw(_("Saldo contable insuficiente en Caja o banco"))
    reference = _label(data.get("reference"), "una referencia")
    reason = _label(data.get("reason"), "un motivo")
    if (data.get("expected_base_amount") is not None and
            str(data["expected_base_amount"]) != _money(base) or
            data.get("expected_debit") is not None and data["expected_debit"] != counter.name or
            data.get("expected_credit") is not None and data["expected_credit"] != cash_account.name):
        frappe.throw(_("El saldo o las cuentas cambiaron; revise nuevamente el asiento"))
    if foreign and any(key in data for key in ("expected_settled_amount",
            "expected_released_base_amount", "expected_exchange_variance_base")) and (
            data.get("expected_settled_amount") != _money(settled) or
            data.get("expected_released_base_amount") != _money(released) or
            data.get("expected_exchange_variance_base") != _money(difference)):
        frappe.throw(_("La liquidación original cambió; revise nuevamente la devolución"))
    return {"source_payment": source.name, "kind": source.kind, "amount": str(value),
            "currency": source.currency, "base_amount": _money(base), "base_currency": prop.currency,
            "exchange_rate": str(rate), "debit": counter.name, "credit": cash_account.name,
            "party": source.pms_party, "receivable": source.pms_receivable,
            "allocation": allocation.name if allocation else None,
            "method": method.name, "shift": shift.name if shift else None,
            "reference": reference, "reason": reason,
            "remaining_currency": _money(remaining_currency - value),
            "remaining_base": _money((remaining_cash_base if foreign else remaining_base) - base),
            "settlement_currency": source.pms_settlement_currency if foreign else None,
            "settled_amount": _money(settled) if foreign else None,
            "released_base_amount": _money(released) if foreign else None,
            "counter_exchange_rate": rate_for_base(settled, released) if foreign else "1",
            "exchange_variance_base": _money(difference) if foreign else None,
            "exchange_variance_account": variance_account.name if variance_account else None}


def refund(prop, data):
    q = refund_quote(prop, data)
    foreign = bool(q["settlement_currency"])
    if foreign and (data.get("expected_base_amount") != q["base_amount"] or
            data.get("expected_debit") != q["debit"] or
            data.get("expected_credit") != q["credit"] or
            data.get("expected_settled_amount") != q["settled_amount"] or
            data.get("expected_released_base_amount") != q["released_base_amount"] or
            data.get("expected_exchange_variance_base") != q["exchange_variance_base"]):
        frappe.throw(_("Revise el principal, las cuentas y el cambio antes de devolver"))
    source = locked_doc("HS Payment", q["source_payment"])
    refund_doc = insert("HS Payment", prop, shift=q["shift"], method=q["method"],
        folio=source.folio if q["kind"] == "Guarantee" else None,
        booking=source.booking if q["kind"] == "Guarantee" else None,
        currency=q["currency"], amount=q["amount"], exchange_rate=q["exchange_rate"],
        base_amount=q["base_amount"],
        kind="Guarantee Refund" if q["kind"] == "Guarantee" else "Refund", status="Posted",
        reference=q["reference"], reason=q["reason"], source_payment=q["source_payment"],
        pms_party=q["party"], pms_counter_account=q["debit"],
        pms_receivable=q["receivable"],
        pms_settlement_currency=q["settlement_currency"],
        pms_settled_amount=q["settled_amount"],
        pms_released_base_amount=q["released_base_amount"],
        pms_exchange_variance_account=q["exchange_variance_account"])
    counter_line = {"account": q["debit"],
        "debit": q["released_base_amount"] if foreign else q["base_amount"],
        "credit": "0", "party": q["party"]}
    if foreign:
        counter_line.update(account_currency=q["settlement_currency"],
            exchange_rate=q["counter_exchange_rate"],
            debit_in_account_currency=q["settled_amount"],
            credit_in_account_currency="0")
    lines = [counter_line,
        {"account": q["credit"], "debit": "0", "credit": q["base_amount"],
         "account_currency": q["currency"], "exchange_rate": q["exchange_rate"],
         "debit_in_account_currency": "0", "credit_in_account_currency": q["amount"]}]
    if foreign and Decimal(q["exchange_variance_base"]):
        difference = Decimal(q["exchange_variance_base"])
        lines.append({"account": q["exchange_variance_account"],
            "debit": _money(max(difference, Decimal(0))),
            "credit": _money(max(-difference, Decimal(0)))})
    journal = post(prop, source_doctype="HS Payment", source_name=refund_doc.name,
        purpose="Refund", memo=q["reason"], lines=lines)
    refund_doc.pms_journal = journal.name
    refund_doc.save()
    allocation_name = None
    if q["allocation"]:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
            receivable=q["receivable"], payment=refund_doc.name,
            kind="Direct Reversed", reverses=q["allocation"],
            business_date=prop.business_date, currency=prop.currency,
            amount=q["released_base_amount"] if foreign else q["base_amount"],
            settlement_currency=q["settlement_currency"],
            settled_amount=q["settled_amount"], journal=journal.name)
        allocation_name = row.name
    audit(prop, "pms_payment_refunded", refund_doc, reason=q["reason"], details={
        "original_payment": q["source_payment"], "journal": journal.name,
        "allocation": allocation_name, "amount": q["amount"], "currency": q["currency"],
        "settled_amount": q["settled_amount"],
        "released_base_amount": q["released_base_amount"],
        "exchange_variance_base": q["exchange_variance_base"]})
    return {"payment": refund_doc.name, "journal": journal.name,
            "allocation": allocation_name, "source_payment": q["source_payment"],
            "amount": q["amount"], "currency": q["currency"], "base_amount": q["base_amount"],
            "remaining_currency": q["remaining_currency"], "remaining_base": q["remaining_base"],
            "settled_amount": q["settled_amount"],
            "released_base_amount": q["released_base_amount"],
            "exchange_variance_base": q["exchange_variance_base"]}


def snapshot(property_name, folio=None):
    prop = require(property_name, "finance")
    require_pms(prop)
    if folio is not None:
        if not isinstance(folio, str) or len(folio) > 140:
            frappe.throw(_("Revise la cuenta de estancia"))
        folio = folio.strip() or None
    from hospitality_suite.standalone_receivables import list_receivables
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name},
        fields=["name", "mode_of_payment", "account", "currency", "is_cash"])
    categories = frappe.get_all("HS Expense Category", filters={"property": prop.name, "active": 1},
        fields=["name", "label", "account", "max_amount"])
    concepts = frappe.get_all("HS Treasury Concept", filters={"property": prop.name, "active": 1, "nature": "Other Income"},
        fields=["name", "label", "account"])
    folios = frappe.get_all("HS Folio", filters={"property": prop.name, "status": "Open"},
        fields=["name", "customer", "label"], order_by="creation desc", limit_page_length=500)
    bookings = frappe.get_all("HS Booking", filters={"property": prop.name,
        "status": ["in", ["Hold", "Confirmed", "Checked In"]]},
        fields=["name", "customer", "status", "starts_at", "hold_until"],
        order_by="creation desc", limit_page_length=500)
    bookings = [row for row in bookings if row.status != "Hold" or
                (row.hold_until and get_datetime(row.hold_until) > now_datetime())]
    deposit_accounts = frappe.get_all("HS Account", filters={"property": prop.name, "root_type": "Liability",
                                                       "account_currency": prop.currency, "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name, "status": "Open"},
        fields=["name", "cashier", "opened_at", "opening_by_currency"])
    movements = frappe.get_all("HS Payment", filters={"property": prop.name,
                                                    "pms_journal": ["is", "set"]},
                     fields=["name", "kind", "currency", "amount", "base_amount", "exchange_rate",
                             "reference", "business_date", "shift", "method", "pms_receivable",
                             "pms_party", "folio", "booking", "source_payment",
                             "pms_settlement_currency", "pms_settled_amount",
                             "pms_released_base_amount"],
                     order_by="creation desc", limit_page_length=50)
    from hospitality_suite.standalone_receivables import deposit_available, remaining_allocation
    refundable = []
    for row in movements:
        if row.kind not in ("Payment", "Advance", "Guarantee"):
            continue
        refunds = current_all("HS Payment", filters={"property": prop.name,
            "source_payment": row.name,
            "kind": "Guarantee Refund" if row.kind == "Guarantee" else "Refund",
            "status": "Posted"},
            fields=["amount", "base_amount", "pms_settled_amount",
                    "pms_released_base_amount"])
        foreign = Decimal(str(row.amount)) - sum((Decimal(str(item.amount)) for item in refunds), Decimal(0))
        if row.kind in ("Advance", "Guarantee"):
            base = deposit_available(prop, row.name, row.kind)
            foreign = min(foreign, (base / Decimal(str(row.exchange_rate))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        else:
            original = frappe.db.get_value("HS PMS Allocation", {"property": prop.name,
                "payment": row.name, "kind": "Direct"}, "name")
            base = remaining_allocation(prop, original) if original else Decimal(0)
            if row.pms_settlement_currency:
                released = base
                settled = Decimal(str(row.pms_settled_amount)) - sum(
                    (Decimal(str(item.pms_settled_amount or 0)) for item in refunds), Decimal(0))
                base = Decimal(str(row.base_amount)) - sum(
                    (Decimal(str(item.base_amount)) for item in refunds), Decimal(0))
        if foreign > 0 and base > 0:
            refundable.append({"name": row.name, "kind": row.kind, "currency": row.currency,
                "reference": row.reference, "method": row.method, "folio": row.folio,
                "booking": row.booking,
                "remaining_amount": _money(foreign), "remaining_base": _money(base),
                "pms_receivable": row.pms_receivable,
                "settlement_currency": row.pms_settlement_currency,
                "remaining_settled_amount": _money(settled) if row.pms_settlement_currency else None,
                "remaining_released_base": _money(released) if row.pms_settlement_currency else None})
    return {"base_currency": prop.currency, "accepted_currencies": sorted({prop.currency} |
        {row.currency for row in prop.accepted_currencies}), "methods": methods, "categories": categories,
        "concepts": concepts, "customers": customers(prop.name),
        "folios": folios, "bookings": bookings,
        "shifts": [{**shift, "expected": expected(frappe.get_doc("HS Shift", shift.name))}
                               for shift in shifts if shift.cashier == frappe.session.user],
        "deposit_accounts": deposit_accounts,
        "receivables": list_receivables(prop, open_only=True, folio=folio),
        "movements": movements, "refundable": refundable}
