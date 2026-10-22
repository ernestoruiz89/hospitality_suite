"""Petty cash and non-invoiced financing, backed by submitted ERPNext journals.

All commands execute inside service.command's property lock and savepoint.  Amounts
and account identities are copied onto operational records at posting time.
"""
from decimal import Decimal

import frappe
from frappe.utils import now_datetime, nowdate

from hospitality_suite.accounting import post_standard, ready
from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import audit, current_all, insert, locked_doc

INCOMING = {"Other Income", "Loan Received", "Capital Contribution"}
OUTGOING = {"Loan Repayment", "Capital Withdrawal"}
FINANCING = {"Loan Received", "Loan Repayment", "Capital Contribution", "Capital Withdrawal"}
NATURE = {"Other Income": "Income", "Loan": "Liability", "Capital": "Equity"}
KIND_NATURE = {"Other Income": "Other Income", "Loan Received": "Loan", "Loan Repayment": "Loan",
               "Capital Contribution": "Capital", "Capital Withdrawal": "Capital"}


def base(prop):
    return frappe.db.get_value("Company", prop.company, "default_currency")


def account(prop, name, root, account_type=None):
    if not name:
        frappe.throw(frappe._("Configure una cuenta contable para esta operación"))
    row = locked_doc("Account", name)
    if (row.company != prop.company or row.is_group or row.root_type != root
            or row.account_currency != base(prop) or (account_type and row.account_type != account_type)):
        frappe.throw(frappe._("La cuenta debe ser auxiliar, de la compañía, naturaleza indicada y moneda base"))
    return row


def validate_property(doc, check_history=False):
    fields = ("petty_cash_account", "petty_cash_responsible", "petty_cash_overage_account", "petty_cash_shortage_account")
    previous = doc.get_doc_before_save()
    if previous and previous.petty_cash_account != doc.petty_cash_account and previous.petty_cash_account:
        if balance(previous) != 0 or unsettled(previous):
            frappe.throw(frappe._("No cambie ni desactive la cuenta de Caja Chica con saldo o movimientos pendientes"))
    if not any(doc.get(f) for f in fields):
        return
    if not all(doc.get(f) for f in fields):
        frappe.throw(frappe._("Complete cuenta, responsable y cuentas de diferencias de Caja Chica"))
    if not frappe.db.get_value("User", doc.petty_cash_responsible, "enabled"):
        frappe.throw(frappe._("El responsable de Caja Chica debe ser un usuario activo"))
    from hospitality_suite.security import allowed_properties
    if doc.name not in allowed_properties(doc.petty_cash_responsible):
        frappe.throw(frappe._("El responsable de Caja Chica requiere acceso al establecimiento"))
    account(doc, doc.petty_cash_account, "Asset")
    account(doc, doc.petty_cash_overage_account, "Income")
    account(doc, doc.petty_cash_shortage_account, "Expense")
    if len({doc.petty_cash_account, doc.petty_cash_overage_account, doc.petty_cash_shortage_account}) != 3:
        frappe.throw(frappe._("Las cuentas de Caja Chica y diferencias deben ser distintas"))
    other = frappe.db.exists("HS Property", {"petty_cash_account": doc.petty_cash_account, "name": ["!=", doc.name]})
    if other:
        frappe.throw(frappe._("La cuenta de Caja Chica ya pertenece a otro establecimiento"))
    if check_history and (not previous or previous.petty_cash_account != doc.petty_cash_account) and frappe.db.exists("GL Entry", {"account": doc.petty_cash_account, "is_cancelled": 0}):
        frappe.throw(frappe._("La cuenta exclusiva de Caja Chica debe comenzar sin movimientos contables"))
    if previous and previous.petty_cash_responsible != doc.petty_cash_responsible and balance(previous) != 0 and not getattr(frappe.local, "hs_petty_handover", False):
        frappe.throw(frappe._("Con saldo, cambie el responsable mediante un traspaso con dos aceptaciones"))


def unsettled(prop):
    """Open custody and reimbursement work must stay attached to its original account."""
    expenses = current_all("HS Petty Cash Expense", filters={"property": prop.name, "status": "Posted"}, fields=["rendition"])
    return bool(
        any(not row.rendition or frappe.db.get_value("HS Petty Cash Rendition", row.rendition, "status") == "Returned" for row in expenses)
        or current_all("HS Petty Cash Rendition", filters={"property": prop.name,
                 "status": ["in", ["Submitted", "Approved", "Partially Reimbursed"]]}, pluck="name")
        or current_all("HS Petty Cash Handover", filters={"property": prop.name,
                 "status": "Awaiting Acceptance"}, pluck="name")
    )


def validate_concept(doc):
    if doc.nature not in NATURE:
        frappe.throw(frappe._("Seleccione ingreso, préstamo o capital para el concepto"))
    doc.currency = base(doc)
    account(doc, doc.account, NATURE[doc.nature])


def update_concept(prop, data):
    require(prop.name, "setup")
    from hospitality_suite.service import assert_version
    concept = document("HS Treasury Concept", data.get("concept"), "setup")
    assert_version(concept, data.get("modified"))
    for field in ("label", "nature", "account", "active"):
        if field in data:
            concept.set(field, data[field])
    concept.save()
    audit(prop, "Update treasury concept", concept, data.get("reason"))
    return dict(concept=concept.name)


def configured(prop):
    if not all(prop.get(f) for f in ("petty_cash_account", "petty_cash_responsible", "petty_cash_overage_account", "petty_cash_shortage_account")):
        frappe.throw(frappe._("Configure Caja Chica, responsable y cuentas de diferencias en el establecimiento"))
    validate_property(prop)
    if ledger_balance(prop) != balance(prop):
        frappe.throw(frappe._("El mayor de Caja Chica no coincide con sus movimientos; concilie antes de continuar"))
    return base(prop)


def positive(prop, value):
    amount = money(value, currency=base(prop))
    if amount <= 0 or decimal(value) != amount:
        frappe.throw(frappe._("Indique un importe positivo en moneda base con precisión válida"))
    return amount


def balance(prop):
    """Operational balance; reconciliation separately checks the underlying GL."""
    if not prop.get("petty_cash_account"):
        return Decimal(0)
    value = Decimal(0)
    for row in current_all("HS Treasury Movement", filters={"property": prop.name, "status": "Posted",
                                                        "kind": ["in", ["Initial Fund", "Replenishment"]]}, fields=["amount"]):
        value += decimal(row.amount)
    for row in current_all("HS Petty Cash Expense", filters={"property": prop.name, "status": "Posted"}, fields=["amount"]):
        value -= decimal(row.amount)
    for row in current_all("HS Petty Cash Rendition", filters={"property": prop.name,
                                                              "status": ["in", ["Approved", "Partially Reimbursed", "Reimbursed"]]}, fields=["variance"]):
        value += decimal(row.variance)
    return money(value, currency=base(prop))


def ledger_balance(prop):
    if not prop.get("petty_cash_account"):
        return Decimal(0)
    entries = current_all("GL Entry", filters={"account": prop.petty_cash_account, "is_cancelled": 0},
                          fields=["debit", "credit"])
    return money(sum((decimal(row.debit)-decimal(row.credit) for row in entries), Decimal(0)), currency=base(prop))


def fund_view(prop):
    if not prop.get("petty_cash_account"):
        return dict(active=False, balance="0", expected_cash="0", responsible=None, currency=base(prop))
    pending = current_all("HS Petty Cash Expense", filters={"property": prop.name, "status": "Posted", "rendition": ["is", "not set"]}, fields=["amount"])
    return dict(active=all(prop.get(f) for f in ("petty_cash_account", "petty_cash_responsible", "petty_cash_overage_account", "petty_cash_shortage_account")),
                responsible=prop.petty_cash_responsible, account=prop.petty_cash_account, currency=base(prop),
                balance=str(ledger_balance(prop)), expected_cash=str(balance(prop)),
                pending_expenses=str(sum((decimal(r.amount) for r in pending), Decimal(0))))


def journal(prop, debit, credit, amount, reason, shift=None, reference=None):
    account(prop, debit, frappe.db.get_value("Account", debit, "root_type"))
    account(prop, credit, frappe.db.get_value("Account", credit, "root_type"))
    doc = frappe.new_doc("Journal Entry")
    doc.update(dict(company=prop.company, posting_date=nowdate(), voucher_type="Cash Entry" if shift else "Journal Entry",
                    hs_shift=shift, user_remark=reason))
    if reference:
        doc.cheque_no, doc.cheque_date = reference, nowdate()
    for name, is_debit in ((debit, True), (credit, False)):
        doc.append("accounts", dict(account=name, debit_in_account_currency=float(amount) if is_debit else 0,
                                    credit_in_account_currency=0 if is_debit else float(amount), exchange_rate=1,
                                    cost_center=prop.cost_center))
    return post_standard(doc, prop)


def cash_context(prop, data, amount, outgoing=False):
    from hospitality_suite.cashier import expected
    shift = document("HS Shift", data.get("shift"), "finance")
    method = document("HS Payment Method", data.get("method"), "finance")
    if shift.status != "Open" or not method.is_cash or method.currency != base(prop) or shift.currency != base(prop):
        frappe.throw(frappe._("Seleccione un turno abierto y un medio en efectivo en moneda base"))
    if shift.cashier != frappe.session.user:
        require(prop.name, "cash_approve")
    account(prop, method.account, "Asset", "Cash")
    if outgoing and amount > decimal(expected(shift).get(base(prop), 0)):
        frappe.throw(frappe._("El movimiento supera el efectivo esperado del turno"))
    return shift, method


def fund_transfer(prop, data):
    ready(prop)
    configured(prop)
    kind = data.get("kind")
    if kind not in ("Initial Fund", "Replenishment"):
        frappe.throw(frappe._("Tipo de entrega de Caja Chica inválido"))
    amount = positive(prop, data.get("amount"))
    shift, method = cash_context(prop, data, amount, outgoing=True)
    if kind == "Initial Fund":
        if current_all("HS Treasury Movement", filters={"property": prop.name, "kind": kind, "status": ["!=", "Cancelled"]}, pluck="name"):
            frappe.throw(frappe._("El fondo inicial ya se entregó"))
        if balance(prop) != 0:
            frappe.throw(frappe._("La Caja Chica debe comenzar sin saldo"))
    else:
        rendition = document("HS Petty Cash Rendition", data.get("rendition"), "finance")
        if rendition.status not in ("Approved", "Partially Reimbursed"):
            frappe.throw(frappe._("Solo se reponen rendiciones aprobadas con gastos pendientes"))
        previous = sum((decimal(r.amount) for r in current_all("HS Treasury Movement", filters={"rendition": rendition.name,
                             "kind": "Replenishment", "status": "Posted"}, fields=["amount"])), Decimal(0))
        if amount > decimal(rendition.expense_total) - previous:
            frappe.throw(frappe._("La entrega supera los gastos aprobados pendientes de reposición"))
    posted = journal(prop, prop.petty_cash_account, method.account, amount, kind, shift.name)
    move = insert("HS Treasury Movement", prop, kind=kind, rendition=rendition.name if kind == "Replenishment" else None,
                  shift=shift.name, method=method.name, cash_account=method.account,
                  counter_account=prop.petty_cash_account, currency=base(prop), amount=amount,
                  business_date=prop.business_date, status="Posted", requested_by=frappe.session.user,
                  journal_entry=posted.name, reason=data.get("reason") or kind)
    if kind == "Replenishment":
        rendition.status = "Reimbursed" if amount == decimal(rendition.expense_total) - previous else "Partially Reimbursed"
        rendition.save()
    audit(prop, kind, move, data.get("reason"))
    return dict(movement=move.name, journal_entry=posted.name, balance=str(balance(prop)))


def petty_expense(prop, data):
    ready(prop)
    configured(prop)
    if prop.petty_cash_responsible != frappe.session.user:
        frappe.throw(frappe._("Solo el responsable asignado puede desembolsar Caja Chica"), frappe.PermissionError)
    category = document("HS Expense Category", data.get("category"))
    amount = positive(prop, data.get("amount"))
    if not category.active or (category.max_amount and amount > decimal(category.max_amount)):
        frappe.throw(frappe._("La categoría no está activa o se superó su límite por operación"))
    if amount > balance(prop):
        frappe.throw(frappe._("Caja Chica no dispone de ese saldo"))
    for field in ("beneficiary", "concept", "receipt_reference"):
        if not str(data.get(field) or "").strip():
            frappe.throw(frappe._("Complete beneficiario, concepto y referencia del comprobante"))
    account(prop, category.account, "Expense")
    posted = journal(prop, category.account, prop.petty_cash_account, amount, data["concept"])
    expense = insert("HS Petty Cash Expense", prop, category=category.name, category_label=category.label, responsible=frappe.session.user,
                     beneficiary=data["beneficiary"].strip(), concept=data["concept"].strip(),
                     receipt_reference=data["receipt_reference"].strip(), currency=base(prop), amount=amount,
                     business_date=prop.business_date, expense_account=category.account,
                     petty_account=prop.petty_cash_account, journal_entry=posted.name, status="Posted")
    audit(prop, "Petty cash expense", expense, data["concept"])
    return dict(expense=expense.name, journal_entry=posted.name, balance=str(balance(prop)))


def correct_expense(prop, data):
    expense = document("HS Petty Cash Expense", data.get("expense"), "petty")
    if expense.responsible != frappe.session.user or expense.status != "Posted":
        frappe.throw(frappe._("Solo el responsable puede corregir un gasto vigente"), frappe.PermissionError)
    if expense.rendition:
        rendition = document("HS Petty Cash Rendition", expense.rendition, "petty")
        if rendition.status != "Returned":
            frappe.throw(frappe._("La rendición debe estar devuelta para corregir comprobantes"))
    for field in ("beneficiary", "concept", "receipt_reference"):
        if field in data:
            if not str(data[field] or "").strip():
                frappe.throw(frappe._("Los datos descriptivos no pueden quedar vacíos"))
            expense.set(field, data[field].strip())
    expense.save()
    audit(prop, "Correct petty cash expense", expense, data.get("reason"))
    return dict(expense=expense.name)


def submit_rendition(prop, data):
    ready(prop)
    configured(prop)
    if prop.petty_cash_responsible != frappe.session.user:
        frappe.throw(frappe._("Solo el responsable asignado puede presentar la rendición"), frappe.PermissionError)
    count = money(data.get("counted_cash"), currency=base(prop))
    if count < 0 or decimal(data.get("counted_cash")) != count:
        frappe.throw(frappe._("El conteo físico debe ser válido y no negativo"))
    if data.get("rendition"):
        rendition = document("HS Petty Cash Rendition", data["rendition"], "petty")
        if rendition.status != "Returned" or rendition.responsible != frappe.session.user:
            frappe.throw(frappe._("Solo una rendición devuelta puede presentarse de nuevo"))
        expenses = [document("HS Petty Cash Expense", name, "petty") for name in frappe.parse_json(rendition.expenses or "[]")]
        expenses = [e for e in expenses if e.status == "Posted"]
        expenses += [document("HS Petty Cash Expense", name, "petty") for name in current_all("HS Petty Cash Expense",
                    filters={"property": prop.name, "status": "Posted", "rendition": ["is", "not set"]}, pluck="name")]
    else:
        expenses = [document("HS Petty Cash Expense", name, "petty") for name in current_all("HS Petty Cash Expense",
                    filters={"property": prop.name, "status": "Posted", "rendition": ["is", "not set"]}, pluck="name")]
        if not expenses:
            frappe.throw(frappe._("No hay gastos sin rendir"))
    if not expenses or any(e.status != "Posted" for e in expenses):
        frappe.throw(frappe._("La rendición contiene un gasto anulado"))
    expected = balance(prop)
    variance = count - expected
    if variance and not str(data.get("explanation") or "").strip():
        frappe.throw(frappe._("Explique la diferencia del arqueo"))
    total = sum((decimal(e.amount) for e in expenses), Decimal(0))
    if data.get("rendition"):
        rendition.update(dict(expected_cash=expected, counted_cash=count, variance=variance,
                              expense_total=total, explanation=data.get("explanation"), status="Submitted",
                              expenses=frappe.as_json([e.name for e in expenses]),
                              submitted_by=frappe.session.user, submitted_at=now_datetime()))
        rendition.save()
        for expense in expenses:
            if not expense.rendition:
                expense.rendition = rendition.name
                expense.save()
    else:
        rendition = insert("HS Petty Cash Rendition", prop, responsible=frappe.session.user,
                           expenses=frappe.as_json([e.name for e in expenses]), currency=base(prop),
                           expected_cash=expected, counted_cash=count, variance=variance, expense_total=total,
                           explanation=data.get("explanation"), status="Submitted",
                           submitted_by=frappe.session.user, submitted_at=now_datetime())
        for expense in expenses:
            expense.rendition = rendition.name
            expense.save()
    audit(prop, "Submit petty cash rendition", rendition, data.get("explanation"))
    return dict(rendition=rendition.name, expected_cash=str(expected), variance=str(variance), expense_total=str(total))


def review_rendition(prop, data):
    require(prop.name, "approve")
    rendition = document("HS Petty Cash Rendition", data.get("rendition"), "finance")
    if rendition.status != "Submitted" or rendition.submitted_by == frappe.session.user:
        frappe.throw(frappe._("La rendición debe estar presentada y requiere un aprobador distinto"))
    if not data.get("approve"):
        if not str(data.get("note") or "").strip():
            frappe.throw(frappe._("Indique qué debe corregirse"))
        rendition.status = "Returned"
    else:
        if decimal(rendition.expected_cash) != balance(prop):
            frappe.throw(frappe._("El saldo cambió desde la presentación; devuelva y actualice el arqueo"))
        variance = decimal(rendition.variance)
        if variance:
            configured(prop)
            account_name = prop.petty_cash_overage_account if variance > 0 else prop.petty_cash_shortage_account
            posted = journal(prop, prop.petty_cash_account if variance > 0 else account_name,
                             account_name if variance > 0 else prop.petty_cash_account,
                             abs(variance), rendition.explanation or data.get("note") or "Diferencia Caja Chica")
            rendition.variance_journal = posted.name
            rendition.variance_account = account_name
        rendition.status = "Approved"
        rendition.approved_business_date = prop.business_date
    rendition.reviewed_by, rendition.reviewed_at, rendition.review_note = frappe.session.user, now_datetime(), data.get("note")
    rendition.save()
    audit(prop, "Approve petty cash rendition" if data.get("approve") else "Return petty cash rendition", rendition, data.get("note"))
    return dict(rendition=rendition.name, status=rendition.status, balance=str(balance(prop)))


def request_handover(prop, data):
    require(prop.name, "approve")
    configured(prop)
    incoming = data.get("incoming")
    if incoming == prop.petty_cash_responsible or not frappe.db.get_value("User", incoming, "enabled"):
        frappe.throw(frappe._("Seleccione otro usuario activo"))
    from hospitality_suite.security import allowed_properties
    if prop.name not in allowed_properties(incoming):
        frappe.throw(frappe._("El nuevo responsable requiere acceso al establecimiento"))
    if current_all("HS Petty Cash Handover", filters={"property": prop.name, "status": "Awaiting Acceptance"}, pluck="name"):
        frappe.throw(frappe._("Ya existe un traspaso pendiente"))
    expected = balance(prop)
    counted = money(data.get("counted_cash"), currency=base(prop))
    if counted != expected:
        frappe.throw(frappe._("El traspaso requiere arqueo sin diferencia; rinda y apruebe la diferencia primero"))
    handover = insert("HS Petty Cash Handover", prop, outgoing=prop.petty_cash_responsible, incoming=incoming,
                      requested_by=frappe.session.user, expected_cash=expected, counted_cash=counted,
                      reason=data.get("reason"), status="Awaiting Acceptance", requested_at=now_datetime())
    audit(prop, "Request petty cash handover", handover, data.get("reason"))
    return dict(handover=handover.name)


def accept_handover(prop, data):
    handover = document("HS Petty Cash Handover", data.get("handover"), "petty")
    if handover.status != "Awaiting Acceptance" or frappe.session.user not in (handover.outgoing, handover.incoming):
        frappe.throw(frappe._("Solo los responsables saliente y entrante pueden aceptar"), frappe.PermissionError)
    if prop.petty_cash_responsible != handover.outgoing or balance(prop) != decimal(handover.expected_cash):
        frappe.throw(frappe._("El saldo cambió; solicite un nuevo arqueo de traspaso"))
    handover.set("outgoing_accepted" if frappe.session.user == handover.outgoing else "incoming_accepted", 1)
    if handover.outgoing_accepted and handover.incoming_accepted:
        before = getattr(frappe.local, "hs_petty_handover", False)
        frappe.local.hs_petty_handover = True
        try:
            prop.petty_cash_responsible = handover.incoming
            prop.save()
        finally:
            frappe.local.hs_petty_handover = before
        handover.status, handover.completed_at = "Completed", now_datetime()
    handover.save()
    audit(prop, "Accept petty cash handover", handover)
    return dict(handover=handover.name, status=handover.status)


def outstanding(source, exclude=None):
    returned = sum((decimal(r.amount) for r in current_all("HS Treasury Movement", filters={"source_movement": source.name,
                       "status": "Posted"}, fields=["amount"])), Decimal(0))
    reserved = sum((decimal(r.amount) for r in current_all("HS Treasury Movement", filters={"source_movement": source.name,
                       "status": ["in", ["Pending Approval", "Approved"]]}, fields=["name", "amount"]) if r.name != exclude), Decimal(0))
    return decimal(source.amount) - returned - reserved


def financing_request(prop, data):
    ready(prop)
    kind = data.get("kind")
    if kind not in FINANCING:
        frappe.throw(frappe._("Seleccione un préstamo o aporte/retiro de capital"))
    amount = positive(prop, data.get("amount"))
    if kind in OUTGOING:
        source = document("HS Treasury Movement", data.get("source_movement"), "finance")
        if source.kind != ("Loan Received" if kind == "Loan Repayment" else "Capital Contribution") or source.status != "Posted" or amount > outstanding(source):
            frappe.throw(frappe._("La devolución supera el principal pendiente de su entrada original"))
        concept_name, counter_account, concept_label = source.concept, source.counter_account, source.concept_label
    else:
        concept = document("HS Treasury Concept", data.get("concept"), "finance")
        if not concept.active or concept.nature != KIND_NATURE[kind]:
            frappe.throw(frappe._("Seleccione un concepto activo de la naturaleza indicada"))
        account(prop, concept.account, NATURE[concept.nature])
        concept_name, counter_account, concept_label = concept.name, concept.account, concept.label
    movement = insert("HS Treasury Movement", prop, kind=kind, concept=concept_name, concept_label=concept_label,
                      source_movement=data.get("source_movement") if kind in OUTGOING else None,
                      counter_account=counter_account, currency=base(prop), amount=amount,
                      business_date=prop.business_date, reason=data.get("reason"), requested_by=frappe.session.user,
                      status="Pending Approval")
    audit(prop, "Request financing", movement, data.get("reason"))
    return dict(movement=movement.name, status=movement.status)


def approve_financing(prop, data):
    require(prop.name, "approve")
    movement = document("HS Treasury Movement", data.get("movement"), "finance")
    if movement.kind not in FINANCING or movement.status != "Pending Approval" or movement.requested_by == frappe.session.user:
        frappe.throw(frappe._("Se requiere solicitud pendiente y aprobación por otro usuario"))
    if movement.kind in OUTGOING:
        source = document("HS Treasury Movement", movement.source_movement, "finance")
        if source.status != "Posted":
            frappe.throw(frappe._("La entrada original ya no está vigente"))
    movement.status, movement.approved_by, movement.approved_at = "Approved", frappe.session.user, now_datetime()
    movement.save()
    audit(prop, "Approve financing", movement, data.get("reason"))
    return dict(movement=movement.name, status=movement.status)


def financial_quote(prop, data):
    kind = data.get("kind")
    if kind not in INCOMING | OUTGOING:
        frappe.throw(frappe._("Tipo de movimiento financiero inválido"))
    amount = positive(prop, data.get("amount"))
    approved = document("HS Treasury Movement", data["movement"], "finance") if data.get("movement") else None
    if approved and (approved.status != "Approved" or approved.kind != kind or decimal(approved.amount) != amount):
        frappe.throw(frappe._("La solicitud aprobada ya no coincide con el importe o tipo"))
    if kind in OUTGOING:
        source = document("HS Treasury Movement", data.get("source_movement"), "finance")
        if source.kind != ("Loan Received" if kind == "Loan Repayment" else "Capital Contribution") or source.status != "Posted" or amount > outstanding(source, approved.name if approved else None):
            frappe.throw(frappe._("No existe principal suficiente en la entrada original"))
        counter = source.counter_account
    elif approved:
        counter = approved.counter_account
    else:
        concept = document("HS Treasury Concept", data.get("concept"), "finance")
        if not concept.active or concept.nature != KIND_NATURE[kind]:
            frappe.throw(frappe._("El concepto no corresponde al movimiento"))
        counter = concept.account
    account(prop, counter, NATURE[KIND_NATURE[kind]])
    channel = data.get("channel")
    if channel == "Cash":
        shift, method = cash_context(prop, data, amount, outgoing=kind in OUTGOING)
        cash_account, shift_name, method_name = method.account, shift.name, method.name
    elif channel == "Bank":
        cash_account = data.get("bank_account")
        account(prop, cash_account, "Asset", "Bank")
        shift_name = method_name = None
        if not data.get("reference"):
            frappe.throw(frappe._("Indique la referencia bancaria"))
    else:
        frappe.throw(frappe._("Seleccione Caja o banco"))
    if cash_account == counter:
        frappe.throw(frappe._("La cuenta de contrapartida debe ser distinta de Caja o banco"))
    return dict(kind=kind, amount=str(amount), currency=base(prop), debit=cash_account if kind in INCOMING else counter,
                credit=counter if kind in INCOMING else cash_account, cash_account=cash_account,
                counter_account=counter, shift=shift_name, method=method_name, channel=channel)


def post_financial(prop, data):
    ready(prop)
    movement = document("HS Treasury Movement", data["movement"], "finance") if data.get("movement") else None
    if movement:
        if movement.kind not in FINANCING or movement.status != "Approved":
            frappe.throw(frappe._("El movimiento requiere aprobación previa de Gerencia"))
        quote_data = {**data, "kind": movement.kind, "amount": movement.amount,
                      "source_movement": movement.source_movement, "concept": movement.concept}
        if movement.kind in OUTGOING:
            source = document("HS Treasury Movement", movement.source_movement, "finance")
            if decimal(movement.amount) > outstanding(source, movement.name):
                frappe.throw(frappe._("La entrada original no dispone de ese principal"))
    else:
        if data.get("kind") != "Other Income":
            frappe.throw(frappe._("Solo otros ingresos pueden registrarse sin aprobación previa"))
        quote_data = data
    quote = financial_quote(prop, quote_data)
    if movement and quote["counter_account"] != movement.counter_account:
        frappe.throw(frappe._("La cuenta aprobada cambió; presente una nueva solicitud"))
    posted = journal(prop, quote["debit"], quote["credit"], decimal(quote["amount"]),
                     data.get("reason") or quote["kind"], quote["shift"], data.get("reference"))
    if movement:
        movement.update(dict(shift=quote["shift"], method=quote["method"], cash_account=quote["cash_account"],
                             journal_entry=posted.name, status="Posted", reference=data.get("reference"),
                             business_date=prop.business_date))
        movement.save()
    else:
        concept = document("HS Treasury Concept", data["concept"], "finance")
        movement = insert("HS Treasury Movement", prop, kind=quote["kind"], concept=concept.name, concept_label=concept.label,
                          shift=quote["shift"], method=quote["method"], cash_account=quote["cash_account"],
                          counter_account=quote["counter_account"], currency=base(prop), amount=quote["amount"],
                          business_date=prop.business_date, status="Posted", requested_by=frappe.session.user,
                          journal_entry=posted.name, reference=data.get("reference"), reason=data.get("reason"))
    audit(prop, "Post financial movement", movement, data.get("reason"), quote)
    return dict(movement=movement.name, journal_entry=posted.name, **quote)


def reverse(prop, data):
    """Authorized same-business-day reversal; native on_cancel updates the ledger."""
    require(prop.name, "approve")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        frappe.throw(frappe._("Indique el motivo de reversión contable"))
    kind = data.get("doctype")
    if kind == "HS Petty Cash Expense":
        source = document(kind, data.get("name"), "finance")
        if source.rendition and frappe.db.get_value("HS Petty Cash Rendition", source.rendition, "status") != "Returned":
            frappe.throw(frappe._("Devuelva primero la rendición y revierta antes de aprobarla"))
    elif kind == "HS Treasury Movement":
        source = document(kind, data.get("name"), "finance")
    elif kind == "HS Petty Cash Rendition":
        source = document(kind, data.get("name"), "finance")
        if source.status != "Approved" or not source.variance_journal:
            frappe.throw(frappe._("Solo un ajuste aprobado y sin reposiciones admite reversión"))
    else:
        frappe.throw(frappe._("Documento de reversión no admitido"))
    if kind == "HS Treasury Movement" and source.status in ("Pending Approval", "Approved"):
        source.status = "Cancelled"
        source.save()
        audit(prop, "Cancel financing request", source, reason)
        return dict(name=source.name, status=source.status)
    if kind != "HS Petty Cash Rendition" and source.status != "Posted":
        frappe.throw(frappe._("El movimiento ya no está vigente"))
    business_date = source.approved_business_date if kind == "HS Petty Cash Rendition" else source.business_date
    if str(business_date) != str(prop.business_date):
        frappe.throw(frappe._("La fecha operativa ya cerró; realice un ajuste contable autorizado en ERPNext"))
    journal_entry = source.variance_journal if kind == "HS Petty Cash Rendition" else source.journal_entry
    native = locked_doc("Journal Entry", journal_entry)
    if native.docstatus != 1 or native.hs_property != prop.name:
        frappe.throw(frappe._("El asiento original no está vigente en este establecimiento"))
    if native.hs_shift and frappe.db.get_value("HS Shift", native.hs_shift, "status") != "Open":
        frappe.throw(frappe._("El turno del asiento ya cerró"))
    native.hs_correction_reason = reason
    native.flags.ignore_permissions = True
    native.cancel()
    audit(prop, "Reverse financial movement", source, reason)
    return dict(name=source.name, journal_entry=native.name, status="Cancelled")
