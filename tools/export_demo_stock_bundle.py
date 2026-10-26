"""Export only the reviewed, isolated two-hotel stock fixture for a cutover rehearsal."""

import json
from pathlib import Path

import frappe


SITE = "hs-demo-stock-qa.localhost"
SITES = Path("/home/frappe/benches/hospitality-bench/sites")


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated ERPNext test bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite.erp_to_pms_preflight import preflight
        from hospitality_suite.erp_fiscal_history import export_bundle

        status = preflight()
        if not status["ready_for_mapping"] or len(status["properties"]) != 2:
            raise RuntimeError("The demo stock source is not the reviewed two-hotel fixture")
        if any(len(row["stock"]["positions"]) != 1 or
               row["stock"]["positions"][0]["quantity"] != "100"
               for row in status["properties"]):
            raise RuntimeError("The stock fixture changed; review it before exporting")
        result = export_bundle(status["source_sha256"])
        print(json.dumps(result, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
