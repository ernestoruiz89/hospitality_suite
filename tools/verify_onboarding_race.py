"""Exercise two simultaneous initial PMS property requests on a disposable site.

Run from a Frappe bench's sites directory with its environment Python. The
script commits the temporary property to make retry visibility realistic, then
removes only its own keyed rows.
"""

import multiprocessing as mp
import sys
import time
import uuid


def _worker(site, data, key, channel, wait_for_commit):
    import frappe
    from hospitality_suite import api

    frappe.init(site, sites_path=".")
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        if not wait_for_commit:
            channel.send(("started", None))
        result = api.create_property(data, key)
        if wait_for_commit:
            channel.send(("ready", result))
            channel.recv()
        frappe.db.commit()
        channel.send(("done", result))
    except Exception as exc:
        frappe.db.rollback()
        channel.send(("error", repr(exc)))
    finally:
        frappe.destroy()
        channel.close()


def run(site="hs-pms-smoke.local"):
    import frappe

    if not site.startswith("hs-pms-smoke"):
        raise RuntimeError("Use only a disposable hs-pms-smoke site")
    token = uuid.uuid4().hex[:10]
    legal_name = "Onboarding race " + token
    data = {"property_name": "Race hotel " + token,
            "new_organization": {"legal_name": legal_name,
                                 "tax_id": "", "tax_regime": "General"},
            "mode": "Mixed", "currency": "NIO",
            "time_zone": "America/Managua", "close_time": "06:00"}
    key = "onboarding-race-" + token
    context = mp.get_context("spawn")
    first_parent, first_child = context.Pipe()
    second_parent, second_child = context.Pipe()
    first = context.Process(target=_worker, args=(site, data, key, first_child, True))
    second = context.Process(target=_worker, args=(site, data, key, second_child, False))
    first.start()
    property_name = None
    try:
        if not first_parent.poll(60):
            raise RuntimeError("First request did not reach its commit barrier")
        first_state, first_value = first_parent.recv()
        if first_state != "ready":
            raise RuntimeError(f"First request failed: {first_value}")
        property_name = first_value["property"]
        second.start()
        if not second_parent.poll(30):
            raise RuntimeError("Second request did not start")
        second_state, second_value = second_parent.recv()
        if second_state != "started":
            raise RuntimeError(f"Second request failed: {second_value}")
        time.sleep(0.5)
        first_parent.send("commit")
        if not first_parent.poll(60) or not second_parent.poll(60):
            raise RuntimeError("Concurrent requests did not finish")
        first_done = first_parent.recv()
        second_done = second_parent.recv()
        if (first_done != ("done", first_value) or
                second_done != ("done", first_value)):
            raise AssertionError((first_done, second_done))
        first.join(10)
        second.join(10)
        if first.exitcode != 0 or second.exitcode != 0:
            raise RuntimeError("A worker exited abnormally")
        frappe.init(site, sites_path=".")
        frappe.connect()
        try:
            org = frappe.db.get_value("HS Property", property_name,
                                      "organization")
            assert org and frappe.db.count("HS Organization",
                {"legal_name": legal_name}) == 1
            assert frappe.db.count("HS Property",
                {"property_name": data["property_name"]}) == 1
            assert frappe.db.count("HS Request",
                {"property": property_name, "operation": "create_property"}) == 1
            print({"concurrent_replay": True, "property": property_name})
        finally:
            frappe.destroy()
    finally:
        if first.is_alive():
            first.terminate()
        if second.is_alive():
            second.terminate()
        first.join(10)
        if second.pid:
            second.join(10)
        frappe.init(site, sites_path=".")
        frappe.connect()
        try:
            names = frappe.get_all("HS Property", filters={
                "property_name": data["property_name"]}, pluck="name")
            for name in names:
                frappe.db.delete("HS Audit Event", {"property": name})
                frappe.db.delete("HS Request", {"property": name})
                frappe.db.delete("HS Property", {"name": name})
            frappe.db.delete("HS Organization", {"legal_name": legal_name})
            frappe.db.commit()
            assert not frappe.db.exists("HS Organization",
                {"legal_name": legal_name})
            assert not frappe.db.exists("HS Property",
                {"property_name": data["property_name"]})
        finally:
            frappe.destroy()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "hs-pms-smoke.local")
