"""Rehearse a real partially used ERPNext USD advance on the PMS-only site."""

import json
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe

from hospitality_suite import api, erp_fiscal_history, setup
from hospitality_suite.service import insert, operation


def run(metadata_file):
    if ("erpnext" in frappe.get_installed_apps() or
            not frappe.local.site.startswith("hs-pms-smoke") or
            not isinstance(metadata_file, str) or not re.fullmatch(
                r"hs-real-fx-advance-[0-9a-f]{32}\.json", metadata_file)):
        frappe.throw("Indique un recibo válido en el sitio PMS de ensayo")
    frappe.set_user("Administrator")
    details = json.loads(Path(frappe.get_site_path("private", "files",
        metadata_file)).read_text(encoding="utf-8"))
    source_hash = details["source_sha256"]
    manifest_hash = details["manifest_sha256"]
    manifest, inventory = erp_fiscal_history.load_source_inventory(
        details["bundle_file"], source_hash, manifest_hash)
    source = inventory["properties"][0]
    if (len(inventory["properties"]) != 1 or
            source["property"] != details["source_property"] or
            len(manifest["documents"]) != 1 or
            source["deposits"]["customer_credits"][0]["voucher"] !=
                details["payment"]):
        frappe.throw("El paquete no corresponde al anticipo inspeccionado")
    marker = "hs_real_foreign_advance_target"
    frappe.db.savepoint(marker)
    try:
        suffix = uuid4().hex
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Destino anticipo USD " + suffix,
            "base_currency": "NIO", "tax_regime": "General",
            "active": 1}).insert()
        created = setup.create_property({
            "property_name": "Destino anticipo USD " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel",
            "business_date": source["business_date"]},
            "real-fx-advance-target-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.append("accepted_currencies", {"currency": "USD"})
        prop.save()
        with operation(prop):
            bridge = insert("HS Account", prop, organization=org.name,
                account_code="1998-" + suffix[:8],
                account_name="Puente anticipo USD", root_type="Asset",
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
                    active=1, is_group=0,
                    is_bank=int(row.get("account_type") == "Bank"))
            customer = insert("HS Party", prop, organization=org.name,
                party_name="Cliente anticipo USD real",
                party_type="Customer", active=1)
        imported = erp_fiscal_history.import_bundle(
            details["bundle_file"], source_hash, manifest_hash,
            {source["property"]: prop.name})
        archive = frappe.db.get_value("HS Historical Fiscal Document", {
            "property": prop.name, "source_doctype": "Sales Invoice",
            "source_name": details["source_invoice"]},
            ["currency", "document_type", "pdf_sha256"], as_dict=True)
        if (imported["imported"] != 1 or not archive or
                archive.currency != "USD" or
                archive.document_type != "Invoice" or
                archive.pdf_sha256 != manifest["documents"][0]["pdf_sha256"]):
            frappe.throw("La factura cubierta por el anticipo no se archivó")
        mapping = api.erp_to_pms_mapping_template(
            details["bundle_file"], source_hash, manifest_hash)
        mapped = mapping["properties"][source["property"]]
        mapped["property"] = prop.name
        mapped["temporary_opening_account"] = bridge.name
        mapped["accounts"].update({name: target.name
                                   for name, target in accounts.items()})
        mapped["customers"][details["source_customer"]] = customer.name
        reviewed = api.erp_to_pms_mapping_review(details["bundle_file"],
            source_hash, manifest_hash, mapping)
        if not reviewed["mapping_ready"]:
            frappe.throw("El mapa del anticipo no pasó: " +
                         frappe.as_json(reviewed["blockers"]))
        plan = api.erp_to_pms_transfer_plan(details["bundle_file"],
            source_hash, manifest_hash, mapping)
        advances = plan["properties"][0]["opening_advances"]
        if (not plan["arithmetically_balanced"] or len(advances) != 1 or
                advances[0]["source"] != details["payment"] or
                Decimal(advances[0]["signed_account_balance"]) != -30 or
                Decimal(advances[0]["signed_base_balance"]) != -1080):
            frappe.throw("El plan no concilió el anticipo abierto: " +
                         frappe.as_json(plan["blockers"]))
        from hospitality_suite import erp_to_pms_transfer_rehearsal as writer

        original_verify = writer._verify_property

        def inspect_posting(target, expected, stock):
            credit = frappe.db.get_value("HS PMS Opening Credit", {
                "property": target.name,
                "opening_source_doctype": "Payment Entry",
                "opening_source_name": details["payment"]},
                ["name", "credit_kind", "currency", "amount",
                 "base_currency", "base_amount", "receivable_account",
                 "customer", "journal"], as_dict=True)
            if (not credit or credit.credit_kind != "Advance" or
                    credit.currency != "USD" or
                    Decimal(str(credit.amount)) != 30 or
                    credit.base_currency != "NIO" or
                    Decimal(str(credit.base_amount)) != 1080 or
                    credit.receivable_account != accounts[
                        details["source_ar"]].name or
                    credit.customer != customer.name):
                frappe.throw("La apertura perdió el anticipo extranjero")
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
                    (bridge.name, None, Decimal(1080), Decimal(0),
                     Decimal(1080), Decimal(0)),
                    (accounts[details["source_ar"]].name, customer.name,
                     Decimal(0), Decimal(1080), Decimal(0), Decimal(30))}:
                frappe.throw("El asiento del anticipo no conservó ambas monedas")
            original_verify(target, expected, stock)

        with patch.object(writer, "_verify_property",
                          side_effect=inspect_posting):
            rehearsal = api.erp_to_pms_transfer_rehearsal(
                details["bundle_file"], source_hash, manifest_hash, mapping,
                plan["plan_sha256"])
        if (not rehearsal["reconciled"] or not rehearsal["rolled_back"] or
                len(rehearsal["properties"][0]["credits"]) != 1 or
                frappe.db.exists("HS PMS Opening Credit", {
                    "property": prop.name})):
            frappe.throw("El ensayo del anticipo no revirtió los registros")
        return {"real_erpnext_package": True,
            "source_payment": details["payment"],
            "remaining_usd": "30.00", "base_nio": "1080.00",
            "invoice_pdf_verified": True,
            "opening_rehearsed_and_rolled_back": True}
    finally:
        frappe.db.rollback(save_point=marker)
