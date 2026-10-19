from hospitality_suite.service import current_all, locked_doc
import json

import frappe
from frappe.utils import now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, assert_version, canonical


def open_shift(prop, data):
    if current_all("HS Shift", filters={"property": prop.name, "cashier": frappe.session.user, "status": "Open", "currency": data.get("currency") or prop.currency}):
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
    for method in current_all("HS Payment Method",filters={"property":shift.property,"is_cash":1},fields=["currency"]):
        amounts.setdefault(method.currency,decimal(0))
    for row in current_all("HS Payment", filters={"shift": shift.name, "status": "Posted"}, fields=["amount", "kind", "method", "currency"]):
        if row.kind=="Guarantee Applied":
            continue
        if not frappe.db.get_value("HS Payment Method", row.method, "is_cash"):
            continue
        sign = -1 if row.kind in ("Refund", "Guarantee Refund", "Withdrawal") else 1
        amounts[row.currency] = amounts.get(row.currency, decimal(0)) + decimal(row.amount) * sign
    return {k: str(money(v,currency=k)) for k, v in amounts.items()}


def close_shift(prop, data):
    doc = document("HS Shift", data["shift"], "finance")
    assert_version(doc, data.get("modified"))
    if doc.status not in ("Open", "Review"):
        frappe.throw("El turno ya está cerrado")
    if doc.cashier != frappe.session.user:
        require(prop.name, "approve")
    from hospitality_suite.reconciliation import unmatched_cash
    if unmatched_cash(prop,doc.name):
        frappe.throw("Conciliación pendiente: existen movimientos nativos del turno sin registro operativo")
    denominations = data.get("denominations") or {}
    totals = {}
    for currency, rows in denominations.items():
        if not frappe.db.exists("Currency",currency) or any(decimal(r["value"]) <= 0 or int(r["count"]) < 0 or decimal(r["count"])!=decimal(int(r["count"])) for r in rows):
            frappe.throw("Denominaciones inválidas")
        totals[currency] = money(sum(decimal(r["value"]) * int(r["count"]) for r in rows),currency=currency)
    exp = expected(doc)
    differences = {c: str(money(totals.get(c,decimal(0))-decimal(exp.get(c,0)))) for c in set(exp)|set(totals)}
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


def withdrawal(prop,data):
    from hospitality_suite.accounting import ready,post_standard,exchange
    ready(prop)
    shift=document("HS Shift",data["shift"],"finance")
    method=document("HS Payment Method",data["method"],"finance")
    if shift.status!="Open" or not method.is_cash or not data.get("reason"):
        frappe.throw("Seleccione un turno abierto, medio en efectivo y motivo")
    if shift.cashier!=frappe.session.user:
        require(prop.name,"approve")
    if not prop.get("cash_transfer_account"):
        frappe.throw("Configure la cuenta de traslado de efectivo en el establecimiento")
    account=locked_doc("Account",prop.cash_transfer_account)
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    if account.company!=prop.company or account.is_group or account.account_currency!=company_currency or account.root_type!="Asset" or account.name==method.account:
        frappe.throw("La cuenta de entrega debe ser un activo en la moneda base de la compañía")
    amount=money(data["amount"])
    balances=expected(shift)
    if amount<=0 or amount>decimal(balances.get(method.currency,0)):
        frappe.throw("El retiro supera el efectivo esperado en esa moneda")
    fx=exchange(method.currency,company_currency)
    journal=frappe.new_doc("Journal Entry")
    journal.update(dict(company=prop.company,posting_date=frappe.utils.nowdate(),voucher_type="Cash Entry",multi_currency=1,hs_shift=shift.name,user_remark=data["reason"]))
    journal.append("accounts",dict(account=prop.cash_transfer_account,debit_in_account_currency=float(money(amount*fx)),exchange_rate=1,cost_center=prop.cost_center))
    journal.append("accounts",dict(account=method.account,credit_in_account_currency=float(amount),exchange_rate=float(fx),cost_center=prop.cost_center))
    post_standard(journal,prop)
    record=insert("HS Payment",prop,shift=shift.name,method=method.name,amount=amount,currency=method.currency,
                  exchange_rate=fx,base_amount=money(amount*fx),kind="Withdrawal",status="Posted",journal_entry=journal.name,reason=data["reason"])
    audit(prop,"Cash withdrawal",record,data["reason"])
    return dict(payment=record.name,journal_entry=journal.name)
