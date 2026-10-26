"""Read-only check of the isolated fresh-site demo stock fixture."""

import json
from pathlib import Path

import frappe


SITE = "hs-demo-stock-qa.localhost"
SITES = Path("/home/frappe/benches/hospitality-bench/sites")


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated test bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        if not frappe.conf.get("hospitality_allow_demo"):
            raise RuntimeError("The isolated demo site is not enabled")
        properties = frappe.get_all("HS Property", filters={"property_name": ["in", [
            "Hotel Jardín Demo", "Luna Demo · Por tiempo"]]},
            fields=["name", "property_name", "warehouse"], order_by="name asc")
        assert len(properties) == 2, properties
        assert len({row.warehouse for row in properties}) == 2
        result = []
        for row in properties:
            assert frappe.db.get_value("Warehouse", row.warehouse, "hs_property") == row.name
            details = frappe.get_all("Stock Entry Detail", filters={
                "item_code": "HS-DEMO-WATER", "t_warehouse": row.warehouse},
                fields=["parent", "qty"])
            assert len(details) == 1 and details[0].qty == 100, details
            entry = frappe.db.get_value("Stock Entry", details[0].parent,
                ["hs_property", "docstatus"], as_dict=True)
            assert entry.hs_property == row.name and entry.docstatus == 1, entry
            quantity = frappe.db.get_value("Bin", {"warehouse": row.warehouse,
                "item_code": "HS-DEMO-WATER"}, "actual_qty")
            assert quantity == 100, quantity
            gl_count = frappe.db.count("GL Entry", {"voucher_type": "Stock Entry",
                "voucher_no": details[0].parent, "is_cancelled": 0})
            assert gl_count >= 2, gl_count
            result.append({"property": row.name, "warehouse": row.warehouse,
                "receipt": details[0].parent, "quantity": quantity, "gl_entries": gl_count})
        from hospitality_suite.erp_to_pms_preflight import preflight

        status = preflight()
        assert not status["blockers"], status["blockers"]
        requirements = [{"property": row["property"], **{
            key: len(value) if isinstance(value, list) else {
                party: len(rows) for party, rows in value.items()}
            for key, value in row["mapping_requirements"].items()
            if key != "source_settings"}}
            for row in status["properties"]]
        print(json.dumps({"site": SITE, "properties": result,
            "ready_for_mapping": status["ready_for_mapping"],
            "mapping_requirements": requirements,
            "source_sha256": status["source_sha256"]}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
