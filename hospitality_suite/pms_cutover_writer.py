"""Internal ERPNext opening writer for a validated PMS cutover plan.

The caller must hold the source/target cutover locks, validate the current
source, mapping and plan hashes, and keep this in one database transaction.
This module never commits, rewrites PMS links, or changes HS Site Mode. It is
intentionally not exposed as a whitelisted API.
"""

from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal
from hashlib import sha256

import frappe

from hospitality_suite.service import canonical


def _decimal(value):
    return Decimal(str(value or 0))


def _money(value):
    return format(_decimal(value).normalize(), "f")


@contextmanager
def _migration_posting():
    prior_operation = getattr(frappe.local, "hs_operation", False)
    prior_posting = getattr(frappe.local, "hs_posting", False)
    prior_cutover = getattr(frappe.local, "hs_cutover_opening", False)
    frappe.local.hs_operation = True
    frappe.local.hs_posting = True
    frappe.local.hs_cutover_opening = True
    try:
        yield
    finally:
        frappe.local.hs_operation = prior_operation
        frappe.local.hs_posting = prior_posting
        frappe.local.hs_cutover_opening = prior_cutover


def _scope(data, property_name):
    if property_name:
        if not frappe.get_meta(data["doctype"]).has_field("hs_property"):
            frappe.throw("ERPNext hospitality property field is missing: " + data["doctype"])
        data["hs_property"] = property_name
    return data


def _opening_uom():
    name = "HS PMS Monetary Unit"
    whole = frappe.db.get_value("UOM", name, "must_be_whole_number")
    if whole is None:
        frappe.get_doc({"doctype": "UOM", "uom_name": name,
                        "must_be_whole_number": 0, "enabled": 1}).insert(
                            ignore_permissions=True)
    elif whole:
        frappe.throw("The PMS opening UOM must allow fractional amounts")
    return name


def _opening_invoice(row, *, sales):
    """Use ERPNext's opening invoice builder without its per-invoice commits."""
    posting_date = frappe.utils.getdate(row["posting_date"])
    source_due_date = frappe.utils.getdate(row.get("due_date") or posting_date)
    # ERPNext rejects a due date before the new opening invoice's posting
    # date. Preserve the historical due date in remarks for audit instead.
    due_date = max(source_due_date, posting_date)
    tool = frappe.get_single("Opening Invoice Creation Tool")
    tool.update({
        "company": row["company"],
        "cost_center": row["cost_center"],
        "invoice_type": "Sales" if sales else "Purchase",
        "create_missing_party": 0,
        "invoices": [{
            "party": row["customer"] if sales else row["supplier"],
            "outstanding_amount": row["outstanding"],
            "qty": row["outstanding"],
            "posting_date": row["posting_date"],
            "due_date": str(due_date),
            "cost_center": row["cost_center"],
            "temporary_opening_account": row["temporary_opening_account"],
            "item_name": "PMS opening: " + row["source"],
        }],
    })
    data = tool.get_invoices()[0]
    monetary_uom = _opening_uom()
    for item in data["items"]:
        item["uom"] = monetary_uom
        item["stock_uom"] = monetary_uom
        item["conversion_factor"] = 1
    data["currency"] = row["currency"]
    data["conversion_rate"] = 1
    data["remarks"] = "PMS opening source: " + row["source"] + (
        "; reference: " + str(row["reference"]) if row.get("reference") else "") + (
        "; original due date: " + str(source_due_date)
        if source_due_date < posting_date else "")
    data["debit_to" if sales else "credit_to"] = (
        row["debit_to"] if sales else row["payable_account"])
    _scope(data, row.get("property"))
    if sales:
        for field, source in (("hs_folio", "folio"), ("hs_booking", "booking"),
                              ("hs_stay", "stay")):
            if row.get(source):
                if not frappe.get_meta("Sales Invoice").has_field(field):
                    frappe.throw("ERPNext hospitality invoice field is missing: " + field)
                data[field] = row[source]
    invoice = frappe.get_doc(data)
    invoice.flags.ignore_mandatory = True
    invoice.flags.dont_auto_add_taxes = True
    invoice.insert(ignore_permissions=True)
    invoice.submit()
    return invoice


def _bind_day_passes(prop, refs):
    """Attach each live access to its ERP opening balance and source proof."""
    invoices = {row["source"]: name for row, name in zip(
        prop["opening_receivables"], refs["receivables"], strict=True)}
    for row in prop.get("continuing_day_passes", []):
        day_pass = frappe.db.get_value("HS Day Pass", row["source"],
            ["name", "property", "company", "customer", "status",
             "pms_receivable", "quote_snapshot", "service", "sales_invoice",
             "payment", "erp_opening_invoice", "erp_opening_snapshot",
             "erp_opening_sha256"], as_dict=True)
        opening = invoices.get(row["opening_receivable_source"])
        if (not day_pass or row["property"] != prop["property"] or
                row["company"] != prop["company"] or
                (day_pass.property, day_pass.company, day_pass.customer,
                 day_pass.status, day_pass.pms_receivable) !=
                    (prop["property"], prop["company"], row["customer"],
                     "Issued", row["source_receivable"]) or
                day_pass.service or day_pass.sales_invoice or day_pass.payment or
                day_pass.erp_opening_invoice or day_pass.erp_opening_snapshot or
                day_pass.erp_opening_sha256 or
                sha256(str(day_pass.quote_snapshot or "").encode()).hexdigest() !=
                    row["source_hashes"]["quote_sha256"] or
                bool(opening) != bool(_decimal(row["outstanding"]))):
            frappe.throw("PMS Day Pass changed before its ERP continuation: " +
                         row["source"])
        if opening:
            invoice = frappe.db.get_value("Sales Invoice", opening,
                ["company", "hs_property", "customer", "docstatus",
                 "outstanding_amount"], as_dict=True)
            if (not invoice or
                    (invoice.company, invoice.hs_property, invoice.customer,
                     invoice.docstatus) !=
                        (prop["company"], prop["property"], row["customer"], 1) or
                    _decimal(invoice.outstanding_amount) !=
                        _decimal(row["outstanding"])):
                frappe.throw("PMS Day Pass opening balance changed: " +
                             row["source"])
        proof = canonical({**row, "opening_invoice": opening})
        digest = sha256(proof.encode()).hexdigest()
        frappe.db.set_value("HS Day Pass", day_pass.name, {
            "erp_opening_invoice": opening,
            "erp_opening_snapshot": proof,
            "erp_opening_sha256": digest}, update_modified=False)
        refs["day_passes"].append({"source": day_pass.name,
            "opening_invoice": opening, "snapshot_sha256": digest})
        if opening:
            refs["source_documents"].append({
                "source_doctype": "HS Day Pass", "source_name": day_pass.name,
                "target_doctype": "Sales Invoice", "target_name": opening,
                "relationship": "outstanding_balance"})


def _journal(company, posting_date, accounts, remark, property_name=None,
             opening=True):
    data = {
        "doctype": "Journal Entry",
        "voucher_type": "Opening Entry" if opening else "Journal Entry",
        "is_opening": "Yes" if opening else "No", "company": company,
        "multi_currency": 1,
        "posting_date": posting_date, "user_remark": remark,
        "accounts": accounts,
    }
    doc = frappe.get_doc(_scope(data, property_name))
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc


def _supplier_credit(row):
    amount = row["outstanding"]
    return _journal(row["company"], row["posting_date"], [
        {"account": row["payable_account"], "party_type": "Supplier",
         "party": row["supplier"], "cost_center": row["cost_center"],
         "debit_in_account_currency": amount, "exchange_rate": 1},
        {"account": row["temporary_opening_account"],
         "cost_center": row["cost_center"],
         "credit_in_account_currency": amount, "exchange_rate": 1},
    ], "PMS supplier credit opening: " + row["source"], row.get("property"))


def _guarantee_opening(row):
    """Restore the original guarantee book value without recreating cash."""
    amount = _decimal(row["original_base"])
    if amount <= 0 or _decimal(row["remaining_base"]) > amount:
        frappe.throw("PMS guarantee opening has invalid book value")
    payment = frappe.get_doc("HS Payment", row["source"])
    if (payment.property != row["property"] or payment.kind != "Guarantee" or
            payment.status != "Posted" or payment.journal_entry or
            payment.payment_entry or payment.customer not in (None, "", row["customer"])):
        frappe.throw("PMS guarantee source changed before its opening")
    doc = _journal(row["company"], row["posting_date"], [
        {"account": row["temporary_opening_account"],
         "cost_center": row["cost_center"],
         "debit_in_account_currency": str(amount), "exchange_rate": 1},
        {"account": row["liability_account"],
         "cost_center": row["cost_center"],
         "credit_in_account_currency": str(amount), "exchange_rate": 1},
    ], "PMS guarantee opening: " + row["source"], row["property"])
    frappe.db.set_value("HS Payment", payment.name,
        {"customer": row["customer"], "journal_entry": doc.name,
         "booking": row.get("booking"), "stay": row.get("stay")},
        update_modified=False)
    return doc


def _advance_opening(row):
    """Reclassify an unused PMS deposit as an ERP customer credit."""
    amount = _decimal(row["remaining_base"])
    if amount <= 0 or amount > _decimal(row["original_base"]):
        frappe.throw("PMS advance opening has invalid book value")
    payment = frappe.get_doc("HS Payment", row["source"])
    if (payment.property != row["property"] or payment.kind != "Advance" or
            payment.status != "Posted" or payment.payment_entry or
            payment.journal_entry or
            payment.customer not in (None, "", row["customer"])):
        frappe.throw("PMS advance source changed before its opening")
    data = {"doctype": "Payment Entry", "company": row["company"],
        "payment_type": "Receive", "party_type": "Customer",
        "party": row["customer"], "posting_date": row["posting_date"],
        "is_opening": "Yes", "paid_from": row["receivable_account"],
        "paid_to": row["temporary_opening_account"],
        "paid_amount": float(amount), "received_amount": float(amount),
        "source_exchange_rate": 1, "target_exchange_rate": 1,
        "reference_no": "PMS opening: " + row["source"],
        "reference_date": row["posting_date"],
        "cost_center": row["cost_center"],
        "remarks": "PMS unused advance opening: " + row["source"]}
    doc = frappe.get_doc(_scope(data, row["property"]))
    doc.insert(ignore_permissions=True)
    doc.submit()
    frappe.db.set_value("HS Payment", payment.name,
        {"customer": row["customer"], "payment_entry": doc.name,
         "booking": row.get("booking"), "stay": row.get("stay")},
        update_modified=False)
    return doc


def _stock_opening(prop):
    positions = prop["opening_stock"]
    if not positions:
        return None
    temporary_accounts = {row["temporary_opening_account"] for row in positions}
    if len(temporary_accounts) != 1:
        frappe.throw("PMS cutover stock opening needs one temporary account per property")
    items = []
    for row in positions:
        quantity = _decimal(row["quantity"])
        value = _decimal(row["value"])
        if quantity <= 0 or value < 0:
            frappe.throw("PMS cutover stock position has an invalid quantity or value")
        items.append({"item_code": row["item_code"], "warehouse": row["warehouse"],
            "qty": str(quantity), "valuation_rate": _money(value / quantity),
            "allow_zero_valuation_rate": int(value == 0)})
    data = {
        "doctype": "Stock Reconciliation", "purpose": "Opening Stock",
        "company": prop["company"], "posting_date": prop["posting_date"],
        "posting_time": "00:00:00", "cost_center": prop["cost_center"],
        "expense_account": next(iter(temporary_accounts)), "items": items,
    }
    doc = frappe.get_doc(_scope(data, prop.get("property")))
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc


def _continuing_purchase_order(row):
    """Submit only the unreceived balance of a PMS approved order."""
    schedule = max(row["posting_date"],
        row.get("expected_date") or row["posting_date"])
    data = {"doctype": "Purchase Order", "company": row["company"],
        "supplier": row["supplier"], "currency": row["currency"],
        "conversion_rate": float(_decimal(row["conversion_rate"])),
        "transaction_date": row["posting_date"],
        "schedule_date": schedule, "cost_center": row["cost_center"],
        "remarks": "PMS approved order " + row["source"] +
                   ("; source line: " + row["source_line"]
                    if row.get("source_line") else "") +
                   "; reference: " + str(row["reference"]) +
                   ("; " + row["notes"] if row.get("notes") else ""),
        "items": [{"item_code": line["item_code"],
            "qty": float(_decimal(line["quantity"])),
            "rate": float(_decimal(line["unit_net"])),
            "warehouse": line["warehouse"], "schedule_date": schedule,
            "cost_center": row["cost_center"]} for line in row["lines"]]}
    if _decimal(row["recoverable_tax"]):
        data["taxes"] = [{"charge_type": "Actual",
            "account_head": row["tax_account"],
            "description": "PMS recoverable tax " + row["source"],
            "tax_amount": float(_decimal(row["recoverable_tax"])),
            "add_deduct_tax": "Add"}]
    doc = frappe.get_doc(_scope(data, row["property"]))
    doc.flags.dont_auto_add_taxes = True
    doc.set_missing_values()
    doc.calculate_taxes_and_totals()
    if (_decimal(doc.grand_total) != _decimal(row["remaining_gross"]) or
            _decimal(doc.total_taxes_and_charges) !=
                _decimal(row["recoverable_tax"])):
        frappe.throw("PMS purchase order amount changed during ERPNext preparation: " +
                     row["source"])
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc


def _residual_journal(prop):
    if not prop["opening_journal"]:
        return None
    accounts = []
    for row in prop["opening_journal"]:
        account = {"account": row["account"], "cost_center": row["cost_center"],
            "debit_in_account_currency": row["debit_in_account_currency"],
            "credit_in_account_currency": row["credit_in_account_currency"],
            "exchange_rate": float(row.get("exchange_rate", 1))}
        accounts.append(account)
    return _journal(prop["company"], prop["posting_date"], accounts,
                    "PMS residual opening for " + prop["property"],
                    prop.get("property"))


def _profit_loss_transfer_journal(prop):
    if not prop.get("profit_loss_transfer_journal"):
        return None
    accounts = []
    for row in prop["profit_loss_transfer_journal"]:
        accounts.append({"account": row["account"],
            "cost_center": row["cost_center"],
            "debit_in_account_currency": row["debit_in_account_currency"],
            "credit_in_account_currency": row["credit_in_account_currency"],
            "exchange_rate": float(row.get("exchange_rate", 1))})
    return _journal(prop["company"], prop["posting_date"], accounts,
                    "PMS historical P&L transfer for " + prop["property"],
                    prop.get("property"), opening=False)


def _verify(prop, refs):
    """Compare posted ERPNext vouchers with the plan, including stock and AR/AP."""
    expected = defaultdict(Decimal)
    expected_original = defaultdict(Decimal)
    for row in prop["opening_receivables"]:
        amount = _decimal(row["outstanding"])
        expected[row["debit_to"]] += amount
        expected[row["temporary_opening_account"]] -= amount
        expected_original[row["debit_to"]] += amount
        expected_original[row["temporary_opening_account"]] -= amount
    for row in prop["opening_payables"]:
        amount = _decimal(row["outstanding"])
        expected[row["temporary_opening_account"]] += amount
        expected[row["payable_account"]] -= amount
        expected_original[row["temporary_opening_account"]] += amount
        expected_original[row["payable_account"]] -= amount
    for row in prop["opening_supplier_credits"]:
        amount = _decimal(row["outstanding"])
        expected[row["payable_account"]] += amount
        expected[row["temporary_opening_account"]] -= amount
        expected_original[row["payable_account"]] += amount
        expected_original[row["temporary_opening_account"]] -= amount
    for row in prop.get("opening_guarantees", []):
        amount = _decimal(row["original_base"])
        expected[row["temporary_opening_account"]] += amount
        expected[row["liability_account"]] -= amount
        expected_original[row["temporary_opening_account"]] += amount
        expected_original[row["liability_account"]] -= amount
    for row in prop.get("opening_advances", []):
        amount = _decimal(row["remaining_base"])
        expected[row["temporary_opening_account"]] += amount
        expected[row["receivable_account"]] -= amount
        expected_original[row["temporary_opening_account"]] += amount
        expected_original[row["receivable_account"]] -= amount
    for row in prop["opening_stock"]:
        amount = _decimal(row["value"])
        expected[row["inventory_account"]] += amount
        expected[row["temporary_opening_account"]] -= amount
        expected_original[row["inventory_account"]] += amount
        expected_original[row["temporary_opening_account"]] -= amount
    for row in prop["opening_journal"] + prop.get("profit_loss_transfer_journal", []):
        expected[row["account"]] += _decimal(row["debit"]) - _decimal(row["credit"])
        expected_original[row["account"]] += (
            _decimal(row["debit_in_account_currency"]) -
            _decimal(row["credit_in_account_currency"]))

    actual = defaultdict(Decimal)
    actual_original = defaultdict(Decimal)
    for kind, name in refs["vouchers"]:
        voucher = frappe.db.get_value(kind, name,
            ["company", "hs_property", "docstatus"], as_dict=True)
        if (not voucher or voucher.company != prop["company"] or
                voucher.hs_property != prop["property"] or
                voucher.docstatus != 1):
            frappe.throw("PMS cutover voucher belongs to another property: " +
                         kind + " " + name)
        rows = frappe.get_all("GL Entry", filters={"company": prop["company"],
            "voucher_type": kind, "voucher_no": name, "is_cancelled": 0},
            fields=["account", "debit", "credit", "debit_in_account_currency",
                    "credit_in_account_currency", "cost_center"],
            limit_page_length=0)
        if not rows:
            frappe.throw("PMS cutover voucher has no GL entries: " + kind + " " + name)
        for row in rows:
            if row.cost_center and row.cost_center != prop["cost_center"]:
                frappe.throw("PMS cutover GL entry uses another hotel's cost center: " +
                             kind + " " + name)
            actual[row.account] += _decimal(row.debit) - _decimal(row.credit)
            actual_original[row.account] += (_decimal(row.debit_in_account_currency) -
                                             _decimal(row.credit_in_account_currency))
    all_accounts = set(expected) | set(actual)
    differences = {account: _money(actual[account] - expected[account])
        for account in sorted(all_accounts) if actual[account] != expected[account]}
    if differences:
        frappe.throw("PMS cutover GL mismatch: " + frappe.as_json(differences))
    if len(refs["purchase_orders"]) != len(prop.get("purchase_orders", [])):
        frappe.throw("PMS cutover purchase order count changed")
    for source, name in zip(prop.get("purchase_orders", []),
                            refs["purchase_orders"], strict=True):
        order = frappe.get_doc("Purchase Order", name)
        if (order.docstatus != 1 or order.hs_property != prop["property"] or
                order.company != prop["company"] or
                order.supplier != source["supplier"] or
                order.currency != source["currency"] or
                _decimal(order.conversion_rate) !=
                    _decimal(source["conversion_rate"]) or
                _decimal(order.grand_total) !=
                    _decimal(source["remaining_gross"]) or
                _decimal(order.base_grand_total) !=
                    _decimal(_money(_decimal(source["remaining_gross"]) *
                                    _decimal(source["conversion_rate"]))) or
                _decimal(order.total_taxes_and_charges) !=
                    _decimal(source["recoverable_tax"]) or
                len(order.items) != len(source["lines"])):
            frappe.throw("PMS cutover purchase order mismatch: " + name)
        for actual_item, planned_item in zip(order.items, source["lines"], strict=True):
            if (actual_item.item_code != planned_item["item_code"] or
                    actual_item.warehouse != planned_item["warehouse"] or
                    _decimal(actual_item.qty) != _decimal(planned_item["quantity"]) or
                    _decimal(actual_item.amount) != _decimal(planned_item["net"])):
                frappe.throw("PMS cutover purchase order line mismatch: " + name)
    original_differences = {account: _money(actual_original[account] -
        expected_original[account]) for account in sorted(all_accounts)
        if actual_original[account] != expected_original[account]}
    if original_differences:
        frappe.throw("PMS cutover account currency mismatch: " +
                     frappe.as_json(original_differences))

    for row, name in zip(prop["opening_receivables"], refs["receivables"], strict=True):
        doc = frappe.get_doc("Sales Invoice", name)
        if (doc.docstatus != 1 or doc.company != prop["company"] or
                doc.customer != row["customer"] or doc.debit_to != row["debit_to"] or
                (row.get("property") and doc.hs_property != row["property"]) or
                (row.get("folio") and doc.hs_folio != row["folio"]) or
                (row.get("booking") and doc.hs_booking != row["booking"]) or
                (row.get("stay") and doc.hs_stay != row["stay"]) or
                doc.currency != row["currency"] or
                str(doc.posting_date) != str(row["posting_date"]) or
                _decimal(doc.outstanding_amount) != _decimal(row["outstanding"])):
            frappe.throw("PMS cutover customer invoice mismatch: " + name)
    if len(refs["day_passes"]) != len(prop.get("continuing_day_passes", [])):
        frappe.throw("PMS Day Pass continuation count changed")
    for planned, bound in zip(prop.get("continuing_day_passes", []),
                              refs["day_passes"], strict=True):
        source = frappe.db.get_value("HS Day Pass", planned["source"],
            ["property", "company", "customer", "status", "pms_receivable",
             "erp_opening_invoice", "erp_opening_snapshot",
             "erp_opening_sha256"], as_dict=True)
        proof = canonical({**planned,
            "opening_invoice": bound["opening_invoice"]})
        digest = sha256(proof.encode()).hexdigest()
        if (not source or bound["source"] != planned["source"] or
                source.property != planned["property"] or
                source.company != planned["company"] or
                source.customer != planned["customer"] or
                source.status != "Issued" or
                source.pms_receivable != planned["source_receivable"] or
                source.erp_opening_invoice != bound["opening_invoice"] or
                source.erp_opening_snapshot != proof or
                source.erp_opening_sha256 != digest or
                bound["snapshot_sha256"] != digest):
            frappe.throw("PMS Day Pass continuation mismatch: " +
                         planned["source"])
    for row, name in zip(prop["opening_payables"], refs["payables"], strict=True):
        doc = frappe.get_doc("Purchase Invoice", name)
        if (doc.docstatus != 1 or doc.company != prop["company"] or
                doc.supplier != row["supplier"] or
                doc.credit_to != row["payable_account"] or
                (row.get("property") and doc.hs_property != row["property"]) or
                doc.currency != row["currency"] or
                str(doc.posting_date) != str(row["posting_date"]) or
                _decimal(doc.outstanding_amount) != _decimal(row["outstanding"])):
            frappe.throw("PMS cutover supplier invoice mismatch: " + name)
    for row, name in zip(prop["opening_supplier_credits"],
                         refs["supplier_credits"], strict=True):
        entries = frappe.get_all("Payment Ledger Entry", filters={
            "voucher_type": "Journal Entry", "voucher_no": name},
            fields=["party_type", "party", "account", "amount"],
            limit_page_length=0)
        if (len(entries) != 1 or entries[0].party_type != "Supplier" or
                entries[0].party != row["supplier"] or
                entries[0].account != row["payable_account"] or
                _decimal(entries[0].amount) != -_decimal(row["outstanding"])):
            frappe.throw("PMS cutover supplier credit ledger mismatch: " + name)

    for row, name in zip(prop.get("opening_guarantees", []),
                         refs["guarantees"], strict=True):
        payment = frappe.get_doc("HS Payment", row["source"])
        doc = frappe.get_doc("Journal Entry", name)
        if (payment.property != row["property"] or payment.kind != "Guarantee" or
                payment.customer != row["customer"] or
                payment.booking != row.get("booking") or
                payment.stay != row.get("stay") or
                payment.journal_entry != name or doc.docstatus != 1 or
                doc.company != row["company"] or doc.hs_property != row["property"]):
            frappe.throw("PMS cutover guarantee bridge mismatch: " + row["source"])
        from hospitality_suite.accounting import original_guarantee
        line = original_guarantee(payment)
        if (line.account != row["liability_account"] or
                _decimal(line.credit_in_account_currency) !=
                _decimal(row["original_base"])):
            frappe.throw("PMS cutover guarantee liability mismatch: " + row["source"])
    for row, name in zip(prop.get("opening_advances", []),
                         refs["advances"], strict=True):
        payment = frappe.get_doc("HS Payment", row["source"])
        doc = frappe.get_doc("Payment Entry", name)
        if (payment.property != row["property"] or payment.kind != "Advance" or
                payment.customer != row["customer"] or
                payment.payment_entry != name or
                payment.booking != row.get("booking") or
                payment.stay != row.get("stay") or
                doc.docstatus != 1 or doc.company != row["company"] or
                doc.hs_property != row["property"] or
                doc.party != row["customer"] or
                doc.paid_from != row["receivable_account"] or
                doc.paid_to != row["temporary_opening_account"] or
                _decimal(doc.unallocated_amount) != _decimal(row["remaining_base"])):
            frappe.throw("PMS cutover advance bridge mismatch: " + row["source"])
        entries = frappe.get_all("Payment Ledger Entry", filters={
            "voucher_type": "Payment Entry", "voucher_no": name,
            "delinked": 0}, fields=["party", "account", "amount"],
            limit_page_length=0)
        if (len(entries) != 1 or entries[0].party != row["customer"] or
                entries[0].account != row["receivable_account"] or
                _decimal(entries[0].amount) != -_decimal(row["remaining_base"])):
            frappe.throw("PMS cutover advance customer credit mismatch: " + row["source"])

    if prop["opening_stock"]:
        stock_name = refs["stock_reconciliation"]
        actual_stock = {}
        for row in frappe.get_all("Stock Ledger Entry",
                filters={"voucher_type": "Stock Reconciliation",
                         "voucher_no": stock_name, "is_cancelled": 0},
                fields=["item_code", "warehouse", "qty_after_transaction", "stock_value"],
                limit_page_length=0):
            key = (row.item_code, row.warehouse)
            if key in actual_stock:
                frappe.throw("PMS cutover stock ledger has duplicate position: " + stock_name)
            actual_stock[key] = [_decimal(row.qty_after_transaction),
                                 _decimal(row.stock_value)]
        expected_stock = defaultdict(lambda: [Decimal(0), Decimal(0)])
        for row in prop["opening_stock"]:
            pair = expected_stock[(row["item_code"], row["warehouse"])]
            pair[0] += _decimal(row["quantity"])
            pair[1] += _decimal(row["value"])
        if dict(actual_stock) != dict(expected_stock):
            frappe.throw("PMS cutover stock ledger mismatch: " + stock_name + " " +
                repr(dict(actual_stock)) + " != " + repr(dict(expected_stock)))
    return {"accounts": {account: _money(actual[account])
                         for account in sorted(all_accounts)},
            "account_currency_balances": {account: _money(actual_original[account])
                for account in sorted(all_accounts)},
            "stock_positions": len(prop["opening_stock"])}


def post_property(prop):
    """Post one planned property in the caller's open transaction; never commit.

    Roll back all its documents to a savepoint on any ERPNext or reconciliation
    failure. A successful call still requires the outer cutover transaction.
    """
    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw("ERPNext is required for a PMS cutover opening")
    if prop.get("temporary_net") not in (None, "0", "0.0") and _decimal(
            prop["temporary_net"]) != 0:
        frappe.throw("PMS cutover plan does not clear the temporary account")
    savepoint = "hs_cutover_" + frappe.generate_hash(length=12)
    frappe.db.savepoint(savepoint)
    try:
        with _migration_posting():
            return _post_property(prop)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def _post_property(prop):
    refs = {"property": prop["property"], "company": prop["company"],
            "receivables": [], "payables": [], "supplier_credits": [],
            "day_passes": [],
            "guarantees": [], "advances": [],
            "stock_reconciliation": None, "residual_journal": None,
            "profit_loss_transfer_journal": None,
            "purchase_orders": [],
            "vouchers": [], "source_documents": []}
    for row in prop["opening_receivables"]:
        doc = _opening_invoice(row, sales=True)
        refs["receivables"].append(doc.name)
        refs["vouchers"].append((doc.doctype, doc.name))
        refs["source_documents"].append({"source_doctype": "HS PMS Receivable",
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name})
    _bind_day_passes(prop, refs)
    for row in prop["opening_payables"]:
        doc = _opening_invoice(row, sales=False)
        refs["payables"].append(doc.name)
        refs["vouchers"].append((doc.doctype, doc.name))
        refs["source_documents"].append({
            "source_doctype": ("HS PMS Agency Commission" if
                row.get("source_kind") == "Agency Commission" else "HS PMS Purchase"),
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name})
    for row in prop["opening_supplier_credits"]:
        doc = _supplier_credit(row)
        refs["supplier_credits"].append(doc.name)
        refs["vouchers"].append((doc.doctype, doc.name))
        refs["source_documents"].append({"source_doctype": "HS PMS Purchase Return",
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name})
    for row in prop.get("opening_guarantees", []):
        doc = _guarantee_opening(row)
        refs["guarantees"].append(doc.name)
        refs["vouchers"].append((doc.doctype, doc.name))
        refs["source_documents"].append({"source_doctype": "HS Payment",
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name})
    for row in prop.get("opening_advances", []):
        doc = _advance_opening(row)
        refs["advances"].append(doc.name)
        refs["vouchers"].append((doc.doctype, doc.name))
        refs["source_documents"].append({"source_doctype": "HS Payment",
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name})
    stock = _stock_opening(prop)
    if stock:
        refs["stock_reconciliation"] = stock.name
        refs["vouchers"].append((stock.doctype, stock.name))
        for row in prop["opening_stock"]:
            refs["source_documents"].append({"source_doctype": "HS Stock Position",
                "source_product": row["source_product"],
                "source_warehouse": row["source_warehouse"],
                "target_doctype": stock.doctype, "target_name": stock.name,
                "target_item": row["item_code"], "target_warehouse": row["warehouse"]})
    for row in prop.get("purchase_orders", []):
        doc = _continuing_purchase_order(row)
        refs["purchase_orders"].append(doc.name)
        refs["source_documents"].append({"source_doctype": "HS PMS Purchase Order",
            "source_name": row["source"], "target_doctype": doc.doctype,
            "target_name": doc.name,
            **({"source_line": row["source_line"]}
               if row.get("source_line") else {})})
    journal = _residual_journal(prop)
    if journal:
        refs["residual_journal"] = journal.name
        refs["vouchers"].append((journal.doctype, journal.name))
    profit_loss = _profit_loss_transfer_journal(prop)
    if profit_loss:
        refs["profit_loss_transfer_journal"] = profit_loss.name
        refs["vouchers"].append((profit_loss.doctype, profit_loss.name))
    refs["reconciliation"] = _verify(prop, refs)
    return refs
