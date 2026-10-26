"""One-time, committed PMS fixture on the isolated restored cutover test site."""

from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import operation


def run():
    if frappe.local.site != "hs-cutover-restore.local":
        frappe.throw("Use only the isolated cutover restore site")
    if not frappe.conf.get("maintenance_mode") or not frappe.conf.get("pause_scheduler"):
        frappe.throw("Freeze the isolated site before seeding restore evidence")
    if frappe.db.count("HS Property"):
        frappe.throw("The isolated restore site already contains hotels")
    frappe.set_user("Administrator")
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
            ignore_permissions=True)
    suffix = uuid4().hex[:6].upper()
    org = frappe.get_doc({"doctype": "HS Organization",
        "legal_name": "HS Restore Evidence " + suffix,
        "base_currency": "NIO", "active": 1}).insert(ignore_permissions=True)
    company = frappe.get_doc({"doctype": "Company",
        "company_name": "HS Restore Evidence " + suffix,
        "abbr": "R" + suffix, "country": "Nicaragua",
        "default_currency": "NIO"}).insert(ignore_permissions=True)
    frappe.db.set_single_value("HS Site Mode", "provider", "PMS")
    from frappe.model.naming import make_autoname

    prop = frappe.get_doc({"doctype": "HS Property",
        "name": make_autoname("ESTAB-.#####"),
        "property_name": "HS Restore Hotel " + suffix,
        "company": company.name, "organization": org.name,
        "currency": "NIO", "mode": "Hotel",
        "time_zone": "America/Managua", "close_time": "06:00:00",
        "business_date": str(frappe.utils.getdate())})
    prop.db_insert()
    cash = api.execute(prop.name, "pms_account", "restore-cash-" + suffix,
        {"account_code": "CASH-" + suffix, "account_name": "Caja de restauración",
         "root_type": "Asset", "account_type": "Cash", "account_currency": "NIO"})
    capital = api.execute(prop.name, "pms_account", "restore-equity-" + suffix,
        {"account_code": "EQUITY-" + suffix, "account_name": "Capital de restauración",
         "root_type": "Equity", "account_type": "Equity",
         "account_currency": "NIO"})
    opened = api.execute(prop.name, "pms_opening_balance", "restore-opening-" + suffix,
        {"reference": "RESTORE-" + suffix,
         "lines": [{"account": cash["account"], "debit": "123.45", "credit": "0"},
                   {"account": capital["account"], "debit": "0",
                    "credit": "123.45"}]})
    with operation(prop):
        evidence = frappe.get_doc({"doctype": "File",
            "file_name": "cutover-restore-evidence-" + suffix + ".txt",
            "content": "Hotel " + prop.name + " / asiento " + opened["journal"] + "\n",
            "is_private": 1, "attached_to_doctype": "HS Property",
            "attached_to_name": prop.name}).insert(ignore_permissions=True)
    if (not frappe.db.exists("HS Journal", opened["journal"]) or
            frappe.db.count("HS Journal Line", {"parent": opened["journal"]}) != 2 or
            not evidence.file_url):
        frappe.throw("The data-bearing fixture is incomplete")
    frappe.db.commit()
    return {"property": prop.name, "organization": org.name,
            "company": company.name, "journal": opened["journal"],
            "file": evidence.name, "file_url": evidence.file_url}
