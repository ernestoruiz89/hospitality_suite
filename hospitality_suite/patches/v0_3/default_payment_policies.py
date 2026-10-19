"""Preserve existing receipt behavior when policy columns are introduced."""
import frappe


def execute():
    for field in ("advance_policy","guarantee_policy"):
        for row in frappe.get_all("HS Property",fields=["name",field]):
            if not row.get(field):
                frappe.db.set_value("HS Property",row.name,field,"Manual",update_modified=False)
