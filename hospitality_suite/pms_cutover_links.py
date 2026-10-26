"""Inventory operational and ERPNext Link fields containing PMS identifiers.

The manifest covers Link fields, accepted JSON snapshots, and pending booked
experiences. It includes historical Link records while preserving accepted
amounts. Applying it is part of the caller's cutover transaction.
"""

from decimal import Decimal
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite.schema import ERP_LINK_TARGETS, SCHEMA
from hospitality_suite.security import is_system
from hospitality_suite.service import canonical


MASTER_MAPS = {"Account": "accounts", "Item": "products",
               "Warehouse": "warehouses"}
PARTY_MAPS = {"Customer": "customer", "Supplier": "supplier"}
LEGACY_DEFAULT_PRINT_FIELDS = {"invoice_print_format", "receipt_print_format"}
SNAPSHOT_FIELDS = {
    "HS Booking": {"quote_snapshot"},
    "HS Allocation": {"quote_snapshot"},
    "HS Stay": {"quote_snapshot", "service_entitlements"},
}
SNAPSHOT_LINKS = {"item": "Item", "lodging_item": "Item",
    "extra_hour_item": "Item", "timing_item": "Item",
    "day_pass_item": "Item", "penalty_item": "Item",
    "customer": "Customer", "company": "Company"}


def _grouped_values(doctype, field, child):
    # Identifiers below come only from the installed schema, never from input.
    table = f"`tab{doctype}`"
    column = f"`{field}`"
    if child:
        sql = (f"SELECT parenttype,parent,{column} AS old_value,COUNT(*) AS row_count "
               f"FROM {table} WHERE {column} IS NOT NULL AND {column}!='' "
               f"GROUP BY parenttype,parent,{column} ORDER BY parenttype,parent,{column}")
    else:
        property_column = "name" if doctype == "HS Property" else "property"
        sql = (f"SELECT `{property_column}` AS property,{column} AS old_value,"
               f"COUNT(*) AS row_count FROM {table} "
               f"WHERE {column} IS NOT NULL AND {column}!='' "
               f"GROUP BY `{property_column}`,{column} "
               f"ORDER BY `{property_column}`,{column}")
    return frappe.db.sql(sql, as_dict=True)


def _property_for_child(row, cache):
    key = (row.parenttype, row.parent)
    if key not in cache:
        parenttype, parent = key
        if parenttype == "HS Property":
            cache[key] = parent
        elif not frappe.db.exists("DocType", parenttype) or not frappe.get_meta(parenttype).has_field("property"):
            cache[key] = None
        else:
            cache[key] = frappe.db.get_value(parenttype, parent, "property")
    return cache[key]


def _resolve(target_type, old, cfg, source):
    if target_type == "Company":
        return cfg["company"] if old == source["organization"] else None
    if target_type in MASTER_MAPS:
        mapped = cfg[MASTER_MAPS[target_type]].get(old)
        if mapped:
            return mapped
    if target_type in PARTY_MAPS:
        party = cfg["parties"].get(old)
        mapped = party.get(PARTY_MAPS[target_type]) if isinstance(party, dict) else None
        if mapped:
            return mapped
    if target_type == "Cost Center" and old == cfg["cost_center"]:
        return cfg["cost_center"]
    legacy = cfg.get("legacy_links") or {}
    return legacy.get(target_type, {}).get(old) if isinstance(legacy, dict) and isinstance(
        legacy.get(target_type), dict) else None


def _target_fields():
    fields = dict(ERP_LINK_TARGETS)
    # Standalone PMS DocTypes deliberately keep company as Data. Their scope
    # must still follow the property when its ERPNext Company is activated.
    for row in frappe.get_all("DocType", filters={"module": "Hospitality Suite"},
            fields=["name"], limit_page_length=0):
        meta = frappe.get_meta(row.name)
        if not meta.istable and meta.has_field("property") and meta.has_field("company"):
            fields.setdefault((row.name, "company"), "Company")
    return fields


def _snapshot_sources(source):
    operations = source.get("open_operations") or {}
    for row in operations.get("bookings", []):
        yield "HS Booking", row["name"], "quote_snapshot", row["quote_sha256"]
    for row in operations.get("stays", []):
        yield "HS Stay", row["name"], "quote_snapshot", row["quote_sha256"]
        yield ("HS Stay", row["name"], "service_entitlements",
               row["entitlements_sha256"])
    allocations = {}
    for kind in ("bookings", "stays"):
        for row in operations.get(kind, []):
            for allocation in row["allocations"]:
                allocations[allocation["name"]] = allocation
    for name in sorted(allocations):
        row = allocations[name]
        yield "HS Allocation", name, "quote_snapshot", row["quote_sha256"]


def _rewrite_snapshot(value, cfg, source, blockers, context):
    source_products = set(source["mapping_requirements"]["products"])
    source_parties = set(source["mapping_requirements"]["parties"])
    changes = []

    def walk(node, path):
        if isinstance(node, list):
            return [walk(child, [*path, index]) for index, child in enumerate(node)]
        if not isinstance(node, dict):
            return node
        pms_product = node.get("pms_product")
        if isinstance(pms_product, str) and pms_product:
            target = (_resolve("Item", pms_product, cfg, source)
                      if pms_product in source_products else None)
            item = frappe.db.get_value("Item", target,
                ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
                as_dict=True) if target else None
            if (not item or not item.is_sales_item or item.is_stock_item or
                    item.is_fixed_asset or item.disabled or
                    node.get("item") not in (None, "", target)):
                blockers.append({**context, "code": "unmapped_pms_experience_snapshot",
                                 "path": [*path, "pms_product"],
                                 "source": pms_product})
            else:
                node = {**node, "item": target, "pms_product": None}
                changes.extend((
                    {"path": [*path, "item"], "target_type": "Item",
                     "source": None, "target": target},
                    {"path": [*path, "pms_product"], "target_type": "Item",
                     "source": pms_product, "target": None}))
        result = {}
        for key, child in node.items():
            field_path = [*path, key]
            target_type = SNAPSHOT_LINKS.get(key)
            source_identifier = isinstance(child, str) and (
                target_type == "Item" and child in source_products or
                target_type == "Customer" and child in source_parties or
                target_type == "Company" and child == source["organization"])
            if target_type and isinstance(child, str) and source_identifier:
                target = _resolve(target_type, child, cfg, source)
                if not target or not frappe.db.exists(target_type, target):
                    blockers.append({**context, "code": "unmapped_snapshot_link",
                                     "path": field_path, "target_type": target_type,
                                     "source": child})
                    result[key] = child
                else:
                    result[key] = target
                    if target != child:
                        changes.append({"path": field_path, "target_type": target_type,
                                        "source": child, "target": target})
                continue
            if target_type and isinstance(child, str) and child:
                legacy_type = ("HS Product" if target_type == "Item" else
                               "HS Party" if target_type == "Customer" else
                               "HS Organization")
                if frappe.db.exists(legacy_type, child):
                    blockers.append({**context, "code": "foreign_snapshot_link",
                                     "path": field_path, "target_type": target_type,
                                     "source": child})
            result[key] = walk(child, field_path)
        return result

    return walk(value, []), changes


def _snapshot_manifest(sources, mapping, blockers):
    rewrites = []
    for property_name, source in sorted(sources.items()):
        cfg = mapping["properties"].get(property_name)
        if not isinstance(cfg, dict):
            continue
        for doctype, name, field, expected_hash in _snapshot_sources(source):
            context = {"property": property_name, "doctype": doctype,
                       "name": name, "field": field}
            row = frappe.db.get_value(doctype, name, ["property", field],
                                      as_dict=True)
            if (not row or row.property != property_name or
                    sha256(str(row.get(field) or "").encode()).hexdigest() != expected_hash):
                blockers.append({**context, "code": "snapshot_changed"})
                continue
            original = row.get(field) or ""
            if not original:
                continue
            try:
                value = frappe.parse_json(original)
            except (TypeError, ValueError):
                blockers.append({**context, "code": "invalid_snapshot_json"})
                continue
            rewritten, changes = _rewrite_snapshot(value, cfg, source,
                                                    blockers, context)
            if changes:
                result = canonical(rewritten)
                rewrites.append({**context, "before": original, "after": result,
                    "before_sha256": expected_hash,
                    "after_sha256": sha256(result.encode()).hexdigest(),
                    "changes": changes})
    return rewrites


def _experience_manifest(sources, mapping, blockers):
    rewrites = []
    for property_name, source in sorted(sources.items()):
        cfg = mapping["properties"].get(property_name)
        if not isinstance(cfg, dict):
            continue
        for doctype, filters in (
                ("HS Experience", {"property": property_name,
                                   "pms_product": ["is", "set"]}),
                ("HS Experience Order", {"property": property_name,
                    "status": ["in", ["Reserved", "Confirmed"]]})):
            for row in frappe.get_all(doctype, filters=filters,
                    fields=["name", "pms_product", "item"],
                    order_by="name asc", limit_page_length=0):
                product = row.pms_product
                if not product:
                    if not row.item:
                        blockers.append({"code": "experience_without_item",
                            "property": property_name, "doctype": doctype,
                            "source": row.name})
                    continue
                target = cfg["products"].get(product)
                item = frappe.db.get_value("Item", target,
                    ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
                    as_dict=True) if target else None
                if (product not in source["mapping_requirements"]["products"] or
                        not item or not item.is_sales_item or item.is_stock_item or
                        item.is_fixed_asset or item.disabled or
                        (row.item and row.item != target)):
                    blockers.append({"code": "unmapped_experience_product",
                        "property": property_name, "doctype": doctype,
                        "source": row.name, "product": product})
                    continue
                if not row.item:
                    rewrites.append({"property": property_name, "doctype": doctype,
                        "name": row.name, "source_product": product,
                        "target_item": target})
    return rewrites


def _laundry_manifest(sources, mapping, blockers):
    """Carry accepted PMS laundry work into the native ERPNext item flow."""
    rewrites = []
    for property_name, source in sorted(sources.items()):
        cfg = mapping["properties"].get(property_name)
        if not isinstance(cfg, dict):
            continue
        rates = frappe.get_all("HS Laundry Rate", filters={
            "property": property_name}, fields=["name", "pms_product", "item"],
            order_by="name asc", limit_page_length=0)
        orders = frappe.get_all("HS Laundry Order", filters={
            "property": property_name,
            "status": ["in", ["Requested", "Collected", "In Process", "Ready"]]},
            fields=["name"], order_by="name asc", limit_page_length=0)
        order_names = [row.name for row in orders]
        items = (frappe.get_all("HS Laundry Order Item", filters={
            "parenttype": "HS Laundry Order", "parent": ["in", order_names]},
            fields=["name", "parent", "pms_product", "item"],
            order_by="parent asc,idx asc", limit_page_length=0)
            if order_names else [])
        for doctype, rows in (("HS Laundry Rate", rates),
                              ("HS Laundry Order Item", items)):
            for row in rows:
                product = row.pms_product
                if not product and row.item:
                    native = frappe.db.get_value("Item", row.item,
                        ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
                        as_dict=True)
                    if native and native.is_sales_item and not native.is_stock_item and not native.is_fixed_asset and not native.disabled:
                        continue
                target = cfg["products"].get(product) if product else None
                source_product = frappe.db.get_value("HS Product", product,
                    ["property", "product_type"], as_dict=True) if product else None
                item = frappe.db.get_value("Item", target,
                    ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
                    as_dict=True) if target else None
                if (not product or
                        product not in source["mapping_requirements"]["products"] or
                        not source_product or source_product.property != property_name or
                        source_product.product_type != "Service" or
                        not item or not item.is_sales_item or item.is_stock_item or
                        item.is_fixed_asset or item.disabled or
                        (row.item and row.item != target)):
                    blockers.append({"code": "unmapped_laundry_product",
                        "property": property_name, "doctype": doctype,
                        "source": row.name, "product": product})
                    continue
                if not row.item:
                    rewrites.append({"property": property_name,
                        "doctype": doctype, "name": row.name,
                        "parent": row.parent if doctype == "HS Laundry Order Item" else None,
                        "source_product": product, "target_item": target})
    return rewrites


def _agent_manifest(sources, mapping, blockers):
    rewrites = []
    for property_name, source in sorted(sources.items()):
        cfg = mapping["properties"].get(property_name)
        if not isinstance(cfg, dict):
            continue
        for row in frappe.get_all("HS Travel Agent", filters={
                "property": property_name, "pms_supplier": ["is", "set"]},
                fields=["name", "pms_supplier", "supplier"],
                order_by="name asc", limit_page_length=0):
            target = _resolve("Supplier", row.pms_supplier, cfg, source)
            supplier = frappe.db.get_value("Supplier", target, "disabled") if target else None
            if (row.pms_supplier not in source["mapping_requirements"]["parties"] or
                    supplier is None or supplier or
                    (row.supplier and row.supplier != target)):
                blockers.append({"code": "unmapped_travel_agent_supplier",
                    "property": property_name, "source": row.name,
                    "pms_supplier": row.pms_supplier})
            elif not row.supplier:
                rewrites.append({"property": property_name, "name": row.name,
                    "source_party": row.pms_supplier, "target_supplier": target})
    return rewrites


def _credit_terms(row):
    return {"credit_authorized": int(bool(row.credit_authorized)),
            "credit_limit": str(Decimal(str(row.credit_limit or 0))),
            "credit_days": int(row.credit_days or 0),
            "valid_until": str(row.credit_valid_until) if row.credit_valid_until else None}


def _billing_party_manifest(sources, mapping, blockers):
    creations = []
    for property_name, source in sorted(sources.items()):
        cfg = mapping["properties"].get(property_name)
        if not isinstance(cfg, dict):
            continue
        for party in frappe.get_all("HS Party", filters={"property": property_name,
                "party_type": ["in", ["Customer", "Both"]], "active": 1},
                fields=["name", "party_type", "credit_authorized", "credit_limit",
                        "credit_days", "credit_valid_until", "credit_reason"],
                order_by="name asc", limit_page_length=0):
            target = _resolve("Customer", party.name, cfg, source)
            if not target or not frappe.db.exists("Customer", target):
                blockers.append({"code": "unmapped_billing_party_customer",
                    "property": property_name, "source": party.name})
                continue
            terms = _credit_terms(party)
            existing = frappe.get_all("HS Billing Party", filters={
                "property": property_name,
                "customer": ["in", sorted({party.name, target})]},
                fields=["name", "company", "customer", "credit_authorized",
                        "credit_limit", "credit_days", "valid_until", "reason"],
                limit_page_length=2)
            if existing:
                current = existing[0]
                if (len(existing) != 1 or
                        current.company not in (source["organization"], cfg["company"]) or
                        _credit_terms(frappe._dict({**dict(current),
                            "credit_valid_until": current.valid_until})) != terms or
                        (party.credit_reason and current.reason != party.credit_reason)):
                    blockers.append({"code": "billing_party_policy_conflict",
                        "property": property_name, "source": party.name,
                        "target": target})
                continue
            creations.append({"property": property_name,
                "company": cfg["company"], "source_party": party.name,
                "target_customer": target, "terms": terms,
                "reason": party.credit_reason or
                    "Migrado desde HS Party " + party.name})
    return creations


def build(report, mapping):
    """Return grouped rewrites, retained ERP links, and unresolved sources."""
    sources = {row["property"]: row for row in report["properties"]}
    parent_properties = {}
    rewrites = []
    retained = []
    blockers = []
    for (doctype, field), target_type in sorted(_target_fields().items()):
        if not frappe.db.exists("DocType", doctype) or not frappe.get_meta(doctype).has_field(field):
            blockers.append({"code": "missing_link_schema", "doctype": doctype,
                             "field": field})
            continue
        child = bool(SCHEMA.get(doctype, {}).get("child") or frappe.get_meta(doctype).istable)
        for row in _grouped_values(doctype, field, child):
            property_name = (_property_for_child(row, parent_properties)
                             if child else row.property)
            old = str(row.old_value)
            count = int(row.row_count)
            if property_name not in sources:
                blockers.append({"code": "link_without_property", "doctype": doctype,
                    "field": field, "source": old, "property": property_name,
                    "parent": row.parent if child else None})
                continue
            source = sources[property_name]
            cfg = mapping["properties"].get(property_name)
            if not isinstance(cfg, dict):
                blockers.append({"code": "missing_property_mapping", "property": property_name})
                continue
            target = _resolve(target_type, old, cfg, source)
            # Earlier PMS setup stored "Standard" as a pseudo format. ERPNext
            # Link fields need a real Print Format; an empty value selects the
            # Suite's default invoice or receipt format after activation.
            clear_legacy_default = (doctype == "HS Property" and
                field in LEGACY_DEFAULT_PRINT_FIELDS and
                target_type == "Print Format" and old == "Standard" and
                not target and not frappe.db.exists("Print Format", old))
            if not target and frappe.db.exists("DocType", target_type) and frappe.db.exists(target_type, old):
                if target_type == "Company":
                    target = old if old == cfg["company"] else None
                elif target_type == "Cost Center":
                    target = old if old == cfg["cost_center"] else None
                elif target_type in ("Account", "Warehouse"):
                    target = old if frappe.db.get_value(target_type, old, "company") == cfg["company"] else None
                else:
                    target = old
            if clear_legacy_default:
                target = ""
            if not target and not clear_legacy_default:
                blockers.append({"code": "unmapped_existing_link", "property": property_name,
                    "doctype": doctype, "field": field, "target_type": target_type,
                    "source": old, "count": count})
                continue
            if not frappe.db.exists("DocType", target_type) or (target and not frappe.db.exists(target_type, target)):
                blockers.append({"code": "missing_link_target", "property": property_name,
                    "doctype": doctype, "field": field, "target_type": target_type,
                    "source": old, "target": target, "count": count})
                continue
            entry = {"property": property_name, "doctype": doctype, "field": field,
                     "target_type": target_type, "source": old, "target": target,
                     "count": count}
            if child:
                entry.update(parenttype=row.parenttype, parent=row.parent)
            (retained if old == target else rewrites).append(entry)
    snapshot_rewrites = _snapshot_manifest(sources, mapping, blockers)
    experience_rewrites = _experience_manifest(sources, mapping, blockers)
    laundry_rewrites = _laundry_manifest(sources, mapping, blockers)
    agent_rewrites = _agent_manifest(sources, mapping, blockers)
    billing_party_creations = _billing_party_manifest(sources, mapping, blockers)
    payload = {"schema_version": 7, "source_sha256": report["source_sha256"],
               "rewrites": rewrites, "snapshot_rewrites": snapshot_rewrites,
               "experience_rewrites": experience_rewrites,
               "laundry_rewrites": laundry_rewrites,
               "agent_rewrites": agent_rewrites,
               "billing_party_creations": billing_party_creations,
               "retained": retained, "blockers": blockers}
    return {**payload, "link_sha256": sha256(canonical(payload).encode()).hexdigest(),
            "links_resolved": not blockers, "cutover_performed": False}


def apply(manifest, expected_hash):
    """Rewrite a verified manifest inside the caller's cutover transaction.

    This function never commits. The caller must lock all properties, compare a
    freshly rebuilt manifest, submit ERP documents, and reconcile before use.
    """
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede aplicar enlaces del corte"),
                     frappe.PermissionError)
    payload = {key: manifest[key] for key in (
        "schema_version", "source_sha256", "rewrites", "snapshot_rewrites",
        "experience_rewrites", "laundry_rewrites", "agent_rewrites",
        "billing_party_creations",
        "retained", "blockers")}
    digest = sha256(canonical(payload).encode()).hexdigest()
    if (manifest.get("link_sha256") != digest or expected_hash != digest or
            manifest.get("schema_version") != 7 or
            manifest.get("blockers") or not manifest.get("links_resolved")):
        frappe.throw(_("El manifiesto de enlaces cambió o conserva bloqueos"))
    allowed = _target_fields()
    updated = 0
    for row in manifest["rewrites"]:
        doctype, field = row["doctype"], row["field"]
        target_type = allowed.get((doctype, field))
        clear_legacy_default = (doctype == "HS Property" and
            field in LEGACY_DEFAULT_PRINT_FIELDS and
            target_type == "Print Format" and row["source"] == "Standard" and
            row["target"] == "" and not frappe.db.exists("Print Format", "Standard"))
        if (not target_type or target_type != row["target_type"] or
                row["source"] == row["target"] or
                (not clear_legacy_default and
                 not frappe.db.exists(target_type, row["target"]))):
            frappe.throw(_("El destino de un enlace del corte dejó de ser válido"))
        child = bool(SCHEMA.get(doctype, {}).get("child") or frappe.get_meta(doctype).istable)
        if child:
            parent = frappe._dict(parenttype=row["parenttype"], parent=row["parent"])
            if _property_for_child(parent, {}) != row["property"]:
                frappe.throw(_("La tabla hija cambió de establecimiento durante el corte"))
            where = "`parenttype`=%s AND `parent`=%s"
            scope = (row["parenttype"], row["parent"])
        elif doctype == "HS Property":
            where = "`name`=%s"
            scope = (row["property"],)
        else:
            where = "`property`=%s"
            scope = (row["property"],)
        table = f"`tab{doctype}`"
        column = f"`{field}`"
        count = frappe.db.sql(
            f"SELECT COUNT(*) FROM {table} WHERE {where} AND {column}=%s",
            (*scope, row["source"]), as_list=True)[0][0]
        if int(count) != int(row["count"]):
            frappe.throw(_("La cantidad de enlaces cambió durante el corte"))
        # Preserve creation/modified timestamps on historical immutable rows.
        frappe.db.sql(f"UPDATE {table} SET {column}=%s WHERE {where} AND {column}=%s",
                      (row["target"], *scope, row["source"]))
        remaining = frappe.db.sql(
            f"SELECT COUNT(*) FROM {table} WHERE {where} AND {column}=%s",
            (*scope, row["source"]), as_list=True)[0][0]
        if remaining:
            frappe.throw(_("No se pudieron reemplazar todos los enlaces del corte"))
        updated += int(count)
    snapshot_updated = 0
    for row in manifest["snapshot_rewrites"]:
        doctype, field = row["doctype"], row["field"]
        if (field not in SNAPSHOT_FIELDS.get(doctype, set()) or
                not isinstance(row.get("before"), str) or
                not isinstance(row.get("after"), str) or
                not row.get("changes") or
                sha256(row["before"].encode()).hexdigest() != row["before_sha256"] or
                sha256(row["after"].encode()).hexdigest() != row["after_sha256"]):
            frappe.throw(_("La traducción de una cotización del corte no es válida"))
        table = f"`tab{doctype}`"
        column = f"`{field}`"
        count = frappe.db.sql(
            f"SELECT COUNT(*) FROM {table} WHERE name=%s AND property=%s "
            f"AND {column}=%s FOR UPDATE",
            (row["name"], row["property"], row["before"]), as_list=True)[0][0]
        if count != 1:
            frappe.throw(_("Una cotización operativa cambió durante el corte"))
        frappe.db.sql(f"UPDATE {table} SET {column}=%s WHERE name=%s "
                      f"AND property=%s AND {column}=%s",
                      (row["after"], row["name"], row["property"], row["before"]))
        snapshot_updated += 1
    experience_updated = 0
    for row in manifest["experience_rewrites"]:
        doctype = row["doctype"]
        if (doctype not in ("HS Experience", "HS Experience Order") or
                not frappe.db.exists("Item", row["target_item"])):
            frappe.throw(_("La experiencia del corte no tiene artículo destino"))
        table = f"`tab{doctype}`"
        count = frappe.db.sql(
            f"SELECT COUNT(*) FROM {table} WHERE name=%s AND property=%s "
            "AND pms_product=%s AND (item IS NULL OR item='') FOR UPDATE",
            (row["name"], row["property"], row["source_product"]),
            as_list=True)[0][0]
        if count != 1:
            frappe.throw(_("Una experiencia cambió durante el corte"))
        frappe.db.sql(f"UPDATE {table} SET item=%s WHERE name=%s AND property=%s "
                      "AND pms_product=%s AND (item IS NULL OR item='')",
                      (row["target_item"], row["name"], row["property"],
                       row["source_product"]))
        experience_updated += 1
    laundry_updated = 0
    for row in manifest["laundry_rewrites"]:
        doctype = row["doctype"]
        if doctype == "HS Laundry Rate":
            if row["parent"] is not None:
                frappe.throw(_("La tarifa de lavandería del corte cambió"))
            scope = "name=%s AND property=%s"
            values = (row["name"], row["property"])
        elif doctype == "HS Laundry Order Item":
            parent = frappe.db.get_value("HS Laundry Order", row["parent"],
                ["property", "status"], as_dict=True)
            if (not parent or parent.property != row["property"] or
                    parent.status not in ("Requested", "Collected", "In Process", "Ready")):
                frappe.throw(_("La orden de lavandería cambió durante el corte"))
            scope = "name=%s AND parenttype='HS Laundry Order' AND parent=%s"
            values = (row["name"], row["parent"])
        else:
            frappe.throw(_("La traducción de lavandería no es válida"))
        item = frappe.db.get_value("Item", row["target_item"],
            ["is_sales_item", "is_stock_item", "is_fixed_asset", "disabled"],
            as_dict=True)
        if (not item or not item.is_sales_item or item.is_stock_item or
                item.is_fixed_asset or item.disabled):
            frappe.throw(_("El artículo de lavandería dejó de ser válido"))
        table = f"`tab{doctype}`"
        count = frappe.db.sql(
            f"SELECT COUNT(*) FROM {table} WHERE {scope} "
            "AND pms_product=%s AND (item IS NULL OR item='') FOR UPDATE",
            (*values, row["source_product"]), as_list=True)[0][0]
        if count != 1:
            frappe.throw(_("Una tarifa o prenda de lavandería cambió durante el corte"))
        frappe.db.sql(f"UPDATE {table} SET item=%s WHERE {scope} "
            "AND pms_product=%s AND (item IS NULL OR item='')",
            (row["target_item"], *values, row["source_product"]))
        laundry_updated += 1
    agent_updated = 0
    for row in manifest["agent_rewrites"]:
        if not frappe.db.exists("Supplier", row["target_supplier"]):
            frappe.throw(_("El proveedor de una agencia dejó de existir"))
        count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabHS Travel Agent` WHERE name=%s AND "
            "property=%s AND pms_supplier=%s AND (supplier IS NULL OR supplier='') "
            "FOR UPDATE", (row["name"], row["property"], row["source_party"]),
            as_list=True)[0][0]
        if count != 1:
            frappe.throw(_("Una agencia cambió durante el corte"))
        frappe.db.sql("UPDATE `tabHS Travel Agent` SET supplier=%s WHERE name=%s "
            "AND property=%s AND pms_supplier=%s AND (supplier IS NULL OR supplier='')",
            (row["target_supplier"], row["name"], row["property"],
             row["source_party"]))
        agent_updated += 1
    billing_created = 0
    for row in manifest["billing_party_creations"]:
        source = frappe.db.get_value("HS Party", row["source_party"],
            ["property", "party_type", "active", "credit_authorized",
             "credit_limit", "credit_days", "credit_valid_until",
             "credit_reason"], as_dict=True)
        if (not source or source.property != row["property"] or
                source.party_type not in ("Customer", "Both") or not source.active or
                _credit_terms(source) != row["terms"] or
                not frappe.db.exists("Customer", row["target_customer"]) or
                frappe.db.exists("HS Billing Party", {
                    "property": row["property"],
                    "customer": row["target_customer"]})):
            frappe.throw(_("El pagador del corte cambió o ya existe"))
        frappe.get_doc({"doctype": "HS Billing Party",
            "company": row["company"], "property": row["property"],
            "customer": row["target_customer"], "kind": "Individual",
            "credit_authorized": row["terms"]["credit_authorized"],
            "credit_limit": Decimal(row["terms"]["credit_limit"]),
            "credit_days": row["terms"]["credit_days"],
            "valid_until": row["terms"]["valid_until"],
            "reason": row["reason"]}).insert(ignore_permissions=True)
        billing_created += 1
    return {"link_sha256": digest, "rows_updated": updated,
            "snapshot_rows_updated": snapshot_updated,
            "experience_rows_updated": experience_updated,
            "laundry_rows_updated": laundry_updated,
            "agent_rows_updated": agent_updated,
            "billing_parties_created": billing_created}
