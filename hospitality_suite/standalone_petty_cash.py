"""One reconciled petty-cash fund per property on the PMS ledger."""

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount, inverse_lines
from hospitality_suite.security import allowed_properties, can_receive_petty_cash, petty_handover_users, require
from hospitality_suite.service import audit, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, account_currency_balance, balance as gl_balance, post, require_pms
from hospitality_suite.standalone_cash import expected


CONFIG = ("petty_cash_account", "petty_cash_responsible",
          "petty_cash_overage_account", "petty_cash_shortage_account")


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _value(raw, *, positive=False):
    try:
        value = amount(raw)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if positive and value <= 0:
        frappe.throw(_("Indique un importe positivo en moneda base"))
    return value


def _text(raw, label, maximum=500):
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > maximum:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, maximum))
    return raw.strip()


def _receipt_file(raw):
    if not raw:
        return None
    if (not isinstance(raw, str) or len(raw) > 255 or
            not raw.startswith(("/files/", "/private/files/"))):
        frappe.throw(_("Seleccione un archivo de comprobante cargado en la Suite"))
    uploaded = frappe.db.get_value("File", {"file_url": raw},
                                   ["name", "owner"], as_dict=True)
    if not uploaded or uploaded.owner != frappe.session.user:
        frappe.throw(_("El archivo del comprobante no pertenece al responsable"),
                     frappe.PermissionError)
    return raw


def _account(prop, name, root):
    selected = account(prop, name)
    if selected.root_type != root or selected.account_currency != prop.currency:
        frappe.throw(_("La cuenta de Caja Chica requiere naturaleza y moneda base correctas"))
    return selected


def unsettled(prop):
    expenses = current_all("HS Petty Cash Expense", filters={"property": prop.name,
        "status": "Posted"}, fields=["rendition"])
    return bool(any(not row.rendition or frappe.db.get_value(
        "HS Petty Cash Rendition", row.rendition, "status") == "Returned"
        for row in expenses) or frappe.db.exists("HS Petty Cash Rendition", {
            "property": prop.name,
            "status": ["in", ["Submitted", "Approved", "Partially Reimbursed"]]}) or
        frappe.db.exists("HS Petty Cash Handover", {"property": prop.name,
            "status": "Awaiting Acceptance"}))


def operational_balance(prop):
    if not prop.petty_cash_account:
        return Decimal(0)
    funds = current_all("HS Treasury Movement", filters={"property": prop.name,
        "kind": ["in", ["Initial Fund", "Replenishment"]],
        "status": "Posted", "pms_journal": ["is", "set"]}, fields=["amount"])
    expenses = current_all("HS Petty Cash Expense", filters={"property": prop.name,
        "status": "Posted", "pms_journal": ["is", "set"]}, fields=["amount"])
    renditions = current_all("HS Petty Cash Rendition", filters={"property": prop.name,
        "status": ["in", ["Approved", "Partially Reimbursed", "Reimbursed"]],
        "pms_variance_journal": ["is", "set"]},
        fields=["variance", "pms_variance_reversal_journal"])
    return (sum((Decimal(str(row.amount)) for row in funds), Decimal(0)) -
            sum((Decimal(str(row.amount)) for row in expenses), Decimal(0)) +
            sum((Decimal(str(row.variance)) for row in renditions
                 if not row.pms_variance_reversal_journal), Decimal(0)))


def validate_property(doc, check_history=True):
    require_pms(doc)
    prior = doc.get_doc_before_save()
    if prior and prior.petty_cash_account and prior.petty_cash_account != doc.petty_cash_account:
        if operational_balance(prior) != 0 or unsettled(prior):
            frappe.throw(_("No cambie la cuenta de Caja Chica con saldo o movimientos pendientes"))
    if not any(doc.get(field) for field in CONFIG):
        return
    if not all(doc.get(field) for field in CONFIG):
        frappe.throw(_("Complete cuenta, responsable y cuentas de diferencias de Caja Chica"))
    if not frappe.db.get_value("User", doc.petty_cash_responsible, "enabled") or (
            doc.name not in allowed_properties(doc.petty_cash_responsible)):
        frappe.throw(_("El responsable debe estar activo y tener acceso al establecimiento"))
    _account(doc, doc.petty_cash_account, "Asset")
    _account(doc, doc.petty_cash_overage_account, "Income")
    _account(doc, doc.petty_cash_shortage_account, "Expense")
    if len({doc.petty_cash_account, doc.petty_cash_overage_account,
            doc.petty_cash_shortage_account}) != 3:
        frappe.throw(_("Las cuentas de Caja Chica y diferencias deben ser distintas"))
    if frappe.db.exists("HS Property", {"petty_cash_account": doc.petty_cash_account,
            "name": ["!=", doc.name]}):
        frappe.throw(_("La cuenta de Caja Chica ya pertenece a otro establecimiento"))
    if check_history and (not prior or prior.petty_cash_account != doc.petty_cash_account) and frappe.db.exists(
            "HS Journal Line", {"account": doc.petty_cash_account}):
        frappe.throw(_("La cuenta exclusiva de Caja Chica debe comenzar sin asientos"))
    if (prior and prior.petty_cash_responsible != doc.petty_cash_responsible and
            operational_balance(prior) != 0 and
            not getattr(frappe.local, "hs_petty_handover", False)):
        frappe.throw(_("Con saldo, cambie responsable mediante arqueo y dos aceptaciones"))


def configure(prop, data):
    require_pms(prop)
    require(prop.name, "setup")
    if not isinstance(data, dict) or set(data) != set(CONFIG):
        frappe.throw(_("Configure las cuatro referencias de Caja Chica"))
    before = {field: prop.get(field) for field in CONFIG}
    for field in CONFIG:
        prop.set(field, data[field])
    prop.save()
    audit(prop, "pms_petty_cash_configured", prop, before=before)
    return {"property": prop.name, "active": bool(prop.petty_cash_account)}


def configured(prop):
    require_pms(prop)
    if not all(prop.get(field) for field in CONFIG):
        frappe.throw(_("Configure Caja Chica, responsable y cuentas de diferencias"))
    validate_property(prop, check_history=False)
    ledger = Decimal(gl_balance(prop, prop.petty_cash_account))
    operational = operational_balance(prop)
    if ledger != operational:
        frappe.throw(_("El mayor de Caja Chica no coincide con sus movimientos"))
    return operational


def _responsible(prop):
    if prop.petty_cash_responsible != frappe.session.user:
        frappe.throw(_("Solo el responsable asignado puede operar Caja Chica"), frappe.PermissionError)


def _cash(prop, data, value):
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not method.is_cash or method.currency != prop.currency:
        frappe.throw(_("Use un medio de efectivo en moneda base del establecimiento"))
    cash = account(prop, method.account)
    if not cash.is_cash or cash.account_currency != prop.currency:
        frappe.throw(_("El medio no conserva una cuenta de Caja válida"))
    shift = locked_doc("HS Shift", data.get("shift"))
    if (shift.property != prop.name or shift.status != "Open" or
            shift.cashier != frappe.session.user):
        frappe.throw(_("Se requiere turno abierto propio"), frappe.PermissionError)
    if value > Decimal(expected(shift).get(prop.currency, "0")) or value > Decimal(
            account_currency_balance(prop, cash.name)["balance"]):
        frappe.throw(_("El turno o la cuenta no tienen efectivo suficiente"))
    return shift, method, cash


def _replenishable(prop, rendition):
    replenished = sum((Decimal(str(row.amount)) for row in current_all(
        "HS Treasury Movement", filters={"property": prop.name,
            "rendition": rendition.name, "kind": "Replenishment",
            "status": "Posted", "pms_journal": ["is", "set"]},
        fields=["amount"])), Decimal(0))
    left = Decimal(str(rendition.expense_total)) - replenished
    if left < 0:
        frappe.throw(_("La rendición requiere conciliación de reposiciones"))
    return left


def fund(prop, data):
    configured(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"kind", "rendition", "method",
            "shift", "amount", "reference", "reason"}:
        frappe.throw(_("Revise la entrega de Caja Chica"))
    kind = data.get("kind")
    if kind not in ("Initial Fund", "Replenishment"):
        frappe.throw(_("Seleccione fondo inicial o reposición"))
    value = _value(data.get("amount"), positive=True)
    shift, method, cash = _cash(prop, data, value)
    rendition = None
    if kind == "Initial Fund":
        if data.get("rendition") or frappe.db.exists("HS Treasury Movement", {
                "property": prop.name, "kind": kind,
                "status": ["!=", "Cancelled"]}) or operational_balance(prop) != 0:
            frappe.throw(_("El fondo inicial ya se entregó o Caja Chica tiene saldo"))
    else:
        rendition = locked_doc("HS Petty Cash Rendition", data.get("rendition"))
        if (rendition.property != prop.name or
                rendition.status not in ("Approved", "Partially Reimbursed") or
                value > _replenishable(prop, rendition)):
            frappe.throw(_("La reposición supera los gastos aprobados pendientes"))
    reference = _text(data.get("reference"), "la referencia", 140)
    reason = _text(data.get("reason"), "el motivo")
    movement = insert("HS Treasury Movement", prop, kind=kind,
        rendition=rendition.name if rendition else None,
        shift=shift.name, method=method.name, cash_account=cash.name,
        counter_account=prop.petty_cash_account, currency=prop.currency,
        amount=_money(value), base_amount=_money(value), exchange_rate=1,
        business_date=prop.business_date, reference=reference, reason=reason,
        requested_by=frappe.session.user, status="Approved")
    journal = post(prop, source_doctype=movement.doctype, source_name=movement.name,
        purpose=kind, memo=reason, lines=[
            {"account": prop.petty_cash_account, "debit": _money(value), "credit": 0},
            {"account": cash.name, "debit": 0, "credit": _money(value)}])
    movement.status = "Posted"
    movement.pms_journal = journal.name
    movement.save()
    if rendition:
        rendition.status = ("Reimbursed" if _replenishable(prop, rendition) == 0
                            else "Partially Reimbursed")
        rendition.save()
    audit(prop, "pms_petty_fund_transferred", movement, reason=reason,
          details={"journal": journal.name, "amount": _money(value)})
    return {"movement": movement.name, "journal": journal.name,
        "balance": _money(operational_balance(prop))}


def expense(prop, data):
    configured(prop)
    require(prop.name, "petty")
    _responsible(prop)
    if not isinstance(data, dict) or set(data) - {"category", "beneficiary",
            "concept", "receipt_reference", "receipt_file", "amount"}:
        frappe.throw(_("Revise el desembolso de Caja Chica"))
    category = locked_doc("HS Expense Category", data.get("category"))
    value = _value(data.get("amount"), positive=True)
    if category.property != prop.name or not category.active or (
            category.max_amount and value > Decimal(str(category.max_amount))):
        frappe.throw(_("La categoría no está activa o el importe supera su límite"))
    expense_account = _account(prop, category.account, "Expense")
    if value > operational_balance(prop):
        frappe.throw(_("Caja Chica no dispone de ese saldo"))
    beneficiary = _text(data.get("beneficiary"), "el beneficiario", 140)
    concept = _text(data.get("concept"), "el concepto")
    reference = _text(data.get("receipt_reference"), "la referencia del comprobante", 140)
    receipt_file = _receipt_file(data.get("receipt_file"))
    row = insert("HS Petty Cash Expense", prop, category=category.name,
        category_label=category.label, responsible=frappe.session.user,
        beneficiary=beneficiary, concept=concept, receipt_reference=reference,
        receipt_file=receipt_file, currency=prop.currency, amount=_money(value),
        business_date=prop.business_date, expense_account=expense_account.name,
        petty_account=prop.petty_cash_account, status="Posted")
    journal = post(prop, source_doctype=row.doctype, source_name=row.name,
        purpose="Petty Cash Expense", memo=concept, lines=[
            {"account": expense_account.name, "debit": _money(value), "credit": 0},
            {"account": prop.petty_cash_account, "debit": 0, "credit": _money(value)}])
    row.pms_journal = journal.name
    row.save()
    audit(prop, "pms_petty_expense_posted", row,
          details={"journal": journal.name, "amount": _money(value)})
    return {"expense": row.name, "journal": journal.name,
        "balance": _money(operational_balance(prop))}


def correct_expense(prop, data):
    configured(prop)
    require(prop.name, "petty")
    _responsible(prop)
    if not isinstance(data, dict) or set(data) - {"expense", "beneficiary",
            "concept", "receipt_reference", "receipt_file"}:
        frappe.throw(_("Revise la corrección del comprobante"))
    row = locked_doc("HS Petty Cash Expense", data.get("expense"))
    if row.property != prop.name or row.responsible != frappe.session.user or row.status != "Posted":
        frappe.throw(_("Solo el responsable puede corregir su desembolso vigente"), frappe.PermissionError)
    if row.rendition and frappe.db.get_value("HS Petty Cash Rendition", row.rendition,
                                            "status") != "Returned":
        frappe.throw(_("La rendición debe estar devuelta para corregir comprobantes"))
    before = {field: row.get(field) for field in ("beneficiary", "concept",
                                                "receipt_reference", "receipt_file")}
    for field, maximum in (("beneficiary", 140), ("concept", 500),
                           ("receipt_reference", 140)):
        if field in data:
            row.set(field, _text(data[field], field, maximum))
    if "receipt_file" in data:
        row.receipt_file = _receipt_file(data["receipt_file"])
    row.save()
    audit(prop, "pms_petty_expense_corrected", row, before=before)
    return {"expense": row.name}


def submit(prop, data):
    configured(prop)
    require(prop.name, "petty")
    _responsible(prop)
    if not isinstance(data, dict) or set(data) - {"rendition", "counted_cash",
            "explanation"}:
        frappe.throw(_("Revise la rendición"))
    count = _value(data.get("counted_cash"))
    existing = locked_doc("HS Petty Cash Rendition", data["rendition"]) if data.get("rendition") else None
    if existing and (existing.property != prop.name or existing.status != "Returned" or
                     existing.responsible != frappe.session.user):
        frappe.throw(_("Solo una rendición propia devuelta puede presentarse de nuevo"))
    new_names = current_all("HS Petty Cash Expense", filters={"property": prop.name,
        "status": "Posted", "rendition": ["is", "not set"]}, pluck="name")
    names = list(dict.fromkeys((frappe.parse_json(existing.expenses or "[]") if existing else []) + new_names))
    expenses = [locked_doc("HS Petty Cash Expense", name) for name in names]
    if not expenses or any(row.property != prop.name or row.status != "Posted" or
            row.responsible != frappe.session.user or
            row.rendition not in (None, existing.name if existing else None) for row in expenses):
        frappe.throw(_("La rendición contiene gastos no vigentes o ajenos"))
    expected_cash = operational_balance(prop)
    variance = count - expected_cash
    explanation = data.get("explanation") or ""
    if variance:
        explanation = _text(explanation, "la justificación de la diferencia")
    elif not isinstance(explanation, str) or len(explanation) > 500:
        frappe.throw(_("Revise la explicación de la rendición"))
    expense_total = sum((Decimal(str(row.amount)) for row in expenses), Decimal(0))
    fields = dict(expenses=frappe.as_json(names), responsible=frappe.session.user,
        currency=prop.currency, expense_total=_money(expense_total),
        expected_cash=_money(expected_cash), counted_cash=_money(count),
        variance=_money(variance), explanation=explanation.strip(),
        status="Submitted", submitted_by=frappe.session.user,
        submitted_at=now_datetime())
    if existing:
        existing.update(fields)
        existing.save()
        rendition = existing
    else:
        rendition = insert("HS Petty Cash Rendition", prop, **fields)
    for row in expenses:
        if not row.rendition:
            row.rendition = rendition.name
            row.save()
    audit(prop, "pms_petty_rendition_submitted", rendition,
          details={"expenses": names, "expected_cash": _money(expected_cash),
                   "counted_cash": _money(count)})
    return {"rendition": rendition.name, "expected_cash": _money(expected_cash),
        "variance": _money(variance), "expense_total": _money(expense_total)}


def review(prop, data):
    configured(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"rendition", "approve", "note"}:
        frappe.throw(_("Revise la decisión sobre la rendición"))
    rendition = locked_doc("HS Petty Cash Rendition", data.get("rendition"))
    if (rendition.property != prop.name or rendition.status != "Submitted" or
            rendition.submitted_by == frappe.session.user):
        frappe.throw(_("La rendición requiere un aprobador distinto del responsable"))
    note = _text(data.get("note"), "la nota de revisión")
    if not data.get("approve"):
        rendition.status = "Returned"
    else:
        if Decimal(str(rendition.expected_cash)) != operational_balance(prop):
            frappe.throw(_("El saldo cambió; devuelva y actualice el arqueo"))
        names = frappe.parse_json(rendition.expenses or "[]")
        rows = [locked_doc("HS Petty Cash Expense", name) for name in names]
        if not rows or any(row.property != prop.name or row.status != "Posted" or
                row.rendition != rendition.name for row in rows) or sum((
                Decimal(str(row.amount)) for row in rows), Decimal(0)) != Decimal(str(
                rendition.expense_total)):
            frappe.throw(_("Los gastos de la rendición cambiaron; devuélvala"))
        variance = Decimal(str(rendition.variance))
        if variance:
            difference = (_account(prop, prop.petty_cash_overage_account, "Income")
                          if variance > 0 else
                          _account(prop, prop.petty_cash_shortage_account, "Expense"))
            debit = prop.petty_cash_account if variance > 0 else difference.name
            credit = difference.name if variance > 0 else prop.petty_cash_account
            variance_count = frappe.db.count("HS Journal", filters={
                "property": prop.name, "source_doctype": rendition.doctype,
                "source_name": rendition.name,
                "purpose": ["like", "Petty Cash Variance%"]})
            purpose = ("Petty Cash Variance" if variance_count == 0 else
                       f"Petty Cash Variance {variance_count + 1}")
            journal = post(prop, source_doctype=rendition.doctype,
                source_name=rendition.name, purpose=purpose,
                memo=rendition.explanation or note, lines=[
                    {"account": debit, "debit": _money(abs(variance)), "credit": 0},
                    {"account": credit, "debit": 0, "credit": _money(abs(variance))}])
            rendition.pms_variance_journal = journal.name
            rendition.pms_variance_reversal_journal = None
            rendition.variance_account = difference.name
        rendition.status = "Approved"
        rendition.approved_business_date = prop.business_date
    rendition.reviewed_by = frappe.session.user
    rendition.reviewed_at = now_datetime()
    rendition.review_note = note
    rendition.save()
    audit(prop, "pms_petty_rendition_approved" if data.get("approve")
          else "pms_petty_rendition_returned", rendition, reason=note)
    return {"rendition": rendition.name, "status": rendition.status,
        "balance": _money(operational_balance(prop))}


def handover_request(prop, data):
    configured(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"incoming", "counted_cash", "reason"}:
        frappe.throw(_("Revise el traspaso de responsable"))
    incoming = data.get("incoming")
    if (incoming == prop.petty_cash_responsible or
            not can_receive_petty_cash(prop, incoming)):
        frappe.throw(_("El nuevo responsable requiere acceso y permiso de Caja Chica en este establecimiento"))
    if frappe.db.exists("HS Petty Cash Handover", {"property": prop.name,
            "status": "Awaiting Acceptance"}):
        frappe.throw(_("Ya existe un traspaso pendiente"))
    count = _value(data.get("counted_cash"))
    expected_cash = operational_balance(prop)
    if count != expected_cash:
        frappe.throw(_("El traspaso requiere arqueo sin diferencia"))
    reason = _text(data.get("reason"), "el motivo")
    row = insert("HS Petty Cash Handover", prop,
        outgoing=prop.petty_cash_responsible, incoming=incoming,
        requested_by=frappe.session.user, expected_cash=_money(expected_cash),
        counted_cash=_money(count), reason=reason,
        status="Awaiting Acceptance", requested_at=now_datetime())
    audit(prop, "pms_petty_handover_requested", row, reason=reason)
    return {"handover": row.name, "status": row.status}


def handover_accept(prop, data):
    configured(prop)
    require(prop.name, "petty")
    if not isinstance(data, dict) or set(data) - {"handover"}:
        frappe.throw(_("Revise la aceptación del traspaso"))
    row = locked_doc("HS Petty Cash Handover", data.get("handover"))
    if (row.property != prop.name or row.status != "Awaiting Acceptance" or
            frappe.session.user not in (row.outgoing, row.incoming)):
        frappe.throw(_("Solo los responsables saliente y entrante pueden aceptar"), frappe.PermissionError)
    if (prop.petty_cash_responsible != row.outgoing or
            operational_balance(prop) != Decimal(str(row.expected_cash))):
        frappe.throw(_("El saldo cambió; solicite otro arqueo de traspaso"))
    row.set("outgoing_accepted" if frappe.session.user == row.outgoing else
            "incoming_accepted", 1)
    if row.outgoing_accepted and row.incoming_accepted:
        before = getattr(frappe.local, "hs_petty_handover", False)
        frappe.local.hs_petty_handover = True
        try:
            prop.petty_cash_responsible = row.incoming
            prop.save()
        finally:
            frappe.local.hs_petty_handover = before
        row.status = "Completed"
        row.completed_at = now_datetime()
    row.save()
    audit(prop, "pms_petty_handover_accepted", row)
    return {"handover": row.name, "status": row.status}


def handover_cancel(prop, data):
    configured(prop)
    require(prop.name, "approve")
    row = locked_doc("HS Petty Cash Handover", data.get("handover"))
    if row.property != prop.name or row.status != "Awaiting Acceptance":
        frappe.throw(_("Solo un traspaso pendiente puede cancelarse"))
    reason = _text(data.get("reason"), "el motivo")
    row.status = "Cancelled"
    row.save()
    audit(prop, "pms_petty_handover_cancelled", row, reason=reason)
    return {"handover": row.name, "status": row.status}


def _reverse_journal(prop, original, reason):
    doc = locked_doc("HS Journal", original)
    if (doc.property != prop.name or doc.status != "Posted" or doc.reversal_of or
            frappe.db.exists("HS Journal", {"reversal_of": doc.name})):
        frappe.throw(_("El asiento original no admite otra reversión"))
    lines = inverse_lines([{"account": line.account, "debit": str(line.debit),
        "credit": str(line.credit), "party": line.party, "memo": line.memo,
        "account_currency": line.account_currency,
        "exchange_rate": str(line.exchange_rate),
        "debit_in_account_currency": str(line.debit_in_account_currency),
        "credit_in_account_currency": str(line.credit_in_account_currency)}
        for line in doc.lines])
    return post(prop, source_doctype="HS Journal", source_name=doc.name,
        purpose="Reversal", lines=lines, memo=reason, reversal_of=doc.name)


def reverse(prop, data):
    configured(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"doctype", "name", "reason"}:
        frappe.throw(_("Revise la reversión de Caja Chica"))
    reason = _text(data.get("reason"), "el motivo de reversión")
    kind = data.get("doctype")
    if kind == "HS Petty Cash Expense":
        row = locked_doc(kind, data.get("name"))
        if row.property != prop.name or row.status != "Posted" or not row.pms_journal or (
                row.rendition and frappe.db.get_value("HS Petty Cash Rendition",
                    row.rendition, "status") != "Returned"):
            frappe.throw(_("Devuelva primero la rendición para revertir el desembolso"))
        original = row.pms_journal
        date = row.business_date
    elif kind == "HS Treasury Movement":
        row = locked_doc(kind, data.get("name"))
        if row.property != prop.name or row.status != "Posted" or row.kind not in (
                "Initial Fund", "Replenishment") or not row.pms_journal:
            frappe.throw(_("Seleccione una entrega vigente de Caja Chica"))
        shift = locked_doc("HS Shift", row.shift)
        if shift.property != prop.name or shift.status != "Open":
            frappe.throw(_("No revierta una entrega de un turno cerrado"))
        if row.kind == "Initial Fund" and (
                frappe.db.exists("HS Petty Cash Expense", {"property": prop.name,
                    "status": "Posted"}) or frappe.db.exists("HS Treasury Movement", {
                    "property": prop.name, "kind": "Replenishment", "status": "Posted"})):
            frappe.throw(_("El fondo inicial tiene movimientos posteriores"))
        if row.kind == "Replenishment":
            rendition = locked_doc("HS Petty Cash Rendition", row.rendition)
            if rendition.property != prop.name or rendition.status not in (
                    "Reimbursed", "Partially Reimbursed"):
                frappe.throw(_("La reposición ya no coincide con la rendición"))
        original = row.pms_journal
        date = row.business_date
    elif kind == "HS Petty Cash Rendition":
        row = locked_doc(kind, data.get("name"))
        if (row.property != prop.name or row.status != "Approved" or
                not row.pms_variance_journal or row.pms_variance_reversal_journal or
                _replenishable(prop, row) != Decimal(str(row.expense_total))):
            frappe.throw(_("Solo un ajuste aprobado sin reposiciones admite reversión"))
        original = row.pms_variance_journal
        date = row.approved_business_date
    else:
        frappe.throw(_("Documento de Caja Chica no admitido"))
    if str(date) != str(prop.business_date):
        frappe.throw(_("La fecha operativa ya cerró; use una corrección contable autorizada"))
    reversal = _reverse_journal(prop, original, reason)
    if kind == "HS Petty Cash Expense":
        row.pms_reversal_journal = reversal.name
        row.status = "Cancelled"
    elif kind == "HS Treasury Movement":
        row.pms_reversal_journal = reversal.name
        row.status = "Cancelled"
    else:
        row.pms_variance_reversal_journal = reversal.name
        row.status = "Returned"
        row.review_note = reason
    row.save()
    if kind == "HS Treasury Movement" and row.kind == "Replenishment":
        rendition.status = ("Approved" if _replenishable(prop, rendition) ==
                            Decimal(str(rendition.expense_total)) else
                            "Partially Reimbursed")
        rendition.save()
    audit(prop, "pms_petty_reversed", row, reason=reason,
          details={"reversal_journal": reversal.name})
    return {"name": row.name, "status": row.status, "journal": reversal.name,
        "balance": _money(operational_balance(prop))}


def snapshot(property_name):
    prop = require(property_name)
    require_pms(prop)
    visible = (prop.petty_cash_responsible == frappe.session.user or
               bool(set(frappe.get_roles()).intersection(("HS Administrator", "HS Manager",
                   "HS Accountant", "HS Auditor", "HS Cashier"))) or
               frappe.session.user == "Administrator")
    if not visible:
        frappe.throw(_("No tiene acceso a Caja Chica"), frappe.PermissionError)
    active = all(prop.get(field) for field in CONFIG)
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "account_currency": prop.currency,
        "active": 1, "is_group": 0},
        fields=["name", "account_code", "account_name", "root_type"],
        order_by="account_code asc")
    categories = frappe.get_all("HS Expense Category", filters={"property": prop.name,
        "active": 1}, fields=["name", "label", "account", "max_amount"],
        order_by="label asc")
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name,
        "currency": prop.currency, "is_cash": 1},
        fields=["name", "mode_of_payment", "currency"])
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
        "cashier": frappe.session.user, "status": "Open"},
        fields=["name", "opened_at"])
    expenses = frappe.get_all("HS Petty Cash Expense", filters={"property": prop.name,
        "pms_journal": ["is", "set"]},
        fields=["name", "category", "category_label", "responsible", "beneficiary",
            "concept", "receipt_reference", "amount", "business_date",
            "rendition", "status", "pms_journal"],
        order_by="creation desc", limit_page_length=200)
    renditions = frappe.get_all("HS Petty Cash Rendition", filters={"property": prop.name},
        fields=["name", "responsible", "expense_total", "expected_cash",
            "counted_cash", "variance", "explanation", "status", "submitted_by",
            "reviewed_by", "review_note", "approved_business_date",
            "pms_variance_journal"],
        order_by="creation desc", limit_page_length=100)
    handovers = frappe.get_all("HS Petty Cash Handover", filters={"property": prop.name},
        fields=["name", "outgoing", "incoming", "expected_cash", "counted_cash",
            "status", "outgoing_accepted", "incoming_accepted"],
        order_by="creation desc", limit_page_length=30)
    funds = frappe.get_all("HS Treasury Movement", filters={"property": prop.name,
        "kind": ["in", ["Initial Fund", "Replenishment"]],
        "pms_journal": ["is", "set"]},
        fields=["name", "kind", "rendition", "amount", "reference",
            "status", "business_date", "shift"],
        order_by="creation desc", limit_page_length=100)
    pending = sum((Decimal(str(row.amount)) for row in expenses if row.status == "Posted"
                   and not row.rendition), Decimal(0))
    if active:
        ledger = Decimal(gl_balance(prop, prop.petty_cash_account))
        operational = operational_balance(prop)
    else:
        ledger = operational = Decimal(0)
    return {"active": active, "currency": prop.currency,
        "initial_fund_exists": bool(frappe.db.exists("HS Treasury Movement", {
            "property": prop.name, "kind": "Initial Fund",
            "status": ["!=", "Cancelled"]})),
        "responsible": prop.petty_cash_responsible,
        "account": prop.petty_cash_account,
        "overage_account": prop.petty_cash_overage_account,
        "shortage_account": prop.petty_cash_shortage_account,
        "balance": _money(ledger), "expected_cash": _money(operational),
        "pending_expenses": _money(pending),
        "reconciled": ledger == operational,
        "accounts": accounts, "categories": categories,
        "methods": methods, "shifts": shifts,
        "expenses": expenses, "renditions": renditions,
        "funds": funds, "handovers": handovers,
        "users": petty_handover_users(prop),
        "user": frappe.session.user}
