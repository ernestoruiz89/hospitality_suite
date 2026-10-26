"""Copy and rehearse one real ERPNext foreign supplier credit on PMS smoke."""

import json
import re
import shutil
from pathlib import Path

from verify_real_foreign_credit_transfer import (
    FILE_PATTERN, SOURCE_SITE, TARGET_SITE, _digest, _execute, _site_file)


RECEIPT_PATTERN = re.compile(r"hs-real-fx-vendor-[0-9a-f]{32}\.json\Z")


def run():
    if not (Path.cwd() / "sites" / SOURCE_SITE / "site_config.json").is_file():
        raise RuntimeError("Run this verifier from the Frappe smoke bench")
    if not shutil.which("bench"):
        raise RuntimeError("bench is not available in PATH")
    created = []
    try:
        source = _execute(SOURCE_SITE,
            "hospitality_suite.tests.smoke_foreign_supplier_credit_source_bundle.run")
        zip_name = source["bundle_file"]
        receipt_name = source["metadata_file"]
        source_zip = _site_file(SOURCE_SITE, zip_name, FILE_PATTERN)
        source_receipt = _site_file(SOURCE_SITE, receipt_name, RECEIPT_PATTERN)
        created.extend([source_zip, source_receipt])
        target_zip = _site_file(TARGET_SITE, zip_name, FILE_PATTERN)
        target_receipt = _site_file(TARGET_SITE, receipt_name, RECEIPT_PATTERN)
        if target_zip.exists() or target_receipt.exists():
            raise RuntimeError("The target smoke file name already exists")
        shutil.copy2(source_zip, target_zip)
        created.append(target_zip)
        shutil.copy2(source_receipt, target_receipt)
        created.append(target_receipt)
        if _digest(source_zip) != _digest(target_zip):
            raise RuntimeError("The copied ERPNext ZIP changed")
        target = _execute(TARGET_SITE,
            "hospitality_suite.tests.smoke_foreign_supplier_credit_target_bundle.run",
            receipt_name)
        if not (target.get("real_erpnext_package") and
                target.get("opening_rehearsed_and_rolled_back") and
                target.get("mapping_reconciled")):
            raise RuntimeError("The PMS opening rehearsal did not reconcile")
        return {"source_note": source["source_note"],
            "principal_usd": target["principal_usd"],
            "base_nio": target["base_nio"],
            "copied_zip_sha256": _digest(target_zip),
            "opening_rehearsed_and_rolled_back": True}
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
