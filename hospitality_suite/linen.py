import frappe

from hospitality_suite.accounting import ready, post_standard
from hospitality_suite.security import property_document,require,private_evidence,warehouse_allowed
from hospitality_suite.service import insert, audit,assert_version
from hospitality_suite.pricing import decimal


def incident(prop, data):
    if data.get("incident"):
        record=property_document(prop,"HS Incident",data["incident"],"incident")
        assert_version(record,data.get("modified"))
        if record.status!="Open":
            frappe.throw(frappe._("La novedad ya está resuelta"))
        if data.get("evidence"):
            record.evidence=private_evidence(data["evidence"],record)
        if data.get("resolve"):
            require(prop.name,"inspect")
            if not data.get("resolution"):
                frappe.throw(frappe._("Describa la resolución o entrega del objeto"))
            record.status,record.resolution="Resolved",data["resolution"]
            record.resolved_by,record.resolved_at=frappe.session.user,frappe.utils.now_datetime()
        record.save()
        audit(prop,"Resolve incident" if data.get("resolve") else "Incident evidence",record,record.resolution)
        return dict(incident=record.name,status=record.status)
    room = property_document(prop,"HS Room",data["room"],"incident")
    if data.get("kind") not in ("Damage","Lost Property") or not data.get("description"):
        frappe.throw(frappe._("Indique tipo y descripción de la novedad"))
    record = insert("HS Incident",prop,room=room.name,kind=data["kind"],description=data["description"],status="Open")
    audit(prop,"Record incident",record)
    return dict(incident=record.name)


def move_linen(prop,data):
    room=property_document(prop,"HS Room",data["room"],"clean")
    ready(prop)
    if not prop.get("laundry_warehouse") or prop.laundry_warehouse==prop.warehouse:
        frappe.throw(frappe._("Configure un almacén de lavandería diferente al almacén operativo"))
    if not warehouse_allowed(prop,prop.laundry_warehouse):
        frappe.throw(frappe._("El almacén de lavandería no pertenece a este establecimiento"))
    item = frappe.get_doc("Item",data["item"])
    quantity = decimal(data["quantity"])
    direction = data["direction"]
    if not item.is_stock_item or quantity<=0 or direction not in ("Send","Receive","Loss"):
        frappe.throw(frappe._("Artículo, cantidad o movimiento de ropa inválido"))
    if direction=="Loss" and not data.get("reason"):
        frappe.throw(frappe._("Indique el motivo de la pérdida"))
    entry = frappe.new_doc("Stock Entry")
    entry.company=prop.company
    entry.hs_stock_purpose="Waste" if direction=="Loss" else "Laundry"
    entry.stock_entry_type="Material Issue" if direction=="Loss" else "Material Transfer"
    entry.append("items",dict(item_code=item.name,qty=float(quantity),cost_center=prop.cost_center,
                               s_warehouse=prop.warehouse if direction=="Send" else prop.laundry_warehouse,
                               t_warehouse=None if direction=="Loss" else (prop.warehouse if direction=="Receive" else prop.laundry_warehouse)))
    post_standard(entry,prop)
    description = data.get("reason") or direction
    record = insert("HS Incident",prop,room=room.name,kind="Linen",description=description,
                    linen_direction=direction, item=item.name,quantity=float(quantity),
                    status="Resolved",stock_entry=entry.name, resolution=description,
                    resolved_by=frappe.session.user,resolved_at=frappe.utils.now_datetime())
    audit(prop,"Linen "+direction,record,data.get("reason"))
    return dict(incident=record.name,stock_entry=entry.name)
