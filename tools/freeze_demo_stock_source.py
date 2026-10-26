"""Seal the reviewed stock-only ERPNext source after its complete native backup."""

import json
from pathlib import Path

import frappe


SITES = Path("/home/frappe/benches/hospitality-bench/sites")
SITE = "hs-demo-stock-qa.localhost"
BUNDLE = "hs-erp-fiscal-c5388f199da84ca8a8101f9698657d1a.zip"
SOURCE_SHA256 = "b1ccd819e0387f3a3b0fb17bc2d2bb5bac26c6a8a96482b6e4055df39d328e65"
MANIFEST_SHA256 = "0156de9079300c86bc854d345e056ba59fc28bc862a7ecd72ec48b66f9df52d6"


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated ERPNext test bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import erp_to_pms_freeze, pms_cutover_backup

        backup = pms_cutover_backup.prepare()
        sealed = erp_to_pms_freeze.export_frozen(SOURCE_SHA256, backup,
            BUNDLE, MANIFEST_SHA256)
        print(json.dumps({"site": SITE, "source_sha256": SOURCE_SHA256,
            "receipt_file": sealed["receipt_file"],
            "receipt_sha256": sealed["receipt_sha256"],
            "source_backup_sha256": sealed["backup_sha256"],
            "bundle_sha256": sealed["bundle_sha256"]}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
