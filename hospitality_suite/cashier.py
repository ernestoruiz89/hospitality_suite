import json

import frappe
from frappe.utils import now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, assert_version, canonical


def open_shift(prop, data):
    if frappe.db.exists("HS Shift", {"property": prop.name, "cashier": frappe.session.user, "status": "Open", "currency": data.get("currency") or prop.currency}):
        frappe.throw("Ya tiene un turno abierto en esa moneda")
    opening = money(data.get("opening_amount"))
    if opening < 0:
        frappe.throw("El fondo inicial no puede ser negativo")
    doc = insert("HS Shift", prop, cashier=frappe.session.user, opened_at=now_datetime(), status="Open",
                 currency=data.get("currency") or prop.currency, opening_amount=opening)
    audit(prop, "Open shift", doc)
    return dict(shift=doc.name)


def expected(shift):
    amounts = {shift.currency: decimal(shift.opening_amount)}
    for row in frappe.get_all("HS Payment", filters={"shift": shift.name, "status": "Posted"}, fields=["amount", "kind", "method", "currency"]):
        if not frappe.db.get_value("HS Payment Method", row.method, "is_cash"):
            continue
        sign = -1 if row.kind in ("Refund", "Guarantee Refund", "Withdrawal") else 1
        amounts[row.currency] = amounts.get(row.currency, decimal(0)) + decimal(row.amount) * sign
    return {k: str(money(v)) for k, v in amounts.items()}


def close_shift(prop, data):
    doc = document("HS Shift", data["shift"], "finance")
    assert_version(doc, data.get("modified"))
    if doc.status not in ("Open", "Review"):
        frappe.throw("El turno ya está cerrado")
    if doc.cashier != frappe.session.user:
        require(prop.name, "approve")
    denominations = data.get("denominations") or {}
    totals = {}
    for currency, rows in denominations.items():
        if any(decimal(r["value"]) <= 0 or int(r["count"]) < 0 for r in rows):
            frappe.throw("Denominaciones inválidas")
        totals[currency] = money(sum(decimal(r["value"]) * int(r["count"]) for r in rows))
    exp = expected(doc)
    differences = {c: str(money(totals.get(c, decimal(0)) - decimal(v))) for c, v in exp.items()}
    if any(decimal(v) for v in differences.values()):
        if not data.get("reason"):
            frappe.throw("Indique el motivo de la diferencia de arqueo")
        if data.get("approve"):
            require(prop.name, "approve")
            doc.approved_by = frappe.session.user
            doc.status = "Closed"
        else:
            doc.status = "Review"
    else:
        doc.status = "Closed"
    doc.expected_amount = exp.get(doc.currency, "0")
    doc.counted_amount = totals.get(doc.currency, 0)
    doc.difference = differences.get(doc.currency, "0")
    doc.denominations = canonical(dict(counts=denominations, expected=exp, differences=differences))
    doc.closed_at, doc.reason = now_datetime(), data.get("reason")
    doc.save()
    audit(prop, "Close shift", doc, doc.reason, differences)
    return dict(shift=doc.name, status=doc.status, differences=differences)
