"""Run two identical cutovers against the disposable restored race site.

Requires a reviewed mapping and a complete frozen-site backup. A successful
run permanently activates ERPNext on hs-cutover-race.local only.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


BENCH = Path("/home/frappe/frappe-bench")
SITE = "hs-cutover-race.local"
MAPPING = "cutover-race-mapping.json"
DEFAULT_BACKUP = "cutover-race-backup-manifest.json"
REQUEST = "cutover-race-request.json"


def connect():
    import frappe

    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    return frappe


def private(name):
    return BENCH / "sites" / SITE / "private" / "files" / name


def worker(token, label):
    frappe = connect()
    try:
        from hospitality_suite.pms_cutover_cli import activate_file

        request = json.loads(private(REQUEST).read_text(encoding="utf-8"))
        if request["token"] != token or label not in ("A", "B"):
            raise RuntimeError("Race request does not match this worker")
        own = private(f"cutover-race-{token}-{label}.ready")
        other = private(f"cutover-race-{token}-{'B' if label == 'A' else 'A'}.ready")
        own.open("x").close()
        deadline = time.monotonic() + 30
        while not other.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("The other cutover worker did not start")
            time.sleep(0.05)
        result = activate_file(MAPPING, request["backup_file"],
                               **request["kwargs"])
        print(json.dumps({"worker": label, "result": result}), flush=True)
    finally:
        frappe.destroy()


def parent(backup_file):
    if not (BENCH / "sites" / SITE).is_dir():
        raise RuntimeError("The isolated restored race site is missing")
    frappe = connect()
    try:
        from hospitality_suite import pms_cutover_backup, pms_cutover_cli
        from hospitality_suite.standalone_accounting import provider

        if provider() != "pms" or frappe.db.count("HS Cutover Run"):
            raise RuntimeError("The isolated race site is already activated")
        review = pms_cutover_cli.review_file(MAPPING)
        if not review["ready"]:
            raise RuntimeError("The cutover mapping is no longer ready")
        backup = pms_cutover_backup.verify(
            pms_cutover_cli._json_file(backup_file))
        token = uuid4().hex[:12]
        request = {"token": token, "backup_file": backup_file, "kwargs": {
            "source_sha256": review["source_sha256"],
            "mapping_sha256": review["mapping_sha256"],
            "plan_sha256": review["plan_sha256"],
            "link_sha256": review["link_sha256"],
            "backup_sha256": backup["sha256"],
            "migration_reference": "HS-RACE-" + token.upper(),
        }}
        private(REQUEST).write_text(json.dumps(request), encoding="utf-8")
        os.chmod(private(REQUEST), 0o600)
    finally:
        frappe.destroy()

    command = [sys.executable, str(Path(__file__).resolve()), "worker", token]
    processes = [subprocess.Popen(command + [label], cwd=BENCH / "sites",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for label in ("A", "B")]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=180)
            if process.returncode:
                raise RuntimeError(f"Cutover worker failed: {stderr[-4000:]}")
            results.append(json.loads(stdout.strip().splitlines()[-1])["result"])
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

    frappe = connect()
    try:
        from hospitality_suite.standalone_accounting import provider

        runs = frappe.get_all("HS Cutover Run", fields=["name", "migration_reference"])
        if (provider() != "erpnext" or len(runs) != 1 or
                runs[0]["migration_reference"] != request["kwargs"]["migration_reference"] or
                results[0] != results[1] or
                results[0]["cutover_run"] != runs[0]["name"]):
            raise RuntimeError("The simultaneous activation did not return one acta")
        target = frappe.db.get_value("HS Property", "ESTAB-00001", "company")
        print(json.dumps({"serialized": True, "provider": provider(),
            "cutover_run": runs[0]["name"], "results_identical": True,
            "target_company": target,
            "target_gl_entries": frappe.db.count("GL Entry", {"company": target})}))
    finally:
        frappe.destroy()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        parent(DEFAULT_BACKUP)
    elif len(sys.argv) == 3 and sys.argv[1] == "--backup":
        parent(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "worker":
        worker(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("Run without arguments on the isolated restored race site")
