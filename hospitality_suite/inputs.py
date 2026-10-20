"""Bounded JSON objects at authenticated and public application boundaries."""
import json

import frappe


def object_payload(value):
    try:
        if isinstance(value,str):
            if len(value)>100000:
                frappe.throw(frappe._("Solicitud demasiado grande"))
            value=json.loads(value)
        if not isinstance(value,dict):
            frappe.throw(frappe._("Se requiere un objeto JSON"))
        # Apply the same bounds to Frappe's already-decoded JSON bodies.
        encoded=json.dumps(value,ensure_ascii=False,allow_nan=False)
        if len(encoded)>100000:
            frappe.throw(frappe._("Solicitud demasiado grande"))
        pending=[(value,0)]
        while pending:
            node,depth=pending.pop()
            if depth>32:
                frappe.throw(frappe._("La solicitud contiene demasiados niveles"))
            if isinstance(node,dict):
                if any(not isinstance(key,str) for key in node):
                    frappe.throw(frappe._("Las claves del objeto JSON deben ser texto"))
                pending.extend((child,depth+1) for child in node.values())
            elif isinstance(node,(list,tuple)):
                pending.extend((child,depth+1) for child in node)
    except (ValueError,TypeError,RecursionError):
        frappe.throw(frappe._("Se requiere un objeto JSON válido con valores finitos"))
    return value
