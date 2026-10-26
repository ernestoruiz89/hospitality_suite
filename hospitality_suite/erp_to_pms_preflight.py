"""Read-only source inventory for a future ERPNext-to-PMS cutover.

This report never changes the active book. It cannot authorize a reverse
cutover until open operations and all target postings are reconciled.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.schema import STANDARD_SCOPED
from hospitality_suite.security import is_system
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


ACCOUNT_SETTINGS = ("income_account", "expense_account", "receivable_account",
    "guarantee_account", "cash_transfer_account", "petty_cash_account",
    "petty_cash_overage_account", "petty_cash_shortage_account")
ITEM_SETTINGS = ("lodging_item", "extra_hour_item", "day_pass_item",
    "agent_commission_item", "penalty_item", "timing_item")
WAREHOUSE_SETTINGS = ("warehouse", "laundry_warehouse")
MAX_EVIDENCE_BYTES = 25 * 1024 * 1024


def _private_evidence(doctype, document_name, url):
    """Read an attachment scoped to one source record for the source hash."""
    if doctype not in ("HS Incident", "HS Maintenance Order"):
        raise ValueError("unsupported evidence owner")
    if not isinstance(url, str) or not url.startswith("/private/files/"):
        raise ValueError("evidence is not private")
    files = frappe.get_all("File", filters={"file_url": url,
        "is_private": 1, "attached_to_doctype": doctype,
        "attached_to_name": document_name}, fields=["name", "file_name"],
        order_by="name asc", limit_page_length=0)
    if not files:
        raise ValueError("evidence has no private File attachment")
    if len({row.file_name for row in files}) != 1:
        raise ValueError("evidence has conflicting filenames")
    attachment = frappe.get_doc("File", files[0].name)
    filename = attachment.file_name
    if (not isinstance(filename, str) or not filename or
            Path(filename).name != filename or len(filename) > 180):
        raise ValueError("evidence filename is invalid")
    root = Path(frappe.get_site_path("private", "files")).resolve()
    path = Path(attachment.get_full_path()).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("evidence file is missing")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise ValueError("evidence file size is invalid")
    content = path.read_bytes()
    return {"evidence_file_name": filename,
        "evidence_size": len(content),
        "evidence_sha256": sha256(content).hexdigest()}, content


def _incident_evidence(incident_name, url):
    return _private_evidence("HS Incident", incident_name, url)


def _day_pass_financial(prop, row, blockers):
    """Freeze native sale and settlement facts before a live pass can move."""
    source = row["name"]
    invoice = frappe.db.get_value("Sales Invoice", row.get("sales_invoice"),
        ["name", "company", "hs_property", "customer", "currency",
         "net_total", "total_taxes_and_charges", "grand_total",
         "outstanding_amount", "debit_to", "docstatus",
         "is_return"],
        as_dict=True) if row.get("sales_invoice") else None
    service = frappe.db.get_value("HS Service Request", row.get("service"),
        ["name", "company", "property", "customer", "item", "quantity",
         "status", "stock_entry", "sales_invoice"],
        as_dict=True) if row.get("service") else None
    payment = frappe.db.get_value("HS Payment", row.get("payment"),
        ["name", "company", "property", "customer", "service",
         "sales_invoice", "payment_entry", "kind", "status", "currency",
         "amount", "base_amount"],
        as_dict=True) if row.get("payment") else None
    entry = frappe.db.get_value("Payment Entry", payment.payment_entry,
        ["name", "company", "party", "payment_type", "docstatus"],
        as_dict=True) if payment and payment.payment_entry else None
    references = frappe.get_all("Payment Entry Reference", filters={
        "parent": entry.name, "parenttype": "Payment Entry"},
        fields=["reference_doctype", "reference_name", "allocated_amount"],
        limit_page_length=0) if entry else []
    items = frappe.get_all("Sales Invoice Item", filters={
        "parent": invoice.name, "parenttype": "Sales Invoice"},
        fields=["item_code", "qty"], limit_page_length=0) if invoice else []
    try:
        valid = (row.get("status") == "Issued" and not row.get(
            "pms_receivable") and not row.get("quote_snapshot") and
            int(row.get("people") or 0) > 0 and invoice and service and
            payment and entry and invoice.docstatus == 1 and not invoice.is_return and
            (invoice.company, invoice.hs_property, invoice.customer,
             invoice.currency) == (prop.company, prop.name, row["customer"],
                                   prop.currency) and
            Decimal(str(invoice.grand_total)) > 0 and
            Decimal(str(invoice.outstanding_amount)) == 0 and
            len(items) == 1 and items[0].item_code == prop.day_pass_item and
            Decimal(str(items[0].qty)) == Decimal(str(row["people"])) and
            (service.company, service.property, service.customer,
             service.item, service.status, service.sales_invoice) ==
                (prop.company, prop.name, row["customer"],
                 prop.day_pass_item, "Delivered", invoice.name) and
            not service.stock_entry and
            Decimal(str(service.quantity)) == Decimal(str(row["people"])) and
            (payment.company, payment.property, payment.customer,
             payment.service, payment.sales_invoice, payment.kind,
             payment.status) == (prop.company, prop.name, row["customer"],
                                 service.name, invoice.name, "Payment", "Posted") and
            Decimal(str(payment.amount)) > 0 and
            Decimal(str(payment.base_amount)) ==
                Decimal(str(invoice.grand_total)) and
            entry.company == prop.company and entry.party == row["customer"] and
            entry.payment_type == "Receive" and entry.docstatus == 1 and
            len(references) == 1 and
            (references[0].reference_doctype,
             references[0].reference_name) == ("Sales Invoice", invoice.name) and
            Decimal(str(references[0].allocated_amount)) ==
                Decimal(str(invoice.grand_total)) and
            not frappe.db.exists("HS Payment", {"property": prop.name,
                "source_payment": payment.name, "kind": "Refund",
                "status": "Posted"}))
    except (InvalidOperation, TypeError, ValueError):
        valid = False
    if not valid:
        blockers.append({"property": prop.name,
            "code": "invalid_active_day_pass_financial_graph",
            "source": source})
        return
    gl = frappe.get_all("GL Entry", filters={"voucher_type": "Sales Invoice",
        "voucher_no": invoice.name, "company": prop.company,
        "is_cancelled": 0},
        fields=["name", "account", "party_type", "party", "debit", "credit",
            "account_currency", "debit_in_account_currency",
            "credit_in_account_currency"],
        order_by="name asc", limit_page_length=0)
    lines = [{key: _number(line[key]) if key in ("debit", "credit",
              "debit_in_account_currency", "credit_in_account_currency")
              else line[key] for key in ("account", "party_type", "party",
                "debit", "credit", "account_currency",
                "debit_in_account_currency", "credit_in_account_currency")}
             for line in gl]
    account_names = {line["account"] for line in lines}
    account_rows = {row.name: row for row in frappe.get_all("Account",
        filters={"name": ["in", sorted(account_names)]},
        fields=["name", "company", "root_type", "account_type",
                "account_currency", "is_group", "disabled"],
        limit_page_length=0)} if account_names else {}
    for line in lines:
        source_account = account_rows.get(line["account"])
        line["root_type"] = source_account.root_type if source_account else None
        line["account_type"] = (source_account.account_type or "General") if source_account else None
    debit = sum((Decimal(line["debit"]) for line in lines), Decimal(0))
    credit = sum((Decimal(line["credit"]) for line in lines), Decimal(0))
    receivable_lines = [line for line in lines if line["account"] ==
        invoice.debit_to and line["party_type"] == "Customer" and
        line["party"] == row["customer"]]
    receivable_total = sum((Decimal(line["debit"]) -
        Decimal(line["credit"]) for line in receivable_lines), Decimal(0))
    net = sum((Decimal(line["credit"]) - Decimal(line["debit"])
        for line in lines if line["root_type"] == "Income"), Decimal(0))
    tax = sum((Decimal(line["credit"]) - Decimal(line["debit"])
        for line in lines if line["root_type"] == "Liability"), Decimal(0))
    if (len(lines) < 2 or debit != credit or
            debit < Decimal(str(invoice.grand_total)) or
            receivable_total != Decimal(str(invoice.grand_total)) or
            net < 0 or tax < 0 or net + tax != receivable_total or
            net != Decimal(str(invoice.net_total)) or
            tax != Decimal(str(invoice.total_taxes_and_charges)) or
            any(not account_rows.get(line["account"]) or
                account_rows[line["account"]].company != prop.company or
                account_rows[line["account"]].is_group or
                account_rows[line["account"]].disabled or
                (account_rows[line["account"]].account_currency or prop.currency) != prop.currency or
                (line["account"] == invoice.debit_to and
                    (line["root_type"] != "Asset" or
                     line["account_type"] != "Receivable")) or
                (line["account"] != invoice.debit_to and
                    (line["root_type"] not in ("Income", "Liability") or
                     line["party_type"] or line["party"]))
                for line in lines) or
            any(line["party_type"] not in (None, "Customer") or
                line["party_type"] == "Customer" and
                line["party"] != row["customer"] for line in lines) or
            any(line["account_currency"] != prop.currency or
                Decimal(line["debit_in_account_currency"]) !=
                    Decimal(line["debit"]) or
                Decimal(line["credit_in_account_currency"]) !=
                    Decimal(line["credit"]) or
                min(Decimal(line["debit"]), Decimal(line["credit"])) < 0 or
                (Decimal(line["debit"]) > 0 and
                 Decimal(line["credit"]) > 0) or
                (Decimal(line["debit"]) == 0 and
                 Decimal(line["credit"]) == 0)
                for line in lines)):
        blockers.append({"property": prop.name,
            "code": "invalid_active_day_pass_invoice_gl", "source": source})
        return
    snapshot = {"invoice": invoice.name,
        "invoice_net": _number(invoice.net_total),
        "invoice_tax": _number(invoice.total_taxes_and_charges),
        "invoice_total": _number(invoice.grand_total),
        "receivable_account": invoice.debit_to,
        "invoice_currency": invoice.currency,
        "payment": payment.name,
        "payment_entry": entry.name,
        "payment_currency": payment.currency,
        "payment_amount": _number(payment.amount),
        "payment_base_amount": _number(payment.base_amount),
        "service": service.name,
        "invoice_gl": lines}
    row["source_financial"] = snapshot
    row["source_financial_sha256"] = sha256(canonical(snapshot).encode()).hexdigest()


def _number(value):
    return format(Decimal(str(value or 0)).normalize(), "f")


def _open_invoices(prop, doctype, party_field, account_field, blockers):
    visit_fields = (",hs_folio AS folio,hs_stay AS stay,hs_booking AS booking"
                    if doctype == "Sales Invoice" else "")
    rows = frappe.db.sql(
        f"SELECT name,{party_field} AS party,{account_field} AS account,"
        "party_account_currency AS account_currency,currency,posting_date,"
        "due_date,outstanding_amount,is_return" + visit_fields +
        " FROM `tab" + doctype + "` "
        "WHERE hs_property=%s AND company=%s AND docstatus=1 "
        "AND outstanding_amount!=0 ORDER BY name",
        (prop.name, prop.company), as_dict=True)
    ledger = defaultdict(list)
    for start in range(0, len(rows), 500):
        names = [row.name for row in rows[start:start + 500]]
        placeholders = ",".join(["%s"] * len(names))
        entries = frappe.db.sql(
            "SELECT against_voucher_no,account,party_type,party,account_currency,"
            "SUM(amount) AS base_amount,"
            "SUM(amount_in_account_currency) AS account_amount "
            "FROM `tabPayment Ledger Entry` WHERE company=%s "
            "AND against_voucher_type=%s AND delinked=0 "
            f"AND against_voucher_no IN ({placeholders}) "
            "GROUP BY against_voucher_no,account,party_type,party,account_currency",
            (prop.company, doctype, *names), as_dict=True)
        for entry in entries:
            ledger[entry.against_voucher_no].append(entry)
    folios = {}
    if doctype == "Sales Invoice":
        names = sorted({row.folio for row in rows if row.folio})
        if names:
            folios = {row.name: row for row in frappe.get_all("HS Folio",
                filters={"name": ["in", names]},
                fields=["name", "property", "company", "customer", "currency",
                        "status"], limit_page_length=0)}
    result = []
    for row in rows:
        account_currency = row.account_currency or prop.currency
        item = {**dict(row), "posting_date": str(row.posting_date),
            "due_date": str(row.due_date) if row.due_date else None,
            "outstanding_amount": _number(row.outstanding_amount),
            "account_currency": account_currency}
        matching = [entry for entry in ledger[row.name]
                    if entry.account == row.account and entry.party == row.party and
                    entry.party_type == ("Customer" if doctype == "Sales Invoice"
                                         else "Supplier") and
                    entry.account_currency == account_currency]
        if (len(ledger[row.name]) != 1 or len(matching) != 1 or
                Decimal(str(matching[0].account_amount or 0)) !=
                    Decimal(item["outstanding_amount"]) or
                not Decimal(str(matching[0].base_amount or 0))):
            blockers.append({"property": prop.name,
                "code": "open_invoice_payment_ledger_mismatch",
                "doctype": doctype, "source": row.name})
        else:
            item["base_outstanding_amount"] = _number(matching[0].base_amount)
        if doctype == "Sales Invoice" and row.folio:
            folio = folios.get(row.folio)
            item.update({"folio_property": folio.property if folio else None,
                "folio_company": folio.company if folio else None,
                "folio_customer": folio.customer if folio else None,
                "folio_currency": folio.currency if folio else None,
                "folio_status": folio.status if folio else None})
        result.append(item)
    return result


def _warehouses_and_stock(prop, blockers):
    names = set(frappe.get_all("Warehouse", filters={"hs_property": prop.name,
        "company": prop.company, "is_group": 0}, pluck="name"))
    for name in (prop.warehouse, prop.laundry_warehouse):
        if not name:
            continue
        row = frappe.db.get_value("Warehouse", name,
            ["company", "hs_property", "is_group", "disabled"], as_dict=True)
        if (not row or row.company != prop.company or row.hs_property != prop.name or
                row.is_group or row.disabled):
            blockers.append({"property": prop.name, "code": "warehouse_scope_invalid",
                             "warehouse": name})
        else:
            names.add(name)
    if not names:
        return {"warehouses": [], "positions": []}
    positions = frappe.get_all("Bin", filters={"warehouse": ["in", sorted(names)]},
        fields=["item_code", "warehouse", "actual_qty",
        "stock_value"], order_by="warehouse asc,item_code asc", limit_page_length=0)
    result = []
    for row in positions:
        quantity = Decimal(str(row.actual_qty or 0))
        value = Decimal(str(row.stock_value or 0))
        if not quantity and not value:
            continue
        if quantity < 0:
            blockers.append({"property": prop.name, "code": "negative_stock",
                             "warehouse": row.warehouse, "item": row.item_code})
        if not quantity and value:
            blockers.append({"property": prop.name, "code": "stock_value_without_quantity",
                             "warehouse": row.warehouse, "item": row.item_code,
                             "value": _number(value)})
        result.append({"item": row.item_code, "warehouse": row.warehouse,
                       "quantity": _number(quantity), "stock_value": _number(value)})
    return {"warehouses": sorted(names), "positions": result}


def _ledger(prop, blockers):
    balances = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
    matched_entries = 0
    for doctype in STANDARD_SCOPED:
        rows = frappe.db.sql(
            "SELECT g.account,g.cost_center,g.party_type,g.party,"
            "SUM(g.debit) AS debit,SUM(g.credit) AS credit,"
            "SUM(g.debit_in_account_currency-g.credit_in_account_currency) AS original,"
            "COUNT(*) AS entries FROM `tabGL Entry` g "
            f"JOIN `tab{doctype}` d ON d.name=g.voucher_no "
            "WHERE g.voucher_type=%s AND g.company=%s AND g.is_cancelled=0 "
            "AND d.docstatus=1 AND d.company=%s AND d.hs_property=%s "
            "GROUP BY g.account,g.cost_center,g.party_type,g.party",
            (doctype, prop.company, prop.company, prop.name), as_dict=True)
        for row in rows:
            key = (row.account, row.cost_center, row.party_type, row.party)
            balance = balances[key]
            balance[0] += Decimal(str(row.debit or 0))
            balance[1] += Decimal(str(row.credit or 0))
            balance[2] += Decimal(str(row.original or 0))
            matched_entries += int(row.entries)
    debit = sum((amounts[0] for amounts in balances.values()), Decimal(0))
    credit = sum((amounts[1] for amounts in balances.values()), Decimal(0))
    if debit != credit:
        blockers.append({"property": prop.name, "code": "unbalanced_property_gl",
                         "difference": _number(debit-credit)})
    accounts = sorted({key[0] for key in balances})
    account_rows = {row.name: row for row in frappe.get_all("Account",
        filters={"name": ["in", accounts]},
        fields=["name", "company", "root_type", "account_type", "account_currency",
                "is_group", "disabled"], limit_page_length=0)} if accounts else {}
    for account in accounts:
        row = account_rows.get(account)
        if not row or row.company != prop.company or row.is_group or row.disabled:
            blockers.append({"property": prop.name, "code": "invalid_gl_account",
                             "account": account})
    lines = []
    for (account, center, party_type, party), amounts in sorted(
            balances.items(), key=lambda item: tuple(value or "" for value in item[0])):
        row = account_rows.get(account)
        lines.append({"account": account, "cost_center": center,
                      "party_type": party_type, "party": party,
                      "root_type": row.root_type if row else None,
                      "account_type": row.account_type if row else None,
                      "account_currency": (row.account_currency or prop.currency) if row else None,
                      "debit": _number(amounts[0]), "credit": _number(amounts[1]),
                      "original_balance": _number(amounts[2])})
    return {"debit": _number(debit), "credit": _number(credit),
            "matched_entries": matched_entries, "lines": lines}


def _stock_ledger_valuation(prop, ledger, stock, blockers):
    """Reject hotel scope that cannot carry its own stock balance to PMS."""
    if any(row.get("property") == prop.name and
           row.get("code") == "warehouse_scope_invalid" for row in blockers):
        return
    from erpnext.stock import get_warehouse_account_map

    warehouse_accounts = get_warehouse_account_map(prop.company)
    stock_by_account = defaultdict(Decimal)
    for warehouse in stock["warehouses"]:
        account = warehouse_accounts.get(warehouse)
        if not account or not account.account:
            blockers.append({"property": prop.name,
                "code": "property_stock_account_unresolved",
                "warehouse": warehouse})
        else:
            stock_by_account.setdefault(account.account, Decimal(0))
    for row in stock["positions"]:
        account = warehouse_accounts.get(row["warehouse"])
        if account and account.account:
            stock_by_account[account.account] += Decimal(str(row["stock_value"]))
    ledger_by_account = defaultdict(Decimal)
    for row in ledger["lines"]:
        ledger_by_account[row["account"]] += (
            Decimal(str(row["debit"])) - Decimal(str(row["credit"])))
    stock_accounts = {row["account"] for row in ledger["lines"]
        if row.get("account_type") == "Stock"}
    mismatches = [(account, value, ledger_by_account[account])
        for account, value in sorted(stock_by_account.items())
        if value != ledger_by_account[account]]
    mismatches.extend((account, Decimal(0), ledger_by_account[account])
        for account in sorted(stock_accounts - set(stock_by_account))
        if ledger_by_account[account])
    if not mismatches:
        return
    transfers = frappe.db.sql(
        "SELECT e.name AS voucher,e.hs_property AS voucher_property,"
        "d.s_warehouse AS source_warehouse,s.hs_property AS source_property,"
        "d.t_warehouse AS target_warehouse,t.hs_property AS target_property,"
        "d.item_code,d.qty,d.basic_amount "
        "FROM `tabStock Entry Detail` d "
        "JOIN `tabStock Entry` e ON e.name=d.parent "
        "JOIN `tabWarehouse` s ON s.name=d.s_warehouse "
        "JOIN `tabWarehouse` t ON t.name=d.t_warehouse "
        "WHERE e.docstatus=1 AND e.company=%s "
        "AND s.hs_property IS NOT NULL AND t.hs_property IS NOT NULL "
        "AND s.hs_property!=t.hs_property "
        "AND (s.hs_property=%s OR t.hs_property=%s) "
        "ORDER BY e.name,d.idx LIMIT 20",
        (prop.company, prop.name, prop.name), as_dict=True)
    sample = [{"voucher": row.voucher,
        "voucher_property": row.voucher_property,
        "source_warehouse": row.source_warehouse,
        "source_property": row.source_property,
        "target_warehouse": row.target_warehouse,
        "target_property": row.target_property,
        "item": row.item_code, "quantity": _number(row.qty),
        "basic_amount": _number(row.basic_amount)}
        for row in transfers]
    for account, stock_value, ledger_balance in mismatches:
        blockers.append({"property": prop.name,
            "code": "property_stock_gl_mismatch",
            "account": account,
            "stock_value": _number(stock_value),
            "ledger_balance": _number(ledger_balance),
            "difference": _number(stock_value - ledger_balance),
            "cross_property_transfers": sample})


def _company_gl_coverage(company, properties, ledgers, blockers):
    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabGL Entry` WHERE company=%s AND is_cancelled=0",
        company, as_list=True)[0][0]
    matched = sum(ledgers[name]["matched_entries"] for name in properties)
    if matched != total:
        blockers.append({"company": company, "code": "unattributed_company_gl",
                         "entries": int(total-matched),
                         "sample": _unattributed_gl_sample(company, properties)})
    return {"company": company, "total_entries": int(total),
            "attributed_entries": matched}


def _unattributed_gl_sample(company, properties):
    """Identify a bounded set of vouchers behind a company coverage blocker."""
    sample = []
    kinds = ",".join(["%s"] * len(STANDARD_SCOPED))
    unscoped = frappe.db.sql(
        "SELECT name,voucher_type,voucher_no,posting_date,account,debit,credit "
        "FROM `tabGL Entry` WHERE company=%s AND is_cancelled=0 "
        f"AND COALESCE(voucher_type,'') NOT IN ({kinds}) "
        "ORDER BY name LIMIT 20", (company, *STANDARD_SCOPED), as_dict=True)
    for row in unscoped:
        sample.append({"gl_entry": row.name, "voucher_type": row.voucher_type,
            "voucher_no": row.voucher_no, "posting_date": str(row.posting_date),
            "account": row.account, "debit": _number(row.debit),
            "credit": _number(row.credit), "reason": "voucher_type_not_scoped"})
    allowed = ",".join(["%s"] * len(properties))
    for doctype in STANDARD_SCOPED:
        rows = frappe.db.sql(
            "SELECT g.name,g.voucher_type,g.voucher_no,g.posting_date,"
            "g.account,g.debit,g.credit,d.name AS source_name,"
            "d.docstatus AS source_docstatus,d.company AS source_company,"
            "d.hs_property AS source_property "
            "FROM `tabGL Entry` g "
            f"LEFT JOIN `tab{doctype}` d ON d.name=g.voucher_no "
            "WHERE g.company=%s AND g.is_cancelled=0 AND g.voucher_type=%s "
            "AND (d.name IS NULL OR COALESCE(d.docstatus,-1)!=1 "
            "OR COALESCE(d.company,'')!=%s "
            f"OR COALESCE(d.hs_property,'') NOT IN ({allowed})) "
            "ORDER BY g.name LIMIT 20",
            (company, doctype, company, *properties), as_dict=True)
        for row in rows:
            reason = ("source_missing" if not row.source_name else
                "source_not_submitted" if row.source_docstatus != 1 else
                "source_company_mismatch" if row.source_company != company else
                "source_property_not_in_cutover")
            sample.append({"gl_entry": row.name, "voucher_type": row.voucher_type,
                "voucher_no": row.voucher_no, "posting_date": str(row.posting_date),
                "account": row.account, "debit": _number(row.debit),
                "credit": _number(row.credit), "reason": reason,
                "source_property": row.source_property})
    return sorted(sample, key=lambda row: row["gl_entry"])[:20]


def _deposits(prop, blockers):
    """Inventory customer credits by their native voucher and original fund."""
    from hospitality_suite.accounting import guarantee_balance
    from hospitality_suite.refunds import original_funds

    guarantees = []
    sources = frappe.get_all("HS Payment", filters={"property": prop.name,
        "company": prop.company, "status": "Posted", "kind": "Guarantee"},
        fields=["name"], order_by="name asc", limit_page_length=0)
    for row in sources:
        source = frappe.get_doc("HS Payment", row.name)
        try:
            balance = guarantee_balance(prop, source)
        except (frappe.ValidationError, frappe.DoesNotExistError):
            blockers.append({"property": prop.name, "code": "invalid_guarantee_balance",
                             "source": source.name})
            continue
        if balance.nominal or balance.book:
            guarantees.append({"source": source.name, "customer": source.customer,
                "booking": source.booking, "stay": source.stay, "folio": source.folio,
                "currency": source.currency, "nominal": _number(balance.nominal),
                "base_balance": _number(balance.book),
                "journal_entry": source.journal_entry,
                "liability_account": balance.liability.account if balance.liability else None})

    native = frappe.get_all("Payment Entry", filters={"hs_property": prop.name,
        "company": prop.company, "docstatus": 1, "party_type": "Customer",
        "payment_type": "Receive", "unallocated_amount": [">", 0]},
        fields=["name", "party", "paid_from", "paid_to", "paid_from_account_currency",
                "paid_to_account_currency", "paid_amount", "unallocated_amount",
                "source_exchange_rate", "posting_date"],
        order_by="name asc", limit_page_length=0)
    payment_names = [row.name for row in native]
    payment_ledger = defaultdict(list)
    for start in range(0, len(payment_names), 500):
        names = payment_names[start:start + 500]
        placeholders = ",".join(["%s"] * len(names))
        entries = frappe.db.sql(
            "SELECT against_voucher_no,account,party_type,party,account_currency,"
            "SUM(amount) AS base_amount,"
            "SUM(amount_in_account_currency) AS account_amount "
            "FROM `tabPayment Ledger Entry` WHERE company=%s "
            "AND against_voucher_type='Payment Entry' AND delinked=0 "
            f"AND against_voucher_no IN ({placeholders}) "
            "GROUP BY against_voucher_no,account,party_type,party,account_currency",
            (prop.company, *names), as_dict=True)
        for entry in entries:
            payment_ledger[entry.against_voucher_no].append(entry)
    sources_by_entry = defaultdict(list)
    if payment_names:
        for row in frappe.get_all("HS Payment", filters={"property": prop.name,
                "company": prop.company, "status": "Posted",
                "payment_entry": ["in", payment_names]},
                fields=["name", "kind", "payment_entry", "booking", "stay", "folio"],
                order_by="name asc", limit_page_length=0):
            sources_by_entry[row.payment_entry].append(row)
    advances = []
    for row in native:
        matching = [entry for entry in payment_ledger[row.name]
                    if entry.account == row.paid_from and
                    entry.party_type == "Customer" and entry.party == row.party and
                    entry.account_currency == row.paid_from_account_currency]
        base_available = None
        if (len(payment_ledger[row.name]) != 1 or len(matching) != 1 or
                Decimal(str(matching[0].account_amount or 0)) !=
                    -Decimal(str(row.unallocated_amount)) or
                Decimal(str(matching[0].base_amount or 0)) >= 0):
            blockers.append({"property": prop.name,
                "code": "customer_credit_payment_ledger_mismatch",
                "source": row.name})
        else:
            base_available = -Decimal(str(matching[0].base_amount))
            if (row.paid_from_account_currency == prop.currency and
                    base_available != Decimal(str(row.unallocated_amount))):
                blockers.append({"property": prop.name,
                    "code": "customer_credit_base_mismatch", "source": row.name})
        advances.append({"voucher_type": "Payment Entry", "voucher": row.name,
            "customer": row.party, "receivable_account": row.paid_from,
            "cash_account": row.paid_to,
            "account_currency": row.paid_from_account_currency,
            "paid_currency": row.paid_to_account_currency,
            "original_amount": _number(row.paid_amount),
            "available": _number(row.unallocated_amount),
            "base_available": _number(base_available) if base_available is not None else None,
            "exchange_rate": _number(row.source_exchange_rate),
            "posting_date": str(row.posting_date),
            "sources": [{"name": source.name, "kind": source.kind,
                "booking": source.booking, "stay": source.stay,
                "folio": source.folio} for source in sources_by_entry[row.name]]})

    applied = frappe.get_all("HS Payment", filters={"property": prop.name,
        "company": prop.company, "status": "Posted", "kind": "Guarantee Applied"},
        fields=["name"], order_by="name asc", limit_page_length=0)
    for row in applied:
        source = frappe.get_doc("HS Payment", row.name)
        foreign_rows = frappe.get_all("Journal Entry Account", filters={
            "parent": source.journal_entry, "parenttype": "Journal Entry",
            "party_type": "Customer", "party": source.customer,
            "credit_in_account_currency": [">", 0],
            "account_currency": ["!=", prop.currency]},
            fields=["name", "account_currency"], limit=1) if source.journal_entry else []
        if foreign_rows:
            blockers.append({"property": prop.name,
                "code": "foreign_applied_guarantee_credit_unsupported",
                "source": source.journal_entry,
                "account_currency": foreign_rows[0].account_currency})
            continue
        try:
            funds = original_funds(prop, source)
        except (frappe.ValidationError, frappe.DoesNotExistError):
            blockers.append({"property": prop.name,
                             "code": "invalid_applied_guarantee_credit",
                             "source": source.name})
            continue
        if funds.unallocated > 0:
            if funds.currency != prop.currency:
                blockers.append({"property": prop.name,
                    "code": "foreign_applied_guarantee_credit_unsupported",
                    "source": funds.doc.name})
            advances.append({"voucher_type": "Journal Entry", "voucher": funds.doc.name,
                "customer": source.customer, "receivable_account": funds.account,
                "cash_account": None, "account_currency": funds.currency,
                "paid_currency": source.currency,
                "original_amount": _number(funds.total),
                "available": _number(funds.unallocated),
                "base_available": (_number(funds.unallocated)
                    if funds.currency == prop.currency else None),
                "exchange_rate": _number(funds.rate),
                "posting_date": str(funds.doc.posting_date),
                "sources": [{"name": source.name, "kind": source.kind,
                    "booking": source.booking, "stay": source.stay,
                    "folio": source.folio}]})
    advances.sort(key=lambda row: (row["voucher_type"], row["voucher"]))
    return {"guarantees": guarantees, "customer_credits": advances}


def _delivered_service_issue(prop, row, blockers):
    """Freeze the exact stock cost and accounts needed for a later PMS return."""
    source = row.get("stock_entry")
    if not source:
        return None
    entry = frappe.db.get_value("Stock Entry", source,
        ["company", "hs_property", "docstatus", "stock_entry_type"],
        as_dict=True)
    lines = frappe.get_all("Stock Ledger Entry", filters={
        "voucher_type": "Stock Entry", "voucher_no": source,
        "is_cancelled": 0},
        fields=["item_code", "warehouse", "actual_qty",
                "stock_value_difference"], limit_page_length=0)
    gl = frappe.get_all("GL Entry", filters={
        "voucher_type": "Stock Entry", "voucher_no": source,
        "is_cancelled": 0},
        fields=["account", "debit", "credit", "party_type", "party"],
        limit_page_length=0)
    if (not entry or entry.company != prop.company or
            entry.hs_property != prop.name or entry.docstatus != 1 or
            entry.stock_entry_type != "Material Issue" or len(lines) != 1 or
            lines[0].item_code != row["item"] or
            not lines[0].warehouse or not gl):
        blockers.append({"property": prop.name,
                         "code": "invalid_delivered_service_stock_issue",
                         "source": row["name"], "stock_entry": source})
        return None
    warehouse = frappe.db.get_value("Warehouse", lines[0].warehouse,
        ["company", "hs_property", "is_group"], as_dict=True)
    if (not warehouse or warehouse.company != prop.company or
            warehouse.hs_property != prop.name or warehouse.is_group):
        blockers.append({"property": prop.name,
                         "code": "delivered_service_warehouse_scope_invalid",
                         "source": row["name"], "stock_entry": source,
                         "warehouse": lines[0].warehouse})
        return None
    quantity = -Decimal(str(lines[0].actual_qty or 0))
    cost = -Decimal(str(lines[0].stock_value_difference or 0))
    debit, credit = defaultdict(lambda: Decimal(0)), defaultdict(lambda: Decimal(0))
    party_found = False
    for line in gl:
        if line.party_type or line.party:
            party_found = True
            break
        debit[line.account] += Decimal(str(line.debit or 0))
        credit[line.account] += Decimal(str(line.credit or 0))
    debit = {name: amount for name, amount in debit.items() if amount}
    credit = {name: amount for name, amount in credit.items() if amount}
    if (party_found or len(debit) != 1 or len(credit) != 1 or
            quantity != Decimal(str(row["quantity"] or 0)) or
            cost <= 0 or list(debit.values()) != [cost] or
            list(credit.values()) != [cost] or
            next(iter(debit)) == next(iter(credit))):
        blockers.append({"property": prop.name,
                         "code": "invalid_delivered_service_stock_issue",
                         "source": row["name"], "stock_entry": source})
        return None
    issue = {"voucher": source, "item": row["item"],
             "warehouse": lines[0].warehouse,
             "quantity": _number(quantity), "cost": _number(cost),
             "expense_account": next(iter(debit)),
             "inventory_account": next(iter(credit))}
    return issue


def _maintenance_issued_parts(prop, parts, blockers):
    """Freeze each still issued part against one native stock voucher and GL."""
    by_voucher = defaultdict(list)
    for part in parts:
        if part.get("status") == "Issued":
            by_voucher[part.get("stock_entry")].append(part)
    for voucher, group in by_voucher.items():
        entry = frappe.db.get_value("Stock Entry", voucher,
            ["company", "hs_property", "docstatus", "stock_entry_type",
             "hs_stock_purpose"], as_dict=True) if voucher else None
        details = frappe.get_all("Stock Entry Detail", filters={"parent": voucher},
            fields=["name", "idx", "item_code", "qty", "s_warehouse",
                    "expense_account", "basic_amount"],
            order_by="idx asc", limit_page_length=0) if entry else []
        stock = frappe.get_all("Stock Ledger Entry", filters={
            "voucher_type": "Stock Entry", "voucher_no": voucher,
            "is_cancelled": 0}, fields=["voucher_detail_no", "item_code",
                "warehouse", "actual_qty", "stock_value_difference"],
            limit_page_length=0) if entry else []
        gl = frappe.get_all("GL Entry", filters={
            "voucher_type": "Stock Entry", "voucher_no": voucher,
            "is_cancelled": 0}, fields=["account", "debit", "credit",
                "party_type", "party"], limit_page_length=0) if entry else []
        reason = None
        try:
            if (not entry or entry.company != prop.company or
                    entry.hs_property != prop.name or entry.docstatus != 1 or
                    entry.stock_entry_type != "Material Issue" or
                    entry.hs_stock_purpose != "Maintenance" or
                    len(details) != len(group) or not stock or not gl or
                    len({part["parent"] for part in group}) != 1):
                raise ValueError("voucher scope or line count")
            credits = defaultdict(lambda: Decimal(0))
            debits = defaultdict(lambda: Decimal(0))
            for line in gl:
                debit = Decimal(str(line.debit or 0))
                credit = Decimal(str(line.credit or 0))
                if (line.party_type or line.party or not line.account or
                        debit < 0 or credit < 0 or
                        (debit > 0 and credit > 0)):
                    raise ValueError("unsupported stock GL line")
                debits[line.account] += debit
                credits[line.account] += credit
            debits = {key: value for key, value in debits.items() if value}
            credits = {key: value for key, value in credits.items() if value}
            if len(credits) != 1 or not debits or set(debits) & set(credits):
                raise ValueError("unattributable stock accounts")
            inventory_account = next(iter(credits))
            stock_by_detail = defaultdict(list)
            for movement in stock:
                detail = movement.voucher_detail_no
                if not detail and len(details) == 1:
                    detail = details[0].name
                stock_by_detail[detail].append(movement)
            if set(stock_by_detail) != {detail.name for detail in details}:
                raise ValueError("unattributable stock ledger lines")
            expected_expenses = defaultdict(lambda: Decimal(0))
            frozen = []
            for part, detail in zip(sorted(group, key=lambda row: row["idx"]),
                                    details):
                movements = stock_by_detail[detail.name]
                quantity = -sum((Decimal(str(row.actual_qty or 0))
                    for row in movements), Decimal(0))
                value = -sum((Decimal(str(row.stock_value_difference or 0))
                    for row in movements), Decimal(0))
                cost = Decimal(str(part["cost"] or 0))
                expense_account = (detail.expense_account or
                    next(iter(debits)) if len(debits) == 1 else
                    detail.expense_account)
                if (detail.item_code != part["item"] or
                        detail.s_warehouse != prop.warehouse or
                        any(row.item_code != detail.item_code or
                            row.warehouse != detail.s_warehouse
                            for row in movements) or
                        quantity <= 0 or value <= 0 or
                        quantity != Decimal(str(part["quantity"] or 0)) or
                        quantity != Decimal(str(detail.qty or 0)) or
                        value.quantize(Decimal("0.01")) != cost or
                        Decimal(str(detail.basic_amount or 0)).quantize(
                            Decimal("0.01")) != cost or
                        expense_account not in debits):
                    raise ValueError("part valuation or account differs")
                expected_expenses[expense_account] += cost
                frozen.append((part, {"voucher": voucher,
                    "detail": detail.name, "item": part["item"],
                    "warehouse": detail.s_warehouse,
                    "quantity": _number(quantity), "cost": _number(cost),
                    "group_count": len(group),
                    "voucher_total_cost": _number(sum(
                        credits.values(), Decimal(0))),
                    "expense_account": expense_account,
                    "inventory_account": inventory_account}))
            if (dict(expected_expenses) != debits or
                    sum(expected_expenses.values(), Decimal(0)) !=
                    credits[inventory_account]):
                raise ValueError("stock GL does not match parts")
            for part, issue in frozen:
                part["source_stock_issue"] = issue
                part["source_stock_issue_sha256"] = sha256(
                    canonical(issue).encode()).hexdigest()
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            reason = str(exc)
        if reason:
            blockers.append({"property": prop.name,
                "code": "invalid_open_maintenance_stock_issue",
                "source": group[0]["parent"], "stock_entry": voucher,
                "reason": reason,
                "voucher_company": entry.company if entry else None,
                "voucher_property": entry.hs_property if entry else None,
                "voucher_docstatus": entry.docstatus if entry else None,
                "voucher_type": entry.stock_entry_type if entry else None,
                "voucher_purpose": entry.hs_stock_purpose if entry else None,
                "issued_parts": len(group), "stock_details": len(details),
                "stock_ledger_entries": len(stock), "gl_entries": len(gl)})


def _open_operations(prop, blockers):
    """Freeze the data needed to reconstruct live hotel work on a PMS site."""
    specs = (
        ("bookings", "HS Booking", ["Draft", "Hold", "Confirmed", "Checked In"],
         ["name", "status", "customer", "guest", "starts_at", "ends_at",
          "hold_until", "channel", "travel_agent", "agent_commission_pct",
          "agent_commission_estimate", "instructions", "reason", "currency",
          "amount", "draft_data", "quote_snapshot", "fee_invoice",
          "fee_receivable", "fee_amount", "portal_token_hash",
          "portal_expires_at", "agent_commission_invoice",
          "pms_agent_commission", "modified"]),
        ("stays", "HS Stay", ["Active"],
         ["name", "status", "booking", "guest", "customer", "room",
          "rate", "starts_at", "ends_at", "actual_check_in",
          "actual_check_out", "lodging_charge_policy", "currency", "amount",
          "quote_snapshot", "service_entitlements", "reason", "early_fee",
          "late_fee", "departure_expires_at", "departure_inspected_by",
          "departure_inspected_at", "departure_notes", "modified"]),
        ("folios", "HS Folio", ["Open"],
         ["name", "status", "booking", "stay", "customer", "currency",
          "label", "modified"]),
        ("charges", "HS Charge", ["Pending", "Scheduled"],
         ["name", "status", "stay", "folio", "item", "description",
          "quantity", "rate", "amount", "currency", "business_date",
          "kind", "period_key", "service_date", "posted_at",
          "sales_invoice", "pms_receivable", "invoice_item", "reason",
          "quote_snapshot", "applies_to_charge", "adjustment_type",
          "modified"]),
        ("service_requests", "HS Service Request", ["Requested", "In Progress",
             "Delivered"],
         ["name", "status", "stay", "folio", "customer", "item",
          "warehouse", "quantity", "included", "amount", "currency",
          "charge", "stock_entry", "return_stock_entry", "credit_note",
          "sales_invoice", "notes", "modified"]),
        ("cleaning_tasks", "HS Cleaning Task", ["Pending", "In Progress",
             "Inspection"],
         ["name", "status", "room", "stay", "kind", "priority",
          "assigned_to", "started_at", "completed_at", "checklist",
          "notes", "inspected_by", "modified"]),
        ("guest_tickets", "HS Guest Ticket", ["Open", "In Progress"],
         ["name", "room", "stay", "subject", "description", "category",
          "priority", "status", "assigned_to", "due_at",
          "first_response_at", "resolved_at", "resolved_by", "resolution",
          "reopened_count", "modified"]),
        ("experience_orders", "HS Experience Order", ["Reserved", "Confirmed"],
         ["name", "experience", "booking", "stay", "folio", "customer",
          "item", "pms_product", "quantity", "participants",
          "scheduled_at", "unit_rate", "currency", "amount",
          "accepted_net", "accepted_tax", "accepted_total",
          "accepted_tax_profile", "income_account", "tax_account",
          "status", "charge", "pms_receivable", "sales_invoice",
          "notes", "cancel_reason", "modified"]),
        ("laundry_orders", "HS Laundry Order", ["Requested", "Collected",
             "In Process", "Ready"],
         ["name", "status", "stay", "room", "folio", "currency",
          "express", "complimentary", "notes", "total", "billed_total",
          "ready_by", "collected_by", "collected_at", "counted_at",
          "delivered_by", "delivered_at", "shortage_note",
          "cancel_reason", "modified"]),
        ("incidents", "HS Incident", ["Open"],
         ["name", "status", "room", "kind", "description", "evidence",
          "item", "quantity", "linen_direction", "stock_entry",
          "resolution", "resolved_by", "resolved_at", "modified"]),
        ("day_passes", "HS Day Pass", ["Issued"],
         ["name", "status", "customer", "guest", "people", "starts_at",
          "ends_at", "service", "sales_invoice", "payment",
          "pms_receivable", "quote_snapshot", "notes", "modified"]),
        ("portal_requests", "HS Portal Request", ["Hold", "Requested"],
         ["name", "status", "full_name", "email", "phone", "booking",
          "category", "rooms", "people", "mode", "starts_at", "ends_at",
          "hold_until", "request_until", "currency", "amount",
          "quote_snapshot", "experiences", "request_key", "payload_hash",
          "modified"]),
        ("room_blocks", "HS Room Block", ["Active"],
         ["name", "status", "room", "reason", "starts_at", "ends_at",
          "note", "created_by", "modified"]),
        ("maintenance_orders", "HS Maintenance Order", ["Open", "In Progress"],
         ["name", "status", "room", "equipment", "blocks_room", "title",
          "starts_at", "until_reopened", "ends_at", "kind", "assigned_to",
          "notes", "evidence", "cost", "stock_entry", "reopened_by",
          "modified"]),
    )
    result = {}
    for key, doctype, statuses, fields in specs:
        filters = {"property": prop.name, "company": prop.company,
                   "status": ["in", statuses]}
        if key == "service_requests":
            active_stays = [stay["name"] for stay in result["stays"]]
            if not active_stays:
                result[key] = []
                continue
            filters["stay"] = ["in", active_stays]
        if key == "day_passes":
            filters["ends_at"] = [">", now_datetime()]
        rows = frappe.get_all(doctype, filters=filters,
            fields=fields, order_by="name asc", limit_page_length=0)
        result[key] = []
        for row in rows:
            item = dict(row)
            for field in ("draft_data", "quote_snapshot", "service_entitlements",
                          "experiences", "checklist"):
                if field in item:
                    item[field + "_sha256"] = sha256(
                        str(item[field] or "").encode()).hexdigest()
            if key == "cleaning_tasks":
                room = frappe.db.get_value("HS Room", item.get("room"),
                    ["property", "company", "cleaning_status"], as_dict=True)
                expected = {"Pending": "Dirty", "In Progress": "Cleaning",
                            "Inspection": "Inspection"}[item["status"]]
                item["room_cleaning_status"] = room.cleaning_status if room else None
                if (not room or room.property != prop.name or
                        room.company != prop.company or
                        room.cleaning_status != expected):
                    blockers.append({"property": prop.name,
                        "code": "invalid_open_cleaning_room_state",
                        "source": item["name"], "room": item.get("room")})
            if key == "service_requests" and item["status"] == "Delivered":
                issue = _delivered_service_issue(prop, item, blockers)
                if issue:
                    item["source_stock_issue"] = issue
                    item["source_stock_issue_sha256"] = sha256(
                        canonical(issue).encode()).hexdigest()
                elif (not item.get("stock_entry") and
                        frappe.db.get_value("Item", item.get("item"),
                            "is_stock_item")):
                    blockers.append({"property": prop.name,
                                     "code": "invalid_delivered_service_stock_issue",
                                     "source": item["name"]})
            if key == "day_passes":
                _day_pass_financial(prop, item, blockers)
            result[key].append(item)
    booking_names = [row["name"] for row in result["bookings"]]
    result["booking_rooms"] = [dict(row) for row in frappe.get_all(
        "HS Booking Room", filters={"parenttype": "HS Booking",
            "parent": ["in", booking_names]},
        fields=["name", "parent", "idx", "category", "room", "rate",
                "people", "extra_beds", "modified"],
        order_by="parent asc,idx asc", limit_page_length=0)] if booking_names else []
    stay_names = [row["name"] for row in result["stays"]]
    result["stay_guests"] = [dict(row) for row in frappe.get_all(
        "HS Stay Guest", filters={"parenttype": "HS Stay",
            "parent": ["in", stay_names]},
        fields=["name", "parent", "idx", "guest", "relationship", "modified"],
        order_by="parent asc,idx asc", limit_page_length=0)] if stay_names else []
    maintenance_names = [row["name"] for row in result["maintenance_orders"]]
    result["maintenance_parts"] = [dict(row) for row in frappe.get_all(
        "HS Maintenance Part", filters={"parenttype": "HS Maintenance Order",
            "parent": ["in", maintenance_names]},
        fields=["name", "parent", "idx", "item", "quantity",
                "stock_entry", "cost", "status", "modified"],
        order_by="parent asc,idx asc", limit_page_length=0)] if maintenance_names else []
    returned_entries = {}
    for part in result["maintenance_parts"]:
        if part["status"] != "Returned":
            continue
        voucher = part.get("stock_entry")
        if voucher not in returned_entries:
            returned_entries[voucher] = frappe.db.get_value("Stock Entry", voucher,
                ["company", "hs_property", "docstatus", "stock_entry_type"],
                as_dict=True) if voucher else None
        entry = returned_entries[voucher]
        if (not entry or entry.company != prop.company or
                entry.hs_property != prop.name or entry.docstatus != 2 or
                entry.stock_entry_type != "Material Issue"):
            blockers.append({"property": prop.name,
                "code": "invalid_returned_maintenance_part",
                "source": part["name"], "stock_entry": voucher})
        else:
            part["source_returned_entry"] = {"voucher": voucher,
                "company": entry.company, "property": entry.hs_property,
                "docstatus": entry.docstatus,
                "stock_entry_type": entry.stock_entry_type}
    _maintenance_issued_parts(prop, result["maintenance_parts"], blockers)
    for order in result["maintenance_orders"]:
        if not order.get("evidence"):
            continue
        try:
            metadata, _ = _private_evidence("HS Maintenance Order",
                order["name"], order["evidence"])
            order.update(metadata)
        except (OSError, ValueError) as exc:
            blockers.append({"property": prop.name,
                "code": "invalid_open_maintenance_evidence",
                "source": order["name"], "reason": str(exc)})
    laundry_names = [row["name"] for row in result["laundry_orders"]]
    result["laundry_items"] = [dict(row) for row in frappe.get_all(
        "HS Laundry Order Item", filters={"parenttype": "HS Laundry Order",
            "parent": ["in", laundry_names]},
        fields=["name", "parent", "idx", "laundry_rate", "garment",
                "service_type", "item", "pms_product", "quantity",
                "returned_quantity", "rate", "amount", "charge", "modified"],
        order_by="parent asc,idx asc", limit_page_length=0)] if laundry_names else []
    ticket_names = [row["name"] for row in result["guest_tickets"]]
    result["ticket_events"] = [dict(row) for row in frappe.get_all(
        "HS Ticket Event", filters={"property": prop.name,
            "company": prop.company, "ticket": ["in", ticket_names]},
        fields=["name", "ticket", "kind", "actor", "occurred_at",
                "note", "before_value", "after_value", "creation"],
        order_by="ticket asc,occurred_at asc,creation asc,name asc",
        limit_page_length=0)] if ticket_names else []
    event_tickets = {row["ticket"] for row in result["ticket_events"]
                     if row["kind"] == "Created"}
    scoped_events = defaultdict(int)
    for event in result["ticket_events"]:
        scoped_events[event["ticket"]] += 1
    all_event_counts = {row.ticket: int(row.total) for row in frappe.db.sql(
        "SELECT ticket, COUNT(*) AS total FROM `tabHS Ticket Event` "
        "WHERE ticket IN %(ticket_names)s GROUP BY ticket",
        {"ticket_names": tuple(ticket_names)}, as_dict=True)} if ticket_names else {}
    active_stays = {row["name"]: row for row in result["stays"]}
    for task in result["cleaning_tasks"]:
        if task.get("stay") and task["stay"] not in active_stays:
            historical = frappe.db.get_value("HS Stay", task["stay"],
                ["property", "company", "room", "status", "modified"],
                as_dict=True)
            if (historical and historical.property == prop.name and
                    historical.company == prop.company and
                    historical.room == task["room"] and
                    historical.status == "Checked Out" and
                    task["kind"] == "Departure"):
                task["source_closed_stay"] = {
                    "name": task["stay"], "room": historical.room,
                    "status": historical.status,
                    "modified": str(historical.modified)}
            else:
                blockers.append({"property": prop.name,
                    "code": "unreplayable_open_cleaning_stay",
                    "source": task["name"], "stay": task["stay"]})
    for ticket in result["guest_tickets"]:
        room = frappe.db.get_value("HS Room", ticket["room"],
            ["property", "company"], as_dict=True) if ticket["room"] else None
        stay = active_stays.get(ticket["stay"]) if ticket["stay"] else None
        if (ticket["room"] and (not room or
                (room.property, room.company) != (prop.name, prop.company)) or
                ticket["stay"] and (not stay or
                    ticket["room"] != stay["room"])):
            blockers.append({"property": prop.name,
                "code": "invalid_open_ticket_links", "source": ticket["name"]})
        if ticket["name"] not in event_tickets:
            blockers.append({"property": prop.name,
                "code": "missing_open_ticket_creation_event",
                "source": ticket["name"]})
        if all_event_counts.get(ticket["name"], 0) != \
                scoped_events[ticket["name"]]:
            blockers.append({"property": prop.name,
                "code": "cross_property_ticket_event",
                "source": ticket["name"]})
    allocations = frappe.get_all("HS Allocation", filters={"property": prop.name,
        "company": prop.company, "status": "Active"},
        fields=["name", "booking", "booking_room", "stay", "portal_request",
                "category", "room", "kind", "status", "starts_at", "ends_at",
                "buffer_minutes", "rate", "currency", "accepted_amount",
                "quote_snapshot", "maintenance", "room_block", "modified"],
        order_by="name asc", limit_page_length=0)
    result["allocations"] = []
    for row in allocations:
        item = dict(row)
        item["quote_sha256"] = sha256(
            str(item["quote_snapshot"] or "").encode()).hexdigest()
        result["allocations"].append(item)
    room_counts = defaultdict(int)
    for row in result["booking_rooms"]:
        room_counts[row["parent"]] += 1
    for booking in result["bookings"]:
        if booking["status"] != "Draft" and not room_counts[booking["name"]]:
            blockers.append({"property": prop.name,
                             "code": "open_booking_without_rooms",
                             "source": booking["name"]})
    for stay in result["stays"]:
        booking = frappe.db.get_value("HS Booking", stay["booking"],
            ["property", "company", "customer"], as_dict=True) if stay["booking"] else None
        room = frappe.db.get_value("HS Room", stay["room"],
            ["property", "company"], as_dict=True) if stay["room"] else None
        if (not booking or not room or
                (booking.property, booking.company, booking.customer) !=
                    (prop.name, prop.company, stay["customer"]) or
                (room.property, room.company) != (prop.name, prop.company)):
            blockers.append({"property": prop.name,
                             "code": "active_stay_link_mismatch", "source": stay["name"]})
    for folio in result["folios"]:
        if not folio["booking"] and not folio["stay"]:
            blockers.append({"property": prop.name,
                             "code": "open_folio_without_visit", "source": folio["name"]})
    for incident in result["incidents"]:
        if incident.get("evidence"):
            try:
                metadata, _ = _incident_evidence(incident["name"],
                    incident["evidence"])
                incident.update(metadata)
            except (OSError, ValueError) as exc:
                blockers.append({"property": prop.name,
                    "code": "invalid_open_incident_evidence",
                    "source": incident["name"], "reason": str(exc)})
        if incident.get("stock_entry"):
            blockers.append({"property": prop.name,
                "code": "unsupported_open_incident_stock",
                "source": incident["name"]})
    return result


def _mapping_requirements(prop, ledger, stock, receivables, payables,
                          deposits, operations, blockers):
    """Freeze every master referenced by open balances or live operations."""
    settings = {field: prop.get(field) or "" for field in
                (*ACCOUNT_SETTINGS, *ITEM_SETTINGS, *WAREHOUSE_SETTINGS)}
    account_ids = {row["account"] for row in ledger["lines"] if row["account"]}
    account_ids.update(value for field, value in settings.items()
                       if field in ACCOUNT_SETTINGS and value)
    account_ids.update(row["account"] for row in receivables + payables
                       if row["account"])
    account_ids.update(row["liability_account"] for row in
                       deposits["guarantees"] if row["liability_account"])
    for row in operations["service_requests"]:
        issue = row.get("source_stock_issue") or {}
        account_ids.update(issue[field] for field in
            ("expense_account", "inventory_account") if issue.get(field))
    for row in operations["maintenance_parts"]:
        issue = row.get("source_stock_issue") or {}
        account_ids.update(issue[field] for field in
            ("expense_account", "inventory_account") if issue.get(field))
    for row in operations["experience_orders"]:
        account_ids.update(value for value in
                           (row["income_account"], row["tax_account"]) if value)
    for row in operations["day_passes"]:
        account_ids.update(line["account"] for line in
            (row.get("source_financial") or {}).get("invoice_gl", [])
            if line.get("account"))
    for row in deposits["customer_credits"]:
        account_ids.update(value for value in
                           (row["receivable_account"], row["cash_account"]) if value)
    item_ids = {row["item"] for row in stock["positions"] if row["item"]}
    item_ids.update(value for field, value in settings.items()
                    if field in ITEM_SETTINGS and value)
    item_ids.update(row["item"] for row in operations["charges"] if row["item"])
    item_ids.update(row["item"] for row in operations["service_requests"]
                    if row["item"])
    item_ids.update(row["item"] for row in operations["experience_orders"]
                    if row["item"])
    item_ids.update(row["item"] for row in operations["laundry_items"]
                    if row["item"])
    embedded_items = {"item", "lodging_item", "extra_hour_item",
                      "timing_item", "day_pass_item", "penalty_item"}
    embedded_experiences = set()

    def collect_items(node):
        if isinstance(node, list):
            for child in node:
                collect_items(child)
        elif isinstance(node, dict):
            for key, child in node.items():
                if key in embedded_items and isinstance(child, str) and child:
                    item_ids.add(child)
                elif key == "experience" and isinstance(child, str) and child:
                    embedded_experiences.add(child)
                else:
                    collect_items(child)

    for kind in ("bookings", "stays", "charges", "portal_requests",
                 "allocations"):
        for row in operations[kind]:
            for field in ("draft_data", "quote_snapshot",
                          "service_entitlements", "experiences"):
                raw = row.get(field)
                if not raw:
                    continue
                try:
                    collect_items(frappe.parse_json(raw))
                except (TypeError, ValueError):
                    blockers.append({"property": prop.name,
                        "code": "invalid_open_operation_snapshot",
                        "doctype": kind, "source": row["name"], "field": field})
    for row in prop.get("service_accounts") or []:
        if row.item:
            item_ids.add(row.item)
        account_ids.update(value for value in
                           (row.income_account, row.expense_account) if value)
    parties = {"Customer": set(), "Supplier": set()}
    for row in ledger["lines"]:
        if row["party"]:
            if row["party_type"] not in parties:
                blockers.append({"property": prop.name,
                                 "code": "unsupported_gl_party_type",
                                 "party_type": row["party_type"],
                                 "party": row["party"]})
            else:
                parties[row["party_type"]].add(row["party"])
    parties["Customer"].update(row["party"] for row in receivables
                               if row["party"])
    parties["Supplier"].update(row["party"] for row in payables
                               if row["party"])
    parties["Customer"].update(row["customer"] for row in
                               deposits["guarantees"] if row["customer"])
    parties["Customer"].update(row["customer"] for row in
                               deposits["customer_credits"] if row["customer"])
    for kind in ("bookings", "stays", "folios", "service_requests",
                 "experience_orders", "day_passes"):
        parties["Customer"].update(row["customer"] for row in
                                   operations[kind] if row["customer"])
    parties["Customer"].discard(None)
    parties["Supplier"].discard(None)
    refs = {"categories": set(), "rooms": set(), "rates": set(),
            "guests": set(), "travel_agents": set(), "experiences": set(),
            "laundry_rates": set(),
            "users": set(), "equipment": set()}
    refs["experiences"].update(embedded_experiences)
    for row in operations["booking_rooms"]:
        for key, field in (("categories", "category"), ("rooms", "room"),
                           ("rates", "rate")):
            if row[field]:
                refs[key].add(row[field])
    for row in operations["allocations"]:
        for key, field in (("categories", "category"), ("rooms", "room"),
                           ("rates", "rate")):
            if row[field]:
                refs[key].add(row[field])
    for row in operations["portal_requests"]:
        if row["category"]:
            refs["categories"].add(row["category"])
    for row in operations["room_blocks"]:
        if row["room"]:
            refs["rooms"].add(row["room"])
        if row["created_by"]:
            refs["users"].add(row["created_by"])
    for row in operations["incidents"]:
        if row["room"]:
            refs["rooms"].add(row["room"])
    refs["guests"].update(row["guest"] for row in
        operations["day_passes"] if row["guest"])
    for row in operations["cleaning_tasks"]:
        if row["room"]:
            refs["rooms"].add(row["room"])
        refs["users"].update(value for value in
            (row["assigned_to"], row["inspected_by"]) if value)
    for row in operations["guest_tickets"]:
        if row["room"]:
            refs["rooms"].add(row["room"])
        refs["users"].update(value for value in
            (row["assigned_to"], row["resolved_by"]) if value)
    refs["users"].update(row["actor"] for row in
        operations["ticket_events"] if row["actor"])
    refs["experiences"].update(row["experience"] for row in
        operations["experience_orders"] if row["experience"])
    refs["laundry_rates"].update(row["laundry_rate"] for row in
        operations["laundry_items"] if row["laundry_rate"])
    refs["users"].update(row["collected_by"] for row in
        operations["laundry_orders"] if row["collected_by"])
    for row in operations["maintenance_orders"]:
        if row["room"]:
            refs["rooms"].add(row["room"])
        if row["equipment"]:
            refs["equipment"].add(row["equipment"])
        refs["users"].update(value for value in
            (row["assigned_to"], row["reopened_by"]) if value)
    item_ids.update(row["item"] for row in operations["maintenance_parts"]
                    if row["item"])
    for kind in ("bookings", "stays"):
        for row in operations[kind]:
            if row["guest"]:
                refs["guests"].add(row["guest"])
            if kind == "bookings" and row["travel_agent"]:
                refs["travel_agents"].add(row["travel_agent"])
            if kind == "stays":
                if row["room"]:
                    refs["rooms"].add(row["room"])
                if row["rate"]:
                    refs["rates"].add(row["rate"])
    refs["guests"].update(row["guest"] for row in
                          operations["stay_guests"] if row["guest"])
    if refs["travel_agents"]:
        parties["Supplier"].update(row.supplier for row in frappe.get_all(
            "HS Travel Agent",
            filters={"name": ["in", sorted(refs["travel_agents"])]},
            fields=["supplier"], limit_page_length=0) if row.supplier)
    if refs["rooms"]:
        refs["categories"].update(row.category for row in frappe.get_all(
            "HS Room", filters={"name": ["in", sorted(refs["rooms"])]},
            fields=["category"], limit_page_length=0) if row.category)
    if refs["rates"]:
        refs["categories"].update(row.category for row in frappe.get_all(
            "HS Rate", filters={"name": ["in", sorted(refs["rates"])]},
            fields=["category"], limit_page_length=0) if row.category)
        item_ids.update(row.item for row in frappe.get_all("HS Rate Service",
            filters={"parenttype": "HS Rate",
                     "parent": ["in", sorted(refs["rates"])]},
            fields=["item"], limit_page_length=0) if row.item)
    if refs["guests"]:
        parties["Customer"].update(row.customer for row in frappe.get_all(
            "HS Guest", filters={"name": ["in", sorted(refs["guests"])]},
            fields=["customer"], limit_page_length=0) if row.customer)
    if refs["experiences"]:
        item_ids.update(row.item for row in frappe.get_all("HS Experience",
            filters={"name": ["in", sorted(refs["experiences"])]},
            fields=["item"], limit_page_length=0) if row.item)
    if refs["laundry_rates"]:
        item_ids.update(row.item for row in frappe.get_all("HS Laundry Rate",
            filters={"name": ["in", sorted(refs["laundry_rates"])]},
            fields=["item"], limit_page_length=0) if row.item)

    def rows(doctype, names, fields, code, scoped=False):
        found = {row.name: row for row in frappe.get_all(doctype,
            filters={"name": ["in", sorted(names)]}, fields=fields,
            limit_page_length=0)} if names else {}
        result = []
        for name in sorted(names):
            row = found.get(name)
            if not row or (scoped and (row.property != prop.name or
                                       row.company != prop.company)):
                blockers.append({"property": prop.name, "code": code,
                                 "source": name})
            else:
                result.append(dict(row))
        return result

    accounts = rows("Account", account_ids,
        ["name", "company", "root_type", "account_type", "account_currency",
         "is_group", "disabled"], "invalid_mapping_account")
    for row in accounts:
        if row["company"] != prop.company or row["is_group"] or row["disabled"]:
            blockers.append({"property": prop.name,
                             "code": "invalid_mapping_account",
                             "source": row["name"]})
    products = rows("Item", item_ids,
        ["name", "item_name", "is_stock_item", "is_fixed_asset", "disabled"],
        "missing_mapping_item")
    for row in products:
        if row["disabled"]:
            blockers.append({"property": prop.name,
                             "code": "disabled_mapping_item",
                             "source": row["name"]})
    party_rows = {}
    for doctype in ("Customer", "Supplier"):
        party_rows[doctype] = rows(doctype, parties[doctype],
            ["name", "disabled", "customer_name" if doctype == "Customer"
             else "supplier_name"], "missing_mapping_party")
    warehouse_rows = rows("Warehouse", stock["warehouses"],
        ["name", "company", "hs_property", "is_group", "disabled"],
        "invalid_mapping_warehouse")
    for row in warehouse_rows:
        if (row["company"] != prop.company or row["hs_property"] != prop.name or
                row["is_group"] or row["disabled"]):
            blockers.append({"property": prop.name,
                             "code": "invalid_mapping_warehouse",
                             "source": row["name"]})
    scoped_rows = {}
    master_fields = {
        "categories": ["name", "property", "company"],
        "rooms": ["name", "property", "company", "category", "active"],
        "rates": ["name", "property", "company", "category", "currency",
                  "mode", "active"],
        "guests": ["name", "property", "company", "customer"],
        "travel_agents": ["name", "property", "company", "agent_type",
                          "supplier", "pms_supplier", "commission_pct",
                          "active"],
        "experiences": ["name", "property", "company", "item",
                        "experience_category", "active"],
        "laundry_rates": ["name", "property", "company", "item",
                          "garment", "service_type", "currency", "active"],
        "users": ["name", "enabled"],
        "equipment": ["name", "property", "company", "room", "active"],
    }
    for key, doctype in (("categories", "HS Category"), ("rooms", "HS Room"),
                         ("rates", "HS Rate"), ("guests", "HS Guest"),
                         ("travel_agents", "HS Travel Agent"),
                         ("experiences", "HS Experience"),
                         ("laundry_rates", "HS Laundry Rate"),
                         ("users", "User"), ("equipment", "HS Equipment")):
        scoped_rows[key] = rows(doctype, refs[key],
            master_fields[key], "invalid_mapping_" + key,
            scoped=key != "users")
    return {"source_settings": settings, "accounts": accounts,
            "products": products, "parties": party_rows,
            "warehouses": warehouse_rows, **scoped_rows}


def _fiscal_history(prop, blockers):
    """Freeze document identities and complete source-content hashes for archival."""
    native = []
    invoices = frappe.get_all("Sales Invoice", filters={"hs_property": prop.name,
        "company": prop.company, "docstatus": ["in", [1, 2]]},
        fields=["name", "posting_date", "customer", "customer_name", "currency",
                "grand_total", "is_return", "return_against", "is_opening",
                "docstatus"], order_by="name asc", limit_page_length=0)
    for row in invoices:
        if row.is_return and row.return_against:
            original = frappe.db.get_value("Sales Invoice", row.return_against,
                ["hs_property", "company"], as_dict=True)
            if (not original or original.hs_property != prop.name or
                    original.company != prop.company):
                blockers.append({"property": prop.name,
                                 "code": "cross_property_credit_note",
                                 "source": row.name,
                                 "original": row.return_against})
        doc = frappe.get_doc("Sales Invoice", row.name)
        native.append({"name": row.name, "document_type": "Credit Note"
            if row.is_return else "Invoice", "status": "Cancelled"
            if row.docstatus == 2 else "Posted", "posting_date": str(row.posting_date),
            "customer": row.customer, "customer_name": row.customer_name,
            "currency": row.currency, "total_amount": _number(row.grand_total),
            "source_invoice": row.return_against,
            "is_opening": row.is_opening == "Yes",
            "snapshot_sha256": sha256(canonical(doc.as_dict()).encode()).hexdigest()})
    historical = []
    for row in frappe.get_all("HS PMS Fiscal Document", filters={
            "property": prop.name, "company": prop.company},
            fields=["name", "document_number", "document_type", "business_date",
                    "buyer_name",
                    "currency", "total_amount", "source_invoice", "status"],
            order_by="name asc", limit_page_length=0):
        doc = frappe.get_doc("HS PMS Fiscal Document", row.name)
        historical.append({"name": row.name, "document_number": row.document_number,
            "document_type": row.document_type, "status": row.status,
            "buyer_name": row.buyer_name,
            "business_date": str(row.business_date), "currency": row.currency,
            "total_amount": _number(row.total_amount),
            "source_invoice": row.source_invoice,
            "snapshot_sha256": sha256(canonical(doc.as_dict()).encode()).hexdigest()})
    return {"native_documents": native, "pms_documents": historical}


def preflight():
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede revisar la migración"),
                     frappe.PermissionError)
    if provider() != "erpnext" or "erpnext" not in frappe.get_installed_apps():
        frappe.throw(_("El sitio no conserva autoridad contable ERPNext"))
    names = [row.name for row in frappe.db.sql(
        "SELECT name FROM `tabHS Property` ORDER BY name FOR UPDATE", as_dict=True)]
    blockers = []
    if not names:
        blockers.append({"code": "no_properties"})
    properties = []
    ledgers = {}
    by_company = defaultdict(list)
    for name in names:
        prop = frappe.get_doc("HS Property", name)
        company = frappe.db.get_value("Company", prop.company,
            ["name", "default_currency", "is_group"], as_dict=True)
        if not company or company.is_group or company.default_currency != prop.currency:
            blockers.append({"property": name, "code": "invalid_erp_company"})
        shifts = frappe.get_all("HS Shift", filters={"property": name,
            "company": prop.company, "status": ["in", ["Open", "Review"]]},
            pluck="name", order_by="name asc", limit_page_length=0)
        if shifts:
            blockers.append({"property": name, "code": "unclosed_cash_shifts",
                             "sources": shifts})
        ledger = _ledger(prop, blockers)
        stock = _warehouses_and_stock(prop, blockers)
        _stock_ledger_valuation(prop, ledger, stock, blockers)
        receivables = _open_invoices(prop, "Sales Invoice", "customer", "debit_to", blockers)
        payables = _open_invoices(prop, "Purchase Invoice", "supplier", "credit_to", blockers)
        deposits = _deposits(prop, blockers)
        operations = _open_operations(prop, blockers)
        fiscal = _fiscal_history(prop, blockers)
        mapping_requirements = _mapping_requirements(prop, ledger, stock,
            receivables, payables, deposits, operations, blockers)
        properties.append({"property": name, "company": prop.company,
            "currency": prop.currency, "business_date": str(prop.business_date),
            "ledger": ledger, "stock": stock, "deposits": deposits,
            "open_operations": operations, "fiscal_history": fiscal,
            "mapping_requirements": mapping_requirements,
            "open_receivables": receivables, "open_payables": payables,
            "open_shifts": shifts})
        ledgers[name] = ledger
        by_company[prop.company].append(name)
    coverage = [_company_gl_coverage(company, names, ledgers, blockers)
                for company, names in sorted(by_company.items())]
    source = {"schema_version": 1, "provider": "ERPNext",
              "properties": properties, "gl_coverage": coverage, "blockers": blockers}
    return {**source, "generated_at": str(now_datetime()),
            "source_sha256": sha256(canonical(source).encode()).hexdigest(),
            "ready_for_mapping": not blockers, "cutover_performed": False}
