"""Approved loan and capital movements on the standalone PMS ledger."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (account, account_currency_balance,
    post, require_pms)
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, latest_rate


INCOMING = {"Loan Received": "Loan", "Capital Contribution": "Capital"}
OUTGOING = {"Loan Repayment": "Loan Received", "Capital Withdrawal": "Capital Contribution"}
ROOT = {"Loan": "Liability", "Capital": "Equity", "Other Income": "Income"}


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _text(value, label, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, maximum))
    return value.strip()


def _base_amount(value):
    try:
        result = amount(value)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if result <= 0:
        frappe.throw(_("El importe debe ser positivo"))
    return result


def _concept(prop, name, nature):
    concept = locked_doc("HS Treasury Concept", name)
    if (concept.property != prop.name or concept.nature != nature or
            not concept.active):
        frappe.throw(_("Seleccione un concepto financiero activo del establecimiento"))
    selected = account(prop, concept.account)
    if selected.root_type != ROOT[nature] or selected.account_currency != prop.currency:
        frappe.throw(_("El concepto requiere una cuenta de su naturaleza en moneda base"))
    return concept, selected


def _source(prop, name, kind):
    source = locked_doc("HS Treasury Movement", name)
    if (source.property != prop.name or source.kind != OUTGOING[kind] or
            source.status != "Posted" or not source.pms_journal or
            not frappe.db.exists("HS Journal", {"name": source.pms_journal,
                "property": prop.name, "status": "Posted"})):
        frappe.throw(_("Seleccione una entrada original vigente del establecimiento"))
    counter = account(prop, source.counter_account)
    if counter.root_type != ROOT["Loan" if kind == "Loan Repayment" else "Capital"]:
        frappe.throw(_("La cuenta original del principal no es válida"))
    return source


def remaining(prop, source, exclude=None, reserve=True):
    """Principal disponible en moneda base, con reservas de solicitudes abiertas."""
    rows = current_all("HS Treasury Movement", filters={"property": prop.name,
        "source_movement": source.name,
        "kind": "Loan Repayment" if source.kind == "Loan Received" else "Capital Withdrawal",
        "status": ["in", ["Posted", "Pending Approval", "Approved"]]},
        fields=["name", "status", "base_amount"])
    used = sum((Decimal(str(row.base_amount or 0)) for row in rows
                if row.name != exclude and (reserve or row.status == "Posted")), Decimal(0))
    left = Decimal(str(source.base_amount)) - used
    if left < 0:
        frappe.throw(_("El principal requiere conciliación"))
    return left


def request(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"kind", "concept", "source_movement",
            "amount", "reason"}:
        frappe.throw(_("Revise la solicitud de financiación"))
    kind = data.get("kind")
    if kind not in INCOMING and kind not in OUTGOING:
        frappe.throw(_("Seleccione préstamo recibido, devolución, aporte o retiro"))
    value = _base_amount(data.get("amount"))
    reason = _text(data.get("reason"), "el motivo")
    if kind in INCOMING:
        if data.get("source_movement"):
            frappe.throw(_("La entrada no debe vincular otra operación"))
        concept, counter = _concept(prop, data.get("concept"), INCOMING[kind])
        source_name = None
        concept_name, concept_label = concept.name, concept.label
    else:
        if data.get("concept"):
            frappe.throw(_("La devolución usa el concepto original"))
        source = _source(prop, data.get("source_movement"), kind)
        if value > remaining(prop, source):
            frappe.throw(_("La devolución supera el principal disponible"))
        counter = account(prop, source.counter_account)
        source_name = source.name
        concept_name, concept_label = source.concept, source.concept_label
    movement = insert("HS Treasury Movement", prop, kind=kind,
        concept=concept_name, concept_label=concept_label,
        source_movement=source_name, counter_account=counter.name,
        currency=prop.currency, amount=_money(value), base_amount=_money(value),
        business_date=prop.business_date, status="Pending Approval",
        requested_by=frappe.session.user, reason=reason)
    audit(prop, "pms_financing_requested", movement, reason=reason,
          details={"kind": kind, "base_amount": _money(value),
                   "source_movement": source_name})
    return {"movement": movement.name, "status": movement.status}


def approve(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"movement", "reason"}:
        frappe.throw(_("Revise la aprobación financiera"))
    movement = locked_doc("HS Treasury Movement", data.get("movement"))
    if (movement.property != prop.name or movement.kind not in INCOMING | OUTGOING or
            movement.status != "Pending Approval" or
            movement.requested_by == frappe.session.user):
        frappe.throw(_("Se requiere solicitud pendiente y aprobación por otro usuario"))
    if movement.kind in OUTGOING:
        source = _source(prop, movement.source_movement, movement.kind)
        if Decimal(str(movement.base_amount)) > remaining(prop, source, movement.name):
            frappe.throw(_("El principal disponible cambió"))
    note = _text(data.get("reason"), "el motivo de aprobación")
    movement.status = "Approved"
    movement.approved_by = frappe.session.user
    movement.approved_at = now_datetime()
    movement.save()
    audit(prop, "pms_financing_approved", movement, reason=note)
    return {"movement": movement.name, "status": movement.status}


def cancel_request(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"movement", "reason"}:
        frappe.throw(_("Revise la cancelación de solicitud"))
    movement = locked_doc("HS Treasury Movement", data.get("movement"))
    if movement.property != prop.name or movement.status not in ("Pending Approval", "Approved"):
        frappe.throw(_("Solo una solicitud sin contabilizar puede cancelarse"))
    if movement.status == "Approved":
        require(prop.name, "approve")
    elif movement.requested_by != frappe.session.user:
        require(prop.name, "approve")
    reason = _text(data.get("reason"), "el motivo de cancelación")
    movement.status = "Cancelled"
    movement.save()
    audit(prop, "pms_financing_request_cancelled", movement, reason=reason)
    return {"movement": movement.name, "status": movement.status}


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"movement", "concept", "method",
            "shift", "amount", "reference", "reason"}:
        frappe.throw(_("Revise el movimiento financiero"))
    request_doc = None
    if data.get("movement"):
        if data.get("concept"):
            frappe.throw(_("La solicitud aprobada ya conserva su concepto"))
        request_doc = locked_doc("HS Treasury Movement", data["movement"])
        if (request_doc.property != prop.name or request_doc.status != "Approved" or
                request_doc.kind not in INCOMING | OUTGOING or
                not request_doc.approved_by or
                request_doc.approved_by == request_doc.requested_by):
            frappe.throw(_("El préstamo o aporte requiere aprobación previa por otro usuario"))
        kind = request_doc.kind
        counter = account(prop, request_doc.counter_account)
        nature = (INCOMING[kind] if kind in INCOMING else
                  "Loan" if kind == "Loan Repayment" else "Capital")
        if counter.root_type != ROOT[nature] or counter.account_currency != prop.currency:
            frappe.throw(_("La cuenta aprobada ya no es válida"))
        source = None
        if kind in OUTGOING:
            source = _source(prop, request_doc.source_movement, kind)
            if Decimal(str(request_doc.base_amount)) > remaining(prop, source, request_doc.name):
                frappe.throw(_("El principal pendiente cambió"))
        concept_name, concept_label = request_doc.concept, request_doc.concept_label
    else:
        kind = "Other Income"
        concept, counter = _concept(prop, data.get("concept"), kind)
        concept_name, concept_label = concept.name, concept.label
        source = None
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de Caja o banco del establecimiento"))
    cash = account(prop, method.account)
    if (cash.account_currency != method.currency or
            bool(cash.is_cash) != bool(method.is_cash) or
            not (cash.is_cash or cash.is_bank)):
        frappe.throw(_("La cuenta del medio de pago no es válida"))
    value = _base_amount(data.get("amount"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0:
        frappe.throw(_("El importe convertido debe ser positivo"))
    if request_doc and base != Decimal(str(request_doc.base_amount)):
        frappe.throw(_("El importe convertido debe coincidir con el principal aprobado"))
    outgoing = kind in OUTGOING
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("Se requiere turno abierto propio para efectivo"), frappe.PermissionError)
        if outgoing and value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data.get("shift"):
        frappe.throw(_("El movimiento bancario no usa turno"))
    if outgoing and value > Decimal(account_currency_balance(prop, cash.name)["balance"]):
        frappe.throw(_("Caja o banco no tiene saldo contable suficiente"))
    reference = _text(data.get("reference"), "la referencia", 140)
    reason = _text(data.get("reason"), "el motivo")
    if frappe.db.exists("HS Treasury Movement", {"property": prop.name,
            "status": "Posted", "reference": reference}):
        frappe.throw(_("La referencia financiera ya fue utilizada en este establecimiento"))
    signature = {"property": prop.name, "kind": kind,
        "movement": request_doc.name if request_doc else None,
        "movement_modified": str(request_doc.modified) if request_doc else None,
        "concept": concept_name, "concept_label": concept_label,
        "counter": counter.name, "source": source.name if source else None,
        "source_remaining": _money(remaining(prop, source, request_doc.name)) if source else None,
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None,
        "shift_expected": expected(shift).get(method.currency) if shift and outgoing else None,
        "cash_balance": account_currency_balance(prop, cash.name)["balance"] if outgoing else None,
        "amount": str(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "reference": reference, "reason": reason}
    return {"kind": kind, "movement": request_doc.name if request_doc else None,
        "concept": concept_name, "concept_label": concept_label,
        "source_movement": source.name if source else None,
        "counter_account": counter.name, "cash_account": cash.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "debit": counter.name if outgoing else cash.name,
        "credit": cash.name if outgoing else counter.name,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def post_movement(prop, data):
    if not isinstance(data, dict) or set(data) - {"movement", "concept", "method",
            "shift", "amount", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise el movimiento antes de confirmar"))
    reviewed = quote(prop, {key: value for key, value in data.items() if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("La aprobación, saldo, cuenta o cambio variaron; revise nuevamente"))
    movement = (locked_doc("HS Treasury Movement", reviewed["movement"])
                if reviewed["movement"] else
                insert("HS Treasury Movement", prop, kind="Other Income",
                    concept=reviewed["concept"], concept_label=reviewed["concept_label"],
                    counter_account=reviewed["counter_account"],
                    currency=reviewed["currency"], amount=reviewed["amount"],
                    base_amount=reviewed["base_amount"],
                    business_date=prop.business_date, status="Approved",
                    requested_by=frappe.session.user, reason=reviewed["reason"]))
    outgoing = reviewed["kind"] in OUTGOING
    cash_line = {"account": reviewed["cash_account"],
        "debit": 0 if outgoing else reviewed["base_amount"],
        "credit": reviewed["base_amount"] if outgoing else 0,
        "account_currency": reviewed["currency"],
        "exchange_rate": reviewed["exchange_rate"],
        "debit_in_account_currency": 0 if outgoing else reviewed["amount"],
        "credit_in_account_currency": reviewed["amount"] if outgoing else 0}
    counter_line = {"account": reviewed["counter_account"],
        "debit": reviewed["base_amount"] if outgoing else 0,
        "credit": 0 if outgoing else reviewed["base_amount"]}
    journal = post(prop, source_doctype="HS Treasury Movement",
        source_name=movement.name, purpose=reviewed["kind"],
        memo=reviewed["reason"], lines=[cash_line, counter_line])
    movement.update({"shift": reviewed["shift"], "method": reviewed["method"],
        "cash_account": reviewed["cash_account"],
        "currency": reviewed["currency"], "amount": reviewed["amount"],
        "exchange_rate": reviewed["exchange_rate"],
        "rate_record": reviewed["rate_record"],
        "base_amount": reviewed["base_amount"], "business_date": prop.business_date,
        "reference": reviewed["reference"], "reason": reviewed["reason"],
        "pms_journal": journal.name, "status": "Posted"})
    movement.save()
    audit(prop, "pms_financial_movement_posted", movement,
        reason=reviewed["reason"], details={"journal": journal.name,
            "kind": reviewed["kind"], "currency": reviewed["currency"],
            "amount": reviewed["amount"], "base_amount": reviewed["base_amount"],
            "source_movement": reviewed["source_movement"]})
    return {"movement": movement.name, "journal": journal.name,
        "kind": reviewed["kind"], "base_amount": reviewed["base_amount"],
        "currency": reviewed["currency"]}


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    concepts = frappe.get_all("HS Treasury Concept", filters={"property": prop.name,
        "active": 1}, fields=["name", "label", "nature", "account"],
        order_by="label asc")
    from hospitality_suite.security import ACTIONS, is_system
    concept_settings = frappe.get_all("HS Treasury Concept", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "label", "nature", "account", "active", "modified"],
        order_by="label asc") if (is_system() or
        set(frappe.get_roles()).intersection(ACTIONS["chart"])) else []
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "account_currency": prop.currency,
        "active": 1, "is_group": 0},
        fields=["name", "account_code", "account_name", "root_type"],
        order_by="account_code asc")
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name},
        fields=["name", "mode_of_payment", "currency", "is_cash"],
        order_by="mode_of_payment asc")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
        "cashier": frappe.session.user, "status": "Open"},
        fields=["name", "opened_at"])
    movements = frappe.get_all("HS Treasury Movement", filters={"property": prop.name,
        "kind": ["in", ["Other Income", *INCOMING, *OUTGOING]]},
        fields=["name", "kind", "concept", "concept_label", "source_movement",
            "counter_account", "cash_account", "method", "shift",
            "currency", "amount", "base_amount", "exchange_rate", "rate_record",
            "status", "requested_by", "approved_by", "reference",
            "business_date", "pms_journal"],
        order_by="creation desc", limit_page_length=200)
    sources = []
    for row in movements:
        if row.kind in INCOMING and row.status == "Posted":
            row.available = _money(remaining(prop, row))
            row.principal_outstanding = _money(remaining(prop, row, reserve=False))
            sources.append(row)
    return {"currency": prop.currency, "concepts": concepts,
        "concept_settings": concept_settings, "accounts": accounts,
        "methods": methods,
        "shifts": shifts, "movements": movements, "sources": sources,
        "user": frappe.session.user}
