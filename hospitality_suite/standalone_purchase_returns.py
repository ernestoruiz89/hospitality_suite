"""Stock returns, supplier credits and refunds in the standalone PMS book."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, post, require_pms
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, latest_rate
from hospitality_suite.standalone_inventory import consume, current_balance
from hospitality_suite.standalone_purchases import _money, _text, outstanding
from hospitality_suite.stock_rules import StockValidationError, issue, quantity


def _source_lines(purchase):
    if purchase.lines:
        return {line.stock_movement: line for line in purchase.lines}
    if not purchase.stock_movement:
        frappe.throw(_("La compra histórica no conserva su recepción de inventario"))
    return {purchase.stock_movement: purchase}


def _prior(prop, movement):
    return frappe.db.sql(
        "SELECT COALESCE(SUM(l.quantity),0) AS quantity, "
        "COALESCE(SUM(l.credit_amount),0) AS credit_amount, "
        "COALESCE(SUM(l.tax_amount),0) AS tax_amount, "
        "COALESCE(SUM(l.base_credit),0) AS base_credit, "
        "COALESCE(SUM(l.base_tax),0) AS base_tax "
        "FROM `tabHS PMS Purchase Return Line` l "
        "JOIN `tabHS PMS Purchase Return` r ON r.name=l.parent "
        "WHERE r.property=%s AND r.status='Posted' AND l.source_movement=%s",
        (prop.name, movement), as_dict=True)[0]


def _share(original, previously, new_qty, total_qty, prior_qty):
    original = Decimal(str(original))
    prior_value = Decimal(str(previously))
    if new_qty == total_qty - prior_qty:
        result = original - prior_value
    else:
        cumulative = (original * (prior_qty + new_qty) / total_qty).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        result = cumulative - prior_value
    return result


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if (not isinstance(data, dict) or set(data) -
            {"purchase", "reference", "reason", "variance_account", "lines"} or
            not {"purchase", "reference", "reason", "lines"}.issubset(data)):
        frappe.throw(_("Revise la devolución al proveedor"))
    purchase = locked_doc("HS PMS Purchase", data["purchase"])
    if purchase.property != prop.name or purchase.organization != prop.organization or purchase.status != "Posted":
        frappe.throw(_("Seleccione una compra publicada del establecimiento"))
    reference = _text(data["reference"], "la referencia de devolución")
    reason = _text(data["reason"], "el motivo de devolución", 500)
    if frappe.db.exists("HS PMS Purchase Return", {"property": prop.name,
            "purchase": purchase.name, "reference": reference}):
        frappe.throw(_("Esta devolución ya se registró"))
    requested = data["lines"]
    if not isinstance(requested, list) or not 1 <= len(requested) <= 50:
        frappe.throw(_("Seleccione de una a cincuenta líneas para devolver"))
    sources = _source_lines(purchase)
    seen, lines = set(), []
    credit = base_credit = base_tax = stock_value = Decimal(0)
    for supplied in requested:
        if not isinstance(supplied, dict) or set(supplied) != {"source_movement", "quantity"}:
            frappe.throw(_("Revise la línea solicitada para devolución"))
        source_name = supplied["source_movement"]
        if source_name not in sources or source_name in seen:
            frappe.throw(_("Seleccione cada línea original de esta compra una sola vez"))
        seen.add(source_name)
        source = sources[source_name]
        receipt = locked_doc("HS Stock Movement", source_name)
        if (receipt.property != prop.name or receipt.source_doctype != "HS PMS Purchase" or
                receipt.source_name != purchase.name or receipt.direction != "Receipt" or
                (receipt.product, receipt.warehouse) != (source.product, source.warehouse)):
            frappe.throw(_("La recepción original no coincide con la compra"))
        try:
            qty = quantity(supplied["quantity"])
            original_qty = quantity(source.quantity)
        except StockValidationError as exc:
            frappe.throw(str(exc))
        prior = _prior(prop, source_name)
        prior_qty = Decimal(str(prior.quantity))
        if prior_qty + qty > original_qty:
            frappe.throw(_("La devolución supera la cantidad recibida"))
        line_credit = _share(source.invoice_amount, prior.credit_amount, qty, original_qty, prior_qty)
        line_tax = _share(source.recoverable_tax or 0, prior.tax_amount, qty, original_qty, prior_qty)
        line_base = _share(source.base_amount, prior.base_credit, qty, original_qty, prior_qty)
        line_base_tax = _share(source.base_tax or 0, prior.base_tax, qty, original_qty, prior_qty)
        if (line_credit <= line_tax or line_base <= line_base_tax or
                line_tax < 0 or line_base_tax < 0):
            frappe.throw(_("La fracción devuelta no conserva crédito positivo"))
        balance_qty, balance_value = current_balance(prop, source.product, source.warehouse)
        try:
            movement = issue(balance_qty, balance_value, qty)
        except StockValidationError as exc:
            frappe.throw(str(exc))
        value = -Decimal(movement["value_delta"])
        if value <= 0:
            frappe.throw(_("La devolución requiere inventario con costo positivo"))
        lines.append({"source_movement": source_name, "product": source.product,
            "warehouse": source.warehouse, "quantity": str(qty),
            "invoice_currency": purchase.invoice_currency, "base_currency": prop.currency,
            "credit_amount": _money(line_credit), "tax_amount": _money(line_tax),
            "base_credit": _money(line_base), "base_tax": _money(line_base_tax),
            "stock_value": _money(value), "inventory_account": source.inventory_account,
            "available_quantity": str(original_qty - prior_qty),
            "stock_balance_quantity": str(balance_qty),
            "stock_balance_value": _money(balance_value)})
        credit += line_credit
        base_credit += line_base
        base_tax += line_base_tax
        stock_value += value
    variance = base_credit - base_tax - stock_value
    variance_account = None
    if variance:
        if data.get("variance_account"):
            variance_account = account(prop, data["variance_account"])
            expected_root = "Income" if variance > 0 else "Expense"
            if (variance_account.root_type != expected_root or
                    variance_account.account_currency != prop.currency or
                    variance_account.name in {purchase.payable_account, purchase.tax_account} |
                        {line["inventory_account"] for line in lines}):
                frappe.throw(_("Seleccione una cuenta de variación de tipo {0} en moneda base").format(expected_root))
    elif data.get("variance_account"):
        frappe.throw(_("No se necesita cuenta de variación para esta devolución"))
    payable_before = outstanding(prop, purchase.name)
    applied = min(base_credit, payable_before)
    supplier_credit = base_credit - applied
    signature = {"property": prop.name, "purchase": purchase.name,
        "purchase_modified": str(purchase.modified), "reference": reference,
        "reason": reason, "lines": lines, "payable_before": _money(payable_before),
        "variance_account": variance_account.name if variance_account else None}
    return {"purchase": purchase.name, "supplier": purchase.supplier,
        "reference": reference, "reason": reason,
        "invoice_currency": purchase.invoice_currency, "base_currency": prop.currency,
        "credit_amount": _money(credit), "base_credit": _money(base_credit),
        "base_tax": _money(base_tax), "stock_value": _money(stock_value),
        "variance": _money(variance), "variance_nature":
            "Income" if variance > 0 else "Expense" if variance < 0 else None,
        "variance_account": variance_account.name if variance_account else None,
        "payable_before": _money(payable_before),
        "payable_applied": _money(applied), "supplier_credit": _money(supplier_credit),
        "payable_account": purchase.payable_account, "tax_account": purchase.tax_account,
        "lines": lines,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()
            if not variance or variance_account else None}


def return_purchase(prop, data, *, cancellation=False):
    if not isinstance(data, dict) or set(data) - {
            "purchase", "reference", "reason", "variance_account", "lines", "acceptance"}:
        frappe.throw(_("Revise la devolución antes de registrar"))
    reviewed = quote(prop, {key: value for key, value in data.items() if key != "acceptance"})
    if not reviewed["acceptance"] or data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("El inventario, crédito o cuenta de variación cambió; revise nuevamente"))
    doc = insert("HS PMS Purchase Return", prop, organization=prop.organization,
        purchase=reviewed["purchase"], supplier=reviewed["supplier"],
        kind="Full Cancellation" if cancellation else "Return",
        reference=reviewed["reference"], reason=reviewed["reason"],
        business_date=prop.business_date,
        invoice_currency=reviewed["invoice_currency"], base_currency=prop.currency,
        credit_amount=reviewed["credit_amount"], base_credit=reviewed["base_credit"],
        base_tax=reviewed["base_tax"], stock_value=reviewed["stock_value"],
        variance=reviewed["variance"], payable_applied=reviewed["payable_applied"],
        supplier_credit=reviewed["supplier_credit"],
        payable_account=reviewed["payable_account"], tax_account=reviewed["tax_account"],
        variance_account=reviewed["variance_account"], status="Posted",
        lines=[{key: line[key] for key in ("source_movement", "product", "warehouse",
            "quantity", "invoice_currency", "base_currency", "credit_amount",
            "tax_amount", "base_credit", "base_tax", "stock_value",
            "inventory_account")} for line in reviewed["lines"]])
    movements = []
    for line in doc.lines:
        stock = consume(prop, product=line.product, warehouse=line.warehouse,
            quantity=line.quantity, counter_account=doc.payable_account,
            counter_party=doc.supplier, source_doctype=doc.doctype,
            source_name=doc.name, purpose="Supplier Return", memo=doc.reference,
            inventory_account_name=line.inventory_account, allow_inactive=True)
        if -Decimal(stock["value_delta"]) != Decimal(str(line.stock_value)):
            frappe.throw(_("El costo del inventario cambió durante la devolución"))
        frappe.db.set_value(line.doctype, line.name, "return_movement",
                            stock["movement"], update_modified=False)
        movements.append(stock["movement"])
    journal_lines = []
    if Decimal(reviewed["base_tax"]) > 0:
        journal_lines.extend([
            {"account": doc.payable_account, "debit": doc.base_tax, "credit": 0,
             "party": doc.supplier},
            {"account": doc.tax_account, "debit": 0, "credit": doc.base_tax}])
    variance = Decimal(reviewed["variance"])
    if variance > 0:
        journal_lines.extend([
            {"account": doc.payable_account, "debit": str(variance), "credit": 0,
             "party": doc.supplier},
            {"account": doc.variance_account, "debit": 0, "credit": str(variance)}])
    elif variance < 0:
        journal_lines.extend([
            {"account": doc.variance_account, "debit": str(-variance), "credit": 0},
            {"account": doc.payable_account, "debit": 0, "credit": str(-variance),
             "party": doc.supplier}])
    adjustment = post(prop, source_doctype=doc.doctype, source_name=doc.name,
        purpose="Supplier Return Adjustment", lines=journal_lines,
        memo=doc.reason) if journal_lines else None
    if adjustment:
        frappe.db.set_value(doc.doctype, doc.name, "adjustment_journal",
                            adjustment.name, update_modified=False)
    audit(prop, "pms_supplier_returned", doc, reason=doc.reason,
        details={"purchase": doc.purchase, "movements": movements,
                 "adjustment_journal": adjustment.name if adjustment else None,
                 "supplier_credit": reviewed["supplier_credit"]})
    return {"return": doc.name, "purchase": doc.purchase,
        "stock_movements": movements, "adjustment_journal": adjustment.name if adjustment else None,
        "payable_applied": reviewed["payable_applied"],
        "supplier_credit": reviewed["supplier_credit"],
        "outstanding": _money(outstanding(prop, doc.purchase))}


def cancellation_quote(prop, data):
    reviewed = quote(prop, data)
    purchase = locked_doc("HS PMS Purchase", reviewed["purchase"])
    if frappe.db.exists("HS Payment", {"property": prop.name,
            "pms_purchase": purchase.name, "kind": "Supplier Payment",
            "status": "Posted"}) or frappe.db.exists("HS PMS Purchase Return", {
            "property": prop.name, "purchase": purchase.name, "status": "Posted"}):
        frappe.throw(_("Cancele solo compras sin pagos ni devoluciones; para las demás use devolución"))
    sources = _source_lines(purchase)
    requested = {row["source_movement"]: quantity(row["quantity"])
        for row in data["lines"]}
    if (set(requested) != set(sources) or
            any(requested[name] != quantity(source.quantity)
                for name, source in sources.items()) or
            Decimal(reviewed["base_credit"]) != Decimal(str(purchase.base_amount)) or
            Decimal(reviewed["supplier_credit"]) != 0):
        frappe.throw(_("La cancelación requiere devolver todas las líneas y cantidades"))
    reviewed["acceptance"] = (sha256(canonical({"cancel": True,
        "return_acceptance": reviewed["acceptance"]}).encode()).hexdigest()
        if reviewed["acceptance"] else None)
    return reviewed


def cancel_purchase(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "purchase", "reference", "reason", "variance_account", "lines", "acceptance"}:
        frappe.throw(_("Revise la cancelación de compra"))
    reviewed = cancellation_quote(prop, {key: value for key, value in data.items()
                                         if key != "acceptance"})
    if not reviewed["acceptance"] or data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("La compra o el inventario cambió; revise la cancelación"))
    return_review = quote(prop, {key: value for key, value in data.items()
                                 if key != "acceptance"})
    result = return_purchase(prop, {**data,
        "acceptance": return_review["acceptance"]}, cancellation=True)
    purchase = locked_doc("HS PMS Purchase", reviewed["purchase"])
    purchase.status = "Cancelled"
    purchase.cancellation_return = result["return"]
    purchase.cancellation_reason = reviewed["reason"]
    purchase.cancelled_at = now_datetime()
    purchase.save()
    audit(prop, "pms_purchase_cancelled", purchase, reason=reviewed["reason"],
        details={"return": result["return"],
                 "stock_movements": result["stock_movements"]})
    return {"purchase": purchase.name, "status": purchase.status,
            "return": result["return"], "stock_movements": result["stock_movements"]}


def refund_available(prop, return_name):
    row = locked_doc("HS PMS Purchase Return", return_name)
    if row.property != prop.name or row.status != "Posted":
        frappe.throw(_("Seleccione una devolución del establecimiento"))
    received = sum((Decimal(str(payment.base_amount)) for payment in current_all(
        "HS Payment", filters={"property": prop.name, "pms_purchase_return": row.name,
            "kind": "Supplier Refund", "status": "Posted"}, fields=["base_amount"])), Decimal(0))
    remaining = Decimal(str(row.supplier_credit)) - received
    if remaining < 0:
        frappe.throw(_("El reintegro del proveedor requiere conciliación"))
    return remaining


def refund_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {
            "return", "method", "shift", "amount", "reference", "reason"}:
        frappe.throw(_("Revise el reintegro del proveedor"))
    row = locked_doc("HS PMS Purchase Return", data.get("return"))
    if row.property != prop.name or row.status != "Posted":
        frappe.throw(_("Seleccione una devolución vigente"))
    available = refund_available(prop, row.name)
    if available <= 0:
        frappe.throw(_("La devolución no tiene crédito pendiente de reintegro"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de cobro del establecimiento"))
    cash_account = account(prop, method.account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank)):
        frappe.throw(_("El medio no conserva Caja o banco válido"))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0 or base <= 0 or base > available:
        frappe.throw(_("El reintegro supera el crédito pendiente del proveedor"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if shift.property != prop.name or shift.status != "Open" or shift.cashier != frappe.session.user:
            frappe.throw(_("Se requiere turno propio abierto para recibir efectivo"), frappe.PermissionError)
    elif data.get("shift"):
        frappe.throw(_("El reintegro bancario no se asigna a un turno"))
    reference = _text(data.get("reference"), "la referencia de reintegro")
    reason = _text(data.get("reason"), "el motivo del reintegro", 500)
    if frappe.db.exists("HS Payment", {"property": prop.name, "kind": "Supplier Refund",
            "pms_purchase_return": row.name, "reference": reference, "status": "Posted"}):
        frappe.throw(_("Esta referencia de reintegro ya se registró"))
    signature = {"return": row.name, "modified": str(row.modified),
        "available": _money(available), "method": method.name,
        "method_modified": str(method.modified), "shift": shift.name if shift else None,
        "amount": _money(value), "rate": str(rate), "rate_record": rate_record,
        "reference": reference, "reason": reason}
    return {"return": row.name, "purchase": row.purchase,
        "supplier": row.supplier, "payable_account": row.payable_account,
        "cash_account": cash_account.name, "method": method.name,
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": _money(value), "exchange_rate": str(rate),
        "rate_record": rate_record, "base_amount": _money(base),
        "base_currency": prop.currency, "available_before": _money(available),
        "available_after": _money(available - base),
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def refund(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "return", "method", "shift", "amount", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise el reintegro antes de registrar"))
    reviewed = refund_quote(prop, {key: value for key, value in data.items()
                                   if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("El crédito, cambio o medio de cobro cambió; revise nuevamente"))
    payment = insert("HS Payment", prop, shift=reviewed["shift"],
        method=reviewed["method"], currency=reviewed["currency"],
        amount=reviewed["amount"], exchange_rate=reviewed["exchange_rate"],
        base_amount=reviewed["base_amount"], kind="Supplier Refund", status="Posted",
        reference=reviewed["reference"], reason=reviewed["reason"],
        pms_party=reviewed["supplier"],
        pms_counter_account=reviewed["payable_account"],
        pms_purchase=reviewed["purchase"], pms_purchase_return=reviewed["return"])
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
        purpose="Supplier Refund", memo=reviewed["reason"], lines=[
            {"account": reviewed["cash_account"], "debit": reviewed["base_amount"],
             "credit": 0, "account_currency": reviewed["currency"],
             "exchange_rate": reviewed["exchange_rate"],
             "debit_in_account_currency": reviewed["amount"],
             "credit_in_account_currency": 0},
            {"account": reviewed["payable_account"], "debit": 0,
             "credit": reviewed["base_amount"], "party": reviewed["supplier"]}])
    payment.pms_journal = journal.name
    payment.save()
    audit(prop, "pms_supplier_refunded", payment, reason=reviewed["reason"],
        details={"return": reviewed["return"], "journal": journal.name,
                 "amount": reviewed["amount"], "currency": reviewed["currency"]})
    return {"payment": payment.name, "journal": journal.name,
        "return": reviewed["return"], "available": reviewed["available_after"]}


def snapshot(prop):
    require_pms(prop)
    require(prop.name, "finance")
    rows = frappe.get_all("HS PMS Purchase Return", filters={"property": prop.name},
        fields=["name", "purchase", "supplier", "kind", "reference", "business_date",
                "invoice_currency", "base_currency", "credit_amount", "base_credit",
                "stock_value", "variance", "supplier_credit"],
        order_by="creation desc", limit_page_length=200)
    for row in rows:
        row["refund_available"] = _money(refund_available(prop, row.name))
    return rows
