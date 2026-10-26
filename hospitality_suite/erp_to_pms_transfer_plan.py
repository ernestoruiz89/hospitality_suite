"""Read-only decomposition of ERPNext balances into PMS opening operations.

The temporary account represents each native opening document's counterpart.
The residual journal clears it. This module does not publish either operation.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256

import frappe

from hospitality_suite import (erp_fiscal_history, erp_to_pms_balance_preview,
                               erp_to_pms_operations)
from hospitality_suite.ledger_rules import (LedgerValidationError, amount,
                                            normalize_lines, rate_for_base)
from hospitality_suite.service import canonical


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


def _problem(blockers, property_name, code, **details):
    blockers.append({"property": property_name, "code": code, **details})


def _control(prop, cfg, records, balances, kind, source, source_account,
             source_party, party_kind, signed_value, currency, precision,
             signed_original=None, **details):
    try:
        target_account = cfg["accounts"][source_account]
        target_party = cfg[party_kind][source_party] if party_kind else None
        value = _decimal(signed_value)
        if not value:
            raise ValueError("zero opening document")
        amount(abs(value), precision)
        original = _decimal(signed_original) if signed_original is not None else value
        amount(abs(original), precision)
        if not original or (original > 0) != (value > 0):
            raise ValueError("opening base and account amounts have incompatible signs")
        if currency == prop["currency"] and original != value:
            raise ValueError("base-currency opening differs from payment ledger")
        if currency != prop["currency"]:
            if (kind not in ("opening_payables", "opening_receivables",
                             "opening_customer_credits", "opening_supplier_credits",
                             "opening_advances") or
                    frappe.db.get_value("HS Account", target_account,
                                        "account_currency") != currency):
                raise ValueError("foreign open document needs account-currency settlement"
                    f" (base {value}, account {original} {currency})")
            rate_for_base(abs(original), abs(value), precision)
    except (KeyError, ValueError, LedgerValidationError) as exc:
        _problem(records["blockers"], prop["property"],
                 "unrepresentable_open_document", kind=kind, source=source,
                 reason=str(exc))
        return
    key = (target_account, target_party)
    balances[key] += value
    records[kind].append({"source": source, "source_account": source_account,
        "account": target_account, "source_party": source_party,
        "party": target_party, "currency": currency,
        "signed_base_balance": _text(value),
        "signed_account_balance": _text(original), **details})


def _temporary_line(account, value, currency):
    return {"source_account": None, "source_cost_center": None,
        "source_party_type": None, "source_party": None,
        "account": account, "party": None, "account_currency": currency,
        "exchange_rate": "1", "debit": _text(max(value, Decimal(0))),
        "credit": _text(max(-value, Decimal(0))),
        "debit_in_account_currency": _text(max(value, Decimal(0))),
        "credit_in_account_currency": _text(max(-value, Decimal(0)))}


def _property_plan(source, preview, cfg, precision):
    name = source["property"]
    records = {"opening_receivables": [], "opening_customer_credits": [],
        "opening_payables": [], "opening_supplier_credits": [],
        "opening_advances": [], "opening_guarantees": [],
        "opening_stock": [], "blockers": []}
    operation_counts = {key: len(rows) for key, rows in
        (source.get("open_operations") or {}).items()
        if isinstance(rows, list)} if isinstance(
            source.get("open_operations"), dict) else {}
    operational = erp_to_pms_operations.plan(source, cfg,
        frappe.get_doc("HS Property", cfg["property"]))
    records["operational_rows"] = operational["rows"]
    records["blockers"].extend(operational["blockers"])
    open_folios = {row["name"]: row for row in
        operational["rows"]["folios"]}
    controls = defaultdict(Decimal)
    accounts = cfg["accounts"]
    for row in source["open_receivables"]:
        try:
            outstanding = _decimal(row["outstanding_amount"])
        except (KeyError, ValueError) as exc:
            _problem(records["blockers"], name, "invalid_open_receivable",
                     source=row.get("name"), reason=str(exc))
            continue
        if not outstanding:
            continue
        source_folio = row.get("folio")
        if source_folio and (row.get("folio_property") != name or
                row.get("folio_company") != source["company"] or
                row.get("folio_customer") != row.get("party") or
                row.get("folio_currency") != source["currency"] or
                row.get("folio_status") not in ("Open", "Closed")):
            _problem(records["blockers"], name,
                "open_invoice_folio_source_mismatch", source=row["name"],
                folio=source_folio)
            continue
        target_folio = open_folios.get(source_folio)
        if (source_folio and row.get("folio_status") == "Open" and
                not target_folio):
            _problem(records["blockers"], name,
                "open_invoice_folio_not_restored", source=row["name"],
                folio=source_folio)
            continue
        if target_folio and (row.get("folio_status") != "Open" or
                (outstanding > 0 and (
                target_folio.get("customer") !=
                    cfg["customers"].get(row.get("party")) or
                target_folio.get("currency") != source["currency"] or
                row.get("stay") and target_folio.get("stay") != row["stay"] or
                row.get("booking") and
                    target_folio.get("booking") != row["booking"]))):
            _problem(records["blockers"], name,
                "open_invoice_folio_mismatch", source=row["name"],
                folio=source_folio)
            continue
        _control(source, cfg, records, controls,
            "opening_receivables" if outstanding > 0 else "opening_customer_credits",
            row["name"], row["account"], row["party"], "customers",
            row.get("base_outstanding_amount", row["outstanding_amount"]),
            row["account_currency"], precision,
            signed_original=outstanding,
            due_date=row.get("due_date"), posting_date=row.get("posting_date"),
            is_return=bool(row.get("is_return")),
            source_folio=source_folio,
            folio=target_folio["name"] if target_folio and outstanding > 0
                else None)
    for row in source["open_payables"]:
        try:
            outstanding = _decimal(row["outstanding_amount"])
        except (KeyError, ValueError) as exc:
            _problem(records["blockers"], name, "invalid_open_payable",
                     source=row.get("name"), reason=str(exc))
            continue
        if not outstanding:
            continue
        _control(source, cfg, records, controls,
            "opening_payables" if outstanding > 0 else "opening_supplier_credits",
            row["name"], row["account"], row["party"], "suppliers",
            -_decimal(row.get("base_outstanding_amount", row["outstanding_amount"])),
            row["account_currency"], precision,
            signed_original=-outstanding,
            due_date=row.get("due_date"), posting_date=row.get("posting_date"),
            is_return=bool(row.get("is_return")))
    for row in source["deposits"].get("customer_credits", []):
        try:
            available = _decimal(row["available"])
        except (KeyError, ValueError) as exc:
            _problem(records["blockers"], name, "invalid_customer_credit",
                     source=row.get("voucher"), reason=str(exc))
            continue
        if not available:
            continue
        base_available = row.get("base_available")
        if base_available is None and row["account_currency"] == source["currency"]:
            base_available = row["available"]
        if (row["account_currency"] != source["currency"] and
                (row.get("voucher_type") != "Payment Entry" or
                 base_available is None)):
            _problem(records["blockers"], name,
                "unrepresentable_foreign_advance", source=row["voucher"])
            continue
        if base_available is None:
            _problem(records["blockers"], name,
                "unverified_advance_base_balance", source=row["voucher"])
            continue
        _control(source, cfg, records, controls, "opening_advances",
            row["voucher"], row["receivable_account"], row["customer"],
            "customers", -_decimal(base_available),
            row["account_currency"], precision,
            signed_original=-available,
            voucher_type=row.get("voucher_type"),
            sources=row.get("sources", []))
    for row in source["deposits"].get("guarantees", []):
        try:
            book = _decimal(row["base_balance"])
        except (KeyError, ValueError) as exc:
            _problem(records["blockers"], name, "invalid_guarantee",
                     source=row.get("source"), reason=str(exc))
            continue
        if not book:
            continue
        try:
            nominal = _decimal(row["nominal"])
            if (book <= 0 or nominal != book or
                    row.get("currency") != source["currency"] or
                    row.get("customer") not in cfg["customers"] or
                    not row.get("liability_account") or
                    not (row.get("folio") or row.get("booking"))):
                raise ValueError("guarantee identity or base-currency balance mismatch")
        except (KeyError, ValueError) as exc:
            _problem(records["blockers"], name, "unrepresentable_guarantee",
                     source=row.get("source"), reason=str(exc))
            continue
        _control(source, cfg, records, controls, "opening_guarantees",
            row["source"], row["liability_account"], None, None,
            -book, source["currency"], precision,
            customer=cfg["customers"].get(row.get("customer")),
            nominal=row.get("nominal"), payment_currency=row.get("currency"),
            booking=row.get("booking"), stay=row.get("stay"),
            folio=row.get("folio"))
    for row in preview["stock_positions"]:
        target_account = row["inventory_account"]
        value = _decimal(row["stock_value"])
        controls[(target_account, None)] += value
        records["opening_stock"].append({**row,
            "signed_base_balance": _text(value)})

    control_accounts = {accounts[row["name"]] for row in
        source["mapping_requirements"]["accounts"]
        if row.get("account_type") in ("Receivable", "Payable", "Stock") and
           row["name"] in accounts}
    control_accounts.update(account for account, _ in controls)
    actual = defaultdict(Decimal)
    for line in preview["net_balances"]:
        actual[(line["account"], line["party"])] += (
            _decimal(line["debit"]) - _decimal(line["credit"]))
    for key in sorted(set(controls) | {key for key in actual
                                   if key[0] in control_accounts},
                      key=lambda value: (value[0], value[1] or "")):
        expected, found = controls[key], actual[key]
        if found != expected:
            _problem(records["blockers"], name, "opening_control_mismatch",
                     account=key[0], party=key[1],
                     source_balance=_text(found), planned_balance=_text(expected))
    residual = [line for line in preview["net_balances"]
                if line["account"] not in control_accounts]
    control_total = sum(controls.values(), Decimal(0))
    if control_total:
        residual.append(_temporary_line(cfg["temporary_opening_account"],
                                        control_total, source["currency"]))
    try:
        if residual:
            normalize_lines(residual, precision)
    except LedgerValidationError as exc:
        _problem(records["blockers"], name,
                 "residual_opening_journal_unbalanced", reason=str(exc))
    temporary_net = -control_total + control_total
    return {"source_property": name, "target_property": cfg["property"],
        "currency": source["currency"], "posting_date": source["business_date"],
        "temporary_opening_account": cfg["temporary_opening_account"],
        **records, "open_operation_counts": operation_counts,
        "residual_journal": residual,
        "control_total": _text(control_total),
        "temporary_net": _text(temporary_net)}


def review(file_name, expected_source_sha256, expected_manifest_sha256, mapping):
    """Reconcile native opening documents with GL and a zero bridge account."""
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    inspected = erp_to_pms_balance_preview.preview(file_name,
        expected_source_sha256, expected_manifest_sha256, mapping)
    result = {"schema_version": 1,
        "source_sha256": expected_source_sha256,
        "mapping_sha256": inspected["mapping_sha256"],
        "balance_preview_sha256": inspected.get("preview_sha256"),
        "properties": [], "blockers": list(inspected["blockers"]),
        "arithmetically_balanced": False,
        "ready_for_transfer": False, "posted": False}
    if inspected["blockers"]:
        return result
    _, inventory = erp_fiscal_history.load_source_inventory(file_name,
        expected_source_sha256, expected_manifest_sha256)
    by_name = {row["source_property"]: row for row in inspected["properties"]}
    precision = frappe.utils.get_currency_precision() or 2
    for source in inventory["properties"]:
        plan = _property_plan(source, by_name[source["property"]],
                              mapping["properties"][source["property"]], precision)
        result["properties"].append(plan)
        result["blockers"].extend(plan["blockers"])
    result["arithmetically_balanced"] = not result["blockers"]
    result["ready_for_transfer"] = result["arithmetically_balanced"]
    frozen = {key: result[key] for key in ("schema_version", "source_sha256",
        "mapping_sha256", "balance_preview_sha256", "properties")}
    result["plan_sha256"] = sha256(canonical(frozen).encode()).hexdigest()
    return result
