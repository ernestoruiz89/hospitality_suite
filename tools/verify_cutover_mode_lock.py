"""Verify the sitewide cutover row serializes two independent DB connections.

Run with the bench Python on the isolated ERP smoke site. This probe reads the
provider row, holds its transaction lock, and rolls both transactions back.
"""

import json
import select
import subprocess
import sys
import time
from pathlib import Path


BENCH = Path("/home/frappe/frappe-bench")
SITE = "hs-erp-smoke.local"


def child(role):
    import frappe

    frappe.init(SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    try:
        from hospitality_suite.pms_cutover_activation import _locked_mode

        if role == "holder":
            mode = _locked_mode()
            print("LOCKED " + json.dumps({"provider": mode.provider}), flush=True)
            if (not select.select([sys.stdin], [], [], 30)[0] or
                    sys.stdin.readline() != "release\n"):
                raise RuntimeError("The lock holder was not released")
        else:
            print("ATTEMPT", flush=True)
            start = time.monotonic()
            mode = _locked_mode()
            print("ACQUIRED " + json.dumps({"provider": mode.provider,
                "wait_seconds": round(time.monotonic() - start, 3)}), flush=True)
    finally:
        frappe.db.rollback()
        frappe.destroy()


def event(process, prefix):
    ready, _, _ = select.select([process.stdout], [], [], 30)
    if not ready:
        raise RuntimeError(f"Timed out waiting for {prefix}")
    line = process.stdout.readline().strip()
    if not line.startswith(prefix):
        raise RuntimeError(f"Expected {prefix}; child returned {line!r}")
    return json.loads(line[len(prefix):]) if len(line) > len(prefix) else None


def parent():
    if not BENCH.is_dir() or not (BENCH / "sites" / SITE).is_dir():
        raise RuntimeError("Use the existing isolated ERP smoke bench")
    command = [sys.executable, str(Path(__file__).resolve())]
    holder = subprocess.Popen(command + ["holder"], cwd=BENCH / "sites",
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1)
    waiter = None
    try:
        locked = event(holder, "LOCKED ")
        waiter = subprocess.Popen(command + ["waiter"], cwd=BENCH / "sites",
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        event(waiter, "ATTEMPT")
        time.sleep(0.5)
        if waiter.poll() is not None:
            raise RuntimeError("The second connection passed the held cutover lock")
        holder.stdin.write("release\n")
        holder.stdin.flush()
        acquired = event(waiter, "ACQUIRED ")
        holder.wait(timeout=30)
        waiter.wait(timeout=30)
        if (holder.returncode or waiter.returncode or
                acquired["provider"] != locked["provider"] or
                acquired["wait_seconds"] < 0.45):
            raise RuntimeError("The provider row did not serialize connections")
        print(json.dumps({"serialized": True, "provider": locked["provider"],
            "wait_seconds": acquired["wait_seconds"]}))
    finally:
        for process in (waiter, holder):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        parent()
    elif len(sys.argv) == 2 and sys.argv[1] in {"holder", "waiter"}:
        child(sys.argv[1])
    else:
        raise SystemExit("Run without arguments on the ERP smoke bench")
