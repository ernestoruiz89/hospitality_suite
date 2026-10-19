"""Backfill only dates demonstrated by immutable creation/submission audit."""
import frappe


def execute():
    rows=frappe.get_all("HS Payment",filters={"business_date":["is","not set"]},fields=["name","property","payment_entry","journal_entry"])
    if not rows:
        return
    direct={}
    native={}
    events=frappe.get_all("HS Audit Event",filters={"property":["in",list({r.property for r in rows})]},
                         fields=["property","source_doctype","source_name","business_date","action","details"],order_by="occurred_at asc,name asc")
    for event in events:
        if not event.business_date:
            continue
        if event.source_doctype=="HS Payment":
            direct.setdefault((event.property,event.source_name),event.business_date)
        if event.action=="on_submit":
            try:
                detail=frappe.parse_json(event.details or "{}")
            except (ValueError,TypeError):
                continue
            if isinstance(detail,dict) and detail.get("name") and detail.get("docstatus")==1 and detail.get("doctype") in ("Payment Entry","Journal Entry"):
                native.setdefault((event.property,detail["doctype"],detail.get("name")),event.business_date)
    for row in rows:
        day=direct.get((row.property,row.name)) or native.get((row.property,"Payment Entry",row.payment_entry)) or native.get((row.property,"Journal Entry",row.journal_entry))
        values=dict(business_date=day,business_date_source="Audit" if day else "Unknown")
        frappe.db.set_value("HS Payment",row.name,values,update_modified=False)
