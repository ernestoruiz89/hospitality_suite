"""Two real DB sessions race to post one PMS stock count on a disposable site."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import frappe

from activate_demo_stock_reverse import REFERENCE, SITE, SITES


BACKUP_FILE = "demo-stock-concurrency-backup.json"


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import api, pms_cutover_backup
        from hospitality_suite.service import canonical, lock_property
        from hospitality_suite.standalone_inventory import current_balance

        if (frappe.local.conf.get("db_name") != "hs_pms_demo_stock_qa" or
                not frappe.local.conf.get("maintenance_mode") or
                not frappe.local.conf.get("pause_scheduler") or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") != REFERENCE):
            raise RuntimeError("Only the frozen disposable cutover site is allowed")
        prop = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 1"})
        other = frappe.get_doc("HS Property", {"property_name": "Hotel PMS inventario 2"})
        product = frappe.db.get_value("HS Product", {"property": prop.name,
            "product_code": "HS-DEMO-WATER"}, "name")
        warehouse = frappe.db.get_value("HS Warehouse", {"property": prop.name,
            "warehouse_code": "DEMO-STOCK-1"}, "name")
        expense = frappe.db.get_value("HS Account", {"property": prop.name,
            "account_type": "Stock Adjustment"}, "name")
        other_product = frappe.db.get_value("HS Product", {"property": other.name,
            "product_code": "HS-DEMO-WATER"}, "name")
        other_warehouse = frappe.db.get_value("HS Warehouse", {
            "property": other.name, "warehouse_code": "DEMO-STOCK-2"}, "name")
        if (current_balance(prop, product, warehouse) !=
                (Decimal(100), Decimal(1000)) or
                current_balance(other, other_product, other_warehouse) !=
                (Decimal(100), Decimal(1000))):
            raise RuntimeError("The opening stock changed before the race")
        backup = pms_cutover_backup.prepare()
        digest = pms_cutover_backup.verify(backup)["sha256"]
        backup_path = Path(frappe.get_site_path("private", "files", BACKUP_FILE))
        if backup_path.exists():
            if backup_path.is_symlink() or backup_path.read_text().strip() != canonical(backup):
                raise RuntimeError("The saved backup manifest changed")
        else:
            backup_path.write_text(canonical(backup) + "\n", encoding="utf-8")
        before = {dt: frappe.db.count(dt, {"property": prop.name}) for dt in
            ("HS Stock Count", "HS Stock Movement", "HS Journal", "HS Request")}
        payload = {"product": product, "warehouse": warehouse,
            "counted_quantity": "99", "adjustment_account": expense,
            "reference": "QA-CONCURRENT-COUNT-20261026",
            "reason": "Dos solicitudes simultáneas del mismo conteo"}
        key = "qa-concurrent-count-20261026"
        # current_balance uses FOR UPDATE; release the parent's read locks
        # before the independent sessions contend for the hotel row.
        frappe.db.rollback()
        held = threading.Event()
        attempting = threading.Event()
        release = threading.Event()
        second_done = threading.Event()

        def first():
            frappe.init(site=SITE, sites_path=str(SITES))
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                lock_property(prop.name, "approve")
                held.set()
                if not attempting.wait(15) or not release.wait(15):
                    raise AssertionError("The competing request did not arrive")
                result = api.execute(prop.name, "pms_count_stock", key, payload)
                frappe.db.commit()
                return result
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                frappe.destroy()

        def second():
            if not held.wait(15):
                raise AssertionError("The first session did not lock the hotel")
            frappe.init(site=SITE, sites_path=str(SITES))
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                attempting.set()
                result = api.execute(prop.name, "pms_count_stock", key, payload)
                frappe.db.commit()
                return result
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                second_done.set()
                frappe.destroy()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            two = pool.submit(second)
            try:
                if not held.wait(15) or not attempting.wait(15):
                    raise AssertionError("The independent sessions did not start")
                if second_done.wait(0.3):
                    raise AssertionError("The second request bypassed the hotel lock")
            finally:
                release.set()
            first_result = one.result(timeout=20)
            second_result = two.result(timeout=20)
        frappe.db.rollback()  # Refresh the parent's repeatable-read snapshot.
        if first_result != second_result:
            raise AssertionError("The two same-key requests returned different counts")
        after = {dt: frappe.db.count(dt, {"property": prop.name}) for dt in before}
        if (after["HS Stock Count"] != before["HS Stock Count"] + 1 or
                after["HS Stock Movement"] != before["HS Stock Movement"] + 1 or
                after["HS Journal"] != before["HS Journal"] + 1 or
                after["HS Request"] != before["HS Request"] + 1 or
                current_balance(prop, product, warehouse) !=
                (Decimal(99), Decimal(990)) or
                current_balance(other, other_product, other_warehouse) !=
                (Decimal(100), Decimal(1000))):
            raise AssertionError("The concurrent count duplicated or crossed hotel stock")
        try:
            api.execute(prop.name, "pms_count_stock", key,
                {**payload, "counted_quantity": "98"})
        except frappe.ValidationError:
            frappe.db.rollback()
        else:
            raise AssertionError("The same key accepted a different count")
        print(json.dumps({"site": SITE, "hotel": prop.name,
            "serialized": True, "same_result": first_result == second_result,
            "one_count": True, "after_quantity": "99",
            "other_hotel_quantity": "100", "payload_conflict_rejected": True,
            "backup_file": BACKUP_FILE, "backup_sha256": digest,
            "cutover_reference": REFERENCE}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
