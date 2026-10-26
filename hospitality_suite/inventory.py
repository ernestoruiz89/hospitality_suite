from hospitality_suite.service import current_all, locked_doc
import hashlib
import frappe

from hospitality_suite.accounting import ready, post_standard
from hospitality_suite.security import document
from hospitality_suite.service import insert, audit, assert_version, canonical
from hospitality_suite.pricing import decimal, money


def erp_service_snapshot(property_name, stay=None):
    """Property-scoped guest service queue for the React ERPNext mode."""
    from hospitality_suite import standalone_accounting
    from hospitality_suite.security import require

    prop = require(property_name, "service")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte los servicios desde la contabilidad PMS"))
    if stay:
        chosen = document("HS Stay", stay, "service")
        if chosen.property != prop.name or chosen.company != prop.company:
            frappe.throw(frappe._("La estancia pertenece a otro establecimiento"),
                         frappe.PermissionError)
        if chosen.status != "Active":
            frappe.throw(frappe._("La estancia ya no está activa"))
        stays = [chosen]
        folio_filters = {"property": prop.name, "company": prop.company,
                         "status": "Open"}
        folios = frappe.get_all("HS Folio", filters={**folio_filters, "stay": chosen.name},
            fields=["name", "stay", "booking", "label", "customer", "currency"],
            limit_page_length=0)
        if chosen.booking:
            folios += frappe.get_all("HS Folio", filters={**folio_filters,
                "stay": ["is", "not set"], "booking": chosen.booking},
                fields=["name", "stay", "booking", "label", "customer", "currency"],
                limit_page_length=0)
    else:
        stays = frappe.get_all("HS Stay", filters={"property": prop.name,
                                                  "company": prop.company,
                                                  "status": "Active"},
                               fields=["name", "booking", "guest"],
                               order_by="creation desc", limit_page_length=150)
        folios = frappe.get_all("HS Folio", filters={"property": prop.name,
                                                    "company": prop.company,
                                                    "status": "Open"},
                                fields=["name", "stay", "booking", "label", "customer",
                                        "currency"], limit_page_length=250)
    requests = frappe.get_all("HS Service Request", filters={"property": prop.name,
                                                        "company": prop.company,
                                                        "stay": stay if stay else ["is", "set"]},
                              fields=["name", "stay", "folio", "item", "quantity",
                                      "included", "amount", "currency", "status", "modified",
                                      "charge", "stock_entry", "notes"],
                              order_by="creation desc", limit_page_length=200)
    item_ids = sorted({row.item for row in requests if row.item})
    items = frappe.get_all("Item", filters={"name": ["in", item_ids]},
                           fields=["name", "item_name"],
                           limit_page_length=len(item_ids)) if item_ids else []
    return {"currency": prop.currency,
            "stays": [{"name": stay.name, "guest": stay.guest,
                       "folios": [{"name": folio.name, "label": folio.label,
                                   "customer": folio.customer, "currency": folio.currency}
                                  for folio in folios if
                                  folio.stay == stay.name or
                                  (not folio.stay and stay.booking and
                                   folio.booking == stay.booking)]}
                      for stay in stays],
            "requests": requests, "items": items,
            "warehouse": prop.warehouse}


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


def _service_draft(prop, data):
    ready(prop)
    stay = document("HS Stay", data["stay"], "service")
    folio = document("HS Folio", data["folio"], "service")
    matches=folio.stay==stay.name if folio.stay else bool(folio.booking and folio.booking==stay.booking)
    if stay.status != "Active" or folio.status != "Open" or not matches:
        frappe.throw(frappe._("El consumo requiere una estancia activa y una cuenta abierta"))
    item = locked_doc("Item", data["item"])
    if item.disabled or not item.is_sales_item or item.is_fixed_asset:
        frappe.throw(frappe._("El artículo no está habilitado para venta"))
    quantity = decimal(data.get("quantity",1))
    if quantity <= 0:
        frappe.throw(frappe._("La cantidad debe ser positiva"))
    included=data.get("included") in (True,1,"1")
    if included:
        entitlement=sum(decimal(r["quantity"]) for r in frappe.parse_json(stay.service_entitlements or "[]") if r["item"]==item.name)
        used=sum(decimal(r.quantity) for r in current_all("HS Service Request",filters={"stay":stay.name,"item":item.name,"included":1,"status":["in",["Requested","In Progress","Delivered"]]},fields=["quantity"]))
        if quantity>entitlement-used:
            frappe.throw(frappe._("La solicitud supera los servicios incluidos disponibles de la estancia"))
    # A configured ERPNext Item Price is the authority; callers cannot invent prices.
    from hospitality_suite.item_configuration import selling_price
    price_row=None if included else selling_price(prop,item.name,folio.currency,folio.customer)
    price=price_row.price_list_rate if price_row else 0
    amount=0 if included else money(quantity * decimal(price))
    quote=dict(stay=stay.name,folio=folio.name,customer=folio.customer,
               item=item.name,quantity=str(quantity),included=bool(included),
               currency=folio.currency,unit_rate=str(price),amount=str(amount),
               item_price=price_row.name if price_row else None)
    quote["acceptance"]=hashlib.sha256(canonical(quote).encode()).hexdigest()
    return stay,folio,item,quantity,included,price_row,quote


def service_quote(prop, data):
    from hospitality_suite import standalone_accounting
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte los servicios desde la contabilidad PMS"))
    return _service_draft(prop, data)[-1]


def request_service(prop, data):
    stay,folio,item,quantity,included,price_row,quote=_service_draft(prop,data)
    if data.get("acceptance") and data["acceptance"]!=quote["acceptance"]:
        frappe.throw(frappe._("Revise y acepte el precio vigente del servicio"))
    doc = insert("HS Service Request", prop, stay=stay.name, folio=folio.name, customer=folio.customer, item=item.name,
                 quantity=quantity,included=included, amount=quote["amount"], currency=folio.currency, status="Requested", notes=data.get("notes"))
    audit(prop,"Request service",doc,details=dict(item_price=price_row.name,rate=str(price_row.price_list_rate),valid_from=price_row.valid_from,valid_upto=price_row.valid_upto) if price_row else dict(included=True))
    return dict(service=doc.name, amount=str(doc.amount))


def update_service(prop, data):
    from hospitality_suite.operations import charge
    doc = document("HS Service Request", data["service"], "service")
    if not doc.stay:
        frappe.throw(frappe._("Use Devolver venta directa para esta operación"))
    assert_version(doc, data.get("modified"))
    target = data["status"]
    transitions = {"Requested": ["In Progress", "Delivered", "Cancelled"], "In Progress": ["Delivered", "Cancelled"], "Delivered": ["Returned"]}
    if target not in transitions.get(doc.status, []):
        frappe.throw(frappe._("Transición de servicio inválida"))
    if target == "Delivered":
        stay = document("HS Stay", doc.stay, "service")
        folio = document("HS Folio", doc.folio, "service")
        if stay.status != "Active" or folio.status != "Open":
            frappe.throw(frappe._("La estancia o cuenta ya está cerrada"))
        entry = stock_movement(prop, doc.item, doc.quantity)
        doc.stock_entry = entry.name if entry else None
        if not doc.included:
            doc.charge = charge(prop, stay, folio, doc.item, doc.amount, "Service", frappe.db.get_value("Item", doc.item, "item_name"), quantity=doc.quantity).name
    elif target == "Returned":
        from hospitality_suite.security import require
        require(prop.name, "approve")
        if not data.get("reason"):
            frappe.throw(frappe._("Indique el motivo de la devolución"))
        if doc.charge:
            original = locked_doc("HS Charge", doc.charge)
            if original.status == "Invoiced" and not doc.credit_note:
                frappe.throw(frappe._("Cree la nota de crédito antes de devolver un consumo facturado"))
            if original.status != "Invoiced":
                original.status, original.reason = "Reversed", data["reason"]
                original.save()
                for name in current_all('HS Charge',filters={'applies_to_charge':original.name,'status':['in',['Pending','Scheduled']]},pluck='name'):
                    adjustment=locked_doc('HS Charge',name)
                    adjustment.status,adjustment.reason='Reversed',data['reason']
                    adjustment.save()
        if doc.stock_entry:
            entry = locked_doc("Stock Entry", doc.stock_entry)
            entry.flags.ignore_permissions = True
            entry.hs_correction_reason=data["reason"]
            entry.cancel()  # standard ledger reversal, no second inventory path
    doc.status = target
    doc.save()
    audit(prop, "Service " + target, doc, data.get("reason"))
    return dict(service=doc.name, status=target)
