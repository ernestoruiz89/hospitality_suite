"""Read-only, separate-process audit of the committed two-hotel PMS opening."""

import json
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES, SOURCE_SHA256


def balance(prop, account):
    value = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit-l.credit),0) "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s",
        (prop, account), as_list=True)[0][0]
    return Decimal(str(value))


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite.standalone_inventory import current_balance

        mode = frappe.get_single("HS Site Mode")
        runs = frappe.get_all("HS ERP to PMS Cutover Run",
            fields=["name", "migration_reference", "source_sha256"])
        if (mode.provider != "PMS" or mode.migration_reference != REFERENCE or
                len(runs) != 1 or runs[0].migration_reference != REFERENCE or
                runs[0].source_sha256 != SOURCE_SHA256):
            raise AssertionError("The confirmed cutover receipt is missing")
        result = []
        for index in (1, 2):
            prop = frappe.get_doc("HS Property", {"property_name":
                "Hotel PMS inventario " + str(index)})
            product = frappe.get_doc("HS Product", {"property": prop.name,
                "product_code": "HS-DEMO-WATER"})
            warehouse = frappe.get_doc("HS Warehouse", {"property": prop.name,
                "warehouse_code": "DEMO-STOCK-" + str(index)})
            quantity, value = current_balance(prop, product.name, warehouse.name)
            if (quantity, value) != (Decimal(100), Decimal(1000)):
                raise AssertionError("The hotel's opening stock is not 100/C$1,000")
            movements = frappe.get_all("HS Stock Movement", filters={
                "property": prop.name, "product": product.name,
                "warehouse": warehouse.name},
                fields=["name", "source_doctype", "quantity_delta", "value_delta"])
            if (len(movements) != 1 or
                    movements[0].source_doctype != "ERPNext Opening Stock" or
                    Decimal(str(movements[0].quantity_delta)) != 100 or
                    Decimal(str(movements[0].value_delta)) != 1000):
                raise AssertionError("The stock opening is missing or duplicated")
            bridge = frappe.db.get_value("HS Account", {"property": prop.name,
                "account_code": "1990"}, "name")
            if (balance(prop.name, product.inventory_account) != 1000 or
                    balance(prop.name, bridge) != 0 or
                    frappe.db.count("HS Journal", {"property": prop.name}) != 2):
                raise AssertionError("The stock ledger or bridge does not reconcile")
            result.append({"property": prop.name, "warehouse": warehouse.name,
                "quantity": str(quantity), "value_nio": str(value),
                "stock_gl_nio": "1000", "bridge_nio": "0"})
        print(json.dumps({"site": SITE, "cutover_run": runs[0].name,
            "migration_reference": REFERENCE, "properties": result},
            ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
