"""Rollback-only stock and GL cutover probe on the disposable ERPNext clone.

The historic cross-hotel transfers left a C$20 stock/GL ownership gap.
This test receives new stock into each hotel's own warehouse. For the old
gap, it posts one synthetic native transfer without Suite scope validation,
then tags the voucher for preflight attribution. This fixture is not a
supported hotel operation and never commits any voucher.
"""

import json
from decimal import Decimal
from pathlib import Path
import sys

import frappe


BENCH = Path("/home/frappe/benches/hospitality-bench")
SITE = "hospitality-cutover-audit.localhost"
HOTELS = (("akoalnkvvg", "Finished Goods - HSD", 10),
          ("alj05n08v4", "Stores - HSD", 5))


def run():
    export_bundle = sys.argv[1:] == ["--export-bundle"]
    if sys.argv[1:] and not export_bundle:
        raise RuntimeError("Only --export-bundle is accepted")
    if Path.cwd().resolve() != (BENCH / "sites").resolve():
        raise RuntimeError("Run from the isolated bench sites directory")
    config = json.loads((BENCH / "sites" / SITE / "site_config.json").read_text())
    if (config.get("db_name") != "hospitality_cutover_audit" or
            not config.get("maintenance_mode") or
            not config.get("pause_scheduler")):
        raise RuntimeError("Only the paused disposable audit clone is allowed")
    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    from hospitality_suite.accounting import post_standard
    from hospitality_suite.erp_to_pms_preflight import preflight

    before = preflight()
    expected = {("akoalnkvvg", "20"), ("alj05n08v4", "-20")}
    gaps = {(row.get("property"), str(row.get("difference")))
            for row in before["blockers"]
            if row.get("code") == "property_stock_gl_mismatch"}
    expected_operations = {
        ("delivered_service_warehouse_scope_invalid", "a74t16e5j7")}
    operations = {(row.get("code"), row.get("source"))
        for row in before["blockers"]
        if row.get("code") != "property_stock_gl_mismatch"}
    if gaps != expected or operations != expected_operations:
        raise RuntimeError("The clone no longer matches the reviewed test data")
    if any(frappe.db.get_value("Warehouse", warehouse, "hs_property") != name
            for name, warehouse, _ in HOTELS):
        raise RuntimeError("The test warehouses are not exclusively scoped")

    frappe.db.savepoint("hs_stock_cutover_simulation")
    try:
        receipts = []
        for name, warehouse, quantity in HOTELS:
            prop = frappe.get_doc("HS Property", name)
            receipt = frappe.new_doc("Stock Entry")
            receipt.update({"company": prop.company,
                "stock_entry_type": "Material Receipt",
                "remarks": "SIMULACIÓN REVERSIBLE: existencias nuevas por hotel"})
            receipt.append("items", {"item_code": "HS-DEMO-WATER",
                "qty": quantity, "t_warehouse": warehouse,
                "basic_rate": 10, "cost_center": prop.cost_center})
            post_standard(receipt, prop)
            receipts.append(receipt.name)
        received = preflight()
        if received["ready_for_mapping"]:
            raise AssertionError("New receipts unexpectedly hid the old stock gap")
        origin = frappe.get_doc("HS Property", HOTELS[0][0])
        transfer = frappe.new_doc("Stock Entry")
        transfer.update({"company": origin.company,
            "stock_entry_type": "Material Transfer",
            "hs_stock_purpose": "Transfer",
            "remarks": "SIMULACIÓN REVERSIBLE: devolución física de dos aguas"})
        transfer.append("items", {"item_code": "HS-DEMO-WATER",
            "qty": 2, "s_warehouse": HOTELS[0][1],
            "t_warehouse": HOTELS[1][1],
            "cost_center": origin.cost_center})
        # Suite correctly forbids a hotel-scoped cross-property transfer.
        # The isolated native fixture exists only to test the cutover reader
        # after the legacy physical attribution has been corrected.
        transfer.flags.ignore_permissions = True
        transfer.insert()
        transfer.submit()
        frappe.db.set_value("Stock Entry", transfer.name, "hs_property",
            origin.name, update_modified=False)
        frappe.clear_document_cache("Stock Entry", transfer.name)
        trial = preflight()
        remaining = {(row.get("code"), row.get("source"))
            for row in trial["blockers"]}
        if remaining != expected_operations:
            raise AssertionError("Stock correction did not isolate operational blockers")
        balances = []
        expected_values = {HOTELS[0][0]: Decimal("90"),
            HOTELS[1][0]: Decimal("2030")}
        for row in trial["properties"]:
            stock_value = sum((Decimal(str(position["stock_value"]))
                for position in row["stock"]["positions"]), Decimal(0))
            ledger_value = sum((Decimal(str(line["debit"])) -
                Decimal(str(line["credit"]))
                for line in row["ledger"]["lines"]
                if line["account_type"] == "Stock"), Decimal(0))
            if stock_value != ledger_value or stock_value != expected_values[row["property"]]:
                raise AssertionError("Synthetic hotel stock and GL do not reconcile")
            balances.append({"property": row["property"],
                "stock_value": str(stock_value),
                "stock_gl_balance": str(ledger_value)})
        result = {"baseline_sha256": before["source_sha256"],
            "received_ready": received["ready_for_mapping"],
            "trial_ready": trial["ready_for_mapping"],
            "stock_balanced": True,
            "trial_sha256": trial["source_sha256"],
            "synthetic_native_transfer": transfer.name,
            "receipts": receipts,
            "balances": balances,
            "positions": [{"property": row["property"],
                "stock_positions": row["stock"]["positions"]}
                for row in trial["properties"]],
            "blockers": trial["blockers"]}
        if export_bundle:
            if trial["blockers"]:
                raise RuntimeError("Resolve operational blockers before exporting")
            from hospitality_suite.erp_fiscal_history import export_bundle as export
            result["bundle"] = export(trial["source_sha256"])
    finally:
        frappe.db.rollback(save_point="hs_stock_cutover_simulation")
        frappe.clear_cache()
    after = preflight()
    if after["source_sha256"] != before["source_sha256"]:
        raise AssertionError("The disposable source changed after rollback")
    result["rolled_back"] = True
    result["after_sha256"] = after["source_sha256"]
    print(json.dumps(result, ensure_ascii=False, default=str))
    frappe.destroy()


if __name__ == "__main__":
    run()
