"""Rehearse a native ERPNext USD supplier credit ZIP on the PMS-only site."""

import json
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe

from hospitality_suite import api, erp_fiscal_history, setup
from hospitality_suite.service import insert, operation


def run(metadata_file=None):
    if ("erpnext" in frappe.get_installed_apps() or
            not frappe.local.site.startswith("hs-pms-smoke")):
        frappe.throw("Use únicamente el sitio PMS de ensayo")
    if not isinstance(metadata_file, str) or not re.fullmatch(
            r"hs-real-fx-vendor-[0-9a-f]{32}\.json", metadata_file):
        frappe.throw("Indique el recibo de prueba del paquete")
    frappe.set_user("Administrator")
    metadata_path = Path(frappe.get_site_path("private", "files",
                                              metadata_file))
    details = json.loads(metadata_path.read_text(encoding="utf-8"))
    bundle_path = Path(frappe.get_site_path("private", "files",
                                            details["bundle_file"]))
    source_hash = details["source_sha256"]
    manifest_hash = details["manifest_sha256"]
    manifest, inventory = erp_fiscal_history.load_source_inventory(
        details["bundle_file"], source_hash, manifest_hash)
    source = inventory["properties"][0]
    if (len(inventory["properties"]) != 1 or
            source["property"] != details["source_property"] or
            manifest["documents"] or not bundle_path.is_file()):
        frappe.throw("El paquete real no corresponde al recibo")
    savepoint = "hs_real_foreign_vendor_target"
    frappe.db.savepoint(savepoint)
    try:
        suffix = uuid4().hex
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Destino proveedor USD " + suffix,
            "base_currency": "NIO", "tax_regime": "General",
            "active": 1}).insert()
        created = setup.create_property({
            "property_name": "Destino proveedor USD " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel",
            "business_date": source["business_date"]},
            "real-fx-vendor-target-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.append("accepted_currencies", {"currency": "USD"})
        prop.save()
        with operation(prop):
            bridge = insert("HS Account", prop, organization=org.name,
                account_code="1998-" + suffix[:8],
                account_name="Puente proveedor USD", root_type="Asset",
                account_type="Temporary", account_currency="NIO",
                active=1, is_group=0)
            accounts = {}
            for index, row in enumerate(source["mapping_requirements"]
                                        ["accounts"], start=1):
                accounts[row["name"]] = insert("HS Account", prop,
                    organization=org.name,
                    account_code=f"{1200 + index}-{suffix[:8]}",
                    account_name="Destino " + row["name"][:90],
                    root_type=row["root_type"],
                    account_type=row.get("account_type") or "General",
                    account_currency=row["account_currency"],
                    active=1, is_group=0)
            supplier = insert("HS Party", prop, organization=org.name,
                party_name="Proveedor nota USD real",
                party_type="Supplier", active=1)
        imported = erp_fiscal_history.import_bundle(
            details["bundle_file"], source_hash, manifest_hash,
            {source["property"]: prop.name})
        if imported["imported"] != 0:
            frappe.throw("El paquete de proveedor creó archivo fiscal de venta")
        mapping = api.erp_to_pms_mapping_template(
            details["bundle_file"], source_hash, manifest_hash)
        mapped = mapping["properties"][source["property"]]
        mapped["property"] = prop.name
        mapped["temporary_opening_account"] = bridge.name
        mapped["accounts"].update({name: target.name
                                   for name, target in accounts.items()})
        mapped["suppliers"][details["source_supplier"]] = supplier.name
        reviewed = api.erp_to_pms_mapping_review(details["bundle_file"],
            source_hash, manifest_hash, mapping)
        if not reviewed["mapping_ready"]:
            frappe.throw("El mapa del proveedor no pasó: " +
                         frappe.as_json(reviewed["blockers"]))
        plan = api.erp_to_pms_transfer_plan(details["bundle_file"],
            source_hash, manifest_hash, mapping)
        credits = plan["properties"][0]["opening_supplier_credits"]
        if (not plan["arithmetically_balanced"] or len(credits) != 1 or
                credits[0]["source"] != details["source_note"] or
                Decimal(credits[0]["signed_account_balance"]) != 50 or
                Decimal(credits[0]["signed_base_balance"]) != 1800):
            frappe.throw("El plan real no concilió: " +
                         frappe.as_json(plan["blockers"]))
        from hospitality_suite import erp_to_pms_transfer_rehearsal as writer

        original_verify = writer._verify_property

        def inspect_posting(target, expected, stock):
            credit = frappe.db.get_value("HS PMS Opening Supplier Credit", {
                "property": target.name,
                "opening_source_name": details["source_note"]},
                ["name", "currency", "amount", "base_currency",
                 "base_amount", "payable_account", "supplier", "journal"],
                as_dict=True)
            if (not credit or credit.currency != "USD" or
                    Decimal(str(credit.amount)) != 50 or
                    credit.base_currency != "NIO" or
                    Decimal(str(credit.base_amount)) != 1800 or
                    credit.payable_account != accounts[
                        details["source_ap"]].name or
                    credit.supplier != supplier.name):
                frappe.throw("La publicación real perdió el crédito USD")
            lines = frappe.get_all("HS Journal Line", filters={
                "parent": credit.journal}, fields=["account", "party",
                "debit", "credit", "debit_in_account_currency",
                "credit_in_account_currency"])
            actual = {(line.account, line.party,
                Decimal(str(line.debit)), Decimal(str(line.credit)),
                Decimal(str(line.debit_in_account_currency)),
                Decimal(str(line.credit_in_account_currency)))
                for line in lines}
            if actual != {
                    (accounts[details["source_ap"]].name, supplier.name,
                     Decimal(1800), Decimal(0), Decimal(50), Decimal(0)),
                    (bridge.name, None, Decimal(0), Decimal(1800),
                     Decimal(0), Decimal(1800))}:
                frappe.throw("El asiento real no conservó las dos monedas")
            original_verify(target, expected, stock)

        with patch.object(writer, "_verify_property",
                          side_effect=inspect_posting):
            rehearsal = api.erp_to_pms_transfer_rehearsal(
                details["bundle_file"], source_hash, manifest_hash, mapping,
                plan["plan_sha256"])
        if (not rehearsal["reconciled"] or not rehearsal["rolled_back"] or
                len(rehearsal["properties"][0]["supplier_credits"]) != 1 or
                frappe.db.exists("HS PMS Opening Supplier Credit", {
                    "property": prop.name})):
            frappe.throw("El paquete real dejó saldos tras el ensayo")
        return {"real_erpnext_package": True,
            "source_note": details["source_note"],
            "principal_usd": "50.00", "base_nio": "1800.00",
            "mapping_reconciled": True,
            "opening_rehearsed_and_rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
