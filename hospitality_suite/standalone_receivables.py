"""Internal PMS receivables and application of customer advances.

These records are operational charges, not fiscal invoices. Every mutation runs
under the property lock supplied by service.command.
"""

from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, inverse_lines
from hospitality_suite.security import document, require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
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
    return sum(((-1 if row.kind in ("Direct Reversed", "Advance Reversed", "Guarantee Reversed",
                                    "Opening Credit Reversed", "Opening Guarantee Reversed") else 1) *
                Decimal(str(row.amount)) for row in current_all("HS PMS Allocation",
        filters={"property": prop.name, "receivable": receivable}, fields=["amount", "kind"])), Decimal(0))


def credited(prop, receivable):
    """Gross amount of posted credit notes against one invoiced receivable."""
    result = frappe.db.sql(
        "SELECT COALESCE(SUM(l.total_amount),0) FROM `tabHS PMS Fiscal Line` l "
        "JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "WHERE d.property=%s AND d.document_type='Credit Note' AND d.status='Posted' "
        "AND l.receivable=%s", (prop.name, receivable), as_list=True)
    return Decimal(str(result[0][0]))


def outstanding(prop, receivable):
    row = frappe.db.get_value("HS PMS Receivable", receivable,
        ["property", "amount", "currency", "status"], as_dict=True)
    if not row or row.property != prop.name or row.status != "Posted":
        frappe.throw(_("La cuenta por cobrar pertenece a otro establecimiento"), frappe.PermissionError)
    if row.currency != prop.currency:
        return opening_balances(prop, receivable)[0]
    return Decimal(str(row.amount)) - allocated(prop, receivable) - credited(prop, receivable)


def opening_balances(prop, receivable):
    row = frappe.db.get_value("HS PMS Receivable", receivable,
        ["property", "organization", "opening_source_name", "currency", "amount",
         "base_currency", "base_amount", "status"], as_dict=True)
    if (not row or row.property != prop.name or row.organization != prop.organization or
            row.status != "Posted" or not row.opening_source_name or
            row.currency == prop.currency or row.base_currency != prop.currency):
        frappe.throw(_("Seleccione cartera extranjera abierta del establecimiento"))
    if credited(prop, receivable):
        frappe.throw(_("La cartera extranjera requiere una nota en su moneda original"))
    allocations = current_all("HS PMS Allocation", filters={
        "property": prop.name, "receivable": receivable},
        fields=["kind", "amount", "settlement_currency", "settled_amount"])
    if any(item.kind not in ("Direct", "Direct Reversed",
                            "Opening Credit Applied", "Opening Credit Reversed") or
           item.settlement_currency != row.currency or
           Decimal(str(item.settled_amount or 0)) <= 0 for item in allocations):
        frappe.throw(_("La cartera extranjera tiene una aplicación incompatible"))
    paid_original = sum(((-1 if item.kind in ("Direct Reversed",
        "Opening Credit Reversed") else 1) *
        Decimal(str(item.settled_amount)) for item in allocations), Decimal(0))
    paid_base = sum(((-1 if item.kind in ("Direct Reversed",
        "Opening Credit Reversed") else 1) *
        Decimal(str(item.amount)) for item in allocations), Decimal(0))
    remaining = Decimal(str(row.amount)) - paid_original
    base_remaining = Decimal(str(row.base_amount)) - paid_base
    if (remaining < 0 or base_remaining < 0 or
            (remaining == 0) != (base_remaining == 0)):
        frappe.throw(_("Los cobros superan la cartera extranjera"))
    return remaining, base_remaining


def deposit_available(prop, payment, kind):
    if kind not in ("Advance", "Guarantee"):
        frappe.throw(_("Seleccione un depósito de cliente"))
    row = frappe.db.get_value("HS Payment", payment,
        ["property", "kind", "status", "base_amount"], as_dict=True)
    if not row or row.property != prop.name or row.kind != kind or row.status != "Posted":
        frappe.throw(_("Seleccione un depósito vigente del establecimiento"))
    applied_kind = kind + " Applied"
    reversed_kind = kind + " Reversed"
    used = sum(((-1 if item.kind == reversed_kind else 1) * Decimal(str(item.amount))
                for item in current_all("HS PMS Allocation",
        filters={"property": prop.name, "payment": payment,
                 "kind": ["in", [applied_kind, reversed_kind]]},
        fields=["amount", "kind"])), Decimal(0))
    refunds = sum((Decimal(str(item.base_amount)) for item in current_all("HS Payment",
        filters={"property": prop.name, "source_payment": payment,
                 "kind": "Guarantee Refund" if kind == "Guarantee" else "Refund",
                 "status": "Posted"}, fields=["base_amount"])), Decimal(0))
    return Decimal(str(row.base_amount)) - used - refunds


def advance_available(prop, payment):
    return deposit_available(prop, payment, "Advance")


def guarantee_matches(prop, payment, receivable):
    """A guarantee follows its original folio or its booking into a stay folio."""
    if not receivable.folio:
        return False
    folio = frappe.db.get_value("HS Folio", receivable.folio,
        ["property", "company", "customer", "booking", "stay"], as_dict=True)
    if (not folio or folio.property != prop.name or folio.company != prop.company or
            folio.customer != receivable.party):
        return False
    if payment.folio:
        return payment.folio == receivable.folio
    if payment.booking:
        origin = folio.booking or (frappe.db.get_value("HS Stay", folio.stay, "booking")
                                   if folio.stay else None)
        return payment.booking == origin
    return False


def remaining_allocation(prop, allocation):
    original = frappe.db.get_value("HS PMS Allocation", allocation,
        ["property", "kind", "amount"], as_dict=True)
    if not original or original.property != prop.name or original.kind not in (
            "Direct", "Advance Applied", "Guarantee Applied"):
        frappe.throw(_("Seleccione una aplicación original del establecimiento"))
    reversed_amount = sum((Decimal(str(row.amount)) for row in current_all(
        "HS PMS Allocation", filters={"property": prop.name, "reverses": allocation},
        fields=["amount"])), Decimal(0))
    return Decimal(str(original.amount)) - reversed_amount


def create(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"party", "reference", "description", "amount",
                                              "receivable_account", "income_account", "tax_profile"}:
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
    return _create(prop, party=data["party"], reference=reference,
                   description=description, value=value, receivable=receivable,
                   income=income, tax_profile=data.get("tax_profile"))


def _create(prop, *, party, reference, description, value, receivable, income,
            folio=None, source_charge=None, booking=None, experience_order=None,
            tax_profile=None, source_service=None):
    from hospitality_suite.standalone_tax import tax_for_amount
    from hospitality_suite.standalone_credit import due_date

    tax = tax_for_amount(prop, tax_profile, value)
    lines = [{"account": receivable.name, "debit": tax["total"], "credit": "0",
              "party": party},
             {"account": income.name, "debit": "0", "credit": tax["net"]}]
    if Decimal(tax["tax"]) > 0:
        lines.append({"account": tax["liability_account"], "debit": "0",
                      "credit": tax["tax"]})
    journal = post(prop, source_doctype="HS PMS Receivable", source_name=reference,
                   purpose="Receivable", memo=description, lines=lines)
    doc = insert("HS PMS Receivable", prop, organization=prop.organization,
                 party=party, reference=reference, description=description,
                 business_date=prop.business_date, due_date=due_date(prop, party),
                 currency=prop.currency, amount=tax["total"],
                 net_amount=tax["net"], tax_amount=tax["tax"],
                 tax_profile=tax["profile"], tax_rate=tax["rate"],
                 tax_treatment=tax["treatment"], price_includes_tax=int(tax["included_in_price"]),
                 tax_account=tax["liability_account"],
                 receivable_account=receivable.name, income_account=income.name,
                 folio=folio, source_charge=source_charge, source_service=source_service,
                 booking=booking,
                 experience_order=experience_order,
                 journal=journal.name, status="Posted")
    audit(prop, "pms_receivable_created", doc, details={"journal": journal.name,
                                                       "amount": tax["total"], "tax": tax["tax"]})
    return {"receivable": doc.name, "journal": journal.name,
            "amount": tax["total"], "net_amount": tax["net"],
            "tax_amount": tax["tax"], "currency": prop.currency}


def _pending_groups(prop, folio_name, *, include_scheduled=False):
    charges = current_all("HS Charge", filters={"property": prop.name,
        "folio": folio_name, "status": ["in", ["Pending", "Scheduled"]] if include_scheduled else "Pending"}, fields=["*"],
        order_by="creation asc,name asc")
    groups = {row.name: [row] for row in charges if not row.applies_to_charge}
    for row in charges:
        if row.applies_to_charge:
            if row.applies_to_charge not in groups:
                frappe.throw(_("Un ajuste de la cuenta de estancia no conserva su cargo pendiente de origen"))
            groups[row.applies_to_charge].append(row)
    return groups


def pending_total(prop, folio_name):
    """Estimated gross of pending charges using their current tax profiles."""
    from hospitality_suite.standalone_tax import tax_for_amount

    gross = Decimal(0)
    for group in _pending_groups(prop, folio_name).values():
        price = sum((Decimal(str(row.amount)) for row in group), Decimal(0))
        if price < 0:
            frappe.throw(_("Los ajustes superan el cargo original"))
        if not price:
            continue
        product = frappe.db.get_value("HS Product", group[0].item,
            ["property", "organization", "tax_profile"], as_dict=True)
        if not product or (product.property, product.organization) != (prop.name, prop.organization):
            frappe.throw(_("El cargo pendiente no conserva su producto PMS"))
        gross += Decimal(tax_for_amount(prop, product.tax_profile, price)["total"])
    return gross


def folio_quote(prop, data):
    """Quote only due, unposted folio charges; the acceptance binds all sources."""
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"folio", "receivable_account"}:
        frappe.throw(_("Revise los datos de la cuenta de estancia"))
    folio = document("HS Folio", data.get("folio"), "finance")
    if folio.property != prop.name or folio.company != prop.company or folio.status != "Open":
        frappe.throw(_("Seleccione una cuenta de estancia abierta del establecimiento"))
    if folio.currency != prop.currency:
        frappe.throw(_("La cuenta de estancia debe usar la moneda base del establecimiento"))
    _customer(prop, folio.customer)
    receivable = account(prop, data.get("receivable_account"))
    if (receivable.root_type != "Asset" or receivable.account_type != "Receivable" or
            receivable.is_cash or receivable.is_bank or receivable.account_currency != prop.currency):
        frappe.throw(_("Seleccione una cuenta por cobrar activa en moneda base"))
    groups = _pending_groups(prop, folio.name, include_scheduled=True)
    lines = []
    for source, group in groups.items():
        primary = group[0]
        if any(row.company != prop.company or row.currency != folio.currency or
               row.pms_receivable or row.sales_invoice for row in group):
            frappe.throw(_("Un cargo ya contabilizado no puede facturarse de nuevo"))
        total = sum((Decimal(str(row.amount)) for row in group), Decimal(0))
        if total < 0:
            frappe.throw(_("Los ajustes superan el cargo original"))
        if total == 0:
            continue
        product = frappe.db.get_value("HS Product", primary.item,
            ["name", "property", "organization", "active", "income_account", "tax_profile",
             "product_name", "modified"],
            as_dict=True)
        if (not product or product.property != prop.name or
                product.organization != prop.organization or not product.active or
                not product.income_account):
            frappe.throw(_("Configure un producto PMS activo con cuenta de ingresos para cada cargo"))
        income = account(prop, product.income_account)
        if income.root_type != "Income" or income.account_currency != prop.currency:
            frappe.throw(_("La cuenta de ingresos del producto debe usar la moneda base"))
        from hospitality_suite.standalone_tax import tax_for_amount
        tax = tax_for_amount(prop, product.tax_profile, total)
        lines.append({"source_charge": source, "charge_names": [row.name for row in group],
                      "item": primary.item, "description": primary.description or product.product_name,
                      "amount": tax["total"], "price": tax["price"],
                      "net_amount": tax["net"], "tax_amount": tax["tax"],
                      "tax_profile": tax["profile"], "tax_treatment": tax["treatment"],
                      "tax_rate": tax["rate"], "tax_account": tax["liability_account"],
                      "income_account": income.name,
                      "product_modified": str(product.modified),
                      "tax_profile_modified": tax.get("profile_modified"),
                      "charge_modified": [str(row.modified) for row in group]})
    signature = {"property": prop.name, "folio": folio.name,
                 "folio_modified": str(folio.modified), "party": folio.customer,
                 "receivable_account": receivable.name, "lines": lines}
    return {"folio": folio.name, "currency": prop.currency,
            "total": _money(sum((Decimal(row["amount"]) for row in lines), Decimal(0))),
            "lines": lines, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def bill_folio(prop, data):
    """Post each charge group once, preserving its product income account."""
    if not isinstance(data, dict) or set(data) - {"folio", "receivable_account", "acceptance"}:
        frappe.throw(_("Revise la contabilización de la cuenta de estancia"))
    quote = folio_quote(prop, {"folio": data.get("folio"),
                               "receivable_account": data.get("receivable_account")})
    if not quote["lines"]:
        frappe.throw(_("La cuenta de estancia no tiene cargos pendientes con importe positivo"))
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("Los cargos o las cuentas contables cambiaron; revise nuevamente la cuenta de estancia"))
    folio = locked_doc("HS Folio", quote["folio"])
    receivable = account(prop, data["receivable_account"])
    from hospitality_suite.periodic import settle_before_billing
    settle_before_billing(prop, folio.name)
    posted = []
    for line in quote["lines"]:
        income = account(prop, line["income_account"])
        reference = f"{folio.name}-{line['source_charge']}-{uuid4().hex[:8]}"
        result = _create(prop, party=folio.customer, reference=reference,
            description=line["description"], value=Decimal(line["price"]),
            receivable=receivable, income=income, folio=folio.name,
            source_charge=line["source_charge"], tax_profile=line["tax_profile"])
        for name in line["charge_names"]:
            charge = locked_doc("HS Charge", name)
            if charge.status != "Pending" or charge.pms_receivable:
                frappe.throw(_("El cargo cambió durante la contabilización"))
            charge.status = "Posted"
            charge.pms_receivable = result["receivable"]
            charge.save()
        posted.append({**result, "source_charge": line["source_charge"]})
    audit(prop, "pms_folio_billed", folio,
          details={"receivables": [row["receivable"] for row in posted],
                   "total": quote["total"]})
    return {"folio": folio.name, "total": quote["total"],
            "currency": quote["currency"], "receivables": posted}


def _apply_deposit(prop, data, kind):
    require_pms(prop)
    require(prop.name, "approve" if kind == "Guarantee" else "finance")
    key = "guarantee" if kind == "Guarantee" else "advance"
    if not isinstance(data, dict) or set(data) - {"receivable", key, "amount", "reason"}:
        frappe.throw(_("Revise la aplicación del depósito"))
    receivable = locked_doc("HS PMS Receivable", data.get("receivable"))
    deposit = locked_doc("HS Payment", data.get(key))
    if (receivable.property != prop.name or receivable.status != "Posted" or
            deposit.property != prop.name or deposit.pms_party != receivable.party or
            (kind == "Guarantee" and not guarantee_matches(prop, deposit, receivable))):
        frappe.throw(_("El depósito y la cuenta por cobrar deben pertenecer al mismo cliente y a la misma cuenta de estancia"))
    if deposit.kind != kind or deposit.status != "Posted":
        frappe.throw(_("Seleccione un depósito vigente"))
    value = _amount(data.get("amount"))
    if value > outstanding(prop, receivable.name) or value > deposit_available(prop, deposit.name, kind):
        frappe.throw(_("La aplicación supera el saldo de la cuenta o del depósito"))
    reason = _text(data.get("reason"), "el motivo", 500)
    liability = account(prop, deposit.pms_counter_account)
    ar = account(prop, receivable.receivable_account)
    if liability.root_type != "Liability" or ar.root_type != "Asset":
        frappe.throw(_("Las cuentas originales ya no son válidas"))
    journal = post(prop, source_doctype="HS PMS Allocation",
                   source_name=uuid4().hex, purpose=kind + " Applied",
                   memo=reason, lines=[
                       {"account": liability.name, "debit": str(value), "credit": "0",
                        "party": deposit.pms_party},
                       {"account": ar.name, "debit": "0", "credit": str(value),
                        "party": deposit.pms_party}])
    row = insert("HS PMS Allocation", prop, organization=prop.organization,
                 receivable=receivable.name, payment=deposit.name, kind=kind + " Applied",
                 business_date=prop.business_date, currency=prop.currency,
                 amount=str(value), journal=journal.name)
    audit(prop, "pms_deposit_applied", row, reason=reason,
          details={"journal": journal.name, "remaining": _money(outstanding(prop, receivable.name))})
    return {"allocation": row.name, "journal": journal.name,
            "outstanding": _money(outstanding(prop, receivable.name)),
            key + "_available": _money(deposit_available(prop, deposit.name, kind))}


def apply_advance(prop, data):
    return _apply_deposit(prop, data, "Advance")


def apply_guarantee(prop, data):
    return _apply_deposit(prop, data, "Guarantee")


def _unapply_deposit(prop, data, kind):
    """Return an applied deposit to its liability without changing prior entries."""
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"allocation", "amount", "reason"}:
        frappe.throw(_("Revise la reversión del depósito"))
    original = locked_doc("HS PMS Allocation", data.get("allocation"))
    if original.property != prop.name or original.kind != kind + " Applied":
        frappe.throw(_("Seleccione una aplicación del depósito del establecimiento"))
    value = _amount(data.get("amount"))
    if value > remaining_allocation(prop, original.name):
        frappe.throw(_("La reversión supera la aplicación pendiente"))
    reason = _text(data.get("reason"), "el motivo", 500)
    receivable = locked_doc("HS PMS Receivable", original.receivable)
    deposit = locked_doc("HS Payment", original.payment)
    if (receivable.property != prop.name or receivable.status != "Posted" or
            deposit.property != prop.name or deposit.kind != kind or
            deposit.status != "Posted" or deposit.pms_party != receivable.party or
            (kind == "Guarantee" and not guarantee_matches(prop, deposit, receivable))):
        frappe.throw(_("El depósito o la cuenta por cobrar cambió"))
    ar = account(prop, receivable.receivable_account)
    liability = account(prop, deposit.pms_counter_account)
    journal = post(prop, source_doctype="HS PMS Allocation", source_name=uuid4().hex,
                   purpose=kind + " Reversed", memo=reason, lines=[
                       {"account": ar.name, "debit": str(value), "credit": "0",
                        "party": receivable.party},
                       {"account": liability.name, "debit": "0", "credit": str(value),
                        "party": receivable.party}])
    row = insert("HS PMS Allocation", prop, organization=prop.organization,
                 receivable=receivable.name, payment=deposit.name,
                 kind=kind + " Reversed", reverses=original.name,
                 business_date=prop.business_date, currency=prop.currency,
                 amount=str(value), journal=journal.name)
    audit(prop, "pms_deposit_unapplied", row, reason=reason,
          details={"journal": journal.name, "original_allocation": original.name})
    return {"allocation": row.name, "journal": journal.name,
            "outstanding": _money(outstanding(prop, receivable.name)),
            ("guarantee" if kind == "Guarantee" else "advance") + "_available":
                _money(deposit_available(prop, deposit.name, kind))}


def unapply_advance(prop, data):
    return _unapply_deposit(prop, data, "Advance")


def unapply_guarantee(prop, data):
    return _unapply_deposit(prop, data, "Guarantee")


def cancel(prop, data, *, allow_day_pass=False):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"receivable", "reason"}:
        frappe.throw(_("Revise la cancelación del cargo"))
    doc = locked_doc("HS PMS Receivable", data.get("receivable"))
    if doc.property != prop.name or doc.status != "Posted":
        frappe.throw(_("Seleccione un cargo vigente del establecimiento"))
    if doc.opening_source_name:
        frappe.throw(_("La cartera migrada se corrige con su flujo de crédito y conciliación"))
    if not allow_day_pass and frappe.db.exists("HS Day Pass", {
            "property": prop.name, "pms_receivable": doc.name, "status": "Issued"}):
        frappe.throw(_("Cancele el Day Pass desde su operación para conservar el estado de acceso"))
    if allocated(prop, doc.name) != 0:
        frappe.throw(_("La cuenta tiene cobros aplicados; primero se requiere conciliación y devolución"))
    from hospitality_suite.standalone_fiscal import _already_invoiced
    if _already_invoiced(prop, doc.name):
        frappe.throw(_("El cargo ya está facturado; registre una nota de crédito"))
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
    if doc.folio:
        for row in current_all("HS Charge", filters={"property": prop.name,
                                                       "pms_receivable": doc.name}, fields=["name"]):
            charge = locked_doc("HS Charge", row.name)
            if charge.status != "Posted":
                frappe.throw(_("El cargo de la cuenta de estancia no conserva su estado contable"))
            charge.status = "Pending"
            charge.pms_receivable = None
            charge.save()
    if doc.experience_order:
        order = locked_doc("HS Experience Order", doc.experience_order)
        if (order.property != prop.name or order.status != "Delivered" or
                order.pms_receivable != doc.name):
            frappe.throw(_("La orden de experiencia directa no coincide con el cargo"))
        order.status = "Cancelled"
        order.cancel_reason = reason
        order.save()
    audit(prop, "pms_receivable_cancelled", doc, reason=reason,
          details={"reversal_journal": reversal.name})
    return {"receivable": doc.name, "status": doc.status, "reversal_journal": reversal.name}


def list_receivables(prop, open_only=False, folio=None):
    open_filter = " AND (r.amount-COALESCE(a.original_allocated,0)-COALESCE(c.credited,0))>0" if open_only else ""
    folio_filter = " AND r.folio=%s" if folio else ""
    rows = frappe.db.sql(
        "SELECT r.name, r.party, r.reference, r.description, r.amount, r.currency, "
        "r.base_currency, r.base_amount, "
        "r.business_date, r.due_date, r.receivable_account, r.folio, "
        "f.stay AS folio_stay, "
        "r.opening_source_name, h.name AS historical_document, "
        "COALESCE(r.booking, f.booking, s.booking) AS booking, r.source_charge, "
        "r.amount-COALESCE(a.original_allocated,0)-COALESCE(c.credited,0) AS outstanding, "
        "COALESCE(NULLIF(r.base_amount,0),r.amount)-COALESCE(a.base_allocated,0)-"
        "COALESCE(c.credited,0) AS base_outstanding "
        "FROM `tabHS PMS Receivable` r LEFT JOIN `tabHS Folio` f ON f.name=r.folio "
        "LEFT JOIN `tabHS Stay` s ON s.name=f.stay "
        "LEFT JOIN `tabHS Historical Fiscal Document` h ON "
        "h.property=r.property AND h.source_site=r.opening_source_site "
        "AND h.source_doctype='Sales Invoice' AND h.source_name=r.opening_source_name "
        "LEFT JOIN ("
        "SELECT receivable, SUM(CASE WHEN kind IN ('Direct Reversed','Advance Reversed','Guarantee Reversed','Opening Credit Reversed','Opening Guarantee Reversed') "
        "THEN -amount ELSE amount END) AS base_allocated, "
        "SUM(CASE WHEN kind IN ('Direct Reversed','Advance Reversed','Guarantee Reversed','Opening Credit Reversed','Opening Guarantee Reversed') "
        "THEN -COALESCE(NULLIF(settled_amount,0),amount) "
        "ELSE COALESCE(NULLIF(settled_amount,0),amount) END) AS original_allocated "
        "FROM `tabHS PMS Allocation` "
        "WHERE property=%s GROUP BY receivable) a ON a.receivable=r.name "
        "LEFT JOIN (SELECT l.receivable, SUM(l.total_amount) AS credited "
        "FROM `tabHS PMS Fiscal Line` l JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "WHERE d.property=%s AND d.document_type='Credit Note' AND d.status='Posted' "
        "GROUP BY l.receivable) c ON c.receivable=r.name "
        "WHERE r.property=%s AND r.status='Posted'" + open_filter + folio_filter +
        " ORDER BY r.creation DESC LIMIT 200",
        (prop.name, prop.name, prop.name, *((folio,) if folio else ())), as_dict=True)
    return [{**row, "outstanding": _money(row.outstanding),
             "base_outstanding": _money(row.base_outstanding)} for row in rows]


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    rows = list_receivables(prop)
    deposits = frappe.db.sql(
        "SELECT p.name, p.kind, p.folio, p.booking, p.pms_party, p.amount, p.currency, p.base_amount, p.reference, "
        "p.pms_counter_account, p.base_amount-COALESCE(a.applied,0)-COALESCE(f.refunded,0) AS available "
        "FROM `tabHS Payment` p LEFT JOIN ("
        "SELECT payment, SUM(CASE WHEN kind IN ('Advance Reversed','Guarantee Reversed') THEN -amount ELSE amount END) AS applied "
        "FROM `tabHS PMS Allocation` WHERE property=%s "
        "AND kind IN ('Advance Applied','Advance Reversed','Guarantee Applied','Guarantee Reversed') "
        "GROUP BY payment) a ON a.payment=p.name "
        "LEFT JOIN (SELECT source_payment, SUM(base_amount) AS refunded FROM `tabHS Payment` "
        "WHERE property=%s AND kind IN ('Refund','Guarantee Refund') AND status='Posted' "
        "GROUP BY source_payment) f "
        "ON f.source_payment=p.name "
        "WHERE p.property=%s AND p.kind IN ('Advance','Guarantee') AND p.status='Posted' "
        "AND p.pms_journal IS NOT NULL ORDER BY p.creation DESC LIMIT 200",
        (prop.name, prop.name, prop.name), as_dict=True)
    applied_deposits = frappe.db.sql(
        "SELECT a.name, a.kind, a.receivable, a.payment, a.amount-COALESCE(r.reversed_amount,0) AS remaining "
        "FROM `tabHS PMS Allocation` a LEFT JOIN ("
        "SELECT reverses, SUM(amount) AS reversed_amount FROM `tabHS PMS Allocation` "
        "WHERE property=%s AND kind IN ('Advance Reversed','Guarantee Reversed') "
        "GROUP BY reverses) r ON r.reverses=a.name "
        "WHERE a.property=%s AND a.kind IN ('Advance Applied','Guarantee Applied') "
        "AND a.amount>COALESCE(r.reversed_amount,0) ORDER BY a.creation DESC LIMIT 200",
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
    from hospitality_suite.standalone_opening_credits import snapshot as opening_snapshot
    from hospitality_suite.standalone_opening_guarantees import snapshot as guarantee_snapshot
    return {"currency": prop.currency, "accounts": accounts, "customers": customers,
            "tax_profiles": frappe.get_all("HS PMS Tax Profile", filters={"property": prop.name,
                "active": 1}, fields=["name", "label", "treatment", "rate", "included_in_price"],
                order_by="label asc"),
            "cancelled": cancelled,
            "receivables": rows,
            "advances": [{**row, "available": _money(row.available)} for row in deposits if row.kind == "Advance"],
            "guarantees": [{**row, "available": _money(row.available)} for row in deposits if row.kind == "Guarantee"],
            "applied_advances": [{**row, "remaining": _money(row.remaining)} for row in applied_deposits
                                 if row.kind == "Advance Applied"],
            "applied_guarantees": [{**row, "remaining": _money(row.remaining)} for row in applied_deposits
                                   if row.kind == "Guarantee Applied"],
            "opening_credits": opening_snapshot(prop),
            "opening_guarantees": guarantee_snapshot(prop),
            "opening_guarantee_applications": frappe.db.sql(
                "SELECT a.name,a.opening_guarantee,a.receivable,a.amount-"
                "COALESCE(r.reversed_amount,0) AS remaining "
                "FROM `tabHS PMS Allocation` a LEFT JOIN ("
                "SELECT reverses,SUM(amount) AS reversed_amount "
                "FROM `tabHS PMS Allocation` WHERE property=%s "
                "AND kind='Opening Guarantee Reversed' GROUP BY reverses) r "
                "ON r.reverses=a.name WHERE a.property=%s "
                "AND a.kind='Opening Guarantee Applied' "
                "AND a.amount>COALESCE(r.reversed_amount,0) "
                "ORDER BY a.creation DESC LIMIT 200",
                (prop.name, prop.name), as_dict=True),
            "refund_methods": frappe.get_all("HS Payment Method",
                filters={"property": prop.name},
                fields=["name", "mode_of_payment", "currency", "is_cash"],
                order_by="mode_of_payment asc"),
            "refund_shifts": frappe.get_all("HS Shift", filters={"property": prop.name,
                "cashier": frappe.session.user, "status": "Open"},
                fields=["name", "opened_at"], order_by="opened_at desc")}
