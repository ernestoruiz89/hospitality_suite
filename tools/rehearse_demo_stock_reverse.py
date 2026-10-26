"""Prepare and rehearse the isolated two-hotel ERPNext stock opening in PMS."""

import json
from pathlib import Path

import frappe


SITES = Path("/home/frappe/frappe-bench/sites")
SITE = "hs-pms-demo-stock-qa.local"
BUNDLE = "hs-erp-fiscal-c5388f199da84ca8a8101f9698657d1a.zip"
SOURCE_SHA256 = "b1ccd819e0387f3a3b0fb17bc2d2bb5bac26c6a8a96482b6e4055df39d328e65"
MANIFEST_SHA256 = "0156de9079300c86bc854d345e056ba59fc28bc862a7ecd72ec48b66f9df52d6"
RECEIPT = "hs-erp-freeze-5b62e644b79940bd87ffacdde3a9153a.json"
RECEIPT_SHA256 = "24735fb3c5a54132970f265dbe993381d3f2784d8ace299dd5022b093c11bfb8"
SOURCE_BACKUP_SHA256 = "fcde7a91d78aa3d72561b1d3dc88c6c5e2b3e3b66584a3207d738e33fb554a95"
MAPPING_FILE = "demo-stock-reverse-mapping.json"


def one(doctype, prop, lookup, **values):
    from hospitality_suite.service import insert

    name = frappe.db.get_value(doctype, {"property": prop.name, **lookup}, "name")
    return frappe.get_doc(doctype, name) if name else insert(doctype, prop,
        organization=prop.organization, **values)


def main():
    if Path.cwd().resolve() != SITES.resolve():
        raise RuntimeError("Run from the isolated PMS bench sites directory")
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        from hospitality_suite import (erp_fiscal_history,
            erp_to_pms_activation, erp_to_pms_cli,
            erp_to_pms_mapping, erp_to_pms_transfer_plan,
            erp_to_pms_transfer_rehearsal, setup)
        from hospitality_suite.service import canonical, operation
        from hospitality_suite.standalone_accounting import provider

        if provider() != "pms" or "erpnext" in frappe.get_installed_apps():
            raise RuntimeError("The isolated target must use the PMS ledger")
        manifest, source = erp_fiscal_history.load_source_inventory(
            BUNDLE, SOURCE_SHA256, MANIFEST_SHA256)
        if len(source["properties"]) != 2 or manifest["documents"]:
            raise RuntimeError("The reviewed stock-only bundle changed")
        if not frappe.db.count("HS Organization"):
            organization = frappe.get_doc({"doctype": "HS Organization",
                "legal_name": "Demostración de corte de existencias",
                "base_currency": "NIO", "tax_regime": "General",
                "active": 1}).insert()
        else:
            organization = frappe.get_doc("HS Organization", {
                "legal_name": "Demostración de corte de existencias"})
        mapping = erp_to_pms_mapping.template(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256)
        target_props = []
        for index, origin in enumerate(source["properties"], start=1):
            label = "Hotel PMS inventario " + str(index)
            name = frappe.db.get_value("HS Property", {
                "property_name": label}, "name")
            if not name:
                created = setup.create_property({"property_name": label,
                    "organization": organization.name, "currency": "NIO",
                    "mode": "Hotel" if index == 1 else "Por tiempo",
                    "time_zone": "America/Managua", "close_time": "06:00",
                    "business_date": str(origin["business_date"])},
                    "demo-stock-reverse-" + str(index))
                name = created["property"]
            prop = frappe.get_doc("HS Property", name)
            target_props.append(prop.name)
            section = mapping["properties"][origin["property"]]
            section["property"] = prop.name
            with operation(prop):
                temporary = one("HS Account", prop,
                    {"account_code": "1990"}, account_code="1990",
                    account_name="Puente de apertura", root_type="Asset",
                    account_type="Temporary", account_currency="NIO",
                    active=1, is_group=0)
                section["temporary_opening_account"] = temporary.name
                mapped_accounts = {}
                for number, account in enumerate(
                        origin["mapping_requirements"]["accounts"], start=1):
                    code = "M" + str(number).zfill(3)
                    target = one("HS Account", prop, {"account_code": code},
                        account_code=code, account_name=account["name"],
                        root_type=account["root_type"],
                        account_type=account["account_type"] or "General",
                        account_currency=account["account_currency"],
                        active=1, is_group=0)
                    section["accounts"][account["name"]] = target.name
                    mapped_accounts[account["account_type"]] = target.name
                for product in origin["mapping_requirements"]["products"]:
                    kind = "Stock" if product["is_stock_item"] else "Service"
                    target = one("HS Product", prop,
                        {"product_code": product["name"]},
                        product_code=product["name"],
                        product_name=product["item_name"], product_type=kind,
                        inventory_account=mapped_accounts.get("Stock") if kind == "Stock" else None,
                        active=1)
                    section["products"][product["name"]] = target.name
                for warehouse in origin["mapping_requirements"]["warehouses"]:
                    code = "DEMO-STOCK-" + str(index)
                    target = one("HS Warehouse", prop,
                        {"warehouse_code": code}, warehouse_code=code,
                        warehouse_name=warehouse["name"], active=1)
                    section["warehouses"][warehouse["name"]] = target.name
        if frappe.db.count("HS Property") != 2:
            raise RuntimeError("The target has unrelated properties")
        frappe.db.commit()
        reviewed = erp_to_pms_mapping.review(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256, mapping)
        plan = erp_to_pms_transfer_plan.review(BUNDLE, SOURCE_SHA256,
            MANIFEST_SHA256, mapping)
        if not reviewed["mapping_ready"] or not plan["ready_for_transfer"]:
            raise AssertionError({"mapping": reviewed["blockers"],
                "plan": plan["blockers"]})
        stock_rows = [row["opening_stock"] for row in plan["properties"]]
        if (len(stock_rows) != 2 or any(len(rows) != 1 or
                rows[0]["quantity"] != "100" or
                rows[0]["stock_value"] != "1000" for rows in stock_rows) or
                len({rows[0]["warehouse"] for rows in stock_rows}) != 2):
            raise AssertionError("The plan did not isolate C$1,000 and 100 units per hotel")
        rehearsal = erp_to_pms_transfer_rehearsal.rehearse(BUNDLE,
            SOURCE_SHA256, MANIFEST_SHA256, mapping, plan["plan_sha256"])
        if not rehearsal["reconciled"] or not rehearsal["rolled_back"]:
            raise AssertionError("The PMS stock rehearsal did not reconcile and roll back")
        if any(len(row["stock_movements"]) != 1 for row in rehearsal["properties"]):
            raise AssertionError("The rehearsal omitted a hotel's stock movement")
        if frappe.db.count("HS Stock Movement") or frappe.db.count("HS Journal"):
            raise AssertionError("The rehearsal left opening stock or journals")
        mapping_path = Path(frappe.get_site_path("private", "files", MAPPING_FILE))
        encoded = canonical(mapping) + "\n"
        if mapping_path.exists():
            if mapping_path.is_symlink() or mapping_path.read_text() != encoded:
                raise RuntimeError("The reviewed mapping file changed")
        else:
            mapping_path.write_text(encoded, encoding="utf-8")
        frozen = erp_to_pms_cli.review_file(MAPPING_FILE, RECEIPT,
            BUNDLE, source_sha256=SOURCE_SHA256,
            manifest_sha256=MANIFEST_SHA256,
            receipt_sha256=RECEIPT_SHA256,
            source_backup_sha256=SOURCE_BACKUP_SHA256)
        if (not frozen["ready"] or frozen["blockers"] or
                frozen["plan_sha256"] != plan["plan_sha256"]):
            raise AssertionError("The frozen source does not match the reviewed plan")
        sealed = erp_to_pms_activation.rehearse_activation(BUNDLE,
            RECEIPT, mapping, source_sha256=SOURCE_SHA256,
            manifest_sha256=MANIFEST_SHA256,
            receipt_sha256=RECEIPT_SHA256,
            source_backup_sha256=SOURCE_BACKUP_SHA256,
            mapping_sha256=frozen["mapping_sha256"],
            plan_sha256=frozen["plan_sha256"],
            migration_reference="demo-stock-reverse-rehearsal-20261026")
        if (not sealed["reconciled"] or not sealed["rolled_back"] or
                frappe.db.count("HS Stock Movement") or
                frappe.db.count("HS ERP to PMS Cutover Run")):
            raise AssertionError("The frozen rehearsal left business documents")
        print(json.dumps({"site": SITE, "properties": target_props,
            "mapping_ready": reviewed["mapping_ready"],
            "plan_ready": plan["ready_for_transfer"],
            "plan_sha256": plan["plan_sha256"],
            "mapping_sha256": frozen["mapping_sha256"],
            "frozen_rehearsal": sealed["reconciled"] and sealed["rolled_back"],
            "reconciled": rehearsal["reconciled"],
            "rolled_back": rehearsal["rolled_back"],
            "plan_properties": [{"property": row["target_property"],
                "stock": row["opening_stock"]} for row in plan["properties"]]},
            ensure_ascii=False, default=str))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
