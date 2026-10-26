"""Real two-session races against PMS receivable collection on a disposable site."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES


BACKUP_FILE = "demo-payment-concurrency-backup.json"


def run_race(prop_name, method, receivable, *, same_key):
    from hospitality_suite import api
    from hospitality_suite.service import lock_property

    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    payload = {"kind": "Payment", "amount": "10.00", "method": method,
        "receivable": receivable, "reference": "QA-PAY-" + receivable,
        "reason": "Ensayo de cobro concurrente"}
    first_key = "qa-pay-race-" + receivable
    second_key = first_key if same_key else first_key + "-different"

    def first():
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(prop_name, "finance")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The competing payment did not arrive")
            result = api.execute(prop_name, "pms_cash_movement",
                first_key, payload)
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.destroy()

    def second():
        if not held.wait(15):
            raise AssertionError("The first payment did not lock the hotel")
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            attempting.set()
            try:
                result = api.execute(prop_name, "pms_cash_movement",
                    second_key, payload)
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
                raise AssertionError("The independent payment sessions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The second payment bypassed the hotel lock")
        finally:
            release.set()
        first_result = one.result(timeout=20)
        second_result = two.result(timeout=20)
    if (same_key and (second_result != first_result or
            first_result["status"] != "posted")):
        raise AssertionError("Same-key collection was not idempotent")
    if (not same_key and (first_result["status"] != "posted" or
            second_result["status"] != "rejected")):
        raise AssertionError("Two different requests collected one debt twice")
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
        from hospitality_suite.standalone_receivables import outstanding

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler") or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE):
            raise RuntimeError("Only the frozen disposable cutover site is allowed")
        prop = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 1"})
        other = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 2"})
        if (frappe.db.count("HS Payment", {"property": prop.name}) or
                frappe.db.count("HS Payment", {"property": other.name})):
            raise RuntimeError("The isolated hotels already have payment history")
        backup = pms_cutover_backup.prepare()
        backup_sha256 = pms_cutover_backup.verify(backup)["sha256"]
        backup_path = Path(frappe.get_site_path("private", "files", BACKUP_FILE))
        if backup_path.exists():
            if backup_path.is_symlink() or backup_path.read_text().strip() != canonical(backup):
                raise RuntimeError("The saved payment-race backup manifest changed")
        else:
            backup_path.write_text(canonical(backup) + "\n", encoding="utf-8")
        with operation(prop):
            bank = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-BANK-PAY", account_name="Banco ensayo de cobro",
                root_type="Asset", account_type="Bank",
                account_currency="NIO", active=1, is_group=0)
            income = insert("HS Account", prop, organization=prop.organization,
                account_code="QA-INCOME-PAY", account_name="Ingreso ensayo de cobro",
                root_type="Income", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            party = insert("HS Party", prop, organization=prop.organization,
                party_name="Cliente ensayo de cobro concurrente",
                party_type="Customer", active=1)
        receivable_account = frappe.db.get_value("HS Account", {
            "property": prop.name, "account_type": "Receivable"}, "name")
        method = api.execute(prop.name, "pms_payment_method",
            "qa-bank-pay-method", {"label": "Banco ensayo cobro",
                "account": bank.name})["method"]
        receivables = []
        for number in (1, 2):
            created = api.execute(prop.name, "pms_receivable",
                "qa-pay-receivable-" + str(number),
                {"party": party.name, "reference": "QA-PAY-INV-" + str(number),
                 "description": "Factura simulada para carrera de cobro",
                 "amount": "10.00", "receivable_account": receivable_account,
                 "income_account": income.name})
            receivables.append(created["receivable"])
        frappe.db.commit()
        baseline = {dt: frappe.db.count(dt, {"property": prop.name}) for dt in
            ("HS Payment", "HS PMS Allocation", "HS Journal")}
        frappe.db.rollback()  # Release all parent reads before worker sessions.
        results = []
        for index, receivable in enumerate(receivables):
            results.append(run_race(prop.name, method, receivable,
                same_key=index == 0))
            frappe.db.rollback()
        counts = {dt: frappe.db.count(dt, {"property": prop.name}) for dt in baseline}
        if (counts["HS Payment"] != baseline["HS Payment"] + 2 or
                counts["HS PMS Allocation"] != baseline["HS PMS Allocation"] + 2 or
                counts["HS Journal"] != baseline["HS Journal"] + 2 or
                any(outstanding(prop, receivable) != 0 for receivable in receivables) or
                account_balance(prop.name, bank.name) != 20 or
                account_balance(prop.name, receivable_account) != 0 or
                frappe.db.count("HS Payment", {"property": other.name})):
            raise AssertionError("A payment, allocation or ledger balance duplicated")
        try:
            api.execute(prop.name, "pms_cash_movement",
                "qa-pay-race-" + receivables[0],
                {"kind": "Payment", "amount": "9.00", "method": method,
                 "receivable": receivables[0],
                 "reference": "QA-PAY-" + receivables[0],
                 "reason": "Ensayo de cobro concurrente"})
        except frappe.ValidationError:
            frappe.db.rollback()
        else:
            raise AssertionError("The same request key accepted a different amount")
        print(json.dumps({"site": SITE, "property": prop.name,
            "races": results, "payments": 2, "allocations": 2,
            "bank_balance_nio": "20", "receivable_balance_nio": "0",
            "other_hotel_payments": 0, "payload_conflict_rejected": True,
            "backup_file": BACKUP_FILE,
            "backup_sha256": backup_sha256}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
