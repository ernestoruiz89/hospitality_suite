"""Read-only, sitewide reconciliation before a PMS -> ERPNext cutover.

This is a preflight only. It never installs ERPNext, creates target records, or
changes HS Site Mode. Run it again after freezing operations at the cutover.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, now_datetime

from hospitality_suite.security import is_system
from hospitality_suite.schema import SCOPED
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider
from hospitality_suite.time import to_site


def _decimal(value):
    return Decimal(str(value or 0))


def _money(value):
    # A source audit must retain currencies with more than two decimal places.
    return format(_decimal(value).normalize(), "f")


def _rows(doctype, prop, fields, **filters):
    return frappe.get_all(doctype, filters={"property": prop.name, **filters},
        fields=fields, order_by="name asc", limit_page_length=0)


def _sums(doctype, prop, reference, value, **filters):
    grouped = defaultdict(Decimal)
    for row in _rows(doctype, prop, [reference, value], **filters):
        if row.get(reference):
            grouped[row[reference]] += _decimal(row[value])
    return grouped


def _ledger(prop):
    accounts = _rows("HS Account", prop,
        ["name", "account_code", "account_number", "account_name", "root_type",
         "account_type", "account_currency", "is_group", "active", "is_cash", "is_bank"])
    postings = frappe.db.sql(
        "SELECT l.account,l.party,SUM(l.debit) AS debit,SUM(l.credit) AS credit,"
        "SUM(l.debit_in_account_currency-l.credit_in_account_currency) AS original "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' GROUP BY l.account,l.party",
        prop.name, as_dict=True)
    by_account = defaultdict(Decimal)
    by_original = defaultdict(Decimal)
    by_party = defaultdict(Decimal)
    debit = credit = Decimal(0)
    for row in postings:
        movement = _decimal(row.debit) - _decimal(row.credit)
        debit += _decimal(row.debit)
        credit += _decimal(row.credit)
        by_account[row.account] += movement
        by_original[row.account] += _decimal(row.original)
        if row.party:
            by_party[(row.account, row.party)] += movement
    return ({"debit": _money(debit), "credit": _money(credit),
             "accounts": [{**dict(row), "balance": _money(by_account[row.name]),
                 "original_balance": _money(by_original[row.name])} for row in accounts]},
            by_account, by_party)


def _receivables(prop, by_account, by_party, blockers):
    receivable_accounts = {row.name for row in _rows("HS Account", prop,
        ["name"], root_type="Asset", account_type="Receivable")}
    allocations = defaultdict(Decimal)
    for row in _rows("HS PMS Allocation", prop, ["receivable", "kind", "amount"]):
        sign = -1 if row.kind in ("Direct Reversed", "Advance Reversed",
                                  "Guarantee Reversed", "Opening Credit Reversed",
                                  "Opening Guarantee Reversed") else 1
        allocations[row.receivable] += sign * _decimal(row.amount)
    credited = defaultdict(Decimal)
    for row in frappe.db.sql(
        "SELECT l.receivable,SUM(l.total_amount) AS credited "
        "FROM `tabHS PMS Fiscal Line` l JOIN `tabHS PMS Fiscal Document` d "
        "ON d.name=l.parent WHERE d.property=%s AND d.document_type='Credit Note' "
        "AND d.status='Posted' GROUP BY l.receivable", prop.name, as_dict=True):
        credited[row.receivable] = _decimal(row.credited)
    open_rows = []
    expected = defaultdict(Decimal)
    for row in _rows("HS PMS Receivable", prop,
            ["name", "party", "reference", "receivable_account", "amount",
             "currency", "due_date", "status", "folio", "booking",
             "source_charge", "experience_order"]):
        remaining = (_decimal(row.amount) - allocations[row.name] - credited[row.name]
                     if row.status == "Posted" else Decimal(0))
        if remaining < 0:
            blockers.append({"property": prop.name, "code": "negative_receivable",
                             "source": row.name, "difference": _money(remaining)})
        if remaining:
            if row.receivable_account not in receivable_accounts:
                blockers.append({"property": prop.name, "code": "invalid_receivable_account",
                    "source": row.name, "account": row.receivable_account})
            expected[(row.receivable_account, row.party)] += remaining
            folio = frappe.db.get_value("HS Folio", row.folio,
                ["stay", "booking"], as_dict=True) if row.folio else None
            open_rows.append({"source": row.name, "party": row.party,
                "account": row.receivable_account, "reference": row.reference,
                "currency": row.currency,
                "due_date": str(row.due_date) if row.due_date else None,
                "folio": row.folio, "booking": row.booking or (
                    folio.booking if folio else None),
                "stay": folio.stay if folio else None,
                "source_charge": row.source_charge,
                "experience_order": row.experience_order,
                "outstanding": _money(remaining)})
    for account in sorted(receivable_accounts | {account for account, _ in expected}):
        parties = ({party for acct, party in expected if acct == account} |
                   {party for acct, party in by_party if acct == account})
        for party in sorted(parties):
            difference = by_party[(account, party)] - expected[(account, party)]
            if difference:
                blockers.append({"property": prop.name, "code": "receivable_control_mismatch",
                    "account": account, "party": party, "difference": _money(difference)})
        unassigned = by_account[account] - sum((by_party[(account, party)]
            for party in parties), Decimal(0))
        if unassigned:
            blockers.append({"property": prop.name, "code": "receivable_without_party",
                "account": account, "difference": _money(unassigned)})
    return open_rows


def _payables(prop, by_account, by_party, blockers):
    payable_accounts = {row.name for row in _rows("HS Account", prop,
        ["name"], root_type="Liability", account_type="Payable")}
    supplier_payments = _sums("HS Payment", prop, "pms_purchase", "base_amount",
        kind="Supplier Payment", status="Posted")
    commission_payments = _sums("HS Payment", prop, "pms_agent_commission",
        "base_amount", kind="Supplier Payment", status="Posted")
    supplier_refunds = _sums("HS Payment", prop, "pms_purchase_return",
        "base_amount", kind="Supplier Refund", status="Posted")
    returns_applied = _sums("HS PMS Purchase Return", prop, "purchase", "payable_applied",
        status="Posted")
    expected = defaultdict(Decimal)
    open_rows = []
    for row in _rows("HS PMS Purchase", prop,
            ["name", "supplier", "supplier_reference", "payable_account",
             "base_amount", "status"]):
        if row.status != "Posted":
            continue
        remaining = (_decimal(row.base_amount) - supplier_payments[row.name]
                     - returns_applied[row.name])
        if remaining < 0:
            blockers.append({"property": prop.name, "code": "negative_supplier_payable",
                             "source": row.name, "difference": _money(remaining)})
        if remaining > 0:
            if row.payable_account not in payable_accounts:
                blockers.append({"property": prop.name, "code": "invalid_payable_account",
                    "source": row.name, "account": row.payable_account})
            expected[(row.payable_account, row.supplier)] -= remaining
            open_rows.append({"kind": "Purchase", "source": row.name,
                "party": row.supplier, "account": row.payable_account,
                "reference": row.supplier_reference, "outstanding": _money(remaining)})
    for row in _rows("HS PMS Agency Commission", prop,
            ["name", "supplier", "booking", "payable_account", "amount", "status"]):
        if row.status != "Posted":
            continue
        remaining = _decimal(row.amount) - commission_payments[row.name]
        if remaining < 0:
            blockers.append({"property": prop.name, "code": "negative_agency_payable",
                             "source": row.name, "difference": _money(remaining)})
        if remaining > 0:
            if row.payable_account not in payable_accounts:
                blockers.append({"property": prop.name, "code": "invalid_payable_account",
                    "source": row.name, "account": row.payable_account})
            expected[(row.payable_account, row.supplier)] -= remaining
            open_rows.append({"kind": "Agency Commission", "source": row.name,
                "party": row.supplier, "account": row.payable_account,
                "reference": row.booking, "outstanding": _money(remaining)})
    for row in _rows("HS PMS Purchase Return", prop,
            ["name", "supplier", "payable_account", "supplier_credit", "status"]):
        if row.status != "Posted":
            continue
        remaining = _decimal(row.supplier_credit) - supplier_refunds[row.name]
        if remaining < 0:
            blockers.append({"property": prop.name, "code": "negative_supplier_credit",
                             "source": row.name, "difference": _money(remaining)})
        if remaining > 0:
            if row.payable_account not in payable_accounts:
                blockers.append({"property": prop.name, "code": "invalid_payable_account",
                    "source": row.name, "account": row.payable_account})
            expected[(row.payable_account, row.supplier)] += remaining
            open_rows.append({"kind": "Supplier Credit", "source": row.name,
                "party": row.supplier, "account": row.payable_account,
                "outstanding": _money(remaining)})
    for account in sorted(payable_accounts | {account for account, _ in expected}):
        parties = ({party for acct, party in expected if acct == account} |
                   {party for acct, party in by_party if acct == account})
        for party in sorted(parties):
            difference = by_party[(account, party)] - expected[(account, party)]
            if difference:
                blockers.append({"property": prop.name, "code": "payable_control_mismatch",
                    "account": account, "party": party, "difference": _money(difference)})
        unassigned = by_account[account] - sum((by_party[(account, party)]
            for party in parties), Decimal(0))
        if unassigned:
            blockers.append({"property": prop.name, "code": "payable_without_party",
                "account": account, "difference": _money(unassigned)})
    return open_rows


def _stock(prop, by_account, blockers):
    grouped = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in _rows("HS Stock Movement", prop,
            ["product", "warehouse", "quantity_delta", "value_delta"]):
        item = grouped[(row.product, row.warehouse)]
        item[0] += _decimal(row.quantity_delta)
        item[1] += _decimal(row.value_delta)
    products = {row.name: row for row in _rows("HS Product", prop,
        ["name", "product_code", "inventory_account", "product_type"])}
    account_values = defaultdict(Decimal)
    inventory_accounts = {row.inventory_account for row in products.values()
                          if row.product_type == "Stock" and row.inventory_account}
    inventory_accounts.update(row.name for row in _rows("HS Account", prop,
        ["name"], root_type="Asset", account_type="Stock"))
    positions = []
    for (product, warehouse), (quantity, value) in sorted(grouped.items()):
        if quantity < 0 or value < 0 or (quantity == 0 and value != 0):
            blockers.append({"property": prop.name, "code": "invalid_stock_balance",
                "product": product, "warehouse": warehouse,
                "quantity": str(quantity), "value": _money(value)})
        if quantity == 0 and value == 0:
            continue
        account = products.get(product).inventory_account if product in products else None
        if not account:
            blockers.append({"property": prop.name, "code": "stock_without_account",
                             "product": product, "warehouse": warehouse})
        else:
            account_values[account] += value
        positions.append({"product": product, "warehouse": warehouse,
            "inventory_account": account, "quantity": str(quantity), "value": _money(value)})
    for account in sorted(inventory_accounts | set(account_values)):
        difference = by_account[account] - account_values[account]
        if difference:
            blockers.append({"property": prop.name, "code": "stock_control_mismatch",
                "account": account, "difference": _money(difference)})
    return positions


def _deposit_journal_line(prop, journal_name, source_doctype, source_name,
                          purpose, account, amount, *, debit):
    journal = frappe.db.get_value("HS Journal", journal_name,
        ["property", "status", "source_doctype", "source_name", "purpose"],
        as_dict=True) if journal_name else None
    if (not journal or journal.property != prop.name or
            journal.status != "Posted" or
            journal.source_doctype != source_doctype or
            (source_name and journal.source_name != source_name) or
            journal.purpose != purpose):
        return False
    lines = frappe.get_all("HS Journal Line", filters={
        "parenttype": "HS Journal", "parent": journal_name,
        "account": account}, fields=["debit", "credit",
            "debit_in_account_currency", "credit_in_account_currency"],
        limit_page_length=0)
    positive = "debit" if debit else "credit"
    original = positive + "_in_account_currency"
    matches = [line for line in lines if _decimal(line[positive]) > 0]
    return (len(matches) == 1 and
            _decimal(matches[0][positive]) == amount and
            _decimal(matches[0][original]) == amount)


def _open_deposits(prop, blockers):
    """Expose customer liabilities that still need an ERP allocation route."""
    from hospitality_suite.standalone_receivables import deposit_available

    deposits = []
    for row in _rows("HS Payment", prop,
            ["name", "kind", "pms_party", "booking", "stay", "folio",
             "currency", "amount", "base_amount", "exchange_rate",
             "pms_counter_account", "pms_journal"],
            kind=["in", ["Advance", "Guarantee"]], status="Posted"):
        remaining = deposit_available(prop, row.name, row.kind)
        if remaining < 0:
            blockers.append({"property": prop.name, "code": "negative_deposit_balance",
                             "source": row.name, "difference": _money(remaining)})
        if not _deposit_journal_line(prop, row.pms_journal,
                "HS Payment", row.name, row.kind,
                row.pms_counter_account, _decimal(row.base_amount), debit=False):
            blockers.append({"property": prop.name,
                "code": ("invalid_guarantee_origin" if row.kind == "Guarantee"
                         else "invalid_advance_origin"), "source": row.name})
        for allocation in _rows("HS PMS Allocation", prop,
                ["name", "kind", "amount", "journal"], payment=row.name,
                kind=["in", [row.kind + " Applied", row.kind + " Reversed"]]):
            if (not _deposit_journal_line(prop, allocation.journal,
                    "HS PMS Allocation", None, allocation.kind,
                    row.pms_counter_account, _decimal(allocation.amount),
                    debit=allocation.kind.endswith("Applied")) or
                    frappe.db.count("HS PMS Allocation", {
                        "property": prop.name, "journal": allocation.journal}) != 1):
                blockers.append({"property": prop.name,
                    "code": "invalid_deposit_application_journal",
                    "source": row.name, "allocation": allocation.name})
        refund_kind = "Guarantee Refund" if row.kind == "Guarantee" else "Refund"
        for refund in _rows("HS Payment", prop,
                ["name", "base_amount", "pms_journal"],
                source_payment=row.name, kind=refund_kind, status="Posted"):
            if not _deposit_journal_line(prop, refund.pms_journal,
                    "HS Payment", refund.name, "Refund",
                    row.pms_counter_account, _decimal(refund.base_amount),
                    debit=True):
                blockers.append({"property": prop.name,
                    "code": "invalid_deposit_refund_journal",
                    "source": row.name, "refund": refund.name})
        if remaining > 0:
            folio = frappe.db.get_value("HS Folio", row.folio,
                ["booking", "stay"], as_dict=True) if row.folio else None
            booking = row.booking or (folio.booking if folio else None)
            stay = row.stay or (folio.stay if folio else None)
            deposits.append({"source": row.name, "kind": row.kind,
                "party": row.pms_party, "booking": booking,
                "stay": stay, "folio": row.folio,
                "currency": row.currency, "original_amount": _money(row.amount),
                "original_base": _money(row.base_amount),
                "exchange_rate": _money(row.exchange_rate),
                "used_base": _money(_decimal(row.base_amount) - remaining),
                "remaining_base": _money(remaining),
                "liability_account": row.pms_counter_account,
                "pms_journal": row.pms_journal})
    return deposits


def _accepted_day_pass_quote(prop, day_pass):
    """Keep the issued sale terms, not the current product price, for mapping."""
    try:
        quote = frappe.parse_json(day_pass.quote_snapshot)
        if not isinstance(quote, dict) or type(quote.get("people")) is not int:
            return None
        people = quote["people"]
        net = Decimal(str(quote["net_amount"]))
        tax = Decimal(str(quote["tax_amount"]))
        total = Decimal(str(quote["total_amount"]))
        unit_rate = Decimal(str(quote["unit_rate"]))
        if (people <= 0 or people != day_pass.people or
                quote.get("customer") != day_pass.customer or
                (quote.get("guest") or None) != (day_pass.guest or None) or
                quote.get("currency") != prop.currency or
                get_datetime(to_site(quote["starts_at"], prop)) !=
                    get_datetime(day_pass.starts_at) or
                get_datetime(to_site(quote["ends_at"], prop)) !=
                    get_datetime(day_pass.ends_at) or
                not all(isinstance(quote.get(field), str) and
                    quote[field] for field in ("product", "income_account",
                        "receivable_account", "tax_profile")) or
                not all(value.is_finite() for value in
                    (net, tax, total, unit_rate)) or
                net <= 0 or tax < 0 or total <= 0 or unit_rate <= 0 or
                net + tax != total):
            return None
        return {"product": quote["product"],
            "income_account": quote["income_account"],
            "receivable_account": quote["receivable_account"],
            "tax_profile": quote["tax_profile"],
            "unit_rate": _money(unit_rate), "net_amount": _money(net),
            "tax_amount": _money(tax), "total_amount": _money(total)}
    except (AttributeError, frappe.ValidationError, InvalidOperation,
            KeyError, OverflowError, TypeError, ValueError):
        return None


def _day_pass_receivable(prop, day_pass, sale):
    """Prove that the accepted sale and its posted PMS journal still agree."""
    if not sale or not day_pass.pms_receivable:
        return None
    receivable = frappe.db.get_value("HS PMS Receivable",
        day_pass.pms_receivable,
        ["name", "property", "company", "organization", "party",
         "reference", "currency", "amount", "net_amount", "tax_amount",
         "tax_profile", "receivable_account", "income_account",
         "tax_account", "journal", "status", "folio", "booking",
         "source_charge", "experience_order", "opening_source_name"],
        as_dict=True)
    journal = frappe.db.get_value("HS Journal", receivable.journal,
        ["property", "organization", "source_doctype", "source_name",
         "purpose", "status"], as_dict=True) if receivable and receivable.journal else None
    lines = frappe.get_all("HS Journal Line", filters={
        "parenttype": "HS Journal", "parent": receivable.journal},
        fields=["account", "party", "account_currency", "debit", "credit",
                "debit_in_account_currency", "credit_in_account_currency"],
        order_by="idx asc", limit_page_length=0) if journal else []
    try:
        total = Decimal(sale["total_amount"])
        net = Decimal(sale["net_amount"])
        tax = Decimal(sale["tax_amount"])
        if (not receivable or not journal or
                (receivable.property, receivable.company,
                 receivable.organization, receivable.party,
                 receivable.currency, receivable.status) !=
                    (prop.name, prop.company, prop.organization,
                     day_pass.customer, prop.currency, "Posted") or
                (receivable.receivable_account, receivable.income_account,
                 receivable.tax_profile) !=
                    (sale["receivable_account"], sale["income_account"],
                     sale["tax_profile"]) or
                any(receivable.get(field) for field in ("folio", "booking",
                    "source_charge", "experience_order", "opening_source_name")) or
                (Decimal(str(receivable.amount)),
                 Decimal(str(receivable.net_amount)),
                 Decimal(str(receivable.tax_amount))) != (total, net, tax) or
                (tax > 0 and not receivable.tax_account) or
                (journal.property, journal.organization,
                 journal.source_doctype, journal.source_name,
                 journal.purpose, journal.status) !=
                    (prop.name, prop.organization, "HS PMS Receivable",
                     receivable.reference, "Receivable", "Posted")):
            return None
        expected = [
            (receivable.receivable_account, receivable.party, total, Decimal(0)),
            (receivable.income_account, None, Decimal(0), net),
        ]
        if tax:
            expected.append((receivable.tax_account, None, Decimal(0), tax))
        actual = []
        for line in lines:
            debit = Decimal(str(line.debit))
            credit = Decimal(str(line.credit))
            if (line.account_currency != prop.currency or
                    Decimal(str(line.debit_in_account_currency)) != debit or
                    Decimal(str(line.credit_in_account_currency)) != credit or
                    min(debit, credit) < 0 or debit and credit):
                return None
            actual.append((line.account, line.party or None, debit, credit))
        if len(actual) != len(expected) or sorted(actual) != sorted(expected):
            return None
        from hospitality_suite.standalone_receivables import outstanding

        balance = outstanding(prop, receivable.name)
        if not balance.is_finite() or balance < 0 or balance > total:
            return None
        snapshot = {"receivable": receivable.name,
            "reference": receivable.reference,
            "journal": receivable.journal,
            "receivable_account": receivable.receivable_account,
            "income_account": receivable.income_account,
            "tax_account": receivable.tax_account or None,
            "net_amount": _money(net), "tax_amount": _money(tax),
            "total_amount": _money(total),
            "outstanding_amount": _money(balance)}
        return snapshot
    except (AttributeError, frappe.ValidationError, InvalidOperation,
            KeyError, TypeError, ValueError):
        return None


def _day_pass_fiscal(prop, day_pass, sale, financial):
    """Freeze the original invoice line and any credited part of this sale."""
    rows = frappe.get_all("HS PMS Fiscal Line", filters={
        "receivable": financial["receivable"]},
        fields=["name", "parent", "parenttype", "product", "income_account",
                "tax_account", "net_amount", "tax_amount", "total_amount"],
        order_by="parent asc,idx asc", limit_page_length=0)
    if not rows:
        return {"invoice": None, "credits": [], "credited_amount": "0"}
    names = sorted({row.parent for row in rows if row.parent})
    documents = {row.name: row for row in frappe.get_all(
        "HS PMS Fiscal Document", filters={"name": ["in", names]},
        fields=["name", "company", "property", "organization",
                "document_type", "document_number", "party", "currency",
                "status", "source_invoice", "journal"],
        limit_page_length=0)}
    invoice = None
    credits = []
    credited = credited_net = credited_tax = Decimal(0)
    try:
        for row in rows:
            doc = documents.get(row.parent)
            net = Decimal(str(row.net_amount))
            tax = Decimal(str(row.tax_amount))
            total = Decimal(str(row.total_amount))
            if (row.parenttype != "HS PMS Fiscal Document" or not doc or
                    (doc.company, doc.property, doc.organization, doc.party,
                     doc.currency, doc.status) !=
                        (prop.company, prop.name, prop.organization,
                         day_pass.customer, prop.currency, "Posted") or
                    row.product not in (None, "", sale["product"]) or
                    row.income_account != financial["income_account"] or
                    (row.tax_account or None) != financial["tax_account"] or
                    not all(value.is_finite() for value in (net, tax, total)) or
                    net < 0 or tax < 0 or total <= 0 or net + tax != total or
                    not doc.document_number):
                return None
            frozen = {"document": doc.name,
                "document_number": doc.document_number, "line": row.name,
                "source_product": row.product or None,
                "net_amount": _money(net), "tax_amount": _money(tax),
                "total_amount": _money(total)}
            if doc.document_type == "Invoice":
                if (invoice or doc.source_invoice or
                        (net, tax, total) !=
                            (Decimal(sale["net_amount"]),
                             Decimal(sale["tax_amount"]),
                             Decimal(sale["total_amount"]))):
                    return None
                invoice = frozen
            elif doc.document_type == "Credit Note":
                if not doc.source_invoice or not doc.journal:
                    return None
                credits.append({**frozen, "source_invoice": doc.source_invoice,
                    "journal": doc.journal})
                credited += total
                credited_net += net
                credited_tax += tax
            else:
                return None
        if (credits and not invoice or
                any(row["source_invoice"] != invoice["document"]
                    for row in credits) or
                credited > Decimal(sale["total_amount"]) or
                credited_net > Decimal(sale["net_amount"]) or
                credited_tax > Decimal(sale["tax_amount"])):
            return None
        return {"invoice": invoice, "credits": credits,
            "credited_amount": _money(credited)}
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError):
        return None


def _day_pass_settlements(prop, day_pass, sale, financial, fiscal):
    """Freeze applications and independently reconcile the receivable balance."""
    rows = frappe.get_all("HS PMS Allocation", filters={
        "receivable": financial["receivable"]},
        fields=["name", "company", "property", "organization", "receivable",
                "payment", "opening_credit", "opening_guarantee", "kind",
                "reverses", "business_date", "currency", "amount", "journal",
                "settlement_currency", "settled_amount"],
        order_by="creation asc,name asc", limit_page_length=0)
    applied = {
        "Direct", "Advance Applied", "Guarantee Applied",
        "Opening Credit Applied", "Opening Guarantee Applied"}
    reversed_kinds = {
        "Direct Reversed": "Direct",
        "Advance Reversed": "Advance Applied",
        "Guarantee Reversed": "Guarantee Applied",
        "Opening Credit Reversed": "Opening Credit Applied",
        "Opening Guarantee Reversed": "Opening Guarantee Applied"}
    by_name = {row.name: row for row in rows}
    payment_names = sorted({row.payment for row in rows if row.payment})
    journal_names = sorted({row.journal for row in rows if row.journal})
    payments = {row.name: row for row in frappe.get_all("HS Payment",
        filters={"name": ["in", payment_names]},
        fields=["name", "company", "property", "pms_party", "kind",
                "status", "method", "currency", "amount", "exchange_rate",
                "base_amount", "pms_counter_account", "pms_receivable",
                "pms_journal", "source_payment"],
        limit_page_length=0)} if payment_names else {}
    journals = {row.name: row for row in frappe.get_all("HS Journal",
        filters={"name": ["in", journal_names]},
        fields=["name", "property", "organization", "status"],
        limit_page_length=0)} if journal_names else {}
    reversed_amounts = {}
    frozen = []
    allocated = Decimal(0)
    try:
        if len(by_name) != len(rows):
            return None
        for row in rows:
            value = Decimal(str(row.amount))
            if ((row.company, row.property, row.organization, row.receivable,
                    row.currency) != (prop.company, prop.name, prop.organization,
                    financial["receivable"], prop.currency) or
                    row.kind not in applied | set(reversed_kinds) or
                    not value.is_finite() or value <= 0 or not row.journal or
                    not row.business_date):
                return None
            journal = journals.get(row.journal)
            if (not journal or (journal.property, journal.organization,
                    journal.status) !=
                    (prop.name, prop.organization, "Posted")):
                return None
            origin = by_name.get(row.reverses) if row.reverses else None
            if row.kind in reversed_kinds:
                if not origin or origin.kind != reversed_kinds[row.kind]:
                    return None
                reversed_amounts[origin.name] = (
                    reversed_amounts.get(origin.name, Decimal(0)) + value)
                allocated -= value
            elif row.reverses:
                return None
            else:
                allocated += value
            payment = payments.get(row.payment) if row.payment else None
            if row.kind.startswith("Opening "):
                if (row.payment or
                        bool(row.opening_credit) == bool(row.opening_guarantee) or
                        ("Credit" in row.kind) != bool(row.opening_credit)):
                    return None
            else:
                expected_kind = ("Payment" if row.kind == "Direct" else
                    "Refund" if row.kind == "Direct Reversed" else
                    "Advance" if row.kind.startswith("Advance") else "Guarantee")
                if (not payment or row.opening_credit or row.opening_guarantee or
                        (payment.company, payment.property, payment.pms_party,
                         payment.kind, payment.status) !=
                        (prop.company, prop.name, day_pass.customer,
                         expected_kind, "Posted")):
                    return None
                if row.kind in ("Direct", "Direct Reversed"):
                    if (payment.pms_receivable != financial["receivable"] or
                            payment.pms_journal != row.journal or
                            Decimal(str(payment.base_amount)) != value or
                            (row.kind == "Direct Reversed" and
                             payment.source_payment != origin.payment)):
                        return None
            frozen.append({"allocation": row.name, "kind": row.kind,
                "payment": row.payment or None,
                "payment_method": payment.method if payment else None,
                "payment_currency": payment.currency if payment else None,
                "payment_amount": (_money(payment.amount) if payment else None),
                "payment_exchange_rate": (_money(payment.exchange_rate)
                    if payment else None),
                "payment_base_amount": (_money(payment.base_amount)
                    if payment else None),
                "payment_counter_account": (payment.pms_counter_account
                    if payment else None),
                "payment_source": (payment.source_payment or None)
                    if payment else None,
                "opening_credit": row.opening_credit or None,
                "opening_guarantee": row.opening_guarantee or None,
                "reverses": row.reverses or None,
                "business_date": str(row.business_date), "amount": _money(value),
                "settlement_currency": row.settlement_currency or None,
                "settled_amount": (_money(row.settled_amount)
                    if row.settlement_currency else None),
                "journal": row.journal})
        if (any(value > Decimal(str(by_name[name].amount))
                for name, value in reversed_amounts.items()) or
                Decimal(sale["total_amount"]) - allocated -
                    Decimal(fiscal["credited_amount"]) !=
                    Decimal(financial["outstanding_amount"])):
            return None
        return {"allocations": frozen, "allocated_amount": _money(allocated)}
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError):
        return None


def _active_day_passes(prop, blockers):
    """Freeze live access and financial links while ERPNext return is unsupported."""
    snapshot_time = now_datetime()
    active = []
    for day_pass in _rows("HS Day Pass", prop,
            ["name", "customer", "guest", "people", "starts_at", "ends_at",
             "status", "pms_receivable", "sales_invoice", "payment",
             "quote_snapshot", "modified"], status="Issued"):
        try:
            expires_at = get_datetime(day_pass.ends_at) if day_pass.ends_at else None
        except (TypeError, ValueError):
            expires_at = None
        if not expires_at or expires_at > snapshot_time:
            frozen = dict(day_pass)
            frozen["quote_sha256"] = sha256(
                str(frozen.pop("quote_snapshot") or "").encode()).hexdigest()
            frozen["accepted_sale"] = _accepted_day_pass_quote(prop, day_pass)
            if not frozen["accepted_sale"]:
                blockers.append({"property": prop.name,
                    "code": "invalid_active_pms_day_pass_quote",
                    "source": day_pass.name})
            else:
                frozen["source_financial"] = _day_pass_receivable(
                    prop, day_pass, frozen["accepted_sale"])
                if not frozen["source_financial"]:
                    blockers.append({"property": prop.name,
                        "code": "invalid_active_pms_day_pass_receivable",
                        "source": day_pass.name})
                else:
                    frozen["source_financial_sha256"] = sha256(canonical(
                        frozen["source_financial"]).encode()).hexdigest()
                    frozen["source_fiscal"] = _day_pass_fiscal(prop,
                        day_pass, frozen["accepted_sale"],
                        frozen["source_financial"])
                    if frozen["source_fiscal"] is None:
                        blockers.append({"property": prop.name,
                            "code": "invalid_active_pms_day_pass_fiscal",
                            "source": day_pass.name})
                    else:
                        frozen["source_fiscal_sha256"] = sha256(canonical(
                            frozen["source_fiscal"]).encode()).hexdigest()
                        frozen["source_settlements"] = _day_pass_settlements(
                            prop, day_pass, frozen["accepted_sale"],
                            frozen["source_financial"], frozen["source_fiscal"])
                        if frozen["source_settlements"] is None:
                            blockers.append({"property": prop.name,
                                "code": "invalid_active_pms_day_pass_settlement",
                                "source": day_pass.name})
                        else:
                            frozen["source_settlements_sha256"] = sha256(
                                canonical(frozen["source_settlements"]).encode()
                            ).hexdigest()
                            if (_decimal(frozen["source_fiscal"]["credited_amount"])
                                    == _decimal(frozen["accepted_sale"]["total_amount"])):
                                blockers.append({"property": prop.name,
                                    "code": "fully_credited_active_pms_day_pass",
                                    "source": day_pass.name})
            active.append(frozen)
    return active


def _open_operations(prop, blockers):
    """Inventory live hotel work and reject links that cannot resume after cutover."""
    pending_parts = frappe.db.sql(
        "SELECT DISTINCT orders.name AS maintenance_order,parts.stock_entry "
        "FROM `tabHS Maintenance Order` orders "
        "JOIN `tabHS Maintenance Part` parts ON parts.parent=orders.name "
        "JOIN `tabHS Stock Movement` movement ON movement.name=parts.stock_entry "
        "WHERE orders.property=%s AND orders.company=%s "
        "AND orders.status!='Completed' AND parts.status='Issued' "
        "AND movement.property=%s AND movement.source_doctype='HS Maintenance Order'",
        (prop.name, prop.company, prop.name), as_dict=True)
    for part in pending_parts:
        blockers.append({"property": prop.name,
            "code": "open_pms_maintenance_parts_at_cutover",
            "source": part.maintenance_order, "stock_movement": part.stock_entry})
    active_day_passes = _active_day_passes(prop, blockers)
    bookings = _rows("HS Booking", prop,
        ["name", "status", "customer", "guest", "starts_at", "ends_at",
         "currency", "quote_snapshot"],
        status=["in", ["Hold", "Confirmed", "Checked In"]])
    stays = _rows("HS Stay", prop,
        ["name", "booking", "guest", "customer", "room", "rate",
         "starts_at", "ends_at", "currency", "status", "quote_snapshot",
         "service_entitlements"], status="Active")
    folios = _rows("HS Folio", prop,
        ["name", "booking", "stay", "customer", "currency", "status"],
        status="Open")
    experience_orders = _rows("HS Experience Order", prop,
        ["name", "experience", "booking", "stay", "customer", "item",
         "pms_product", "quantity", "unit_rate", "status", "currency",
         "amount", "accepted_net", "accepted_tax", "accepted_total",
         "income_account", "tax_account", "pms_receivable", "sales_invoice"],
        status=["in", ["Reserved", "Confirmed"]])
    for order in experience_orders:
        if not order.booking:
            product = frappe.db.get_value("HS Product", order.pms_product,
                ["property", "organization", "product_type", "active"],
                as_dict=True) if order.pms_product else None
            party = frappe.db.get_value("HS Party", order.customer,
                ["property", "organization", "party_type", "active"],
                as_dict=True) if order.customer else None
            income = frappe.db.get_value("HS Account", order.income_account,
                ["property", "organization", "root_type"], as_dict=True
                ) if order.income_account else None
            tax_account = frappe.db.get_value("HS Account", order.tax_account,
                ["property", "organization", "root_type"], as_dict=True
                ) if order.tax_account else None
            net = _decimal(order.accepted_net)
            tax = _decimal(order.accepted_tax)
            total = _decimal(order.accepted_total)
            valid = (product and party and income and
                (product.property, product.organization,
                 product.product_type, product.active) ==
                    (prop.name, prop.organization, "Service", 1) and
                (party.property, party.organization, party.active) ==
                    (prop.name, prop.organization, 1) and
                party.party_type in ("Customer", "Both") and
                (income.property, income.organization, income.root_type) ==
                    (prop.name, prop.organization, "Income") and
                (tax == 0 or tax_account and
                    (tax_account.property, tax_account.organization,
                     tax_account.root_type) ==
                        (prop.name, prop.organization, "Liability")) and
                (tax > 0 or not order.tax_account) and
                net > 0 and tax >= 0 and net + tax == total and
                _decimal(order.amount) in (net, total) and
                _decimal(order.quantity) > 0 and
                order.currency == prop.currency and not order.item and
                not order.stay and not order.pms_receivable and
                not order.sales_invoice and
                frappe.db.get_value("HS Experience", order.experience,
                    "property") == prop.name)
            if not valid:
                blockers.append({"property": prop.name,
                    "code": "pending_direct_experience_incomplete",
                    "source": order.name, "product": order.pms_product})
    if not (bookings or stays or folios):
        return {"bookings": [], "stays": [], "folios": [],
                "experience_orders": [dict(row) for row in experience_orders],
                "day_passes": active_day_passes}
    booking_names = [row.name for row in bookings]
    lines = frappe.get_all("HS Booking Room", filters={
        "parenttype": "HS Booking", "parent": ["in", booking_names]},
        fields=["name", "parent", "idx", "category", "room", "rate", "people"],
        order_by="parent asc,idx asc", limit_page_length=0) if booking_names else []
    allocations = _rows("HS Allocation", prop,
        ["name", "booking", "booking_room", "stay", "category", "room",
         "kind", "status", "starts_at", "ends_at", "quote_snapshot"],
         status="Active")
    parties = {row.name: row for row in _rows("HS Party", prop,
        ["name", "organization", "party_type", "active"])}
    categories = {row.name for row in _rows("HS Category", prop, ["name"])}
    rooms = {row.name: row for row in _rows("HS Room", prop,
        ["name", "category", "active"])}
    rates = {row.name for row in _rows("HS Rate", prop, ["name"])}
    products = {row.name for row in _rows("HS Product", prop, ["name"])}
    lines_by_booking = defaultdict(list)
    for line in lines:
        lines_by_booking[line.parent].append(line)
    allocations_by_booking = defaultdict(list)
    allocations_by_stay = defaultdict(list)
    for allocation in allocations:
        if allocation.booking:
            allocations_by_booking[allocation.booking].append(allocation)
        if allocation.stay:
            allocations_by_stay[allocation.stay].append(allocation)

    def block(code, source, **details):
        blockers.append({"property": prop.name, "code": code,
                         "source": source, **details})

    def valid_customer(name):
        party = parties.get(name)
        return bool(party and party.organization == prop.organization and
                    party.active and party.party_type in ("Customer", "Both"))

    def valid_span(start, end):
        try:
            return bool(start and end and get_datetime(start) < get_datetime(end))
        except (TypeError, ValueError):
            return False

    def embedded_products(value):
        found = set()
        if isinstance(value, dict):
            for key, nested in value.items():
                if (key in ("item", "lodging_item", "extra_hour_item", "timing_item",
                            "day_pass_item", "penalty_item") and
                        isinstance(nested, str) and nested in products):
                    found.add(nested)
                else:
                    found.update(embedded_products(nested))
        elif isinstance(value, list):
            for nested in value:
                found.update(embedded_products(nested))
        return found

    allocation_views = {}
    relevant_bookings = set(booking_names)
    relevant_stays = {row.name for row in stays}
    for allocation in allocations:
        if allocation.booking not in relevant_bookings and allocation.stay not in relevant_stays:
            continue
        try:
            quote = frappe.parse_json(allocation.quote_snapshot) if allocation.quote_snapshot else None
        except (TypeError, ValueError):
            quote = None
        embedded = sorted(embedded_products(quote))
        allocation_views[allocation.name] = {
            **{key: value for key, value in dict(allocation).items()
               if key != "quote_snapshot"},
            "embedded_products": embedded,
            "quote_sha256": sha256(str(allocation.quote_snapshot or "").encode()).hexdigest()}

    open_bookings = []
    for booking in bookings:
        booking_lines = lines_by_booking[booking.name]
        snapshot = booking.quote_snapshot
        try:
            quote = frappe.parse_json(snapshot) if snapshot else None
        except (TypeError, ValueError):
            quote = None
        quoted_lines = quote.get("lines") if isinstance(quote, dict) else None
        if not valid_customer(booking.customer):
            block("open_booking_invalid_customer", booking.name,
                  customer=booking.customer)
        if not valid_span(booking.starts_at, booking.ends_at):
            block("open_booking_invalid_span", booking.name)
        if booking.currency != prop.currency or not booking_lines or not isinstance(
                quoted_lines, list) or len(quoted_lines) != len(booking_lines):
            block("open_booking_incomplete_quote", booking.name,
                  room_count=len(booking_lines))
        embedded = sorted(embedded_products(quote))
        for index, line in enumerate(booking_lines):
            room = rooms.get(line.room) if line.room else None
            quoted = (quoted_lines[index] if isinstance(quoted_lines, list) and
                      index < len(quoted_lines) else None)
            if (line.category not in categories or line.rate not in rates or
                    (line.room and (not room or room.category != line.category or
                                    not room.active)) or (line.people or 0) < 1 or
                    not isinstance(quoted, dict) or
                    quoted.get("category") != line.category or
                    quoted.get("currency") != prop.currency or
                    not isinstance(quoted.get("rules"), dict) or
                    quoted["rules"].get("name") != line.rate):
                block("open_booking_invalid_room_line", booking.name,
                      line=line.name)
        if booking.status in ("Hold", "Confirmed"):
            active = allocations_by_booking[booking.name]
            by_line = {line.name: line for line in booking_lines}
            reserved = {row.booking_room for row in active
                        if row.kind == "Reservation"}
            if (len(active) != len(booking_lines) or
                    reserved != {line.name for line in booking_lines} or
                    any(row.kind != "Reservation" or
                        row.booking_room not in by_line or
                        row.category != by_line[row.booking_room].category or
                        (by_line[row.booking_room].room and
                         row.room != by_line[row.booking_room].room) or
                        not valid_span(row.starts_at, row.ends_at) or
                        (valid_span(booking.starts_at, booking.ends_at) and
                         (get_datetime(row.starts_at) != get_datetime(booking.starts_at) or
                          get_datetime(row.ends_at) != get_datetime(booking.ends_at)))
                        for row in active)):
                block("open_booking_allocation_mismatch", booking.name,
                      allocation_count=len(active), room_count=len(booking_lines))
        open_bookings.append({"name": booking.name, "status": booking.status,
            "customer": booking.customer, "guest": booking.guest,
            "starts_at": str(booking.starts_at) if booking.starts_at else None,
            "ends_at": str(booking.ends_at) if booking.ends_at else None,
            "currency": booking.currency,
            "quote_sha256": sha256(str(snapshot or "").encode()).hexdigest(),
            "embedded_products": embedded,
            "rooms": [dict(line) for line in booking_lines],
            "allocations": [allocation_views[row.name]
                            for row in allocations_by_booking[booking.name]]})

    open_stays = []
    for stay in stays:
        booking = frappe.db.get_value("HS Booking", stay.booking,
            ["property", "customer"], as_dict=True) if stay.booking else None
        guest = frappe.db.get_value("HS Guest", stay.guest, "property") if stay.guest else None
        room = rooms.get(stay.room)
        active = [row for row in allocations_by_stay[stay.name]
                  if row.kind == "Stay" and row.room == stay.room]
        try:
            quote = frappe.parse_json(stay.quote_snapshot) if stay.quote_snapshot else None
            entitlements = frappe.parse_json(stay.service_entitlements) if stay.service_entitlements else []
        except (TypeError, ValueError):
            quote = entitlements = None
        if not isinstance(quote, dict) or not isinstance(quote.get("rules"), dict):
            block("active_stay_incomplete_quote", stay.name)
        embedded = sorted(embedded_products(quote) | embedded_products(entitlements))
        if (not booking or booking.property != prop.name or
                booking.customer != stay.customer or not valid_customer(stay.customer) or
                guest != prop.name or not room or not room.active or
                stay.rate not in rates or stay.currency != prop.currency or
                not valid_span(stay.starts_at, stay.ends_at) or not active):
            block("active_stay_incomplete", stay.name)
        if not any(row.stay == stay.name for row in folios):
            block("active_stay_without_open_folio", stay.name)
        open_stays.append({**{key: value for key, value in dict(stay).items()
                              if key not in ("quote_snapshot", "service_entitlements")},
            "quote_sha256": sha256(str(stay.quote_snapshot or "").encode()).hexdigest(),
            "entitlements_sha256": sha256(str(stay.service_entitlements or "").encode()).hexdigest(),
            "embedded_products": embedded,
            "allocations": [allocation_views[row.name]
                            for row in allocations_by_stay[stay.name]]})

    open_folios = []
    for folio in folios:
        booking = frappe.db.get_value("HS Booking", folio.booking,
            ["property", "customer"], as_dict=True) if folio.booking else None
        stay = frappe.db.get_value("HS Stay", folio.stay,
            ["property", "booking", "customer"], as_dict=True) if folio.stay else None
        if (not valid_customer(folio.customer) or folio.currency != prop.currency or
                not (booking or stay) or
                (booking and (booking.property != prop.name or
                              booking.customer != folio.customer)) or
                (stay and (stay.property != prop.name or
                           stay.customer != folio.customer or
                           (folio.booking and stay.booking != folio.booking)))):
            block("open_folio_invalid_link", folio.name)
        open_folios.append(dict(folio))
    return {"bookings": open_bookings, "stays": open_stays,
            "folios": open_folios,
            "experience_orders": [dict(row) for row in experience_orders],
            "day_passes": active_day_passes}


def _open_purchase_orders(prop, blockers):
    """Freeze the unreceived portion of approved PMS orders for ERPNext."""
    from hospitality_suite.standalone_purchase_orders import allocation, progress

    open_orders = []
    for order in _rows("HS PMS Purchase Order", prop,
            ["name", "reference", "supplier", "currency", "status",
             "requested_by", "approved_by", "expected_date", "notes",
             "payable_account", "tax_account"],
            status=["in", ["Pending", "Approved"]]):
        lines = frappe.get_all("HS PMS Purchase Order Line", filters={
            "parenttype": "HS PMS Purchase Order", "parent": order.name},
            fields=["name", "product", "warehouse", "quantity", "amount",
                    "recoverable_tax"],
            order_by="idx asc", limit_page_length=0)
        remaining = []
        for line in lines:
            received = progress(prop, line.name)
            quantity = _decimal(line.quantity) - received
            if quantity < 0:
                blockers.append({"code": "over_received_pms_purchase_order",
                    "property": prop.name, "source": order.name, "line": line.name})
                continue
            if quantity:
                gross, tax = allocation(line, received, quantity)
                remaining.append({"line": line.name, "product": line.product,
                    "warehouse": line.warehouse, "quantity": _money(quantity),
                    "gross": _money(gross), "recoverable_tax": _money(tax),
                    "net": _money(gross - tax)})
        summary = {"property": prop.name, "source": order.name,
            "reference": order.reference, "supplier": order.supplier,
            "currency": order.currency, "status": order.status,
            "requested_by": order.requested_by,
            "approved_by": order.approved_by,
            "expected_date": str(order.expected_date) if order.expected_date else None,
            "notes": order.notes or "", "payable_account": order.payable_account,
            "tax_account": order.tax_account, "remaining": remaining}
        open_orders.append(summary)
        if order.status == "Pending":
            blockers.append({"code": "unapproved_pms_purchase_order", **summary})
        elif (not lines or not order.approved_by or
                order.approved_by == order.requested_by or
                not frappe.db.get_value("HS Party", order.supplier, "active")):
            blockers.append({"code": "invalid_approved_pms_purchase_order", **summary})
    return open_orders


def _scope_integrity():
    """Find foreign-company and orphaned scoped records before mapping."""
    blockers = []
    for doctype in SCOPED:
        if doctype == "HS Property":
            continue
        table = f"`tab{doctype}`"
        mismatched = frappe.db.sql(
            f"SELECT d.name,d.property,d.company,p.company AS expected_company "
            f"FROM {table} d LEFT JOIN `tabHS Property` p ON p.name=d.property "
            "WHERE p.name IS NULL OR d.company IS NULL OR d.company!=p.company "
            "ORDER BY d.name", as_dict=True)
        for row in mismatched:
            blockers.append({"property": row.property,
                             "code": "scoped_company_mismatch" if row.expected_company
                                     else "scoped_property_missing",
                             "doctype": doctype, "source": row.name,
                             "record_company": row.company})
    return blockers


def _property(prop, blockers):
    own = []
    organization = frappe.db.get_value("HS Organization", prop.organization,
        ["name", "base_currency", "active"], as_dict=True)
    if (not organization or not organization.active or
            organization.base_currency != prop.currency or prop.company != prop.organization):
        own.append({"property": prop.name, "code": "invalid_legal_entity"})
    for field, _message in prop._get_missing_mandatory_fields():
        own.append({"property": prop.name,
                    "code": "missing_property_required_field", "field": field})
    for field, minimum, maximum in (("cleaning_minutes", 0, None),
                                    ("hold_minutes", 1, 1440),
                                    ("schedule_grace_minutes", 0, None),
                                    ("schedule_rounding_minutes", 1, None),
                                    ("checkout_quote_minutes", 1, 60)):
        value = prop.get(field)
        if (value is None or cint(value) < minimum or
                (maximum is not None and cint(value) > maximum)):
            own.append({"property": prop.name,
                        "code": "invalid_property_timing_setting", "field": field})
    ledger, by_account, by_party = _ledger(prop)
    listed_accounts = {row["name"] for row in ledger["accounts"]}
    for account_row in ledger["accounts"]:
        if account_row["is_group"] and _decimal(account_row["balance"]):
            own.append({"property": prop.name, "code": "group_account_has_balance",
                        "account": account_row["name"],
                        "balance": account_row["balance"]})
    for account_name in sorted(set(by_account) - listed_accounts):
        own.append({"property": prop.name, "code": "posted_account_outside_property",
                    "account": account_name, "balance": _money(by_account[account_name])})
    if _decimal(ledger["debit"]) != _decimal(ledger["credit"]):
        own.append({"property": prop.name, "code": "unbalanced_ledger",
            "difference": _money(_decimal(ledger["debit"]) - _decimal(ledger["credit"]))})
    receivables = _receivables(prop, by_account, by_party, own)
    payables = _payables(prop, by_account, by_party, own)
    positions = _stock(prop, by_account, own)
    deposits = _open_deposits(prop, own)
    open_operations = _open_operations(prop, own)
    open_purchase_orders = _open_purchase_orders(prop, own)
    petty_account = prop.petty_cash_account
    if petty_account:
        from hospitality_suite.standalone_petty_cash import operational_balance
        difference = by_account[petty_account] - operational_balance(prop)
        if difference:
            own.append({"property": prop.name, "code": "petty_cash_mismatch",
                "account": petty_account, "difference": _money(difference)})
    open_shifts = _rows("HS Shift", prop, ["name", "status", "cashier"],
        status=["in", ["Open", "Review"]])
    if open_shifts:
        own.append({"property": prop.name, "code": "unclosed_cash_shifts",
            "sources": [row.name for row in open_shifts]})
    current_postings = frappe.db.count("HS Journal", {"property": prop.name,
        "business_date": prop.business_date, "status": "Posted"})
    if current_postings:
        own.append({"property": prop.name, "code": "postings_on_cutover_day",
            "count": current_postings})
    previous = str(add_days(prop.business_date, -1))
    last_close = frappe.db.get_value("HS Daily Close", {"property": prop.name,
        "status": "Closed", "business_date": ["<", prop.business_date]},
        "business_date", order_by="business_date desc")
    if frappe.db.exists("HS Journal", {"property": prop.name}) and str(last_close) != previous:
        own.append({"property": prop.name, "code": "previous_day_not_closed",
            "expected": previous, "actual": str(last_close) if last_close else None})
    cash = [{"account": row["name"], "currency": row["account_currency"],
        "base_balance": row["balance"], "original_balance": row["original_balance"]}
        for row in ledger["accounts"] if row["is_cash"] or row["is_bank"]]
    result = {"property": prop.name, "organization": prop.organization,
        "currency": prop.currency, "business_date": str(prop.business_date),
        "property_receivable_account": prop.receivable_account,
        "property_petty_cash_account": prop.petty_cash_account,
        "property_petty_cash_responsible": prop.petty_cash_responsible,
        "property_petty_cash_overage_account": prop.petty_cash_overage_account,
        "property_petty_cash_shortage_account": prop.petty_cash_shortage_account,
        "pms_linen_operating_warehouse": prop.get("pms_linen_operating_warehouse"),
        "pms_linen_laundry_warehouse": prop.get("pms_linen_laundry_warehouse"),
        "pms_linen_clearing_account": prop.get("pms_linen_clearing_account"),
        "ledger": ledger, "cash_and_bank": cash, "open_receivables": receivables,
        "open_payables": payables, "stock_positions": positions,
        "open_deposits": deposits,
        "open_operations": open_operations,
        "open_purchase_orders": open_purchase_orders,
        "open_shifts": [dict(row) for row in open_shifts], "blockers": own,
        "mapping_requirements": {"accounts": [row["name"] for row in ledger["accounts"]],
            "parties": [row.name for row in _rows("HS Party", prop, ["name"])],
            "products": [row.name for row in _rows("HS Product", prop, ["name"])],
            "warehouses": [row.name for row in _rows("HS Warehouse", prop, ["name"])]}}
    blockers.extend(own)
    return result


def preflight():
    """Produce a locked, deterministic source reconciliation, never a cutover."""
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede revisar la migración"),
                     frappe.PermissionError)
    if provider() != "pms":
        frappe.throw(_("El sitio no conserva autoridad contable PMS"))
    names = [row.name for row in frappe.db.sql(
        "SELECT name FROM `tabHS Property` ORDER BY name FOR UPDATE", as_dict=True)]
    blockers = _scope_integrity()
    if not names:
        blockers.append({"code": "no_properties"})
    properties = [_property(frappe.get_doc("HS Property", name), blockers)
                  for name in names]
    source = {"schema_version": 1, "provider": "PMS", "properties": properties,
        "blockers": blockers}
    return {**source, "generated_at": str(now_datetime()),
        "source_sha256": sha256(canonical(source).encode()).hexdigest(),
        "ready_for_mapping": not blockers,
        "cutover_performed": False}
