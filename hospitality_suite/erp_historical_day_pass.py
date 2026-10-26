"""Finish a PMS Day Pass in ERPNext without treating its opening balance as a sale."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import nowdate

from hospitality_suite import accounting
from hospitality_suite.pricing import money
from hospitality_suite.security import require
from hospitality_suite.service import assert_version, audit, canonical, insert, locked_doc


def _amount(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(_("Importe de devolución inválido"))
    if not result.is_finite() or result < 0 or result != money(result):
        frappe.throw(_("Importe de devolución inválido"))
    return result


def _remaining(proof):
    sale = proof["accepted_sale"]
    credits = proof["source_fiscal"]["credits"]
    net = _amount(sale["net_amount"]) - sum(
        (_amount(row["net_amount"]) for row in credits), Decimal(0))
    tax = _amount(sale["tax_amount"]) - sum(
        (_amount(row["tax_amount"]) for row in credits), Decimal(0))
    total = _amount(sale["total_amount"]) - sum(
        (_amount(row["total_amount"]) for row in credits), Decimal(0))
    if net < 0 or tax < 0 or total <= 0 or net + tax != total:
        frappe.throw(_("La venta histórica no conserva un saldo acreditable"))
    return net, tax, total


def _verify_opening_settlements(prop, doc, opening, original, outstanding):
    """Do not turn a post-cutover write-off or another credit into cash back."""
    lock = " FOR UPDATE" if getattr(frappe.local, "hs_operation", False) else ""
    rows = frappe.db.sql(
        "SELECT voucher_type, voucher_no, company, account, party, "
        "amount_in_account_currency FROM `tabPayment Ledger Entry` "
        "WHERE against_voucher_type='Sales Invoice' AND against_voucher_no=%s "
        "AND delinked=0" + lock,
        (opening.name,), as_dict=True)
    balance = Decimal(0)
    origin_count = 0
    for row in rows:
        amount = money(row.amount_in_account_currency, currency=prop.currency)
        if (row.company != prop.company or row.account != opening.debit_to or
                row.party != doc.customer):
            frappe.throw(_("Las aplicaciones de la factura de apertura no concilian"))
        if row.voucher_type == "Sales Invoice" and row.voucher_no == opening.name:
            origin_count += 1
            if amount != original:
                frappe.throw(_("El saldo original de apertura cambió"))
        elif row.voucher_type == "Payment Entry" and amount < 0:
            payment = frappe.db.get_value("Payment Entry", row.voucher_no,
                ["company", "hs_property", "docstatus", "payment_type",
                 "party_type", "party", "paid_from", "paid_amount",
                 "difference_amount"], as_dict=True)
            if (not payment or payment.company != prop.company or
                    payment.hs_property != prop.name or payment.docstatus != 1 or
                    payment.payment_type != "Receive" or
                    payment.party_type != "Customer" or
                    payment.party != doc.customer or
                    payment.paid_from != opening.debit_to or
                    Decimal(str(payment.paid_amount)) < -amount or
                    Decimal(str(payment.difference_amount or 0)) != 0 or
                    frappe.db.exists("Payment Entry Deduction", {
                        "parent": row.voucher_no})):
                frappe.throw(_("Un cobro posterior no conserva el efectivo aplicado"))
        else:
            frappe.throw(_("La factura de apertura tiene un ajuste distinto de un cobro"))
        balance += amount
    if origin_count != 1 or money(balance, currency=prop.currency) != outstanding:
        frappe.throw(_("El libro de pagos no concilia con el Day Pass trasladado"))


def _source(prop, data):
    from hospitality_suite.standalone_accounting import provider

    if provider() != "erpnext":
        frappe.throw(_("Esta devolución requiere contabilidad ERPNext"))
    if frappe.db.get_value("Company", prop.company, "default_currency") != prop.currency:
        frappe.throw(_("La moneda base del corte no coincide con la compañía"))
    require(prop.name, "approve")
    doc = locked_doc("HS Day Pass", data["day_pass"])
    assert_version(doc, data["modified"])
    if (doc.property != prop.name or doc.company != prop.company or
            doc.status != "Issued" or not doc.pms_receivable or
            doc.service or doc.sales_invoice or doc.payment or
            doc.erp_return_credit_note or doc.erp_return_refund or
            not doc.erp_opening_snapshot or not doc.erp_opening_sha256 or
            sha256(doc.erp_opening_snapshot.encode()).hexdigest() !=
                doc.erp_opening_sha256):
        frappe.throw(_("Seleccione un Day Pass PMS vigente y conciliado"))
    proof = frappe.parse_json(doc.erp_opening_snapshot)
    if (not isinstance(proof, dict) or proof.get("source") != doc.name or
            proof.get("property") != prop.name or
            proof.get("company") != prop.company or
            proof.get("customer") != doc.customer or
            proof.get("source_receivable") != doc.pms_receivable or
            proof.get("opening_invoice") != doc.erp_opening_invoice or
            proof.get("outstanding") !=
                proof.get("source_financial", {}).get("outstanding_amount")):
        frappe.throw(_("El Day Pass no concilia con su continuación ERPNext"))
    net, tax, total = _remaining(proof)
    target = proof["target_accounts"]
    receivable = target["receivable_account"]
    for name, root, account_type in (
            (receivable, "Asset", "Receivable"),
            (target["income_account"], "Income", None),
            (target.get("tax_account"), "Liability", None)):
        if not name and not (root == "Liability" and not tax):
            frappe.throw(_("Falta una cuenta de la venta histórica"))
        if not name:
            continue
        row = frappe.db.get_value("Account", name,
            ["company", "root_type", "account_type", "account_currency",
             "is_group"], as_dict=True)
        if (not row or row.company != prop.company or row.root_type != root or
                row.is_group or (account_type and row.account_type != account_type) or
                (root == "Asset" and row.account_currency != prop.currency)):
            frappe.throw(_("Las cuentas ERPNext no coinciden con la venta histórica"))
    item = frappe.db.get_value("Item", proof["item_code"],
        ["is_sales_item", "is_stock_item", "disabled"], as_dict=True)
    if not item or not item.is_sales_item or item.is_stock_item or item.disabled:
        frappe.throw(_("El artículo de la venta histórica ya no permite devolución"))
    opening = None
    outstanding = Decimal(0)
    if doc.erp_opening_invoice:
        opening = locked_doc("Sales Invoice", doc.erp_opening_invoice)
        if ((opening.company, opening.hs_property, opening.customer,
             opening.debit_to, opening.currency, opening.docstatus) !=
                (prop.company, prop.name, doc.customer, receivable,
                 prop.currency, 1) or opening.is_return or
                money(opening.grand_total, currency=prop.currency) !=
                    _amount(proof["outstanding"])):
            frappe.throw(_("La factura de apertura del Day Pass no concilia"))
        outstanding = money(opening.outstanding_amount, currency=prop.currency)
        _verify_opening_settlements(prop, doc, opening,
                                    _amount(proof["outstanding"]), outstanding)
    if outstanding < 0 or outstanding > _amount(proof["outstanding"]) or outstanding > total:
        frappe.throw(_("El saldo trasladado del Day Pass no concilia"))
    return doc, proof, opening, net, tax, total, outstanding


def quote(prop, data):
    """Freeze the credit, opening application and only the remaining cash refund."""
    required = {"day_pass", "modified", "method", "shift", "amount",
                "reference", "reason"}
    if not isinstance(data, dict) or set(data) != required:
        frappe.throw(_("Revise la devolución del Day Pass histórico"))
    doc, proof, opening, net, tax, total, outstanding = _source(prop, data)
    refund_base = total - outstanding
    method = None
    shift = None
    amount = (_amount(data["amount"]) if data["amount"] not in (None, "")
              else None)
    rate = Decimal(1)
    reference = data["reference"]
    reason = data["reason"]
    if (not isinstance(reason, str) or not reason.strip() or
            len(reason.strip()) > 500 or not isinstance(reference, str) or
            len(reference.strip()) > 140):
        frappe.throw(_("Indique un motivo y una referencia válidos"))
    reference, reason = reference.strip(), reason.strip()
    if refund_base:
        if not data["method"]:
            frappe.throw(_("Seleccione el medio del reembolso"))
        method = locked_doc("HS Payment Method", data["method"])
        account = frappe.db.get_value("Account", method.account,
            ["company", "account_type", "account_currency", "is_group"],
            as_dict=True)
        if (method.property != prop.name or method.company != prop.company or
                not account or account.company != prop.company or account.is_group or
                account.account_currency != method.currency or
                account.account_type != ("Cash" if method.is_cash else "Bank")):
            frappe.throw(_("El medio de reembolso no corresponde al establecimiento"))
        from hospitality_suite.standalone_currency import enabled
        if not enabled(prop, method.currency):
            frappe.throw(_("La moneda del medio no está habilitada"))
        market = accounting.exchange(method.currency, prop.currency)
        expected_amount = money(refund_base / market, currency=method.currency)
        if amount is None:
            amount = expected_amount
        if amount <= 0 or amount != expected_amount:
            frappe.throw(_("El reembolso debe ser {0} {1} al cambio vigente").format(
                expected_amount, method.currency))
        rate = (refund_base / amount).quantize(Decimal("0.000000001"),
                                               rounding=ROUND_HALF_UP)
        if money(amount * rate, currency=prop.currency) != refund_base:
            frappe.throw(_("El redondeo impide devolver en esta moneda"))
        if method.is_cash:
            from hospitality_suite.cashier import expected

            shift = locked_doc("HS Shift", data["shift"])
            if (shift.property != prop.name or shift.company != prop.company or
                    shift.status != "Open" or shift.cashier != frappe.session.user or
                    shift.currency != method.currency):
                frappe.throw(_("La devolución en efectivo requiere turno propio abierto"),
                             frappe.PermissionError)
            if amount > Decimal(expected(shift).get(method.currency, "0")):
                frappe.throw(_("El turno no tiene efectivo suficiente"))
        elif data["shift"]:
            frappe.throw(_("La devolución bancaria no se asigna a turno"))
        if method.reference_required and not reference:
            frappe.throw(_("Indique la referencia del reembolso"))
    elif amount or data["method"] or data["shift"]:
        frappe.throw(_("El saldo abierto absorbe la nota; no corresponde reembolso"))
    else:
        amount = Decimal(0)
    signature = {"day_pass": doc.name, "modified": str(doc.modified),
        "snapshot_sha256": doc.erp_opening_sha256,
        "opening_invoice": opening.name if opening else None,
        "opening_modified": str(opening.modified) if opening else None,
        "opening_outstanding": str(outstanding),
        "method": method.name if method else None,
        "method_modified": str(method.modified) if method else None,
        "shift": shift.name if shift else None,
        "amount": str(amount), "rate": str(rate),
        "reference": reference, "reason": reason}
    return {"day_pass": doc.name, "modified": str(doc.modified),
        "original_invoice": proof["source_fiscal"].get("invoice", {}).get("document_number")
            if proof["source_fiscal"].get("invoice") else None,
        "currency": prop.currency, "credit_net": str(net),
        "credit_tax": str(tax), "credit_total": str(total),
        "opening_applied": str(outstanding),
        "refund_base": str(refund_base),
        "refund_amount": str(amount),
        "refund_currency": method.currency if method else None,
        "exchange_rate": str(rate),
        "method": method.name if method else None,
        "shift": shift.name if shift else None,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def return_pass(prop, data):
    required = {"day_pass", "modified", "method", "shift", "amount",
                "reference", "reason", "acceptance"}
    if not isinstance(data, dict) or set(data) != required:
        frappe.throw(_("Revise la devolución del Day Pass histórico"))
    accepted = quote(prop, {key: value for key, value in data.items()
                            if key != "acceptance"})
    if data["acceptance"] != accepted["acceptance"]:
        frappe.throw(_("Cambió el saldo o el tipo de cambio; revise la devolución"))
    doc, proof, opening, net, tax, total, outstanding = _source(prop, data)
    credit = frappe.new_doc("Sales Invoice")
    credit.flags.dont_auto_add_taxes = True
    credit.update({"company": prop.company, "customer": doc.customer,
        "posting_date": nowdate(), "due_date": nowdate(),
        "currency": prop.currency, "debit_to": proof["target_accounts"]["receivable_account"],
        "cost_center": prop.cost_center, "is_return": 1, "update_stock": 0,
        "selling_price_list": prop.price_list,
        "price_list_currency": prop.currency, "plc_conversion_rate": 1,
        "remarks": _("Devolución Day Pass PMS {0}. Factura original {1}. {2}").format(
            doc.name, accepted["original_invoice"] or _("sin emitir"),
            accepted["reason"])})
    credit.append("items", {"item_code": proof["item_code"], "qty": -1,
        "rate": float(net), "income_account": proof["target_accounts"]["income_account"],
        "cost_center": prop.cost_center, "warehouse": prop.warehouse,
        "ignore_pricing_rule": 1})
    if tax:
        credit.append("taxes", {"charge_type": "Actual",
            "account_head": proof["target_accounts"]["tax_account"],
            "tax_amount": -float(tax), "description": _("Tributo Day Pass PMS")})
    credit.set_missing_values()
    credit.calculate_taxes_and_totals()
    if money(credit.grand_total, currency=prop.currency) != -total:
        frappe.throw(_("ERPNext cambió el total de la nota histórica"))
    accounting.post_standard(credit, prop)
    if opening and outstanding:
        accounting._reconcile_credit_to_unpaid(prop, opening, credit)
    refund = None
    if Decimal(accepted["refund_base"]):
        method = locked_doc("HS Payment Method", accepted["method"])
        pe = frappe.new_doc("Payment Entry")
        pe.update({"company": prop.company, "payment_type": "Pay",
            "posting_date": nowdate(), "party_type": "Customer",
            "party": doc.customer, "paid_from": method.account,
            "paid_to": proof["target_accounts"]["receivable_account"],
            "paid_amount": float(Decimal(accepted["refund_amount"])),
            "received_amount": float(Decimal(accepted["refund_base"])),
            "source_exchange_rate": float(Decimal(accepted["exchange_rate"])),
            "target_exchange_rate": 1,
            "mode_of_payment": method.mode_of_payment,
            "reference_no": accepted["reference"] or credit.name,
            "reference_date": nowdate(), "cost_center": prop.cost_center,
            "hs_shift": accepted["shift"], "remarks": accepted["reason"]})
        pe.append("references", {"reference_doctype": "Sales Invoice",
            "reference_name": credit.name,
            "allocated_amount": -float(Decimal(accepted["refund_base"]))})
        accounting.post_standard(pe, prop)
        refund = insert("HS Payment", prop, customer=doc.customer,
            shift=accepted["shift"], method=method.name,
            amount=accepted["refund_amount"], currency=method.currency,
            exchange_rate=accepted["exchange_rate"],
            base_amount=accepted["refund_base"], kind="Refund", status="Posted",
            payment_entry=pe.name, sales_invoice=credit.name,
            reference=accepted["reference"], reason=accepted["reason"])
    before = getattr(frappe.local, "hs_erp_historical_day_pass_return", False)
    frappe.local.hs_erp_historical_day_pass_return = True
    try:
        doc.erp_return_credit_note = credit.name
        doc.erp_return_refund = refund.name if refund else None
        doc.status = "Cancelled"
        doc.save()
    finally:
        frappe.local.hs_erp_historical_day_pass_return = before
    audit(prop, "erp_historical_day_pass_returned", doc,
        accepted["reason"], {"credit_note": credit.name,
            "opening_invoice": opening.name if opening else None,
            "opening_applied": str(outstanding),
            "refund": refund.name if refund else None,
            "refund_base": accepted["refund_base"]})
    return {"day_pass": doc.name, "credit_note": credit.name,
            "refund": refund.name if refund else None,
            "opening_applied": str(outstanding)}
