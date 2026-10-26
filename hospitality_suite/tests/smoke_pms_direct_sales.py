"""Rollback-only PMS counter sale smoke test on a disposable Frappe site."""

from decimal import Decimal
from uuid import uuid4

import frappe

from hospitality_suite import api, setup, standalone_closing, standalone_inventory
from hospitality_suite.service import operation


def run():
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente un sitio PMS descartable")
    frappe.set_user("Administrator")
    suffix = uuid4().hex[:8]
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Venta directa ensayo " + suffix,
            "base_currency": "NIO", "tax_regime": "General", "active": 1}).insert()
        name = setup.create_property({"property_name": "Mostrador ensayo " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "qa-direct-property-" + suffix)["property"]
        prop = frappe.get_doc("HS Property", name)
        api.execute(name, "pms_currencies", "qa-direct-currencies-" + suffix,
            {"currencies": ["NIO", "USD"]})
        api.execute(name, "pms_exchange_rate", "qa-direct-rate-" + suffix,
            {"from_currency": "USD", "rate": "36.5", "source": "Ensayo"})

        def make_account(code, label, root, kind="General", currency="NIO"):
            return api.execute(name, "pms_account", "qa-direct-account-" + code + suffix,
                {"account_code": code + suffix, "account_name": label,
                 "root_type": root, "account_type": kind,
                 "account_currency": currency})["account"]

        ar = make_account("AR", "Cartera", "Asset", "Receivable")
        cash = make_account("CASH", "Caja", "Asset", "Cash")
        bank = make_account("USD", "Banco USD", "Asset", "Bank", "USD")
        income = make_account("INC", "Ingresos", "Income")
        tax_account = make_account("TAX", "Impuesto", "Liability")
        inventory = make_account("STOCK", "Inventario", "Asset", "Stock")
        expense = make_account("COGS", "Costo", "Expense")
        equity = make_account("EQUITY", "Origen", "Equity")
        prop.reload()
        api.save_setup(name, "property", {"receivable_account": ar},
            "qa-direct-settings-" + suffix, str(prop.modified))
        prop.reload()
        profile = api.execute(name, "pms_tax_profile", "qa-direct-tax-" + suffix,
            {"label": "IVA ensayo", "treatment": "Taxable", "rate": "15",
             "liability_account": tax_account})["profile"]
        series = api.execute(name, "pms_fiscal_series", "qa-direct-series-" + suffix,
            {"series_code": "QA-DIR-" + suffix + "-", "document_type": "Invoice",
             "start_number": 1, "end_number": 20, "padding": 2})["series"]
        credit_series = api.execute(name, "pms_fiscal_series",
            "qa-direct-credit-series-" + suffix,
            {"series_code": "QA-CR-" + suffix + "-", "document_type": "Credit Note",
             "start_number": 1, "end_number": 20, "padding": 2})["series"]
        customer = api.execute(name, "pms_customer", "qa-direct-customer-" + suffix,
            {"party_name": "Cliente mostrador"})["party"]
        cash_method = api.execute(name, "pms_payment_method",
            "qa-direct-cash-method-" + suffix,
            {"label": "Efectivo", "account": cash})["method"]
        bank_method = api.execute(name, "pms_payment_method",
            "qa-direct-bank-method-" + suffix,
            {"label": "Transferencia USD", "account": bank})["method"]
        shift = api.execute(name, "pms_open_shift", "qa-direct-shift-" + suffix,
            {"opening_by_currency": {"NIO": "0.00"}})["shift"]
        service_item = api.save_setup(name, "product",
            {"product_code": "SVC" + suffix, "product_name": "Servicio de mostrador",
             "product_type": "Service", "income_account": income,
             "tax_profile": profile, "sales_rate": "100", "active": 1},
            "qa-direct-service-" + suffix)["name"]
        stock_item = api.save_setup(name, "product",
            {"product_code": "WATER" + suffix, "product_name": "Agua de mostrador",
             "product_type": "Stock", "income_account": income,
             "tax_profile": profile, "sales_rate": "100",
             "inventory_account": inventory, "expense_account": expense,
             "active": 1}, "qa-direct-stock-" + suffix)["name"]
        warehouse = api.execute(name, "pms_warehouse", "qa-direct-warehouse-" + suffix,
            {"warehouse_code": "WH" + suffix,
             "warehouse_name": "Almacén mostrador"})["warehouse"]
        api.execute(name, "pms_opening_stock", "qa-direct-opening-" + suffix,
            {"product": stock_item, "warehouse": warehouse, "quantity": "3",
             "value": "30", "equity_account": equity,
             "reference": "QA-DIRECT-STOCK-" + suffix})

        service_data = {"customer": customer, "item": service_item,
            "quantity": "1", "method": cash_method, "shift": shift,
            "series": series, "reference": "", "tendered": "120",
            "notes": "Venta al mostrador"}
        service_quote = api.preview(name, service_data, "pms_direct_sale")
        assert (service_quote["total"] == "115.00" and
                service_quote["payment_amount"] == "115.00" and
                service_quote["change"] == "5.00")
        service_sale = api.execute(name, "pms_direct_sale",
            "qa-direct-sell-service-" + suffix,
            {**service_data, "acceptance": service_quote["acceptance"]})
        assert api.execute(name, "pms_direct_sale",
            "qa-direct-sell-service-" + suffix,
            {**service_data, "acceptance": service_quote["acceptance"]}) == service_sale
        assert (frappe.db.get_value("HS Service Request", service_sale["service"],
                    "status") == "Delivered" and
                frappe.db.get_value("HS PMS Fiscal Document", service_sale["invoice"],
                    "document_type") == "Invoice" and
                frappe.db.count("HS PMS Allocation", {
                    "receivable": service_sale["receivable"], "kind": "Direct"}) == 1)

        stock_data = {"customer": customer, "item": stock_item,
            "warehouse": warehouse, "quantity": "1", "method": bank_method,
            "series": series, "reference": "USD-TRANSFER-" + suffix,
            "notes": "Agua al mostrador"}
        stock_quote = api.preview(name, stock_data, "pms_direct_sale")
        assert (stock_quote["total"] == "115.00" and
                stock_quote["payment_currency"] == "USD" and
                Decimal(stock_quote["payment_amount"]) > 0)
        stock_sale = api.execute(name, "pms_direct_sale",
            "qa-direct-sell-stock-" + suffix,
            {**stock_data, "acceptance": stock_quote["acceptance"]})
        assert (standalone_inventory.current_balance(prop, stock_item, warehouse) ==
                    (Decimal("2"), Decimal("20")) and
                frappe.db.get_value("HS PMS Receivable", stock_sale["receivable"],
                    "source_service") == stock_sale["service"] and
                frappe.db.get_value("HS Payment", stock_sale["payment"],
                    "base_amount") == 115 and
                frappe.db.count("HS PMS Fiscal Document", {
                    "property": name, "document_type": "Invoice"}) == 2)
        assert (api.pms_direct_sale_options(name)["currency"] == "NIO" and
                any(row.name == customer for row in
                    api.pms_direct_sale_customers(name, "Cliente")["rows"]) and
                any(row.name == stock_item for row in
                    api.pms_direct_sale_products(name, "Agua")["rows"]))
        available = api.pms_direct_sale_history(name, returnable=1)["rows"]
        assert ({row["name"] for row in available} ==
                {service_sale["service"], stock_sale["service"]} and
                all(row["payment"] for row in available))
        altered = frappe.get_doc("HS Service Request", service_sale["service"])
        altered.amount = "116.00"
        try:
            altered.save()
        except frappe.ValidationError:
            altered.reload()
        else:
            raise AssertionError("La venta contabilizada admitió cambiar su importe")
        before_return = standalone_closing.build(prop)
        assert (len(before_return["sources"]["receivables"]) == 2 and
                len(before_return["sources"]["fiscal_documents"]) == 2 and
                len(before_return["sources"]["payments"]) == 2)
        for sale, return_shift in ((service_sale, shift), (stock_sale, None)):
            return_data = {"service": sale["service"], "series": credit_series,
                "shift": return_shift, "reference": "QA-RETURN-" + sale["service"],
                "reason": "Devolución completa de ensayo"}
            reviewed = api.pms_direct_sale_return_quote(name, return_data)
            returned = api.execute(name, "pms_direct_sale_return",
                "qa-direct-return-" + sale["service"],
                {**return_data, "acceptance": reviewed["acceptance"]})
            assert (api.execute(name, "pms_direct_sale_return",
                "qa-direct-return-" + sale["service"],
                {**return_data, "acceptance": reviewed["acceptance"]}) == returned and
                frappe.db.get_value("HS Service Request", sale["service"],
                    "status") == "Returned" and
                frappe.db.get_value("HS PMS Fiscal Document",
                    returned["credit_note"], "document_type") == "Credit Note")
        assert (standalone_inventory.current_balance(prop, stock_item, warehouse) ==
                    (Decimal("3"), Decimal("30")) and
                frappe.db.count("HS PMS Fiscal Document", {
                    "property": name, "document_type": "Credit Note"}) == 2 and
                frappe.db.count("HS Payment", {"property": name,
                    "kind": "Refund", "status": "Posted"}) == 2)
        assert (not api.pms_direct_sale_history(name, returnable=1)["rows"] and
                len(api.pms_direct_sale_history(name)["rows"]) == 2)
        after_return = standalone_closing.build(prop)
        assert (len(after_return["sources"]["fiscal_documents"]) == 4 and
                len(after_return["sources"]["payments"]) == 4 and
                after_return["ledger"]["day_debit"] ==
                after_return["ledger"]["day_credit"])
        print({"site": frappe.local.site, "service": service_sale["service"],
            "stock": stock_sale["service"], "invoice_count": 2,
            "credit_count": 2, "stock_quantity": "3",
            "transaction": "rolled back"})
    finally:
        frappe.db.rollback()
