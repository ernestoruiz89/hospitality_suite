"""Rollback-only integration probe for the internal ERPNext opening writer."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import frappe

from hospitality_suite.pms_cutover_writer import post_property


def run():
    if not frappe.local.site.startswith("hs-erp-smoke"):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_cutover_writer_probe")
    try:
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
                ignore_permissions=True)
        if not frappe.db.exists("Party Type", "Supplier"):
            frappe.get_doc({"doctype": "Party Type", "party_type": "Supplier",
                            "account_type": "Payable"}).insert(ignore_permissions=True)
        if not frappe.db.exists("Party Type", "Customer"):
            frappe.get_doc({"doctype": "Party Type", "party_type": "Customer",
                            "account_type": "Receivable"}).insert(ignore_permissions=True)
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
                            "must_be_whole_number": 1, "enabled": 1}).insert(
                                ignore_permissions=True)
        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc({"doctype": "Item Group",
                            "item_group_name": "All Item Groups", "is_group": 1}).insert(
                                ignore_permissions=True)
        suffix = uuid4().hex[:6].upper()
        company = frappe.get_doc({"doctype": "Company",
            "company_name": "HS Writer Test " + suffix, "abbr": "HW" + suffix,
            "country": "Nicaragua", "default_currency": "NIO",
            "enable_perpetual_inventory": 1}).insert(ignore_permissions=True)
        from frappe.model.naming import make_autoname
        property_doc = frappe.get_doc({"doctype": "HS Property",
            "name": make_autoname("ESTAB-.#####"),
            "property_name": "HS Writer Property " + suffix,
            "company": company.name, "currency": "NIO", "mode": "Hotel",
            "time_zone": "America/Managua", "close_time": "06:00:00",
            "business_date": frappe.utils.today()})
        property_doc.db_insert()
        year = frappe.utils.today()[:4]
        frappe.get_doc({"doctype": "Fiscal Year", "year": "HS Writer FY " + suffix,
            "year_start_date": year + "-01-01", "year_end_date": year + "-12-31",
            "companies": [{"company": company.name}]}).insert(ignore_permissions=True)

        def account(**filters):
            return frappe.db.get_value("Account", {"company": company.name,
                "is_group": 0, **filters}, "name")

        temporary = account(account_type="Temporary")
        receivable = account(account_type="Receivable")
        payable = account(account_type="Payable")
        cash = account(account_type="Cash")
        equity = account(root_type="Equity")
        liability_parent = frappe.db.get_value("Account", {
            "company": company.name, "account_name": "Current Liabilities",
            "is_group": 1}, "name")
        guarantee_liability = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Guarantee " + suffix,
            "parent_account": liability_parent, "company": company.name,
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        bank_parent = frappe.db.get_value("Account", {"company": company.name,
            "account_name": "Bank Accounts", "is_group": 1}, "name")
        foreign_bank = frappe.get_doc({"doctype": "Account",
            "account_name": "HS USD Bank " + suffix, "parent_account": bank_parent,
            "company": company.name, "account_type": "Bank",
            "account_currency": "USD", "is_group": 0}).insert(ignore_permissions=True)
        center = frappe.db.get_value("Cost Center", {"company": company.name,
            "is_group": 0}, "name")
        warehouse = frappe.db.get_value("Warehouse", {"company": company.name,
            "is_group": 0, "warehouse_name": "Stores"}, "name")
        from erpnext.stock import get_warehouse_account
        inventory = get_warehouse_account(frappe.get_doc("Warehouse", warehouse),
                                          raise_error=True)
        customer = frappe.get_doc({"doctype": "Customer",
            "customer_name": "HS Writer Guest " + suffix,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")}).insert(
                ignore_permissions=True)
        supplier = frappe.get_doc({"doctype": "Supplier",
            "supplier_name": "HS Writer Supplier " + suffix,
            "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert(
                ignore_permissions=True)
        from hospitality_suite.service import operation
        with operation(property_doc):
            frappe.get_doc({"doctype": "HS Supplier",
                "company": company.name, "property": property_doc.name,
                "supplier": supplier.name, "active": 1}).insert(
                    ignore_permissions=True)
        group = frappe.get_doc({"doctype": "Item Group",
            "item_group_name": "HS Writer Group " + suffix, "is_group": 0,
            "parent_item_group": "All Item Groups"}).insert(ignore_permissions=True)
        item = frappe.get_doc({"doctype": "Item", "item_code": "HS-WRITER-" + suffix,
            "item_name": "HS Writer Stock " + suffix, "is_stock_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        zero_item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-WRITER-ZERO-" + suffix,
            "item_name": "HS Writer Zero Stock " + suffix, "is_stock_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        date = frappe.utils.today()
        guarantee_source = frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-GUAR-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Guarantee",
            "status": "Posted", "amount": "30", "base_amount": "30",
            "currency": "NIO", "exchange_rate": 1,
            "pms_journal": "HS-OLD-GUAR-" + suffix})
        guarantee_source.db_insert()
        frappe.get_doc({"doctype": "HS PMS Allocation",
            "name": "HS-OLD-APL-" + suffix,
            "company": company.name, "property": property_doc.name,
            "payment": guarantee_source.name, "kind": "Guarantee Applied",
            "business_date": date, "currency": "NIO", "amount": "10"}).db_insert()
        advance_source = frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-ADV-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Advance",
            "status": "Posted", "amount": "20", "base_amount": "20",
            "currency": "NIO", "exchange_rate": 1,
            "pms_journal": "HS-OLD-ADV-" + suffix})
        advance_source.db_insert()
        frappe.get_doc({"doctype": "HS PMS Allocation",
            "name": "HS-OLD-ADV-APL-" + suffix,
            "company": company.name, "property": property_doc.name,
            "payment": advance_source.name, "kind": "Advance Applied",
            "business_date": date, "currency": "NIO", "amount": "8"}).db_insert()
        common = {"company": company.name, "cost_center": center,
                  "property": property_doc.name,
                  "posting_date": date, "temporary_opening_account": temporary,
                  "currency": "NIO"}
        prop = {"property": property_doc.name, "company": company.name,
            "cost_center": center, "posting_date": date,
            "opening_receivables": [{**common, "source": "HS-AR-" + suffix,
                "reference": "ROOM-1", "customer": customer.name,
                "debit_to": receivable, "due_date": date, "outstanding": "100"}],
            "opening_payables": [{**common, "source": "HS-AP-" + suffix,
                "reference": "PUR-1", "supplier": supplier.name,
                "payable_account": payable, "outstanding": "40"}],
            "opening_supplier_credits": [{**common, "source": "HS-CR-" + suffix,
                "supplier": supplier.name, "payable_account": payable,
                "outstanding": "10"}],
            "opening_guarantees": [{**common,
                "source": guarantee_source.name, "customer": customer.name,
                "liability_account": guarantee_liability.name,
                "original_amount": "30", "original_base": "30",
                "remaining_base": "20", "used_base": "10",
                "payment_currency": "NIO", "exchange_rate": "1"}],
            "opening_advances": [{**common,
                "source": advance_source.name, "customer": customer.name,
                "receivable_account": receivable,
                "liability_account": guarantee_liability.name,
                "original_amount": "20", "original_base": "20",
                "remaining_base": "12", "used_base": "8",
                "payment_currency": "NIO", "exchange_rate": "1"}],
            "opening_stock": [
                {**common, "source_product": "HS-STOCK-" + suffix,
                 "source_warehouse": "HS-WH-" + suffix,
                 "item_code": item.name, "warehouse": warehouse,
                 "inventory_account": inventory, "quantity": "3", "value": "30"},
                {**common, "source_product": "HS-STOCK-ZERO-" + suffix,
                 "source_warehouse": "HS-WH-" + suffix,
                 "item_code": zero_item.name, "warehouse": warehouse,
                 "inventory_account": inventory, "quantity": "2", "value": "0"}],
            "opening_journal": [
                {"account": temporary, "cost_center": center,
                 "debit": "58", "credit": "0",
                 "debit_in_account_currency": "58", "credit_in_account_currency": "0"},
                {"account": guarantee_liability.name, "cost_center": center,
                 "debit": "10", "credit": "0",
                 "debit_in_account_currency": "10", "credit_in_account_currency": "0"},
                {"account": cash, "cost_center": center,
                 "debit": "12", "credit": "0",
                 "debit_in_account_currency": "12", "credit_in_account_currency": "0"},
                {"account": foreign_bank.name, "cost_center": center,
                 "debit": "25", "credit": "0",
                 "debit_in_account_currency": "1", "credit_in_account_currency": "0",
                 "exchange_rate": "25"},
                {"account": equity, "cost_center": center,
                 "debit": "0", "credit": "105",
                 "debit_in_account_currency": "0", "credit_in_account_currency": "105"}],
        }
        invalid = deepcopy(prop)
        invalid["opening_journal"][4]["credit_in_account_currency"] = "104"
        invalid["opening_journal"][4]["credit"] = "104"
        try:
            post_property(invalid)
        except Exception:
            if (frappe.db.count("GL Entry", {"company": company.name}) or
                    frappe.db.count("Sales Invoice", {"company": company.name}) or
                    frappe.db.count("Stock Ledger Entry", {"warehouse": warehouse})):
                frappe.throw("Failed cutover left target postings behind")
        else:
            frappe.throw("Unbalanced cutover unexpectedly posted")
        result = post_property(prop)
        if result["reconciliation"]["accounts"].get(temporary) != "0":
            frappe.throw("Temporary account did not clear")
        if (result["reconciliation"]["accounts"].get(guarantee_liability.name) != "-20" or
                frappe.db.get_value("HS Payment", guarantee_source.name,
                    "journal_entry") != result["guarantees"][0]):
            frappe.throw("Guarantee opening did not preserve the remaining liability")
        if (result["reconciliation"]["accounts"].get(temporary) != "0" or
                result["reconciliation"]["accounts"].get(receivable) != "88" or
                frappe.db.get_value("HS Payment", advance_source.name,
                    "payment_entry") != result["advances"][0]):
            frappe.throw("Advance opening did not preserve the customer credit")
        frappe.db.set_value("HS Property", property_doc.name,
            {"receivable_account": receivable, "cost_center": center},
            update_modified=False)
        property_doc.reload()
        service_item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-WRITER-SERVICE-" + suffix,
            "item_name": "HS Writer Service " + suffix,
            "is_stock_item": 0, "item_group": group.name,
            "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        income = account(root_type="Income")
        price_list = frappe.get_doc({"doctype": "Price List",
            "price_list_name": "HS Writer Selling " + suffix,
            "enabled": 1, "selling": 1, "currency": "NIO"}).insert(
                ignore_permissions=True)
        frappe.db.savepoint("hs_writer_foreign_credit_source_probe")
        try:
            from hospitality_suite.erp_to_pms_preflight import _open_invoices
            from hospitality_suite.pms_cutover_writer import _migration_posting

            ar_parent = frappe.db.get_value("Account", {
                "company": company.name, "account_name": "Accounts Receivable",
                "is_group": 1}, "name") or frappe.db.get_value("Account", {
                "company": company.name, "account_name": "Current Assets",
                "is_group": 1}, "name")
            foreign_ar = frappe.get_doc({"doctype": "Account",
                "account_name": "HS Writer USD AR " + suffix,
                "parent_account": ar_parent, "company": company.name,
                "account_type": "Receivable", "account_currency": "USD",
                "is_group": 0}).insert(ignore_permissions=True)
            usd_prices = frappe.get_doc({"doctype": "Price List",
                "price_list_name": "HS Writer USD " + suffix,
                "enabled": 1, "selling": 1, "currency": "USD"}).insert(
                    ignore_permissions=True)
            foreign_customer = frappe.get_doc({"doctype": "Customer",
                "customer_name": "HS Writer USD Guest " + suffix,
                "customer_type": "Individual",
                "customer_group": frappe.db.get_value("Customer Group", {
                    "is_group": 0}, "name"),
                "territory": frappe.db.get_value("Territory", {
                    "is_group": 0}, "name")}).insert(ignore_permissions=True)
            with _migration_posting():
                foreign_credit = frappe.get_doc({"doctype": "Sales Invoice",
                    "company": company.name, "customer": foreign_customer.name,
                    "hs_property": property_doc.name,
                    "posting_date": date, "due_date": date,
                    "is_return": 1, "currency": "USD", "conversion_rate": 36,
                    "debit_to": foreign_ar.name,
                    "selling_price_list": usd_prices.name,
                    "price_list_currency": "USD", "plc_conversion_rate": 1,
                    "items": [{"item_code": service_item.name, "qty": -1,
                               "rate": 50, "income_account": income,
                               "cost_center": center}]})
                foreign_credit.set_missing_values()
                foreign_credit.insert(ignore_permissions=True)
                foreign_credit.submit()
            blockers = []
            rows = _open_invoices(property_doc, "Sales Invoice", "customer",
                                  "debit_to", blockers)
            opened = next((row for row in rows
                           if row["name"] == foreign_credit.name), None)
            if (blockers or not opened or not opened["is_return"] or
                    opened["account_currency"] != "USD" or
                    Decimal(opened["outstanding_amount"]) != -50 or
                    Decimal(opened["base_outstanding_amount"]) != -1800):
                frappe.throw("ERPNext did not expose the foreign credit principal and base")
            ap_parent = frappe.db.get_value("Account", {
                "company": company.name, "account_name": "Accounts Payable",
                "is_group": 1}, "name") or liability_parent
            foreign_ap = frappe.get_doc({"doctype": "Account",
                "account_name": "HS Writer USD AP " + suffix,
                "parent_account": ap_parent, "company": company.name,
                "account_type": "Payable", "account_currency": "USD",
                "is_group": 0}).insert(ignore_permissions=True)
            foreign_supplier = frappe.get_doc({"doctype": "Supplier",
                "supplier_name": "HS Writer USD Supplier " + suffix,
                "supplier_group": frappe.db.get_value("Supplier Group", {
                    "is_group": 0}, "name")}).insert(ignore_permissions=True)
            with operation(property_doc):
                frappe.get_doc({"doctype": "HS Supplier",
                    "company": company.name, "property": property_doc.name,
                    "supplier": foreign_supplier.name, "active": 1}).insert(
                        ignore_permissions=True)
            expense = account(root_type="Expense")
            with _migration_posting():
                vendor_credit = frappe.get_doc({"doctype": "Purchase Invoice",
                    "company": company.name, "supplier": foreign_supplier.name,
                    "hs_property": property_doc.name,
                    "posting_date": date, "due_date": date,
                    "is_return": 1, "currency": "USD", "conversion_rate": 36,
                    "credit_to": foreign_ap.name,
                    "items": [{"item_code": service_item.name, "qty": -1,
                               "rate": 50, "expense_account": expense,
                               "cost_center": center}]})
                vendor_credit.set_missing_values()
                vendor_credit.insert(ignore_permissions=True)
                vendor_credit.submit()
            vendor_blockers = []
            vendor_rows = _open_invoices(property_doc, "Purchase Invoice",
                                         "supplier", "credit_to", vendor_blockers)
            opened_vendor = next((row for row in vendor_rows
                                  if row["name"] == vendor_credit.name), None)
            if (vendor_blockers or not opened_vendor or
                    not opened_vendor["is_return"] or
                    opened_vendor["account_currency"] != "USD" or
                    Decimal(opened_vendor["outstanding_amount"]) != -50 or
                    Decimal(opened_vendor["base_outstanding_amount"]) != -1800):
                frappe.throw("ERPNext did not expose the foreign vendor credit")
        finally:
            frappe.db.rollback(save_point="hs_writer_foreign_credit_source_probe")
        frappe.db.savepoint("hs_writer_no_folio_credit_probe")
        try:
            opening_name = result["receivables"][0]
            opening_doc = frappe.get_doc("Sales Invoice", opening_name)
            if opening_doc.hs_folio or opening_doc.is_opening != "Yes":
                frappe.throw("The writer did not create a standalone opening receivable")
            frappe.get_doc({"doctype": "HS Cutover Run",
                "name": frappe.generate_hash(length=12),
                "migration_reference": "writer-no-folio-" + suffix,
                "source_sha256": "0" * 64, "mapping_sha256": "0" * 64,
                "plan_sha256": "0" * 64, "link_sha256": "0" * 64,
                "performed_by": "Administrator",
                "performed_at": frappe.utils.now_datetime(),
                "result_json": frappe.as_json({"properties": [{
                    "property": property_doc.name,
                    "receivables": [opening_name]}]})}).db_insert()
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
            from hospitality_suite.accounting import post_standard
            partial_payment = get_payment_entry("Sales Invoice", opening_name,
                                                bank_account=cash)
            partial_payment.paid_amount = 40
            partial_payment.received_amount = 40
            for reference in partial_payment.references:
                reference.allocated_amount = (40 if reference.reference_name ==
                                              opening_name else 0)
            post_standard(partial_payment, property_doc)
            if Decimal(str(frappe.db.get_value("Sales Invoice", opening_name,
                                               "outstanding_amount"))) != 60:
                frappe.throw("The standalone opening receivable was not partly paid")
            from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
            no_folio_credit = make_sales_return(opening_name)
            no_folio_credit.update(dict(hs_property=property_doc.name,
                selling_price_list=price_list.name,
                price_list_currency="NIO", plc_conversion_rate=1,
                update_outstanding_for_self=0,
                remarks="Corrección de cartera sin folio"))
            for line in no_folio_credit.items:
                line.hs_charge = None
                line.hs_charge_sources = None
            post_standard(no_folio_credit, property_doc)
            if (Decimal(str(frappe.db.get_value("Sales Invoice", opening_name,
                    "outstanding_amount"))) != 0 or
                    Decimal(str(frappe.db.get_value("Sales Invoice",
                        no_folio_credit.name,
                        "outstanding_amount"))) != Decimal("-40")):
                frappe.throw("The standalone opening credit did not reconcile")
        finally:
            frappe.db.rollback(save_point="hs_writer_no_folio_credit_probe")
        from hospitality_suite.pms_cutover_writer import _migration_posting
        with _migration_posting():
            invoice = frappe.get_doc({"doctype": "Sales Invoice",
                "company": company.name, "customer": customer.name,
                "posting_date": date, "due_date": date,
                "currency": "NIO", "debit_to": receivable,
                "selling_price_list": price_list.name,
                "price_list_currency": "NIO", "plc_conversion_rate": 1,
                "hs_property": property_doc.name,
                "items": [{"item_code": service_item.name, "qty": 1,
                           "rate": 7, "income_account": income,
                           "cost_center": center}]})
            invoice.set_missing_values()
            invoice.insert(ignore_permissions=True)
            invoice.submit()
        from hospitality_suite.api import execute, erp_customer_credits_snapshot
        allocation_data = {"advance": advance_source.name,
                           "invoice": invoice.name, "amount": "5"}
        allocation_key = "writer-advance-" + suffix
        applied = execute(property_doc.name, "apply_customer_advance",
                          allocation_key, allocation_data)
        if (applied["amount"] != "5.00" or
                applied["remaining_advance"] != "7.00" or
                applied["invoice_outstanding"] != "2.00" or
                execute(property_doc.name, "apply_customer_advance",
                        allocation_key, allocation_data) != applied):
            frappe.throw("Migrated advance allocation or retry changed balances")
        snapshot = erp_customer_credits_snapshot(property_doc.name)
        if (not any(row["name"] == advance_source.name and
                    Decimal(row["available"]) == 7 for row in snapshot["advances"]) or
                not any(row["name"] == invoice.name and
                    Decimal(row["outstanding"]) == 2 for row in snapshot["invoices"])):
            frappe.throw("ERP customer credits view lost the reconciled balances")
        from hospitality_suite.refunds import original_funds, invoice_available, balance, plan as refund_plan
        source_after = frappe.get_doc("HS Payment", advance_source.name)
        funds = original_funds(property_doc, source_after)
        if (funds.unallocated != 7 or
                invoice_available(balance(property_doc, source_after), invoice.name) != 5):
            frappe.throw("Reconciled advance lost its invoice refund provenance")
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        with _migration_posting():
            credit_note = make_sales_return(invoice.name)
            credit_note.hs_property = property_doc.name
            credit_note.debit_to = receivable
            credit_note.items[0].qty = -1
            credit_note.items[0].rate = 5
            credit_note.insert(ignore_permissions=True)
            credit_note.submit()
        refund = refund_plan(property_doc, source_after, Decimal("5"),
                             frappe._dict(currency="NIO"), credit_note.name)
        if (refund.party_amount != 5 or
                refund.proof["mode"] != "Applied Advance" or
                refund.proof["invoice"] != invoice.name):
            frappe.throw("Applied migrated advance could not be refunded against its credit note")
        try:
            execute(property_doc.name, "apply_customer_advance",
                    "writer-overallocate-" + suffix,
                    {**allocation_data, "amount": "3"})
        except frappe.ValidationError:
            pass
        else:
            frappe.throw("Advance allocation exceeded invoice outstanding")
        from hospitality_suite.accounting import guarantee_balance, guarantee_book_amount
        available = guarantee_balance(property_doc,
            frappe.get_doc("HS Payment", guarantee_source.name))
        if (available.nominal != 20 or available.book != 20 or
                guarantee_book_amount(property_doc, guarantee_source, 5,
                    available) != 5):
            frappe.throw("Historical guarantee use was not carried into ERPNext")
        from hospitality_suite.pms_cutover_writer import _journal, _migration_posting

        def use_guarantee(kind, amount):
            with _migration_posting():
                journal = _journal(company.name, date, [
                    {"account": guarantee_liability.name, "cost_center": center,
                     "debit_in_account_currency": str(amount), "exchange_rate": 1},
                    {"account": temporary, "cost_center": center,
                     "credit_in_account_currency": str(amount), "exchange_rate": 1},
                ], "Guarantee use fixture", property_doc.name)
            child = frappe.get_doc({"doctype": "HS Payment",
                "name": "HS-GUAR-USE-" + kind.replace(" ", "") + suffix,
                "company": company.name, "property": property_doc.name,
                "customer": customer.name, "kind": kind,
                "source_payment": guarantee_source.name,
                "status": "Posted", "amount": str(amount),
                "base_amount": str(amount), "currency": "NIO",
                "exchange_rate": 1, "journal_entry": journal.name})
            child.db_insert()

        use_guarantee("Guarantee Applied", 5)
        available = guarantee_balance(property_doc,
            frappe.get_doc("HS Payment", guarantee_source.name))
        if (available.nominal != 15 or available.book != 15 or
                guarantee_book_amount(property_doc, guarantee_source, 15,
                    available) != 15):
            frappe.throw("Post-cutover guarantee application changed the wrong balance")
        use_guarantee("Guarantee Refund", 15)
        available = guarantee_balance(property_doc,
            frappe.get_doc("HS Payment", guarantee_source.name))
        if available.nominal != 0 or available.book != 0:
            frappe.throw("Post-cutover guarantee refund left a residual balance")
        settled = frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-GUAR-SETTLED-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Guarantee",
            "status": "Posted", "amount": "10", "base_amount": "10",
            "currency": "NIO", "exchange_rate": 1,
            "pms_journal": "HS-OLD-SETTLED-" + suffix})
        settled.db_insert()
        frappe.get_doc({"doctype": "HS PMS Allocation",
            "name": "HS-OLD-SETTLED-APL-" + suffix,
            "company": company.name, "property": property_doc.name,
            "payment": settled.name, "kind": "Guarantee Applied",
            "business_date": date, "currency": "NIO", "amount": "10"}).db_insert()
        closed = guarantee_balance(property_doc, settled)
        if closed.nominal != 0 or closed.book != 0:
            frappe.throw("Fully consumed PMS guarantee was not preserved")
        foreign_source = frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-GUAR-USD-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Guarantee",
            "status": "Posted", "amount": "2", "base_amount": "73",
            "currency": "USD", "exchange_rate": "36.5",
            "pms_journal": "HS-OLD-USD-" + suffix})
        foreign_source.db_insert()
        frappe.get_doc({"doctype": "HS PMS Allocation",
            "name": "HS-OLD-USD-APL-" + suffix,
            "company": company.name, "property": property_doc.name,
            "payment": foreign_source.name, "kind": "Guarantee Applied",
            "business_date": date, "currency": "NIO", "amount": "20"}).db_insert()
        with _migration_posting():
            foreign_opening = _journal(company.name, date, [
                {"account": temporary, "cost_center": center,
                 "debit_in_account_currency": "73", "exchange_rate": 1},
                {"account": guarantee_liability.name, "cost_center": center,
                 "credit_in_account_currency": "73", "exchange_rate": 1},
            ], "Foreign guarantee fixture", property_doc.name)
        frappe.db.set_value("HS Payment", foreign_source.name,
            "journal_entry", foreign_opening.name, update_modified=False)
        foreign_available = guarantee_balance(property_doc,
            frappe.get_doc("HS Payment", foreign_source.name))
        if (foreign_available.nominal != Decimal("1.45") or
                foreign_available.book != Decimal("53") or
                guarantee_book_amount(property_doc, foreign_source,
                    Decimal("0.50"), foreign_available) != Decimal("18.25")):
            frappe.throw("Foreign guarantee did not preserve nominal and book value: " +
                repr((foreign_available.nominal, foreign_available.book,
                    guarantee_book_amount(property_doc, foreign_source, Decimal("0.50"),
                        foreign_available))))
        with _migration_posting():
            foreign_partial = _journal(company.name, date, [
                {"account": guarantee_liability.name, "cost_center": center,
                 "debit_in_account_currency": "18.25", "exchange_rate": 1},
                {"account": temporary, "cost_center": center,
                 "credit_in_account_currency": "18.25", "exchange_rate": 1},
            ], "Foreign guarantee partial fixture", property_doc.name)
        frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-GUAR-USD-USE-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Guarantee Applied",
            "source_payment": foreign_source.name, "status": "Posted",
            "amount": "0.50", "base_amount": "18.25",
            "currency": "USD", "exchange_rate": "36.5",
            "journal_entry": foreign_partial.name}).db_insert()
        foreign_available = guarantee_balance(property_doc,
            frappe.get_doc("HS Payment", foreign_source.name))
        if (foreign_available.nominal != Decimal("0.95") or
                foreign_available.book != Decimal("34.75") or
                guarantee_book_amount(property_doc, foreign_source,
                    Decimal("0.95"), foreign_available) != Decimal("34.75")):
            frappe.throw("Final foreign guarantee use did not absorb book value")
        foreign_advance = frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-ADV-USD-" + suffix,
            "company": company.name, "property": property_doc.name,
            "customer": customer.name, "kind": "Advance",
            "status": "Posted", "amount": "2", "base_amount": "73",
            "currency": "USD", "exchange_rate": "36.5",
            "pms_journal": "HS-OLD-ADV-USD-" + suffix})
        foreign_advance.db_insert()
        frappe.get_doc({"doctype": "HS PMS Allocation",
            "name": "HS-OLD-ADV-USD-APL-" + suffix,
            "company": company.name, "property": property_doc.name,
            "payment": foreign_advance.name, "kind": "Advance Applied",
            "business_date": date, "currency": "NIO", "amount": "20"}).db_insert()
        frappe.get_doc({"doctype": "HS Payment",
            "name": "HS-OLD-ADV-USD-REF-" + suffix,
            "company": company.name, "property": property_doc.name,
            "kind": "Refund", "status": "Posted",
            "source_payment": foreign_advance.name,
            "amount": "0.08", "base_amount": "3", "currency": "USD",
            "exchange_rate": "36.5",
            "pms_journal": "HS-OLD-ADV-USD-REF-J-" + suffix}).db_insert()
        from hospitality_suite.pms_cutover_writer import _advance_opening
        with _migration_posting():
            _advance_opening({**common, "source": foreign_advance.name,
                "customer": customer.name,
                "receivable_account": receivable,
                "original_amount": "2", "original_base": "73",
                "remaining_base": "50", "used_base": "23",
                "payment_currency": "USD", "exchange_rate": "36.5"})
        from hospitality_suite.refunds import balance as refund_balance, plan as refund_plan
        foreign_advance = frappe.get_doc("HS Payment", foreign_advance.name)
        foreign_credit = refund_balance(property_doc, foreign_advance)
        partial_refund = refund_plan(property_doc, foreign_advance,
            Decimal("0.50"), frappe._dict(currency="USD"))
        final_refund = refund_plan(property_doc, foreign_advance,
            Decimal("1.37"), frappe._dict(currency="USD"))
        if (foreign_credit.remaining != Decimal("1.37") or
                foreign_credit.remaining_party != Decimal("50") or
                partial_refund.party_amount != Decimal("18.25") or
                final_refund.party_amount != Decimal("50")):
            frappe.throw("Foreign advance refund did not retain its opening value")
        result["supplier_credit_payment_ledger"] = frappe.get_all(
            "Payment Ledger Entry", filters={"voucher_type": "Journal Entry",
                "voucher_no": result["supplier_credits"][0]},
            fields=["party_type", "party", "account", "amount",
                    "amount_in_account_currency"], limit_page_length=0)
        return result
    finally:
        frappe.db.rollback(save_point="hs_cutover_writer_probe")
