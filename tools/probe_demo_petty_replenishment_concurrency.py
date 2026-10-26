"""Two-session same-key and competing-key PMS petty-cash reimbursements."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES


BACKUP_FILE = "demo-petty-concurrency-backup.json"
APPROVER = "qa-petty-manager@hospitality.example.invalid"


def race(prop_name, data, *, same_key):
    from hospitality_suite import api
    from hospitality_suite.service import lock_property

    rendition = data["rendition"]
    first_key = "qa-petty-race-" + rendition
    second_key = first_key if same_key else first_key + "-different"
    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    def first():
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(prop_name, "finance")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The competing reimbursement did not arrive")
            result = api.execute(prop_name, "pms_petty_fund", first_key, data)
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.destroy()

    def second():
        if not held.wait(15):
            raise AssertionError("The first reimbursement did not lock the hotel")
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            attempting.set()
            try:
                result = api.execute(prop_name, "pms_petty_fund", second_key, data)
            except frappe.ValidationError:
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
                raise AssertionError("Independent reimbursement sessions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The second reimbursement bypassed the hotel lock")
        finally:
            release.set()
        first_result = one.result(timeout=20)
        second_result = two.result(timeout=20)
    if same_key:
        if first_result != second_result or first_result["status"] != "posted":
            raise AssertionError("Same-key reimbursement was not idempotent")
    elif (first_result["status"] != "posted" or
            second_result["status"] != "rejected"):
        raise AssertionError("Competing keys reimbursed one rendition twice")
    return {"same_key": same_key,
        "first": first_result["status"],
        "second": second_result["status"]}


def account_balance(prop_name, account_name):
    value = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit-l.credit),0) "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s",
        (prop_name, account_name), as_list=True)[0][0]
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
        from hospitality_suite.standalone_petty_cash import operational_balance

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler") or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE):
            raise RuntimeError("Only the frozen disposable cutover site is allowed")
        prop = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 1"})
        other = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 2"})
        if (frappe.db.count("HS Petty Cash Expense", {"property": prop.name}) or
                frappe.db.count("HS Treasury Movement", {"property": prop.name}) or
                frappe.db.count("HS Treasury Movement", {"property": other.name})):
            raise RuntimeError("The disposable sites already have petty-cash history")
        backup = pms_cutover_backup.prepare()
        backup_sha256 = pms_cutover_backup.verify(backup)["sha256"]
        backup_path = Path(frappe.get_site_path("private", "files", BACKUP_FILE))
        if backup_path.exists():
            if backup_path.is_symlink() or backup_path.read_text().strip() != canonical(backup):
                raise RuntimeError("The saved petty-race backup manifest changed")
        else:
            backup_path.write_text(canonical(backup) + "\n", encoding="utf-8")
        with operation(prop):
            cash = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-CASH", account_name="Caja ensayo reposición",
                root_type="Asset", account_type="Cash",
                account_currency="NIO", active=1, is_group=0)
            petty = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-FUND", account_name="Fondo ensayo Caja Chica",
                root_type="Asset", account_type="Current Asset",
                account_currency="NIO", active=1, is_group=0)
            equity = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-EQUITY", account_name="Origen del efectivo ensayo",
                root_type="Equity", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            overage = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-OVER", account_name="Sobrante ensayo",
                root_type="Income", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            shortage = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-SHORT", account_name="Faltante ensayo",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            expense = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-PETTY-EXP", account_name="Gastos menores ensayo",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            post(prop, source_doctype="QA Cash Fixture", source_name="qa-petty-cash-100",
                purpose="Opening Cash", lines=[
                    {"account": cash.name, "debit": "100", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "100"}])
        if not frappe.db.exists("User", APPROVER):
            frappe.get_doc({"doctype": "User", "email": APPROVER,
                "first_name": "Gerencia de ensayo", "enabled": 1,
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Desk User"}, {"role": "HS Manager"}]}).insert()
        if not frappe.db.exists("HS Access", {"user": APPROVER,
                "property": prop.name}):
            frappe.get_doc({"doctype": "HS Access", "user": APPROVER,
                "property": prop.name, "company": prop.company}).insert()
        method = api.execute(prop.name, "pms_payment_method",
            "qa-petty-cash-method", {"label": "Efectivo ensayo Caja Chica",
                "account": cash.name})["method"]
        category = api.execute(prop.name, "pms_expense_category",
            "qa-petty-category", {"label": "Gasto ensayo",
                "account": expense.name, "max_amount": "20"})["category"]
        api.execute(prop.name, "pms_petty_configure", "qa-petty-config",
            {"petty_cash_account": petty.name,
             "petty_cash_responsible": "Administrator",
             "petty_cash_overage_account": overage.name,
             "petty_cash_shortage_account": shortage.name})
        prop.reload()
        shift = api.execute(prop.name, "pms_open_shift", "qa-petty-shift",
            {"opening_by_currency": {"NIO": "100.00"}})["shift"]
        api.execute(prop.name, "pms_petty_fund", "qa-petty-initial",
            {"kind": "Initial Fund", "method": method, "shift": shift,
             "amount": "40.00", "reference": "QA-PETTY-INITIAL",
             "reason": "Fondo de ensayo"})

        def approved_rendition(number):
            api.execute(prop.name, "pms_petty_expense",
                "qa-petty-expense-" + str(number),
                {"category": category, "beneficiary": "Proveedor de ensayo",
                 "concept": "Gasto menor de ensayo",
                 "receipt_reference": "QA-PETTY-REC-" + str(number),
                 "amount": "10.00"})
            rendition = api.execute(prop.name, "pms_petty_submit",
                "qa-petty-submit-" + str(number),
                {"counted_cash": "30.00"})["rendition"]
            frappe.set_user(APPROVER)
            try:
                result = api.execute(prop.name, "pms_petty_review",
                    "qa-petty-approve-" + str(number),
                    {"rendition": rendition, "approve": 1,
                     "note": "Gasto y arqueo verificados"})
            finally:
                frappe.set_user("Administrator")
            if result["status"] != "Approved":
                raise AssertionError("The manager did not approve the rendition")
            return rendition

        first_rendition = approved_rendition(1)
        frappe.db.commit()
        frappe.db.rollback()  # Release all parent read locks before the race.
        first_data = {"kind": "Replenishment", "rendition": first_rendition,
            "method": method, "shift": shift, "amount": "10.00",
            "reference": "QA-PETTY-REPLENISH-1",
            "reason": "Reposición total de primera rendición"}
        first_result = race(prop.name, first_data, same_key=True)
        frappe.db.rollback()
        if (frappe.db.count("HS Treasury Movement", {"property": prop.name,
                "kind": "Replenishment", "status": "Posted"}) != 1 or
                frappe.db.get_value("HS Petty Cash Rendition", first_rendition,
                    "status") != "Reimbursed"):
            raise AssertionError("The first rendition was reimbursed more than once")
        frappe.db.rollback()
        second_rendition = approved_rendition(2)
        frappe.db.commit()
        frappe.db.rollback()
        second_data = {"kind": "Replenishment", "rendition": second_rendition,
            "method": method, "shift": shift, "amount": "10.00",
            "reference": "QA-PETTY-REPLENISH-2",
            "reason": "Reposición total de segunda rendición"}
        second_result = race(prop.name, second_data, same_key=False)
        frappe.db.rollback()
        prop.reload()
        if (frappe.db.count("HS Treasury Movement", {"property": prop.name,
                "kind": "Replenishment", "status": "Posted"}) != 2 or
                frappe.db.get_value("HS Petty Cash Rendition", second_rendition,
                    "status") != "Reimbursed" or
                operational_balance(prop) != Decimal(40) or
                account_balance(prop.name, petty.name) != 40 or
                account_balance(prop.name, cash.name) != 40 or
                frappe.db.count("HS Treasury Movement", {"property": other.name})):
            raise AssertionError("The fund, cash or other hotel changed unexpectedly")
        try:
            api.execute(prop.name, "pms_petty_fund",
                "qa-petty-race-" + first_rendition,
                {**first_data, "amount": "9.00"})
        except frappe.ValidationError:
            frappe.db.rollback()
        else:
            raise AssertionError("The same key accepted another reimbursement amount")
        print(json.dumps({"site": SITE, "property": prop.name,
            "races": [first_result, second_result],
            "posted_replenishments": 2, "petty_balance_nio": "40",
            "cash_balance_nio": "40", "other_hotel_movements": 0,
            "payload_conflict_rejected": True,
            "backup_file": BACKUP_FILE,
            "backup_sha256": backup_sha256}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
