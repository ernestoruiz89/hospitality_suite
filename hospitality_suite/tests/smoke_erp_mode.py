"""Read-only checks on a disposable Frappe + ERPNext + Suite site."""

from copy import deepcopy
from hashlib import sha256
from unittest.mock import patch
from uuid import uuid4

import frappe

from hospitality_suite.schema import ERP_LINK_TARGETS
from hospitality_suite.standalone_accounting import provider
from hospitality_suite.service import canonical


def run():
    if not frappe.local.site.startswith("hs-erp-smoke"):
        frappe.throw("Use únicamente el sitio de ensayo ERPNext")
    assert "erpnext" in frappe.get_installed_apps()
    assert provider() == "erpnext"
    from hospitality_suite import api
    source = api.erp_to_pms_preflight()
    assert source["ready_for_mapping"] == (not source["blockers"])
    assert not source["cutover_performed"]
    previous_user = frappe.session.user
    try:
        frappe.set_user("Guest")
        try:
            api.erp_to_pms_preflight()
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("A guest read the reverse-cutover source inventory")
    finally:
        frappe.set_user(previous_user)
    for (doctype, field), target in ERP_LINK_TARGETS.items():
        if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("DocType", target):
            continue
        actual = frappe.get_meta(doctype).get_field(field)
        assert actual and (actual.fieldtype, actual.options) == ("Link", target), (doctype, field)
    assert frappe.db.get_single_value("HS Site Mode", "provider") == "ERPNext"
    from hospitality_suite import pms_cutover_mapping
    source = {"source_sha256": "test-source", "blockers": [], "properties": [{
        "property": "HS-MAPPING-TEST", "organization": "HS-ORG-TEST",
        "currency": "USD", "ledger": {"accounts": [{"name": "HS-ACCOUNT-TEST",
            "root_type": "Asset", "account_type": "Cash",
            "account_currency": "USD", "is_group": 0}]},
        "stock_positions": [], "open_receivables": [], "open_payables": [],
        "mapping_requirements": {"accounts": ["HS-ACCOUNT-TEST"],
            "parties": [], "products": [], "warehouses": []}}]}
    mapping = {"source_sha256": "test-source", "properties": {"HS-MAPPING-TEST": {
        "company": "NONEXISTENT-COMPANY", "cost_center": "NONEXISTENT-COST-CENTER",
        "temporary_opening_account": "NONEXISTENT-TEMPORARY-ACCOUNT",
        "accounts": {"HS-ACCOUNT-TEST": "NONEXISTENT-ACCOUNT"},
        "parties": {}, "products": {}, "warehouses": {}}}}
    with patch.object(pms_cutover_mapping, "preflight", return_value=source):
        reviewed = pms_cutover_mapping.review(mapping)
    assert not reviewed["mapping_complete"] and not reviewed["cutover_performed"]
    assert {"incompatible_company", "incompatible_cost_center",
            "incompatible_temporary_opening_account",
            "missing_target_record"}.issubset(
        {row["code"] for row in reviewed["mapping_blockers"]})
    reused = deepcopy(mapping)
    reused["properties"]["HS-MAPPING-TEST"]["temporary_opening_account"] = "NONEXISTENT-ACCOUNT"
    with patch.object(pms_cutover_mapping, "preflight", return_value=source):
        reused_review = pms_cutover_mapping.review(reused)
    assert "temporary_account_reused" in {row["code"] for row in
        reused_review["mapping_blockers"]}
    legacy = deepcopy(mapping)
    legacy["properties"]["HS-MAPPING-TEST"]["legacy_links"] = {
        "Price List": {"OLD-PRICE-LIST": "NONEXISTENT-PRICE-LIST"}}
    with patch.object(pms_cutover_mapping, "preflight", return_value=source):
        legacy_review = pms_cutover_mapping.review(legacy)
    assert "incompatible_legacy_link_target" in {row["code"] for row in
        legacy_review["mapping_blockers"]}
    from hospitality_suite import pms_cutover_plan
    amounts = [("CASH", "Cash", "20", "20"),
               ("AR", "Receivable", "100", "100"),
               ("AP", "Payable", "-40", "-40"),
               ("STOCK", "Stock", "30", "30"),
               ("EQUITY", "Equity", "-110", "-110")]
    source_plan = {"source_sha256": "source-plan", "properties": [{
        "property": "HOTEL", "organization": "ORG", "currency": "USD",
        "business_date": "2026-10-25",
        "ledger": {"accounts": [dict(name=key, account_type=type_,
            root_type=("Asset" if type_ in ("Cash", "Receivable", "Stock")
                       else "Liability" if type_ == "Payable" else "Equity"),
            account_currency="USD", balance=base, original_balance=original)
            for key, type_, base, original in amounts]},
        "open_receivables": [dict(source="AR-1", reference="VENTA-1",
            account="AR", party="GUEST", currency="USD", due_date="2026-11-25",
            outstanding="100")],
        "open_payables": [dict(source="PUR-1", kind="Purchase", reference="PROV-1",
            account="AP", party="VENDOR", outstanding="50"),
            dict(source="RET-1", kind="Supplier Credit", account="AP",
                 party="VENDOR", outstanding="10")],
        "stock_positions": [dict(product="ITEM", warehouse="STORE",
            inventory_account="STOCK", quantity="3", value="30")]}]}
    plan_mapping = {"properties": {"HOTEL": {"company": "ERP CO",
        "cost_center": "HOTEL - ERP CO", "temporary_opening_account": "OPENING - ERP CO",
        "accounts": {key: key + " - ERP CO" for key, *_ in amounts},
        "parties": {"GUEST": {"customer": "ERP GUEST"},
                    "VENDOR": {"supplier": "ERP VENDOR"}},
        "products": {"ITEM": "ERP ITEM"}, "warehouses": {"STORE": "ERP STORE"}}}}
    plan = pms_cutover_plan.build(source_plan, plan_mapping)
    hotel = plan["properties"][0]
    assert plan["arithmetically_balanced"] and not plan["cutover_performed"]
    with (patch.object(pms_cutover_mapping, "review", return_value={
            "source_and_mapping_ready": True, "source_sha256": "source-plan"}),
          patch.object(pms_cutover_plan.pms_cutover, "preflight", return_value=source_plan)):
        integrated = pms_cutover_plan.review(plan_mapping)
    assert integrated["plan"]["plan_sha256"] == plan["plan_sha256"]
    assert integrated["link_manifest"]["link_sha256"]
    assert len(hotel["opening_receivables"]) == len(hotel["opening_payables"]) == 1
    assert len(hotel["opening_supplier_credits"]) == len(hotel["opening_stock"]) == 1
    assert (hotel["control_total"], hotel["journal_debit"],
            hotel["journal_credit"], hotel["temporary_net"]) == ("90", "110", "110", "0")
    pnl_source = deepcopy(source_plan)
    pnl_source["properties"][0]["ledger"]["accounts"].append(dict(
        name="PETTY EXPENSE", account_type="Expense Account", root_type="Expense",
        account_currency="USD", balance="5", original_balance="5"))
    pnl_source["properties"][0]["ledger"]["accounts"][-2]["balance"] = "-115"
    pnl_source["properties"][0]["ledger"]["accounts"][-2]["original_balance"] = "-115"
    pnl_mapping = deepcopy(plan_mapping)
    pnl_mapping["properties"]["HOTEL"]["accounts"]["PETTY EXPENSE"] = "PETTY EXPENSE - ERP CO"
    pnl_plan = pms_cutover_plan.build(pnl_source, pnl_mapping)
    pnl_hotel = pnl_plan["properties"][0]
    assert pnl_plan["arithmetically_balanced"] and pnl_hotel["profit_loss_debit"] == "5"
    assert {row["source_account"] for row in pnl_hotel["profit_loss_transfer_journal"]} == {
        "PETTY EXPENSE", None}
    assert all(row["source_account"] != "PETTY EXPENSE" for row in
               pnl_hotel["opening_journal"])
    mismatched_source = deepcopy(source_plan)
    mismatched_source["properties"][0]["open_receivables"][0]["outstanding"] = "99"
    mismatched = pms_cutover_plan.build(mismatched_source, plan_mapping)
    assert not mismatched["arithmetically_balanced"]
    assert {"planned_control_mismatch", "opening_journal_unbalanced"}.issubset(
        {row["code"] for row in mismatched["blockers"]})
    fx_source = {"source_sha256": "fx-source", "properties": [{
        "property": "FX HOTEL", "organization": "FX ORG", "currency": "USD",
        "business_date": "2026-10-25",
        "ledger": {"accounts": [
            dict(name="EUR CASH", account_type="Cash", root_type="Asset", account_currency="EUR",
                 balance="200", original_balance="100"),
            dict(name="EQUITY", account_type="Equity", root_type="Equity", account_currency="USD",
                 balance="-200", original_balance="-200")]},
        "open_receivables": [], "open_payables": [], "stock_positions": []}]}
    fx_map = {"properties": {"FX HOTEL": {"company": "ERP CO",
        "cost_center": "FX - ERP CO", "temporary_opening_account": "OPENING - ERP CO",
        "accounts": {"EUR CASH": "EUR CASH - ERP CO", "EQUITY": "EQUITY - ERP CO"},
        "parties": {}, "products": {}, "warehouses": {}}}}
    fx_plan = pms_cutover_plan.build(fx_source, fx_map)
    assert fx_plan["arithmetically_balanced"]
    assert next(row for row in fx_plan["properties"][0]["opening_journal"]
                if row["source_account"] == "EUR CASH")["exchange_rate"] == "2"
    from hospitality_suite import pms_cutover_links
    suffix = uuid4().hex[:8]
    old_company = "HS-OLD-" + suffix
    target_company = "HS-ERP-" + suffix
    property_name = "HS-LINK-" + suffix
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_link_rewrite_smoke")
    try:
        frappe.db.sql("INSERT INTO `tabCompany` (name,default_currency) VALUES (%s,%s)",
                      (target_company, "USD"))
        frappe.db.sql("INSERT INTO `tabHS Property` (name,company,organization,currency) "
                      "VALUES (%s,%s,%s,%s)",
                      (property_name, old_company, old_company, "USD"))
        payload = {"schema_version": 7, "source_sha256": "link-source",
            "rewrites": [{"property": property_name, "doctype": "HS Property",
                "field": "company", "target_type": "Company",
                "source": old_company, "target": target_company, "count": 1}],
            "snapshot_rewrites": [], "experience_rewrites": [],
            "laundry_rewrites": [],
            "agent_rewrites": [], "billing_party_creations": [],
            "retained": [], "blockers": []}
        digest = sha256(canonical(payload).encode()).hexdigest()
        manifest = {**payload, "link_sha256": digest, "links_resolved": True}
        changed = pms_cutover_links.apply(manifest, digest)
        assert changed["rows_updated"] == 1
        assert frappe.db.get_value("HS Property", property_name, "company") == target_company
        try:
            pms_cutover_links.apply(manifest, digest)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó de nuevo un manifiesto de enlaces ya aplicado")
    finally:
        frappe.db.rollback(save_point="hs_link_rewrite_smoke")
        frappe.set_user(original_user)
    return {"provider": "erpnext", "restored_links": len(ERP_LINK_TARGETS)}
