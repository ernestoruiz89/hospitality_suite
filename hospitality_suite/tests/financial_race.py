"""Run two financial commands in independent Frappe database sessions."""

import threading
from concurrent.futures import ThreadPoolExecutor

import frappe

from hospitality_suite import api
from hospitality_suite.service import lock_property


def race_command(site, sites_path, prop_name, action, payload, key, *, same_key):
    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    other_key = key if same_key else key + "-different"

    def first():
        frappe.init(site=site, sites_path=str(sites_path))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(prop_name, "approve")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The second financial command did not arrive")
            result = api.execute(prop_name, action, key, payload)
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.destroy()

    def second():
        if not held.wait(15):
            raise AssertionError("The first financial command did not lock the hotel")
        frappe.init(site=site, sites_path=str(sites_path))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            attempting.set()
            try:
                result = api.execute(prop_name, action, other_key, payload)
            except (frappe.ValidationError, frappe.TimestampMismatchError):
                frappe.db.rollback()
                return {"status": "rejected"}
            frappe.db.commit()
            return {"status": "posted", "result": result}
        finally:
            second_done.set()
            frappe.destroy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first)
        two = pool.submit(second)
        try:
            if not held.wait(15) or not attempting.wait(15):
                raise AssertionError("Both independent sessions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The second financial command bypassed the hotel lock")
        finally:
            release.set()
        first_result = one.result(timeout=30)
        second_result = two.result(timeout=30)
    if first_result["status"] != "posted":
        raise AssertionError("The first financial command did not post")
    if same_key and second_result != first_result:
        raise AssertionError("A same-key command did not return its first result")
    if not same_key and second_result["status"] != "rejected":
        raise AssertionError("Two distinct commands changed the same document")
    return first_result["result"]
