"""Freeze paid PMS counter sales that may need a native return after cutover."""

from decimal import Decimal

import frappe

def _decimal(value):
    return Decimal(str(value or 0))


def _one(doctype, filters, fields):
    rows = frappe.get_all(doctype, filters=filters, fields=fields,
        limit_page_length=2)
    return rows[0] if len(rows) == 1 else None


def _source(service, prop, cfg):
    if (service.company != prop["organization"] or service.stay or
            service.folio or service.charge or service.sales_invoice or
            service.credit_note or service.pms_fiscal_credit or
            service.return_stock_entry or not service.pms_party or
            not service.pms_product or not service.pms_fiscal_invoice):
        raise ValueError("La venta de mostrador no conserva su origen PMS")
    receivable = frappe.db.get_value("HS PMS Receivable", service.pms_receivable,
        ["property", "organization", "party", "source_service", "status",
         "currency", "amount", "net_amount", "tax_amount",
         "receivable_account", "income_account", "tax_account"], as_dict=True)
    invoice = frappe.db.get_value("HS PMS Fiscal Document",
        service.pms_fiscal_invoice,
        ["property", "organization", "document_type", "document_number",
         "party", "status", "currency", "net_amount", "tax_amount",
         "total_amount"], as_dict=True)
    line = _one("HS PMS Fiscal Line", {"parent": service.pms_fiscal_invoice},
        ["receivable", "product", "income_account", "tax_account",
         "net_amount", "tax_amount", "total_amount"])
    payment = _one("HS Payment", {"property": service.property,
        "service": service.name, "pms_receivable": service.pms_receivable,
        "kind": "Payment", "status": "Posted"},
        ["name", "customer", "pms_party", "method", "currency", "amount",
         "base_amount", "exchange_rate", "pms_journal"])
    allocation = _one("HS PMS Allocation", {
        "property": service.property, "receivable": service.pms_receivable,
        "payment": payment.name if payment else "", "kind": "Direct"},
        ["amount", "journal"])
    method = frappe.db.get_value("HS Payment Method", payment.method,
        ["property", "company", "currency", "account", "mode_of_payment",
         "is_cash"], as_dict=True) if payment else None
    total = _decimal(service.amount)
    if (not receivable or not invoice or not line or not payment or
            not allocation or not method or total <= 0 or
            receivable.property != service.property or
            receivable.organization != prop["organization"] or
            receivable.party != service.pms_party or
            receivable.source_service != service.name or
            receivable.status != "Posted" or
            receivable.currency != prop["currency"] or
            invoice.property != service.property or
            invoice.organization != prop["organization"] or
            invoice.document_type != "Invoice" or invoice.status != "Posted" or
            invoice.party != service.pms_party or
            invoice.currency != prop["currency"] or
            line.receivable != service.pms_receivable or
            line.product != service.pms_product or
            line.income_account != receivable.income_account or
            line.tax_account != receivable.tax_account or
            payment.pms_party != service.pms_party or
            not payment.pms_journal or allocation.journal != payment.pms_journal or
            method.property != service.property or
            method.company != prop["organization"] or
            method.currency != payment.currency or
            any(_decimal(value) != total for value in
                (receivable.amount, invoice.total_amount, line.total_amount,
                 payment.base_amount, allocation.amount)) or
            any(_decimal(value) != _decimal(invoice.net_amount) for value in
                (receivable.net_amount, line.net_amount)) or
            any(_decimal(value) != _decimal(invoice.tax_amount) for value in
                (receivable.tax_amount, line.tax_amount)) or
            _decimal(invoice.net_amount) + _decimal(invoice.tax_amount) != total or
            _decimal(payment.amount) <= 0 or
            abs(_decimal(payment.amount) *
                _decimal(payment.exchange_rate) - total) > Decimal("0.01") or
            service.currency != prop["currency"] or
            frappe.db.exists("HS PMS Fiscal Document", {
                "property": service.property, "source_invoice":
                    service.pms_fiscal_invoice, "document_type": "Credit Note",
                "status": "Posted"}) or
            frappe.db.exists("HS Payment", {"property": service.property,
                "source_payment": payment.name, "kind": "Refund", "status": "Posted"})):
        raise ValueError("La factura, cuenta y cobro PMS no concilian")
    accounts = cfg["accounts"]
    target = {field: accounts.get(receivable.get(field))
        if receivable.get(field) else None for field in
        ("receivable_account", "income_account", "tax_account")}
    cash_account = accounts.get(method.account)
    customer = cfg["parties"].get(service.pms_party, {}).get("customer")
    item = cfg["products"].get(service.pms_product)
    product = frappe.db.get_value("HS Product", service.pms_product,
        ["property", "organization", "product_type"], as_dict=True)
    native_item = frappe.db.get_value("Item", item,
        ["is_sales_item", "is_stock_item", "disabled"], as_dict=True) if item else None
    if (not target["receivable_account"] or not target["income_account"] or
            (receivable.tax_account and not target["tax_account"]) or
            not cash_account or not customer or not item or not product or
            product.property != service.property or
            product.organization != prop["organization"] or
            not native_item or not native_item.is_sales_item or
            native_item.disabled or bool(native_item.is_stock_item) !=
                (product.product_type == "Stock")):
        raise ValueError("Faltan destinos de la venta de mostrador")
    stock = None
    if product.product_type == "Stock":
        movement = frappe.db.get_value("HS Stock Movement", service.stock_entry,
            ["name", "property", "product", "warehouse", "direction",
             "quantity_delta", "value_delta", "source_doctype",
             "source_name", "purpose", "journal"], as_dict=True)
        journal = frappe.get_doc("HS Journal", movement.journal) if movement else None
        debit_lines = [row for row in journal.lines
            if _decimal(row.debit) > 0] if journal else []
        credit_lines = [row for row in journal.lines
            if _decimal(row.credit) > 0] if journal else []
        target_warehouse = cfg["warehouses"].get(service.warehouse)
        if (not movement or movement.property != service.property or
                movement.product != service.pms_product or
                movement.warehouse != service.warehouse or
                movement.direction != "Issue" or
                movement.source_doctype != "HS Service Request" or
                movement.source_name != service.name or
                movement.purpose != "Direct Sale" or
                _decimal(movement.quantity_delta) != -_decimal(service.quantity) or
                _decimal(movement.value_delta) >= 0 or
                not journal or journal.status != "Posted" or
                journal.company != service.company or
                journal.property != service.property or
                journal.organization != prop["organization"] or
                journal.source_doctype != "HS Stock Movement" or
                journal.source_name != movement.name or
                journal.purpose != "Issue" or
                len(journal.lines) != 2 or
                len(debit_lines) != 1 or len(credit_lines) != 1 or
                _decimal(debit_lines[0].debit) !=
                    -_decimal(movement.value_delta) or
                _decimal(credit_lines[0].credit) !=
                    -_decimal(movement.value_delta) or
                not accounts.get(debit_lines[0].account) or
                not accounts.get(credit_lines[0].account) or
                not target_warehouse):
            raise ValueError("La salida de inventario PMS no concilia")
        stock = {"source_movement": service.stock_entry,
            "source_warehouse": service.warehouse,
            "warehouse": target_warehouse,
            "quantity": str(_decimal(service.quantity)),
            "value": str(-_decimal(movement.value_delta)),
            "expense_account": accounts[debit_lines[0].account],
            "inventory_account": accounts[credit_lines[0].account]}
    elif service.stock_entry:
        raise ValueError("Un servicio de mostrador conserva salida de inventario")
    return {"source": service.name, "property": service.property,
        "company": cfg["company"], "customer": customer, "item_code": item,
        "cost_center": cfg["cost_center"],
        "source_party": service.pms_party,
        "source_product": service.pms_product,
        "source_receivable": service.pms_receivable,
        "source_invoice": service.pms_fiscal_invoice,
        "document_number": invoice.document_number,
        "net_amount": str(_decimal(invoice.net_amount)),
        "tax_amount": str(_decimal(invoice.tax_amount)),
        "total_amount": str(total),
        "quantity": str(_decimal(service.quantity)),
        "currency": service.currency,
        "target_accounts": target,
        "source_payment": payment.name,
        "payment_currency": payment.currency,
        "payment_amount": str(_decimal(payment.amount)),
        "payment_rate": str(_decimal(payment.exchange_rate)),
        "target_cash_account": cash_account,
        "payment_method": payment.method,
        "mode_of_payment": method.mode_of_payment,
        "is_cash": bool(method.is_cash),
        "stock": stock}


def collect(prop, cfg, blockers):
    rows = frappe.get_all("HS Service Request", filters={
        "property": prop["property"], "status": "Delivered",
        "pms_receivable": ["is", "set"]},
        fields=["name", "company", "property", "stay", "folio", "charge",
            "sales_invoice", "credit_note", "pms_fiscal_credit",
            "return_stock_entry", "pms_party", "pms_product",
            "pms_receivable", "pms_fiscal_invoice", "stock_entry",
            "warehouse", "quantity", "amount", "currency"],
        order_by="name asc", limit_page_length=0)
    proofs = []
    for row in rows:
        try:
            proofs.append(_source(row, prop, cfg))
        except ValueError as exc:
            blockers.append({"property": prop["property"],
                "code": "unreconciled_direct_sale_continuation",
                "source": row.name, "detail": str(exc)})
    return proofs
