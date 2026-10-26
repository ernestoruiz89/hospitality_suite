"""Build a real target mapping on the isolated PMS cutover race fixture."""

import json
import os
from pathlib import Path

import frappe

from hospitality_suite import pms_cutover, pms_cutover_mapping, pms_cutover_plan
from hospitality_suite.pms_cutover_activation import _settings
from hospitality_suite.service import canonical


def run():
    if frappe.local.site != "hs-cutover-race.local":
        frappe.throw("Use only the isolated cutover race fixture")
    frappe.set_user("Administrator")
    source = pms_cutover.preflight()
    if not source["ready_for_mapping"] or len(source["properties"]) != 1:
        frappe.throw("Prepare a valid isolated PMS source before mapping")
    prop = source["properties"][0]
    companies = frappe.get_all("Company", pluck="name")
    targets = [name for name in companies if name != prop["organization"]]
    if len(targets) != 1:
        frappe.throw("The race fixture needs exactly one ERPNext target company")
    company = targets[0]
    output = Path(frappe.get_site_path("private", "files",
                                       "cutover-race-mapping.json"))
    if output.exists() or output.is_symlink():
        frappe.throw("The isolated mapping file already exists")
    year = str(prop["business_date"])[:4]
    if not frappe.db.exists("Fiscal Year", "HS Race FY " + year):
        frappe.get_doc({"doctype": "Fiscal Year", "year": "HS Race FY " + year,
            "year_start_date": year + "-01-01",
            "year_end_date": year + "-12-31",
            "companies": [{"company": company}]}).insert(ignore_permissions=True)
    for party_type, account_type in (("Customer", "Receivable"),
                                     ("Supplier", "Payable")):
        if not frappe.db.exists("Party Type", party_type):
            frappe.get_doc({"doctype": "Party Type", "party_type": party_type,
                "account_type": account_type}).insert(ignore_permissions=True)
    if not frappe.db.exists("Item Group", "All Item Groups"):
        frappe.get_doc({"doctype": "Item Group", "item_group_name":
                        "All Item Groups", "is_group": 1}).insert(
                            ignore_permissions=True)
    if not frappe.db.exists("UOM", "Nos"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
                        "must_be_whole_number": 1, "enabled": 1}).insert(
                            ignore_permissions=True)
    item = frappe.get_doc({"doctype": "Item", "item_code": "HS-RACE-ROOM",
        "item_name": "Alojamiento de ensayo", "is_stock_item": 0,
        "is_sales_item": 1, "item_group": "All Item Groups",
        "stock_uom": "Nos", "uom": "Nos"}).insert(ignore_permissions=True)
    price_list = frappe.get_doc({"doctype": "Price List",
        "price_list_name": "HS Race Sales", "currency": prop["currency"],
        "selling": 1, "enabled": 1})
    price_list.db_insert()
    frappe.get_doc({"doctype": "Item Price", "item_code": item.name,
        "price_list": price_list.name, "price_list_rate": 1,
        "currency": prop["currency"]}).insert(ignore_permissions=True)

    def account(**filters):
        name = frappe.db.get_value("Account", {"company": company,
            "is_group": 0, "account_currency": prop["currency"],
            **filters}, "name")
        if not name:
            frappe.throw("The target company lacks a required account")
        return name

    mapping = pms_cutover_mapping.template()
    config = mapping["properties"][prop["property"]]
    config["company"] = company
    config["cost_center"] = frappe.db.get_value("Cost Center",
        {"company": company, "is_group": 0}, "name")
    config["temporary_opening_account"] = account(account_type="Temporary")
    for source_account in frappe.get_all("HS Account", filters={
            "property": prop["property"]},
            fields=["name", "root_type", "account_type"]):
        config["accounts"][source_account.name] = (
            account(account_type="Cash") if source_account.account_type == "Cash"
            else account(account_name="Capital Stock") if source_account.root_type == "Equity"
            else account(root_type=source_account.root_type))
    config["target_settings"] = {
        "warehouse": frappe.db.get_value("Warehouse", {"company": company,
            "warehouse_name": "Stores", "is_group": 0}, "name"),
        "receivable_account": account(account_type="Receivable"),
        "guarantee_account": account(account_name="Customer Advances"),
        "lodging_item": item.name, "price_list": price_list.name,
        "tax_policy_confirmed": False,
    }
    _settings(mapping)
    reviewed = pms_cutover_plan.review(mapping)
    if not reviewed["cutover_inputs_consistent"]:
        blockers = {key: reviewed[key] for key in ("mapping_review",
            "plan", "link_manifest") if key in reviewed}
        frappe.throw("The isolated mapping is not ready: " +
                     canonical(blockers)[:3000])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(canonical(mapping) + "\n")
    os.chmod(output, 0o600)
    frappe.db.commit()
    return {"mapping_file": output.name, "source_sha256":
        reviewed["plan"]["source_sha256"],
        "plan_sha256": reviewed["plan"]["plan_sha256"],
        "link_sha256": reviewed["link_manifest"]["link_sha256"],
        "target_company": company}
