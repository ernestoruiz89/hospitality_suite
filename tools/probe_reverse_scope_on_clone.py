"""Reversible source-scope probe on one disposable ERPNext demo clone.

The assumed warehouse and voucher ownership is for diagnosis only. It must
never be used to authorize a cutover or repair original hotel records.
"""

import json
from pathlib import Path
import sys

import frappe


BENCH = Path("/home/frappe/benches/hospitality-bench")
SITE = "hospitality-cutover-audit.localhost"
FIRST = "akoalnkvvg"
SECOND = "alj05n08v4"


def run():
    inspect_stock = sys.argv[1:] == ["--inspect-stock"]
    apply_disposable = sys.argv[1:] == ["--apply-disposable-scope"]
    if sys.argv[1:] and not (apply_disposable or inspect_stock):
        raise RuntimeError("Only --apply-disposable-scope or --inspect-stock is accepted")
    if Path.cwd().resolve() != (BENCH / "sites") or not (BENCH / "sites" / SITE).is_dir():
        raise RuntimeError("Run only in the isolated cutover audit bench")
    config = json.loads((BENCH / "sites" / SITE / "site_config.json").read_text())
    if (config.get("db_name") != "hospitality_cutover_audit" or
            not config.get("maintenance_mode") or
            not config.get("pause_scheduler")):
        raise RuntimeError("The disposable site is not isolated")
    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    from hospitality_suite.erp_to_pms_preflight import preflight

    before = preflight()
    if len(before["properties"]) != 2 or not {
            row["property"] for row in before["properties"]} == {FIRST, SECOND}:
        raise RuntimeError("Unexpected properties in the disposable clone")
    if inspect_stock:
        vouchers = ("MAT-STE-2026-00001", "MAT-STE-2026-00002",
                    "MAT-STE-2026-00004", "MAT-STE-2026-00010")
        print(json.dumps({
            "blockers": [row for row in before["blockers"]
                if row["code"] == "property_stock_gl_mismatch"],
            "entries": frappe.get_all("Stock Entry",
                filters={"name": ["in", vouchers]},
                fields=["name", "hs_property", "stock_entry_type",
                        "hs_stock_purpose"], order_by="name asc"),
            "details": frappe.get_all("Stock Entry Detail",
                filters={"parent": ["in", vouchers]},
                fields=["parent", "item_code", "s_warehouse", "t_warehouse",
                        "qty", "basic_amount"], order_by="parent asc, idx asc"),
            "stock_ledger": frappe.get_all("Stock Ledger Entry",
                filters={"voucher_no": ["in", vouchers]},
                fields=["voucher_no", "item_code", "warehouse", "actual_qty",
                        "stock_value_difference"],
                order_by="voucher_no asc, creation asc"),
            "gl": frappe.get_all("GL Entry",
                filters={"voucher_no": ["in", vouchers], "is_cancelled": 0},
                fields=["voucher_no", "account", "debit", "credit"],
                order_by="voucher_no asc, name asc"),
            "all_stock_gl": frappe.get_all("GL Entry",
                filters={"account": "Stock In Hand - HSD", "is_cancelled": 0},
                fields=["voucher_type", "voucher_no", "debit", "credit"],
                order_by="posting_date asc, name asc", limit_page_length=0),
            "all_stock_ledger": frappe.get_all("Stock Ledger Entry",
                filters={"is_cancelled": 0},
                fields=["voucher_type", "voucher_no", "item_code", "warehouse",
                        "actual_qty", "stock_value_difference"],
                order_by="posting_date asc, name asc", limit_page_length=0),
        }, ensure_ascii=False, default=str))
        frappe.destroy()
        return
    if apply_disposable and before["source_sha256"] != (
            "39b9be65924a16eec35159536acdf9607e14179b5f7a3d6d95005e6fc32ed408"):
        raise RuntimeError("The clone no longer matches the reviewed probe baseline")
    frappe.db.savepoint("hs_clone_scope_probe")
    committed = False
    try:
        frappe.db.set_value("HS Property", FIRST, "warehouse",
                            "Finished Goods - HSD", update_modified=False)
        for warehouse, property_name in (
                ("Finished Goods - HSD", FIRST),
                ("Stores - HSD", SECOND),
                ("Goods In Transit - HSD", SECOND)):
            frappe.db.set_value("Warehouse", warehouse, "hs_property",
                                property_name, update_modified=False)
        for voucher in ("MAT-STE-2026-00001", "MAT-STE-2026-00002"):
            frappe.db.set_value("Stock Entry", voucher, "hs_property",
                                SECOND, update_modified=False)
        for doctype, names in (("HS Property", (FIRST,)),
                               ("Warehouse", ("Finished Goods - HSD",
                                              "Stores - HSD",
                                              "Goods In Transit - HSD")),
                               ("Stock Entry", ("MAT-STE-2026-00001",
                                                "MAT-STE-2026-00002"))):
            for name in names:
                frappe.clear_document_cache(doctype, name)
        trial = preflight()
        if apply_disposable:
            if not trial["ready_for_mapping"]:
                raise RuntimeError("The disposable attribution does not pass preflight")
            frappe.db.commit()
            committed = True
            marker = BENCH / "sites" / SITE / "private" / "files" / (
                "HS-DISPOSABLE-ATTRIBUTION-ONLY.txt")
            marker.write_text("Test-only hypothetical ownership of shared stock "
                "and warehouses. Never use as evidence of the original hotel's "
                "accounting ownership. Restore the 20261025_204735 backup to "
                "return to the original demo state.\n", encoding="utf-8")
    finally:
        if not committed:
            frappe.db.rollback(save_point="hs_clone_scope_probe")
        frappe.clear_cache()
    after = preflight()
    if after["source_sha256"] != (trial["source_sha256"] if committed else
                                  before["source_sha256"]):
        raise RuntimeError("The scope probe ended in an unexpected source state")
    print(json.dumps({
        "before_sha256": before["source_sha256"],
        "after_sha256": after["source_sha256"],
        "trial_ready": trial["ready_for_mapping"],
        "trial_blockers": trial["blockers"],
        "trial_gl_coverage": trial["gl_coverage"],
        "rolled_back": not committed,
        "disposable_attribution_applied": committed,
    }, ensure_ascii=False))
    frappe.destroy()


if __name__ == "__main__":
    run()
