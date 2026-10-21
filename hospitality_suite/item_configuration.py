"""Native Item bindings and the single price-selection rule used by services."""
import frappe
from frappe.utils import nowdate

from hospitality_suite.pricing import decimal
from hospitality_suite.service import current_all
from hospitality_suite.security import require


BINDINGS=(("lodging_item","Alojamiento"),("extra_hour_item","Horas adicionales por tiempo"),("timing_item","Entrada anticipada y salida tardía de hotel"))


def bindings(prop,snapshot=None):
    if snapshot and snapshot.get("charge_items"):
        return {field:snapshot["charge_items"].get(field) or prop.get(field) for field,_ in BINDINGS}
    result={field:prop.get(field) for field,_ in BINDINGS}
    if snapshot:  # A pre-0.4 contract did not distinguish its overtime article.
        result["extra_hour_item"]=result["extra_hour_item"] or result["lodging_item"]
    return result


def validate_bindings(prop):
    for field,label in BINDINGS:
        if prop.get(field):
            item=frappe.get_doc("Item",prop.get(field))
            if item.disabled or not item.is_sales_item or item.is_fixed_asset or item.is_stock_item:
                frappe.throw(frappe._("{0}: seleccione un servicio de venta habilitado, sin inventario").format(frappe._(label)))
            if field=="extra_hour_item" and item.name!=prop.lodging_item and frappe.db.get_value("UOM",item.stock_uom,"must_be_whole_number"):
                frappe.throw(frappe._("El artículo de horas adicionales debe usar una unidad que admita fracciones de hora"))
    if prop.mode in ("Motel","Mixed") and not prop.get("extra_hour_item") and frappe.db.exists("HS Rate",{"property":prop.name,"mode":"Motel","active":1,"extra_hour_rate":[">",0]}):
        frappe.throw(frappe._("Configure el artículo para horas adicionales de motel"))


def bound_item(prop,snapshot,field):
    name=bindings(prop,snapshot).get(field)
    if not name:
        frappe.throw(frappe._("Configure el artículo correspondiente antes de registrar este cargo"))
    item=frappe.get_doc("Item",name)
    if item.disabled or not item.is_sales_item or item.is_fixed_asset or item.is_stock_item:
        frappe.throw(frappe._("El artículo aceptado debe seguir habilitado como servicio de venta sin inventario"))
    return name


def hours_quantity(prop,snapshot,hours):
    selected=bindings(prop,snapshot)
    if selected["extra_hour_item"]==selected["lodging_item"]:
        return 1  # Legacy accommodation articles bill one accepted charge.
    quantity=decimal(hours)
    uom=frappe.db.get_value("Item",selected["extra_hour_item"],"stock_uom")
    if quantity%1 and frappe.db.get_value("UOM",uom,"must_be_whole_number"):
        frappe.throw(frappe._("El artículo aceptado debe admitir fracciones de hora en su unidad"))
    return quantity or 1


def prices(prop,item,currency,customer=None):
    price_list=prop.price_list or frappe.db.get_single_value("Selling Settings","selling_price_list")
    settings=frappe.db.get_value("Price List",price_list,["enabled","selling","currency"],as_dict=True) if price_list else None
    if not settings or not settings.enabled or not settings.selling or settings.currency!=currency:
        return price_list,[]
    uom=frappe.db.get_value("Item",item,"stock_uom")
    rows=current_all("Item Price",filters={"item_code":item,"price_list":price_list,"currency":currency,"selling":1},
                     fields=["name","price_list_rate","valid_from","valid_upto","customer","supplier","uom","batch_no","packing_unit"],order_by="name")
    rows=[r for r in rows if (not r.valid_from or str(r.valid_from)<=nowdate()) and (not r.valid_upto or str(r.valid_upto)>=nowdate())
          and (not r.customer or r.customer==customer) and not r.supplier and not r.batch_no and (not r.uom or r.uom==uom) and (r.packing_unit or 1)==1]
    specific=[r for r in rows if customer and r.customer==customer]
    return price_list,specific or rows


def selling_price(prop,item,currency,customer=None):
    _,rows=prices(prop,item,currency,customer)
    if len(rows)!=1 or decimal(rows[0].price_list_rate)<0:
        frappe.throw(frappe._("Configure un precio de venta vigente e inequívoco para este artículo"))
    return rows[0]


def configuration(property_name,item=None):
    from hospitality_suite.catalog import item_label
    prop=require(property_name,"setup")
    result=dict(modified=str(prop.modified),values={**bindings(prop),"price_list":prop.price_list},
                mappings=[dict(field=field,label=frappe._(label),item=prop.get(field),item_name=frappe.db.get_value("Item",prop.get(field),"item_name") if prop.get(field) else None) for field,label in BINDINGS],
                currency=prop.currency,price_list=prop.price_list or frappe.db.get_single_value("Selling Settings","selling_price_list"))
    for row in result['mappings']:row['display_name']=item_label(row['item'],row['item_name'])
    if item:
        if not isinstance(item,str) or len(item)>140:
            frappe.throw(frappe._("Seleccione un artículo válido"))
        source=frappe.get_doc("Item",item)
        if source.disabled or not source.is_sales_item or source.is_fixed_asset:
            frappe.throw(frappe._("El artículo no está habilitado para venta"))
        _,rows=prices(prop,item,prop.currency)
        result["service"]=dict(item=source.name,item_name=source.item_name,is_stock_item=bool(source.is_stock_item),
                               display_name=item_label(source.name,source.item_name),
                               status="Priced" if len(rows)==1 and decimal(rows[0].price_list_rate)>=0 else "Missing" if not rows else "Ambiguous",
                               rate=str(rows[0].price_list_rate) if len(rows)==1 and decimal(rows[0].price_list_rate)>=0 else None)
    return result
