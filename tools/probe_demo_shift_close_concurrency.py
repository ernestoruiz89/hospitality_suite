"""Exercise post-cutover PMS cash closing against concurrent requests."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES


BACKUP_FILE = "demo-shift-concurrency-backup.json"


def race(property_name, first_action, first_key, first_data,
         second_action, second_key, second_data, expected):
    from hospitality_suite import api
    from hospitality_suite.service import lock_property

    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    def run_first():
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(property_name, "finance")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The second cash request did not arrive")
            result = api.execute(property_name, first_action, first_key, first_data)
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.destroy()

    def run_second():
        if not held.wait(15):
            raise AssertionError("The first cash request did not acquire the lock")
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            attempting.set()
            try:
                result = api.execute(property_name, second_action,
                                     second_key, second_data)
            except (frappe.ValidationError, frappe.PermissionError):
                frappe.db.rollback()
                return {"status": "rejected"}
            frappe.db.commit()
            return {"status": "posted", "result": result}
        finally:
            second_done.set()
            frappe.destroy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_first)
        second = pool.submit(run_second)
        try:
            if not held.wait(15) or not attempting.wait(15):
                raise AssertionError("Independent cash sessions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The second request bypassed the hotel lock")
        finally:
            release.set()
        one = first.result(timeout=20)
        two = second.result(timeout=20)
    if (one["status"], two["status"]) != expected:
        raise AssertionError("Unexpected concurrent cash outcomes: " + repr((one, two)))
    if first_key == second_key and one != two:
        raise AssertionError("The same cash command key did not return its first result")
    return [one["status"], two["status"]]


def account_balance(property_name, account_name):
    value = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit-l.credit),0) "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s",
        (property_name, account_name), as_list=True)[0][0]
    return Decimal(str(value))


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import api, pms_cutover_backup
        from hospitality_suite.service import canonical, insert, operation
        from hospitality_suite.standalone_accounting import post

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler") or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE):
            raise RuntimeError("Only the frozen disposable cutover site is allowed")
        prop = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 1"})
        other = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 2"})
        if (frappe.db.count("HS Shift") or frappe.db.count("HS Payment") or
                frappe.db.count("HS Treasury Movement")):
            raise RuntimeError("The disposable site already has cash history")
        backup = pms_cutover_backup.prepare()
        backup_sha256 = pms_cutover_backup.verify(backup)["sha256"]
        backup_path = Path(frappe.get_site_path("private", "files", BACKUP_FILE))
        if backup_path.exists():
            if backup_path.is_symlink() or backup_path.read_text().strip() != canonical(backup):
                raise RuntimeError("The saved cash-race backup manifest changed")
        else:
            backup_path.write_text(canonical(backup) + "\n", encoding="utf-8")

        with operation(prop):
            cash = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-SHIFT-CASH", account_name="Caja ensayo cierre",
                root_type="Asset", account_type="Cash",
                account_currency="NIO", active=1, is_group=0)
            equity = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-SHIFT-EQUITY", account_name="Origen Caja ensayo",
                root_type="Equity", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            expense = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-SHIFT-EXPENSE", account_name="Gasto Caja ensayo",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            post(prop, source_doctype="QA Cash Fixture", source_name="qa-shift-cash-100",
                purpose="Opening Cash", lines=[
                    {"account": cash.name, "debit": "100", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "100"}])
        method = api.execute(prop.name, "pms_payment_method", "qa-shift-method",
            {"label": "Efectivo ensayo cierre", "account": cash.name})["method"]
        category = api.execute(prop.name, "pms_expense_category", "qa-shift-category",
            {"label": "Gasto ensayo cierre", "account": expense.name,
             "max_amount": "20"})["category"]

        def open_shift(number):
            result = api.execute(prop.name, "pms_open_shift",
                "qa-shift-open-" + str(number),
                {"opening_by_currency": {"NIO": "100.00"}})
            frappe.db.commit()
            frappe.db.rollback()
            return result["shift"]

        def closing(shift_name, amount="100.00"):
            return {"shift": shift_name, "counted_by_currency": {"NIO": amount}}

        def spending(shift_name):
            return {"kind": "Expense", "amount": "10.00", "method": method,
                "shift": shift_name, "category": category,
                "reference": "QA-SHIFT-EXPENSE",
                "reason": "Gasto de ensayo de cierre concurrente"}

        first_shift = open_shift(1)
        same = race(prop.name, "pms_close_shift", "qa-shift-close-1",
            closing(first_shift), "pms_close_shift", "qa-shift-close-1",
            closing(first_shift), ("posted", "posted"))
        frappe.db.rollback()
        if frappe.db.get_value("HS Shift", first_shift, "status") != "Closed":
            raise AssertionError("The first shift did not close")
        frappe.db.rollback()

        second_shift = open_shift(2)
        competing = race(prop.name, "pms_close_shift", "qa-shift-close-2",
            closing(second_shift), "pms_close_shift", "qa-shift-close-2-other",
            closing(second_shift), ("posted", "rejected"))
        frappe.db.rollback()

        third_shift = open_shift(3)
        close_first = race(prop.name, "pms_close_shift", "qa-shift-close-3",
            closing(third_shift), "pms_cash_movement", "qa-shift-expense-3",
            spending(third_shift), ("posted", "rejected"))
        frappe.db.rollback()

        fourth_shift = open_shift(4)
        spend_first = race(prop.name, "pms_cash_movement", "qa-shift-expense-4",
            spending(fourth_shift), "pms_close_shift", "qa-shift-close-4-stale",
            closing(fourth_shift), ("posted", "rejected"))
        frappe.db.rollback()
        if (frappe.db.get_value("HS Shift", fourth_shift, "status") != "Open" or
                frappe.db.count("HS Payment", {"property": prop.name,
                    "kind": "Expense", "status": "Posted"}) != 1 or
                account_balance(prop.name, cash.name) != 90):
            raise AssertionError("The expense or the remaining cash did not reconcile")
        frappe.db.rollback()
        closed = api.execute(prop.name, "pms_close_shift", "qa-shift-close-4-correct",
            closing(fourth_shift, "90.00"))
        frappe.db.commit()
        frappe.db.rollback()
        if (closed["expected"] != {"NIO": "90.00"} or
                frappe.db.count("HS Shift", {"property": prop.name,
                    "status": "Closed"}) != 4 or
                frappe.db.count("HS Payment", {"property": other.name}) or
                frappe.db.count("HS Shift", {"property": other.name})):
            raise AssertionError("Closing results or hotel isolation differ")
        print(json.dumps({"site": SITE, "property": prop.name,
            "races": {"same_key": same, "competing_keys": competing,
                "close_then_expense": close_first,
                "expense_then_stale_close": spend_first},
            "closed_shifts": 4, "posted_expenses": 1,
            "cash_balance_nio": "90", "other_hotel_cash_records": 0,
            "backup_file": BACKUP_FILE, "backup_sha256": backup_sha256},
            ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
