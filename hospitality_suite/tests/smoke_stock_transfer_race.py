"""Verify that competing PMS transfers cannot consume the same stock twice."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_accounting import balance, provider
from hospitality_suite.standalone_inventory import current_balance
from hospitality_suite.tests.financial_race import race_command


SITE = "hs-pms-smoke-room.local"


def _verify(prop_name, product, source, target, inventory, clearing,
            equity, *, transfers, source_qty, target_qty):
    frappe.db.rollback()
    prop = frappe.get_doc("HS Property", prop_name)
    source_balance = current_balance(prop, product, source)
    target_balance = current_balance(prop, product, target)
    rows = frappe.get_all("HS Stock Transfer", filters={
        "property": prop_name},
        fields=["name", "source_movement", "target_movement",
            "quantity", "value", "reference"], limit_page_length=0)
    movements = frappe.get_all("HS Stock Movement", filters={
        "property": prop_name}, fields=["name", "journal", "purpose"],
        limit_page_length=0)
    journals = set(frappe.get_all("HS Journal", filters={
        "property": prop_name}, pluck="name", limit_page_length=0))
    if (source_balance != (Decimal(source_qty), Decimal(source_qty * 10)) or
            target_balance != (Decimal(target_qty), Decimal(target_qty * 10)) or
            len(rows) != transfers or len(movements) != 1 + transfers * 2 or
            journals != {row.journal for row in movements} or
            any(not row.source_movement or not row.target_movement or
                Decimal(str(row.quantity)) != 1 or Decimal(str(row.value)) != 10
                for row in rows) or
            Decimal(balance(prop, inventory)) != 20 or
            Decimal(balance(prop, clearing)) != 0 or
            Decimal(balance(prop, equity)) != -20 or
            frappe.db.count("HS Audit Event", {"property": prop_name,
                "action": "pms_stock_transfer"}) != transfers or
            frappe.db.count("HS Request", {"property": prop_name,
                "operation": "pms_transfer_stock"}) != transfers):
        raise AssertionError("Stock, transfer legs and ledger did not reconcile")
    return rows


def _remove(property_name, organization):
    frappe.db.rollback()
    scoped = ("HS Stock Movement", "HS Stock Transfer", "HS Journal",
        "HS Product", "HS Warehouse", "HS Account", "HS Audit Event",
        "HS Request")
    journals = []
    if property_name:
        journals = frappe.get_all("HS Journal", filters={
            "property": property_name}, pluck="name", limit_page_length=0)
        if journals:
            frappe.db.delete("HS Journal Line", {"parent": ["in", journals]})
        for doctype in scoped:
            frappe.db.delete(doctype, {"property": property_name})
        frappe.db.delete("HS Property", {"name": property_name})
    if organization:
        frappe.db.delete("HS Organization", {"name": organization})
    frappe.db.commit()
    if (property_name and frappe.db.exists("HS Property", property_name) or
            organization and frappe.db.exists("HS Organization", organization) or
            property_name and any(frappe.db.count(doctype, {
                "property": property_name}) for doctype in scoped) or
            journals and frappe.db.count("HS Journal Line", {
                "parent": ["in", journals]})):
        raise AssertionError("Disposable stock fixture was not removed")


def run():
    if (frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps() or
            provider() != "pms" or frappe.session.user != "Administrator"):
        frappe.throw("Use only the disposable Frappe-only PMS site as Administrator")
    suffix = uuid4().hex[:12]
    property_name = None
    organization = None
    try:
        created = api.create_property({
            "property_name": "Stock Race QA " + suffix,
            "new_organization": {"legal_name": "Stock Race Legal " + suffix},
            "currency": "NIO", "mode": "Hotel",
        }, "stock-race-property-" + suffix)
        property_name = created["property"]
        prop = frappe.get_doc("HS Property", property_name)
        organization = prop.organization

        def account(code, label, root, kind=None):
            data = {"account_code": code + suffix,
                "account_name": label, "root_type": root}
            if kind:
                data["account_type"] = kind
            return api.execute(property_name, "pms_account",
                "stock-race-account-" + code + suffix, data)["account"]

        inventory = account("1150", "Inventario de prueba", "Asset", "Stock")
        clearing = account("1190", "Tránsito de prueba", "Asset", "Temporary")
        equity = account("3000", "Patrimonio de prueba", "Equity")
        source = api.execute(property_name, "pms_warehouse",
            "stock-race-source-" + suffix,
            {"warehouse_code": "SOURCE" + suffix,
             "warehouse_name": "Origen"})["warehouse"]
        target = api.execute(property_name, "pms_warehouse",
            "stock-race-target-" + suffix,
            {"warehouse_code": "TARGET" + suffix,
             "warehouse_name": "Destino"})["warehouse"]

        def create_product(locked):
            return insert("HS Product", locked, organization=organization,
                product_code="STOCK" + suffix,
                product_name="Producto de traslado",
                product_type="Stock", inventory_account=inventory,
                active=1).name

        product = command(property_name, "setup", "stock-race-product-" + suffix,
            {"operation": "stock_race_product"}, create_product)
        opening = api.execute(property_name, "pms_opening_stock",
            "stock-race-opening-" + suffix,
            {"product": product, "warehouse": source,
             "quantity": "2", "value": "20.00",
             "equity_account": equity, "reference": "STOCK-OPEN-" + suffix})
        if opening["balance_quantity"] != "2":
            raise AssertionError("The opening stock is not two units")
        frappe.db.commit()

        data = {"product": product, "source_warehouse": source,
            "target_warehouse": target, "quantity": "1",
            "clearing_account": clearing,
            "reference": "STOCK-TRANSFER-ONE-" + suffix,
            "reason": "Primera unidad del ensayo"}
        sites_path = Path(frappe.local.sites_path).resolve()
        first = race_command(SITE, sites_path, property_name,
            "pms_transfer_stock", data,
            "stock-race-same-" + suffix, same_key=True)
        rows = _verify(property_name, product, source, target,
            inventory, clearing, equity, transfers=1, source_qty=1,
            target_qty=1)
        if rows[0].name != first["transfer"]:
            raise AssertionError("The same-key transfer did not replay")
        frappe.db.commit()

        data["reference"] = "STOCK-TRANSFER-TWO-A-" + suffix
        data["reason"] = "Última unidad del ensayo"
        competitor = {**data,
            "reference": "STOCK-TRANSFER-TWO-B-" + suffix}
        second = race_command(SITE, sites_path, property_name,
            "pms_transfer_stock", data,
            "stock-race-distinct-" + suffix, same_key=False,
            second_payload=competitor,
            rejected_message="No hay existencias suficientes para la salida")
        rows = _verify(property_name, product, source, target,
            inventory, clearing, equity, transfers=2, source_qty=0,
            target_qty=2)
        if (second["transfer"] not in {row.name for row in rows} or
                frappe.db.exists("HS Stock Transfer", {
                    "property": property_name,
                    "reference": competitor["reference"]})):
            raise AssertionError("The rejected transfer left a stock document")
        return {"site": SITE, "same_key": "same_result",
            "distinct_keys": "insufficient_stock_rejected",
            "source_quantity": "0", "target_quantity": "2",
            "inventory_value": "20.00", "clearing_balance": "0.00",
            "transfers": 2, "stock_movements": 5}
    finally:
        _remove(property_name, organization)
