"""Internal PMS receivables and application of customer advances.

These records are operational charges, not fiscal invoices. Every mutation runs
under the property lock supplied by service.command.
"""

from decimal import Decimal
from uuid import uuid4

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, inverse_lines
from hospitality_suite.security import require
from hospitality_suite.service import audit, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, post, require_pms


def _text(value, label, limit=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, limit))
    return value.strip()


def _amount(value):
    try:
        result = amount(value)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if result <= 0:
        frappe.throw(_("El importe debe ser mayor que cero"))
    return result


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _customer(prop, name):
    row = frappe.db.get_value("HS Party", name,
        ["property", "party_type", "active"], as_dict=True) if name else None
    if not row or row.property != prop.name or not row.active or row.party_type not in ("Customer", "Both"):
        frappe.throw(_("Seleccione un cliente activo del establecimiento"))


def allocated(prop, receivable):
    return sum((Decimal(str(row.amount)) for row in current_all("HS PMS Allocation",
        filters={"property": prop.name, "receivable": receivable}, fields=["amount"])), Decimal(0))


def outstanding(prop, receivable):
    row = frappe.db.get_value("HS PMS Receivable", receivable,
        ["property", "amount", "status"], as_dict=True)
    if not row or row.property != prop.name or row.status != "Posted":
        frappe.throw(_("La cuenta por cobrar pertenece a otro establecimiento"), frappe.PermissionError)
    return Decimal(str(row.amount)) - allocated(prop, receivable)


def advance_available(prop, payment):
    row = frappe.db.get_value("HS Payment", payment,
        ["property", "kind", "status", "base_amount"], as_dict=True)
    if not row or row.property != prop.name or row.kind != "Advance" or row.status != "Posted":
        frappe.throw(_("Seleccione un anticipo vigente del establecimiento"))
    used = sum((Decimal(str(item.amount)) for item in current_all("HS PMS Allocation",
        filters={"property": prop.name, "payment": payment, "kind": "Advance Applied"},
        fields=["amount"])), Decimal(0))
    return Decimal(str(row.base_amount)) - used


def create(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"party", "reference", "description", "amount",
                                              "receivable_account", "income_account"}:
        frappe.throw(_("Revise la cuenta por cobrar"))
    _customer(prop, data.get("party"))
    reference = _text(data.get("reference"), "una referencia")
    description = _text(data.get("description"), "una descripción", 500)
    value = _amount(data.get("amount"))
    receivable = account(prop, data.get("receivable_account"))
    income = account(prop, data.get("income_account"))
    if (receivable.root_type != "Asset" or receivable.account_type != "Receivable" or
            receivable.is_cash or receivable.is_bank or
            income.root_type != "Income" or
            receivable.account_currency != prop.currency or income.account_currency != prop.currency):
        frappe.throw(_("Seleccione cuentas por cobrar e ingreso en moneda base"))
    journal = post(prop, source_doctype="HS PMS Receivable", source_name=reference,
                   purpose="Receivable", memo=description,
                   lines=[{"account": receivable.name, "debit": str(value), "credit": "0",
                           "party": data["party"]},
                          {"account": income.name, "debit": "0", "credit": str(value)}])
    doc = insert("HS PMS Receivable", prop, organization=prop.organization,
                 party=data["party"], reference=reference, description=description,
                 business_date=prop.business_date, currency=prop.currency, amount=str(value),
                 receivable_account=receivable.name, income_account=income.name,
                 journal=journal.name, status="Posted")
    audit(prop, "pms_receivable_created", doc, details={"journal": journal.name,
                                                       "amount": str(value)})
    return {"receivable": doc.name, "journal": journal.name,
            "amount": str(value), "currency": prop.currency}


def apply_advance(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"receivable", "advance", "amount", "reason"}:
        frappe.throw(_("Revise la aplicación del anticipo"))
    receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
    advance = locked_doc("HS Payment", data.get("advance"))
    if (receivable.property != prop.name or receivable.status != "Posted" or
            advance.property != prop.name or advance.pms_party != receivable.party):
        frappe.throw(_("El anticipo y la cuenta por cobrar deben pertenecer al mismo cliente"))
    if advance.kind != "Advance" or advance.status != "Posted":
        frappe.throw(_("Seleccione un anticipo vigente"))
    value = _amount(data.get("amount"))
    if value > outstanding(prop, receivable.name) or value > advance_available(prop, advance.name):
        frappe.throw(_("La aplicación supera el saldo de la cuenta o del anticipo"))
    reason = _text(data.get("reason"), "el motivo", 500)
    liability = account(prop, advance.pms_counter_account)
    ar = account(prop, receivable.receivable_account)
    if liability.root_type != "Liability" or ar.root_type != "Asset":
        frappe.throw(_("Las cuentas originales ya no son válidas"))
    journal = post(prop, source_doctype="HS PMS Allocation",
                   source_name=uuid4().hex, purpose="Advance Applied",
                   memo=reason, lines=[
                       {"account": liability.name, "debit": str(value), "credit": "0",
                        "party": advance.pms_party},
                       {"account": ar.name, "debit": "0", "credit": str(value),
                        "party": advance.pms_party}])
    row = insert("HS PMS Allocation", prop, organization=prop.organization,
                 receivable=receivable.name, payment=advance.name, kind="Advance Applied",
                 business_date=prop.business_date, currency=prop.currency,
                 amount=str(value), journal=journal.name)
    audit(prop, "pms_advance_applied", row, reason=reason,
          details={"journal": journal.name, "remaining": _money(outstanding(prop, receivable.name))})
    return {"allocation": row.name, "journal": journal.name,
            "outstanding": _money(outstanding(prop, receivable.name)),
            "advance_available": _money(advance_available(prop, advance.name))}


def cancel(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"receivable", "reason"}:
        frappe.throw(_("Revise la cancelación del cargo"))
    doc = locked_doc("HS PMS Receivable", data.get("receivable"))
    if doc.property != prop.name or doc.status != "Posted":
        frappe.throw(_("Seleccione un cargo vigente del establecimiento"))
    if current_all("HS PMS Allocation", filters={"property": prop.name,
                                                  "receivable": doc.name}, pluck="name"):
        frappe.throw(_("La cuenta tiene cobros aplicados; primero se requiere conciliación y devolución"))
    reason = _text(data.get("reason"), "el motivo de cancelación", 500)
    original = locked_doc("HS Journal", doc.journal)
    lines = inverse_lines([{"account": row.account, "debit": str(row.debit),
                            "credit": str(row.credit), "party": row.party,
                            "account_currency": row.account_currency,
                            "exchange_rate": str(row.exchange_rate),
                            "debit_in_account_currency": str(row.debit_in_account_currency),
                            "credit_in_account_currency": str(row.credit_in_account_currency)}
                           for row in original.lines])
    reversal = post(prop, source_doctype="HS PMS Receivable", source_name=doc.name,
                    purpose="Cancellation", lines=lines, memo=reason,
                    reversal_of=original.name)
    doc.status = "Cancelled"
    doc.reversal_journal = reversal.name
    doc.save()
    audit(prop, "pms_receivable_cancelled", doc, reason=reason,
          details={"reversal_journal": reversal.name})
    return {"receivable": doc.name, "status": doc.status, "reversal_journal": reversal.name}


def list_receivables(prop, open_only=False):
    open_filter = " AND (r.amount-COALESCE(a.allocated,0))>0" if open_only else ""
    rows = frappe.db.sql(
        "SELECT r.name, r.party, r.reference, r.description, r.amount, r.currency, "
        "r.business_date, r.receivable_account, "
        "r.amount-COALESCE(a.allocated,0) AS outstanding "
        "FROM `tabHS PMS Receivable` r LEFT JOIN ("
        "SELECT receivable, SUM(amount) AS allocated FROM `tabHS PMS Allocation` "
        "WHERE property=%s GROUP BY receivable) a ON a.receivable=r.name "
        "WHERE r.property=%s AND r.status='Posted'" + open_filter +
        " ORDER BY r.creation DESC LIMIT 200",
        (prop.name, prop.name), as_dict=True)
    return [{**row, "outstanding": _money(row.outstanding)} for row in rows]


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    rows = list_receivables(prop)
    advances = frappe.db.sql(
        "SELECT p.name, p.pms_party, p.amount, p.currency, p.base_amount, p.reference, "
        "p.pms_counter_account, p.base_amount-COALESCE(a.applied,0) AS available "
        "FROM `tabHS Payment` p LEFT JOIN ("
        "SELECT payment, SUM(amount) AS applied FROM `tabHS PMS Allocation` "
        "WHERE property=%s AND kind='Advance Applied' GROUP BY payment) a ON a.payment=p.name "
        "WHERE p.property=%s AND p.kind='Advance' AND p.status='Posted' "
        "AND p.pms_journal IS NOT NULL ORDER BY p.creation DESC LIMIT 200",
        (prop.name, prop.name), as_dict=True)
    cancelled = frappe.get_all("HS PMS Receivable", filters={"property": prop.name,
                                                            "status": "Cancelled"},
        fields=["name", "party", "reference", "amount", "currency", "reversal_journal"],
        order_by="modified desc", limit_page_length=50)
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "account_currency": prop.currency, "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name", "root_type", "account_type", "is_cash", "is_bank"],
        order_by="account_code asc")
    customers = frappe.get_all("HS Party", filters={"property": prop.name, "active": 1,
        "party_type": ["in", ["Customer", "Both"]]}, fields=["name", "party_name"],
        order_by="party_name asc", limit_page_length=500)
    return {"currency": prop.currency, "accounts": accounts, "customers": customers,
            "cancelled": cancelled,
            "receivables": rows,
            "advances": [{**row, "available": _money(row.available)} for row in advances]}
