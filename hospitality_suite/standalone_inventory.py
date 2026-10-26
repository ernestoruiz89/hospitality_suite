"""Atomic stock and valuation movements backed by the PMS general ledger."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _

from hospitality_suite import standalone_accounting
from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, insert
from hospitality_suite.stock_rules import StockValidationError, issue, quantity, receipt


def _master(prop, doctype, name, *, require_active=True):
    row = frappe.db.get_value(doctype, name, ["name", "property", "organization", "active"], as_dict=True)
    if not row or (row.property, row.organization) != (prop.name, prop.organization):
        frappe.throw(_("El producto o almacén no pertenece al establecimiento"), frappe.PermissionError)
    if require_active and not row.active:
        frappe.throw(_("Seleccione un producto y almacén activos"))
    return frappe.get_doc(doctype, name)


def current_balance(prop, product_name, warehouse_name):
    standalone_accounting.require_pms(prop)
    _master(prop, "HS Product", product_name, require_active=False)
    _master(prop, "HS Warehouse", warehouse_name, require_active=False)
    rows = frappe.db.sql(
        "SELECT quantity_delta, value_delta FROM `tabHS Stock Movement` "
        "WHERE property=%s AND product=%s AND warehouse=%s FOR UPDATE",
        (prop.name, product_name, warehouse_name), as_list=True)
    qty = sum((Decimal(str(row[0])) for row in rows), Decimal(0))
    value = sum((Decimal(str(row[1])) for row in rows), Decimal(0))
    if qty < 0 or value < 0 or (qty == 0 and value != 0):
        frappe.throw(_("El saldo de inventario requiere conciliación"))
    return qty, value


def _record(prop, *, product, warehouse, direction, quantity, value=None,
            counter_account, source_doctype, source_name, purpose, memo=None,
            inventory_account_name=None, historical_return=False, counter_party=None,
            allow_inactive=False):
    standalone_accounting.require_pms(prop)
    if direction not in ("Receipt", "Issue"):
        frappe.throw(_("Dirección de inventario inválida"))
    if not getattr(frappe.local, "hs_operation", False):
        frappe.throw(_("El movimiento requiere una operación transaccional de Suite"))
    if historical_return and (direction != "Receipt" or not inventory_account_name):
        frappe.throw(_("La devolución histórica requiere la cuenta de inventario original"))
    if allow_inactive and (direction != "Issue" or source_doctype != "HS PMS Purchase Return"
                           or not inventory_account_name):
        frappe.throw(_("Solo una devolución al proveedor puede sacar inventario inactivo"))
    item = _master(prop, "HS Product", product,
                   require_active=not (historical_return or allow_inactive))
    _master(prop, "HS Warehouse", warehouse,
            require_active=not (historical_return or allow_inactive))
    if (item.product_type != "Stock" and not historical_return) or not (inventory_account_name or item.inventory_account):
        frappe.throw(_("El producto debe controlar existencias y tener cuenta de inventario"))
    frozen_return = historical_return and getattr(
        frappe.local, "hs_historical_maintenance_return", False)
    inventory_account = standalone_accounting.account(
        prop, inventory_account_name or item.inventory_account,
        allow_inactive=frozen_return)
    counterpart = standalone_accounting.account(prop, counter_account,
        allow_inactive=frozen_return)
    if inventory_account.root_type != "Asset" or counterpart.name == inventory_account.name:
        frappe.throw(_("Configure una cuenta de inventario y una contrapartida distintas"))
    if not all(isinstance(v, str) and v.strip() for v in (source_doctype, source_name, purpose)):
        frappe.throw(_("Identifique el documento de origen del movimiento"))
    if frappe.db.exists("HS Stock Movement", {"property": prop.name, "product": product,
        "warehouse": warehouse, "source_doctype": source_doctype, "source_name": source_name,
        "purpose": purpose}):
        frappe.throw(_("Este origen ya tiene un movimiento de inventario"))
    before_qty, before_value = current_balance(prop, product, warehouse)
    try:
        movement = (receipt(before_qty, before_value, quantity, value) if direction == "Receipt"
                    else issue(before_qty, before_value, quantity))
    except StockValidationError as exc:
        frappe.throw(str(exc))
    posting_value = abs(Decimal(movement["value_delta"]))
    if posting_value <= 0:
        frappe.throw(_("La salida sin costo requiere conciliación antes de contabilizar"))
    # Reception staff may fulfill a service without receiving direct write access
    # to the stock ledger. The operation guard above and product scope remain mandatory.
    doc = frappe.get_doc(dict(doctype="HS Stock Movement", company=prop.company,
        property=prop.name, organization=prop.organization, product=product,
        warehouse=warehouse, direction=direction, business_date=prop.business_date,
        source_doctype=source_doctype, source_name=source_name, purpose=purpose,
        memo=memo, **movement)).insert(ignore_permissions=True)
    lines = ([{"account": inventory_account.name, "debit": str(posting_value), "credit": 0},
              {"account": counterpart.name, "debit": 0, "credit": str(posting_value),
               "party": counter_party}]
             if direction == "Receipt" else
             [{"account": counterpart.name, "debit": str(posting_value), "credit": 0,
               "party": counter_party},
              {"account": inventory_account.name, "debit": 0, "credit": str(posting_value)}])
    journal = standalone_accounting.post(prop, source_doctype="HS Stock Movement",
        source_name=doc.name, purpose=direction, lines=lines, memo=memo)
    frappe.db.set_value("HS Stock Movement", doc.name, "journal", journal.name, update_modified=False)
    audit(prop, "pms_stock_" + direction.lower(), doc,
          details={"product": product, "warehouse": warehouse, "quantity": movement["quantity_delta"],
                   "value": movement["value_delta"], "journal": journal.name})
    return {"movement": doc.name, "journal": journal.name, **movement}


def receive(prop, **values):
    return _record(prop, direction="Receipt", **values)


def consume(prop, **values):
    return _record(prop, direction="Issue", **values)


def create_warehouse(prop, data):
    standalone_accounting.require_pms(prop)
    require(prop.name, "setup")
    if not isinstance(data, dict) or set(data) != {"warehouse_code", "warehouse_name"}:
        frappe.throw(_("Revise los datos del almacén"))
    code, name = data["warehouse_code"], data["warehouse_name"]
    if (not isinstance(code, str) or not code.strip() or len(code.strip()) > 40 or
            not isinstance(name, str) or not name.strip() or len(name.strip()) > 140):
        frappe.throw(_("Indique código y nombre válidos para el almacén"))
    doc = insert("HS Warehouse", prop, organization=prop.organization,
        warehouse_code=code.strip(), warehouse_name=name.strip(), active=1)
    audit(prop, "pms_warehouse_created", doc)
    return {"warehouse": doc.name}


def opening_stock(prop, data):
    """Seed physical stock against equity before regular purchasing is installed."""
    standalone_accounting.require_pms(prop)
    require(prop.name, "inventory")
    if not isinstance(data, dict) or set(data) != {
            "product", "warehouse", "quantity", "value", "equity_account", "reference"}:
        frappe.throw(_("Revise el saldo inicial de inventario"))
    reference = data["reference"]
    if not isinstance(reference, str) or not reference.strip() or len(reference.strip()) > 140:
        frappe.throw(_("Indique una referencia única del conteo inicial"))
    equity = standalone_accounting.account(prop, data["equity_account"])
    if equity.root_type != "Equity" or equity.account_currency != prop.currency:
        frappe.throw(_("El saldo inicial requiere una cuenta de patrimonio en moneda base"))
    if frappe.db.exists("HS Stock Movement", {"property": prop.name,
            "product": data["product"], "warehouse": data["warehouse"]}):
        frappe.throw(_("El producto ya tiene movimientos en este almacén; use una recepción o ajuste posterior"))
    return receive(prop, product=data["product"], warehouse=data["warehouse"],
        quantity=data["quantity"], value=data["value"], counter_account=equity.name,
        source_doctype="PMS Opening Stock", source_name=reference.strip(),
        purpose="Opening Stock", memo="Conteo inicial " + reference.strip())


def _text(value, label, maximum=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, maximum))
    return value.strip()


def transfer_stock(prop, data):
    standalone_accounting.require_pms(prop)
    require(prop.name, "inventory")
    return transfer_between(prop, data)


def transfer_between(prop, data):
    """Post both legs of a scoped transfer inside the caller's Suite transaction."""
    standalone_accounting.require_pms(prop)
    fields = {"product", "source_warehouse", "target_warehouse", "quantity",
              "clearing_account", "reference", "reason"}
    if not isinstance(data, dict) or set(data) != fields:
        frappe.throw(_("Revise los datos del traslado"))
    product = _master(prop, "HS Product", data["product"])
    source = _master(prop, "HS Warehouse", data["source_warehouse"])
    target = _master(prop, "HS Warehouse", data["target_warehouse"])
    if product.product_type != "Stock" or source.name == target.name:
        frappe.throw(_("Seleccione un producto de inventario y almacenes distintos"))
    inventory = standalone_accounting.account(prop, product.inventory_account)
    clearing = standalone_accounting.account(prop, data["clearing_account"])
    if (inventory.root_type != "Asset" or inventory.account_currency != prop.currency or
            clearing.root_type != "Asset" or clearing.account_currency != prop.currency or
            clearing.name == inventory.name or clearing.is_cash or clearing.is_bank or
            clearing.account_type != "Temporary"):
        frappe.throw(_("Use una cuenta temporal de activo en moneda base para el traslado"))
    reference = _text(data["reference"], "la referencia del traslado")
    reason = _text(data["reason"], "el motivo del traslado", 500)
    try:
        qty = quantity(data["quantity"])
        source_qty, source_value = current_balance(prop, product.name, source.name)
        calculated = issue(source_qty, source_value, qty)
    except StockValidationError as exc:
        frappe.throw(str(exc))
    value = -Decimal(calculated["value_delta"])
    doc = insert("HS Stock Transfer", prop, organization=prop.organization,
        product=product.name, source_warehouse=source.name, target_warehouse=target.name,
        quantity=str(qty), value=str(value), clearing_account=clearing.name,
        reference=reference, reason=reason, business_date=prop.business_date, status="Posted")
    issued = consume(prop, product=product.name, warehouse=source.name,
        quantity=str(qty), counter_account=clearing.name,
        source_doctype=doc.doctype, source_name=doc.name,
        purpose="Transfer Out", memo=reason)
    if -Decimal(issued["value_delta"]) != value:
        frappe.throw(_("El costo del traslado cambió; repita la operación"))
    received = receive(prop, product=product.name, warehouse=target.name,
        quantity=str(qty), value=str(value), counter_account=clearing.name,
        source_doctype=doc.doctype, source_name=doc.name,
        purpose="Transfer In", memo=reason)
    frappe.db.set_value(doc.doctype, doc.name, {"source_movement": issued["movement"],
        "target_movement": received["movement"]}, update_modified=False)
    audit(prop, "pms_stock_transfer", doc, reason=reason,
        details={"source_movement": issued["movement"],
                 "target_movement": received["movement"], "cost": str(value)})
    return {"transfer": doc.name, "source_movement": issued["movement"],
        "target_movement": received["movement"], "quantity": str(qty),
        "value": str(value), "source_balance": issued["balance_quantity"],
        "target_balance": received["balance_quantity"]}


def _count_quantity(value):
    if isinstance(value, bool):
        frappe.throw(_("El conteo debe ser una cantidad no negativa"))
    try:
        counted = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        frappe.throw(_("El conteo debe ser numérico"))
    if (not counted.is_finite() or counted < 0 or counted >= Decimal("1000000000") or
            counted != counted.quantize(Decimal("0.000001"))):
        frappe.throw(_("El conteo debe ser no negativo y tener hasta seis decimales"))
    return counted


def count_stock(prop, data):
    standalone_accounting.require_pms(prop)
    require(prop.name, "approve")
    if frappe.db.exists("HS Daily Close", {"property": prop.name,
            "business_date": prop.business_date, "status": "Closed"}):
        frappe.throw(_("La fecha operativa ya está cerrada"))
    fields = {"product", "warehouse", "counted_quantity", "adjustment_account",
              "value", "reference", "reason"}
    if not isinstance(data, dict) or set(data) - fields or not {"product", "warehouse",
            "counted_quantity", "reference", "reason"}.issubset(data):
        frappe.throw(_("Revise el conteo de inventario"))
    product = _master(prop, "HS Product", data["product"])
    warehouse = _master(prop, "HS Warehouse", data["warehouse"])
    if product.product_type != "Stock":
        frappe.throw(_("El conteo requiere un producto de inventario"))
    reference = _text(data["reference"], "la referencia del conteo")
    reason = _text(data["reason"], "el motivo del conteo", 500)
    counted = _count_quantity(data["counted_quantity"])
    expected, expected_value = current_balance(prop, product.name, warehouse.name)
    difference = counted - expected
    account_name = data.get("adjustment_account") or None
    supplied_value = data.get("value")
    movement_result = None
    if difference < 0:
        if supplied_value not in (None, ""):
            frappe.throw(_("Un faltante usa el costo promedio; no indique valor"))
        account_name = account_name or product.expense_account
        selected = standalone_accounting.account(prop, account_name)
        if selected.root_type != "Expense" or selected.account_currency != prop.currency:
            frappe.throw(_("El faltante requiere una cuenta de gasto en moneda base"))
        try:
            calculated = issue(expected, expected_value, -difference)
        except StockValidationError as exc:
            frappe.throw(str(exc))
        adjustment_value = Decimal(calculated["value_delta"])
    elif difference > 0:
        selected = standalone_accounting.account(prop, account_name)
        if selected.root_type != "Income" or selected.account_currency != prop.currency:
            frappe.throw(_("El sobrante requiere una cuenta de ingreso en moneda base"))
        if expected:
            if supplied_value not in (None, ""):
                frappe.throw(_("El sobrante con existencias conserva el costo promedio; no indique valor"))
            adjustment_value = (expected_value * difference / expected).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            try:
                adjustment_value = amount(supplied_value)
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
        if adjustment_value <= 0:
            frappe.throw(_("El sobrante requiere un costo positivo"))
    else:
        if account_name or supplied_value not in (None, ""):
            frappe.throw(_("Un conteo sin diferencia no requiere cuenta ni valor"))
        adjustment_value = Decimal(0)
    doc = insert("HS Stock Count", prop, organization=prop.organization,
        product=product.name, warehouse=warehouse.name,
        expected_quantity=str(expected), counted_quantity=str(counted),
        difference_quantity=str(difference), expected_value=str(expected_value),
        adjustment_value=str(adjustment_value), adjustment_account=account_name,
        reference=reference, reason=reason, approved_by=frappe.session.user,
        business_date=prop.business_date, status="Completed")
    if difference < 0:
        movement_result = consume(prop, product=product.name, warehouse=warehouse.name,
            quantity=str(-difference), counter_account=account_name,
            source_doctype=doc.doctype, source_name=doc.name,
            purpose="Count Shortage", memo=reason)
    elif difference > 0:
        movement_result = receive(prop, product=product.name, warehouse=warehouse.name,
            quantity=str(difference), value=str(adjustment_value),
            counter_account=account_name, source_doctype=doc.doctype,
            source_name=doc.name, purpose="Count Overage", memo=reason)
    if movement_result:
        if Decimal(movement_result["value_delta"]) != adjustment_value:
            frappe.throw(_("El valor del conteo cambió; repita la operación"))
        frappe.db.set_value(doc.doctype, doc.name, "movement",
            movement_result["movement"], update_modified=False)
    audit(prop, "pms_stock_count", doc, reason=reason,
        details={"expected": str(expected), "counted": str(counted),
                 "difference": str(difference), "value": str(adjustment_value),
                 "movement": movement_result["movement"] if movement_result else None})
    return {"count": doc.name, "expected": str(expected), "counted": str(counted),
        "difference": str(difference), "value": str(adjustment_value),
        "movement": movement_result["movement"] if movement_result else None,
        "journal": movement_result["journal"] if movement_result else None}


def snapshot(property_name):
    prop = require(property_name, "inventory")
    standalone_accounting.require_pms(prop)
    products = frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "product_type": "Stock", "active": 1},
        fields=["name", "product_code", "product_name", "inventory_account", "expense_account"],
        order_by="product_name asc", limit_page_length=500)
    warehouses = frappe.get_all("HS Warehouse", filters={"property": prop.name,
        "organization": prop.organization, "active": 1},
        fields=["name", "warehouse_code", "warehouse_name"], order_by="warehouse_name asc")
    balances = frappe.db.sql(
        "SELECT product, warehouse, SUM(quantity_delta) AS quantity, "
        "SUM(value_delta) AS value FROM `tabHS Stock Movement` "
        "WHERE property=%s GROUP BY product, warehouse",
        (prop.name,), as_dict=True)
    movements = frappe.get_all("HS Stock Movement", filters={"property": prop.name},
        fields=["name", "product", "warehouse", "direction", "quantity_delta", "value_delta",
                "purpose", "business_date", "source_name"],
        order_by="creation desc", limit_page_length=100)
    equity = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Equity", "is_group": 0,
        "active": 1, "account_currency": prop.currency},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    clearing = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Asset", "is_group": 0,
        "active": 1, "account_currency": prop.currency, "is_cash": 0, "is_bank": 0,
        "account_type": "Temporary"},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    expense = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Expense", "is_group": 0,
        "active": 1, "account_currency": prop.currency},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    income = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Income", "is_group": 0,
        "active": 1, "account_currency": prop.currency},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    transfers = frappe.get_all("HS Stock Transfer", filters={"property": prop.name},
        fields=["name", "product", "source_warehouse", "target_warehouse", "quantity",
                "value", "reference", "business_date"],
        order_by="creation desc", limit_page_length=50)
    counts = frappe.get_all("HS Stock Count", filters={"property": prop.name},
        fields=["name", "product", "warehouse", "expected_quantity", "counted_quantity",
                "difference_quantity", "adjustment_value", "reference", "business_date"],
        order_by="creation desc", limit_page_length=50)
    return {"currency": prop.currency, "products": products, "warehouses": warehouses,
            "balances": balances, "movements": movements, "equity_accounts": equity,
            "clearing_accounts": clearing, "expense_accounts": expense,
            "income_accounts": income, "transfers": transfers, "counts": counts}
