import frappe

from hospitality_suite.accounting import ready, post_standard
from hospitality_suite.security import document
from hospitality_suite.service import insert, audit
from hospitality_suite.pricing import decimal


def incident(prop, data):
    room = document("HS Room",data["room"],"clean")
    if data.get("kind") not in ("Damage","Lost Property") or not data.get("description"):
        frappe.throw("Indique tipo y descripción de la novedad")
    record = insert("HS Incident",prop,room=room.name,kind=data["kind"],description=data["description"],status="Open")
    audit(prop,"Record incident",record)
    return dict(incident=record.name)


def move_linen(prop,data):
    ready(prop)
    if not prop.get("laundry_warehouse") or prop.laundry_warehouse==prop.warehouse:
        frappe.throw("Configure un almacén de lavandería diferente al almacén operativo")
    laundry = frappe.get_doc("Warehouse",prop.laundry_warehouse)
    if laundry.company!=prop.company or laundry.is_group:
        frappe.throw("El almacén de lavandería no corresponde a la compañía")
    item = frappe.get_doc("Item",data["item"])
    quantity = decimal(data["quantity"])
    direction = data["direction"]
    if not item.is_stock_item or quantity<=0 or direction not in ("Send","Receive","Loss"):
        frappe.throw("Artículo, cantidad o movimiento de ropa inválido")
    if direction=="Loss" and not data.get("reason"):
        frappe.throw("Indique el motivo de la pérdida")
    entry = frappe.new_doc("Stock Entry")
    entry.company=prop.company
    entry.stock_entry_type="Material Issue" if direction=="Loss" else "Material Transfer"
    entry.append("items",dict(item_code=item.name,qty=float(quantity),cost_center=prop.cost_center,
                               s_warehouse=prop.warehouse if direction=="Send" else prop.laundry_warehouse,
                               t_warehouse=None if direction=="Loss" else (prop.warehouse if direction=="Receive" else prop.laundry_warehouse)))
    post_standard(entry,prop)
    room = document("HS Room",data["room"],"clean")
    record = insert("HS Incident",prop,room=room.name,kind="Linen",description=data.get("reason") or direction,
                    item=item.name,quantity=float(quantity),status="Resolved",stock_entry=entry.name)
    audit(prop,"Linen "+direction,record,data.get("reason"))
    return dict(incident=record.name,stock_entry=entry.name)
