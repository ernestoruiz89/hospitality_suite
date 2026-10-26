"""Read-only validation of explicit PMS to ERPNext master mappings.

No target master is created here. The validated map remains an input to a
future transfer; this module cannot switch the accounting authority.
"""

from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite import pms_cutover
from hospitality_suite.pms_cutover import preflight
from hospitality_suite.schema import ERP_LINK_TARGETS
from hospitality_suite.service import canonical


TARGET_FIELDS = {
    "warehouse": "Warehouse", "laundry_warehouse": "Warehouse",
    "receivable_account": "Account", "guarantee_account": "Account",
    "cash_transfer_account": "Account", "income_account": "Account",
    "expense_account": "Account", "petty_cash_account": "Account",
    "petty_cash_overage_account": "Account",
    "petty_cash_shortage_account": "Account",
    "lodging_item": "Item", "extra_hour_item": "Item",
    "day_pass_item": "Item", "timing_item": "Item",
    "penalty_item": "Item", "agent_commission_item": "Item",
    "tax_template": "Sales Taxes and Charges Template",
    "price_list": "Price List",
}
REQUIRED_SETTINGS = ("warehouse", "receivable_account",
                     "guarantee_account", "lodging_item", "price_list")
ACCOUNT_ROOTS = {
    "receivable_account": "Asset", "guarantee_account": "Liability",
    "cash_transfer_account": "Asset", "income_account": "Income",
    "expense_account": "Expense", "petty_cash_account": "Asset",
    "petty_cash_overage_account": "Income",
    "petty_cash_shortage_account": "Expense",
}


def _problem(problems, code, *, property_name=None, kind=None, source=None, target=None):
    row = {"code": code}
    for key, value in (("property", property_name), ("kind", kind),
                       ("source", source), ("target", target)):
        if value is not None:
            row[key] = value
    problems.append(row)


def _target(doctype, name, fields):
    if not isinstance(name, str) or not name.strip():
        return None
    meta = frappe.get_meta(doctype)
    selected = ["name"] + [field for field in fields if meta.has_field(field)]
    return frappe.db.get_value(doctype, name.strip(), selected, as_dict=True)


def _entries(problems, property_name, kind, expected, supplied):
    if not isinstance(supplied, dict):
        _problem(problems, "invalid_mapping_shape", property_name=property_name, kind=kind)
        supplied = {}
    for name in sorted(set(expected) - set(supplied)):
        _problem(problems, "missing_source_mapping", property_name=property_name,
                 kind=kind, source=name)
    for name in sorted(set(supplied) - set(expected)):
        _problem(problems, "unknown_source_mapping", property_name=property_name,
                 kind=kind, source=name)
    return supplied


def _unique_target(problems, seen, property_name, kind, source, target):
    if not isinstance(target, str) or not target.strip():
        _problem(problems, "missing_target", property_name=property_name,
                 kind=kind, source=source)
        return None
    target = target.strip()
    if target in seen:
        _problem(problems, "duplicate_target", property_name=property_name,
                 kind=kind, source=source, target=target)
    else:
        seen[target] = source
    return target


def _validate_account(problems, property_name, source, target, company, base_currency):
    row = _target("Account", target, ["company", "root_type", "account_type",
                                       "account_currency", "is_group", "disabled"])
    if not row:
        _problem(problems, "missing_target_record", property_name=property_name,
                 kind="accounts", source=source["name"], target=target)
        return
    if (company and row.company != company) or row.root_type != source["root_type"] or row.get("disabled"):
        _problem(problems, "incompatible_target_account", property_name=property_name,
                 kind="accounts", source=source["name"], target=target)
    if bool(row.is_group) != bool(source["is_group"]):
        _problem(problems, "account_group_mismatch", property_name=property_name,
                 kind="accounts", source=source["name"], target=target)
    if (row.account_currency or base_currency) != (source["account_currency"] or base_currency):
        _problem(problems, "account_currency_mismatch", property_name=property_name,
                 kind="accounts", source=source["name"], target=target)
    if source["account_type"] in ("Cash", "Bank", "Receivable", "Payable", "Stock") and (
            row.account_type != source["account_type"]):
        _problem(problems, "account_type_mismatch", property_name=property_name,
                 kind="accounts", source=source["name"], target=target)


def template():
    """Return an empty target map with every source identifier filled in."""
    report = preflight()
    properties = {}
    for source in report["properties"]:
        name = source["property"]
        required = source["mapping_requirements"]
        party_types = {row.name: row.party_type for row in frappe.get_all("HS Party",
            filters={"property": name}, fields=["name", "party_type"])}
        linen_laundry = source.get("pms_linen_laundry_warehouse")
        properties[name] = {"company": "", "cost_center": "",
            "temporary_opening_account": "",
            "target_settings": {"warehouse": "", "receivable_account": "",
                                "guarantee_account": "", "lodging_item": "",
                                "price_list": "",
                                **({"laundry_warehouse": ""} if linen_laundry else {})},
            "legacy_links": {},
            "accounts": {key: "" for key in required["accounts"]},
            "parties": {key: {
                kind: "" for kind in (("customer", "supplier")
                    if party_types[key] == "Both" else
                    ("customer",) if party_types[key] == "Customer" else ("supplier",))}
                for key in required["parties"]},
            "products": {key: "" for key in required["products"]},
            "warehouses": {key: "" for key in required["warehouses"]}}
    return {"source_sha256": report["source_sha256"], "properties": properties}


def review(mapping):
    """Check all source IDs and ERPNext target types without changing either book."""
    report = preflight()  # Sitewide permission and source-property locks.
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if not isinstance(mapping, dict):
        frappe.throw(_("El mapeo debe ser un objeto JSON"))
    properties = mapping.get("properties")
    if not isinstance(properties, dict):
        frappe.throw(_("El mapeo requiere un objeto properties"))
    problems = []
    if set(mapping) - {"source_sha256", "properties"}:
        _problem(problems, "unknown_mapping_field")
    if mapping.get("source_sha256") != report["source_sha256"]:
        _problem(problems, "stale_source_hash")
    installed = "erpnext" in frappe.get_installed_apps()
    if not installed:
        _problem(problems, "erpnext_not_installed")
    else:
        for party_type, account_type in (("Customer", "Receivable"),
                                         ("Supplier", "Payable")):
            if frappe.db.get_value("Party Type", party_type,
                                   "account_type") != account_type:
                _problem(problems, "target_party_type_account_mismatch",
                         kind=party_type)
    expected_properties = {row["property"]: row for row in report["properties"]}
    for name in sorted(set(expected_properties) - set(properties)):
        _problem(problems, "missing_property_mapping", property_name=name)
    for name in sorted(set(properties) - set(expected_properties)):
        _problem(problems, "unknown_property_mapping", property_name=name)
    companies_by_organization = {}
    organizations_by_company = {}
    cost_centers = {}
    warehouses = {}
    temporary_targets = set()
    mapped_accounts = []
    for name, source in expected_properties.items():
        cfg = properties.get(name)
        if not isinstance(cfg, dict):
            continue
        if set(cfg) - {"company", "cost_center", "temporary_opening_account", "target_settings", "legacy_links",
                       "accounts", "parties", "products", "warehouses"}:
            _problem(problems, "unknown_property_mapping_field", property_name=name)
        company = cfg.get("company")
        center = cfg.get("cost_center")
        temporary = cfg.get("temporary_opening_account")
        if not isinstance(company, str) or not company.strip():
            _problem(problems, "missing_company", property_name=name)
            company = None
        else:
            company = company.strip()
            prior = companies_by_organization.setdefault(source["organization"], company)
            if prior != company:
                _problem(problems, "organization_company_conflict", property_name=name,
                         target=company)
            prior_org = organizations_by_company.setdefault(company, source["organization"])
            if prior_org != source["organization"]:
                _problem(problems, "company_organization_conflict", property_name=name,
                         target=company)
        if not isinstance(center, str) or not center.strip():
            _problem(problems, "missing_cost_center", property_name=name)
            center = None
        else:
            center = center.strip()
            if center in cost_centers:
                _problem(problems, "duplicate_cost_center", property_name=name, target=center)
            else:
                cost_centers[center] = name
        if not isinstance(temporary, str) or not temporary.strip():
            _problem(problems, "missing_temporary_opening_account", property_name=name)
            temporary = None
        else:
            temporary = temporary.strip()
            temporary_targets.add(temporary)
        target_settings = cfg.get("target_settings")
        if not isinstance(target_settings, dict):
            _problem(problems, "invalid_target_settings", property_name=name)
            target_settings = {}
        for field in REQUIRED_SETTINGS:
            target = target_settings.get(field)
            if not isinstance(target, str) or not target.strip():
                _problem(problems, "missing_target_setting",
                         property_name=name, kind=field)
        for field in sorted(set(target_settings) - set(TARGET_FIELDS) -
                            {"tax_policy_confirmed"}):
            _problem(problems, "unknown_target_setting",
                     property_name=name, kind=field)
        if ("tax_policy_confirmed" in target_settings and
                not isinstance(target_settings["tax_policy_confirmed"], bool)):
            _problem(problems, "invalid_tax_review_setting", property_name=name)
        if installed:
            for field, doctype in TARGET_FIELDS.items():
                if doctype == "Warehouse":
                    continue  # Scope and cross-property ownership are checked below.
                target = target_settings.get(field)
                if target in (None, ""):
                    continue
                if not isinstance(target, str) or target != target.strip():
                    _problem(problems, "invalid_target_setting",
                             property_name=name, kind=field, target=str(target))
                    continue
                row = _target(doctype, target,
                    ["company", "is_group", "disabled", "root_type",
                     "account_type", "account_currency"] if doctype == "Account"
                    else ["company", "is_group", "disabled"])
                if (not row or (row.get("company") and row.company != company) or
                        row.get("is_group") or row.get("disabled")):
                    _problem(problems, "incompatible_target_setting",
                             property_name=name, kind=field, target=target)
                    continue
                if doctype == "Account" and (
                        row.root_type != ACCOUNT_ROOTS[field] or
                        row.account_currency != source["currency"] or
                        (field == "receivable_account" and
                         row.account_type != "Receivable")):
                    _problem(problems, "incompatible_target_account_role",
                             property_name=name, kind=field, target=target)
                if field == "price_list":
                    details = _target("Price List", target,
                        ["enabled", "selling", "currency"])
                    if (not details or not details.enabled or not details.selling or
                            details.currency != source["currency"]):
                        _problem(problems, "incompatible_target_price_list",
                                 property_name=name, kind=field, target=target)
        configured_warehouses = []
        for field in ("warehouse", "laundry_warehouse"):
            target = target_settings.get(field)
            if target in (None, ""):
                continue
            if not isinstance(target, str) or target != target.strip():
                _problem(problems, "invalid_target_warehouse",
                         property_name=name, kind=field, target=str(target))
                continue
            configured_warehouses.append(target)
            prior_property = warehouses.setdefault(target, name)
            if prior_property != name:
                _problem(problems, "warehouse_shared_between_properties",
                         property_name=name, kind=field, target=target)
            if installed:
                row = _target("Warehouse", target,
                    ["company", "is_group", "disabled", "hs_property"])
                if (not row or (company and row.company != company) or
                        row.is_group or row.get("disabled")):
                    _problem(problems, "incompatible_target_warehouse",
                             property_name=name, kind=field, target=target)
                elif row.get("hs_property") and row.hs_property != name:
                    _problem(problems, "target_warehouse_property_conflict",
                             property_name=name, kind=field, target=target)
        if len(configured_warehouses) == 2 and len(set(configured_warehouses)) != 2:
            _problem(problems, "target_warehouses_not_distinct",
                     property_name=name, kind="warehouses",
                     target=configured_warehouses[0])
        account_map = cfg.get("accounts")
        account_map = account_map if isinstance(account_map, dict) else {}
        for source_field, target_field, code in (
                ("property_receivable_account", "receivable_account",
                 "receivable_setting_account_mismatch"),
                ("property_petty_cash_account", "petty_cash_account",
                 "petty_cash_setting_account_mismatch"),
                ("property_petty_cash_overage_account",
                 "petty_cash_overage_account",
                 "petty_cash_overage_account_mismatch"),
                ("property_petty_cash_shortage_account",
                 "petty_cash_shortage_account",
                 "petty_cash_shortage_account_mismatch")):
            source_account = source.get(source_field)
            if source_account:
                mapped = account_map.get(source_account)
                if not mapped or target_settings.get(target_field) != mapped:
                    _problem(problems, code, property_name=name,
                             kind=target_field, source=source_account,
                             target=target_settings.get(target_field))
        if (source.get("pms_linen_operating_warehouse") and
                source.get("pms_linen_laundry_warehouse")):
            warehouse_map = cfg.get("warehouses")
            warehouse_map = warehouse_map if isinstance(warehouse_map, dict) else {}
            for source_field, target_field, code in (
                    ("pms_linen_operating_warehouse", "warehouse",
                     "linen_operating_warehouse_mismatch"),
                    ("pms_linen_laundry_warehouse", "laundry_warehouse",
                     "linen_laundry_warehouse_mismatch")):
                source_warehouse = source[source_field]
                mapped = warehouse_map.get(source_warehouse)
                if not mapped or target_settings.get(target_field) != mapped:
                    _problem(problems, code, property_name=name,
                             kind="warehouses", source=source_warehouse,
                             target=target_settings.get(target_field))
        if installed:
            import erpnext
            needed_vouchers = {"Journal Entry"}
            if source["open_receivables"]:
                needed_vouchers.add("Sales Invoice")
            if any(row["kind"] != "Supplier Credit" for row in source["open_payables"]):
                needed_vouchers.add("Purchase Invoice")
            if source["stock_positions"]:
                needed_vouchers.add("Stock Reconciliation")
            for doctype in sorted(needed_vouchers):
                if not frappe.get_meta(doctype).has_field("hs_property"):
                    _problem(problems, "target_missing_hospitality_scope",
                             property_name=name, kind=doctype)
            if source["open_receivables"]:
                for field in ("hs_folio", "hs_booking", "hs_stay"):
                    if not frappe.get_meta("Sales Invoice").has_field(field):
                        _problem(problems, "target_missing_hospitality_invoice_field",
                                 property_name=name, kind=field)
            if source["open_receivables"] or any(
                    row["kind"] != "Supplier Credit" for row in source["open_payables"]):
                from erpnext.stock.utils import get_default_stock_uom
                if not get_default_stock_uom():
                    _problem(problems, "target_missing_opening_invoice_uom",
                             property_name=name)

            if company:
                company_row = _target("Company", company, ["default_currency", "is_group"])
                if not company_row or company_row.default_currency != source["currency"] or company_row.is_group:
                    _problem(problems, "incompatible_company", property_name=name, target=company)
                elif frappe.db.exists("Period Closing Voucher", {"company": company,
                        "docstatus": 1}):
                    _problem(problems, "target_company_has_period_close",
                             property_name=name, target=company)
                if company_row and not frappe.db.sql(
                        "SELECT fy.name FROM `tabFiscal Year` fy "
                        "WHERE fy.disabled=0 AND fy.year_start_date<=%s "
                        "AND fy.year_end_date>=%s AND ("
                        "NOT EXISTS (SELECT 1 FROM `tabFiscal Year Company` fya "
                        "WHERE fya.parent=fy.name) OR EXISTS ("
                        "SELECT 1 FROM `tabFiscal Year Company` fyc "
                        "WHERE fyc.parent=fy.name AND fyc.company=%s)) LIMIT 1",
                        (source["business_date"], source["business_date"], company)):
                    _problem(problems, "target_fiscal_year_missing",
                             property_name=name, target=company)
                if company_row and source["stock_positions"] and not erpnext.is_perpetual_inventory_enabled(company):
                    _problem(problems, "perpetual_inventory_required",
                             property_name=name, target=company)
            if center:
                center_row = _target("Cost Center", center, ["company", "is_group", "disabled"])
                if not center_row or (company and center_row.company != company) or center_row.is_group or center_row.get("disabled"):
                    _problem(problems, "incompatible_cost_center", property_name=name, target=center)
                elif company and frappe.db.exists("GL Entry", {"company": company,
                        "cost_center": center, "is_cancelled": 0}):
                    _problem(problems, "target_cost_center_has_postings",
                             property_name=name, target=center)
            if temporary:
                temp_row = _target("Account", temporary,
                    ["company", "account_type", "account_currency", "report_type",
                     "is_group", "disabled"])
                if (not temp_row or (company and temp_row.company != company) or
                        temp_row.account_type != "Temporary" or temp_row.is_group or
                        temp_row.get("disabled") or temp_row.report_type != "Balance Sheet" or
                        (temp_row.account_currency or source["currency"]) != source["currency"]):
                    _problem(problems, "incompatible_temporary_opening_account",
                             property_name=name, target=temporary)
                elif company:
                    balance = frappe.db.sql(
                        "SELECT COALESCE(SUM(debit-credit),0) FROM `tabGL Entry` "
                        "WHERE company=%s AND account=%s AND is_cancelled=0",
                        (company, temporary), as_list=True)[0][0]
                    if pms_cutover._decimal(balance):
                        _problem(problems, "temporary_opening_account_not_empty",
                                 property_name=name, target=temporary)
        legacy = cfg.get("legacy_links", {})
        if not isinstance(legacy, dict):
            _problem(problems, "invalid_legacy_link_mapping", property_name=name)
            legacy = {}
        for target_type, entries in legacy.items():
            if target_type not in set(ERP_LINK_TARGETS.values()) - {"Company"} or not isinstance(entries, dict):
                _problem(problems, "invalid_legacy_link_mapping", property_name=name,
                         kind=str(target_type))
                continue
            for old, target in entries.items():
                if not isinstance(old, str) or not old or not isinstance(target, str) or not target:
                    _problem(problems, "invalid_legacy_link_mapping", property_name=name,
                             kind=target_type, source=str(old))
                    continue
                if installed:
                    row = _target(target_type, target, ["company", "is_group", "disabled"])
                    if (not row or (row.get("company") and company and row.company != company)
                            or row.get("is_group") or row.get("disabled")):
                        _problem(problems, "incompatible_legacy_link_target",
                                 property_name=name, kind=target_type,
                                 source=old, target=target)
        for kind in ("accounts", "parties", "products", "warehouses"):
            expected = source["mapping_requirements"][kind]
            supplied = _entries(problems, name, kind, expected, cfg.get(kind))
            seen = {}
            source_rows = {}
            if kind == "accounts":
                source_rows = {row["name"]: row for row in source["ledger"]["accounts"]}
            elif kind == "parties":
                source_rows = {row.name: row for row in frappe.get_all("HS Party",
                    filters={"property": name}, fields=["name", "party_type"])}
            elif kind == "products":
                source_rows = {row.name: row for row in frappe.get_all("HS Product",
                    filters={"property": name}, fields=["name", "product_type"])}
            for source_name in expected:
                if source_name not in supplied:
                    continue
                selected = supplied[source_name]
                if kind == "parties":
                    if not isinstance(selected, dict):
                        _problem(problems, "invalid_mapping_shape", property_name=name,
                                 kind=kind, source=source_name)
                        continue
                    types = ("customer", "supplier") if source_rows[source_name].party_type == "Both" else (
                        "customer",) if source_rows[source_name].party_type == "Customer" else ("supplier",)
                    for party_kind in types:
                        target = _unique_target(problems, seen.setdefault(party_kind, {}),
                            name, party_kind, source_name, selected.get(party_kind))
                        if installed and target:
                            doctype = "Customer" if party_kind == "customer" else "Supplier"
                            row = _target(doctype, target, ["disabled"])
                            if not row or row.get("disabled"):
                                _problem(problems, "missing_target_record", property_name=name,
                                         kind=party_kind, source=source_name, target=target)
                    continue
                target = _unique_target(problems, seen, name, kind, source_name, selected)
                if target and kind == "accounts":
                    mapped_accounts.append((name, source_name, target))
                if target and kind == "warehouses":
                    prior_property = warehouses.setdefault(target, name)
                    if prior_property != name:
                        _problem(problems, "warehouse_shared_between_properties",
                                 property_name=name, kind=kind, source=source_name,
                                 target=target)
                if not installed or not target:
                    continue
                if kind == "accounts":
                    _validate_account(problems, name, source_rows[source_name], target,
                                      company, source["currency"])
                elif kind == "products":
                    row = _target("Item", target, ["is_stock_item", "is_fixed_asset", "disabled"])
                    stock = source_rows[source_name].product_type == "Stock"
                    asset = source_rows[source_name].product_type == "Asset"
                    if not row or bool(row.is_stock_item) != stock or bool(row.is_fixed_asset) != asset or row.get("disabled"):
                        _problem(problems, "incompatible_item", property_name=name,
                                 kind=kind, source=source_name, target=target)
                else:
                    row = _target("Warehouse", target,
                        ["company", "is_group", "disabled", "hs_property"])
                    if not row or (company and row.company != company) or row.is_group or row.get("disabled"):
                        _problem(problems, "incompatible_warehouse", property_name=name,
                                 kind=kind, source=source_name, target=target)
                    elif frappe.db.exists("Stock Ledger Entry", {"warehouse": target,
                            "is_cancelled": 0}):
                        _problem(problems, "target_warehouse_has_stock", property_name=name,
                                 kind=kind, source=source_name, target=target)
                    elif not frappe.get_meta("Warehouse").has_field("hs_property") or (
                            row.get("hs_property") and row.hs_property != name):
                        _problem(problems, "target_warehouse_property_conflict",
                                 property_name=name, kind=kind,
                                 source=source_name, target=target)
        if installed:
            from erpnext.stock import get_warehouse_account

            warehouse_map = cfg.get("warehouses") if isinstance(cfg.get("warehouses"), dict) else {}
            account_map = cfg.get("accounts") if isinstance(cfg.get("accounts"), dict) else {}
            for position in source["stock_positions"]:
                warehouse_name = warehouse_map.get(position["warehouse"])
                mapped_account = account_map.get(position["inventory_account"])
                if not warehouse_name or not mapped_account or not frappe.db.exists("Warehouse", warehouse_name):
                    continue
                warehouse_doc = frappe.get_doc("Warehouse", warehouse_name)
                actual_account = get_warehouse_account(warehouse_doc, raise_error=False)
                if actual_account != mapped_account:
                    _problem(problems, "warehouse_inventory_account_mismatch",
                             property_name=name, kind="warehouses",
                             source=position["warehouse"], target=warehouse_name)
    for property_name, source_name, target in mapped_accounts:
        if target in temporary_targets:
            _problem(problems, "temporary_account_reused", property_name=property_name,
                     kind="accounts", source=source_name, target=target)
    return {"source_sha256": report["source_sha256"],
            "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
            "source_blockers": report["blockers"], "mapping_blockers": problems,
            "mapping_complete": not problems,
            "source_and_mapping_ready": not problems and not report["blockers"],
            "cutover_performed": False}
