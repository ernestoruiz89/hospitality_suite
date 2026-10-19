"""Minimal shared Item catalogue for authorized operational pages."""
import frappe

from hospitality_suite.security import ACTIONS,is_system,require

FIELDS=["name","item_name","disabled","is_stock_item","is_fixed_asset","is_sales_item","is_purchase_item"]
PURPOSES={"any":{},"sale":{"is_sales_item":1,"is_fixed_asset":0},"stock":{"is_stock_item":1,"is_fixed_asset":0},
          "purchase":{"is_purchase_item":1,"is_fixed_asset":0}}


def authorize(property_name):
    prop=require(property_name)
    roles=set(frappe.get_roles())
    if not is_system() and not any(roles.intersection(ACTIONS[a]) for a in ("service","clean","maintain","inventory","setup","report")):
        frappe.throw(frappe._("No tiene permiso para consultar el catálogo"),frappe.PermissionError)
    return prop


def search(property_name,txt="",purpose="any"):
    authorize(property_name)
    if not isinstance(purpose,str) or purpose not in PURPOSES or not isinstance(txt,str) or len(txt)>140:
        frappe.throw(frappe._("Indique una búsqueda válida de hasta 140 caracteres"))
    text=txt.strip().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
    # Item is shared between companies in ERPNext. This explicit operational
    # projection exposes names/usage flags only, never prices, costs or balances.
    rows=frappe.get_all("Item",filters={"disabled":0,**PURPOSES[purpose]},
                        or_filters=[["name","like","%"+text+"%"],["item_name","like","%"+text+"%"]] if text else None,
                        fields=FIELDS,order_by="item_name asc,name asc",limit_page_length=51)
    return dict(items=rows[:50],has_more=len(rows)>50)


def bootstrap_items(data):
    """First choices plus every referenced name, without downloading the catalogue."""
    rows=frappe.get_all("Item",filters={"disabled":0},fields=FIELDS,order_by="item_name asc,name asc",limit_page_length=50)
    names={r.item for r in data.get("services",[]) if r.get("item")}
    names.update(r["item"] for order in data.get("purchase_orders",[]) for r in order.get("items",[]))
    names.update(r.get("item") for order in data.get("maintenance",[]) for r in order.get("parts",[]) if r.get("item"))
    names.difference_update(r.name for r in rows)
    if names:
        rows+=frappe.get_all("Item",filters={"name":["in",sorted(names)]},fields=FIELDS,order_by="item_name asc,name asc")
    return rows
