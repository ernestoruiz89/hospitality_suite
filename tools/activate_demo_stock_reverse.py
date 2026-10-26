"""Commit the frozen stock-only reverse cutover on its disposable PMS site."""

import json
from pathlib import Path

import frappe

from rehearse_demo_stock_reverse import (BUNDLE, MANIFEST_SHA256,
    MAPPING_FILE, RECEIPT, RECEIPT_SHA256, SITE, SITES,
    SOURCE_BACKUP_SHA256, SOURCE_SHA256)


TARGET_BACKUP_FILE = "demo-stock-target-backup.json"
REFERENCE = "demo-stock-reverse-20261026"
MAPPING_SHA256 = "4efee05781115e2f2373b715b91c93e7b775b4aa38429ef7be32cc4a888a6806"
PLAN_SHA256 = "854a1d681cbac38b75dfa8f7ceb7264f51e35738da457630cf0794f2ab13d89b"


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import erp_to_pms_cli

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler")):
            raise RuntimeError("Only the paused disposable PMS site is allowed")
        backup = erp_to_pms_cli.prepare_backup_file(TARGET_BACKUP_FILE)
        reviewed = erp_to_pms_cli.review_file(MAPPING_FILE, RECEIPT,
            BUNDLE, source_sha256=SOURCE_SHA256,
            manifest_sha256=MANIFEST_SHA256,
            receipt_sha256=RECEIPT_SHA256,
            source_backup_sha256=SOURCE_BACKUP_SHA256)
        if (not reviewed["ready"] or reviewed["blockers"] or
                reviewed["mapping_sha256"] != MAPPING_SHA256 or
                reviewed["plan_sha256"] != PLAN_SHA256):
            raise AssertionError("The frozen map or opening plan changed")
        arguments = dict(source_sha256=SOURCE_SHA256,
            manifest_sha256=MANIFEST_SHA256,
            receipt_sha256=RECEIPT_SHA256,
            source_backup_sha256=SOURCE_BACKUP_SHA256,
            mapping_sha256=MAPPING_SHA256, plan_sha256=PLAN_SHA256,
            target_backup_sha256=backup["backup_sha256"],
            migration_reference=REFERENCE)
        first = erp_to_pms_cli.activate_file(MAPPING_FILE, RECEIPT,
            BUNDLE, TARGET_BACKUP_FILE, **arguments)
        second = erp_to_pms_cli.activate_file(MAPPING_FILE, RECEIPT,
            BUNDLE, TARGET_BACKUP_FILE, **arguments)
        if (first != second or not first["cutover_performed"] or
                first["property_count"] != 2):
            raise AssertionError("The persistent cutover did not retry idempotently")
        print(json.dumps({"site": SITE, "activation": first,
            "retry_identical": True,
            "target_backup_sha256": backup["backup_sha256"]},
            ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
