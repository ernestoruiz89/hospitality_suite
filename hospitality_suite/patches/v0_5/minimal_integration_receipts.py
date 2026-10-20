"""Remove arbitrary legacy provider bodies, without rewriting financial history."""
import json

import frappe

from hospitality_suite.integrations import receipt_metadata, is_receipt_metadata
from hospitality_suite.service import operation, audit, canonical


def execute():
    counts=dict(events=0,versions=0,errors=0)
    for row in frappe.get_all("HS Integration Event",fields=["name","property","payload","last_error"]):
        try:
            previous=json.loads(row.payload or "")
        except (ValueError,TypeError):
            previous=None
        changes={}
        if not is_receipt_metadata(previous):
            changes["payload"]=canonical(receipt_metadata((row.payload or "").encode(),source="legacy_payload"))
        if row.last_error:
            changes["last_error"]="LEGACY_ERROR_OMITTED"
            if row.last_error==changes["last_error"]:
                changes.pop("last_error")
        versions=0
        for version in frappe.get_all("Version",filters={"ref_doctype":"HS Integration Event","docname":row.name},fields=["name","data"]):
            data=json.loads(version.data or "{}")
            changed=data.get("changed",[])
            retained=[value for value in changed if not value or value[0] not in ("payload","last_error")]
            if retained!=changed:
                data["changed"]=retained
                data["hospitality_payload_policy"]="receipt-v1"
                frappe.db.set_value("Version",version.name,"data",canonical(data),update_modified=False)
                versions+=1
        if changes:
            frappe.db.set_value("HS Integration Event",row.name,changes,update_modified=False)
        if changes or versions:
            prop=frappe.get_doc("HS Property",row.property)
            with operation():
                audit(prop,"Integration receipt minimization",frappe.get_doc("HS Integration Event",row.name),
                      "Actualización a recibos sin contenido de proveedor",dict(policy="receipt-v1",payload_replaced="payload" in changes,
                                error_replaced="last_error" in changes,versions_redacted=versions))
            counts["events"]+=1
            counts["versions"]+=versions
            counts["errors"]+=int("last_error" in changes)
    return counts
