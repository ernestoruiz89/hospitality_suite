"""Hotel-owned linen movements on the standalone PMS inventory ledger."""

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite import standalone_accounting, standalone_inventory
from hospitality_suite.security import property_document, require
from hospitality_suite.service import audit, insert
from hospitality_suite.stock_rules import StockValidationError, quantity
from hospitality_suite.time import local


FIELDS = ("pms_linen_operating_warehouse", "pms_linen_laundry_warehouse",
          "pms_linen_clearing_account")


def validate_configuration(prop):
    """Check saved PMS links, including edits outside the React setup form."""
    names = [prop.get(field) for field in FIELDS]
    old = prop.get_doc_before_save()
    if old and old.get("pms_linen_laundry_warehouse") and old.get(
            "pms_linen_laundry_warehouse") != names[1]:
        remaining = frappe.db.sql(
            "SELECT COALESCE(SUM(quantity_delta),0) FROM `tabHS Stock Movement` "
            "WHERE property=%s AND warehouse=%s",
            (prop.name, old.pms_linen_laundry_warehouse), as_list=True)[0][0]
        if Decimal(str(remaining)) != 0:
            frappe.throw(_("Traslade o ajuste la ropa del almacén anterior antes de cambiarlo"))
    if not any(names):
        return
    if not all(names):
        frappe.throw(_("Configure ambos almacenes de ropa y la cuenta temporal"))
    operating = standalone_inventory._master(prop, "HS Warehouse", names[0])
    laundry = standalone_inventory._master(prop, "HS Warehouse", names[1])
    if operating.name == laundry.name:
        frappe.throw(_("Use almacenes distintos para ropa operativa y lavandería"))
    clearing = standalone_accounting.account(prop, names[2])
    if (clearing.root_type != "Asset" or clearing.account_type != "Temporary" or
            clearing.account_currency != prop.currency or clearing.is_cash or
            clearing.is_bank):
        frappe.throw(_("Use una cuenta temporal de activo en moneda base para la ropa"))


def _configured(prop):
    if not all(prop.get(field) for field in FIELDS):
        frappe.throw(_("Configure almacenes de ropa y cuenta temporal en el establecimiento"))
    validate_configuration(prop)
    return (prop.pms_linen_operating_warehouse,
            prop.pms_linen_laundry_warehouse,
            prop.pms_linen_clearing_account)


def move(prop, data):
    standalone_accounting.require_pms(prop)
    require(prop.name, "clean")
    if not isinstance(data, dict) or set(data) - {"room", "item", "quantity",
                                               "direction", "reason"}:
        frappe.throw(_("Revise el movimiento de ropa"))
    room = property_document(prop, "HS Room", data.get("room"), "clean")
    direction = data.get("direction")
    if direction not in ("Send", "Receive", "Loss"):
        frappe.throw(_("Seleccione envío, recepción o pérdida"))
    reason = data.get("reason") or ""
    if not isinstance(reason, str) or len(reason.strip()) > 500 or (
            direction == "Loss" and not reason.strip()):
        frappe.throw(_("Indique un motivo válido para el movimiento de ropa"))
    try:
        qty = quantity(data.get("quantity"))
    except StockValidationError as exc:
        frappe.throw(str(exc))
    operating, laundry, clearing = _configured(prop)
    product = standalone_inventory._master(prop, "HS Product", data.get("item"))
    if product.product_type != "Stock" or not product.inventory_account:
        frappe.throw(_("Seleccione ropa de inventario con cuenta de existencias"))
    description = reason.strip() or {"Send": "Envío a lavandería",
        "Receive": "Recepción de lavandería"}[direction]
    record = insert("HS Incident", prop, room=room.name, kind="Linen",
        linen_direction=direction, description=description, item=product.name,
        quantity=str(qty), status="Resolved", resolution=description,
        resolved_by=frappe.session.user, resolved_at=now_datetime())
    if direction == "Loss":
        expense = standalone_accounting.account(prop, product.expense_account)
        if expense.root_type != "Expense" or expense.account_currency != prop.currency:
            frappe.throw(_("La pérdida requiere una cuenta de gasto en moneda base"))
        movement = standalone_inventory.consume(prop, product=product.name,
            warehouse=laundry, quantity=str(qty), counter_account=expense.name,
            source_doctype=record.doctype, source_name=record.name,
            purpose="Linen Loss", memo=description)
        reference = movement["movement"]
        value = -Decimal(str(movement["value_delta"]))
    else:
        source, target = ((operating, laundry) if direction == "Send"
                          else (laundry, operating))
        transfer = standalone_inventory.transfer_between(prop, {
            "product": product.name, "source_warehouse": source,
            "target_warehouse": target, "quantity": str(qty),
            "clearing_account": clearing, "reference": record.name,
            "reason": description})
        reference = transfer["transfer"]
        value = Decimal(transfer["value"])
    frappe.db.set_value(record.doctype, record.name, "stock_entry", reference,
                        update_modified=False)
    audit(prop, "Linen " + direction, record, reason.strip() or None,
          details={"stock_reference": reference, "quantity": str(qty),
                   "value": str(value)})
    return {"incident": record.name, "stock_entry": reference,
            "direction": direction, "quantity": str(qty), "value": str(value)}


def board(property_name, direction="Send", search="", offset=0,
          page_length=25, history_offset=0):
    prop = require(property_name, "clean")
    current_provider = standalone_accounting.provider()
    if direction not in ("Send", "Receive", "Loss"):
        frappe.throw(_("Seleccione un movimiento válido de ropa"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(_("Revise la búsqueda de ropa"))
    try:
        offset, page_length, history_offset = (int(offset), int(page_length),
                                               int(history_offset))
    except (ValueError, TypeError):
        frappe.throw(_("Revise la paginación de ropa"))
    if (offset < 0 or offset > 1000000 or history_offset < 0 or
            history_offset > 1000000 or not 1 <= page_length <= 50):
        frappe.throw(_("Revise la paginación de ropa"))
    if current_provider == "pms":
        standalone_accounting.require_pms(prop)
        operating = prop.get("pms_linen_operating_warehouse")
        laundry = prop.get("pms_linen_laundry_warehouse")
        configured = bool(all(prop.get(field) for field in FIELDS))
        if configured:
            validate_configuration(prop)
    else:
        operating, laundry = prop.warehouse, prop.laundry_warehouse
        configured = bool(operating and laundry and operating != laundry)
        if configured:
            for warehouse in (operating, laundry):
                row = frappe.db.get_value("Warehouse", warehouse,
                    ["company", "is_group", "disabled"], as_dict=True)
                if not row or row.company != prop.company or row.is_group or row.disabled:
                    configured = False
    stock_warehouse = operating if direction == "Send" else laundry
    products = []
    total = 0
    if configured:
        needle = "%" + search.strip() + "%"
        if current_provider == "pms":
            where = ("m.property=%s AND m.warehouse=%s AND "
                "p.property=%s AND p.organization=%s AND p.active=1 AND "
                "p.product_type='Stock' AND (p.name LIKE %s OR p.product_name LIKE %s)")
            args = [prop.name, stock_warehouse, prop.name, prop.organization,
                    needle, needle]
            core = (" FROM `tabHS Stock Movement` m JOIN `tabHS Product` p "
                    "ON p.name=m.product WHERE " + where +
                    " GROUP BY m.product HAVING SUM(m.quantity_delta)>0")
            total = len(frappe.db.sql("SELECT m.product" + core, args))
            products = frappe.db.sql(
                "SELECT p.name,p.product_name,SUM(m.quantity_delta) AS quantity,"
                "p.expense_account" + core +
                " ORDER BY p.product_name,p.name LIMIT %s OFFSET %s",
                [*args, page_length, offset], as_dict=True)
        else:
            args = [stock_warehouse, needle, needle]
            core = (" FROM `tabBin` b JOIN `tabItem` i ON i.name=b.item_code "
                    "WHERE b.warehouse=%s AND b.actual_qty>0 AND i.is_stock_item=1 "
                    "AND i.disabled=0 AND (i.name LIKE %s OR i.item_name LIKE %s)")
            total = frappe.db.sql("SELECT COUNT(*)" + core, args, as_list=True)[0][0]
            products = frappe.db.sql(
                "SELECT i.name,i.item_name AS product_name,b.actual_qty AS quantity" +
                core + " ORDER BY i.item_name,i.name LIMIT %s OFFSET %s",
                [*args, page_length, offset], as_dict=True)
    history_total = frappe.db.count("HS Incident", {"property": prop.name,
        "company": prop.company, "kind": "Linen"})
    history = frappe.get_all("HS Incident", filters={"property": prop.name,
        "company": prop.company, "kind": "Linen"},
        fields=["name", "room", "item", "quantity", "linen_direction",
                "description", "stock_entry", "creation"],
        order_by="creation desc,name desc", limit_start=history_offset,
        limit_page_length=25)
    for row in history:
        row["created_at"] = local(row.pop("creation"), prop).strftime("%Y-%m-%d %H:%M")
    return {"provider": current_provider, "configured": configured,
        "operating_warehouse": operating, "laundry_warehouse": laundry,
        "stock_warehouse": stock_warehouse if configured else None,
        "direction": direction, "products": products, "total": int(total),
        "offset": offset, "has_more": offset + len(products) < total,
        "history": history, "history_total": history_total,
        "history_offset": history_offset,
        "history_has_more": history_offset + len(history) < history_total}


def setup_options(property_name):
    prop = require(property_name, "setup")
    standalone_accounting.require_pms(prop)
    warehouses = frappe.get_all("HS Warehouse", filters={"property": prop.name,
        "organization": prop.organization, "active": 1},
        fields=["name", "warehouse_name"], order_by="warehouse_name asc")
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Asset",
        "account_type": "Temporary", "account_currency": prop.currency,
        "is_group": 0, "active": 1, "is_cash": 0, "is_bank": 0},
        fields=["name", "account_code", "account_name"], order_by="account_code asc")
    return {"warehouses": warehouses, "accounts": accounts}
