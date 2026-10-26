"""Rollback-only correction probe for one legacy cross-hotel demo service."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe


BENCH = Path("/home/frappe/benches/hospitality-bench")
SITE = "hospitality-cutover-audit.localhost"
PROPERTY = "akoalnkvvg"
SERVICE = "a74t16e5j7"
LEGACY_WAREHOUSE = "Stores - HSD"


def run():
    if Path.cwd().resolve() != (BENCH / "sites").resolve():
        raise RuntimeError("Run only from the isolated ERPNext bench")
    config = json.loads((BENCH / "sites" / SITE / "site_config.json").read_text())
    if (config.get("db_name") != "hospitality_cutover_audit" or
            not config.get("maintenance_mode") or
            not config.get("pause_scheduler")):
        raise RuntimeError("The disposable source is not isolated")
    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    from hospitality_suite import api, security
    from hospitality_suite.erp_to_pms_preflight import preflight

    before = preflight()
    service = frappe.get_doc("HS Service Request", SERVICE)
    if (service.property != PROPERTY or service.status != "Delivered" or
            service.stock_entry != "MAT-STE-2026-00009"):
        raise RuntimeError("The legacy demo service changed")
    original_allowed = security.warehouse_allowed
    frappe.db.savepoint("hs_legacy_service_probe")
    try:
        def allow_old_source(prop, warehouse):
            if prop.name == PROPERTY and warehouse == LEGACY_WAREHOUSE:
                return True
            return original_allowed(prop, warehouse)

        with patch.object(security, "warehouse_allowed",
                          side_effect=allow_old_source):
            result = api.execute(PROPERTY, "update_service", uuid4().hex,
                {"service": SERVICE, "status": "Returned",
                 "reason": "Corrección reversible de consumo de prueba entre hoteles",
                 "modified": str(service.modified)})
        after = preflight()
        output = {"result": result, "service_status":
            frappe.db.get_value("HS Service Request", SERVICE, "status"),
            "stock_entry_status": frappe.db.get_value("Stock Entry",
                service.stock_entry, "docstatus"),
            "before_sha256": before["source_sha256"],
            "trial_sha256": after["source_sha256"],
            "trial_blockers": after["blockers"]}
    finally:
        frappe.db.rollback(save_point="hs_legacy_service_probe")
        frappe.clear_cache()
    restored = preflight()
    if restored["source_sha256"] != before["source_sha256"]:
        raise AssertionError("The source did not return to its baseline")
    output["rolled_back"] = True
    print(json.dumps(output, ensure_ascii=False, default=str))
    frappe.destroy()


if __name__ == "__main__":
    run()
