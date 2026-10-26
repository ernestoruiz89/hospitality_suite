"""Return a paid PMS counter sale after its provider moves to ERPNext."""

from decimal import Decimal, InvalidOperation
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime, nowdate

from hospitality_suite import accounting
from hospitality_suite.cashier import expected
from hospitality_suite.pricing import money
from hospitality_suite.security import require
from hospitality_suite.service import assert_version, audit, canonical, insert, locked_doc
from hospitality_suite.standalone_accounting import provider


def _value(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(_("Importe histórico inválido"))
    if not result.is_finite() or result < 0:
        frappe.throw(_("Importe histórico inválido"))
    return result


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (
            required and not value.strip()):
        frappe.throw(_("Revise {0}; admite hasta {1} caracteres").format(label, limit))
    return value.strip()


def _account(prop, name, root, account_type=None, currency=None):
    row = frappe.db.get_value("Account", name,
        ["company", "root_type", "account_type", "account_currency",
         "is_group", "disabled"], as_dict=True) if name else None
    if (not row or row.company != prop.company or row.root_type != root or
            row.is_group or row.disabled or
            (account_type and row.account_type != account_type) or
            (currency and row.account_currency != currency)):
        frappe.throw(_("La cuenta ERPNext de la venta histórica cambió"))
    return row


def _source(prop, data):
    if provider() != "erpnext":
        frappe.throw(_("Esta devolución requiere contabilidad ERPNext"))
    require(prop.name, "approve")
    service = locked_doc("HS Service Request", data.get("service"))
    assert_version(service, data.get("modified"))
    if (service.property != prop.name or service.company != prop.company or
            service.status != "Delivered" or service.stay or service.folio or
            not service.pms_receivable or not service.pms_fiscal_invoice or
            service.pms_fiscal_credit or service.sales_invoice or
            service.credit_note or service.erp_return_refund or
            service.return_stock_entry or not service.erp_cutover_snapshot or
            not service.erp_cutover_sha256 or
            sha256(service.erp_cutover_snapshot.encode()).hexdigest() !=
                service.erp_cutover_sha256):
        frappe.throw(_("Seleccione una venta PMS trasladada y conciliada"))
    proof = frappe.parse_json(service.erp_cutover_snapshot)
    if (not isinstance(proof, dict) or proof.get("source") != service.name or
            proof.get("property") != prop.name or
            proof.get("company") != prop.company or
            proof.get("customer") != service.customer or
            proof.get("item_code") != service.item or
            proof.get("source_party") != service.pms_party or
            proof.get("source_product") != service.pms_product or
            proof.get("source_receivable") != service.pms_receivable or
            proof.get("source_invoice") != service.pms_fiscal_invoice or
            proof.get("currency") != prop.currency or
            _value(proof.get("total_amount")) != _value(service.amount) or
            _value(proof.get("net_amount")) +
                _value(proof.get("tax_amount")) != _value(service.amount) or
            _value(proof.get("quantity")) != _value(service.quantity)):
        frappe.throw(_("La venta cambió desde el corte contable"))
    payment = locked_doc("HS Payment", proof["source_payment"])
    if (payment.property != prop.name or payment.kind != "Payment" or
            payment.status != "Posted" or payment.service != service.name or
            payment.pms_receivable != service.pms_receivable or
            not payment.pms_journal or payment.payment_entry or
            payment.currency != proof["payment_currency"] or
            _value(payment.amount) != _value(proof["payment_amount"]) or
            _value(payment.base_amount) != _value(proof["total_amount"]) or
            _value(payment.exchange_rate) != _value(proof["payment_rate"]) or
            frappe.db.exists("HS Payment", {"property": prop.name,
                "source_payment": payment.name, "kind": "Refund",
                "status": "Posted"})):
        frappe.throw(_("El cobro histórico ya fue alterado o devuelto"))
    accounts = proof["target_accounts"]
    center = frappe.db.get_value("Cost Center", proof.get("cost_center"),
        ["company", "is_group", "disabled"], as_dict=True)
    if (not center or center.company != prop.company or center.is_group or
            center.disabled):
        frappe.throw(_("El centro de costo histórico cambió"))
    _account(prop, accounts["receivable_account"], "Asset", "Receivable",
        prop.currency)
    _account(prop, accounts["income_account"], "Income")
    if _value(proof["tax_amount"]):
        _account(prop, accounts["tax_account"], "Liability")
    item = frappe.db.get_value("Item", service.item,
        ["is_sales_item", "is_stock_item", "disabled"], as_dict=True)
    stock = proof.get("stock")
    if (not item or not item.is_sales_item or item.disabled or
            bool(item.is_stock_item) != bool(stock)):
        frappe.throw(_("El artículo histórico no permite su devolución"))
    if stock:
        _account(prop, stock["expense_account"], "Expense")
        _account(prop, stock["inventory_account"], "Asset", "Stock")
        warehouse = frappe.db.get_value("Warehouse", stock["warehouse"],
            ["company", "hs_property", "is_group", "disabled"], as_dict=True)
        if (not warehouse or warehouse.company != prop.company or
                warehouse.hs_property != prop.name or warehouse.is_group or
                warehouse.disabled or _value(stock["quantity"]) !=
                    _value(service.quantity) or _value(stock["value"]) <= 0):
            frappe.throw(_("El almacén histórico no permite la devolución"))
    return service, proof, payment


def quote(prop, data):
    required = {"service", "modified", "method", "shift", "reference", "reason"}
    if not isinstance(data, dict) or set(data) != required:
        frappe.throw(_("Revise la devolución de la venta PMS histórica"))
    service, proof, payment = _source(prop, data)
    reason = _text(data["reason"], "el motivo", 500, required=True)
    reference = _text(data["reference"], "la referencia", 140)
    method = locked_doc("HS Payment Method", data["method"])
    if (method.property != prop.name or method.company != prop.company or
            method.currency != proof["payment_currency"]):
        frappe.throw(_("Seleccione un medio de la moneda original del cobro"))
    _account(prop, method.account, "Asset",
        "Cash" if method.is_cash else "Bank", method.currency)
    if method.reference_required and not reference:
        frappe.throw(_("Indique la referencia del reembolso"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data["shift"])
        if (shift.property != prop.name or shift.company != prop.company or
                shift.status != "Open" or shift.cashier != frappe.session.user or
                shift.currency != method.currency):
            frappe.throw(_("La devolución en efectivo requiere turno propio abierto"),
                         frappe.PermissionError)
        if _value(proof["payment_amount"]) > _value(
                expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data["shift"]:
        frappe.throw(_("Una devolución bancaria no se asigna a turno"))
    total = _value(proof["total_amount"])
    amount = _value(proof["payment_amount"])
    rate = _value(proof["payment_rate"])
    if amount <= 0 or money(amount * rate, currency=prop.currency) != total:
        frappe.throw(_("El cobro original no puede reembolsarse exactamente"))
    signature = {"service": service.name, "modified": str(service.modified),
        "snapshot_sha256": service.erp_cutover_sha256,
        "payment": payment.name, "payment_modified": str(payment.modified),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None,
        "shift_modified": str(shift.modified) if shift else None,
        "rate": str(rate), "reference": reference, "reason": reason}
    return {"service": service.name, "modified": str(service.modified),
        "original_invoice": proof["document_number"],
        "currency": prop.currency, "total": str(total),
        "refund_currency": method.currency, "refund_amount": str(amount),
        "exchange_rate": str(rate), "method": method.name,
        "shift": shift.name if shift else None,
        "stock_value": proof["stock"]["value"] if proof.get("stock") else None,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def return_sale(prop, data):
    required = {"service", "modified", "method", "shift", "reference",
        "reason", "acceptance"}
    if not isinstance(data, dict) or set(data) != required:
        frappe.throw(_("Revise la devolución de la venta PMS histórica"))
    accepted = quote(prop, {key: value for key, value in data.items()
        if key != "acceptance"})
    if data["acceptance"] != accepted["acceptance"]:
        frappe.throw(_("Cambió la venta o el turno; revise la devolución"))
    service, proof, payment = _source(prop, data)
    total = _value(proof["total_amount"])
    net = _value(proof["net_amount"])
    tax = _value(proof["tax_amount"])
    quantity = _value(proof["quantity"])
    accounts = proof["target_accounts"]
    credit = frappe.new_doc("Sales Invoice")
    credit.flags.dont_auto_add_taxes = True
    credit.update({"company": prop.company, "customer": service.customer,
        "posting_date": nowdate(), "due_date": nowdate(),
        "currency": prop.currency, "debit_to": accounts["receivable_account"],
        "cost_center": proof["cost_center"], "is_return": 1, "update_stock": 0,
        "selling_price_list": prop.price_list,
        "price_list_currency": prop.currency, "plc_conversion_rate": 1,
        "remarks": _("Devolución de venta PMS {0}. Factura fiscal original {1}. {2}").format(
            service.name, proof["document_number"], accepted["reason"])})
    credit.append("items", {"item_code": service.item,
        "qty": -float(quantity), "rate": float(net / quantity),
        "income_account": accounts["income_account"],
        "cost_center": proof["cost_center"],
        "warehouse": proof["stock"]["warehouse"] if proof.get("stock")
            else prop.warehouse, "ignore_pricing_rule": 1})
    if tax:
        credit.append("taxes", {"charge_type": "Actual",
            "account_head": accounts["tax_account"],
            "tax_amount": -float(tax),
            "description": _("Tributo de venta PMS histórica")})
    credit.set_missing_values()
    credit.calculate_taxes_and_totals()
    if (money(credit.net_total, currency=prop.currency) != -net or
            money(credit.grand_total, currency=prop.currency) != -total):
        frappe.throw(_("ERPNext cambió el total de la nota histórica"))
    accounting.post_standard(credit, prop)
    method = locked_doc("HS Payment Method", accepted["method"])
    pe = frappe.new_doc("Payment Entry")
    pe.update({"company": prop.company, "payment_type": "Pay",
        "posting_date": nowdate(), "party_type": "Customer",
        "party": service.customer, "paid_from": method.account,
        "paid_to": accounts["receivable_account"],
        "paid_amount": float(_value(accepted["refund_amount"])),
        "received_amount": float(total),
        "source_exchange_rate": float(_value(accepted["exchange_rate"])),
        "target_exchange_rate": 1,
        "mode_of_payment": method.mode_of_payment,
        "reference_no": accepted["reference"] or credit.name,
        "reference_date": nowdate(), "cost_center": proof["cost_center"],
        "hs_shift": accepted["shift"], "remarks": accepted["reason"]})
    pe.append("references", {"reference_doctype": "Sales Invoice",
        "reference_name": credit.name, "allocated_amount": -float(total)})
    accounting.post_standard(pe, prop)
    refund = insert("HS Payment", prop, customer=service.customer,
        shift=accepted["shift"], method=method.name,
        amount=accepted["refund_amount"], currency=method.currency,
        exchange_rate=accepted["exchange_rate"], base_amount=total,
        kind="Refund", status="Posted", source_payment=payment.name,
        payment_entry=pe.name, sales_invoice=credit.name,
        service=service.name, reference=accepted["reference"],
        reason=accepted["reason"])
    stock_entry = None
    if proof.get("stock"):
        stock = proof["stock"]
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.update({"company": prop.company,
            "stock_entry_type": "Material Receipt",
            "purpose": "Material Receipt",
            "expense_account": stock["expense_account"],
            "cost_center": proof["cost_center"],
            "remarks": _("Devolución de venta PMS {0}. {1}").format(
                service.name, accepted["reason"])})
        stock_entry.append("items", {"item_code": service.item,
            "t_warehouse": stock["warehouse"],
            "qty": float(quantity),
            "basic_rate": float(_value(stock["value"]) / quantity),
            "valuation_rate": float(_value(stock["value"]) / quantity),
            "expense_account": stock["expense_account"],
            "cost_center": proof["cost_center"]})
        accounting.post_standard(stock_entry, prop)
    before = getattr(frappe.local, "hs_erp_historical_direct_return", False)
    frappe.local.hs_erp_historical_direct_return = True
    try:
        service.status = "Returned"
        service.credit_note = credit.name
        service.erp_return_refund = refund.name
        service.return_stock_entry = stock_entry.name if stock_entry else None
        service.save()
    finally:
        frappe.local.hs_erp_historical_direct_return = before
    audit(prop, "erp_historical_direct_sale_return", service,
        accepted["reason"], {"credit_note": credit.name,
            "refund": refund.name,
            "stock_entry": stock_entry.name if stock_entry else None,
            "source_invoice": proof["source_invoice"]})
    return {"service": service.name, "credit_note": credit.name,
        "refund": refund.name,
        "stock_entry": stock_entry.name if stock_entry else None}


def _reversal_source(prop, data):
    if provider() != "erpnext":
        frappe.throw(_("Esta corrección requiere contabilidad ERPNext"))
    require(prop.name, "approve")
    service = locked_doc("HS Service Request", data.get("service"))
    assert_version(service, data.get("modified"))
    if (service.property != prop.name or service.company != prop.company or
            service.status != "Returned" or service.stay or service.folio or
            not service.pms_receivable or not service.pms_fiscal_invoice or
            service.pms_fiscal_credit or service.sales_invoice or
            not service.erp_cutover_snapshot or not service.erp_cutover_sha256 or
            sha256(service.erp_cutover_snapshot.encode()).hexdigest() !=
                service.erp_cutover_sha256 or
            not service.credit_note or not service.erp_return_refund):
        frappe.throw(_("Seleccione una devolución PMS histórica vigente en ERPNext"))
    proof = frappe.parse_json(service.erp_cutover_snapshot)
    if (not isinstance(proof, dict) or proof.get("source") != service.name or
            proof.get("property") != prop.name or
            proof.get("company") != prop.company or
            proof.get("source_receivable") != service.pms_receivable or
            proof.get("source_invoice") != service.pms_fiscal_invoice or
            bool(proof.get("stock")) != bool(service.return_stock_entry)):
        frappe.throw(_("La prueba de corte de la venta no concilia"))
    credit = locked_doc("Sales Invoice", service.credit_note)
    refund = locked_doc("HS Payment", service.erp_return_refund)
    pe = locked_doc("Payment Entry", refund.payment_entry)
    stock = (locked_doc("Stock Entry", service.return_stock_entry)
        if service.return_stock_entry else None)
    if (credit.docstatus != 1 or not credit.is_return or
            credit.company != prop.company or credit.hs_property != prop.name or
            credit.customer != service.customer or
            _value(-credit.grand_total) != _value(service.amount) or
            refund.status != "Posted" or refund.kind != "Refund" or
            refund.property != prop.name or refund.company != prop.company or
            refund.service != service.name or
            refund.source_payment != proof.get("source_payment") or
            refund.sales_invoice != credit.name or
            pe.docstatus != 1 or pe.company != prop.company or
            pe.hs_property != prop.name or pe.payment_type != "Pay" or
            pe.party != service.customer or
            not any(row.reference_doctype == "Sales Invoice" and
                row.reference_name == credit.name and
                _value(-row.allocated_amount) == _value(service.amount)
                for row in pe.references) or
            (stock and (stock.docstatus != 1 or
                stock.company != prop.company or
                stock.hs_property != prop.name or
                stock.stock_entry_type != "Material Receipt"))):
        frappe.throw(_("La devolución ya cambió; revise sus documentos"))
    if (str(refund.business_date) != str(prop.business_date) or
            frappe.db.exists("HS Daily Close", {"property": prop.name,
                "business_date": prop.business_date, "status": "Closed"})):
        frappe.throw(_("Solo puede corregir una devolución en la fecha operativa abierta"))
    shift = locked_doc("HS Shift", refund.shift) if refund.shift else None
    if shift and (shift.property != prop.name or shift.company != prop.company or
            shift.status != "Open" or pe.hs_shift != shift.name):
        frappe.throw(_("El turno del reembolso debe continuar abierto"))
    if stock:
        # A later movement can depend on the receipt's valuation. Correct it
        # before further movements of the same article in this warehouse.
        later = frappe.db.sql(
            "SELECT later.name FROM `tabStock Ledger Entry` own "
            "JOIN `tabStock Ledger Entry` later ON "
            "later.item_code=own.item_code AND later.warehouse=own.warehouse "
            "WHERE own.voucher_type='Stock Entry' AND own.voucher_no=%s "
            "AND own.is_cancelled=0 AND later.is_cancelled=0 "
            "AND later.voucher_no<>%s AND later.creation>own.creation LIMIT 1",
            (stock.name, stock.name))
        if later:
            frappe.throw(_("Existen movimientos de inventario posteriores al reingreso"))
    history = frappe.parse_json(service.erp_return_corrections) if (
        service.erp_return_corrections) else []
    if (not isinstance(history, list) or
            bool(service.erp_return_corrections) !=
                bool(service.erp_return_corrections_sha256) or
            (service.erp_return_corrections and
             sha256(service.erp_return_corrections.encode()).hexdigest() !=
                service.erp_return_corrections_sha256)):
        frappe.throw(_("El historial de correcciones no concilia"))
    return service, proof, credit, refund, pe, stock, shift, history


def reversal_quote(prop, data):
    if not isinstance(data, dict) or set(data) != {"service", "modified", "reason"}:
        frappe.throw(_("Revise la corrección de la devolución histórica"))
    reason = _text(data["reason"], "el motivo", 500, required=True)
    service, proof, credit, refund, pe, stock, shift, history = (
        _reversal_source(prop, data))
    signature = {"service": service.name, "modified": str(service.modified),
        "snapshot_sha256": service.erp_cutover_sha256,
        "history_sha256": service.erp_return_corrections_sha256,
        "credit": credit.name, "credit_modified": str(credit.modified),
        "refund": refund.name, "refund_modified": str(refund.modified),
        "payment_entry": pe.name, "payment_modified": str(pe.modified),
        "stock_entry": stock.name if stock else None,
        "stock_modified": str(stock.modified) if stock else None,
        "shift": shift.name if shift else None,
        "shift_modified": str(shift.modified) if shift else None,
        "business_date": str(prop.business_date), "reason": reason}
    return {"service": service.name, "original_invoice": proof["document_number"],
        "credit_note": credit.name, "refund": refund.name,
        "payment_entry": pe.name, "stock_entry": stock.name if stock else None,
        "refund_currency": refund.currency, "refund_amount": str(refund.amount),
        "business_date": str(prop.business_date), "correction_count": len(history),
        "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def reverse_return(prop, data):
    if not isinstance(data, dict) or set(data) != {
            "service", "modified", "reason", "acceptance"}:
        frappe.throw(_("Revise la corrección de la devolución histórica"))
    accepted = reversal_quote(prop, {key: value for key, value in data.items()
        if key != "acceptance"})
    if accepted["acceptance"] != data["acceptance"]:
        frappe.throw(_("Cambió la devolución; revise la corrección"))
    service, proof, credit, refund, pe, stock, shift, history = (
        _reversal_source(prop, data))
    before = getattr(frappe.local, "hs_erp_historical_direct_reversal", None)
    frappe.local.hs_erp_historical_direct_reversal = service.name
    try:
        for doc in (pe, credit, stock):
            if not doc:
                continue
            # Payment Entry cancellation updates the credit's outstanding
            # amount and modified timestamp through ERPNext reconciliation.
            doc.reload()
            if doc.docstatus != 1:
                frappe.throw(_("Cambió un comprobante de la devolución"))
            doc.hs_correction_reason = accepted["reason"]
            doc.flags.ignore_permissions = True
            doc.cancel()
        refund.reload()
        if refund.status != "Cancelled":
            frappe.throw(_("El reembolso no fue cancelado por ERPNext"))
        history.append({"credit_note": credit.name, "refund": refund.name,
            "payment_entry": pe.name, "stock_entry": stock.name if stock else None,
            "source_payment": proof["source_payment"],
            "business_date": str(prop.business_date),
            "actor": frappe.session.user, "at": str(now_datetime()),
            "reason": accepted["reason"]})
        service.status = "Delivered"
        service.credit_note = None
        service.erp_return_refund = None
        service.return_stock_entry = None
        service.erp_return_corrections = canonical(history)
        service.erp_return_corrections_sha256 = sha256(
            service.erp_return_corrections.encode()).hexdigest()
        service.save()
    finally:
        frappe.local.hs_erp_historical_direct_reversal = before
    audit(prop, "erp_historical_direct_sale_return_reversal", service,
        accepted["reason"], {"credit_note": credit.name,
            "refund": refund.name, "payment_entry": pe.name,
            "stock_entry": stock.name if stock else None,
            "source_invoice": proof["source_invoice"],
            "correction_count": len(history)})
    return {"service": service.name, "status": service.status,
        "credit_note": credit.name, "refund": refund.name,
        "payment_entry": pe.name,
        "stock_entry": stock.name if stock else None,
        "correction_count": len(history)}
