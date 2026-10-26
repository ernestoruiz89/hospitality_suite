"""Confirm and replay a sealed reverse-cutover bundle on the disposable clone.

The first call commits to hs-pms-smoke-reverse.local. Subsequent calls replay
the same acta. It never operates on any other site.
"""

import hashlib
import json
from pathlib import Path
import subprocess


SITE = "hs-pms-smoke-reverse.local"


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _one(root, pattern):
    files = list(root.glob(pattern))
    if len(files) != 1 or files[0].is_symlink() or files[0].resolve().parent != root.resolve():
        raise RuntimeError("Expected exactly one reviewed private artifact: " + pattern)
    return files[0]


def _execute(method, **kwargs):
    command = ["bench", "--site", SITE, "execute", method,
               "--kwargs", _canonical(kwargs)]
    completed = subprocess.run(command, capture_output=True, text=True,
                               check=False)
    if completed.returncode:
        raise RuntimeError("Bench verification failed: " +
                           completed.stdout[-1200:] + completed.stderr[-1200:])
    return json.loads(completed.stdout.strip().splitlines()[-1])


def run():
    bench = Path.cwd()
    site_root = bench / "sites" / SITE
    if (bench.resolve() != Path("/home/frappe/frappe-bench") or
            not (site_root / "site_config.json").is_file()):
        raise RuntimeError("Run only inside the isolated Frappe smoke bench")
    root = site_root / "private" / "files"
    mapping_file = _one(root, "hs-erp-map-*.json")
    receipt_file = _one(root, "hs-erp-freeze-*.json")
    target_backup_file = _one(root, "hs-reverse-target-backup-*.json")
    receipt_bytes = receipt_file.read_bytes()
    receipt = json.loads(receipt_bytes)
    bundle_file = root / receipt["bundle_file"]
    if bundle_file.is_symlink() or bundle_file.resolve().parent != root.resolve() or not bundle_file.is_file():
        raise RuntimeError("The sealed source ZIP is missing")
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    reference = "HS-REVERSE-PERSISTENT-" + receipt_sha256[:12]
    target_backup = json.loads(target_backup_file.read_text(encoding="utf-8"))
    target_backup_sha256 = hashlib.sha256(
        _canonical(target_backup).encode()).hexdigest()
    reviewed = _execute("hospitality_suite.erp_to_pms_cli.review_file",
        mapping_file=mapping_file.name, receipt_file=receipt_file.name,
        bundle_file=bundle_file.name,
        source_sha256=receipt["source_sha256"],
        manifest_sha256=receipt["manifest_sha256"],
        receipt_sha256=receipt_sha256,
        source_backup_sha256=receipt["backup_sha256"])
    if reviewed["ready"] and not reviewed["blockers"]:
        mapping_sha256 = reviewed["mapping_sha256"]
        plan_sha256 = reviewed["plan_sha256"]
    else:
        # After the first commit, the target correctly rejects a new plan
        # because it now has financial history. Replay the saved acta hashes.
        saved = _execute(
            "hospitality_suite.tests.smoke_reverse_persistent_target.verify",
            reference=reference)
        mapping_sha256 = hashlib.sha256(_canonical(json.loads(
            mapping_file.read_text(encoding="utf-8"))).encode()).hexdigest()
        if (saved["mapping_sha256"] != mapping_sha256 or
                saved["source_sha256"] != receipt["source_sha256"] or
                saved["manifest_sha256"] != receipt["manifest_sha256"] or
                saved["receipt_sha256"] != receipt_sha256 or
                saved["source_backup_sha256"] != receipt["backup_sha256"] or
                saved["target_backup_sha256"] != target_backup_sha256):
            raise RuntimeError("The saved cutover acta differs from the files")
        plan_sha256 = saved["plan_sha256"]
    args = {"mapping_file": mapping_file.name,
        "receipt_file": receipt_file.name,
        "bundle_file": bundle_file.name,
        "target_backup_file": target_backup_file.name,
        "source_sha256": receipt["source_sha256"],
        "manifest_sha256": receipt["manifest_sha256"],
        "receipt_sha256": receipt_sha256,
        "source_backup_sha256": receipt["backup_sha256"],
        "mapping_sha256": mapping_sha256,
        "plan_sha256": plan_sha256,
        "target_backup_sha256": target_backup_sha256,
        "migration_reference": reference}
    first = _execute("hospitality_suite.erp_to_pms_cli.activate_file", **args)
    second = _execute("hospitality_suite.erp_to_pms_cli.activate_file", **args)
    if first != second or not first["cutover_performed"]:
        raise RuntimeError("The committed cutover did not replay its acta")
    stale = subprocess.run(["bench", "--site", SITE, "execute",
        "hospitality_suite.erp_to_pms_cli.activate_file", "--kwargs",
        _canonical({**args, "plan_sha256": "1" * 64})],
        capture_output=True, text=True, check=False)
    if (stale.returncode == 0 or
            "El reintento no coincide con el corte aplicado" not in
            stale.stdout + stale.stderr):
        raise RuntimeError("A different plan was accepted after the commit")
    checked = _execute(
        "hospitality_suite.tests.smoke_reverse_persistent_target.verify",
        reference=reference)
    if checked["cutover_run"] != first["cutover_run"]:
        raise RuntimeError("A new process read a different acta")
    return {"cutover_run": first["cutover_run"],
        "migration_reference": reference,
        "target_backup_sha256": target_backup_sha256,
        "replay_identical": True,
        "different_plan_rejected": True, **checked}


if __name__ == "__main__":
    print(_canonical(run()))
