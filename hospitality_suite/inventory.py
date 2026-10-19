from hospitality_suite.service import current_all, locked_doc
import frappe

from hospitality_suite.accounting import ready, post_standard
from hospitality_suite.security import document
from hospitality_suite.service import insert, audit, assert_version
from hospitality_suite.pricing import decimal, money


def stock_movement(prop, item, quantity, returning=False):
    item_doc = locked_doc("Item", item)
    if not item_doc.is_stock_item:
        return None
    entry = frappe.new_doc("Stock Entry")
    entry.stock_entry_type = "Material Receipt" if returning else "Material Issue"
    entry.company = prop.company
    entry.hs_stock_purpose="Sale"
    entry.append("items", dict(item_code=item, qty=quantity, s_warehouse=None if returning else prop.warehouse,
                               t_warehouse=prop.warehouse if returning else None, cost_center=prop.cost_center))
    return post_standard(entry, prop)


def request_service(prop, data):
    ready(prop)
    stay = document("HS Stay", data["stay"], "service")
    folio = document("HS Folio", data["folio"], "service")
    matches=folio.stay==stay.name if folio.stay else bool(folio.booking and folio.booking==stay.booking)
    if stay.status != "Active" or folio.status != "Open" or not matches:
        frappe.throw("El consumo requiere una estancia activa y una cuenta abierta")
    item = locked_doc("Item", data["item"])
    if item.disabled or not item.is_sales_item or item.is_fixed_asset:
        frappe.throw("El artículo no está habilitado para venta")
    quantity = decimal(data.get("quantity") or 1)
    if quantity <= 0:
        frappe.throw("La cantidad debe ser positiva")
    included=data.get("included") in (True,1,"1")
    if included:
        entitlement=sum(decimal(r["quantity"]) for r in frappe.parse_json(stay.service_entitlements or "[]") if r["item"]==item.name)
        used=sum(decimal(r.quantity) for r in current_all("HS Service Request",filters={"stay":stay.name,"item":item.name,"included":1,"status":["in",["Requested","In Progress","Delivered"]]},fields=["quantity"]))
        if quantity>entitlement-used:
            frappe.throw("La solicitud supera los servicios incluidos disponibles de la estancia")
    # A configured ERPNext Item Price is the authority; callers cannot invent prices.
    price_list = prop.get("price_list") or frappe.db.get_single_value("Selling Settings", "selling_price_list")
    price = frappe.db.get_value("Item Price", {"item_code": item.name, "price_list": price_list, "currency": folio.currency, "selling": 1}, "price_list_rate")
    if price is None and not included:
        frappe.throw("Configure el precio de venta del artículo en ERPNext")
    doc = insert("HS Service Request", prop, stay=stay.name, folio=folio.name, customer=folio.customer, item=item.name,
                 quantity=quantity,included=included, amount=0 if included else money(quantity * decimal(price)), currency=folio.currency, status="Requested", notes=data.get("notes"))
    audit(prop, "Request service", doc)
    return dict(service=doc.name, amount=str(doc.amount))


def update_service(prop, data):
    from hospitality_suite.operations import charge
    doc = document("HS Service Request", data["service"], "service")
    if not doc.stay:
        frappe.throw("Use Devolver venta directa para esta operación")
    assert_version(doc, data.get("modified"))
    target = data["status"]
    transitions = {"Requested": ["In Progress", "Delivered", "Cancelled"], "In Progress": ["Delivered", "Cancelled"], "Delivered": ["Returned"]}
    if target not in transitions.get(doc.status, []):
        frappe.throw("Transición de servicio inválida")
    if target == "Delivered":
        stay = document("HS Stay", doc.stay, "service")
        folio = document("HS Folio", doc.folio, "service")
        if stay.status != "Active" or folio.status != "Open":
            frappe.throw("La estancia o cuenta ya está cerrada")
        entry = stock_movement(prop, doc.item, doc.quantity)
        doc.stock_entry = entry.name if entry else None
        if not doc.included:
            doc.charge = charge(prop, stay, folio, doc.item, doc.amount, "Service", frappe.db.get_value("Item", doc.item, "item_name"), quantity=doc.quantity).name
    elif target == "Returned":
        from hospitality_suite.security import require
        require(prop.name, "approve")
        if not data.get("reason"):
            frappe.throw("Indique el motivo de la devolución")
        if doc.charge:
            original = locked_doc("HS Charge", doc.charge)
            if original.status == "Invoiced" and not doc.credit_note:
                frappe.throw("Cree la nota de crédito antes de devolver un consumo facturado")
            if original.status != "Invoiced":
                original.status, original.reason = "Reversed", data["reason"]
                original.save()
        if doc.stock_entry:
            entry = locked_doc("Stock Entry", doc.stock_entry)
            entry.flags.ignore_permissions = True
            entry.hs_correction_reason=data["reason"]
            entry.cancel()  # standard ledger reversal, no second inventory path
    doc.status = target
    doc.save()
    audit(prop, "Service " + target, doc, data.get("reason"))
    return dict(service=doc.name, status=target)
