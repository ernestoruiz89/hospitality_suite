"""Complete permission-checked reads and explicit presentation pagination."""
import frappe


def permitted_all(doctype,*,filters=None,fields=None,or_filters=None,order_by="creation desc, name desc"):
    result=[]
    offset=0
    while True:
        batch=frappe.get_list(doctype,filters=filters,or_filters=or_filters,fields=fields or ["name"],
                              order_by=order_by,limit=500,offset=offset)
        result.extend(batch)
        if len(batch)<500:
            return result
        offset+=len(batch)


def page(records,offset=0,page_length=50):
    try:
        start,length=int(offset),int(page_length)
        if isinstance(offset,bool) or isinstance(page_length,bool) or float(offset)!=start or float(page_length)!=length:
            raise ValueError()
        if start<0 or not 1<=length<=200:
            raise ValueError()
    except (ValueError,TypeError,OverflowError):
        frappe.throw("Seleccione una página válida de hasta 200 registros")
    total=len(records)
    return dict(rows=records[start:start+length],columns=[k for k in records[0] if not k.startswith("_")] if records else [],
                offset=start,page_length=length,total=total,has_more=start+length<total)
