"""Exercise the shared command boundary with two independent database sessions.

Run only on the disposable Frappe-only PMS site. The temporary hotel and its
customers are removed after both same-key and conflicting-payload races.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import lock_property
from hospitality_suite.standalone_accounting import provider


SITE = "hs-pms-smoke-room.local"


def _race(sites_path, property_name, request_key, first_data, second_data):
    locked = Event()
    attempting = Event()
    release = Event()
    second_done = Event()

    def session(data, *, first):
        frappe.init(site=SITE, sites_path=sites_path)
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            if first:
                lock_property(property_name, "finance")
                locked.set()
                if not attempting.wait(15) or not release.wait(15):
                    raise AssertionError("The second request did not start")
            elif not locked.wait(15):
                raise AssertionError("The first request did not lock the hotel")
            else:
                attempting.set()
            try:
                result = api.execute(property_name, "pms_customer", request_key, data)
            except frappe.ValidationError:
                frappe.db.rollback()
                return {"status": "rejected"}
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            if not first:
                second_done.set()
            frappe.destroy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(session, first_data, first=True)
        two = pool.submit(session, second_data, first=False)
        try:
            if not locked.wait(15) or not attempting.wait(15):
                raise AssertionError("Both database sessions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The second request bypassed the hotel lock")
        finally:
            release.set()
        return one.result(timeout=30), two.result(timeout=30)


def run():
    if (frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps() or
            provider() != "pms" or frappe.session.user != "Administrator"):
        frappe.throw("Use only the disposable Frappe-only PMS site as Administrator")
    sites_path = str(Path(frappe.local.sites_path).resolve())
    suffix = uuid4().hex[:12]
    property_name = None
    organization = None
    try:
        created = api.create_property({
            "property_name": "Concurrency QA " + suffix,
            "new_organization": {"legal_name": "Concurrency Legal " + suffix},
            "currency": "NIO", "mode": "Hotel",
        }, "concurrency-property-" + suffix)
        property_name = created["property"]
        organization = frappe.db.get_value("HS Property", property_name,
            "organization")
        frappe.db.commit()

        first_data = {"party_name": "Concurrent Guest " + suffix}
        one, two = _race(sites_path, property_name,
            "concurrency-customer-" + suffix, first_data, first_data)
        frappe.db.rollback()
        if (one["status"] != "posted" or two != one or
                frappe.db.count("HS Party", {"property": property_name}) != 1 or
                frappe.db.count("HS Request", {"property": property_name,
                    "operation": "pms_customer"}) != 1):
            raise AssertionError("A concurrent same-key retry duplicated the customer")

        changed = {"party_name": "Conflicting Guest " + suffix}
        three, four = _race(sites_path, property_name,
            "concurrency-conflict-" + suffix, changed,
            {"party_name": "Different Guest " + suffix})
        frappe.db.rollback()
        if (three["status"] != "posted" or four["status"] != "rejected" or
                frappe.db.count("HS Party", {"property": property_name}) != 2 or
                frappe.db.count("HS Request", {"property": property_name,
                    "operation": "pms_customer"}) != 2 or
                frappe.db.exists("HS Party", {"property": property_name,
                    "party_name": "Different Guest " + suffix})):
            raise AssertionError("A conflicting payload used the same request key")
        return {"site": SITE, "independent_sessions": 2,
            "same_key": "same_result", "conflicting_payload": "rejected",
            "customers_created": 2, "requests_recorded": 2}
    finally:
        frappe.db.rollback()
        if property_name:
            for doctype in ("HS Party", "HS Audit Event", "HS Request"):
                frappe.db.delete(doctype, {"property": property_name})
            frappe.db.delete("HS Property", {"name": property_name})
        if organization:
            frappe.db.delete("HS Organization", {"name": organization})
        frappe.db.commit()
        if (property_name and frappe.db.exists("HS Property", property_name) or
                organization and frappe.db.exists("HS Organization", organization) or
                property_name and frappe.db.count("HS Party", {"property": property_name}) or
                property_name and frappe.db.count("HS Request", {"property": property_name})):
            raise AssertionError("The disposable concurrency fixture was not removed")
