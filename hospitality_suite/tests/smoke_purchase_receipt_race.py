"""Verify competing PMS purchase receipts and supplier payments."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_accounting import balance, provider
from hospitality_suite.standalone_inventory import current_balance
from hospitality_suite.standalone_purchase_orders import progress
from hospitality_suite.standalone_purchases import outstanding
from hospitality_suite.tests.financial_race import race_command


SITE = "hs-pms-smoke-room.local"


def _remove(property_name, organization, requester):
    frappe.db.rollback()
    parents = ("HS PMS Purchase", "HS PMS Purchase Order")
    children = ("HS PMS Purchase Line", "HS PMS Purchase Order Line")
    scoped = ("HS Payment", "HS Payment Method", "HS Stock Movement",
              "HS Journal", "HS Product", "HS Warehouse", "HS Account",
              "HS Party", "HS Audit Event",
              "HS Request") + parents
    journals = []
    child_parents = []
    if property_name:
        journals = frappe.get_all("HS Journal", filters={"property": property_name},
                                  pluck="name", limit_page_length=0)
        if journals:
            frappe.db.delete("HS Journal Line", {"parent": ["in", journals]})
        for parent, child in zip(parents, children):
            names = frappe.get_all(parent, filters={"property": property_name},
                                   pluck="name", limit_page_length=0)
            if names:
                child_parents.append((child, names))
                frappe.db.delete(child, {"parent": ["in", names]})
        for doctype in scoped:
            frappe.db.delete(doctype, {"property": property_name})
        frappe.db.delete("HS Property", {"name": property_name})
    if organization:
        frappe.db.delete("HS Organization", {"name": organization})
    if requester:
        frappe.delete_doc("User", requester, ignore_permissions=True, force=True)
    frappe.db.commit()
    if (property_name and frappe.db.exists("HS Property", property_name) or
            organization and frappe.db.exists("HS Organization", organization) or
            requester and frappe.db.exists("User", requester) or
            property_name and any(frappe.db.count(doctype, {"property": property_name})
                                  for doctype in scoped) or
            any(frappe.db.count(child, {"parent": ["in", names]})
                for child, names in child_parents) or
            journals and frappe.db.count("HS Journal Line", {"parent": ["in", journals]})):
        raise AssertionError("Disposable purchase fixture was not removed")


def _verify(property_name, product, warehouse, inventory, payable,
            order, order_line, *, received):
    frappe.db.rollback()
    prop = frappe.get_doc("HS Property", property_name)
    purchases = frappe.get_all("HS PMS Purchase", filters={
        "property": property_name, "purchase_order": order,
        "status": "Posted"}, fields=["name", "supplier_reference",
            "base_amount", "stock_movement"], limit_page_length=0)
    movements = frappe.get_all("HS Stock Movement", filters={
        "property": property_name}, fields=["name", "journal",
            "quantity_delta", "value_delta"], limit_page_length=0)
    qty, value = current_balance(prop, product, warehouse)
    expected_value = Decimal(received * 10)
    if (progress(prop, order_line) != Decimal(received) or
            (qty, value) != (Decimal(received), expected_value) or
            Decimal(balance(prop, inventory)) != expected_value or
            Decimal(balance(prop, payable)) != -expected_value or
            len(purchases) != received or len(movements) != received or
            {row.stock_movement for row in purchases} !=
                {row.name for row in movements} or
            any(Decimal(str(row.base_amount)) != 10 for row in purchases) or
            any(Decimal(str(row.quantity_delta)) != 1 or
                Decimal(str(row.value_delta)) != 10 or not row.journal
                for row in movements) or
            frappe.db.count("HS Journal", {"property": property_name}) != received + 1 or
            frappe.db.count("HS Audit Event", {"property": property_name,
                "action": "pms_purchase_received"}) != received or
            frappe.db.count("HS Request", {"property": property_name,
                "operation": "pms_receive_purchase"}) != received):
        raise AssertionError("Order, stock, payables and ledger did not reconcile")
    return purchases


def _verify_payments(property_name, bank, payable, equity, purchases, *, paid):
    frappe.db.rollback()
    prop = frappe.get_doc("HS Property", property_name)
    payments = frappe.get_all("HS Payment", filters={
        "property": property_name, "kind": "Supplier Payment",
        "status": "Posted"}, fields=["name", "pms_purchase", "pms_journal",
            "reference", "base_amount"], limit_page_length=0)
    paid_value = Decimal(paid * 10)
    if (len(payments) != paid or
            {row.pms_purchase for row in payments} != set(purchases[:paid]) or
            any(not row.pms_journal or Decimal(str(row.base_amount)) != 10
                for row in payments) or
            any(not frappe.db.exists("HS Journal", {
                "name": row.pms_journal, "property": property_name,
                "source_doctype": "HS Payment", "source_name": row.name,
                "purpose": "Supplier Payment"}) for row in payments) or
            Decimal(balance(prop, bank)) != 20 - paid_value or
            Decimal(balance(prop, payable)) != paid_value - 20 or
            Decimal(balance(prop, equity)) != -20 or
            any(outstanding(prop, name) != (Decimal(0) if index < paid else Decimal(10))
                for index, name in enumerate(purchases)) or
            frappe.db.count("HS Journal", {"property": property_name}) != 3 + paid or
            frappe.db.count("HS Audit Event", {"property": property_name,
                "action": "pms_supplier_paid"}) != paid or
            frappe.db.count("HS Request", {"property": property_name,
                "operation": "pms_pay_supplier"}) != paid):
        raise AssertionError("Supplier payment, payables and bank did not reconcile")
    return payments


def run():
    if (frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps() or
            provider() != "pms" or frappe.session.user != "Administrator"):
        frappe.throw("Use only the disposable Frappe-only PMS site as Administrator")
    suffix = uuid4().hex[:12]
    property_name = None
    organization = None
    requester = None
    try:
        created = api.create_property({
            "property_name": "Purchase Race QA " + suffix,
            "new_organization": {"legal_name": "Purchase Race Legal " + suffix},
            "currency": "NIO", "mode": "Hotel",
        }, "purchase-race-property-" + suffix)
        property_name = created["property"]
        prop = frappe.get_doc("HS Property", property_name)
        organization = prop.organization
        inventory = api.execute(property_name, "pms_account",
            "purchase-race-stock-" + suffix,
            {"account_code": "1150" + suffix,
             "account_name": "Inventario de prueba", "root_type": "Asset",
             "account_type": "Stock"})["account"]
        payable = api.execute(property_name, "pms_account",
            "purchase-race-payable-" + suffix,
            {"account_code": "2100" + suffix,
             "account_name": "Proveedores de prueba", "root_type": "Liability",
             "account_type": "Payable"})["account"]
        bank = api.execute(property_name, "pms_account",
            "purchase-race-bank-" + suffix,
            {"account_code": "1010" + suffix,
             "account_name": "Banco de prueba", "root_type": "Asset",
             "account_type": "Bank"})["account"]
        equity = api.execute(property_name, "pms_account",
            "purchase-race-equity-" + suffix,
            {"account_code": "3000" + suffix,
             "account_name": "Patrimonio de prueba", "root_type": "Equity"})["account"]
        method = api.execute(property_name, "pms_payment_method",
            "purchase-race-method-" + suffix,
            {"label": "Banco de compras", "account": bank})["method"]
        api.execute(property_name, "pms_opening_balance",
            "purchase-race-opening-" + suffix,
            {"reference": "PURCHASE-RACE-OPENING-" + suffix,
             "lines": [{"account": bank, "debit": "20.00", "credit": 0},
                       {"account": equity, "debit": 0, "credit": "20.00"}]})
        warehouse = api.execute(property_name, "pms_warehouse",
            "purchase-race-warehouse-" + suffix,
            {"warehouse_code": "PURCHASE" + suffix,
             "warehouse_name": "Almacén de compras"})["warehouse"]
        supplier = api.execute(property_name, "pms_supplier",
            "purchase-race-supplier-" + suffix,
            {"party_name": "Proveedor de prueba " + suffix})["supplier"]

        def create_product(locked):
            return insert("HS Product", locked, organization=organization,
                product_code="PURCHASE" + suffix,
                product_name="Producto de compra", product_type="Stock",
                inventory_account=inventory, active=1).name

        product = command(property_name, "setup", "purchase-race-product-" + suffix,
            {"operation": "purchase_race_product"}, create_product)

        requester = "purchase-race-" + suffix + "@example.invalid"
        frappe.get_doc(dict(doctype="User", email=requester,
            first_name="Solicitante de prueba", enabled=1,
            send_welcome_email=0,
            roles=[dict(role="System Manager")])).insert(ignore_permissions=True)
        order_data = {"supplier": supplier, "reference": "RACE-ORDER-" + suffix,
            "currency": "NIO", "payable_account": payable,
            "lines": [{"product": product, "warehouse": warehouse,
                "quantity": "2", "amount": "20.00", "recoverable_tax": "0.00"}]}
        try:
            frappe.set_user(requester)
            order_quote = api.pms_order_quote(property_name, order_data)
            pending = api.execute(property_name, "pms_order_request",
                "purchase-race-order-" + suffix,
                {**order_data, "acceptance": order_quote["acceptance"]})
        finally:
            frappe.set_user("Administrator")
        approved = api.execute(property_name, "pms_order_approve",
            "purchase-race-approve-" + suffix,
            {"order": pending["order"], "modified": pending["modified"]})
        if approved["status"] != "Approved":
            raise AssertionError("The purchase order was not approved")
        order = pending["order"]
        order_line = frappe.get_doc("HS PMS Purchase Order", order).lines[0].name
        frappe.db.commit()

        def receipt(reference):
            data = {"purchase_order": order, "supplier": supplier,
                "supplier_reference": reference, "invoice_currency": "NIO",
                "payable_account": payable, "lines": [{
                    "order_line": order_line, "product": product,
                    "warehouse": warehouse, "quantity": "1"}]}
            reviewed = api.pms_purchase_quote(property_name, data)
            return {**data, "acceptance": reviewed["acceptance"]}

        sites_path = Path(frappe.local.sites_path).resolve()
        same_payload = receipt("RACE-BILL-ONE-" + suffix)
        first = race_command(SITE, sites_path, property_name,
            "pms_receive_purchase", same_payload,
            "purchase-race-same-" + suffix, same_key=True)
        rows = _verify(property_name, product, warehouse, inventory,
            payable, order, order_line, received=1)
        if rows[0].name != first["purchase"]:
            raise AssertionError("The same-key receipt did not replay")
        frappe.db.commit()

        winner_payload = receipt("RACE-BILL-TWO-A-" + suffix)
        loser_payload = receipt("RACE-BILL-TWO-B-" + suffix)
        second = race_command(SITE, sites_path, property_name,
            "pms_receive_purchase", winner_payload,
            "purchase-race-distinct-" + suffix, same_key=False,
            second_payload=loser_payload,
            rejected_message="La recepción supera la cantidad pendiente de la orden")
        rows = _verify(property_name, product, warehouse, inventory,
            payable, order, order_line, received=2)
        if (second["purchase"] not in {row.name for row in rows} or
                any(row.supplier_reference == loser_payload["supplier_reference"]
                    for row in rows)):
            raise AssertionError("The rejected receipt left a purchase")
        purchases = [first["purchase"], second["purchase"]]
        frappe.db.commit()

        def payment(purchase, reference):
            data = {"purchase": purchase, "method": method,
                "amount": "10.00", "reference": reference,
                "reason": "Abono de compra concurrente"}
            reviewed = api.pms_supplier_payment_quote(property_name, data)
            return {**data, "acceptance": reviewed["acceptance"]}

        first_payment = race_command(SITE, sites_path, property_name,
            "pms_pay_supplier", payment(purchases[0], "RACE-PAY-ONE-" + suffix),
            "purchase-race-pay-same-" + suffix, same_key=True)
        payments = _verify_payments(property_name, bank, payable, equity, purchases,
            paid=1)
        if payments[0].name != first_payment["payment"]:
            raise AssertionError("The same-key supplier payment did not replay")
        frappe.db.commit()

        winner_payment = payment(purchases[1], "RACE-PAY-TWO-A-" + suffix)
        loser_payment = payment(purchases[1], "RACE-PAY-TWO-B-" + suffix)
        second_payment = race_command(SITE, sites_path, property_name,
            "pms_pay_supplier", winner_payment,
            "purchase-race-pay-distinct-" + suffix, same_key=False,
            second_payload=loser_payment,
            rejected_message="La compra ya está pagada")
        payments = _verify_payments(property_name, bank, payable, equity, purchases,
            paid=2)
        if (second_payment["payment"] not in {row.name for row in payments} or
                any(row.reference == loser_payment["reference"]
                    for row in payments)):
            raise AssertionError("The rejected payment left a supplier settlement")
        return {"site": SITE, "same_key": "same_result",
            "distinct_keys": "order_limit_and_overpayment_rejected",
            "received_quantity": "2", "inventory_value": "20.00",
            "payable_balance": "0.00", "bank_balance": "0.00",
            "purchases": 2, "stock_movements": 2, "supplier_payments": 2}
    finally:
        _remove(property_name, organization, requester)
