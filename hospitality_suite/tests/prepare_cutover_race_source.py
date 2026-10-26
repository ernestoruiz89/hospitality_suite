"""Normalize the isolated restore fixture into a valid small PMS source.

This is intentionally restricted to hs-cutover-race.local and commits the
fixture. It does not alter the original restored sites or production data.
"""

import frappe
from frappe.utils import add_days


def run():
    if frappe.local.site != "hs-cutover-race.local":
        frappe.throw("Use only the isolated cutover race fixture")
    if frappe.db.get_single_value("HS Site Mode", "provider") != "PMS":
        frappe.throw("The race source must still use the PMS ledger")
    properties = frappe.get_all("HS Property", fields=["name", "company",
        "organization", "currency", "business_date"])
    if (len(properties) != 1 or frappe.db.count("HS Journal") != 1 or
            frappe.db.count("HS Daily Close") or frappe.db.count("HS Cutover Run")):
        frappe.throw("The isolated restore no longer matches the expected fixture")
    prop = properties[0]
    if prop.company == prop.organization or frappe.db.exists("Company", prop.organization):
        frappe.throw("The race fixture was already normalized")
    frappe.set_user("Administrator")
    source_company = frappe.get_doc({"doctype": "Company",
        "company_name": prop.organization, "abbr": "HSRC",
        "country": "Nicaragua", "default_currency": prop.currency}).insert(
            ignore_permissions=True)
    if source_company.name != prop.organization:
        frappe.throw("The PMS entity and source company names differ")
    old_company = prop.company
    frappe.db.set_value("HS Property", prop.name, {
        "hold_minutes": 15, "schedule_rounding_minutes": 60,
        "checkout_quote_minutes": 5,
        "lodging_charge_policy": "Arrival", "advance_policy": "Manual",
        "guarantee_policy": "Manual", "cancellation_fee_mode": "None",
        "no_show_fee_mode": "None"}, update_modified=False)
    changed = {}
    for name in frappe.get_all("DocType", filters={"module": "Hospitality Suite"},
                               pluck="name", limit_page_length=0):
        if not name.startswith("HS ") or not frappe.db.table_exists(name):
            continue
        if not frappe.get_meta(name).has_field("company"):
            continue
        rows = frappe.get_all(name, filters={"company": old_company},
            pluck="name", limit_page_length=0)
        for row in rows:
            frappe.db.set_value(name, row, "company", source_company.name,
                                update_modified=False)
        if rows:
            changed[name] = len(rows)
    previous = add_days(prop.business_date, -1)
    journal = frappe.db.get_value("HS Journal", {"property": prop.name}, "name")
    frappe.db.set_value("HS Journal", journal, {
        "posting_date": previous, "business_date": previous},
        update_modified=False)
    frappe.get_doc({"doctype": "HS Daily Close",
        "property": prop.name, "company": source_company.name,
        "business_date": previous, "revision": 1, "status": "Closed",
        "summary": "{}", "blockers": "[]",
        "closed_at": frappe.utils.now_datetime(),
        "reason": "Cierre histórico de la fuente aislada"}).db_insert()
    frappe.db.commit()
    return {"site": frappe.local.site, "source_company": source_company.name,
        "business_date": str(prop.business_date), "last_closed": str(previous),
        "rows_rescoped": changed}
