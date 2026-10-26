"""Read-only scope and eligibility probe for the React PMS journal views."""

import frappe
from uuid import uuid4

from hospitality_suite import api
from hospitality_suite.standalone_accounting import provider


SITE = "hs-pms-demo-stock-qa.local"


def inspect():
    if frappe.local.site != SITE or provider() != "pms":
        frappe.throw("Use only the isolated PMS stock cutover site")
    frappe.set_user("Administrator")
    properties = frappe.get_all("HS Property", pluck="name",
        order_by="name asc", limit_page_length=0)
    if len(properties) != 2:
        frappe.throw("The journal probe requires the two-hotel synthetic clone")
    results = []
    for name in properties:
        status = api.pms_opening_balance_status(name)
        page = api.pms_reversible_journals(name, page_length=25)
        if (status["available"] != (not frappe.db.exists("HS Journal", {
                "property": name})) or page["total"] < len(page["rows"]) or
                any(frappe.db.get_value("HS Journal", row["name"],
                    "property") != name or row["source_doctype"] not in
                    ("HS Manual Journal", "HS Opening Balance") or
                    not row["lines"] for row in page["rows"])):
            frappe.throw("The journal workspace crossed a hotel or state")
        results.append({"property": name, "opening_available":
            status["available"], "reversible_total": page["total"],
            "journal_count": frappe.db.count("HS Journal", {
                "property": name})})
    return {"journal_workspace_scoped": True, "properties": results}


def exercise():
    inspected = inspect()
    property_name, other_name = [row["property"] for row in inspected["properties"]]
    prop = frappe.get_doc("HS Property", property_name)
    accounts = [row for row in api.pms_accounts(property_name)
        if row["manual_enabled"] and row["account_currency"] == prop.currency]
    if len(accounts) < 2:
        frappe.throw("The synthetic clone needs two manual base-currency accounts")
    marker = uuid4().hex[:12]
    frappe.db.savepoint("hs_journal_workspace_probe")
    try:
        manual = api.execute(property_name, "pms_manual_journal",
            "journal-workspace-" + marker,
            {"reference": "QA-JOURNAL-" + marker,
             "reason": "Verificación reversible del formulario contable",
             "lines": [
                 {"account": accounts[0]["name"], "debit": "5.00",
                  "credit": "0"},
                 {"account": accounts[1]["name"], "debit": "0",
                  "credit": "5.00"}]})
        page = api.pms_reversible_journals(property_name,
            search=manual["journal"])
        other = api.pms_reversible_journals(other_name,
            search=manual["journal"])
        if (page["total"] != 1 or len(page["rows"]) != 1 or
                page["rows"][0]["name"] != manual["journal"] or
                len(page["rows"][0]["lines"]) != 2 or other["total"]):
            frappe.throw("The new manual journal was not scoped in React")
        reversed_entry = api.execute(property_name, "pms_reverse_journal",
            "journal-workspace-reversal-" + marker,
            {"journal": manual["journal"],
             "reason": "Ensayo de reversión del asiento manual"})
        after = api.pms_reversible_journals(property_name,
            search=manual["journal"])
        if (after["total"] or reversed_entry["reversed"] != manual["journal"] or
                frappe.db.get_value("HS Journal", reversed_entry["journal"],
                    "reversal_of") != manual["journal"]):
            frappe.throw("The reversed journal remained selectable")
        return {"manual_journal_selected_once": True,
            "other_hotel_excluded": True, "reversed_journal_excluded": True}
    finally:
        frappe.db.rollback(save_point="hs_journal_workspace_probe")
