"""Read-only stock ownership evidence for the two known ERPNext demo sites.

Run from the corresponding bench's sites directory with the site name as the
only argument. This does not assign warehouses, alter vouchers or post GL.
"""

import json
from collections import defaultdict
from pathlib import Path
import sys

import frappe


SITES = {
    "hospitality.localhost": Path("/home/frappe/benches/hospitality-bench"),
    "hospitality-cutover-audit.localhost": Path(
        "/home/frappe/benches/hospitality-bench"),
}


def run():
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        raise RuntimeError("Select one of the two known ERPNext demo sites")
    site = sys.argv[1]
    sites_path = SITES[site] / "sites"
    if Path.cwd().resolve() != sites_path.resolve():
        raise RuntimeError("Run from the matching bench sites directory")
    frappe.init(site, sites_path=str(sites_path))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite.erp_to_pms_preflight import preflight

        status = preflight()
        hotels = frappe.get_all("HS Property", fields=[
            "name", "property_name", "company", "warehouse",
            "laundry_warehouse"], order_by="name asc", limit_page_length=0)
        companies = sorted({row.company for row in hotels})
        warehouses = frappe.get_all("Warehouse", filters={
            "company": ["in", companies], "is_group": 0},
            fields=["name", "company", "hs_property", "disabled"],
            order_by="name asc", limit_page_length=0)
        bins = frappe.get_all("Bin", filters={
            "warehouse": ["in", [row.name for row in warehouses]]},
            fields=["warehouse", "item_code", "actual_qty", "stock_value"],
            order_by="warehouse asc,item_code asc", limit_page_length=0)
        by_warehouse = defaultdict(list)
        for row in bins:
            if row.actual_qty or row.stock_value:
                by_warehouse[row.warehouse].append({
                    "item": row.item_code, "quantity": str(row.actual_qty),
                    "stock_value": str(row.stock_value)})
        configured = defaultdict(list)
        for row in hotels:
            for field in ("warehouse", "laundry_warehouse"):
                if row.get(field):
                    configured[row[field]].append({
                        "property": row.name, "hotel": row.property_name,
                        "setting": field})
        entries = frappe.get_all("Stock Entry", filters={
            "company": ["in", companies], "docstatus": 1},
            fields=["name", "hs_property", "stock_entry_type",
                    "hs_stock_purpose", "posting_date"],
            order_by="posting_date asc,name asc", limit_page_length=0)
        entry_by_name = {row.name: row for row in entries}
        details = frappe.get_all("Stock Entry Detail", filters={
            "parent": ["in", list(entry_by_name)]},
            fields=["parent", "idx", "item_code", "s_warehouse",
                    "t_warehouse", "qty", "basic_amount"],
            order_by="parent asc,idx asc", limit_page_length=0) if entries else []
        lines = []
        for row in details:
            entry = entry_by_name[row.parent]
            lines.append({
                "voucher": row.parent, "voucher_property": entry.hs_property,
                "posting_date": str(entry.posting_date),
                "stock_entry_type": entry.stock_entry_type,
                "hs_stock_purpose": entry.hs_stock_purpose,
                "item": row.item_code, "source": row.s_warehouse,
                "target": row.t_warehouse, "quantity": str(row.qty),
                "basic_amount": str(row.basic_amount)})
        print(json.dumps({
            "site": site, "source_sha256": status["source_sha256"],
            "ready_for_mapping": status["ready_for_mapping"],
            "hotels": hotels,
            "warehouses": [{"name": row.name, "company": row.company,
                "owner": row.hs_property, "disabled": row.disabled,
                "configured_by": configured[row.name],
                "positions": by_warehouse[row.name]} for row in warehouses],
            "stock_entries": lines,
            "blockers": status["blockers"],
        }, ensure_ascii=False, default=str))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    run()
