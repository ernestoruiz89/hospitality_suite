"""Guest service requests fulfilled from PMS products and valued stock."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _

from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, require_pms
from hospitality_suite.standalone_folio_services import _quantity
from hospitality_suite.standalone_inventory import consume, receive
from hospitality_suite.standalone_tax import tax_for_amount


def _matches(stay, folio):
    return (folio.stay == stay.name if folio.stay else
            bool(folio.booking and folio.booking == stay.booking))


def _product(prop, name, included):
    product = locked_doc("HS Product", name)
    if ((product.property, product.organization) != (prop.name, prop.organization) or
            not product.active or product.product_type not in ("Service", "Stock")):
        frappe.throw(_("Seleccione un producto PMS activo del establecimiento"))
    if product.product_type == "Stock":
        inventory = account(prop, product.inventory_account)
        expense = account(prop, product.expense_account)
        if (inventory.root_type != "Asset" or expense.root_type != "Expense" or
                inventory.account_currency != prop.currency or
                expense.account_currency != prop.currency):
            frappe.throw(_("El producto de inventario requiere cuentas de activo y gasto en moneda base"))
    if not included:
        income = account(prop, product.income_account)
        if income.root_type != "Income" or income.account_currency != prop.currency or not product.tax_profile:
            frappe.throw(_("El producto vendible requiere ingreso e impuesto configurados en moneda base"))
        if Decimal(str(product.sales_rate or 0)) <= 0:
            frappe.throw(_("Configure un precio positivo para el producto"))
    return product


def _included_available(prop, stay, product):
    entitlements = frappe.parse_json(stay.service_entitlements or "[]")
    allowed = sum((Decimal(str(row["quantity"])) for row in entitlements
                   if row["item"] == product), Decimal(0))
    used = sum((Decimal(str(row.quantity)) for row in current_all(
        "HS Service Request", filters={"property": prop.name, "stay": stay.name,
            "item": product, "included": 1,
            "status": ["in", ["Requested", "In Progress", "Delivered"]]},
        fields=["quantity"])), Decimal(0))
    return allowed - used


def request(prop, data):
    require_pms(prop)
    require(prop.name, "service")
    if not isinstance(data, dict) or set(data) - {"stay", "folio", "item", "warehouse", "quantity", "included", "notes"}:
        frappe.throw(_("Revise la solicitud de servicio"))
    stay = document("HS Stay", data.get("stay"), "service")
    folio = document("HS Folio", data.get("folio"), "service")
    if (stay.property != prop.name or folio.property != prop.name or
            stay.status != "Active" or folio.status != "Open" or
            folio.currency != prop.currency or not _matches(stay, folio)):
        frappe.throw(_("Seleccione una estancia activa y su cuenta de estancia abierta en moneda base"))
    included = data.get("included") in (True, 1, "1")
    product = _product(prop, data.get("item"), included)
    quantity = _quantity(data.get("quantity", 1))
    if included and quantity > _included_available(prop, stay, product.name):
        frappe.throw(_("La solicitud supera los servicios incluidos disponibles"))
    warehouse = None
    if product.product_type == "Stock":
        warehouse = locked_doc("HS Warehouse", data.get("warehouse"))
        if ((warehouse.property, warehouse.organization) != (prop.name, prop.organization) or
                not warehouse.active):
            frappe.throw(_("Seleccione un almacén activo del establecimiento"))
    elif data.get("warehouse"):
        frappe.throw(_("Un servicio sin inventario no requiere almacén"))
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes) > 500:
        frappe.throw(_("Las observaciones deben tener hasta 500 caracteres"))
    price = (Decimal(str(product.sales_rate or 0)) * quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP) if not included else Decimal(0)
    if not included:
        tax_for_amount(prop, product.tax_profile, price)
    doc = insert("HS Service Request", prop, stay=stay.name, folio=folio.name,
        customer=folio.customer, item=product.name, warehouse=warehouse.name if warehouse else None,
        quantity=str(quantity), included=int(included), amount=str(price),
        currency=prop.currency, status="Requested", notes=notes.strip())
    audit(prop, "pms_service_requested", doc,
          details={"product": product.name, "quantity": str(quantity), "price": str(price)})
    return {"service": doc.name, "status": doc.status, "amount": str(price)}


def _return_charge(prop, doc, reason):
    if not doc.charge:
        return
    charge = locked_doc("HS Charge", doc.charge)
    if charge.property != prop.name or charge.folio != doc.folio:
        frappe.throw(_("El cargo del servicio pertenece a otra cuenta de estancia"))
    if charge.status == "Posted":
        from hospitality_suite.standalone_receivables import credited
        row = frappe.db.get_value("HS PMS Receivable", charge.pms_receivable,
            ["property", "amount", "status"], as_dict=True)
        if (not row or row.property != prop.name or row.status != "Posted" or
                credited(prop, charge.pms_receivable) != Decimal(str(row.amount))):
            frappe.throw(_("Acredite completamente el cargo fiscal antes de devolver el servicio"))
        note = frappe.db.sql(
            "SELECT d.name FROM `tabHS PMS Fiscal Line` l "
            "JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
            "WHERE d.property=%s AND d.document_type='Credit Note' "
            "AND l.receivable=%s ORDER BY d.creation DESC LIMIT 1",
            (prop.name, charge.pms_receivable), as_list=True)
        doc.credit_note = note[0][0] if note else None
    elif charge.status == "Pending":
        charge.status, charge.reason = "Reversed", reason
        charge.save()
        for row in current_all("HS Charge", filters={"property": prop.name,
                "applies_to_charge": charge.name, "status": ["in", ["Pending", "Scheduled"]]},
                fields=["name"]):
            adjustment = locked_doc("HS Charge", row.name)
            adjustment.status, adjustment.reason = "Reversed", reason
            adjustment.save()
    elif charge.status != "Reversed":
        frappe.throw(_("El cargo requiere resolución contable antes de devolver el servicio"))


def update(prop, data):
    require_pms(prop)
    require(prop.name, "service")
    if not isinstance(data, dict) or set(data) - {"service", "modified", "status", "reason"}:
        frappe.throw(_("Revise el cambio de estado del servicio"))
    doc = document("HS Service Request", data.get("service"), "service")
    if doc.property != prop.name or not doc.stay:
        frappe.throw(_("Seleccione una solicitud de estancia del establecimiento"))
    assert_version(doc, data.get("modified"))
    target = data.get("status")
    transitions = {"Requested": ("In Progress", "Delivered", "Cancelled"),
                   "In Progress": ("Delivered", "Cancelled"),
                   "Delivered": ("Returned",)}
    if target not in transitions.get(doc.status, ()):
        frappe.throw(_("Transición de servicio inválida"))
    if target == "Delivered":
        stay = document("HS Stay", doc.stay, "service")
        folio = document("HS Folio", doc.folio, "service")
        if stay.status != "Active" or folio.status != "Open" or not _matches(stay, folio):
            frappe.throw(_("La estancia o la cuenta de estancia ya no admiten entregas"))
        product = _product(prop, doc.item, bool(doc.included))
        if product.product_type == "Stock":
            movement = consume(prop, product=product.name, warehouse=doc.warehouse,
                quantity=doc.quantity, counter_account=product.expense_account,
                source_doctype=doc.doctype, source_name=doc.name,
                purpose="Guest Service", memo=f"Entrega a estancia {stay.name}")
            doc.stock_entry = movement["movement"]
        if not doc.included:
            charge = insert("HS Charge", prop, stay=stay.name, folio=folio.name,
                item=product.name, description=product.product_name,
                quantity=doc.quantity, rate=str(Decimal(str(doc.amount)) / Decimal(str(doc.quantity))),
                amount=doc.amount, currency=prop.currency, business_date=prop.business_date,
                kind="Service", status="Pending")
            doc.charge = charge.name
    elif target == "Returned":
        require(prop.name, "approve")
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            frappe.throw(_("Indique el motivo de la devolución"))
        _return_charge(prop, doc, reason.strip())
        if doc.opening_stock_issue:
            try:
                issue = frappe.parse_json(doc.opening_stock_issue)
            except (TypeError, ValueError):
                issue = None
            try:
                historical_quantity = Decimal(str(issue.get("quantity")))
                historical_cost = Decimal(str(issue.get("cost")))
            except (InvalidOperation, TypeError, ValueError, AttributeError):
                historical_quantity = historical_cost = Decimal("NaN")
            if (not isinstance(issue, dict) or
                    doc.stock_entry != issue.get("voucher") or
                    issue.get("warehouse") != doc.warehouse or
                    not historical_quantity.is_finite() or
                    historical_quantity != Decimal(str(doc.quantity)) or
                    not historical_cost.is_finite() or historical_cost <= 0 or
                    not issue.get("voucher")):
                frappe.throw(_("La salida histórica del servicio requiere conciliación"))
            expense = account(prop, issue.get("expense_account"))
            inventory = account(prop, issue.get("inventory_account"))
            if (expense.root_type != "Expense" or
                    inventory.root_type != "Asset" or
                    expense.account_currency != prop.currency or
                    inventory.account_currency != prop.currency):
                frappe.throw(_("Las cuentas de la salida histórica ya no son válidas"))
            returned = receive(prop, product=doc.item, warehouse=doc.warehouse,
                quantity=doc.quantity, value=issue["cost"],
                counter_account=expense.name,
                inventory_account_name=inventory.name,
                historical_return=True,
                source_doctype=doc.doctype, source_name=doc.name,
                purpose="Guest Service Return", memo=reason.strip())
            doc.return_stock_entry = returned["movement"]
        elif doc.stock_entry:
            original = locked_doc("HS Stock Movement", doc.stock_entry)
            journal = locked_doc("HS Journal", original.journal)
            if (original.property != prop.name or original.source_name != doc.name or
                    original.direction != "Issue" or journal.property != prop.name):
                frappe.throw(_("La salida de inventario no coincide con la solicitud"))
            expense = next((row.account for row in journal.lines if Decimal(str(row.debit)) > 0), None)
            inventory = next((row.account for row in journal.lines if Decimal(str(row.credit)) > 0), None)
            if not expense or not inventory:
                frappe.throw(_("El costo entregado no conserva su asiento"))
            returned = receive(prop, product=doc.item, warehouse=doc.warehouse,
                quantity=doc.quantity, value=str(-Decimal(str(original.value_delta))),
                counter_account=expense, inventory_account_name=inventory,
                historical_return=True,
                source_doctype=doc.doctype, source_name=doc.name,
                purpose="Guest Service Return", memo=reason.strip())
            doc.return_stock_entry = returned["movement"]
    doc.status = target
    doc.save()
    audit(prop, "pms_service_" + target.lower().replace(" ", "_"), doc,
          reason=data.get("reason"))
    return {"service": doc.name, "status": doc.status, "modified": str(doc.modified),
            "charge": doc.charge, "stock_movement": doc.stock_entry,
            "return_stock_movement": doc.return_stock_entry}


def snapshot(property_name, stay=None):
    prop = require(property_name, "service")
    require_pms(prop)
    if stay:
        chosen = document("HS Stay", stay, "service")
        if chosen.property != prop.name:
            frappe.throw(_("La estancia pertenece a otro establecimiento"), frappe.PermissionError)
        if chosen.status != "Active":
            frappe.throw(_("La estancia ya no está activa"))
        stays = [chosen]
        folio_filters = {"property": prop.name, "status": "Open"}
        folios = frappe.get_all("HS Folio", filters={**folio_filters, "stay": chosen.name},
            fields=["name", "stay", "booking", "label", "customer"], limit_page_length=0)
        if chosen.booking:
            folios += frappe.get_all("HS Folio", filters={**folio_filters,
                "stay": ["is", "not set"], "booking": chosen.booking},
                fields=["name", "stay", "booking", "label", "customer"], limit_page_length=0)
    else:
        stays = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"},
            fields=["name", "booking", "guest"], order_by="creation desc", limit_page_length=150)
        folios = frappe.get_all("HS Folio", filters={"property": prop.name, "status": "Open"},
            fields=["name", "stay", "booking", "label", "customer"], limit_page_length=200)
    products = frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "active": 1,
        "product_type": ["in", ["Service", "Stock"]]},
        fields=["name", "product_name", "product_type", "sales_rate"],
        order_by="product_name asc", limit_page_length=500)
    warehouses = frappe.get_all("HS Warehouse", filters={"property": prop.name,
        "organization": prop.organization, "active": 1},
        fields=["name", "warehouse_name"], order_by="warehouse_name asc")
    balances = frappe.db.sql(
        "SELECT product, warehouse, SUM(quantity_delta) AS quantity "
        "FROM `tabHS Stock Movement` WHERE property=%s GROUP BY product, warehouse",
        prop.name, as_dict=True)
    request_filters = {"property": prop.name, "stay": stay if stay else ["is", "set"]}
    requests = frappe.get_all("HS Service Request", filters=request_filters,
        fields=["name", "stay", "folio", "item", "warehouse",
        "quantity", "included", "amount", "currency", "status", "modified", "charge",
        "stock_entry", "return_stock_entry", "notes"],
        order_by="creation desc", limit_page_length=200)
    return {"currency": prop.currency,
        "stays": [{"name": stay.name, "guest": stay.guest,
                   "folios": [folio for folio in folios if _matches(stay, folio)]}
                  for stay in stays], "products": products,
        "warehouses": warehouses, "balances": balances, "requests": requests}
