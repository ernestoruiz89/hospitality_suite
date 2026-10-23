"""Atomic stock and valuation movements backed by the PMS general ledger."""

from decimal import Decimal

import frappe
from frappe import _

from hospitality_suite import standalone_accounting
from hospitality_suite.service import audit, insert
from hospitality_suite.stock_rules import StockValidationError, issue, receipt


def _master(prop, doctype, name):
    row = frappe.db.get_value(doctype, name, ["name", "property", "organization", "active"], as_dict=True)
    if not row or (row.property, row.organization) != (prop.name, prop.organization):
        frappe.throw(_("El producto o almacén no pertenece al establecimiento"), frappe.PermissionError)
    if not row.active:
        frappe.throw(_("Seleccione un producto y almacén activos"))
    return frappe.get_doc(doctype, name)


def current_balance(prop, product_name, warehouse_name):
    standalone_accounting.require_pms(prop)
    _master(prop, "HS Product", product_name)
    _master(prop, "HS Warehouse", warehouse_name)
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
            counter_account, source_doctype, source_name, purpose, memo=None):
    standalone_accounting.require_pms(prop)
    if direction not in ("Receipt", "Issue"):
        frappe.throw(_("Dirección de inventario inválida"))
    if not getattr(frappe.local, "hs_operation", False):
        frappe.throw(_("El movimiento requiere una operación transaccional de Suite"))
    item = _master(prop, "HS Product", product)
    _master(prop, "HS Warehouse", warehouse)
    if item.product_type != "Stock" or not item.inventory_account:
        frappe.throw(_("El producto debe controlar existencias y tener cuenta de inventario"))
    inventory_account = standalone_accounting.account(prop, item.inventory_account)
    counterpart = standalone_accounting.account(prop, counter_account)
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
    doc = insert("HS Stock Movement", prop, organization=prop.organization, product=product,
        warehouse=warehouse, direction=direction, business_date=prop.business_date,
        source_doctype=source_doctype, source_name=source_name, purpose=purpose,
        memo=memo, **movement)
    lines = ([{"account": inventory_account.name, "debit": str(posting_value), "credit": 0},
              {"account": counterpart.name, "debit": 0, "credit": str(posting_value)}]
             if direction == "Receipt" else
             [{"account": counterpart.name, "debit": str(posting_value), "credit": 0},
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
