"""Minimal shared Item catalogue for authorized operational pages."""
import frappe

from hospitality_suite.security import ACTIONS,is_system,require

FIELDS=["name","item_name","disabled","is_stock_item","is_fixed_asset","is_sales_item","is_purchase_item"]
PURPOSES={"any":{},"sale":{"is_sales_item":1,"is_fixed_asset":0},"stock":{"is_stock_item":1,"is_fixed_asset":0},
          "purchase":{"is_purchase_item":1,"is_fixed_asset":0},
          "laundry":{"is_sales_item":1,"is_stock_item":0,"is_fixed_asset":0}}


def item_label(name,label):
    # Only the app's original generated fixture has an operational alias.
    # A user-created master with the same words remains literal data.
    if name=='HS-DEMO-EXTRA-HOUR' and label=='Hora adicional de motel':
        return frappe._('Hora adicional por tiempo')
    return label


def display_rows(rows):
    for row in rows:row['display_name']=item_label(row.name,row.item_name)
    return rows


def authorize(property_name):
    prop=require(property_name)
    roles=set(frappe.get_roles())
    if not is_system() and not any(roles.intersection(ACTIONS[a]) for a in ("service","finance","clean","maintain","inventory","setup","report")):
        frappe.throw(frappe._("No tiene permiso para consultar el catálogo"),frappe.PermissionError)
    return prop


def search(property_name,txt="",purpose="any"):
    authorize(property_name)
    if not isinstance(purpose,str) or purpose not in PURPOSES or not isinstance(txt,str) or len(txt)>140:
        frappe.throw(frappe._("Indique una búsqueda válida de hasta 140 caracteres"))
    text=txt.strip().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
    matches=[["name","like","%"+text+"%"],["item_name","like","%"+text+"%"]] if text else None
    if text:
        legacy=frappe.db.get_value('Item',{'name':'HS-DEMO-EXTRA-HOUR','disabled':0},'item_name')
        if legacy=='Hora adicional de motel' and txt.strip().casefold() in item_label('HS-DEMO-EXTRA-HOUR',legacy).casefold():
            matches.append(['name','=','HS-DEMO-EXTRA-HOUR'])
    # Item is shared between companies in ERPNext. This explicit operational
    # projection exposes names/usage flags only, never prices, costs or balances.
    rows=frappe.get_all("Item",filters={"disabled":0,**PURPOSES[purpose]},
                        or_filters=matches,
                        fields=FIELDS,order_by="item_name asc,name asc",limit_page_length=51)
    return dict(items=display_rows(rows[:50]),has_more=len(rows)>50)


def bootstrap_items(data):
    """First choices plus every referenced name, without downloading the catalogue."""
    rows=frappe.get_all("Item",filters={"disabled":0},fields=FIELDS,order_by="item_name asc,name asc",limit_page_length=50)
    names={r.item for r in data.get("services",[]) if r.get("item")}
    names.update(r["item"] for order in data.get("purchase_orders",[]) for r in order.get("items",[]))
    names.update(r.get("item") for order in data.get("maintenance",[]) for r in order.get("parts",[]) if r.get("item"))
    names.difference_update(r.name for r in rows)
    if names:
        rows+=frappe.get_all("Item",filters={"name":["in",sorted(names)]},fields=FIELDS,order_by="item_name asc,name asc")
    return display_rows(rows)
