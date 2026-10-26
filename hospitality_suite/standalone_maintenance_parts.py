"""Maintenance parts issued from the PMS stock ledger and returned at original cost."""

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _

from hospitality_suite import standalone_accounting, standalone_inventory
from hospitality_suite.housekeeping import maintenance_owner
from hospitality_suite.security import ACTIONS, is_system, property_document, require
from hospitality_suite.service import assert_version, audit


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _return_one(prop, doc, part, reason):
    historical = bool(part.opening_stock_issue)
    if historical:
        try:
            issue = frappe.parse_json(part.opening_stock_issue)
            valid = (isinstance(issue, dict) and
                issue.get("voucher") == part.stock_entry and
                isinstance(issue.get("detail"), str) and issue["detail"] and
                Decimal(str(issue["quantity"])) == Decimal(str(part.quantity)) and
                Decimal(str(issue["cost"])) == Decimal(str(part.cost)) and
                issue.get("warehouse") and issue.get("expense_account") and
                issue.get("inventory_account") and
                issue["expense_account"] != issue["inventory_account"])
        except (InvalidOperation, TypeError, ValueError, KeyError):
            valid = False
        if not valid:
            frappe.throw(_("El repuesto histórico perdió su costo y cuentas originales"))
        product_name = part.item
        warehouse_name = issue["warehouse"]
        expense_account = issue["expense_account"]
        inventory_account = issue["inventory_account"]
        purpose = "Maintenance Return " + part.stock_entry + "/" + issue["detail"]
    else:
        issue = frappe.db.get_value("HS Stock Movement", part.stock_entry,
            ["property", "organization", "product", "warehouse", "direction",
             "source_doctype", "source_name", "purpose", "journal", "quantity_delta",
             "value_delta"], as_dict=True)
        if (not issue or issue.property != prop.name or issue.organization != prop.organization or
                issue.product != part.item or issue.direction != "Issue" or
                issue.source_doctype != doc.doctype or issue.source_name != doc.name or
                not issue.purpose.startswith("Maintenance Part ") or not issue.journal or
                frappe.db.get_value("HS Journal", issue.journal, "status") != "Posted" or
                -Decimal(str(issue.quantity_delta)) != Decimal(str(part.quantity)) or
                -Decimal(str(issue.value_delta)) != Decimal(str(part.cost))):
            frappe.throw(_("El repuesto no conserva una salida contable válida"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": issue.journal},
            fields=["account", "debit", "credit"], limit_page_length=3)
        debits = [row for row in lines if Decimal(str(row.debit)) > 0]
        credits = [row for row in lines if Decimal(str(row.credit)) > 0]
        if (len(lines) != 2 or len(debits) != 1 or len(credits) != 1 or
                Decimal(str(debits[0].debit)) != Decimal(str(part.cost)) or
                Decimal(str(credits[0].credit)) != Decimal(str(part.cost))):
            frappe.throw(_("El asiento original del repuesto requiere conciliación"))
        product_name = issue.product
        warehouse_name = issue.warehouse
        expense_account = debits[0].account
        inventory_account = credits[0].account
        purpose = "Maintenance Return " + part.stock_entry
    return standalone_inventory.receive(prop, product=product_name,
        warehouse=warehouse_name, quantity=str(part.quantity),
        value=_money(part.cost), counter_account=expense_account,
        inventory_account_name=inventory_account, historical_return=True,
        source_doctype=doc.doctype, source_name=doc.name,
        purpose=purpose, memo=reason)


def change(prop, data):
    standalone_accounting.require_pms(prop)
    require(prop.name, "maintain")
    if not isinstance(data, dict) or not data.get("order"):
        frappe.throw(_("Seleccione una orden de mantenimiento"))
    allowed = ({"order", "modified", "return_entry", "reason"} if data.get("return_entry")
        else {"order", "modified", "warehouse", "parts"})
    if set(data) - allowed:
        frappe.throw(_("Revise la operación de repuestos"))
    doc = property_document(prop, "HS Maintenance Order", data["order"], "maintain")
    assert_version(doc, data.get("modified"))
    maintenance_owner(prop, doc)
    if doc.status == "Completed":
        frappe.throw(_("La orden ya está cerrada"))
    if data.get("return_entry"):
        require(prop.name, "approve")
        if not isinstance(data.get("reason"), str) or not data["reason"].strip() or len(data["reason"].strip()) > 500:
            frappe.throw(_("Indique el motivo de devolución de repuestos"))
        matching = [part for part in doc.parts if part.stock_entry == data["return_entry"]
            and part.status == "Issued"]
        if len(matching) > 1:
            try:
                frozen = [frappe.parse_json(part.opening_stock_issue)
                    for part in matching]
                valid_group = (all(isinstance(issue, dict) and
                        issue.get("voucher") == data["return_entry"]
                        for issue in frozen) and
                    len({issue.get("detail") for issue in frozen}) ==
                        len(matching) and
                    all(int(issue["group_count"]) == len(matching)
                        for issue in frozen) and
                    all(Decimal(str(issue["voucher_total_cost"])) ==
                        sum((Decimal(str(part.cost)) for part in matching),
                            Decimal(0)) for issue in frozen))
            except (AttributeError, InvalidOperation, KeyError,
                    TypeError, ValueError):
                valid_group = False
            if not valid_group:
                frappe.throw(_("El grupo histórico de repuestos está incompleto"))
            before_return = getattr(frappe.local,
                "hs_historical_maintenance_return", False)
            frappe.local.hs_historical_maintenance_return = True
            try:
                returned = []
                for part in matching:
                    movement = _return_one(prop, doc, part,
                        data["reason"].strip())
                    part.status = "Returned"
                    returned.append(movement["movement"])
                doc.stock_entry = returned[-1]
                doc.cost = _money(sum((Decimal(str(part.cost))
                    for part in doc.parts if part.status == "Issued"),
                    Decimal(0)))
                doc.save(ignore_permissions=True)
            finally:
                frappe.local.hs_historical_maintenance_return = before_return
            audit(prop, "pms_maintenance_parts_return", doc,
                reason=data["reason"].strip(), details={
                    "issue": data["return_entry"], "returns": returned,
                    "value": _money(sum((Decimal(str(part.cost))
                        for part in matching), Decimal(0))),
                    "cost": str(doc.cost)})
            return {"order": doc.name, "stock_entry": doc.stock_entry,
                "movements": returned, "cost": str(doc.cost),
                "modified": str(doc.modified)}
        if len(matching) != 1:
            frappe.throw(_("La salida no pertenece a los repuestos pendientes de esta orden"))
        part = matching[0]
        historical = bool(part.opening_stock_issue)
        before_return = getattr(frappe.local, "hs_historical_maintenance_return", False)
        frappe.local.hs_historical_maintenance_return = historical
        try:
            returned = _return_one(prop, doc, part, data["reason"].strip())
            part.status = "Returned"
            doc.stock_entry = returned["movement"]
            doc.cost = _money(sum((Decimal(str(item.cost)) for item in doc.parts
                if item.status == "Issued"), Decimal(0)))
            doc.save(ignore_permissions=True)
        finally:
            frappe.local.hs_historical_maintenance_return = before_return
        action = "pms_maintenance_parts_return"
        details = {"issue": part.stock_entry,
            "return": returned["movement"], "value": _money(part.cost)}
    else:
        warehouse = frappe.db.get_value("HS Warehouse", data.get("warehouse"),
            ["property", "organization", "active"], as_dict=True)
        if (not warehouse or warehouse.property != prop.name or
                warehouse.organization != prop.organization or not warehouse.active):
            frappe.throw(_("Seleccione un almacén activo del establecimiento"), frappe.PermissionError)
        parts = data.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 50:
            frappe.throw(_("Seleccione de uno a cincuenta repuestos"))
        issued = []
        for row in parts:
            if not isinstance(row, dict) or set(row) != {"item", "quantity"}:
                frappe.throw(_("Revise el repuesto y su cantidad"))
            product = frappe.db.get_value("HS Product", row["item"],
                ["property", "organization", "product_type", "expense_account",
                 "inventory_account", "active"], as_dict=True)
            if (not product or product.property != prop.name or
                    product.organization != prop.organization or
                    product.product_type != "Stock" or not product.active or
                    not product.inventory_account or not product.expense_account):
                frappe.throw(_("Seleccione un repuesto activo con cuentas de inventario y gasto"))
            expense = standalone_accounting.account(prop, product.expense_account)
            if expense.root_type != "Expense" or expense.account_currency != prop.currency:
                frappe.throw(_("El repuesto requiere una cuenta de gasto en moneda base"))
            movement = standalone_inventory.consume(prop, product=row["item"],
                warehouse=data["warehouse"], quantity=row["quantity"],
                counter_account=expense.name, source_doctype=doc.doctype,
                source_name=doc.name,
                purpose=f"Maintenance Part {len(doc.parts) + 1}",
                memo="Repuesto para " + doc.name)
            cost = -Decimal(str(movement["value_delta"]))
            doc.append("parts", {"item": row["item"], "quantity": row["quantity"],
                "stock_entry": movement["movement"], "cost": _money(cost),
                "status": "Issued"})
            issued.append(movement["movement"])
        doc.stock_entry = issued[-1]
        action = "pms_maintenance_parts_issue"
        details = {"movements": issued}
    if not data.get("return_entry"):
        doc.cost = _money(sum((Decimal(str(part.cost)) for part in doc.parts
            if part.status == "Issued"), Decimal(0)))
        doc.save(ignore_permissions=True)
    audit(prop, action, doc, reason=data.get("reason"), details={
        **details, "cost": str(doc.cost)})
    return {"order": doc.name, "stock_entry": doc.stock_entry,
        "cost": str(doc.cost), "modified": str(doc.modified)}


def board(property_name, order_name, warehouse="", search="", offset=0, page_length=25):
    prop = require(property_name, "maintain")
    doc = property_document(prop, "HS Maintenance Order", order_name, "maintain")
    if not isinstance(search, str) or len(search) > 100 or not isinstance(warehouse, str):
        frappe.throw(_("Revise los filtros de repuestos"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación de repuestos"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(_("Revise la paginación de repuestos"))
    pms = standalone_accounting.provider() == "pms"
    if pms:
        warehouses = frappe.get_all("HS Warehouse", filters={"property": prop.name,
            "organization": prop.organization, "active": 1},
            fields=["name", "warehouse_name"], order_by="warehouse_name asc",
            limit_page_length=1000)
        selected = warehouse or (warehouses[0].name if warehouses else "")
        if selected and selected not in {row.name for row in warehouses}:
            frappe.throw(_("El almacén no pertenece al establecimiento"), frappe.PermissionError)
    else:
        selected = prop.warehouse or ""
        if warehouse and warehouse != selected:
            frappe.throw(_("El almacén no pertenece al establecimiento"), frappe.PermissionError)
        if selected and frappe.db.get_value("Warehouse", selected, "company") != prop.company:
            frappe.throw(_("El almacén no pertenece a la compañía"), frappe.PermissionError)
        warehouses = ([{"name": selected, "warehouse_name": selected}] if selected else [])
    total, products = 0, []
    if selected and doc.status != "Completed":
        if pms:
            where = ("p.property=%s AND p.organization=%s AND p.product_type='Stock' "
                "AND p.active=1")
            values = [prop.name, prop.organization]
            values.insert(0, selected)
            group = " GROUP BY p.name,p.product_name,p.expense_account HAVING SUM(m.quantity_delta)>0"
            if search.strip():
                where += " AND (p.name LIKE %s OR p.product_name LIKE %s)"
                values.extend(["%" + search.strip() + "%"] * 2)
            inner = ("SELECT p.name,p.product_name,"
                "p.expense_account AS expense_account,SUM(m.quantity_delta) AS quantity "
                "FROM `tabHS Product` p JOIN `tabHS Stock Movement` m "
                "ON m.product=p.name AND m.warehouse=%s AND m.property=p.property "
                f"WHERE {where}{group}")
            total = frappe.db.sql("SELECT COUNT(*) FROM (" + inner + ") available",
                values, as_list=True)[0][0]
            products = frappe.db.sql("SELECT * FROM (" + inner +
                ") available ORDER BY product_name ASC,name ASC LIMIT %s OFFSET %s",
                [*values, page_length, offset], as_dict=True)
            for product in products:
                product["has_expense_account"] = bool(product.pop("expense_account"))
        else:
            where = "i.is_stock_item=1 AND i.disabled=0 AND b.actual_qty>0"
            values = [selected]
            if search.strip():
                where += " AND (i.name LIKE %s OR i.item_name LIKE %s)"
                values.extend(["%" + search.strip() + "%"] * 2)
            base = (" FROM `tabItem` i JOIN `tabBin` b ON b.item_code=i.name "
                "AND b.warehouse=%s WHERE " + where)
            total = frappe.db.sql("SELECT COUNT(*)" + base, values, as_list=True)[0][0]
            products = frappe.db.sql("SELECT i.name,i.item_name AS product_name,"
                "b.actual_qty AS quantity" + base +
                " ORDER BY i.item_name ASC,i.name ASC LIMIT %s OFFSET %s",
                [*values, page_length, offset], as_dict=True)
    roles = set(frappe.get_roles())
    can_approve = is_system() or bool(roles.intersection(ACTIONS["approve"]))
    item_names = list({part.item for part in doc.parts})
    item_type = "HS Product" if pms else "Item"
    label_field = "product_name" if pms else "item_name"
    labels = ({row.name: row.get(label_field) for row in frappe.get_all(item_type,
        filters={"name": ["in", item_names]}, fields=["name", label_field],
        limit_page_length=len(item_names))} if item_names else {})
    return {"order": doc.name, "status": doc.status, "modified": str(doc.modified),
        "cost": str(doc.cost or 0), "parts": [{"item": part.item,
            "item_label": labels.get(part.item) or part.item,
            "quantity": part.quantity, "stock_entry": part.stock_entry,
            "cost": part.cost, "status": part.status} for part in doc.parts],
        "warehouses": warehouses, "warehouse": selected, "total": int(total),
        "offset": offset, "has_more": offset + len(products) < total,
        "products": products, "can_approve": can_approve,
        "provider": standalone_accounting.provider()}
