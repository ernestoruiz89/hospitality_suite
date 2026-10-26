"""Supplier stock receipts and payable settlements in the PMS ledger."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import (account, account_currency_balance,
    post, require_pms)
from hospitality_suite.standalone_cash import expected
from hospitality_suite.standalone_currency import enabled, enabled_currencies, latest_rate
from hospitality_suite.standalone_inventory import receive
from hospitality_suite.stock_rules import StockValidationError, quantity


def _text(value, label, maximum=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, maximum))
    return value.strip()


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def create_supplier(prop, data):
    require_pms(prop)
    require(prop.name, "inventory")
    if not isinstance(data, dict) or set(data) - {"party_name", "tax_id"}:
        frappe.throw(_("Revise los datos del proveedor"))
    tax_id = data.get("tax_id") or ""
    if not isinstance(tax_id, str) or len(tax_id.strip()) > 140:
        frappe.throw(_("Revise la identificación del proveedor"))
    doc = insert("HS Party", prop, organization=prop.organization,
        party_name=_text(data.get("party_name"), "el nombre del proveedor"),
        party_type="Supplier", tax_id=tax_id.strip(), active=1)
    audit(prop, "pms_supplier_created", doc)
    return {"supplier": doc.name}


def purchase_quote(prop, data):
    require_pms(prop)
    require(prop.name, "inventory")
    fields = {"supplier", "supplier_reference", "product", "warehouse", "quantity",
              "invoice_currency", "invoice_amount", "recoverable_tax",
              "payable_account", "tax_account", "notes", "lines", "purchase_order"}
    required = {"supplier", "supplier_reference", "invoice_currency", "payable_account"}
    if not isinstance(data, dict) or set(data) - fields or not required.issubset(data):
        frappe.throw(_("Revise la recepción de compra"))
    supplier = locked_doc("HS Party", data["supplier"])
    if (supplier.property != prop.name or supplier.organization != prop.organization or
            not supplier.active or supplier.party_type not in ("Supplier", "Both")):
        frappe.throw(_("Seleccione un proveedor activo del establecimiento"))
    payable = account(prop, data["payable_account"])
    if (payable.root_type != "Liability" or payable.account_type != "Payable" or
            payable.account_currency != prop.currency):
        frappe.throw(_("La compra requiere una cuenta por pagar en moneda base"))
    currency = data["invoice_currency"]
    if not enabled(prop, currency):
        frappe.throw(_("La moneda de la compra no está habilitada"))
    rate, rate_record = latest_rate(prop, currency)
    order = None
    ordered_lines = {}
    if data.get("purchase_order"):
        order = locked_doc("HS PMS Purchase Order", data["purchase_order"])
        if (order.property != prop.name or order.organization != prop.organization or
                order.status != "Approved" or order.supplier != supplier.name or
                order.currency != currency or order.payable_account != payable.name or
                (order.tax_account or None) != (data.get("tax_account") or None)):
            frappe.throw(_("La orden aprobada no coincide con proveedor, moneda o cuentas"))
        ordered_lines = {line.name: line for line in order.lines}
        if "lines" not in data:
            frappe.throw(_("Seleccione líneas pendientes de la orden"))
    if "lines" in data:
        if any(field in data for field in ("product", "warehouse", "quantity",
                                           "invoice_amount", "recoverable_tax")):
            frappe.throw(_("Use líneas o campos de una línea, sin mezclarlos"))
        line_inputs = data["lines"]
        if not isinstance(line_inputs, list) or not 1 <= len(line_inputs) <= 50:
            frappe.throw(_("La compra requiere de una a cincuenta líneas"))
    else:
        if not {"product", "warehouse", "quantity", "invoice_amount"}.issubset(data):
            frappe.throw(_("Indique la línea de producto de la compra"))
        line_inputs = [{key: data[key] for key in ("product", "warehouse", "quantity",
            "invoice_amount")}
            | {"recoverable_tax": data.get("recoverable_tax") or 0}]
    lines, seen = [], set()
    invoice_total = tax_total = Decimal(0)
    base_before = tax_before = Decimal(0)
    for index, supplied in enumerate(line_inputs, 1):
        if (not isinstance(supplied, dict) or
                set(supplied) - {"product", "warehouse", "quantity",
                                 "invoice_amount", "recoverable_tax", "order_line"} or
                not {"product", "warehouse", "quantity"}.issubset(supplied) or
                (not order and "invoice_amount" not in supplied)):
            frappe.throw(_("Revise la línea {0} de la compra").format(index))
        if bool(supplied.get("order_line")) != bool(order):
            frappe.throw(_("Cada línea debe pertenecer a la orden seleccionada"))
        product = locked_doc("HS Product", supplied["product"])
        warehouse = locked_doc("HS Warehouse", supplied["warehouse"])
        pair = (product.name, warehouse.name)
        if pair in seen:
            frappe.throw(_("Agrupe el mismo producto y almacén en una sola línea"))
        seen.add(pair)
        if (product.property != prop.name or product.organization != prop.organization or
                not product.active or product.product_type != "Stock" or
                warehouse.property != prop.name or warehouse.organization != prop.organization or
                not warehouse.active):
            frappe.throw(_("Seleccione productos y almacenes activos del establecimiento"))
        inventory = account(prop, product.inventory_account)
        if inventory.root_type != "Asset" or inventory.account_currency != prop.currency:
            frappe.throw(_("Cada producto requiere cuenta de inventario en moneda base"))
        try:
            qty = quantity(supplied["quantity"])
            received_before = None
            if order:
                ordered = ordered_lines.get(supplied["order_line"])
                if (not ordered or ordered.product != product.name or
                        ordered.warehouse != warehouse.name or
                        ordered.inventory_account != inventory.name):
                    frappe.throw(_("La línea no pertenece a la orden aprobada"))
                from hospitality_suite.standalone_purchase_orders import allocation, progress
                received_before = progress(prop, ordered.name)
                invoice, tax = allocation(ordered, received_before, qty)
                if ("invoice_amount" in supplied and
                        amount(supplied["invoice_amount"]) != invoice) or (
                        "recoverable_tax" in supplied and
                        amount(supplied["recoverable_tax"]) != tax):
                    frappe.throw(_("El precio de la recepción difiere del aprobado"))
            else:
                invoice = amount(supplied["invoice_amount"])
                tax = amount(supplied.get("recoverable_tax") or 0)
        except (StockValidationError, LedgerValidationError) as exc:
            frappe.throw(str(exc))
        if invoice <= 0 or tax >= invoice:
            frappe.throw(_("Cada línea requiere costo positivo e impuesto menor que su total"))
        invoice_total += invoice
        tax_total += tax
        base = (invoice_total * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base_tax = (tax_total * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_base, line_tax = base - base_before, base_tax - tax_before
        line_cost = line_base - line_tax
        if line_cost <= 0:
            frappe.throw(_("Cada línea debe conservar costo de inventario positivo en moneda base"))
        base_before, tax_before = base, base_tax
        lines.append({"product": product.name, "product_name": product.product_name,
            "product_modified": str(product.modified), "warehouse": warehouse.name,
            "warehouse_modified": str(warehouse.modified), "quantity": str(qty),
            "order_line": supplied.get("order_line") if order else None,
            "order_received_before": str(received_before) if order else None,
            "invoice_currency": currency, "base_currency": prop.currency,
            "invoice_amount": _money(invoice), "recoverable_tax": _money(tax),
            "base_amount": _money(line_base), "base_cost": _money(line_cost),
            "base_tax": _money(line_tax), "inventory_account": inventory.name})
    tax_account = None
    if tax_total:
        tax_account = account(prop, data.get("tax_account"))
        if (tax_account.root_type != "Asset" or tax_account.account_type != "Tax" or
                tax_account.account_currency != prop.currency or
                tax_account.name in {line["inventory_account"] for line in lines}):
            frappe.throw(_("El impuesto recuperable necesita otra cuenta de activo en moneda base"))
    elif data.get("tax_account"):
        frappe.throw(_("No indique cuenta de impuesto si la factura no lo desglosa"))
    cost = base_before - tax_before
    reference = _text(data["supplier_reference"], "la referencia de factura del proveedor")
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes) > 500:
        frappe.throw(_("Las observaciones deben tener hasta 500 caracteres"))
    if frappe.db.exists("HS PMS Purchase", {"property": prop.name,
            "supplier": supplier.name, "supplier_reference": reference}):
        frappe.throw(_("La factura del proveedor ya está registrada"))
    signature = {"property": prop.name, "supplier": supplier.name,
        "supplier_modified": str(supplier.modified), "reference": reference,
        "purchase_order": order.name if order else None,
        "order_modified": str(order.modified) if order else None,
        "lines": lines, "currency": currency, "rate": str(rate), "rate_record": rate_record,
        "payable": payable.name,
        "tax_account": tax_account.name if tax_account else None, "notes": notes.strip()}
    first = lines[0]
    return {"supplier": supplier.name, "supplier_name": supplier.party_name,
        "supplier_reference": reference, "product": first["product"],
        "purchase_order": order.name if order else None,
        "product_name": first["product_name"], "warehouse": first["warehouse"],
        "quantity": first["quantity"], "lines": lines,
        "invoice_currency": currency,
        "invoice_amount": _money(invoice_total), "recoverable_tax": _money(tax_total),
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_currency": prop.currency, "base_amount": _money(base_before),
        "base_cost": _money(cost), "base_tax": _money(tax_before),
        "inventory_account": first["inventory_account"], "payable_account": payable.name,
        "tax_account": tax_account.name if tax_account else None,
        "notes": notes.strip(), "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def receive_purchase(prop, data):
    if not isinstance(data, dict) or set(data) - {"supplier", "supplier_reference", "product",
            "warehouse", "quantity", "invoice_currency", "invoice_amount",
            "recoverable_tax", "payable_account", "tax_account", "notes", "lines",
            "purchase_order", "acceptance"}:
        frappe.throw(_("Revise la compra antes de registrar"))
    reviewed = purchase_quote(prop, {key: value for key, value in data.items()
                                    if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("Proveedor, cuentas, importes o cambio variaron; revise la compra"))
    doc = insert("HS PMS Purchase", prop, organization=prop.organization,
        supplier=reviewed["supplier"], supplier_reference=reviewed["supplier_reference"],
        purchase_order=reviewed["purchase_order"],
        product=reviewed["product"], warehouse=reviewed["warehouse"],
        quantity=reviewed["quantity"], invoice_currency=reviewed["invoice_currency"],
        invoice_amount=reviewed["invoice_amount"],
        recoverable_tax=reviewed["recoverable_tax"],
        exchange_rate=reviewed["exchange_rate"], rate_record=reviewed["rate_record"],
        base_amount=reviewed["base_amount"], base_cost=reviewed["base_cost"],
        base_tax=reviewed["base_tax"], payable_account=reviewed["payable_account"],
        inventory_account=reviewed["inventory_account"],
        tax_account=reviewed["tax_account"], business_date=prop.business_date,
        status="Posted", notes=reviewed["notes"],
        lines=[{key: line[key] for key in ("product", "warehouse", "order_line", "quantity",
            "invoice_currency", "base_currency",
            "invoice_amount", "recoverable_tax", "base_amount", "base_cost",
            "base_tax", "inventory_account")} for line in reviewed["lines"]])
    stocks = []
    for line in doc.lines:
        stock = receive(prop, product=line.product, warehouse=line.warehouse,
            quantity=line.quantity, value=line.base_cost,
            counter_account=doc.payable_account, counter_party=doc.supplier,
            source_doctype=doc.doctype, source_name=doc.name,
            purpose="Purchase Receipt", memo=doc.supplier_reference)
        frappe.db.set_value(line.doctype, line.name,
            "stock_movement", stock["movement"], update_modified=False)
        stocks.append(stock)
    tax_journal = None
    if Decimal(reviewed["base_tax"]) > 0:
        tax_journal = post(prop, source_doctype=doc.doctype, source_name=doc.name,
            purpose="Recoverable Tax", memo=doc.supplier_reference,
            lines=[{"account": doc.tax_account, "debit": doc.base_tax, "credit": 0},
                   {"account": doc.payable_account, "debit": 0,
                    "credit": doc.base_tax, "party": doc.supplier}])
    frappe.db.set_value(doc.doctype, doc.name, {
        "stock_movement": stocks[0]["movement"],
        "tax_journal": tax_journal.name if tax_journal else None}, update_modified=False)
    audit(prop, "pms_purchase_received", doc,
        details={"supplier": doc.supplier, "reference": doc.supplier_reference,
                 "purchase_order": doc.purchase_order,
                 "stock_movements": [row["movement"] for row in stocks],
                 "stock_journals": [row["journal"] for row in stocks],
                 "tax_journal": tax_journal.name if tax_journal else None})
    return {"purchase": doc.name, "stock_movement": stocks[0]["movement"],
        "stock_journal": stocks[0]["journal"],
        "stock_movements": [row["movement"] for row in stocks],
        "stock_journals": [row["journal"] for row in stocks],
        "tax_journal": tax_journal.name if tax_journal else None,
        "base_amount": reviewed["base_amount"], "currency": prop.currency}


def outstanding(prop, purchase_name):
    purchase = locked_doc("HS PMS Purchase", purchase_name)
    if purchase.property != prop.name or purchase.status not in ("Posted", "Cancelled"):
        frappe.throw(_("La compra pertenece a otro establecimiento"), frappe.PermissionError)
    if purchase.status == "Cancelled":
        return Decimal(0)
    paid = sum((Decimal(str(row.base_amount)) for row in current_all("HS Payment",
        filters={"property": prop.name, "pms_purchase": purchase.name,
                 "kind": "Supplier Payment", "status": "Posted"},
        fields=["base_amount"])), Decimal(0))
    returned = sum((Decimal(str(row.base_credit)) for row in current_all(
        "HS PMS Purchase Return", filters={"property": prop.name,
            "purchase": purchase.name, "status": "Posted"},
        fields=["base_credit"])), Decimal(0))
    from hospitality_suite.standalone_opening_supplier_credits import applied_to
    remaining = (Decimal(str(purchase.base_amount)) - paid - returned -
                 applied_to(prop, "Purchase", purchase.name))
    if paid > Decimal(str(purchase.base_amount)) or returned > Decimal(str(purchase.base_amount)):
        frappe.throw(_("La compra y sus devoluciones requieren conciliación"))
    return max(remaining, Decimal(0))


def payment_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"purchase", "method", "shift",
            "amount", "reference", "reason"}:
        frappe.throw(_("Revise el pago al proveedor"))
    purchase = locked_doc("HS PMS Purchase", data.get("purchase"))
    if purchase.property != prop.name or purchase.status != "Posted":
        frappe.throw(_("Seleccione una compra vigente del establecimiento"))
    remaining = outstanding(prop, purchase.name)
    if remaining <= 0:
        frappe.throw(_("La compra ya está pagada"))
    method = locked_doc("HS Payment Method", data.get("method"))
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de pago del establecimiento"))
    cash_account = account(prop, method.account)
    if (cash_account.account_currency != method.currency or
            not (cash_account.is_cash or cash_account.is_bank)):
        frappe.throw(_("El medio de pago no conserva una cuenta de Caja o banco válida"))
    payable = account(prop, purchase.payable_account)
    if payable.root_type != "Liability" or payable.account_currency != prop.currency:
        frappe.throw(_("La cuenta por pagar original ya no es válida"))
    try:
        value = amount(data.get("amount"))
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("El pago debe ser positivo"))
    rate, rate_record = latest_rate(prop, method.currency)
    base = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if base <= 0 or base > remaining:
        frappe.throw(_("El pago supera el saldo pendiente de la compra"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if shift.property != prop.name or shift.status != "Open" or shift.cashier != frappe.session.user:
            frappe.throw(_("Se requiere turno abierto propio para pagar en efectivo"), frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data.get("shift"):
        frappe.throw(_("El pago bancario no se asigna a un turno"))
    if value > Decimal(account_currency_balance(prop, cash_account.name)["balance"]):
        frappe.throw(_("Caja o banco no tiene saldo contable suficiente"))
    reference = _text(data.get("reference"), "la referencia del pago")
    reason = _text(data.get("reason"), "el motivo del pago", 500)
    if frappe.db.exists("HS Payment", {"property": prop.name, "kind": "Supplier Payment",
            "pms_purchase": purchase.name, "reference": reference, "status": "Posted"}):
        frappe.throw(_("La referencia del pago ya está aplicada a esta compra"))
    signature = {"property": prop.name, "purchase": purchase.name,
        "purchase_modified": str(purchase.modified), "remaining": _money(remaining),
        "method": method.name, "method_modified": str(method.modified),
        "shift": shift.name if shift else None, "currency": method.currency,
        "amount": str(value), "rate": str(rate), "rate_record": rate_record,
        "base": _money(base), "reference": reference, "reason": reason}
    return {"purchase": purchase.name, "supplier": purchase.supplier,
        "payable_account": payable.name, "cash_account": cash_account.name,
        "method": method.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "base_amount": _money(base), "base_currency": prop.currency,
        "outstanding_before": _money(remaining),
        "outstanding_after": _money(remaining - base),
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def pay_supplier(prop, data):
    if not isinstance(data, dict) or set(data) - {"purchase", "method", "shift",
            "amount", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise el pago al proveedor"))
    reviewed = payment_quote(prop, {key: value for key, value in data.items()
                                    if key != "acceptance"})
    if data.get("acceptance") != reviewed["acceptance"]:
        frappe.throw(_("El saldo, el medio o el cambio variaron; revise el pago"))
    payment = insert("HS Payment", prop, shift=reviewed["shift"], method=reviewed["method"],
        currency=reviewed["currency"], amount=reviewed["amount"],
        exchange_rate=reviewed["exchange_rate"], base_amount=reviewed["base_amount"],
        kind="Supplier Payment", status="Posted", reference=reviewed["reference"],
        reason=reviewed["reason"], pms_party=reviewed["supplier"],
        pms_counter_account=reviewed["payable_account"],
        pms_purchase=reviewed["purchase"])
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
        purpose="Supplier Payment", memo=reviewed["reason"],
        lines=[{"account": reviewed["payable_account"], "debit": reviewed["base_amount"],
                "credit": 0, "party": reviewed["supplier"]},
               {"account": reviewed["cash_account"], "debit": 0,
                "credit": reviewed["base_amount"],
                "account_currency": reviewed["currency"],
                "exchange_rate": reviewed["exchange_rate"],
                "debit_in_account_currency": 0,
                "credit_in_account_currency": reviewed["amount"]}])
    payment.pms_journal = journal.name
    payment.save()
    audit(prop, "pms_supplier_paid", payment, reason=reviewed["reason"],
        details={"purchase": reviewed["purchase"], "journal": journal.name,
                 "amount": reviewed["amount"], "currency": reviewed["currency"],
                 "base_amount": reviewed["base_amount"],
                 "rate_record": reviewed["rate_record"]})
    return {"payment": payment.name, "journal": journal.name,
        "purchase": reviewed["purchase"],
        "base_amount": reviewed["base_amount"], "currency": reviewed["currency"],
        "outstanding": reviewed["outstanding_after"]}


def snapshot(property_name, compact=0):
    prop = require(property_name, "finance")
    require_pms(prop)
    if str(compact) not in ("0", "1"):
        frappe.throw(_("Revise el formato de la consulta de compras"))
    suppliers = frappe.get_all("HS Party", filters={"property": prop.name,
        "organization": prop.organization, "active": 1,
        "party_type": ["in", ["Supplier", "Both"]]},
        fields=["name", "party_name", "tax_id"], order_by="party_name asc",
        limit_page_length=500)
    products = frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "active": 1, "product_type": "Stock"},
        fields=["name", "product_code", "product_name"],
        order_by="product_name asc", limit_page_length=500)
    warehouses = frappe.get_all("HS Warehouse", filters={"property": prop.name,
        "organization": prop.organization, "active": 1},
        fields=["name", "warehouse_name"], order_by="warehouse_name asc")
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "active": 1, "is_group": 0,
        "account_currency": prop.currency},
        fields=["name", "account_code", "account_name", "root_type", "account_type"],
        order_by="account_code asc")
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name},
        fields=["name", "mode_of_payment", "currency", "is_cash"],
        order_by="mode_of_payment asc")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
        "cashier": frappe.session.user, "status": "Open"},
        fields=["name", "opened_at"], order_by="opened_at desc")
    catalogs = {"currency": prop.currency, "currencies": sorted(enabled_currencies(prop)),
        "suppliers": suppliers, "products": products,
        "warehouses": warehouses, "accounts": accounts, "methods": methods,
        "shifts": shifts}
    if str(compact) == "1":
        return catalogs
    purchases = frappe.get_all("HS PMS Purchase", filters={"property": prop.name},
        fields=["name", "supplier", "supplier_reference", "purchase_order", "product", "warehouse",
                "quantity", "invoice_currency", "invoice_amount", "recoverable_tax",
                "base_amount", "base_cost", "base_tax", "business_date",
                "payable_account", "stock_movement", "status", "cancellation_return"],
        order_by="creation desc", limit_page_length=200)
    stored_lines = frappe.get_all("HS PMS Purchase Line",
        filters={"parenttype": "HS PMS Purchase", "parent": ["in", [row.name for row in purchases]]},
        fields=["parent", "idx", "product", "warehouse", "order_line", "quantity", "invoice_amount",
                "invoice_currency", "base_currency", "recoverable_tax",
                "base_amount", "base_cost", "base_tax",
                "inventory_account", "stock_movement"],
        order_by="parent asc, idx asc", limit_page_length=10000) if purchases else []
    by_purchase = {}
    for line in stored_lines:
        by_purchase.setdefault(line.parent, []).append(line)
    for purchase in purchases:
        purchase["outstanding"] = _money(outstanding(prop, purchase.name))
        purchase["lines"] = by_purchase.get(purchase.name) or [{key: purchase.get(key) for key in
            ("product", "warehouse", "quantity", "invoice_amount", "recoverable_tax",
             "base_amount", "base_cost", "base_tax", "inventory_account", "stock_movement")}]
    payments = frappe.get_all("HS Payment", filters={"property": prop.name,
        "kind": ["in", ["Supplier Payment", "Supplier Refund"]],
        "pms_purchase": ["is", "set"], "status": "Posted"},
        fields=["name", "kind", "pms_purchase", "pms_purchase_return",
                "pms_opening_payable", "pms_opening_supplier_credit",
                "amount", "currency", "base_amount",
                "method", "reference", "business_date", "creation"],
        order_by="creation desc", limit_page_length=200)
    opening_payments = frappe.get_all("HS Payment", filters={"property": prop.name,
        "kind": "Supplier Payment", "pms_opening_payable": ["is", "set"],
        "status": "Posted", "pms_journal": ["is", "set"]},
        fields=["name", "kind", "pms_purchase", "pms_purchase_return",
                "pms_opening_payable", "pms_opening_supplier_credit",
                "amount", "currency", "base_amount",
                "pms_settlement_currency", "pms_settled_amount",
                "pms_released_base_amount", "pms_exchange_variance_account",
                "method", "reference", "business_date", "creation"],
        order_by="creation desc", limit_page_length=200)
    payments.extend(opening_payments)
    opening_refunds = frappe.get_all("HS Payment", filters={"property": prop.name,
        "kind": "Supplier Refund", "pms_opening_supplier_credit": ["is", "set"],
        "status": "Posted"},
        fields=["name", "kind", "pms_purchase", "pms_purchase_return",
                "pms_opening_payable", "pms_opening_supplier_credit",
                "amount", "currency", "base_amount", "method", "reference",
                "business_date", "creation"], order_by="creation desc", limit_page_length=200)
    payments.extend(opening_refunds)
    payments.sort(key=lambda row: str(row.get("creation") or ""), reverse=True)
    for row in payments:
        row.pop("creation", None)
    from hospitality_suite.standalone_opening_payables import snapshot as opening_snapshot
    from hospitality_suite.standalone_opening_supplier_credits import snapshot as supplier_credit_snapshot
    from hospitality_suite.standalone_purchase_returns import snapshot as return_snapshot
    from hospitality_suite.standalone_purchase_orders import snapshot as order_snapshot
    return {**catalogs, "purchases": purchases, "opening_payables": opening_snapshot(prop),
        "opening_supplier_credits": supplier_credit_snapshot(prop),
        "payments": payments[:200],
        "returns": return_snapshot(prop), "orders": order_snapshot(prop)}
