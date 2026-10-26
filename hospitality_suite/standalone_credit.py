"""Property-scoped credit terms and exposure for the standalone PMS ledger."""

from datetime import timedelta
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import property_document, require
from hospitality_suite.service import assert_version, audit, current_all
from hospitality_suite.standalone_accounting import require_pms
from hospitality_suite.standalone_receivables import outstanding, pending_total


def _money(value):
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def _party(prop, name):
    party = frappe.db.get_value("HS Party", name,
        ["name", "property", "organization", "party_type", "active", "party_name",
         "credit_authorized", "credit_limit", "credit_days", "credit_valid_until",
         "credit_reason", "modified"], as_dict=True) if name else None
    if (not party or party.property != prop.name or party.organization != prop.organization or
            party.party_type not in ("Customer", "Both")):
        frappe.throw(_("Seleccione un pagador PMS del establecimiento"), frappe.PermissionError)
    return party


def validate_party_terms(doc):
    try:
        limit = amount(doc.credit_limit or 0)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if isinstance(doc.credit_days, bool):
        frappe.throw(_("El plazo de crédito debe ser un número entero de 0 a 365 días"))
    raw_days = 30 if doc.credit_days is None else doc.credit_days
    try:
        days = int(raw_days)
        exact_days = Decimal(str(raw_days)) == days
    except (TypeError, ValueError, ArithmeticError):
        exact_days = False
        days = -1
    if days < 0 or days > 365 or not exact_days:
        frappe.throw(_("El plazo de crédito debe ser un número entero de 0 a 365 días"))
    if doc.credit_authorized and (doc.party_type not in ("Customer", "Both") or limit <= 0):
        frappe.throw(_("Autorice crédito solo a un pagador con límite positivo"))
    if doc.credit_valid_until:
        try:
            getdate(doc.credit_valid_until)
        except (TypeError, ValueError):
            frappe.throw(_("Revise la fecha de vigencia del crédito"))
    old = doc.get_doc_before_save() if not doc.is_new() else None
    changed = (bool(doc.credit_authorized) or limit != 0 or bool(doc.credit_valid_until) or
        bool(doc.credit_reason) or days != 30) if not old else any(
        (bool(old.get(field)) != bool(doc.get(field)) if field == "credit_authorized" else
         Decimal(str(old.get(field) or 0)) != Decimal(str(doc.get(field) or 0)) if field == "credit_limit" else
         (30 if old.get(field) is None else int(old.get(field))) != days if field == "credit_days" else
         str(old.get(field) or "") != str(doc.get(field) or ""))
        for field in ("credit_authorized", "credit_limit", "credit_days",
                      "credit_valid_until", "credit_reason"))
    if changed and not getattr(frappe.local, "hs_credit_terms_update", False):
        frappe.throw(_("Modifique las condiciones de crédito mediante su autorización PMS"), frappe.PermissionError)


def update_terms(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {
            "party", "modified", "credit_authorized", "credit_limit",
            "credit_days", "credit_valid_until", "reason"}:
        frappe.throw(_("Revise las condiciones de crédito"))
    party = property_document(prop, "HS Party", data["party"], "approve")
    assert_version(party, data["modified"])
    if party.party_type not in ("Customer", "Both") or not party.active:
        frappe.throw(_("Seleccione un pagador activo del establecimiento"))
    authorization = data["credit_authorized"]
    if authorization not in (True, False, 0, 1):
        frappe.throw(_("Indique si el crédito está autorizado"))
    try:
        limit = amount(data["credit_limit"])
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    days = data["credit_days"]
    if isinstance(days, bool):
        frappe.throw(_("Indique un plazo de 0 a 365 días"))
    try:
        days = int(days)
    except (TypeError, ValueError):
        frappe.throw(_("Indique un plazo de 0 a 365 días"))
    if days < 0 or days > 365 or str(data["credit_days"]) != str(days):
        frappe.throw(_("Indique un plazo de 0 a 365 días"))
    valid_until = data["credit_valid_until"] or None
    if valid_until:
        try:
            valid_until = getdate(valid_until)
        except (TypeError, ValueError):
            frappe.throw(_("Revise la fecha de vigencia del crédito"))
        if bool(authorization) and valid_until < getdate(nowdate()):
            frappe.throw(_("No autorice crédito con vigencia vencida"))
    reason = data["reason"]
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        frappe.throw(_("Indique un motivo de 8 a 500 caracteres"))
    if authorization and limit <= 0:
        frappe.throw(_("El límite autorizado debe ser mayor que cero"))
    before = {field: party.get(field) for field in ("credit_authorized", "credit_limit",
        "credit_days", "credit_valid_until", "credit_reason")}
    party.update({"credit_authorized": int(bool(authorization)), "credit_limit": limit,
                  "credit_days": days, "credit_valid_until": valid_until,
                  "credit_reason": reason.strip()})
    previous = getattr(frappe.local, "hs_credit_terms_update", False)
    frappe.local.hs_credit_terms_update = True
    try:
        party.save()
    finally:
        frappe.local.hs_credit_terms_update = previous
    audit(prop, "pms_credit_terms_changed", party, reason.strip(), before=before)
    return {"party": party.name, "modified": str(party.modified)}


def update_policy(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {"allow_credit", "modified", "reason"}:
        frappe.throw(_("Revise la política de crédito"))
    assert_version(prop, data["modified"])
    if data["allow_credit"] not in (True, False, 0, 1):
        frappe.throw(_("Indique si se permite crédito en el establecimiento"))
    reason = data["reason"]
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        frappe.throw(_("Indique un motivo de 8 a 500 caracteres"))
    before = {"allow_credit": bool(prop.allow_credit)}
    prop.allow_credit = int(bool(data["allow_credit"]))
    prop.save()
    audit(prop, "pms_credit_policy_changed", prop, reason.strip(), before=before)
    return {"property": prop.name, "allow_credit": bool(prop.allow_credit),
            "modified": str(prop.modified)}


def due_date(prop, party_name):
    party = _party(prop, party_name)
    issued = getdate(prop.business_date)
    active = (prop.allow_credit and party.active and party.credit_authorized and
              (not party.credit_valid_until or getdate(party.credit_valid_until) >= getdate(nowdate())))
    return issued + timedelta(days=int(party.credit_days or 0)) if active else issued


def snapshot(prop, party_name):
    require_pms(prop)
    party = _party(prop, party_name)
    today = getdate(nowdate())
    receivable = overdue = Decimal(0)
    oldest_due = None
    for row in current_all("HS PMS Receivable", filters={"property": prop.name,
            "party": party.name, "status": "Posted"},
            fields=["name", "due_date", "business_date"]):
        due = outstanding(prop, row.name)
        if due <= 0:
            continue
        receivable += due
        deadline = getdate(row.due_date or row.business_date)
        if deadline < today:
            overdue += due
            oldest_due = min(oldest_due, deadline) if oldest_due else deadline
    unbilled = sum((pending_total(prop, row.name) for row in
        current_all("HS Folio", filters={"property": prop.name,
            "customer": party.name, "status": "Open"}, fields=["name"])), Decimal(0))
    exposure = receivable + unbilled
    limit = Decimal(str(party.credit_limit or 0))
    active = bool(prop.allow_credit and party.active and party.credit_authorized and
                  (not party.credit_valid_until or getdate(party.credit_valid_until) >= today))
    status = ("Not Authorized" if not active else "Overdue" if overdue > 0 else
              "Over Limit" if exposure > limit else "Available")
    return {"party": party.name, "party_name": party.party_name, "currency": prop.currency,
            "status": status, "property_credit_enabled": bool(prop.allow_credit),
            "active": bool(party.active),
            "credit_authorized": bool(party.credit_authorized),
            "limit": _money(limit), "receivable": _money(receivable),
            "unbilled": _money(unbilled), "overdue": _money(overdue),
            "oldest_due": str(oldest_due) if oldest_due else None,
            "exposure": _money(exposure), "available": _money(max(Decimal(0), limit - exposure)),
            "credit_days": int(party.credit_days or 0),
            "credit_valid_until": str(party.credit_valid_until or "") or None,
            "credit_reason": party.credit_reason or "", "modified": str(party.modified)}


def enforce(prop, party_name, override_reason=None):
    result = snapshot(prop, party_name)
    if result["status"] == "Available":
        return result
    if result["status"] in ("Overdue", "Over Limit") and override_reason:
        require(prop.name, "approve")
        if not isinstance(override_reason, str) or not 8 <= len(override_reason.strip()) <= 500:
            frappe.throw(_("Explique la excepción de crédito en 8 a 500 caracteres"))
        party = property_document(prop, "HS Party", party_name, "approve")
        audit(prop, "pms_credit_override", party, override_reason.strip(), details={
            "status": result["status"], "limit": result["limit"],
            "exposure": result["exposure"], "overdue": result["overdue"]})
        return {**result, "override_reason": override_reason.strip()}
    messages = {"Not Authorized": _("El pagador no tiene crédito PMS autorizado y vigente"),
                "Overdue": _("El pagador tiene saldos PMS vencidos"),
                "Over Limit": _("La exposición PMS supera el límite de crédito autorizado")}
    frappe.throw(messages[result["status"]])


def status(property_name, party_name):
    prop = require(property_name, "finance")
    return snapshot(prop, party_name)


def overview(property_name, offset=0, page_length=50):
    prop = require(property_name, "finance")
    require_pms(prop)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Paginación inválida"))
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(_("Paginación inválida"))
    filters = {"property": prop.name, "organization": prop.organization,
               "party_type": ["in", ["Customer", "Both"]]}
    rows = frappe.get_all("HS Party", filters=filters, fields=["name"],
        order_by="party_name asc", start=offset, limit_page_length=page_length)
    return {"property": prop.name, "currency": prop.currency,
            "property_credit_enabled": bool(prop.allow_credit), "property_modified": str(prop.modified),
            "total": frappe.db.count("HS Party", filters), "offset": offset,
            "page_length": page_length, "rows": [snapshot(prop, row.name) for row in rows]}
