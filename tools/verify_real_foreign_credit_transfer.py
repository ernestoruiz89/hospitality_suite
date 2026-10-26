"""Move one rollback-only ERPNext USD credit bundle between the smoke sites.

Run from the Frappe bench with its Python environment. Both site scripts roll
back their database changes; this runner removes the exported private files.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


SOURCE_SITE = "hs-erp-smoke.local"
TARGET_SITE = "hs-pms-smoke.local"
FILE_PATTERN = re.compile(r"hs-erp-fiscal-[0-9a-f]{32}\.zip\Z")
METADATA_PATTERN = re.compile(r"hs-real-fx-credit-[0-9a-f]{32}\.json\Z")


def _execute(site, method, *args):
    command = ["bench", "--site", site, "execute", method]
    if args:
        command.extend(["--args", json.dumps(list(args))])
    result = subprocess.run(command, text=True, capture_output=True,
                            check=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{method} did not return a result")
    return json.loads(lines[-1])


def _site_file(site, name, pattern):
    if not pattern.fullmatch(name):
        raise ValueError("Unexpected smoke bundle file name")
    directory = (Path.cwd() / "sites" / site / "private" / "files").resolve()
    path = (directory / name).resolve()
    if path.parent != directory:
        raise ValueError("Smoke bundle left the site private directory")
    return path


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run():
    if not (Path.cwd() / "sites" / SOURCE_SITE / "site_config.json").is_file():
        raise RuntimeError("Run this verifier from the Frappe smoke bench")
    if not shutil.which("bench"):
        raise RuntimeError("bench is not available in PATH")
    created = []
    try:
        source = _execute(SOURCE_SITE,
            "hospitality_suite.tests.smoke_foreign_credit_source_bundle.run")
        zip_name = source["bundle_file"]
        receipt_name = source["metadata_file"]
        source_zip = _site_file(SOURCE_SITE, zip_name, FILE_PATTERN)
        source_receipt = _site_file(SOURCE_SITE, receipt_name,
                                    METADATA_PATTERN)
        created.extend([source_zip, source_receipt])
        target_zip = _site_file(TARGET_SITE, zip_name, FILE_PATTERN)
        target_receipt = _site_file(TARGET_SITE, receipt_name,
                                     METADATA_PATTERN)
        if target_zip.exists() or target_receipt.exists():
            raise RuntimeError("The target smoke file name already exists")
        shutil.copy2(source_zip, target_zip)
        created.append(target_zip)
        shutil.copy2(source_receipt, target_receipt)
        created.append(target_receipt)
        if _digest(source_zip) != _digest(target_zip):
            raise RuntimeError("The copied ERPNext ZIP changed")
        target = _execute(TARGET_SITE,
            "hospitality_suite.tests.smoke_foreign_credit_target_bundle.run",
            receipt_name)
        if not (target.get("real_erpnext_package") and
                target.get("opening_rehearsed_and_rolled_back") and
                target.get("fiscal_pdf_verified")):
            raise RuntimeError("The PMS opening rehearsal did not reconcile")
        return {"source_note": source["source_note"],
            "principal_usd": target["principal_usd"],
            "base_nio": target["base_nio"],
            "copied_zip_sha256": _digest(target_zip),
            "fiscal_pdf_verified": True,
            "opening_rehearsed_and_rolled_back": True}
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
