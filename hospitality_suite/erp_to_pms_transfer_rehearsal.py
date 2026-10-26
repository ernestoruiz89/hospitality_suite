"""Rollback-only PMS opening publication from a verified ERPNext bundle.

This rollback-only writer supports base-currency financial openings, foreign
receivables, customer credit notes and supplier payables, stock, and the
mapped operation graph.
"""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import frappe
from frappe import _

from hospitality_suite import (erp_fiscal_history, erp_to_pms_balance_preview,
                               erp_to_pms_operations)
from hospitality_suite import erp_to_pms_transfer_plan, standalone_accounting
from hospitality_suite.ledger_rules import rate_for_base
from hospitality_suite import (standalone_inventory, standalone_opening_payables,
                               standalone_opening_credits,
                               standalone_opening_guarantees,
                               standalone_opening_supplier_credits)
from hospitality_suite.standalone_receivables import outstanding
from hospitality_suite.security import is_system
from hospitality_suite.service import insert, operation


LINE_FIELDS = ("account", "party", "debit", "credit", "account_currency",
    "exchange_rate", "debit_in_account_currency", "credit_in_account_currency")


def _line(row):
    return {key: row[key] for key in LINE_FIELDS if key in row}


def _post_property(prop, source_site, source_hash, plan):
    temporary = plan["temporary_opening_account"]
    refs = {"property": prop.name, "receivables": [], "payables": [],
            "credits": [], "supplier_credits": [], "guarantees": [],
            "stock_movements": [], "residual_journal": None}
    for row in plan["opening_receivables"]:
        value = row["signed_base_balance"]
        original = row["signed_account_balance"]
        currency = row["currency"]
        rate = (rate_for_base(original, value) if currency != prop.currency
                else "1")
        journal = standalone_accounting.post(prop,
            source_doctype="HS PMS Receivable", source_name=row["source"],
            purpose="Opening Receivable", memo="Cartera de apertura ERPNext",
            lines=[{"account": row["account"], "party": row["party"],
                    "debit": value, "credit": "0",
                    "account_currency": currency, "exchange_rate": rate,
                    "debit_in_account_currency": original,
                    "credit_in_account_currency": "0"},
                   {"account": temporary, "debit": "0", "credit": value}])
        before = getattr(frappe.local, "hs_reverse_opening", None)
        frappe.local.hs_reverse_opening = source_hash
        try:
            receivable = insert("HS PMS Receivable", prop,
                organization=prop.organization, party=row["party"],
                reference=row["source"],
                description="Saldo abierto ERPNext " + row["source"],
                folio=row.get("folio"),
                business_date=prop.business_date,
                due_date=row["due_date"] or prop.business_date,
                currency=currency, amount=original,
                base_currency=prop.currency, base_amount=value,
                net_amount=original,
                tax_amount="0", tax_treatment="Unclassified",
                receivable_account=row["account"], journal=journal.name,
                opening_source_site=source_site,
                opening_source_name=row["source"],
                opening_source_sha256=source_hash,
                opening_temporary_account=temporary, status="Posted")
        finally:
            frappe.local.hs_reverse_opening = before
        if outstanding(prop, receivable.name) != Decimal(original):
            frappe.throw(_("La factura abierta no conserva el saldo cobrable"))
        refs["receivables"].append(receivable.name)
    for group, kind in (("opening_customer_credits", "Credit Note"),
                        ("opening_advances", "Advance")):
        for row in plan[group]:
            value = str(-Decimal(row["signed_base_balance"]))
            original = str(-Decimal(row["signed_account_balance"]))
            currency = row["currency"]
            rate = (rate_for_base(original, value) if currency != prop.currency
                    else "1")
            source_doctype = ("Sales Invoice" if kind == "Credit Note" else
                              row["voucher_type"])
            source_name = source_doctype + "|" + row["source"]
            journal = standalone_accounting.post(prop,
                source_doctype="HS PMS Opening Credit", source_name=source_name,
                purpose="Opening Credit", memo="Crédito de cliente ERPNext",
                lines=[{"account": temporary, "debit": value, "credit": "0"},
                       {"account": row["account"], "party": row["party"],
                        "debit": "0", "credit": value,
                        "account_currency": currency, "exchange_rate": rate,
                        "debit_in_account_currency": "0",
                        "credit_in_account_currency": original}])
            before = getattr(frappe.local, "hs_reverse_opening", None)
            frappe.local.hs_reverse_opening = source_hash
            try:
                credit = insert("HS PMS Opening Credit", prop,
                    organization=prop.organization, credit_kind=kind,
                    customer=row["party"],
                    opening_source_doctype=source_doctype,
                    opening_source_site=source_site,
                    opening_source_name=row["source"],
                    opening_source_sha256=source_hash,
                    opening_temporary_account=temporary,
                    receivable_account=row["account"],
                    business_date=prop.business_date,
                    currency=currency, amount=original,
                    base_currency=prop.currency, base_amount=value,
                    journal=journal.name, status="Posted")
            finally:
                frappe.local.hs_reverse_opening = before
            if standalone_opening_credits.available(prop, credit.name) != Decimal(original):
                frappe.throw(_("El crédito trasladado no conserva su saldo disponible"))
            refs["credits"].append(credit.name)
    for row in plan["opening_guarantees"]:
        value = str(-Decimal(row["signed_base_balance"]))
        journal = standalone_accounting.post(prop,
            source_doctype="HS PMS Opening Guarantee", source_name=row["source"],
            purpose="Opening Guarantee", memo="Garantía de apertura ERPNext",
            lines=[{"account": temporary, "debit": value, "credit": "0"},
                   {"account": row["account"], "debit": "0", "credit": value}])
        before = getattr(frappe.local, "hs_reverse_opening", None)
        frappe.local.hs_reverse_opening = source_hash
        try:
            guarantee = insert("HS PMS Opening Guarantee", prop,
                organization=prop.organization, customer=row["customer"],
                opening_source_site=source_site,
                opening_source_name=row["source"],
                opening_source_sha256=source_hash,
                source_booking=row.get("booking"), source_stay=row.get("stay"),
                source_folio=row.get("folio"),
                opening_temporary_account=temporary,
                liability_account=row["account"],
                business_date=prop.business_date, currency=prop.currency,
                amount=value, journal=journal.name, status="Posted")
        finally:
            frappe.local.hs_reverse_opening = before
        if standalone_opening_guarantees.available(prop, guarantee.name) != Decimal(value):
            frappe.throw(_("La garantía trasladada no conserva su saldo disponible"))
        refs["guarantees"].append(guarantee.name)
    for row in plan["opening_payables"]:
        value = str(-Decimal(row["signed_base_balance"]))
        original = str(-Decimal(row["signed_account_balance"]))
        currency = row["currency"]
        rate = (rate_for_base(original, value) if currency != prop.currency
                else "1")
        journal = standalone_accounting.post(prop,
            source_doctype="HS PMS Opening Payable", source_name=row["source"],
            purpose="Opening Payable", memo="Proveedor de apertura ERPNext",
            lines=[{"account": temporary, "debit": value, "credit": "0"},
                   {"account": row["account"], "party": row["party"],
                    "debit": "0", "credit": value,
                    "account_currency": currency, "exchange_rate": rate,
                    "debit_in_account_currency": "0",
                    "credit_in_account_currency": original}])
        before = getattr(frappe.local, "hs_reverse_opening", None)
        frappe.local.hs_reverse_opening = source_hash
        try:
            payable = insert("HS PMS Opening Payable", prop,
                organization=prop.organization, supplier=row["party"],
                opening_source_site=source_site,
                opening_source_name=row["source"],
                opening_source_sha256=source_hash,
                opening_temporary_account=temporary,
                payable_account=row["account"],
                business_date=prop.business_date,
                due_date=row["due_date"] or prop.business_date,
                currency=currency, amount=original, base_amount=value,
                journal=journal.name, status="Posted")
        finally:
            frappe.local.hs_reverse_opening = before
        if (standalone_opening_payables.outstanding(prop, payable.name) !=
                Decimal(original)):
            frappe.throw(_("La factura del proveedor no conserva el saldo pagable"))
        refs["payables"].append(payable.name)
    for row in plan["opening_supplier_credits"]:
        value = str(Decimal(row["signed_base_balance"]))
        original = str(Decimal(row["signed_account_balance"]))
        currency = row["currency"]
        rate = (rate_for_base(original, value) if currency != prop.currency
                else "1")
        journal = standalone_accounting.post(prop,
            source_doctype="HS PMS Opening Supplier Credit",
            source_name=row["source"], purpose="Opening Supplier Credit",
            memo="Crédito de proveedor ERPNext",
            lines=[{"account": row["account"], "party": row["party"],
                    "debit": value, "credit": "0",
                    "account_currency": currency, "exchange_rate": rate,
                    "debit_in_account_currency": original,
                    "credit_in_account_currency": "0"},
                   {"account": temporary, "debit": "0", "credit": value}])
        before = getattr(frappe.local, "hs_reverse_opening", None)
        frappe.local.hs_reverse_opening = source_hash
        try:
            credit = insert("HS PMS Opening Supplier Credit", prop,
                organization=prop.organization, supplier=row["party"],
                opening_source_site=source_site,
                opening_source_name=row["source"],
                opening_source_sha256=source_hash,
                opening_temporary_account=temporary,
                payable_account=row["account"],
                business_date=prop.business_date, currency=currency,
                amount=original, base_currency=prop.currency, base_amount=value,
                journal=journal.name, status="Posted")
        finally:
            frappe.local.hs_reverse_opening = before
        if (standalone_opening_supplier_credits.available(prop, credit.name) !=
                Decimal(original)):
            frappe.throw(_("El crédito del proveedor no conserva su saldo disponible"))
        refs["supplier_credits"].append(credit.name)
    for row in plan["opening_stock"]:
        identity = (source_hash + "|" + prop.name + "|" + row["source_item"] +
                    "|" + row["source_warehouse"])
        opening = standalone_inventory.receive(prop,
            product=row["product"], warehouse=row["warehouse"],
            quantity=row["quantity"], value=row["stock_value"],
            counter_account=temporary,
            source_doctype="ERPNext Opening Stock",
            source_name=sha256(identity.encode()).hexdigest(),
            purpose="Opening Stock", memo="Existencias de apertura ERPNext")
        refs["stock_movements"].append(opening["movement"])
    if plan["residual_journal"]:
        journal = standalone_accounting.post(prop,
            source_doctype="ERPNext Opening Balance",
            source_name=source_hash,
            purpose="Opening Balance",
            lines=[_line(row) for row in plan["residual_journal"]],
            memo="Saldos residuales de apertura ERPNext")
        refs["residual_journal"] = journal.name
    return refs


def _verify_property(prop, expected, stock):
    rows = frappe.db.sql(
        "SELECT l.account,l.party,l.account_currency,"
        "SUM(l.debit-l.credit) AS base_balance,"
        "SUM(l.debit_in_account_currency-l.credit_in_account_currency) AS original_balance "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' "
        "GROUP BY l.account,l.party,l.account_currency",
        (prop.name,), as_dict=True)
    actual = defaultdict(lambda: [Decimal(0), Decimal(0)])
    desired = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in rows:
        key = (row.account, row.party, row.account_currency)
        actual[key][0] += Decimal(str(row.base_balance))
        actual[key][1] += Decimal(str(row.original_balance))
    for row in expected["net_balances"]:
        key = (row["account"], row["party"], row["account_currency"])
        desired[key][0] += Decimal(row["debit"]) - Decimal(row["credit"])
        desired[key][1] += (Decimal(row["debit_in_account_currency"]) -
                            Decimal(row["credit_in_account_currency"]))
    present = {key: tuple(value) for key, value in actual.items() if any(value)}
    source = {key: tuple(value) for key, value in desired.items() if any(value)}
    if present != source:
        frappe.throw(_("Los saldos PMS publicados no coinciden con el mayor ERPNext"))
    for row in stock:
        qty, value = standalone_inventory.current_balance(prop, row["product"],
                                                           row["warehouse"])
        if (qty, value) != (Decimal(row["quantity"]), Decimal(row["stock_value"])):
            frappe.throw(_("Las existencias PMS no coinciden con el paquete ERPNext"))


def _publish_validated(file_name, expected_source_sha256,
                       expected_manifest_sha256, mapping,
                       expected_plan_sha256, created_files):
    """Stage a hash-checked opening in the caller's transaction.

    The caller owns commit or rollback and must remove created files if it
    rolls back. No authority change occurs here.
    """
    if (not is_system() or standalone_accounting.provider() != "pms" or
            "erpnext" in frappe.get_installed_apps()):
        frappe.throw(_("La apertura inversa requiere un sitio PMS sin ERPNext"),
                     frappe.PermissionError)
    if not isinstance(created_files, list):
        frappe.throw(_("Conserve las evidencias creadas durante la apertura"))
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    plan = erp_to_pms_transfer_plan.review(file_name,
        expected_source_sha256, expected_manifest_sha256, mapping)
    if (not plan["arithmetically_balanced"] or
            plan.get("plan_sha256") != expected_plan_sha256):
        frappe.throw(_("El plan de apertura cambió o contiene bloqueos"))
    names = sorted(row["target_property"] for row in plan["properties"])
    for name in names:
        frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",
                      (name,))
    current = erp_to_pms_transfer_plan.review(file_name,
        expected_source_sha256, expected_manifest_sha256, mapping)
    if current.get("plan_sha256") != expected_plan_sha256:
        frappe.throw(_("El destino cambió durante el ensayo de apertura"))
    manifest, source_inventory = erp_fiscal_history.load_source_inventory(file_name,
        expected_source_sha256, expected_manifest_sha256)
    evidence = erp_fiscal_history.evidence_payloads(file_name,
        expected_source_sha256, expected_manifest_sha256)
    if {row["property"] for row in source_inventory["properties"]} != {
            row["source_property"] for row in plan["properties"]}:
        frappe.throw(_("El plan omite establecimientos del paquete de origen"))
    inspected = erp_to_pms_balance_preview.preview(file_name,
        expected_source_sha256, expected_manifest_sha256, mapping)
    by_name = {row["source_property"]: row for row in inspected["properties"]}
    references = []
    for row in plan["properties"]:
        prop = frappe.get_doc("HS Property", row["target_property"])
        with operation(prop):
            operations = erp_to_pms_operations.publish(prop,
                {"rows": row["operational_rows"], "blockers": row["blockers"]},
                evidence_payloads={(doctype, name): payload for
                    (source_prop, doctype, name), payload in evidence.items()
                    if source_prop == row["source_property"]},
                created_files=created_files)
            refs = _post_property(prop, manifest["source_site"],
                                  expected_source_sha256, row)
            refs["operations"] = operations
            _verify_property(prop, by_name[row["source_property"]],
                             row["opening_stock"])
        references.append(refs)
    return {"source_sha256": expected_source_sha256,
            "plan_sha256": expected_plan_sha256,
            "properties": references, "reconciled": True,
            "rolled_back": False, "provider_changed": False}


def rehearse(file_name, expected_source_sha256, expected_manifest_sha256,
             mapping, expected_plan_sha256):
    """Exercise the same writer and reconciliation, then undo all changes."""
    savepoint = "hs_reverse_opening_" + frappe.generate_hash(length=12)
    created_files = []
    frappe.db.savepoint(savepoint)
    try:
        staged = _publish_validated(file_name, expected_source_sha256,
            expected_manifest_sha256, mapping, expected_plan_sha256,
            created_files)
        return {**staged, "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
        for url, file_path in created_files:
            if not frappe.db.exists("File", {"file_url": url}):
                Path(file_path).unlink(missing_ok=True)
