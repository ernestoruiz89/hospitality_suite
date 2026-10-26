"""Rollback-only ERPNext-to-PMS stock opening rehearsal on a named test site.

The target already has an older fiscal rendering of the same seven demo
documents. Their rows are hidden inside a savepoint so this probe can import
the newly exported package, review the map, and rehearse the writer. No source
or target document is committed.
"""

import json
from pathlib import Path

import frappe


BENCH = Path("/home/frappe/frappe-bench")
SITE = "hs-pms-audit-target.local"
BUNDLE = "hs-erp-fiscal-cd26a7a0b2a047d48bbdce2c05077534.zip"
SOURCE_SHA256 = "b09d04e975e273cefef438febc0f3db3ab023aae09c71ba0dca5d9a9b0c11331"
MANIFEST_SHA256 = "17c3a5773be6ac726eb830633ee61b1d1a86d092f9d98aedc371c0511bb69bf3"
MAPPING = "reverse-audit-target-mapping.json"


def _archive_state():
    docs = frappe.get_all("HS Historical Fiscal Document",
        fields=["name", "source_key", "pdf_sha256"],
        order_by="name asc", limit_page_length=0)
    files = frappe.get_all("File", filters={
        "attached_to_doctype": "HS Historical Fiscal Document"},
        fields=["name", "file_url", "attached_to_name"],
        order_by="name asc", limit_page_length=0)
    return {"docs": [dict(row) for row in docs],
            "files": [dict(row) for row in files]}


def run():
    if Path.cwd().resolve() != (BENCH / "sites").resolve():
        raise RuntimeError("Run from the Frappe-only test bench sites directory")
    site_path = BENCH / "sites" / SITE
    config = json.loads((site_path / "site_config.json").read_text())
    if (config.get("db_name") != "hs_pms_audit_target" or
            not config.get("maintenance_mode") or
            not config.get("pause_scheduler")):
        raise RuntimeError("Only the paused disposable PMS target is allowed")
    private_files = (site_path / "private" / "files").resolve()
    if private_files.is_symlink() or not (private_files / BUNDLE).is_file():
        raise RuntimeError("The simulated source package is unavailable")
    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    from hospitality_suite import (erp_fiscal_history,
        erp_to_pms_mapping, erp_to_pms_transfer_plan,
        erp_to_pms_transfer_rehearsal, standalone_accounting)

    if standalone_accounting.provider() != "pms":
        raise RuntimeError("The target is no longer a PMS site")
    before = _archive_state()
    original_paths = {path.name for path in private_files.iterdir()
        if path.is_file()}
    mapping = json.loads((private_files / MAPPING).read_text())
    mapping["source_sha256"] = SOURCE_SHA256
    mapping["manifest_sha256"] = MANIFEST_SHA256
    manifest, source = erp_fiscal_history.load_source_inventory(BUNDLE,
        SOURCE_SHA256, MANIFEST_SHA256)
    if len(source["properties"]) != 2 or len(manifest["documents"]) != 7:
        raise RuntimeError("The simulated package is not the reviewed fixture")
    property_map = {name: cfg["property"]
        for name, cfg in mapping["properties"].items()}
    if set(property_map) != {"akoalnkvvg", "alj05n08v4"}:
        raise RuntimeError("The target map changed")

    frappe.db.savepoint("hs_reverse_stock_target_probe")
    try:
        source_keys = [row["source_key"] for row in manifest["documents"]]
        existing = frappe.get_all("HS Historical Fiscal Document", filters={
            "source_key": ["in", source_keys]}, pluck="name",
            limit_page_length=0)
        for name in existing:
            frappe.db.sql("DELETE FROM `tabFile` WHERE attached_to_doctype=%s "
                "AND attached_to_name=%s", ("HS Historical Fiscal Document", name))
            frappe.db.sql("DELETE FROM `tabHS Historical Fiscal Document` WHERE name=%s",
                name)
        imported = erp_fiscal_history.import_bundle(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256, property_map)
        reviewed = erp_to_pms_mapping.review(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256, mapping)
        planned = erp_to_pms_transfer_plan.review(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256, mapping)
        result = {"imported": imported, "mapping_ready": reviewed.get(
            "mapping_ready"), "mapping_blockers": reviewed.get("blockers"),
            "plan_ready": planned.get("ready_for_transfer"),
            "plan_blockers": planned.get("blockers"),
            "plan_sha256": planned.get("plan_sha256")}
        if reviewed.get("mapping_ready") and planned.get("ready_for_transfer"):
            rehearsal = erp_to_pms_transfer_rehearsal.rehearse(BUNDLE,
                SOURCE_SHA256, MANIFEST_SHA256, mapping, planned["plan_sha256"])
            result["rehearsal"] = {"reconciled": rehearsal["reconciled"],
                "rolled_back": rehearsal["rolled_back"],
                "properties": len(rehearsal["properties"])}
    finally:
        frappe.db.rollback(save_point="hs_reverse_stock_target_probe")
        frappe.clear_cache()
        for path in private_files.iterdir():
            if (path.is_file() and path.name not in original_paths and
                    path.resolve().parent == private_files and
                    not frappe.db.exists("File", {"file_url":
                        "/private/files/" + path.name})):
                path.unlink()
    after = _archive_state()
    after_paths = {path.name for path in private_files.iterdir()
        if path.is_file()}
    if (after != before or after_paths != original_paths or
            standalone_accounting.provider() != "pms"):
        raise AssertionError("The PMS target changed after the rehearsal")
    result["target_restored"] = True
    print(json.dumps(result, ensure_ascii=False, default=str))
    frappe.destroy()


if __name__ == "__main__":
    run()
