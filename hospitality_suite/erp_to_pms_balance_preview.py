"""Read-only monetary review of a verified ERPNext-to-PMS source inventory.

The result is intentionally not a posting request. Stock, open invoices and
customer funds need native target records before an opening entry is safe.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

import frappe

from hospitality_suite import erp_fiscal_history, erp_to_pms_mapping
from hospitality_suite.ledger_rules import LedgerValidationError, currency_line, normalize_lines
from hospitality_suite.service import canonical
from hospitality_suite.stock_rules import StockValidationError, quantity


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("non-finite decimal")
    return result


def _text(value):
    return format(value, "f")


def _problem(problems, code, **details):
    problems.append({"code": code, **details})


def _account_line(row, cfg, prop, precision, problems):
    source_account = row.get("account")
    target_account = cfg["accounts"].get(source_account)
    if not target_account:
        _problem(problems, "missing_gl_account_mapping", property=prop,
                 account=source_account)
        return None
    try:
        base = _decimal(row["debit"]) - _decimal(row["credit"])
        original = _decimal(row["original_balance"])
        if base == original == 0:
            return None
        if (not base or not original or (base > 0) != (original > 0)):
            raise ValueError("base and account currency have incompatible signs")
        quantum = Decimal(1).scaleb(-precision)
        if base != base.quantize(quantum) or original != original.quantize(quantum):
            raise ValueError("amount exceeds target precision")
        party_type, source_party = row.get("party_type"), row.get("party")
        if source_party:
            kind = {"Customer": "customers", "Supplier": "suppliers"}.get(party_type)
            if not kind or not cfg[kind].get(source_party):
                raise ValueError("unmapped or unsupported GL party")
            target_party = cfg[kind][source_party]
        else:
            if party_type:
                raise ValueError("GL party type without party")
            target_party = None
        currency = row.get("account_currency") or row.get("currency")
        if not currency:
            raise ValueError("account currency missing")
        line = {"account": target_account, "party": target_party,
                "debit": _text(max(base, Decimal(0))),
                "credit": _text(max(-base, Decimal(0))),
                "account_currency": currency,
                "debit_in_account_currency": _text(max(original, Decimal(0))),
                "credit_in_account_currency": _text(max(-original, Decimal(0)))}
        if currency != row["base_currency"]:
            rate = (abs(base) / abs(original)).quantize(
                Decimal("0.000000001"), rounding=ROUND_HALF_UP)
            line["exchange_rate"] = _text(rate)
        checked = currency_line(line, currency, row["base_currency"], precision)
        return {"source_account": source_account,
                "source_cost_center": row.get("cost_center"),
                "source_party_type": party_type,
                "source_party": source_party, **checked}
    except (KeyError, ValueError, InvalidOperation, LedgerValidationError) as exc:
        _problem(problems, "unrepresentable_gl_balance", property=prop,
                 account=source_account, party=row.get("party"), reason=str(exc))
        return None


def _stock_positions(source, cfg, prop, precision, balances, problems):
    positions = source["stock"].get("positions")
    if not isinstance(positions, list):
        _problem(problems, "invalid_source_stock", property=prop)
        return []
    products = {row.name: row for row in frappe.get_all("HS Product",
        filters={"name": ["in", list(cfg["products"].values())]},
        fields=["name", "property", "product_type", "inventory_account"],
        limit_page_length=0)} if cfg["products"] else {}
    values = defaultdict(Decimal)
    result = []
    quantum = Decimal(1).scaleb(-precision)
    for row in positions:
        if not isinstance(row, dict):
            _problem(problems, "invalid_source_stock_position", property=prop)
            continue
        try:
            target_product = cfg["products"][row["item"]]
            target_warehouse = cfg["warehouses"][row["warehouse"]]
            product = products[target_product]
            if (product.property != cfg["property"] or
                    product.product_type != "Stock" or not product.inventory_account):
                raise ValueError("target stock product lacks an inventory account")
            qty = quantity(row["quantity"])
            value = _decimal(row["stock_value"])
            if qty <= 0 or value <= 0 or value != value.quantize(quantum):
                raise ValueError("stock quantity or value is not postable")
            account = frappe.db.get_value("HS Account", product.inventory_account,
                ["property", "root_type", "account_currency", "active"], as_dict=True)
            if (not account or account.property != cfg["property"] or
                    account.root_type != "Asset" or
                    account.account_currency != source["currency"] or not account.active):
                raise ValueError("target inventory account is invalid")
            values[product.inventory_account] += value
            result.append({"source_item": row["item"],
                "source_warehouse": row["warehouse"], "product": target_product,
                "warehouse": target_warehouse,
                "inventory_account": product.inventory_account,
                "quantity": _text(qty), "stock_value": _text(value)})
        except (KeyError, ValueError, InvalidOperation, StockValidationError) as exc:
            _problem(problems, "unrepresentable_stock_position", property=prop,
                     item=row.get("item"), warehouse=row.get("warehouse"),
                     reason=str(exc))
    for account, value in sorted(values.items()):
        ledger_value = balances.get(account, Decimal(0))
        if ledger_value != value:
            _problem(problems, "stock_ledger_value_mismatch", property=prop,
                     account=account, stock_value=_text(value),
                     ledger_balance=_text(ledger_value))
    return result


def preview(file_name, expected_source_sha256, expected_manifest_sha256, mapping):
    """Verify the map, then calculate only balances that PMS can represent."""
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    review = erp_to_pms_mapping.review(file_name, expected_source_sha256,
                                      expected_manifest_sha256, mapping)
    result = {"source_sha256": expected_source_sha256,
        "mapping_sha256": review["mapping_sha256"],
        "ready_for_transfer": False, "posted": False,
        "blockers": list(review["blockers"]), "properties": []}
    if not review["mapping_ready"]:
        return result
    _, inventory = erp_fiscal_history.load_source_inventory(file_name,
        expected_source_sha256, expected_manifest_sha256)
    precision = frappe.utils.get_currency_precision() or 2
    for source in inventory["properties"]:
        name = source["property"]
        cfg = mapping["properties"][name]
        problems = []
        if (not isinstance(source.get("ledger"), dict) or
                not isinstance(source["ledger"].get("lines"), list) or
                not isinstance(source.get("stock"), dict) or
                not isinstance(source.get("open_receivables"), list) or
                not isinstance(source.get("open_payables"), list) or
                not isinstance(source.get("deposits"), dict) or
                not isinstance(source.get("open_operations"), dict)):
            _problem(problems, "source_financial_inventory_missing", property=name)
            result["properties"].append({"source_property": name,
                "target_property": cfg["property"], "net_balances": [],
                "stock_positions": [], "blockers": problems})
            result["blockers"].extend(problems)
            continue
        gl = source["ledger"]
        balances = defaultdict(Decimal)
        lines = []
        centers = set()
        try:
            debit = sum((_decimal(row["debit"]) for row in gl["lines"]), Decimal(0))
            credit = sum((_decimal(row["credit"]) for row in gl["lines"]), Decimal(0))
            if (debit != _decimal(gl["debit"]) or credit != _decimal(gl["credit"]) or
                    debit != credit):
                raise ValueError("GL header and line totals differ")
        except (KeyError, TypeError, ValueError) as exc:
            _problem(problems, "source_gl_totals_mismatch", property=name,
                     reason=str(exc))
        for source_line in gl["lines"]:
            if not isinstance(source_line, dict):
                _problem(problems, "invalid_source_gl_line", property=name)
                continue
            row = {**source_line, "base_currency": source["currency"]}
            candidate = _account_line(row, cfg, name, precision, problems)
            if candidate:
                lines.append(candidate)
                balances[candidate["account"]] += (
                    _decimal(candidate["debit"]) - _decimal(candidate["credit"]))
                if candidate["source_cost_center"]:
                    centers.add(candidate["source_cost_center"])
        if len(centers) > 1:
            _problem(problems, "multiple_source_cost_centers", property=name,
                     cost_centers=sorted(centers))
        try:
            if lines:
                normalize_lines(lines, precision)
            if sum(balances.values(), Decimal(0)):
                raise LedgerValidationError("source net balances are not balanced")
        except LedgerValidationError as exc:
            _problem(problems, "unbalanced_opening_balances", property=name,
                     reason=str(exc))
        stock = _stock_positions(source, cfg, name, precision, balances, problems)
        detail = {"source_property": name, "target_property": cfg["property"],
            "currency": source["currency"], "net_balances": lines,
            "stock_positions": stock,
            "open_receivables": len(source["open_receivables"]),
            "open_payables": len(source["open_payables"]),
            "customer_credits": len(source["deposits"].get("customer_credits", [])),
            "guarantees": len(source["deposits"].get("guarantees", [])),
            "open_operations": {key: len(rows) for key, rows in
                                source["open_operations"].items()},
            "blockers": problems}
        result["properties"].append(detail)
        result["blockers"].extend(problems)
    result["preview_sha256"] = sha256(canonical(result["properties"]).encode()).hexdigest()
    return result
