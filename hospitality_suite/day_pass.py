"""Day Pass access without a room, billed as a registered counter service."""
import hashlib

import frappe
from frappe.utils import now_datetime

from hospitality_suite import direct_sales
from hospitality_suite.availability_search import positive_integer
from hospitality_suite.service import audit, canonical, insert
from hospitality_suite.time import local, to_site


def _context(prop, data):
    item = prop.get("day_pass_item")
    if not item:
        frappe.throw(frappe._("Configure el artículo de Day Pass sin habitación"))
    if frappe.db.get_value("Item", item, "is_stock_item"):
        frappe.throw(frappe._("Day Pass sin habitación requiere un artículo de servicio sin inventario"))
    people = positive_integer(data.get("people"), frappe._("Personas del Day Pass"))
    if people > 100:
        frappe.throw(frappe._("Day Pass admite hasta 100 personas por venta"))
    start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
    if end <= start or local(start, prop).date() != local(end, prop).date():
        frappe.throw(frappe._("Day Pass requiere entrada y salida en el mismo día local"))
    if end <= now_datetime():
        frappe.throw(frappe._("No puede emitir un Day Pass cuyo período ya terminó"))
    guest = data.get("guest")
    if guest and frappe.db.get_value("HS Guest", guest, "property") != prop.name:
        frappe.throw(frappe._("El huésped no pertenece al establecimiento"), frappe.PermissionError)
    return dict(item=item, people=people, starts_at=start, ends_at=end, guest=guest)


def quote_without_room(prop, data):
    context = _context(prop, data)
    sale = direct_sales.quote(prop, {**data, "item": context["item"], "quantity": context["people"]})
    result = {**sale, "people": context["people"], "starts_at": str(context["starts_at"]),
              "ends_at": str(context["ends_at"]), "guest": context["guest"],
              "sale_acceptance": sale["acceptance"]}
    result["acceptance"] = hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def sell_without_room(prop, data):
    quote = quote_without_room(prop, data)
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(frappe._("Revise y acepte la cotización vigente de Day Pass"))
    sale = direct_sales.sell(prop, {**data, "item": prop.day_pass_item,
                                   "quantity": quote["people"], "acceptance": quote["sale_acceptance"]})
    doc = insert("HS Day Pass", prop, customer=data["customer"], guest=quote["guest"], people=quote["people"],
                 starts_at=quote["starts_at"], ends_at=quote["ends_at"], status="Issued",
                 service=sale["service"], sales_invoice=sale["invoice"], payment=sale["payment"],
                 notes=data.get("notes"))
    audit(prop, "Day Pass issued", doc, details=dict(service=sale["service"], invoice=sale["invoice"]))
    return {**sale, "day_pass": doc.name}
