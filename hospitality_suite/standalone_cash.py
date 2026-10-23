"""Multicurrency cash/bank receipts, other income and expenses in PMS mode."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
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
        if frappe.db.exists("HS Payment", {"method": doc.name}):
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
    if not isinstance(data, dict) or set(data) - {"label", "account", "nature"}:
        frappe.throw(_("Revise el concepto financiero"))
    doc = insert("HS Treasury Concept", prop, label=_label(data.get("label"), "el concepto"),
                 account=data.get("account"), nature=data.get("nature"), active=1)
    audit(prop, "pms_financial_concept_created", doc)
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
        sign = -1 if row.kind == "Expense" else 1
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
                                              "receivable",
                                              "expected_exchange_rate", "expected_rate_record",
                                              "expected_debit", "expected_credit"}:
        frappe.throw(_("Revise los datos del movimiento"))
    kind = data.get("kind")
    if kind not in ("Payment", "Advance", "Other Income", "Expense"):
        frappe.throw(_("Seleccione cobro, anticipo, otro ingreso o gasto"))
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
    party = category = concept = receivable = None
    if kind == "Payment":
        from hospitality_suite.standalone_receivables import outstanding
        receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
        if receivable.property != prop.name or receivable.status != "Posted":
            frappe.throw(_("Seleccione una cuenta por cobrar del establecimiento"))
        if base > outstanding(prop, receivable.name):
            frappe.throw(_("El cobro supera el saldo; registre el excedente como anticipo"))
        counter = account(prop, receivable.receivable_account)
        party = receivable.party
    elif kind == "Advance":
        counter = account(prop, data.get("counter_account"))
        if counter.root_type != "Liability" or counter.account_currency != prop.currency:
            frappe.throw(_("El anticipo requiere una cuenta de pasivo en moneda base"))
        party = data.get("party")
        customer = frappe.db.get_value("HS Party", party,
            ["property", "party_type", "active"], as_dict=True) if party else None
        if not customer or customer.property != prop.name or not customer.active or customer.party_type not in ("Customer", "Both"):
            frappe.throw(_("Seleccione un cliente activo del establecimiento"))
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
    if counter.account_currency != prop.currency:
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
            "debit": debit, "credit": credit}


def post_movement(prop, data):
    q = quote(prop, data)
    cash_line = {"account": q["cash_account"], "debit": q["base_amount"] if q["kind"] != "Expense" else "0",
                 "credit": q["base_amount"] if q["kind"] == "Expense" else "0",
                 "account_currency": q["currency"], "exchange_rate": q["exchange_rate"],
                 "debit_in_account_currency": q["amount"] if q["kind"] != "Expense" else "0",
                 "credit_in_account_currency": q["amount"] if q["kind"] == "Expense" else "0"}
    counter_line = {"account": q["counter_account"],
                    "debit": q["base_amount"] if q["kind"] == "Expense" else "0",
                    "credit": q["base_amount"] if q["kind"] != "Expense" else "0",
                    "party": q["party"]}
    payment = insert("HS Payment", prop, shift=q["shift"], method=q["method"],
                     currency=q["currency"], amount=q["amount"],
                     exchange_rate=q["exchange_rate"], base_amount=q["base_amount"],
                     kind=q["kind"], status="Posted", reference=q["reference"], reason=q["reason"],
                     pms_party=q["party"], pms_counter_account=q["counter_account"],
                     pms_concept=q["concept"], pms_receivable=q["receivable"],
                     expense_category=q["category"])
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
                   purpose=q["kind"], lines=[cash_line, counter_line], memo=q["reason"])
    payment.pms_journal = journal.name
    payment.save()
    allocation_name = None
    if q["receivable"]:
        row = insert("HS PMS Allocation", prop, organization=prop.organization,
                     receivable=q["receivable"], payment=payment.name, kind="Direct",
                     business_date=prop.business_date, currency=prop.currency,
                     amount=q["base_amount"], journal=journal.name)
        allocation_name = row.name
    audit(prop, "pms_cash_movement_posted", payment, reason=q["reason"], details={
        "journal": journal.name, "currency": q["currency"], "amount": q["amount"],
        "exchange_rate": q["exchange_rate"], "rate_record": q["exchange_rate_record"]})
    return {"payment": payment.name, "journal": journal.name, "allocation": allocation_name,
            "kind": q["kind"],
            "amount": q["amount"], "currency": q["currency"], "base_amount": q["base_amount"]}


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    from hospitality_suite.standalone_receivables import list_receivables
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name},
        fields=["name", "mode_of_payment", "account", "currency", "is_cash"])
    categories = frappe.get_all("HS Expense Category", filters={"property": prop.name, "active": 1},
        fields=["name", "label", "account", "max_amount"])
    concepts = frappe.get_all("HS Treasury Concept", filters={"property": prop.name, "active": 1, "nature": "Other Income"},
        fields=["name", "label", "account"])
    deposit_accounts = frappe.get_all("HS Account", filters={"property": prop.name, "root_type": "Liability",
                                                       "account_currency": prop.currency, "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name, "status": "Open"},
        fields=["name", "cashier", "opened_at", "opening_by_currency"])
    return {"base_currency": prop.currency, "accepted_currencies": sorted({prop.currency} |
        {row.currency for row in prop.accepted_currencies}), "methods": methods, "categories": categories,
        "concepts": concepts, "customers": customers(prop.name),
        "shifts": [{**shift, "expected": expected(frappe.get_doc("HS Shift", shift.name))}
                               for shift in shifts if shift.cashier == frappe.session.user],
        "deposit_accounts": deposit_accounts,
        "receivables": list_receivables(prop, open_only=True),
        "movements": frappe.get_all("HS Payment", filters={"property": prop.name,
                                                    "pms_journal": ["is", "set"]},
                     fields=["name", "kind", "currency", "amount", "base_amount", "exchange_rate",
                             "reference", "business_date", "shift", "method", "pms_receivable",
                             "pms_party"],
                     order_by="creation desc", limit_page_length=50)}
