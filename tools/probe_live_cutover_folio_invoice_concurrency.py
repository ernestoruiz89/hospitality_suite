"""Race migrated folio billing and fiscal invoice commands on an isolated PMS clone."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import frappe


SITES = Path("/home/frappe/benches/hospitality-bench/sites")
SITE = "hs-pms-reverse-live-retake.local"
REFERENCE = "reverse-live-stage-20261026"
BACKUP_FILE = "live-folio-invoice-concurrency-backup.json"


def race(property_name, action, key, payload, *, same_key):
    from hospitality_suite import api
    from hospitality_suite.service import lock_property

    held = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    second_key = key if same_key else key + "-different"

    def first():
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            lock_property(property_name, "finance")
            held.set()
            if not attempting.wait(15) or not release.wait(15):
                raise AssertionError("The second transaction did not arrive")
            result = api.execute(property_name, action, key, payload)
            frappe.db.commit()
            return {"status": "posted", "result": result}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.destroy()

    def second():
        if not held.wait(15):
            raise AssertionError("The first transaction did not acquire the hotel lock")
        frappe.init(site=SITE, sites_path=str(SITES))
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            attempting.set()
            try:
                result = api.execute(property_name, action, second_key, payload)
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
                raise AssertionError("Both independent transactions did not start")
            if second_done.wait(0.3):
                raise AssertionError("The competing transaction bypassed the hotel lock")
        finally:
            release.set()
        first_result = one.result(timeout=20)
        second_result = two.result(timeout=20)
    if first_result["status"] != "posted":
        raise AssertionError("The first transaction did not post")
    if same_key:
        if first_result != second_result:
            raise AssertionError("An idempotent retry did not return the same result")
    elif second_result["status"] != "rejected":
        raise AssertionError("A competing key duplicated the posting")
    return first_result["result"], {"same_key": same_key,
        "first": first_result["status"], "second": second_result["status"]}


def account_balance(property_name, account_name):
    value = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit-l.credit),0) "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s",
        (property_name, account_name), as_list=True)[0][0]
    return Decimal(str(value))


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated full-clone bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import api, pms_cutover_backup
        from hospitality_suite.service import canonical

        if (frappe.local.conf.get("db_name") != "hs_pms_reverse_live_retake" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler") or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE or
                frappe.db.count("HS ERP to PMS Cutover Run") != 1):
            raise RuntimeError("Only the frozen full-cutover test clone is allowed")
        cases = [
            {"property": "ESTAB-00002", "folio": "CTA-2026-00001",
             "ar": "CUENTA-00016", "total": Decimal("450"), "charges": 1,
             "same_key": True, "series": "QA-LIVE-2-"},
            {"property": "ESTAB-00001", "folio": "9mf6q0entb",
             "ar": "CUENTA-00006", "total": Decimal("3100"), "charges": 2,
             "same_key": False, "series": "QA-LIVE-1-"},
        ]
        if (frappe.db.count("HS PMS Receivable") or
                frappe.db.count("HS PMS Fiscal Document") or
                frappe.db.count("HS PMS Fiscal Series") or
                frappe.db.count("HS Payment")):
            raise RuntimeError("The cutover clone has later billing or cash history")
        for case in cases:
            if (frappe.db.count("HS Charge", {"property": case["property"],
                    "folio": case["folio"], "status": "Pending"}) != case["charges"] or
                    not frappe.db.exists("HS Property", case["property"])):
                raise RuntimeError("The migrated folio fixture changed")
            case["ar_before"] = account_balance(case["property"], case["ar"])

        backup = pms_cutover_backup.prepare()
        backup_sha256 = pms_cutover_backup.verify(backup)["sha256"]
        backup_path = Path(frappe.get_site_path("private", "files", BACKUP_FILE))
        if backup_path.exists():
            if backup_path.is_symlink() or backup_path.read_text().strip() != canonical(backup):
                raise RuntimeError("The folio-race backup manifest changed")
        else:
            backup_path.write_text(canonical(backup) + "\n", encoding="utf-8")

        outcomes = []
        for case in cases:
            quote = api.pms_folio_quote(case["property"], {
                "folio": case["folio"], "receivable_account": case["ar"]})
            if (Decimal(quote["total"]) != case["total"] or
                    len(quote["lines"]) != case["charges"]):
                raise AssertionError("The imported charges did not quote as expected")
            bill, bill_race = race(case["property"], "pms_bill_folio",
                "qa-live-folio-" + case["property"], {
                    "folio": case["folio"], "receivable_account": case["ar"],
                    "acceptance": quote["acceptance"]}, same_key=case["same_key"])
            frappe.db.rollback()
            names = [row["receivable"] for row in bill["receivables"]]
            if (len(names) != case["charges"] or
                    Decimal(bill["total"]) != case["total"] or
                    frappe.db.count("HS PMS Receivable", {"property": case["property"],
                        "folio": case["folio"]}) != case["charges"] or
                    frappe.db.count("HS Charge", {"property": case["property"],
                        "folio": case["folio"], "status": "Pending"}) or
                    account_balance(case["property"], case["ar"]) !=
                    case["ar_before"] + case["total"]):
                raise AssertionError("Billing duplicated or missed a migrated charge")
            frappe.db.rollback()

            series = api.execute(case["property"], "pms_fiscal_series",
                "qa-live-series-" + case["property"], {
                    "series_code": case["series"], "document_type": "Invoice",
                    "start_number": 1, "end_number": 100, "padding": 3})["series"]
            frappe.db.commit()
            frappe.db.rollback()
            invoice_quote = api.pms_invoice_quote(case["property"], {
                "series": series, "receivables": names})
            if (Decimal(invoice_quote["total_amount"]) != case["total"] or
                    len(invoice_quote["lines"]) != case["charges"]):
                raise AssertionError("The billed folio did not produce a fiscal quote")
            invoice, invoice_race = race(case["property"], "pms_issue_invoice",
                "qa-live-invoice-" + case["property"], {
                    "series": series, "receivables": names,
                    "acceptance": invoice_quote["acceptance"]},
                same_key=case["same_key"])
            frappe.db.rollback()
            if (frappe.db.count("HS PMS Fiscal Document", {
                    "property": case["property"], "document_type": "Invoice"}) != 1 or
                    frappe.db.get_value("HS PMS Fiscal Series", series,
                        "next_number") != 2 or
                    Decimal(str(frappe.db.get_value("HS PMS Fiscal Document",
                        invoice["document"], "total_amount"))) != case["total"] or
                    account_balance(case["property"], case["ar"]) !=
                    case["ar_before"] + case["total"]):
                raise AssertionError("The invoice duplicated or altered the ledger")
            frappe.db.rollback()
            outcomes.append({"property": case["property"],
                "folio_total_nio": str(case["total"]),
                "receivables": len(names), "bill_race": bill_race,
                "invoice_race": invoice_race,
                "fiscal_document": invoice["document_number"]})
        print(json.dumps({"site": SITE, "cutover_reference": REFERENCE,
            "outcomes": outcomes, "backup_file": BACKUP_FILE,
            "backup_sha256": backup_sha256}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
