"""Accrual and payment of completed-booking agency commissions in PMS mode."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (account, account_currency_balance,
    post, require_pms)
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, latest_rate


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, limit))
    return value.strip()


def validate_property(prop):
    for field, root, kind in (("pms_commission_expense_account", "Expense", None),
                              ("pms_commission_payable_account", "Liability", "Payable")):
        value = prop.get(field)
        if not value:
            continue
        chosen = account(prop, value)
        if (chosen.root_type != root or chosen.account_currency != prop.currency or
                kind and chosen.account_type != kind):
            frappe.throw(_("Revise las cuentas PMS de gasto y por pagar de comisiones"))


def _source_base(prop, booking):
    stays = current_all("HS Stay", filters={"property": prop.name,
        "booking": booking.name}, fields=["name", "status"])
    if not stays or any(row.status != "Checked Out" for row in stays):
        frappe.throw(_("Todas las estancias de la reserva deben estar finalizadas"))
    charges = current_all("HS Charge", filters={"property": prop.name,
        "stay": ["in", [row.name for row in stays]], "kind": "Lodging"},
        fields=["name", "status", "pms_receivable", "applies_to_charge"])
    primary = [row for row in charges if not row.applies_to_charge and row.status != "Reversed"]
    if not primary or any(row.status != "Posted" or not row.pms_receivable
                          for row in primary) or any(row.status in ("Pending", "Scheduled")
                                                     for row in charges):
        frappe.throw(_("Contabilice todo el alojamiento antes de liquidar la comisión"))
    names = sorted({row.pms_receivable for row in primary})
    receivables = [locked_doc("HS PMS Receivable", name) for name in names]
    if any(row.property != prop.name or row.status != "Posted" or
           row.currency != prop.currency or row.party != booking.customer or
           row.source_charge not in {charge.name for charge in primary}
           for row in receivables):
        frappe.throw(_("Las cuentas de alojamiento no conservan una base válida"))
    if frappe.db.sql(
        "SELECT 1 FROM `tabHS PMS Fiscal Line` l "
        "JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "WHERE d.property=%s AND d.document_type='Credit Note' "
        "AND d.status='Posted' AND l.receivable IN (" + ",".join(["%s"] * len(names)) + ") LIMIT 1",
        (prop.name, *names), as_list=True):
        frappe.throw(_("Revise las notas de crédito del alojamiento antes de liquidar la comisión"))
    base = sum((Decimal(str(row.net_amount)) for row in receivables), Decimal(0))
    if base <= 0:
        frappe.throw(_("No hay alojamiento contabilizado con base positiva"))
    return base, [{"name": row.name, "net_amount": _money(row.net_amount),
                   "modified": str(row.modified)} for row in receivables]


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "commission")
    if not isinstance(data, dict) or set(data) != {"booking"}:
        frappe.throw(_("Seleccione una reserva para liquidar"))
    booking = document("HS Booking", data["booking"], "commission")
    if (booking.property != prop.name or booking.status != "Completed" or
            not booking.travel_agent or booking.pms_agent_commission or
            booking.agent_commission_invoice or frappe.db.exists(
                "HS PMS Agency Commission", {"property": prop.name,
                    "booking": booking.name, "status": ["in", ["Pending", "Posted"]]})):
        frappe.throw(_("La reserva no tiene una comisión PMS pendiente de liquidar"))
    agent = document("HS Travel Agent", booking.travel_agent, "commission")
    supplier = frappe.db.get_value("HS Party", agent.pms_supplier,
        ["name", "property", "organization", "party_type", "active"], as_dict=True)
    if (not supplier or supplier.property != prop.name or
            supplier.organization != prop.organization or not supplier.active or
            supplier.party_type not in ("Supplier", "Both")):
        frappe.throw(_("Vincule la agencia a un proveedor PMS activo"))
    expense = account(prop, prop.pms_commission_expense_account)
    payable = account(prop, prop.pms_commission_payable_account)
    if (expense.root_type != "Expense" or expense.account_currency != prop.currency or
            payable.root_type != "Liability" or payable.account_type != "Payable" or
            payable.account_currency != prop.currency or expense.name == payable.name):
        frappe.throw(_("Configure gasto y cuenta por pagar de comisiones en moneda base"))
    base, sources = _source_base(prop, booking)
    pct = Decimal(str(booking.agent_commission_pct or 0))
    if not pct.is_finite() or pct <= 0 or pct > 100:
        frappe.throw(_("La reserva no conserva un porcentaje de comisión positivo"))
    value = (base * pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        frappe.throw(_("La comisión calculada es menor que la precisión de la moneda"))
    signature = {"property": prop.name, "booking": booking.name,
        "booking_modified": str(booking.modified), "agent": agent.name,
        "agent_modified": str(agent.modified), "agent_name": agent.agent_name,
        "supplier": supplier.name, "expense": expense.name, "payable": payable.name,
        "base": _money(base), "pct": str(pct), "amount": _money(value),
        "sources": sources}
    return {"booking": booking.name, "modified": str(booking.modified),
        "agent": agent.name, "agent_name": agent.agent_name,
        "supplier": supplier.name, "expense_account": expense.name,
        "payable_account": payable.name, "base": _money(base),
        "percent": str(pct), "amount": _money(value),
        "currency": prop.currency, "sources": sources,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def settle(prop, data):
    if not isinstance(data, dict) or set(data) != {"booking", "modified", "acceptance"}:
        frappe.throw(_("Revise la liquidación de agencia"))
    reviewed = quote(prop, {"booking": data["booking"]})
    if data["acceptance"] != reviewed["acceptance"]:
        frappe.throw(_("La base, proveedor o cuentas cambiaron; revise la comisión"))
    booking = document("HS Booking", reviewed["booking"], "commission")
    assert_version(booking, data["modified"])
    doc = insert("HS PMS Agency Commission", prop,
        organization=prop.organization, booking=booking.name,
        agent=reviewed["agent"], supplier=reviewed["supplier"],
        agent_name=reviewed["agent_name"], business_date=prop.business_date,
        currency=prop.currency, base_amount=reviewed["base"],
        percent=reviewed["percent"], amount=reviewed["amount"],
        expense_account=reviewed["expense_account"],
        payable_account=reviewed["payable_account"], status="Pending")
    journal = post(prop, source_doctype=doc.doctype, source_name=doc.name,
        purpose="Agency Commission", memo=f"Comisión de {booking.name}",
        lines=[{"account": doc.expense_account, "debit": reviewed["amount"],
                "credit": 0, "party": doc.supplier},
               {"account": doc.payable_account, "debit": 0,
                "credit": reviewed["amount"], "party": doc.supplier}])
    doc.journal, doc.status = journal.name, "Posted"
    doc.save()
    booking.pms_agent_commission = doc.name
    booking.save()
    audit(prop, "pms_agency_commission_posted", doc,
          details={"booking": booking.name, "journal": journal.name,
                   "sources": reviewed["sources"]})
    return {"commission": doc.name, "booking": booking.name,
        "journal": journal.name, "amount": reviewed["amount"],
        "currency": prop.currency}


def outstanding(prop, name):
    doc = locked_doc("HS PMS Agency Commission", name)
    if doc.property != prop.name or doc.organization != prop.organization:
        frappe.throw(_("La comisión pertenece a otro establecimiento"), frappe.PermissionError)
    if doc.status != "Posted":
        return Decimal(0)
    paid = sum((Decimal(str(row.base_amount)) for row in current_all("HS Payment",
        filters={"property": prop.name, "pms_agent_commission": doc.name,
            "kind": "Supplier Payment", "status": "Posted"},
        fields=["base_amount"])), Decimal(0))
    remaining = Decimal(str(doc.amount)) - paid
    if remaining < 0:
        frappe.throw(_("Los pagos de la comisión exceden su saldo"))
    return remaining


def payment_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"commission", "method", "shift",
            "amount", "reference", "reason"}:
        frappe.throw(_("Revise el pago de la comisión"))
    doc = locked_doc("HS PMS Agency Commission", data.get("commission"))
    if doc.property != prop.name or doc.status != "Posted":
        frappe.throw(_("Seleccione una comisión vigente del establecimiento"))
    remaining = outstanding(prop, doc.name)
    if remaining <= 0:
        frappe.throw(_("La comisión ya está pagada"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de pago del establecimiento"))
    cash_account = account(prop, method.account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank)):
        frappe.throw(_("El medio no conserva una cuenta de Caja o banco válida"))
    payable = account(prop, doc.payable_account)
    if payable.root_type != "Liability" or payable.account_currency != prop.currency:
        frappe.throw(_("La cuenta por pagar original ya no es válida"))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("El pago debe ser positivo"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0 or base > remaining:
        frappe.throw(_("El pago supera el saldo pendiente de la comisión"))
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
    reference = _text(data.get("reference"), "la referencia del pago", 140)
    reason = _text(data.get("reason"), "el motivo del pago", 500)
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "pms_agent_commission": doc.name, "reference": reference,
            "status": "Posted"}):
        frappe.throw(_("La referencia ya está aplicada a esta comisión"))
    signature = {"property": prop.name, "commission": doc.name,
        "commission_modified": str(doc.modified), "remaining": _money(remaining),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": str(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "reference": reference, "reason": reason}
    return {"commission": doc.name, "supplier": doc.supplier,
        "payable_account": payable.name, "cash_account": cash_account.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "outstanding_before": _money(remaining),
        "outstanding_after": _money(remaining - base),
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def pay(prop, data):
    if not isinstance(data, dict) or set(data) - {"commission", "method", "shift",
            "amount", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise el pago de la comisión"))
    reviewed = payment_quote(prop, {key: value for key, value in data.items()
                                    if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("El saldo, medio o cambio variaron; revise el pago"))
    payment = insert("HS Payment", prop, shift=reviewed["shift"], method=reviewed["method"],
        currency=reviewed["currency"], amount=reviewed["amount"],
        exchange_rate=reviewed["exchange_rate"], base_amount=reviewed["base_amount"],
        kind="Supplier Payment", status="Posted", reference=reviewed["reference"],
        reason=reviewed["reason"], pms_party=reviewed["supplier"],
        pms_counter_account=reviewed["payable_account"],
        pms_agent_commission=reviewed["commission"])
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
        purpose="Agency Commission Payment", memo=reviewed["reason"],
        lines=[{"account": reviewed["payable_account"],
                "debit": reviewed["base_amount"], "credit": 0,
                "party": reviewed["supplier"]},
               {"account": reviewed["cash_account"], "debit": 0,
                "credit": reviewed["base_amount"],
                "account_currency": reviewed["currency"],
                "exchange_rate": reviewed["exchange_rate"],
                "debit_in_account_currency": 0,
                "credit_in_account_currency": reviewed["amount"]}])
    payment.pms_journal = journal.name
    payment.save()
    audit(prop, "pms_agency_commission_paid", payment,
          reason=reviewed["reason"], details={"commission": reviewed["commission"],
              "journal": journal.name, "base_amount": reviewed["base_amount"],
              "rate_record": reviewed["rate_record"]})
    return {"payment": payment.name, "journal": journal.name,
        "commission": reviewed["commission"],
        "outstanding": reviewed["outstanding_after"],
        "base_amount": reviewed["base_amount"]}


def cancel(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {"commission", "modified", "reason"}:
        frappe.throw(_("Revise la anulación de la comisión"))
    doc = document("HS PMS Agency Commission", data["commission"], "approve")
    assert_version(doc, data["modified"])
    reason = _text(data["reason"], "el motivo de anulación", 500)
    if doc.property != prop.name or doc.status != "Posted" or outstanding(prop, doc.name) != Decimal(str(doc.amount)):
        frappe.throw(_("Solo puede anular una comisión vigente sin pagos"))
    booking = locked_doc("HS Booking", doc.booking)
    if booking.property != prop.name or booking.pms_agent_commission != doc.name:
        frappe.throw(_("La comisión no coincide con su reserva"))
    journal = post(prop, source_doctype=doc.doctype, source_name=doc.name,
        purpose="Agency Commission Cancellation", memo=reason,
        reversal_of=doc.journal,
        lines=[{"account": doc.payable_account, "debit": doc.amount,
                "credit": 0, "party": doc.supplier},
               {"account": doc.expense_account, "debit": 0,
                "credit": doc.amount, "party": doc.supplier}])
    doc.reversal_journal, doc.cancel_reason = journal.name, reason
    doc.cancelled_business_date, doc.status = prop.business_date, "Cancelled"
    doc.save()
    booking.pms_agent_commission = None
    booking.save()
    audit(prop, "pms_agency_commission_cancelled", doc, reason=reason,
          details={"reversal_journal": journal.name, "booking": booking.name})
    return {"commission": doc.name, "status": doc.status,
            "reversal_journal": journal.name}
