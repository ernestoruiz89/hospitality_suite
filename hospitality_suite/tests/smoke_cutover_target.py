"""Disposable ERPNext target fixture for the PMS cutover writer."""

from uuid import uuid4

import frappe


def run():
    if not frappe.local.site.startswith("hs-erp-smoke"):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_cutover_target_probe")
    try:
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc(dict(doctype="Warehouse Type", name="Transit")).insert(
                ignore_permissions=True)
        if not frappe.db.exists("Party Type", "Supplier"):
            frappe.get_doc(dict(doctype="Party Type", party_type="Supplier",
                account_type="Payable")).insert(ignore_permissions=True)
        suffix = uuid4().hex[:6].upper()
        company = frappe.get_doc(dict(doctype="Company",
            company_name="HS Cutover Test " + suffix, abbr="HC" + suffix,
            country="Nicaragua", default_currency="NIO",
            enable_perpetual_inventory=1)).insert(ignore_permissions=True)
        year = frappe.utils.today()[:4]
        frappe.get_doc(dict(doctype="Fiscal Year", year="HS Cutover FY " + suffix,
            year_start_date=year + "-01-01", year_end_date=year + "-12-31",
            companies=[dict(company=company.name)])).insert(ignore_permissions=True)
        temporary = frappe.db.get_value("Account", {"company": company.name,
            "account_type": "Temporary", "is_group": 0}, "name")
        receivable = frappe.db.get_value("Account", {"company": company.name,
            "account_type": "Receivable", "is_group": 0}, "name")
        payable = frappe.db.get_value("Account", {"company": company.name,
            "account_type": "Payable", "is_group": 0}, "name")
        center = frappe.db.get_value("Cost Center", {"company": company.name,
            "is_group": 0}, "name")
        customer = frappe.get_doc(dict(doctype="Customer",
            customer_name="HS Cutover Guest " + suffix,
            customer_type="Individual",
            customer_group=frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            territory=frappe.db.get_value("Territory", {"is_group": 0}, "name"))).insert(
                ignore_permissions=True)
        tool = frappe.get_single("Opening Invoice Creation Tool")
        tool.update(dict(company=company.name, cost_center=center,
            invoice_type="Sales", invoices=[dict(party=customer.name,
                outstanding_amount="100", posting_date=frappe.utils.today(),
                due_date=frappe.utils.today(), cost_center=center,
                temporary_opening_account=temporary)]))
        invoice_data = tool.get_invoices()[0]
        invoice_data["debit_to"] = receivable
        invoice = frappe.get_doc(invoice_data)
        invoice.flags.ignore_mandatory = True
        invoice.flags.dont_auto_add_taxes = True
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        supplier = frappe.get_doc(dict(doctype="Supplier",
            supplier_name="HS Cutover Supplier " + suffix,
            supplier_group=frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"))).insert(
                ignore_permissions=True)
        tool.update(dict(company=company.name, cost_center=center,
            invoice_type="Purchase", invoices=[dict(party=supplier.name,
                outstanding_amount="40", posting_date=frappe.utils.today(),
                due_date=frappe.utils.today(), cost_center=center,
                temporary_opening_account=temporary)]))
        purchase_data = tool.get_invoices()[0]
        purchase_data["credit_to"] = payable
        purchase = frappe.get_doc(purchase_data)
        purchase.flags.ignore_mandatory = True
        purchase.flags.dont_auto_add_taxes = True
        purchase.insert(ignore_permissions=True)
        purchase.submit()
        supplier_credit = frappe.get_doc(dict(doctype="Journal Entry",
            voucher_type="Opening Entry", is_opening="Yes",
            company=company.name, posting_date=frappe.utils.today(),
            user_remark="HS opening supplier credit",
            accounts=[dict(account=payable, party_type="Supplier",
                           party=supplier.name, debit_in_account_currency="10",
                           exchange_rate=1, cost_center=center),
                      dict(account=temporary, credit_in_account_currency="10",
                           exchange_rate=1, cost_center=center)]))
        supplier_credit.insert(ignore_permissions=True)
        supplier_credit.submit()
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc(dict(doctype="UOM", uom_name="Nos",
                must_be_whole_number=1, enabled=1)).insert(ignore_permissions=True)
        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc(dict(doctype="Item Group", item_group_name="All Item Groups",
                is_group=1)).insert(ignore_permissions=True)
        item_group = frappe.get_doc(dict(doctype="Item Group",
            item_group_name="HS Cutover Group " + suffix, is_group=0,
            parent_item_group="All Item Groups")).insert(ignore_permissions=True)
        item = frappe.get_doc(dict(doctype="Item", item_code="HS-CUTOVER-" + suffix,
            item_name="HS Cutover Stock " + suffix, is_stock_item=1,
            item_group=item_group.name,
            stock_uom="Nos", uom="Nos")).insert(ignore_permissions=True)
        warehouse = frappe.db.get_value("Warehouse", {"company": company.name,
            "is_group": 0, "warehouse_name": "Stores"}, "name")
        stock = frappe.get_doc(dict(doctype="Stock Reconciliation",
            purpose="Opening Stock", company=company.name,
            posting_date=frappe.utils.today(), posting_time="00:00:00",
            cost_center=center, expense_account=temporary,
            items=[dict(item_code=item.name, warehouse=warehouse,
                        qty=3, valuation_rate=10)]))
        stock.insert(ignore_permissions=True)
        stock.submit()
        return {"company": company.name,
                "accounts": frappe.db.count("Account", {"company": company.name}),
                "cost_centers": frappe.db.count("Cost Center", {"company": company.name}),
                "warehouses": frappe.db.count("Warehouse", {"company": company.name}),
                "invoice": invoice.name, "outstanding": str(invoice.outstanding_amount),
                "gl_entries": frappe.db.count("GL Entry", {"voucher_type": "Sales Invoice",
                    "voucher_no": invoice.name, "is_cancelled": 0}),
                "purchase": purchase.name, "purchase_outstanding": str(purchase.outstanding_amount),
                "purchase_gl_entries": frappe.db.count("GL Entry", {
                    "voucher_type": "Purchase Invoice", "voucher_no": purchase.name,
                    "is_cancelled": 0}),
                "credit_journal": supplier_credit.name,
                "credit_gl_entries": frappe.db.count("GL Entry", {
                    "voucher_type": "Journal Entry", "voucher_no": supplier_credit.name,
                    "is_cancelled": 0}),
                "stock_reconciliation": stock.name,
                "stock_ledger_entries": frappe.db.count("Stock Ledger Entry", {
                    "voucher_type": "Stock Reconciliation", "voucher_no": stock.name,
                    "is_cancelled": 0})}
    finally:
        frappe.db.rollback(save_point="hs_cutover_target_probe")
