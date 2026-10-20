"""Preserve the previous article for existing properties; never create an Item."""
import frappe


def execute():
    for row in frappe.get_all("HS Property",fields=["name","lodging_item","extra_hour_item"]):
        if not row.extra_hour_item and row.lodging_item:
            frappe.db.set_value("HS Property",row.name,"extra_hour_item",row.lodging_item,update_modified=False)
