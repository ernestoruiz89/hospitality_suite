"""Read-only posting plan for a PMS to ERPNext opening transfer.

The plan describes target document classes and balanced source amounts. It
never submits an ERPNext document or changes the active accounting provider.
"""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256

import frappe

from hospitality_suite import (pms_cutover, pms_cutover_mapping,
    pms_cutover_links, pms_cutover_direct_sales)
from hospitality_suite.service import canonical
from hospitality_suite.pricing import money


def _signed_line(source, target, base, original, currency, cost_center):
    return {"source_account": source, "account": target,
            "cost_center": cost_center, "account_currency": currency,
            "debit": pms_cutover._money(max(base, Decimal(0))),
            "credit": pms_cutover._money(max(-base, Decimal(0))),
            "debit_in_account_currency": pms_cutover._money(max(original, Decimal(0))),
            "credit_in_account_currency": pms_cutover._money(max(-original, Decimal(0)))}


def _purchase_order_rate(currency, base_currency, posting_date):
    """Freeze a configured buying rate; a cutover review must not fetch live FX."""
    if currency == base_currency:
        return Decimal(1), None, None
    record = frappe.db.get_value("Currency Exchange", {
        "from_currency": currency, "to_currency": base_currency,
        "for_buying": 1, "date": ["<=", posting_date]},
        ["name", "date", "exchange_rate"], as_dict=True,
        order_by="date desc, creation desc")
    if not record:
        raise ValueError("Configure una tasa de compra para la orden pendiente")
    rate = Decimal(str(record.exchange_rate))
    if rate <= 0:
        raise ValueError("La tasa de compra de la orden pendiente no es positiva")
    return rate, record.name, str(record.date)


def _day_pass_continuations(source, cfg, receivables, blockers):
    """Map live PMS Day Pass sources without posting a second sale."""
    property_name = source["property"]
    open_by_source = {row["source"]: row for row in receivables}
    mapped = []
    seen_receivables = set()
    for day_pass in source.get("open_operations", {}).get("day_passes", []):
        sale = day_pass.get("accepted_sale")
        financial = day_pass.get("source_financial")
        fiscal = day_pass.get("source_fiscal")
        settlements = day_pass.get("source_settlements")
        if not all(isinstance(row, dict) for row in
                (sale, financial, fiscal, settlements)):
            blockers.append({"property": property_name,
                "code": "incomplete_day_pass_source",
                "source": day_pass["name"]})
            continue
        receivable = financial.get("receivable")
        item_name = cfg["products"].get(sale.get("product"))
        item = frappe.db.get_value("Item", item_name,
            ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
            as_dict=True) if item_name else None
        customer = cfg["parties"].get(day_pass.get("customer"), {}).get("customer")
        account_sources = {key: financial.get(key) for key in
            ("receivable_account", "income_account", "tax_account")}
        target_accounts = {key: cfg["accounts"].get(name) if name else None
            for key, name in account_sources.items()}
        outstanding = pms_cutover._decimal(financial["outstanding_amount"])
        opening = open_by_source.get(receivable)
        if (not receivable or receivable in seen_receivables or not customer or
                not frappe.db.exists("Customer", customer) or not item or
                not item.is_sales_item or item.is_stock_item or
                item.is_fixed_asset or item.disabled or
                not target_accounts["receivable_account"] or
                not target_accounts["income_account"] or
                (account_sources["tax_account"] and
                 not target_accounts["tax_account"]) or
                (outstanding > 0 and (not opening or
                    pms_cutover._decimal(opening["outstanding"]) != outstanding)) or
                (outstanding == 0 and opening)):
            blockers.append({"property": property_name,
                "code": "unmapped_day_pass_continuation",
                "source": day_pass["name"]})
            continue
        seen_receivables.add(receivable)
        mapped.append({"source": day_pass["name"],
            "property": property_name, "company": cfg["company"],
            "customer": customer, "item_code": item_name,
            "people": day_pass["people"],
            "starts_at": str(day_pass["starts_at"]),
            "ends_at": str(day_pass["ends_at"]),
            "source_receivable": receivable,
            "opening_receivable_source": opening["source"] if opening else None,
            "outstanding": pms_cutover._money(outstanding),
            "accepted_sale": sale,
            "source_financial": financial,
            "source_fiscal": fiscal,
            "source_settlements": settlements,
            "target_accounts": target_accounts,
            "source_hashes": {key: day_pass.get(key) for key in
                ("quote_sha256", "source_financial_sha256",
                 "source_fiscal_sha256", "source_settlements_sha256")}})
    return mapped


def build(report, mapping):
    """Derive document-level openings and a balanced residual journal."""
    blockers = []
    properties = []
    for source in report["properties"]:
        name = source["property"]
        cfg = mapping["properties"][name]
        company = cfg["company"]
        center = cfg["cost_center"]
        temporary = cfg["temporary_opening_account"]
        account_map = cfg["accounts"]
        party_map = cfg["parties"]
        accounts = {row["name"]: row for row in source["ledger"]["accounts"]}
        control = defaultdict(Decimal)
        receivables = []
        payables = []
        supplier_credits = []
        stock = []
        purchase_orders = []
        guarantees = []
        guarantee_accounts = set()
        advances = []
        advance_accounts = set()
        for row in source["open_receivables"]:
            amount = pms_cutover._decimal(row["outstanding"])
            control[row["account"]] += amount
            receivables.append({"source": row["source"], "reference": row["reference"],
                "property": name, "folio": row.get("folio"),
                "booking": row.get("booking"), "stay": row.get("stay"),
                "source_charge": row.get("source_charge"),
                "experience_order": row.get("experience_order"),
                "doctype": "Sales Invoice", "company": company, "cost_center": center,
                "customer": party_map[row["party"]]["customer"],
                "debit_to": account_map[row["account"]],
                "temporary_opening_account": temporary, "currency": source["currency"],
                "posting_date": source["business_date"],
                "due_date": row["due_date"] or source["business_date"],
                "outstanding": pms_cutover._money(amount)})
        day_passes = _day_pass_continuations(source, cfg, receivables, blockers)
        for row in source["open_payables"]:
            amount = pms_cutover._decimal(row["outstanding"])
            direction = 1 if row["kind"] == "Supplier Credit" else -1
            control[row["account"]] += direction * amount
            entry = {"source": row["source"], "source_kind": row["kind"],
                "reference": row.get("reference"), "property": name,
                "company": company,
                "cost_center": center, "supplier": party_map[row["party"]]["supplier"],
                "payable_account": account_map[row["account"]],
                "temporary_opening_account": temporary,
                "currency": source["currency"],
                "posting_date": source["business_date"],
                "outstanding": pms_cutover._money(amount)}
            if direction < 0:
                entry["doctype"] = "Purchase Invoice"
                payables.append(entry)
            else:
                # A party-linked debit to Payable is an unallocated supplier credit.
                entry["doctype"] = "Journal Entry"
                supplier_credits.append(entry)
        for row in source["stock_positions"]:
            quantity = pms_cutover._decimal(row["quantity"])
            value = pms_cutover._decimal(row["value"])
            control[row["inventory_account"]] += value
            stock.append({"source_product": row["product"],
                "source_warehouse": row["warehouse"],
                "doctype": "Stock Reconciliation", "purpose": "Opening Stock",
                "company": company, "cost_center": center,
                "item_code": cfg["products"][row["product"]],
                "warehouse": cfg["warehouses"][row["warehouse"]],
                "inventory_account": account_map[row["inventory_account"]],
                "temporary_opening_account": temporary,
                "posting_date": source["business_date"],
                "quantity": pms_cutover._money(quantity),
                "value": pms_cutover._money(value)})
        for order in source.get("open_purchase_orders", []):
            if order["status"] != "Approved" or not order["remaining"]:
                continue
            supplier = party_map.get(order["supplier"], {}).get("supplier")
            if not supplier or not frappe.db.exists("Supplier", supplier):
                blockers.append({"property": name,
                    "code": "unmapped_purchase_order_supplier",
                    "source": order["source"]})
                continue
            try:
                rate, rate_record, rate_date = _purchase_order_rate(
                    order["currency"], source["currency"],
                    source["business_date"])
            except (ValueError, TypeError):
                blockers.append({"property": name,
                    "code": "missing_purchase_order_exchange_rate",
                    "source": order["source"], "currency": order["currency"]})
                continue
            lines = []
            total_tax = Decimal(0)
            total_gross = Decimal(0)
            for line in order["remaining"]:
                target_item = cfg["products"].get(line["product"])
                target_warehouse = cfg["warehouses"].get(line["warehouse"])
                item = frappe.db.get_value("Item", target_item,
                    ["is_stock_item", "is_purchase_item", "disabled"],
                    as_dict=True) if target_item else None
                if (not item or not item.is_stock_item or
                        not item.is_purchase_item or item.disabled or
                        not target_warehouse or
                        not frappe.db.exists("Warehouse", target_warehouse)):
                    blockers.append({"property": name,
                        "code": "unmapped_purchase_order_line",
                        "source": order["source"], "line": line["line"]})
                    continue
                quantity = pms_cutover._decimal(line["quantity"])
                gross = pms_cutover._decimal(line["gross"])
                tax = pms_cutover._decimal(line["recoverable_tax"])
                net = pms_cutover._decimal(line["net"])
                if (quantity <= 0 or net <= 0 or tax < 0 or
                        net + tax != gross):
                    blockers.append({"property": name,
                        "code": "invalid_purchase_order_line_balance",
                        "source": order["source"], "line": line["line"]})
                    continue
                lines.append({"source_line": line["line"],
                    "item_code": target_item, "warehouse": target_warehouse,
                    "quantity": line["quantity"], "net": line["net"],
                    "recoverable_tax": line["recoverable_tax"],
                    "gross": line["gross"], "unit_net": str(net / quantity)})
                total_tax += tax
                total_gross += gross
            tax_account = (account_map.get(order["tax_account"])
                if order["tax_account"] else None)
            if (len(lines) != len(order["remaining"]) or
                    (total_tax and not tax_account)):
                blockers.append({"property": name,
                    "code": "unmapped_purchase_order_tax",
                    "source": order["source"]})
                continue
            total_net = total_gross - total_tax
            mixed_tax = total_tax and any(
                    pms_cutover._decimal(line["recoverable_tax"]) * total_net !=
                    pms_cutover._decimal(line["net"]) * total_tax
                    for line in lines)
            # ERPNext distributes an Actual tax over every item by net amount.
            # Keep one native order where that agrees with the source; otherwise
            # each line needs its own order to preserve tax on partial receipts.
            groups = [[line] for line in lines] if mixed_tax else [lines]
            for group in groups:
                group_tax = sum((pms_cutover._decimal(line["recoverable_tax"])
                                 for line in group), Decimal(0))
                group_gross = sum((pms_cutover._decimal(line["gross"])
                                   for line in group), Decimal(0))
                purchase_orders.append({"source": order["source"],
                    "source_line": group[0]["source_line"] if mixed_tax else None,
                    "reference": order["reference"], "property": name,
                    "company": company, "cost_center": center,
                    "supplier": supplier, "currency": order["currency"],
                    "conversion_rate": str(rate),
                    "exchange_rate_record": rate_record,
                    "exchange_rate_date": rate_date,
                    "posting_date": source["business_date"],
                    "expected_date": order["expected_date"],
                    "notes": order["notes"],
                    "requested_by": order["requested_by"],
                    "approved_by": order["approved_by"],
                    "tax_account": tax_account if group_tax else None,
                    "recoverable_tax": pms_cutover._money(group_tax),
                    "remaining_gross": pms_cutover._money(group_gross),
                    "lines": group})
        for row in source.get("open_deposits", []):
            if row["kind"] != "Guarantee":
                continue
            account = row["liability_account"]
            original_base = pms_cutover._decimal(row["original_base"])
            remaining_base = pms_cutover._decimal(row["remaining_base"])
            if (account not in accounts or
                    accounts[account]["root_type"] != "Liability" or
                    accounts[account]["account_currency"] != source["currency"] or
                    accounts[account]["account_type"] in (
                        "Payable", "Receivable", "Stock") or
                    original_base <= 0 or remaining_base <= 0 or
                    remaining_base > original_base or not row.get("party") or
                    not row.get("pms_journal") or not (
                        row.get("booking") or row.get("stay")) or
                    pms_cutover._decimal(row["exchange_rate"]) <= 0 or
                    money(pms_cutover._decimal(row["original_amount"]) *
                          pms_cutover._decimal(row["exchange_rate"]),
                          currency=source["currency"]) != original_base or
                    money(pms_cutover._decimal(row["original_amount"]) -
                          pms_cutover._decimal(row["used_base"]) /
                          pms_cutover._decimal(row["exchange_rate"]),
                          currency=row["currency"]) <= 0):
                blockers.append({"property": name, "code": "invalid_open_guarantee",
                                 "source": row["source"]})
                continue
            guarantee_accounts.add(account)
            control[account] -= original_base
            guarantees.append({"source": row["source"], "property": name,
                "doctype": "Journal Entry", "company": company,
                "cost_center": center,
                "customer": party_map[row["party"]]["customer"],
                "liability_account": account_map[account],
                "temporary_opening_account": temporary,
                "currency": source["currency"],
                "payment_currency": row["currency"],
                "exchange_rate": row["exchange_rate"],
                "original_amount": row["original_amount"],
                "original_base": row["original_base"],
                "remaining_base": row["remaining_base"],
                "used_base": row["used_base"],
                "booking": row.get("booking"), "stay": row.get("stay"),
                "folio": row.get("folio"),
                "posting_date": source["business_date"]})
        for row in source.get("open_deposits", []):
            if row["kind"] != "Advance":
                continue
            account = row["liability_account"]
            receiver = source.get("property_receivable_account")
            original_base = pms_cutover._decimal(row["original_base"])
            remaining_base = pms_cutover._decimal(row["remaining_base"])
            rate = pms_cutover._decimal(row["exchange_rate"])
            if (account not in accounts or
                    accounts[account]["root_type"] != "Liability" or
                    accounts[account]["account_currency"] != source["currency"] or
                    accounts[account]["account_type"] in
                        ("Payable", "Receivable", "Stock") or
                    receiver not in accounts or
                    accounts[receiver]["account_type"] != "Receivable" or
                    accounts[receiver]["account_currency"] != source["currency"] or
                    original_base <= 0 or remaining_base <= 0 or
                    remaining_base > original_base or rate <= 0 or
                    not row.get("party") or not row.get("pms_journal") or
                    money(pms_cutover._decimal(row["original_amount"]) * rate,
                          currency=source["currency"]) != original_base or
                    money(pms_cutover._decimal(row["original_amount"]) -
                          pms_cutover._decimal(row["used_base"]) / rate,
                          currency=row["currency"]) <= 0 or
                    not company or "erpnext" not in frappe.get_installed_apps() or
                    frappe.db.get_value("Company", company,
                        "book_advance_payments_in_separate_party_account")):
                blockers.append({"property": name, "code": "invalid_open_advance",
                                 "source": row["source"]})
                continue
            advance_accounts.add(account)
            control[account] -= remaining_base
            advances.append({"source": row["source"], "property": name,
                "doctype": "Payment Entry", "company": company,
                "cost_center": center,
                "customer": party_map[row["party"]]["customer"],
                "receivable_account": account_map[receiver],
                "liability_account": account_map[account],
                "temporary_opening_account": temporary,
                "currency": source["currency"],
                "payment_currency": row["currency"],
                "exchange_rate": row["exchange_rate"],
                "original_amount": row["original_amount"],
                "original_base": row["original_base"],
                "remaining_base": row["remaining_base"],
                "used_base": row["used_base"],
                "booking": row.get("booking"), "stay": row.get("stay"),
                "folio": row.get("folio"),
                "posting_date": source["business_date"]})
        deposit_accounts = guarantee_accounts | advance_accounts
        control_accounts = set(control) | {row["name"] for row in accounts.values()
            if row["account_type"] in ("Receivable", "Payable", "Stock")}
        for account in sorted(control_accounts):
            if account not in accounts:
                blockers.append({"property": name, "code": "control_account_missing",
                                 "account": account})
                continue
            actual = pms_cutover._decimal(accounts[account]["balance"])
            if account in deposit_accounts:
                if accounts[account]["account_currency"] != source["currency"]:
                    blockers.append({"property": name,
                        "code": "deposit_liability_currency_mismatch",
                        "account": account})
                continue
            if actual != control[account]:
                blockers.append({"property": name, "code": "planned_control_mismatch",
                    "account": account,
                    "difference": pms_cutover._money(actual - control[account])})
        journal = []
        profit_loss = []
        for account in sorted((set(accounts) - control_accounts) | deposit_accounts):
            row = accounts[account]
            opening = control[account] if account in deposit_accounts else Decimal(0)
            balance = pms_cutover._decimal(row["balance"]) - opening
            original = pms_cutover._decimal(row["original_balance"]) - opening
            if not balance and not original:
                continue
            currency = row["account_currency"] or source["currency"]
            if currency == source["currency"] and balance != original:
                blockers.append({"property": name, "code": "base_account_currency_mismatch",
                                 "account": account})
            if currency != source["currency"] and (
                    not balance or not original or (balance > 0) != (original > 0)):
                blockers.append({"property": name, "code": "foreign_account_currency_mismatch",
                                 "account": account})
            line = _signed_line(account, account_map[account], balance,
                original, currency, center)
            if currency != source["currency"] and balance and original:
                line["exchange_rate"] = pms_cutover._money(balance / original)
            (profit_loss if row["root_type"] in ("Income", "Expense")
             else journal).append(line)
        control_total = sum(control.values(), Decimal(0))
        profit_loss_net = sum((pms_cutover._decimal(row["debit"]) -
            pms_cutover._decimal(row["credit"]) for row in profit_loss), Decimal(0))
        if profit_loss_net:
            profit_loss.append(_signed_line(None, temporary, -profit_loss_net,
                -profit_loss_net, source["currency"], center))
        residual_temporary = control_total + profit_loss_net
        if residual_temporary:
            journal.append(_signed_line(None, temporary, residual_temporary,
                residual_temporary, source["currency"], center))
        debit = sum((pms_cutover._decimal(row["debit"]) for row in journal), Decimal(0))
        credit = sum((pms_cutover._decimal(row["credit"]) for row in journal), Decimal(0))
        if debit != credit:
            blockers.append({"property": name, "code": "opening_journal_unbalanced",
                "difference": pms_cutover._money(debit - credit)})
        profit_loss_debit = sum((pms_cutover._decimal(row["debit"])
                                 for row in profit_loss), Decimal(0))
        profit_loss_credit = sum((pms_cutover._decimal(row["credit"])
                                  for row in profit_loss), Decimal(0))
        if profit_loss_debit != profit_loss_credit:
            blockers.append({"property": name,
                "code": "profit_loss_transfer_unbalanced",
                "difference": pms_cutover._money(profit_loss_debit - profit_loss_credit)})
        temporary_components = (
            -sum((pms_cutover._decimal(row["outstanding"]) for row in receivables), Decimal(0))
            + sum((pms_cutover._decimal(row["outstanding"]) for row in payables), Decimal(0))
            - sum((pms_cutover._decimal(row["outstanding"]) for row in supplier_credits), Decimal(0))
            - sum((pms_cutover._decimal(row["value"]) for row in stock), Decimal(0))
            + sum((pms_cutover._decimal(row["original_base"]) for row in guarantees), Decimal(0))
            + sum((pms_cutover._decimal(row["remaining_base"]) for row in advances), Decimal(0)))
        temporary_net = temporary_components + control_total
        if temporary_net:
            blockers.append({"property": name, "code": "temporary_account_not_zero",
                             "difference": pms_cutover._money(temporary_net)})
        direct_sales = pms_cutover_direct_sales.collect(source, cfg, blockers)
        properties.append({"property": name, "organization": source["organization"],
            "company": company, "cost_center": center,
            "posting_date": source["business_date"],
            "opening_receivables": receivables, "opening_payables": payables,
            "opening_supplier_credits": supplier_credits,
            "opening_guarantees": guarantees,
            "opening_advances": advances,
            "opening_stock": stock, "purchase_orders": purchase_orders,
            "continuing_day_passes": day_passes,
            "continuing_direct_sales": direct_sales,
            "opening_journal": journal,
            "profit_loss_transfer_journal": profit_loss,
            "control_total": pms_cutover._money(control_total),
            "temporary_net": pms_cutover._money(temporary_net),
            "journal_debit": pms_cutover._money(debit),
            "journal_credit": pms_cutover._money(credit),
            "profit_loss_debit": pms_cutover._money(profit_loss_debit),
            "profit_loss_credit": pms_cutover._money(profit_loss_credit)})
    plan = {"schema_version": 4,
            "source_sha256": report["source_sha256"],
            "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
            "properties": properties}
    return {**plan, "plan_sha256": sha256(canonical(plan).encode()).hexdigest(),
            "blockers": blockers, "arithmetically_balanced": not blockers,
            "cutover_performed": False}


def review(mapping):
    """Validate target readiness and produce a plan without any target writes."""
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    checked = pms_cutover_mapping.review(mapping)
    if not checked["source_and_mapping_ready"]:
        return {"mapping_review": checked, "plan": None,
                "cutover_inputs_consistent": False,
                "cutover_performed": False}
    report = pms_cutover.preflight()
    if report["source_sha256"] != checked["source_sha256"]:
        return {"mapping_review": checked, "plan": None,
                "blockers": [{"code": "source_changed_during_review"}],
                "cutover_inputs_consistent": False,
                "cutover_performed": False}
    plan = build(report, mapping)
    links = pms_cutover_links.build(report, mapping)
    return {"mapping_review": checked, "plan": plan,
            "link_manifest": links,
            "cutover_inputs_consistent": plan["arithmetically_balanced"] and links["links_resolved"],
            "cutover_performed": False}
