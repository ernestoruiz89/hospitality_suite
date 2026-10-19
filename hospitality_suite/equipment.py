"""Operational equipment registry; optional accounting identity stays in Asset."""
import frappe

from hospitality_suite.schema import ROLES
from hospitality_suite.security import allowed_properties,is_system,ACTIONS,require
from hospitality_suite.service import current_all,locked_doc


def validate_equipment(doc):
    if doc.asset:
        asset=locked_doc("Asset",doc.asset)
        if asset.company!=doc.company or asset.hs_property!=doc.property or asset.docstatus==2 or asset.status in ("Scrapped","Sold"):
            frappe.throw(frappe._("Seleccione un activo vigente asignado al mismo establecimiento y compañía"))
        duplicates=current_all("HS Equipment",filters={"asset":asset.name,"name":["!=",doc.name]},pluck="name")
        if duplicates:
            frappe.throw(frappe._("El activo ya tiene un equipo operativo; conserve su historial"))
    old=doc.get_doc_before_save()
    if old and old.asset!=doc.asset and current_all("HS Maintenance Order",filters={"equipment":doc.name},pluck="name"):
        frappe.throw(frappe._("Conserve el activo del equipo que ya tiene mantenimiento registrado"))
    if old and (old.room!=doc.room or old.active!=doc.active) and current_all("HS Maintenance Order",filters={"equipment":doc.name,"status":["!=","Completed"]},pluck="name"):
        frappe.throw(frappe._("Complete las órdenes pendientes antes de mover o deshabilitar el equipo"))


def asset_permission(doc,user=None,permission_type=None,**kwargs):
    if is_system(user):
        return True
    roles=set(frappe.get_roles(user))
    permission_type=permission_type or kwargs.get("ptype")
    if roles.intersection(ROLES)=={"HS Auditor"} and permission_type not in (None,"read","select","print","export","report"):
        return False
    if roles.intersection(ROLES):
        return bool(roles.intersection(ACTIONS["inventory"]+["HS Auditor"])) and doc.hs_property in allowed_properties(user)
    return not doc.hs_property or doc.hs_property in allowed_properties(user)


def asset_query(user=None):
    if is_system(user):
        return ""
    roles=set(frappe.get_roles(user))
    props=",".join(frappe.db.escape(p) for p in allowed_properties(user)) or "NULL"
    if roles.intersection(ROLES):
        return f"`tabAsset`.hs_property IN ({props})" if roles.intersection(ACTIONS["inventory"]+["HS Auditor"]) else "1=0"
    return f"(`tabAsset`.hs_property IS NULL OR `tabAsset`.hs_property='' OR `tabAsset`.hs_property IN ({props}))"


def validate_asset(doc,method=None):
    old=doc.get_doc_before_save()
    for name in sorted({name for name in (doc.hs_property,old.hs_property if old else None) if name}):
        frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(name,))
    linked=frappe.qb.get_query("HS Equipment",filters={"asset":doc.name},fields=["name"],ignore_permissions=True,for_update=True).run()
    if old and old.hs_property!=doc.hs_property and linked:
        frappe.throw(frappe._("El activo está vinculado a un equipo; conserve su establecimiento"))
    if not doc.hs_property:
        if not is_system() and set(frappe.get_roles()).intersection(ROLES):
            frappe.throw(frappe._("Asigne el activo a un establecimiento autorizado"),frappe.PermissionError)
        return
    prop=require(doc.hs_property,"inventory")
    if doc.company!=prop.company:
        frappe.throw(frappe._("La compañía del activo no coincide con el establecimiento"))
