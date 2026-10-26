"""Two-connection correction races on the disposable persistent Day Pass clone."""

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api, cashier
from hospitality_suite.service import canonical, lock_property
from hospitality_suite.tests.probe_persistent_day_pass_cutover import SITE, inspect


SITES = Path("/home/frappe/frappe-bench/sites")


def _return_again(tag, *, same_key):
    before = inspect()
    if before["status"] != "Issued":
        raise AssertionError("The isolated historical access must be issued")
    day_pass = frappe.get_doc("HS Day Pass", before["day_pass"])
    prop = frappe.get_doc("HS Property", day_pass.property)
    method = frappe.db.get_value("HS Payment Method", {
        "property": prop.name, "company": prop.company,
        "is_cash": 1, "currency": prop.currency}, "name")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
        "company": prop.company, "status": "Open", "currency": prop.currency},
        pluck="name", limit_page_length=0)
    if not method or len(shifts) != 1:
        raise AssertionError("The disposable clone lost its cash setup")
    request = {"day_pass": day_pass.name, "modified": str(day_pass.modified),
        "method": method, "shift": shifts[0], "amount": "",
        "reference": "QA-DAY-PASS-RACE-" + tag,
        "reason": "Ensayo de corrección concurrente"}
    quote = api.erp_historical_day_pass_return_quote(prop.name,
        canonical(request))
    audit_before = frappe.db.count("HS Audit Event", {
        "property": prop.name, "source_doctype": "HS Day Pass",
        "source_name": day_pass.name,
        "action": "erp_historical_day_pass_returned"})
    frappe.db.commit()
    result = _race(prop.name, "erp_historical_day_pass_return",
        {**request, "amount": quote["refund_amount"],
         "acceptance": quote["acceptance"]},
        "qa-day-pass-race-return-" + tag, same_key=same_key)
    frappe.db.rollback()
    day_pass.reload()
    if (day_pass.status != "Cancelled" or
            day_pass.erp_return_credit_note != result["credit_note"] or
            day_pass.erp_return_refund != result["refund"] or
            cashier.expected(frappe.get_doc("HS Shift", shifts[0]))[
                prop.currency] != "94.00" or
            frappe.db.count("HS Audit Event", {
                "property": prop.name, "source_doctype": "HS Day Pass",
                "source_name": day_pass.name,
                "action": "erp_historical_day_pass_returned"}) !=
                audit_before + 1):
        raise AssertionError("The new synthetic return did not reconcile")
    return day_pass.name, shifts[0], result


def _race(prop_name, action, payload, key, *, same_key):
    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    other_key = key if same_key else key + "-different"

    def first():
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(prop_name, "approve")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The second Day Pass command did not arrive")
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
            raise AssertionError("The first Day Pass command did not lock the hotel")
        frappe.init(site=SITE, sites_path=str(SITES))
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
                raise AssertionError("The second Day Pass command bypassed the hotel lock")
        finally:
            release.set()
        first_result = one.result(timeout=30)
        second_result = two.result(timeout=30)
    if first_result["status"] != "posted":
        raise AssertionError("The first Day Pass command did not post")
    if same_key and second_result != first_result:
        raise AssertionError("A same-key command did not return its first result")
    if not same_key and second_result["status"] != "rejected":
        raise AssertionError("Two distinct commands changed the same return")
    return first_result["result"]


def run():
    if frappe.local.site != SITE or Path(frappe.local.sites_path).resolve() != SITES:
        frappe.throw("Use only the isolated persistent Day Pass cutover site")
    frappe.set_user("Administrator")
    if inspect()["status"] != "Issued":
        frappe.throw("The isolated Day Pass must be ready for a new return")
    outcomes = []
    for same_key in (True, False):
        tag = uuid4().hex[:12]
        day_pass_name, shift_name, returned = _return_again(tag,
            same_key=same_key)
        day_pass = frappe.get_doc("HS Day Pass", day_pass_name)
        prop = frappe.get_doc("HS Property", day_pass.property)
        old_history = frappe.parse_json(day_pass.erp_return_corrections)
        request = {"day_pass": day_pass.name,
            "modified": str(day_pass.modified),
            "reason": "Corrección concurrente de retorno sintético " + tag}
        quote = api.erp_historical_day_pass_return_reversal_quote(
            prop.name, canonical(request))
        payload = {**request, "acceptance": quote["acceptance"]}
        audit_before = frappe.db.count("HS Audit Event", {
            "property": prop.name, "source_doctype": "HS Day Pass",
            "source_name": day_pass.name,
            "action": "erp_historical_day_pass_return_reversal"})
        frappe.db.commit()
        result = _race(prop.name,
            "erp_historical_day_pass_return_reversal", payload,
            "qa-day-pass-race-correction-" + tag, same_key=same_key)
        frappe.db.rollback()
        day_pass.reload()
        opening = frappe.get_doc("Sales Invoice",
            day_pass.erp_opening_invoice)
        history = frappe.parse_json(day_pass.erp_return_corrections)
        refund = frappe.get_doc("HS Payment", returned["refund"])
        if (day_pass.status != "Issued" or
                day_pass.erp_return_credit_note or day_pass.erp_return_refund or
                len(history) != len(old_history) + 1 or
                history[:-1] != old_history or
                history[-1]["credit_note"] != returned["credit_note"] or
                sha256(day_pass.erp_return_corrections.encode()).hexdigest() !=
                    day_pass.erp_return_corrections_sha256 or
                frappe.db.get_value("Sales Invoice", returned["credit_note"],
                    "docstatus") != 2 or
                refund.status != "Cancelled" or
                frappe.db.get_value("Payment Entry", refund.payment_entry,
                    "docstatus") != 2 or
                Decimal(str(opening.outstanding_amount)) != 6 or
                cashier.expected(frappe.get_doc("HS Shift", shift_name))[
                    prop.currency] != "100.00" or
                frappe.db.count("HS Audit Event", {"property": prop.name,
                    "source_doctype": "HS Day Pass",
                    "source_name": day_pass.name,
                    "action": "erp_historical_day_pass_return_reversal"}) !=
                    audit_before + 1 or
                result["credit_note"] != returned["credit_note"]):
            raise AssertionError("The concurrent correction did not reconcile")
        outcomes.append({"same_key": same_key,
            "return_second": "same_result" if same_key else "rejected",
            "correction_second": "same_result" if same_key else "rejected",
            "correction_count": len(history),
            "opening_outstanding": str(opening.outstanding_amount)})
    return {"independent_session_races_verified": True,
        "site": SITE, "outcomes": outcomes}
