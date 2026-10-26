"""Read-only target mapping review for a verified ERPNext source bundle.

This review identifies valid PMS masters and confirms that the printable fiscal
history is present. It deliberately cannot publish balances or switch books.
"""

from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite import erp_fiscal_history
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider
from hospitality_suite.standalone_currency import enabled


KINDS = {
    "accounts": ("HS Account", ["name", "property", "organization", "root_type",
        "account_type", "account_currency", "is_group", "active"]),
    "products": ("HS Product", ["name", "property", "organization",
        "product_type", "active"]),
    "customers": ("HS Party", ["name", "property", "organization",
        "party_type", "active"]),
    "suppliers": ("HS Party", ["name", "property", "organization",
        "party_type", "active"]),
    "warehouses": ("HS Warehouse", ["name", "property", "organization", "active"]),
    "categories": ("HS Category", ["name", "property", "company"]),
    "rooms": ("HS Room", ["name", "property", "company", "category", "active"]),
    "rates": ("HS Rate", ["name", "property", "company", "category",
        "currency", "mode", "active"]),
    "guests": ("HS Guest", ["name", "property", "company", "customer"]),
    "travel_agents": ("HS Travel Agent", ["name", "property", "company",
        "agent_type", "pms_supplier", "active"]),
    "experiences": ("HS Experience", ["name", "property", "company",
        "experience_category", "pms_product", "active"]),
    "laundry_rates": ("HS Laundry Rate", ["name", "property", "company",
        "garment", "service_type", "currency", "pms_product", "active"]),
    "users": ("User", ["name", "enabled"]),
    "equipment": ("HS Equipment", ["name", "property", "company",
        "room", "active"]),
}


def _requirements(source):
    result = {}
    for prop in source["properties"]:
        requirement = prop.get("mapping_requirements")
        if not isinstance(requirement, dict):
            frappe.throw(_("El paquete requiere un diagnóstico ERPNext más reciente"))
        expected = {"accounts": requirement.get("accounts"),
            "products": requirement.get("products"),
            "customers": requirement.get("parties", {}).get("Customer"),
            "suppliers": requirement.get("parties", {}).get("Supplier"),
            "warehouses": requirement.get("warehouses"),
            "categories": requirement.get("categories"),
            "rooms": requirement.get("rooms"),
            "rates": requirement.get("rates"),
            "guests": requirement.get("guests"),
            "travel_agents": requirement.get("travel_agents", []),
            "experiences": requirement.get("experiences", []),
            "laundry_rates": requirement.get("laundry_rates", []),
            "users": requirement.get("users", []),
            "equipment": requirement.get("equipment", [])}
        if any(not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("name"), str)
                for row in rows) for rows in expected.values()):
            frappe.throw(_("El diagnóstico contiene maestros de origen inválidos"))
        result[prop["property"]] = {key: {row["name"]: row for row in rows}
                                    for key, rows in expected.items()}
    return result


def template(file_name, expected_source_sha256, expected_manifest_sha256):
    if provider() != "pms":
        frappe.throw(_("El mapa de destino requiere un sitio PMS"))
    _, source = erp_fiscal_history.load_source_inventory(file_name,
        expected_source_sha256, expected_manifest_sha256)
    requirements = _requirements(source)
    return {"source_sha256": expected_source_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "properties": {name: {"property": "", "temporary_opening_account": "", **{
            kind: {source_name: "" for source_name in rows}
            for kind, rows in kinds.items()}}
            for name, kinds in requirements.items()}}


def _problem(problems, code, **details):
    problems.append({"code": code, **details})


def _review_kind(kind, sources, mapping, prop, source_currency, problems):
    dt, fields = KINDS[kind]
    if not isinstance(mapping, dict):
        _problem(problems, "invalid_mapping_section", property=prop.name,
                 kind=kind)
        return {}
    for source in sorted(set(sources) - set(mapping)):
        _problem(problems, "missing_master_mapping", property=prop.name,
                 kind=kind, source=source)
    for source in sorted(set(mapping) - set(sources)):
        _problem(problems, "unknown_master_mapping", property=prop.name,
                 kind=kind, source=source)
    names = [value for value in mapping.values() if isinstance(value, str)
             and value and value == value.strip()]
    found = {row.name: row for row in frappe.get_all(dt,
        filters={"name": ["in", sorted(set(names))]}, fields=fields,
        limit_page_length=0)} if names else {}
    seen = set()
    valid = {}
    for source, source_row in sources.items():
        target = mapping.get(source)
        if not isinstance(target, str) or not target.strip() or target != target.strip():
            _problem(problems, "missing_master_target", property=prop.name,
                     kind=kind, source=source)
            continue
        if target in seen:
            _problem(problems, "duplicate_master_target", property=prop.name,
                     kind=kind, source=source, target=target)
            continue
        seen.add(target)
        row = found.get(target)
        if (not row or kind != "users" and row.property != prop.name or
                ("organization" in row and
                row.organization != prop.organization) or ("company" in row and
                row.company != prop.company) or ("active" in row and not row.active) or
                ("is_group" in row and row.is_group)):
            _problem(problems, "invalid_master_target", property=prop.name,
                     kind=kind, source=source, target=target)
            continue
        if kind == "accounts":
            expected_currency = source_row.get("account_currency") or source_currency
            expected_type = source_row.get("account_type") or "General"
            if (row.root_type != source_row.get("root_type") or
                    (row.account_currency or prop.currency) != expected_currency or
                    row.account_type != expected_type or
                    not enabled(prop, expected_currency)):
                _problem(problems, "account_nature_mismatch", property=prop.name,
                         source=source, target=target)
                continue
        elif kind == "products":
            expected_type = ("Asset" if source_row.get("is_fixed_asset") else
                "Stock" if source_row.get("is_stock_item") else "Service")
            if row.product_type != expected_type:
                _problem(problems, "product_type_mismatch", property=prop.name,
                         source=source, target=target)
                continue
        elif kind in ("customers", "suppliers"):
            accepted = ("Customer", "Both") if kind == "customers" else ("Supplier", "Both")
            if row.party_type not in accepted:
                _problem(problems, "party_type_mismatch", property=prop.name,
                         kind=kind, source=source, target=target)
                continue
        elif kind == "rates":
            if row.currency != source_row.get("currency") or row.mode != source_row.get("mode"):
                _problem(problems, "rate_currency_or_mode_mismatch",
                         property=prop.name, source=source, target=target)
                continue
        elif kind == "travel_agents":
            if row.agent_type != source_row.get("agent_type"):
                _problem(problems, "travel_agent_type_mismatch",
                         property=prop.name, source=source, target=target)
                continue
        elif kind == "experiences":
            if row.experience_category != source_row.get("experience_category"):
                _problem(problems, "experience_category_mismatch",
                         property=prop.name, source=source, target=target)
                continue
        elif kind == "laundry_rates":
            if (row.garment != source_row.get("garment") or
                    row.service_type != source_row.get("service_type") or
                    row.currency != source_row.get("currency")):
                _problem(problems, "laundry_rate_terms_mismatch",
                         property=prop.name, source=source, target=target)
                continue
        valid[source] = row
    return valid


def _relations(kinds, valid, prop, problems):
    for kind in ("rooms", "rates"):
        for source, row in kinds[kind].items():
            target = valid[kind].get(source)
            source_category = row.get("category")
            if not target or not source_category:
                continue
            mapped_category = valid["categories"].get(source_category)
            if not mapped_category or target.category != mapped_category.name:
                _problem(problems, "category_relation_mismatch",
                         property=prop.name, kind=kind, source=source,
                         category=source_category)
    for source, row in kinds["guests"].items():
        target = valid["guests"].get(source)
        source_customer = row.get("customer")
        mapped_customer = valid["customers"].get(source_customer)
        if source_customer and target and (
                not mapped_customer or target.customer != mapped_customer.name):
            _problem(problems, "guest_customer_relation_mismatch",
                     property=prop.name, source=source,
                     customer=source_customer)
    for source, row in kinds["travel_agents"].items():
        target = valid["travel_agents"].get(source)
        source_supplier = row.get("supplier")
        mapped_supplier = valid["suppliers"].get(source_supplier)
        if source_supplier and target and (
                not mapped_supplier or target.pms_supplier != mapped_supplier.name):
            _problem(problems, "agent_supplier_relation_mismatch",
                     property=prop.name, source=source,
                     supplier=source_supplier)
    for source, row in kinds["experiences"].items():
        target = valid["experiences"].get(source)
        source_item = row.get("item")
        mapped_product = valid["products"].get(source_item)
        if target and (not source_item or not mapped_product or
                target.pms_product != mapped_product.name):
            _problem(problems, "experience_product_relation_mismatch",
                     property=prop.name, source=source, item=source_item)
    for source, row in kinds["laundry_rates"].items():
        target = valid["laundry_rates"].get(source)
        source_item = row.get("item")
        mapped_product = valid["products"].get(source_item)
        if target and (not source_item or not mapped_product or
                target.pms_product != mapped_product.name):
            _problem(problems, "laundry_product_relation_mismatch",
                     property=prop.name, source=source, item=source_item)
    for source, row in kinds["equipment"].items():
        target = valid["equipment"].get(source)
        source_room = row.get("room")
        mapped_room = valid["rooms"].get(source_room)
        if source_room and target and (
                not mapped_room or target.room != mapped_room.name):
            _problem(problems, "equipment_room_relation_mismatch",
                     property=prop.name, source=source, room=source_room)


def _fiscal_archive(manifest, mapping, problems):
    counts = {"expected": len(manifest["documents"]), "verified": 0}
    for row in manifest["documents"]:
        cfg = mapping.get(row["property"])
        target_property = cfg.get("property") if isinstance(cfg, dict) else None
        if not target_property:
            continue
        name = frappe.db.get_value(erp_fiscal_history.DOCTYPE,
            {"source_key": row["source_key"]}, "name")
        if not name:
            _problem(problems, "missing_fiscal_archive",
                     property=row["property"], source=row["source_name"])
            continue
        doc = frappe.get_doc(erp_fiscal_history.DOCTYPE, name)
        if (doc.property != target_property or
                doc.snapshot_sha256 != row["snapshot_sha256"] or
                doc.pdf_sha256 != row["pdf_sha256"]):
            _problem(problems, "fiscal_archive_mismatch",
                     property=row["property"], source=row["source_name"])
            continue
        try:
            erp_fiscal_history._verified_content(doc)
        except (frappe.ValidationError, FileNotFoundError):
            _problem(problems, "fiscal_pdf_missing_or_changed",
                     property=row["property"], source=row["source_name"])
            continue
        counts["verified"] += 1
    return counts


def review(file_name, expected_source_sha256, expected_manifest_sha256, mapping):
    """Validate an explicit map without creating a target master or posting."""
    if provider() != "pms":
        frappe.throw(_("El mapa de destino requiere un sitio PMS"))
    manifest, source = erp_fiscal_history.load_source_inventory(file_name,
        expected_source_sha256, expected_manifest_sha256)
    requirements = _requirements(source)
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if not isinstance(mapping, dict) or not isinstance(mapping.get("properties"), dict):
        frappe.throw(_("El mapa debe tener un objeto properties"))
    problems = []
    if set(mapping) - {"source_sha256", "manifest_sha256", "properties"}:
        _problem(problems, "unknown_mapping_field")
    if (mapping.get("source_sha256") != expected_source_sha256 or
            mapping.get("manifest_sha256") != expected_manifest_sha256):
        _problem(problems, "stale_mapping_hash")
    configs = mapping["properties"]
    for name in sorted(set(requirements) - set(configs)):
        _problem(problems, "missing_property_mapping", property=name)
    for name in sorted(set(configs) - set(requirements)):
        _problem(problems, "unknown_property_mapping", property=name)
    for source_blocker in source["blockers"]:
        if source_blocker.get("code") != "reverse_transfer_not_implemented":
            _problem(problems, "source_blocker", detail=source_blocker)
    destinations = set()
    organizations_by_source_company = {}
    for source_prop in source["properties"]:
        name = source_prop["property"]
        cfg = configs.get(name)
        if not isinstance(cfg, dict):
            _problem(problems, "invalid_property_mapping", property=name)
            continue
        if set(cfg) - {"property", "temporary_opening_account", *KINDS}:
            _problem(problems, "unknown_property_mapping_field", property=name)
        target_name = cfg.get("property")
        if (not isinstance(target_name, str) or not target_name.strip() or
                target_name != target_name.strip()):
            _problem(problems, "missing_target_property", property=name)
            continue
        if target_name in destinations:
            _problem(problems, "duplicate_target_property", property=name,
                     target=target_name)
            continue
        destinations.add(target_name)
        if not frappe.db.exists("HS Property", target_name):
            _problem(problems, "unknown_target_property", property=name,
                     target=target_name)
            continue
        prop = frappe.get_doc("HS Property", target_name)
        prior_org = organizations_by_source_company.setdefault(
            source_prop["company"], prop.organization)
        if prior_org != prop.organization:
            _problem(problems, "company_organization_conflict",
                     property=name, target=target_name)
        org = frappe.db.get_value("HS Organization", prop.organization,
            ["active", "base_currency"], as_dict=True) if prop.organization else None
        if (prop.currency != source_prop["currency"] or not org or not org.active or
                org.base_currency != prop.currency):
            _problem(problems, "target_entity_currency_mismatch",
                     property=name, target=target_name)
        if str(prop.business_date) != str(source_prop.get("business_date")):
            _problem(problems, "target_business_date_mismatch",
                     property=name, target=target_name,
                     source_date=source_prop.get("business_date"),
                     target_date=str(prop.business_date))
        if any(frappe.db.exists(dt, {"property": target_name}) for dt in
               ("HS Journal", "HS Stock Movement", "HS PMS Receivable",
                "HS PMS Opening Payable", "HS PMS Opening Credit",
                "HS PMS Opening Supplier Credit", "HS PMS Opening Guarantee",
                "HS PMS Supplier Credit Allocation",
                "HS PMS Purchase", "HS Payment", "HS Shift", "HS Daily Close",
                "HS PMS Fiscal Document", "HS Treasury Movement")):
            _problem(problems, "target_has_financial_history",
                     property=name, target=target_name)
        if any(frappe.db.exists(dt, {"property": target_name}) for dt in
               ("HS Booking", "HS Stay", "HS Folio", "HS Charge",
                "HS Allocation", "HS Portal Request", "HS Day Pass",
                "HS Service Request", "HS Experience Order", "HS Laundry Order",
                "HS Room Block", "HS Maintenance Order", "HS Cleaning Task")):
            _problem(problems, "target_has_operational_history",
                     property=name, target=target_name)
        kinds = requirements[name]
        valid = {kind: _review_kind(kind, rows, cfg.get(kind), prop,
                                  source_prop["currency"], problems)
                 for kind, rows in kinds.items()}
        _relations(kinds, valid, prop, problems)
        temporary_name = cfg.get("temporary_opening_account")
        temporary = frappe.db.get_value("HS Account", temporary_name,
            ["property", "organization", "root_type", "account_type",
             "account_currency", "active", "is_group", "is_cash", "is_bank"],
            as_dict=True) if isinstance(temporary_name, str) and temporary_name else None
        if (not temporary or temporary.property != prop.name or
                temporary.organization != prop.organization or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                not temporary.active or temporary.is_group or
                temporary.is_cash or temporary.is_bank or
                temporary_name in (cfg["accounts"].values()
                    if isinstance(cfg.get("accounts"), dict) else ())):
            _problem(problems, "invalid_temporary_opening_account",
                     property=name, target=temporary_name)
    fiscal = _fiscal_archive(manifest, configs, problems)
    digest = sha256(canonical(mapping).encode()).hexdigest()
    return {"source_sha256": expected_source_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "mapping_sha256": digest, "mapping_ready": not problems,
        "ready_for_transfer": False, "blockers": problems,
        "fiscal_archive": fiscal, "target_count": len(destinations)}
