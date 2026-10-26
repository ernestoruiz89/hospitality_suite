"""Approved PMS purchase orders and their outstanding quantities.

An order carries no ledger entry. Every receipt creates its own purchase and payable.
"""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, assert_version, canonical, insert, locked_doc
from hospitality_suite.standalone_accounting import account, require_pms
from hospitality_suite.standalone_currency import enabled
from hospitality_suite.stock_rules import StockValidationError, quantity


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _text(value, label, maximum=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, maximum))
    return value.strip()


def progress(prop, order_line):
    """Net ordered quantity after posted returns, including partial returns."""
    lock = " FOR UPDATE" if getattr(frappe.local, "hs_operation", False) else ""
    receipts = frappe.db.sql(
        "SELECT l.quantity, l.stock_movement FROM `tabHS PMS Purchase Line` l "
        "JOIN `tabHS PMS Purchase` p ON p.name=l.parent "
        "WHERE p.property=%s AND p.organization=%s AND p.status='Posted' "
        "AND l.order_line=%s" + lock,
        (prop.name, prop.organization, order_line), as_dict=True)
    received = sum((Decimal(str(row.quantity)) for row in receipts), Decimal(0))
    movements = [row.stock_movement for row in receipts if row.stock_movement]
    returned = Decimal(0)
    if movements:
        rows = frappe.db.sql(
            "SELECT l.quantity FROM `tabHS PMS Purchase Return Line` l "
            "JOIN `tabHS PMS Purchase Return` r ON r.name=l.parent "
            "WHERE r.property=%s AND r.organization=%s AND r.status='Posted' "
            "AND l.source_movement IN (" + ",".join(["%s"] * len(movements)) + ")" + lock,
            (prop.name, prop.organization, *movements), as_dict=True)
        returned = sum((Decimal(str(row.quantity)) for row in rows), Decimal(0))
    if returned > received:
        frappe.throw(_("Las devoluciones superan lo recibido de la orden"))
    return received - returned


def allocation(line, before, requested):
    """Price/tax of the next slice; the final slice absorbs cent rounding."""
    ordered = Decimal(str(line.quantity))
    after = before + requested
    if before < 0 or requested <= 0 or after > ordered:
        frappe.throw(_("La recepción supera la cantidad pendiente de la orden"))
    value = Decimal(str(line.amount))
    tax = Decimal(str(line.recoverable_tax or 0))
    def cumulative(total, qty):
        return (total * qty / ordered).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return cumulative(value, after) - cumulative(value, before), \
        cumulative(tax, after) - cumulative(tax, before)


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "inventory")
    if (not isinstance(data, dict) or set(data) - {"supplier", "reference", "currency",
            "payable_account", "tax_account", "expected_date", "notes", "lines"}):
        frappe.throw(_("Revise la orden de compra"))
    supplier = locked_doc("HS Party", data.get("supplier"))
    if (supplier.property != prop.name or supplier.organization != prop.organization or
            supplier.party_type not in ("Supplier", "Both") or not supplier.active):
        frappe.throw(_("Seleccione un proveedor activo del establecimiento"))
    currency = data.get("currency")
    if not enabled(prop, currency):
        frappe.throw(_("La moneda de la orden no está habilitada"))
    payable = account(prop, data.get("payable_account"))
    if (payable.root_type != "Liability" or payable.account_type != "Payable" or
            payable.account_currency != prop.currency):
        frappe.throw(_("Seleccione una cuenta por pagar en moneda base"))
    supplied = data.get("lines")
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 50:
        frappe.throw(_("La orden requiere de una a cincuenta líneas"))
    lines, seen = [], set()
    total = tax_total = Decimal(0)
    for row in supplied:
        if (not isinstance(row, dict) or set(row) !=
                {"product", "warehouse", "quantity", "amount", "recoverable_tax"}):
            frappe.throw(_("Revise cada línea de la orden"))
        product = locked_doc("HS Product", row["product"])
        warehouse = locked_doc("HS Warehouse", row["warehouse"])
        pair = (product.name, warehouse.name)
        if (pair in seen or product.property != prop.name or
                product.organization != prop.organization or not product.active or
                product.product_type != "Stock" or warehouse.property != prop.name or
                warehouse.organization != prop.organization or not warehouse.active):
            frappe.throw(_("Cada línea requiere producto y almacén activos y únicos"))
        seen.add(pair)
        inventory = account(prop, product.inventory_account)
        if inventory.root_type != "Asset" or inventory.account_currency != prop.currency:
            frappe.throw(_("Cada producto requiere cuenta de inventario en moneda base"))
        try:
            qty = quantity(row["quantity"])
            value = amount(row["amount"])
            tax = amount(row["recoverable_tax"])
        except (LedgerValidationError, StockValidationError) as exc:
            frappe.throw(str(exc))
        if value <= 0 or tax >= value:
            frappe.throw(_("Cada línea requiere importe positivo e impuesto menor que el total"))
        total += value
        tax_total += tax
        lines.append({"product": product.name, "product_name": product.product_name,
            "product_modified": str(product.modified), "warehouse": warehouse.name,
            "warehouse_modified": str(warehouse.modified), "quantity": str(qty),
            "currency": currency, "amount": _money(value),
            "recoverable_tax": _money(tax), "inventory_account": inventory.name})
    tax_account = None
    if tax_total:
        tax_account = account(prop, data.get("tax_account"))
        if (tax_account.root_type != "Asset" or tax_account.account_type != "Tax" or
                tax_account.account_currency != prop.currency or
                tax_account.name in {row["inventory_account"] for row in lines}):
            frappe.throw(_("Seleccione otra cuenta de activo para el impuesto recuperable"))
    elif data.get("tax_account"):
        frappe.throw(_("No indique cuenta tributaria si la orden no tiene impuesto"))
    reference = _text(data.get("reference"), "la referencia de orden")
    if frappe.db.exists("HS PMS Purchase Order", {"property": prop.name, "reference": reference}):
        frappe.throw(_("La referencia de orden ya existe en este establecimiento"))
    expected_date = data.get("expected_date") or None
    if expected_date:
        try:
            expected_date = str(frappe.utils.getdate(expected_date))
        except Exception:
            frappe.throw(_("La fecha esperada no es válida"))
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes.strip()) > 500:
        frappe.throw(_("Las observaciones son demasiado largas"))
    result = {"supplier": supplier.name, "supplier_name": supplier.party_name,
        "reference": reference, "currency": currency, "payable_account": payable.name,
        "tax_account": tax_account.name if tax_account else None,
        "amount": _money(total), "recoverable_tax": _money(tax_total),
        "expected_date": expected_date, "notes": notes.strip(), "lines": lines}
    signature = {"property": prop.name, "supplier_modified": str(supplier.modified), **result}
    return {**result, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def request(prop, data):
    if not isinstance(data, dict) or set(data) - {"supplier", "reference", "currency",
            "payable_account", "tax_account", "expected_date", "notes", "lines", "acceptance"}:
        frappe.throw(_("Revise la orden antes de solicitarla"))
    reviewed = quote(prop, {key: value for key, value in data.items() if key != "acceptance"})
    if reviewed["acceptance"] != data.get("acceptance"):
        frappe.throw(_("La orden cambió; revísela nuevamente"))
    doc = insert("HS PMS Purchase Order", prop, organization=prop.organization,
        supplier=reviewed["supplier"], reference=reviewed["reference"],
        currency=reviewed["currency"], payable_account=reviewed["payable_account"],
        tax_account=reviewed["tax_account"], amount=reviewed["amount"],
        recoverable_tax=reviewed["recoverable_tax"], business_date=prop.business_date,
        expected_date=reviewed["expected_date"], notes=reviewed["notes"],
        requested_by=frappe.session.user, status="Pending",
        lines=[{key: line[key] for key in ("product", "warehouse", "quantity",
            "currency", "amount", "recoverable_tax", "inventory_account")}
            for line in reviewed["lines"]])
    audit(prop, "pms_purchase_order_requested", doc,
          details={"reference": doc.reference, "amount": str(doc.amount)})
    return {"order": doc.name, "status": doc.status, "modified": str(doc.modified)}


def approve(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {"order", "modified"}:
        frappe.throw(_("Revise la aprobación de la orden"))
    doc = locked_doc("HS PMS Purchase Order", data["order"])
    assert_version(doc, data["modified"])
    if (doc.property != prop.name or doc.organization != prop.organization or
            doc.status != "Pending" or doc.requested_by == frappe.session.user):
        frappe.throw(_("Otra persona de Gerencia debe aprobar una orden pendiente"))
    doc.status = "Approved"
    doc.approved_by = frappe.session.user
    doc.approved_at = now_datetime()
    doc.save()
    audit(prop, "pms_purchase_order_approved", doc)
    return {"order": doc.name, "status": doc.status, "modified": str(doc.modified)}


def close(prop, data):
    require_pms(prop)
    if not isinstance(data, dict) or set(data) != {"order", "modified", "reason"}:
        frappe.throw(_("Revise el cierre de la orden"))
    doc = locked_doc("HS PMS Purchase Order", data["order"])
    assert_version(doc, data["modified"])
    if doc.property != prop.name or doc.organization != prop.organization or doc.status not in ("Pending", "Approved"):
        frappe.throw(_("La orden no admite cierre"))
    if doc.status == "Approved":
        require(prop.name, "approve")
    elif doc.requested_by != frappe.session.user:
        require(prop.name, "approve")
    doc.close_reason = _text(data["reason"], "el motivo del cierre", 500)
    has_receipts = bool(frappe.db.exists("HS PMS Purchase", {"property": prop.name,
        "purchase_order": doc.name, "status": "Posted"}))
    doc.status = "Closed" if has_receipts else "Cancelled"
    doc.closed_at = now_datetime()
    doc.save()
    audit(prop, "pms_purchase_order_closed", doc, reason=doc.close_reason,
          details={"status": doc.status})
    return {"order": doc.name, "status": doc.status, "modified": str(doc.modified)}


def snapshot(prop):
    require_pms(prop)
    orders = frappe.get_all("HS PMS Purchase Order", filters={"property": prop.name,
        "organization": prop.organization},
        fields=["name", "supplier", "reference", "currency", "payable_account",
            "tax_account", "amount", "recoverable_tax", "expected_date", "notes",
            "requested_by", "approved_by", "status", "modified", "business_date",
            "close_reason"], order_by="creation desc", limit_page_length=200)
    return _decorate(prop, orders)


def _decorate(prop, orders):
    for order in orders:
        order["modified"] = str(order.modified)
        doc = frappe.get_doc("HS PMS Purchase Order", order.name)
        order["lines"] = []
        total_qty = received_qty = Decimal(0)
        for line in doc.lines:
            received = progress(prop, line.name)
            ordered = Decimal(str(line.quantity))
            if received > ordered:
                frappe.throw(_("Las recepciones superan la orden"))
            total_qty += ordered
            received_qty += received
            order["lines"].append({"name": line.name, "product": line.product,
                "warehouse": line.warehouse, "quantity": str(ordered),
                "received_quantity": str(received),
                "remaining_quantity": str(ordered - received),
                "amount": _money(line.amount),
                "recoverable_tax": _money(line.recoverable_tax or 0)})
        order["received_quantity"] = str(received_qty)
        order["progress"] = ("Completed" if received_qty == total_qty else
            "Partially Received" if received_qty else order.status) if order.status == "Approved" else order.status
    product_ids = {line["product"] for order in orders for line in order["lines"]}
    labels = {row.name: row.product_name for row in frappe.get_all("HS Product",
        filters={"property": prop.name, "organization": prop.organization,
                 "name": ["in", list(product_ids)]},
        fields=["name", "product_name"], limit_page_length=len(product_ids))
        } if product_ids else {}
    for order in orders:
        for line in order["lines"]:
            line["product_name"] = labels.get(line["product"]) or line["product"]
    return orders


def page(property_name, search="", offset=0, page_length=25, receivable_only=0):
    prop = require(property_name, "finance")
    require_pms(prop)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Revise la paginación de órdenes"))
    if (offset < 0 or page_length < 1 or page_length > 100 or
            not isinstance(search, str) or len(search) > 100 or
            str(receivable_only) not in ("0", "1")):
        frappe.throw(_("Revise los filtros de órdenes"))
    term = search.strip()
    only_open = str(receivable_only) == "1"
    open_clause = (
        "AND o.status='Approved' AND EXISTS ("
        "SELECT 1 FROM `tabHS PMS Purchase Order Line` ol "
        "LEFT JOIN (SELECT pl.order_line,SUM(pl.quantity) AS qty "
        "FROM `tabHS PMS Purchase Line` pl "
        "JOIN `tabHS PMS Purchase` b ON b.name=pl.parent "
        "WHERE b.property=%s AND b.organization=%s AND b.status='Posted' "
        "GROUP BY pl.order_line) received ON received.order_line=ol.name "
        "LEFT JOIN (SELECT pl.order_line,SUM(rl.quantity) AS qty "
        "FROM `tabHS PMS Purchase Return Line` rl "
        "JOIN `tabHS PMS Purchase Return` r ON r.name=rl.parent "
        "JOIN `tabHS PMS Purchase Line` pl ON pl.stock_movement=rl.source_movement "
        "JOIN `tabHS PMS Purchase` b ON b.name=pl.parent "
        "WHERE r.property=%s AND r.organization=%s AND r.status='Posted' "
        "AND b.property=%s AND b.organization=%s AND b.status='Posted' "
        "GROUP BY pl.order_line) returned ON returned.order_line=ol.name "
        "WHERE ol.parent=o.name AND ol.quantity>"
        "COALESCE(received.qty,0)-COALESCE(returned.qty,0)) "
    ) if only_open else ""
    rows = frappe.db.sql(
        "SELECT o.name,o.supplier,p.party_name,o.reference,o.currency,o.payable_account,"
        "o.tax_account,o.amount,o.recoverable_tax,o.expected_date,o.notes,"
        "o.requested_by,o.approved_by,o.status,o.modified,o.business_date,"
        "o.close_reason "
        "FROM `tabHS PMS Purchase Order` o "
        "LEFT JOIN `tabHS Party` p ON p.name=o.supplier AND p.property=o.property "
        "WHERE o.property=%s AND o.organization=%s " + open_clause +
        "AND (%s='' OR LOCATE(%s,o.name)>0 OR LOCATE(%s,o.reference)>0 "
        "OR LOCATE(%s,p.party_name)>0) "
        "ORDER BY o.creation DESC,o.name DESC LIMIT %s OFFSET %s",
        (prop.name, prop.organization,
         *((prop.name, prop.organization, prop.name, prop.organization,
            prop.name, prop.organization) if only_open else ()),
         term, term, term, term, page_length + 1, offset), as_dict=True)
    return {"rows": _decorate(prop, rows[:page_length]), "search": term,
            "offset": offset, "has_more": len(rows) > page_length}
