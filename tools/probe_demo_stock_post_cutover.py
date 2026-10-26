"""Rollback-only stock count through the normal PMS API after cutover."""

import json
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import api
        from hospitality_suite.standalone_inventory import current_balance

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE):
            raise RuntimeError("The isolated stock opening is not active")
        properties = []
        for index in (1, 2):
            prop = frappe.get_doc("HS Property", {"property_name":
                "Hotel PMS inventario " + str(index)})
            product = frappe.db.get_value("HS Product", {"property": prop.name,
                "product_code": "HS-DEMO-WATER"}, "name")
            warehouse = frappe.db.get_value("HS Warehouse", {"property": prop.name,
                "warehouse_code": "DEMO-STOCK-" + str(index)}, "name")
            expense = frappe.db.get_value("HS Account", {"property": prop.name,
                "account_type": "Stock Adjustment"}, "name")
            properties.append((prop, product, warehouse, expense))
        baseline = {prop.name: current_balance(prop, product, warehouse)
            for prop, product, warehouse, _ in properties}
        counts = {prop.name: frappe.db.count("HS Stock Movement", {
            "property": prop.name}) for prop, _, _, _ in properties}
        frappe.db.savepoint("hs_demo_stock_post_cutover")
        try:
            results = []
            for prop, product, warehouse, expense in properties:
                payload = {"product": product, "warehouse": warehouse,
                    "counted_quantity": "99", "adjustment_account": expense,
                    "reference": "QA-POST-CUTOVER-" + prop.name,
                    "reason": "Ensayo reversible de faltante de una unidad"}
                key = "qa-post-cutover-count-" + prop.name
                first = api.execute(prop.name, "pms_count_stock", key, payload)
                repeated = api.execute(prop.name, "pms_count_stock", key, payload)
                if (first != repeated or
                        current_balance(prop, product, warehouse) !=
                        (Decimal(99), Decimal(990)) or
                        frappe.db.count("HS Stock Movement", {
                            "property": prop.name}) != counts[prop.name] + 1):
                    raise AssertionError("The count did not consume one unit idempotently")
                results.append({"property": prop.name,
                    "after_quantity": "99", "after_value_nio": "990"})
        finally:
            frappe.db.rollback(save_point="hs_demo_stock_post_cutover")
            frappe.clear_cache()
        if any(current_balance(prop, product, warehouse) != baseline[prop.name] or
               frappe.db.count("HS Stock Movement", {"property": prop.name}) !=
               counts[prop.name] for prop, product, warehouse, _ in properties):
            raise AssertionError("The post-cutover probe did not roll back")
        print(json.dumps({"site": SITE, "counts": results,
            "idempotent": True, "rolled_back": True}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
