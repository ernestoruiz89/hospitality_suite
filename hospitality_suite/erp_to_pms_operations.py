"""Plan and rehearse live hotel records from an ERPNext source bundle.

The source names are retained so booking, folio, allocation and guarantee
references remain stable. Only mapped masters and accepted JSON are changed.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
import re

import frappe
from frappe import _

from hospitality_suite.service import canonical
from hospitality_suite.standalone_currency import enabled
from hospitality_suite.security import ACTIONS, allowed_properties
from hospitality_suite.time import local


KINDS = ("bookings", "booking_rooms", "stays", "stay_guests", "folios",
         "charges", "service_requests", "cleaning_tasks", "guest_tickets",
         "ticket_events", "incidents", "day_passes", "experience_orders", "laundry_orders",
         "laundry_items", "portal_requests",
         "room_blocks", "maintenance_orders",
         "maintenance_parts", "allocations")
DOCTYPES = {"bookings": "HS Booking", "booking_rooms": "HS Booking Room",
    "stays": "HS Stay", "stay_guests": "HS Stay Guest",
    "folios": "HS Folio", "charges": "HS Charge",
    "service_requests": "HS Service Request",
    "cleaning_tasks": "HS Cleaning Task",
    "guest_tickets": "HS Guest Ticket",
    "ticket_events": "HS Ticket Event",
    "incidents": "HS Incident",
    "day_passes": "HS Day Pass",
    "experience_orders": "HS Experience Order",
    "laundry_orders": "HS Laundry Order",
    "laundry_items": "HS Laundry Order Item",
    "portal_requests": "HS Portal Request", "room_blocks": "HS Room Block",
    "maintenance_orders": "HS Maintenance Order",
    "maintenance_parts": "HS Maintenance Part",
    "allocations": "HS Allocation"}
FIELDS = {
    "bookings": ("status", "customer", "guest", "starts_at", "ends_at",
        "hold_until", "channel", "travel_agent", "agent_commission_pct",
        "agent_commission_estimate", "instructions", "reason", "currency",
        "amount", "draft_data", "quote_snapshot", "fee_amount",
        "portal_token_hash", "portal_expires_at"),
    "booking_rooms": ("idx", "category", "room", "rate", "people",
                      "extra_beds"),
    "stays": ("status", "booking", "guest", "customer", "room", "rate",
        "starts_at", "ends_at", "actual_check_in", "actual_check_out",
        "lodging_charge_policy", "currency", "amount", "quote_snapshot",
        "service_entitlements", "reason", "early_fee", "late_fee",
        "departure_expires_at", "departure_inspected_by",
        "departure_inspected_at", "departure_notes"),
    "stay_guests": ("idx", "guest", "relationship"),
    "folios": ("status", "booking", "stay", "customer", "currency", "label"),
    "charges": ("status", "stay", "folio", "item", "description",
        "quantity", "rate", "amount", "currency", "business_date", "kind",
        "period_key", "service_date", "posted_at", "invoice_item", "reason",
        "quote_snapshot", "adjustment_type"),
    "service_requests": ("status", "stay", "folio", "customer", "item",
        "warehouse", "quantity", "included", "amount", "currency", "notes",
        "charge", "stock_entry"),
    "cleaning_tasks": ("status", "room", "stay", "kind", "priority",
        "assigned_to", "started_at", "completed_at", "checklist",
        "notes", "inspected_by"),
    "guest_tickets": ("room", "stay", "subject", "description", "category",
        "priority", "status", "assigned_to", "due_at",
        "first_response_at", "resolved_at", "resolved_by", "resolution",
        "reopened_count"),
    "ticket_events": ("ticket", "kind", "actor", "occurred_at", "note",
        "before_value", "after_value"),
    "incidents": ("status", "room", "kind", "description", "item",
        "quantity", "linen_direction"),
    "day_passes": ("status", "customer", "guest", "people", "starts_at",
        "ends_at", "sales_invoice", "notes"),
    "experience_orders": ("experience", "booking", "stay", "folio",
        "customer", "quantity", "participants", "scheduled_at",
        "unit_rate", "currency", "amount", "accepted_net",
        "accepted_tax", "accepted_total", "income_account",
        "tax_account", "status", "notes"),
    "laundry_orders": ("status", "stay", "room", "folio", "currency",
        "express", "complimentary", "notes", "total", "billed_total",
        "ready_by", "collected_by", "collected_at", "counted_at",
        "delivered_by", "delivered_at", "shortage_note", "cancel_reason"),
    "laundry_items": ("idx", "laundry_rate", "garment",
        "service_type", "item", "quantity", "returned_quantity",
        "rate", "amount", "charge"),
    "portal_requests": ("status", "full_name", "email", "phone",
        "booking", "category", "rooms", "people", "mode", "starts_at",
        "ends_at", "hold_until", "request_until", "currency", "amount",
        "quote_snapshot", "experiences", "request_key", "payload_hash"),
    "room_blocks": ("status", "room", "reason", "starts_at", "ends_at",
        "note", "created_by"),
    "maintenance_orders": ("status", "room", "equipment", "blocks_room",
        "title", "starts_at", "until_reopened", "ends_at", "kind",
        "assigned_to", "notes", "cost", "stock_entry", "reopened_by"),
    "maintenance_parts": ("idx", "item", "quantity", "cost", "status",
        "stock_entry"),
    "allocations": ("status", "booking", "booking_room", "stay",
        "portal_request", "room_block", "maintenance", "category", "room", "kind",
        "starts_at", "ends_at",
        "buffer_minutes", "rate", "currency", "accepted_amount",
        "quote_snapshot"),
}
LINKS = {"customer": "customers", "guest": "guests", "travel_agent":
    "travel_agents", "item": "products", "category": "categories",
    "room": "rooms", "rate": "rates", "created_by": "users",
    "equipment": "equipment", "assigned_to": "users",
    "reopened_by": "users", "resolved_by": "users", "actor": "users",
    "experience": "experiences", "income_account": "accounts",
    "tax_account": "accounts", "laundry_rate": "laundry_rates",
    "collected_by": "users"}
SNAPSHOTS = ("draft_data", "quote_snapshot", "service_entitlements",
             "experiences", "checklist")
ITEM_KEYS = {"item", "lodging_item", "extra_hour_item", "timing_item",
             "day_pass_item", "penalty_item"}


def _problem(blockers, inventory, code, **details):
    blockers.append({"property": inventory["property"], "code": code,
                     **details})


def _mapped(value, kind, cfg, source, blockers, context):
    if not value:
        return value
    target = cfg.get(kind, {}).get(value)
    if not target:
        _problem(blockers, source, "unmapped_open_operation_link",
                 **context, kind=kind, source=value)
    return target


def _snapshot(raw, field, row, cfg, source, blockers, context):
    if not raw:
        return raw
    if sha256(str(raw).encode()).hexdigest() != row.get(field + "_sha256",
            row.get("quote_sha256") if field == "quote_snapshot" else None):
        _problem(blockers, source, "open_operation_snapshot_mismatch",
                 **context, field=field)
        return raw
    try:
        value = frappe.parse_json(raw)
    except (TypeError, ValueError):
        _problem(blockers, source, "invalid_open_operation_snapshot",
                 **context, field=field)
        return raw

    experience_items = {item["name"]: item.get("item") for item in
        source.get("mapping_requirements", {}).get("experiences", [])
        if isinstance(item, dict) and item.get("name")}

    def walk(node, parent=None):
        if isinstance(node, list):
            return [walk(child) for child in node]
        if not isinstance(node, dict):
            return node
        result = {}
        experience_item = experience_items.get(node.get("experience")) if isinstance(
            node.get("experience"), str) else None
        target_experience_product = None
        if experience_item and ("item" in node or "pms_product" in node):
            if node.get("item") and node["item"] != experience_item:
                _problem(blockers, source,
                         "experience_snapshot_item_mismatch",
                         **context, field=field,
                         experience=node["experience"], item=node["item"])
            target_experience_product = _mapped(
                node.get("item") or experience_item, "products", cfg,
                source, blockers, {**context, "field": field,
                    "path": "experience_product"})
        for key, child in node.items():
            if target_experience_product and key == "item":
                result[key] = None
                continue
            if target_experience_product and key == "item_price":
                result[key] = None
                continue
            if target_experience_product and key == "pms_product":
                result[key] = target_experience_product
                continue
            kind = ("products" if key in ITEM_KEYS else
                    "rates" if key == "name" and parent == "rules" else
                    LINKS.get(key) if key in ("category", "room",
                                               "guest", "travel_agent", "customer",
                                               "experience")
                    else None)
            if kind and isinstance(child, str) and child:
                result[key] = _mapped(child, kind, cfg, source, blockers,
                                      {**context, "field": field, "path": key})
            elif key == "company" and child == source["company"]:
                result[key] = cfg["target_company"]
            else:
                result[key] = walk(child, key)
        if target_experience_product and "pms_product" not in result:
            result["pms_product"] = target_experience_product
        return result

    return canonical(walk(value))


def _service_account(prop, name, root):
    row = frappe.db.get_value("HS Account", name,
        ["property", "organization", "root_type", "account_currency",
         "active", "is_group"], as_dict=True) if name else None
    return bool(row and row.property == prop.name and
                row.organization == prop.organization and
                row.root_type == root and row.account_currency == prop.currency and
                row.active and not row.is_group)


def _service_tax_profile(prop, name):
    row = frappe.db.get_value("HS PMS Tax Profile", name,
        ["property", "organization", "treatment", "rate", "liability_account",
         "active"], as_dict=True) if name else None
    if not row or row.property != prop.name or row.organization != prop.organization or not row.active:
        return False
    try:
        rate = Decimal(str(row.rate))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not rate.is_finite() or rate < 0 or rate > 100:
        return False
    if row.treatment == "Taxable":
        return rate > 0 and _service_account(prop, row.liability_account, "Liability")
    return row.treatment in ("Exempt", "Zero Rate", "Outside Scope") and rate == 0


def _positive_number(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return amount.is_finite() and amount > 0


def _same_positive_quantity(value, expected):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return amount.is_finite() and amount > 0 and amount == expected


def _experience_tax(prop, profile_name, price):
    if not _service_tax_profile(prop, profile_name):
        return None
    profile = frappe.db.get_value("HS PMS Tax Profile", profile_name,
        ["rate", "included_in_price", "liability_account"], as_dict=True)
    try:
        rate = Decimal(str(profile.rate))
        price = Decimal(str(price)).quantize(Decimal("0.01"),
                                           rounding=ROUND_HALF_UP)
        if not price.is_finite() or price <= 0:
            return None
        if profile.included_in_price and rate:
            net = (price / (Decimal(1) + rate / 100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax = price - net
            total = price
        else:
            net = price
            tax = (net * rate / 100).quantize(Decimal("0.01"),
                                              rounding=ROUND_HALF_UP)
            total = net + tax
    except (InvalidOperation, TypeError, ValueError):
        return None
    return {"net": net, "tax": tax, "total": total,
            "tax_account": profile.liability_account if tax else None}


def plan(source, cfg, target):
    """Return mapped rows and graph errors without writing to the destination."""
    operations = source.get("open_operations")
    blockers = []
    if not isinstance(operations, dict) or any(
            not isinstance(operations.get(kind), list) for kind in KINDS):
        _problem(blockers, source, "invalid_open_operation_inventory")
        return {"rows": {kind: [] for kind in KINDS}, "blockers": blockers}
    scoped_cfg = {**cfg, "target_company": target.company}
    names = {}
    for kind in KINDS:
        values = [row.get("name") for row in operations[kind]
                  if isinstance(row, dict)]
        if (len(values) != len(operations[kind]) or
                any(not isinstance(name, str) or not name for name in values) or
                len(set(name for name in values if isinstance(name, str))) !=
                    len(values)):
            _problem(blockers, source, "invalid_open_operation_identity", kind=kind)
        names[kind] = set(values)
    rows = {kind: [] for kind in KINDS}
    for kind in KINDS:
        for original in operations[kind]:
            if not isinstance(original, dict) or not original.get("name"):
                continue
            context = {"doctype": DOCTYPES[kind], "name": original["name"]}
            row = {"name": original["name"]}
            if kind in ("booking_rooms", "stay_guests", "maintenance_parts",
                        "laundry_items"):
                parent_kind = {"booking_rooms": "bookings",
                    "stay_guests": "stays",
                    "maintenance_parts": "maintenance_orders",
                    "laundry_items": "laundry_orders"}[kind]
                if original.get("parent") not in names[parent_kind]:
                    _problem(blockers, source, "orphan_open_operation_child",
                             **context, parent=original.get("parent"))
                row.update(parent=original.get("parent"),
                           parenttype=DOCTYPES[parent_kind],
                           parentfield={"booking_rooms": "rooms",
                               "stay_guests": "guests",
                               "maintenance_parts": "parts",
                               "laundry_items": "items"}[kind])
            else:
                row.update(property=target.name, company=target.company)
            for field in FIELDS[kind]:
                value = original.get(field)
                if field in LINKS and not (
                        kind == "charges" and field == "rate" or
                        kind == "laundry_items" and field == "rate" or
                        kind == "incidents" and field == "item" or
                        kind == "guest_tickets" and field == "category"):
                    value = _mapped(value, LINKS[field], scoped_cfg, source,
                                    blockers, {**context, "field": field})
                elif field in SNAPSHOTS and value:
                    value = _snapshot(value, field, original, scoped_cfg,
                                      source, blockers, context)
                row[field] = value
            if kind == "cleaning_tasks":
                row["room_cleaning_status"] = original.get("room_cleaning_status")
                historical = original.get("source_closed_stay")
                if row.get("stay") and row["stay"] not in names["stays"]:
                    if (isinstance(historical, dict) and
                            historical.get("name") == row["stay"] and
                            historical.get("room") == original.get("room") and
                            historical.get("status") == "Checked Out" and
                            historical.get("modified") and
                            row.get("kind") == "Departure"):
                        row["source_stay"] = row["stay"]
                        row["stay"] = None
                elif historical:
                    _problem(blockers, source,
                        "unexpected_open_cleaning_stay_snapshot", **context)
            if kind in ("incidents", "maintenance_orders") and original.get("evidence"):
                row["source_evidence_sha256"] = original.get("evidence_sha256")
                row["source_evidence_size"] = original.get("evidence_size")
                row["source_evidence_file_name"] = original.get(
                    "evidence_file_name")
            if kind == "maintenance_parts" and original.get("source_stock_issue"):
                issue = original["source_stock_issue"]
                if (not isinstance(issue, dict) or
                        sha256(canonical(issue).encode()).hexdigest() !=
                            original.get("source_stock_issue_sha256")):
                    _problem(blockers, source,
                             "unreplayable_open_maintenance_part", **context)
                else:
                    warehouse = _mapped(issue.get("warehouse"), "warehouses",
                        scoped_cfg, source, blockers, context)
                    expense = _mapped(issue.get("expense_account"), "accounts",
                        scoped_cfg, source, blockers, context)
                    inventory = _mapped(issue.get("inventory_account"),
                        "accounts", scoped_cfg, source, blockers, context)
                    row["opening_stock_issue"] = canonical({
                        "voucher": issue.get("voucher"),
                        "detail": issue.get("detail"),
                        "warehouse": warehouse,
                        "quantity": issue.get("quantity"),
                        "cost": issue.get("cost"),
                        "group_count": issue.get("group_count"),
                        "voucher_total_cost": issue.get("voucher_total_cost"),
                        "expense_account": expense,
                        "inventory_account": inventory})
            if kind == "experience_orders":
                row["item"] = None
                row["pms_product"] = _mapped(original.get("item"),
                    "products", scoped_cfg, source, blockers,
                    {**context, "field": "item"})
            if kind == "laundry_items":
                row["item"] = None
                row["pms_product"] = _mapped(original.get("item"),
                    "products", scoped_cfg, source, blockers,
                    {**context, "field": "item"})
            if row.get("currency") and not enabled(target, row["currency"]):
                _problem(blockers, source, "disabled_open_operation_currency",
                         **context, currency=row["currency"])
            rows[kind].append(row)

    by_booking = {row["name"]: row for row in rows["bookings"]}
    by_stay = {row["name"]: row for row in rows["stays"]}
    by_folio = {row["name"]: row for row in rows["folios"]}
    by_maintenance = {row["name"]: row for row in rows["maintenance_orders"]}
    room_counts = {name: 0 for name in by_booking}
    for row in rows["booking_rooms"]:
        room_counts[row.get("parent")] = room_counts.get(row.get("parent"), 0) + 1
    for row in rows["bookings"]:
        if (row.get("status") not in ("Draft", "Hold", "Confirmed", "Checked In") or
                row.get("status") != "Draft" and
                (not row.get("customer") or not row.get("starts_at") or
                 not row.get("ends_at") or not row.get("currency") or
                 not row.get("quote_snapshot") or not room_counts[row["name"]])):
            _problem(blockers, source, "incomplete_open_booking",
                     source=row["name"])
        try:
            commission_pct = Decimal(str(row.get("agent_commission_pct") or 0))
        except (InvalidOperation, TypeError, ValueError):
            commission_pct = Decimal(-1)
        if commission_pct < 0:
            _problem(blockers, source, "invalid_open_booking_commission",
                     source=row["name"])
        elif commission_pct and not row.get("travel_agent"):
            _problem(blockers, source, "open_booking_commission_without_agent",
                     source=row["name"])
        elif commission_pct:
            supplier = frappe.db.get_value("HS Travel Agent",
                row["travel_agent"], "pms_supplier")
            party = frappe.db.get_value("HS Party", supplier,
                ["property", "organization", "party_type", "active"],
                as_dict=True) if supplier else None
            if (not party or party.property != target.name or
                    party.organization != target.organization or
                    party.party_type not in ("Supplier", "Both") or
                    not party.active):
                _problem(blockers, source, "unmapped_open_booking_commission_supplier",
                         source=row["name"])
    for row in rows["stays"]:
        if (row.get("status") != "Active" or
                any(not row.get(field) for field in
                    ("booking", "guest", "customer", "room", "rate",
                     "starts_at", "ends_at", "currency", "quote_snapshot"))):
            _problem(blockers, source, "incomplete_active_stay",
                     source=row["name"])
    for row in rows["booking_rooms"]:
        if not row.get("category") or not row.get("rate") or not row.get("people"):
            _problem(blockers, source, "incomplete_open_booking_room",
                     source=row["name"])
    laundry_lines = {}
    for line in rows["laundry_items"]:
        laundry_lines.setdefault(line["parent"], []).append(line)
        context = {"doctype": "HS Laundry Order Item", "name": line["name"]}
        original = next((item for item in operations["laundry_items"]
                         if item["name"] == line["name"]), {})
        product = frappe.db.get_value("HS Product", line.get("pms_product"),
            ["property", "organization", "product_type", "active",
             "income_account", "tax_profile"], as_dict=True) if line.get(
                 "pms_product") else None
        try:
            quantity = Decimal(str(line.get("quantity")))
            returned = Decimal(str(line.get("returned_quantity") or 0))
            rate = Decimal(str(line.get("rate")))
            amount = Decimal(str(line.get("amount")))
            valid_amount = (quantity.is_finite() and quantity == int(quantity)
                and 1 <= quantity <= 1000 and returned.is_finite() and
                returned == int(returned) and 0 <= returned <= quantity and
                rate.is_finite() and rate > 0 and amount.is_finite() and
                (rate * quantity).quantize(Decimal("0.01"),
                    rounding=ROUND_HALF_UP) == amount)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            valid_amount = False
        if (not valid_amount or not original.get("item") or
                original.get("charge") or not line.get("laundry_rate") or
                not line.get("garment") or line.get("service_type") not in
                    ("Wash & Iron", "Dry Clean", "Iron Only") or
                not product or product.property != target.name or
                product.organization != target.organization or
                product.product_type != "Service" or not product.active or
                not _service_account(target, product.income_account,
                                     "Income") or not product.tax_profile or
                not _service_tax_profile(target, product.tax_profile)):
            _problem(blockers, source, "invalid_open_laundry_item", **context)
    for row in rows["laundry_orders"]:
        context = {"doctype": "HS Laundry Order", "name": row["name"]}
        stay = by_stay.get(row.get("stay"))
        folio = by_folio.get(row.get("folio"))
        lines = laundry_lines.get(row["name"], [])
        try:
            total = Decimal(str(row.get("total") or 0))
            billed = Decimal(str(row.get("billed_total") or 0))
            line_total = sum((Decimal(str(line["amount"])) for line in lines),
                             Decimal(0))
            valid_total = (total.is_finite() and billed.is_finite() and
                billed == 0 and total == line_total)
        except (InvalidOperation, TypeError, ValueError):
            valid_total = False
        status = row.get("status")
        if (status not in ("Requested", "Collected", "In Process", "Ready")
                or not stay or not folio or
                stay.get("room") != row.get("room") or
                folio.get("customer") != stay.get("customer") or
                folio.get("stay") not in (None, "", stay["name"]) or
                folio.get("booking") not in (None, "", stay.get("booking")) or
                row.get("currency") != target.currency or
                not valid_total or row.get("delivered_by") or
                row.get("delivered_at") or row.get("shortage_note") or
                row.get("cancel_reason") or
                (status == "Requested" and (lines or total != 0 or
                    row.get("collected_by") or row.get("collected_at") or
                    row.get("counted_at") or row.get("ready_by"))) or
                (status != "Requested" and (not lines or
                    not row.get("collected_by") or
                    not row.get("collected_at") or
                    not row.get("ready_by"))) or
                (status in ("Collected", "In Process") and
                    (row.get("counted_at") or any(
                        _positive_number(line.get("returned_quantity"))
                        for line in lines))) or
                (status == "Ready" and not row.get("counted_at") and any(
                    _positive_number(line.get("returned_quantity"))
                    for line in lines))):
            _problem(blockers, source, "invalid_open_laundry_order", **context)
    original_incidents = {item.get("name"): item for item in
        operations["incidents"] if isinstance(item, dict)}
    for row in rows["incidents"]:
        original = original_incidents[row["name"]]
        room = frappe.db.get_value("HS Room", row.get("room"),
            ["property", "company"], as_dict=True) if row.get("room") else None
        if (row.get("status") != "Open" or
                row.get("kind") not in ("Damage", "Lost Property") or
                not isinstance(row.get("description"), str) or
                not row["description"].strip() or
                not room or (room.property, room.company) !=
                    (target.name, target.company) or
                original.get("stock_entry") or
                original.get("resolution") or original.get("resolved_by") or
                original.get("resolved_at") or
                (original.get("evidence") and (
                    not isinstance(row.get("source_evidence_sha256"), str) or
                    not re.fullmatch(r"[0-9a-f]{64}",
                                     row["source_evidence_sha256"]) or
                    not isinstance(row.get("source_evidence_size"), int) or
                    not 0 < row["source_evidence_size"] <= 25 * 1024 * 1024 or
                    not isinstance(row.get("source_evidence_file_name"), str) or
                    not row["source_evidence_file_name"] or
                    len(row["source_evidence_file_name"]) > 180 or
                    any(char in row["source_evidence_file_name"] for char in
                        ("/", "\\"))))):
            _problem(blockers, source, "invalid_open_incident",
                     doctype="HS Incident", name=row["name"])
    originals_by_pass = {item.get("name"): item for item in
        operations["day_passes"] if isinstance(item, dict)}
    for row in rows["day_passes"]:
        original = originals_by_pass[row["name"]]
        financial = original.get("source_financial")
        context = {"doctype": "HS Day Pass", "name": row["name"]}
        try:
            start = frappe.utils.get_datetime(row["starts_at"])
            end = frappe.utils.get_datetime(row["ends_at"])
            people = Decimal(str(row["people"]))
            total = Decimal(str(financial["invoice_total"]))
            net = Decimal(str(financial["invoice_net"]))
            tax = Decimal(str(financial["invoice_tax"]))
            lines = financial["invoice_gl"]
            archive_rows = frappe.get_all("HS Historical Fiscal Document",
                filters={"property": target.name,
                    "source_doctype": "Sales Invoice",
                    "source_name": row["sales_invoice"]},
                fields=["name", "organization", "document_type",
                    "status", "currency", "total_amount"],
                limit_page_length=2)
            valid = (row["status"] == "Issued" and row.get("customer") and
                not original.get("pms_receivable") and
                not original.get("quote_snapshot") and
                bool(original.get("service")) and
                bool(original.get("payment")) and
                isinstance(financial, dict) and
                sha256(canonical(financial).encode()).hexdigest() ==
                    original.get("source_financial_sha256") and
                financial.get("invoice") == row["sales_invoice"] and
                financial.get("payment") == original.get("payment") and
                financial.get("service") == original.get("service") and
                financial.get("invoice_currency") == target.currency and
                financial.get("payment_base_amount") ==
                    financial.get("invoice_total") and
                people.is_finite() and people == int(people) and
                1 <= people <= 100 and start < end and
                local(start, target).date() == local(end, target).date() and
                total.is_finite() and total > 0 and
                net.is_finite() and tax.is_finite() and net >= 0 and
                tax >= 0 and net + tax == total and
                isinstance(financial.get("receivable_account"), str) and
                isinstance(lines, list) and len(lines) >= 2 and
                len(archive_rows) == 1 and
                archive_rows[0].organization == target.organization and
                archive_rows[0].document_type == "Invoice" and
                archive_rows[0].status == "Posted" and
                archive_rows[0].currency == target.currency and
                Decimal(str(archive_rows[0].total_amount)) == total)
        except (AttributeError, InvalidOperation, KeyError, TypeError,
                ValueError, OverflowError):
            valid = False
        if not valid:
            _problem(blockers, source, "invalid_open_day_pass", **context)
            continue
        mapped_lines = []
        for line in lines:
            if (not isinstance(line, dict) or not line.get("account") or
                    line.get("party_type") not in (None, "Customer") or
                    line.get("root_type") not in
                        ("Asset", "Income", "Liability")):
                _problem(blockers, source, "invalid_open_day_pass_gl", **context)
                break
            mapped_account = _mapped(line["account"], "accounts", scoped_cfg,
                source, blockers, {**context, "field": "invoice_gl.account"})
            target_account = frappe.db.get_value("HS Account", mapped_account,
                ["property", "organization", "root_type", "account_type",
                 "account_currency"], as_dict=True) if mapped_account else None
            if (not target_account or target_account.property != target.name or
                    target_account.organization != target.organization or
                    target_account.root_type != line["root_type"] or
                    target_account.account_type != line["account_type"] or
                    target_account.account_currency != target.currency):
                _problem(blockers, source, "invalid_open_day_pass_gl", **context)
                break
            mapped_lines.append({**line,
                "account": mapped_account,
                "party": _mapped(line.get("party"), "customers", scoped_cfg,
                    source, blockers, {**context, "field": "invoice_gl.party"})
                    if line.get("party_type") == "Customer" else None})
        else:
            mapped_receivable = _mapped(financial["receivable_account"],
                "accounts", scoped_cfg, source, blockers,
                {**context, "field": "receivable_account"})
            mapped_financial = {**financial, "customer": row["customer"],
                "invoice_gl": mapped_lines,
                "receivable_account": mapped_receivable,
                "source_financial_sha256": original["source_financial_sha256"]}
            row["opening_historical_invoice"] = archive_rows[0].name
            row["opening_financial"] = canonical(mapped_financial)
            row["opening_financial_sha256"] = sha256(
                row["opening_financial"].encode()).hexdigest()
            from hospitality_suite.standalone_day_pass import opening_sale
            try:
                opening_sale(target, frappe._dict({
                    "opening_historical_invoice": row["opening_historical_invoice"],
                    "opening_financial": row["opening_financial"],
                    "opening_financial_sha256": row["opening_financial_sha256"],
                    "sales_invoice": row["sales_invoice"],
                    "customer": row["customer"]}))
            except frappe.ValidationError:
                frappe.clear_messages()
                _problem(blockers, source, "invalid_open_day_pass_gl", **context)
    for row in rows["portal_requests"]:
        try:
            selected = frappe.parse_json(row.get("experiences") or "[]")
            quote = frappe.parse_json(row.get("quote_snapshot") or "{}")
            quoted = quote.get("experiences") or []
            if (not isinstance(selected, list) or not isinstance(quote, dict)
                    or not isinstance(quoted, list)):
                raise ValueError("invalid portal experience lists")
            def quantities(items):
                result = {}
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("invalid portal experience")
                    name = item.get("experience")
                    quantity = Decimal(str(item.get("quantity")))
                    if (not isinstance(name, str) or not name or name in result
                            or not quantity.is_finite() or quantity != int(quantity)
                            or not 1 <= quantity <= 1000):
                        raise ValueError("invalid portal experience quantity")
                    result[name] = quantity
                return result
            if quantities(selected) != quantities(quoted):
                raise ValueError("portal experience quote differs")
            for item in quoted:
                experience = frappe.db.get_value("HS Experience",
                    item["experience"],
                    ["property", "company", "pms_product", "active"],
                    as_dict=True)
                if (not experience or experience.property != target.name or
                        experience.company != target.company or
                        not experience.active or
                        experience.pms_product != item.get("pms_product") or
                        item.get("item") or item.get("item_price")):
                    raise ValueError("invalid portal experience mapping")
        except (TypeError, ValueError, InvalidOperation, OverflowError,
                AttributeError, KeyError):
            _problem(blockers, source, "invalid_open_portal_experiences",
                     source=row["name"])
    cleaning_rooms = set()
    for row in rows["cleaning_tasks"]:
        context = {"doctype": "HS Cleaning Task", "name": row["name"]}
        expected_status = {"Pending": "Dirty", "In Progress": "Cleaning",
                           "Inspection": "Inspection"}.get(row.get("status"))
        if (not expected_status or not row.get("room") or
                row.get("room_cleaning_status") != expected_status or
                row.get("kind") not in ("Stay", "Deep", "Departure") or
                row.get("priority") not in ("Normal", "High", "Urgent") or
                (row.get("status") == "Inspection" and not row.get("completed_at")) or
                (row.get("status") != "Inspection" and row.get("completed_at")) or
                (row.get("status") == "Pending" and row.get("started_at")) or
                (row.get("status") != "Pending" and not row.get("started_at"))):
            _problem(blockers, source, "invalid_open_cleaning_task", **context)
        if row.get("room") in cleaning_rooms:
            _problem(blockers, source, "duplicate_open_cleaning_room", **context,
                     room=row.get("room"))
        cleaning_rooms.add(row.get("room"))
        if row.get("stay") and row["stay"] not in by_stay:
            _problem(blockers, source, "unreplayable_open_cleaning_stay",
                     **context, stay=row["stay"])
        try:
            checklist = frappe.parse_json(row.get("checklist") or "")
            if (not isinstance(checklist, dict) or not checklist or
                    any(not isinstance(key, str) or not key or
                        value not in (True, False, 0, 1)
                        for key, value in checklist.items()) or
                    row.get("status") == "Inspection" and
                    not all(value is True or value == 1
                            for value in checklist.values())):
                raise ValueError("invalid checklist")
        except (TypeError, ValueError):
            _problem(blockers, source, "invalid_open_cleaning_checklist",
                     **context)
        if row.get("assigned_to") and (
                not frappe.db.get_value("User", row["assigned_to"], "enabled") or
                target.name not in allowed_properties(row["assigned_to"]) or
                not set(frappe.get_roles(row["assigned_to"])).intersection({
                    "HS Housekeeping", "HS Supervisor", "HS Manager",
                    "HS Administrator", "System Manager"})):
            _problem(blockers, source, "invalid_target_cleaning_assignee",
                     **context, user=row["assigned_to"])
        if row.get("inspected_by"):
            _problem(blockers, source, "unreplayable_open_cleaning_inspection",
                     **context, user=row["inspected_by"])
        if row.get("room") and frappe.db.exists("HS Cleaning Task", {
                "room": row["room"], "status": ["!=", "Completed"]}):
            _problem(blockers, source, "target_cleaning_room_busy", **context,
                     room=row["room"])
    ticket_names = {row["name"] for row in rows["guest_tickets"]}
    event_counts = {name: {"Created": 0, "Started": 0, "Reopened": 0}
                    for name in ticket_names}
    for row in rows["ticket_events"]:
        context = {"doctype": "HS Ticket Event", "name": row["name"]}
        if (row.get("ticket") not in ticket_names or
                row.get("kind") not in ("Created", "Assigned", "Started",
                    "Resolved", "Reopened", "Cancelled", "Note",
                    "Due Changed") or not row.get("actor") or
                not row.get("occurred_at")):
            _problem(blockers, source, "invalid_open_ticket_event", **context)
        elif row["kind"] in event_counts[row["ticket"]]:
            event_counts[row["ticket"]][row["kind"]] += 1
    for row in rows["guest_tickets"]:
        context = {"doctype": "HS Guest Ticket", "name": row["name"]}
        stay = by_stay.get(row.get("stay"))
        try:
            reopened = int(row.get("reopened_count") or 0)
            valid_reopens = reopened >= 0 and reopened == (row.get("reopened_count") or 0)
        except (TypeError, ValueError, OverflowError):
            valid_reopens = False
        counts = event_counts[row["name"]]
        if (row.get("status") not in ("Open", "In Progress") or
                not row.get("subject") or not row.get("description") or
                row.get("category") not in ("Guest Request", "Housekeeping",
                    "Maintenance", "Complaint", "Other") or
                row.get("priority") not in ("Normal", "High", "Urgent") or
                not row.get("due_at") or row.get("resolved_at") or
                row.get("resolved_by") or row.get("resolution") or
                not valid_reopens or counts["Created"] != 1 or
                counts["Reopened"] != reopened or
                row["status"] == "In Progress" and
                (not row.get("first_response_at") or not counts["Started"]) or
                row.get("stay") and (not stay or
                    row.get("room") != stay.get("room"))):
            _problem(blockers, source, "invalid_open_guest_ticket", **context)
        if row.get("assigned_to") and (
                not frappe.db.get_value("User", row["assigned_to"], "enabled") or
                target.name not in allowed_properties(row["assigned_to"]) or
                not set(frappe.get_roles(row["assigned_to"])).intersection(
                    ACTIONS["ticket"])):
            _problem(blockers, source, "invalid_target_ticket_assignee",
                     **context, user=row["assigned_to"])
    for row in rows["folios"]:
        if (row.get("status") != "Open" or not row.get("customer") or
                not row.get("currency")):
            _problem(blockers, source, "incomplete_open_folio",
                     source=row["name"])
    for row in rows["charges"]:
        if (row.get("status") not in ("Pending", "Scheduled") or
                any(not row.get(field) for field in
                    ("stay", "folio", "item", "amount", "currency",
                     "business_date", "kind"))):
            _problem(blockers, source, "incomplete_open_charge",
                     source=row["name"])
    by_product = {}
    claimed_issues = set()
    for row in rows["service_requests"]:
        original = next(item for item in operations["service_requests"]
                        if item["name"] == row["name"])
        stay = by_stay.get(row.get("stay"))
        folio = by_folio.get(row.get("folio"))
        context = {"doctype": "HS Service Request", "name": row["name"]}
        if (row.get("status") not in ("Requested", "In Progress", "Delivered") or
                not stay or not folio or not row.get("customer") or
                row["customer"] != folio.get("customer") or
                row["customer"] != stay.get("customer") or
                not (folio.get("stay") == stay["name"] or
                     not folio.get("stay") and
                     folio.get("booking") == stay.get("booking")) or
                not row.get("item") or not row.get("currency") or
                row["currency"] != target.currency or
                folio.get("currency") != target.currency):
            _problem(blockers, source, "invalid_open_service_graph",
                     source=row["name"])
        forbidden = (("charge", "stock_entry", "return_stock_entry",
                      "credit_note", "sales_invoice") if
            row.get("status") != "Delivered" else
            ("return_stock_entry", "credit_note", "sales_invoice"))
        for field in forbidden:
            if original.get(field):
                _problem(blockers, source, "unreplayable_open_service_reference",
                         **context, field=field, target=original[field])
        if row.get("status") == "Delivered":
            charge = next((charge for charge in rows["charges"]
                if charge["name"] == row.get("charge")), None)
            if ((row.get("included") and row.get("charge")) or
                    (not row.get("included") and
                     (not charge or charge.get("stay") != row.get("stay") or
                      charge.get("folio") != row.get("folio") or
                      charge.get("status") != "Pending"))):
                _problem(blockers, source, "unreplayable_delivered_service_charge",
                         source=row["name"], charge=row.get("charge"))
        else:
            row["charge"] = None
            row["stock_entry"] = None
        if original.get("warehouse"):
            _problem(blockers, source, "unmapped_source_service_warehouse",
                     **context, warehouse=original["warehouse"])
        try:
            quantity = Decimal(str(row.get("quantity")))
            amount = Decimal(str(row.get("amount")))
        except (InvalidOperation, TypeError, ValueError):
            quantity = amount = Decimal("NaN")
        if (row.get("included") not in (0, 1, False, True) or
                not quantity.is_finite() or quantity <= 0 or quantity > 10000 or
                quantity != quantity.quantize(Decimal("0.001")) or
                not amount.is_finite() or
                (bool(row.get("included")) and amount != 0) or
                (not row.get("included") and amount <= 0) or
                not isinstance(row.get("notes") or "", str) or
                len(row.get("notes") or "") > 500):
            _problem(blockers, source, "invalid_open_service_terms",
                     source=row["name"])
        product_name = row.get("item")
        if product_name not in by_product:
            by_product[product_name] = frappe.db.get_value("HS Product",
                product_name, ["property", "organization", "product_type",
                    "active", "income_account", "expense_account",
                    "inventory_account", "tax_profile", "sales_rate"],
                as_dict=True) if product_name else None
        product = by_product[product_name]
        if (not product or product.property != target.name or
                product.organization != target.organization or not product.active or
                product.product_type not in ("Service", "Stock")):
            _problem(blockers, source, "invalid_target_service_product",
                     source=row["name"], product=product_name)
            continue
        if product.product_type == "Stock":
            issue = original.get("source_stock_issue") if row["status"] == "Delivered" else None
            source_warehouse = (issue.get("warehouse") if isinstance(issue, dict)
                else source.get("mapping_requirements", {}).get(
                    "source_settings", {}).get("warehouse"))
            row["warehouse"] = cfg.get("warehouses", {}).get(source_warehouse)
            warehouse = frappe.db.get_value("HS Warehouse", row["warehouse"],
                ["property", "organization", "active"], as_dict=True) if row["warehouse"] else None
            if (not warehouse or warehouse.property != target.name or
                    warehouse.organization != target.organization or
                    not warehouse.active):
                _problem(blockers, source, "invalid_target_service_warehouse",
                         source=row["name"], warehouse=source_warehouse)
            for field, root in (("inventory_account", "Asset"),
                                ("expense_account", "Expense")):
                if not _service_account(target, product.get(field), root):
                    _problem(blockers, source, "invalid_target_service_account",
                             source=row["name"], field=field)
            if row["status"] == "Delivered":
                if (not original.get("stock_entry") or not isinstance(issue, dict) or
                        sha256(canonical(issue).encode()).hexdigest() !=
                            original.get("source_stock_issue_sha256") or
                        issue.get("voucher") != original.get("stock_entry") or
                        issue.get("item") != original.get("item") or
                        not _same_positive_quantity(issue.get("quantity"), quantity) or
                        not _positive_number(issue.get("cost"))):
                    _problem(blockers, source, "unreplayable_delivered_service_stock",
                             source=row["name"])
                else:
                    expense = cfg.get("accounts", {}).get(issue.get("expense_account"))
                    inventory = cfg.get("accounts", {}).get(issue.get("inventory_account"))
                    if (not _service_account(target, expense, "Expense") or
                            not _service_account(target, inventory, "Asset") or
                            not row["warehouse"] or expense == inventory):
                        _problem(blockers, source,
                                 "invalid_target_service_return_accounts",
                                 source=row["name"])
                    else:
                        if issue["voucher"] in claimed_issues:
                            _problem(blockers, source,
                                     "duplicate_delivered_service_stock_issue",
                                     source=row["name"],
                                     voucher=issue["voucher"])
                        claimed_issues.add(issue["voucher"])
                        row["opening_stock_issue"] = canonical({
                            "voucher": issue["voucher"],
                            "warehouse": row["warehouse"],
                            "quantity": issue["quantity"],
                            "cost": issue["cost"],
                            "expense_account": expense,
                            "inventory_account": inventory})
        else:
            row["warehouse"] = None
            if row["status"] == "Delivered" and original.get("stock_entry"):
                _problem(blockers, source, "unreplayable_delivered_service_stock",
                         source=row["name"])
        if not row.get("included"):
            if (not _service_account(target, product.income_account, "Income") or
                    not product.tax_profile or
                    not _service_tax_profile(target, product.tax_profile) or
                    not _positive_number(product.sales_rate)):
                _problem(blockers, source, "invalid_target_service_sale_setup",
                         source=row["name"])
    included_requested = {}
    for row in rows["service_requests"]:
        if row.get("included") not in (1, True):
            continue
        try:
            quantity = Decimal(str(row["quantity"]))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if quantity.is_finite() and quantity > 0:
            key = (row.get("stay"), row.get("item"))
            included_requested[key] = included_requested.get(key, Decimal(0)) + quantity
    for (stay_name, product_name), used in included_requested.items():
        stay = by_stay.get(stay_name)
        try:
            entitlements = frappe.parse_json(
                stay.get("service_entitlements") or "[]") if stay else []
            if not isinstance(entitlements, list):
                raise ValueError("invalid entitlements")
            allowed = sum((Decimal(str(item["quantity"])) for item in
                entitlements if item["item"] == product_name), Decimal(0))
            if not allowed.is_finite() or allowed < 0:
                raise ValueError("invalid entitlement quantity")
        except (InvalidOperation, TypeError, ValueError, KeyError):
            _problem(blockers, source, "invalid_open_service_entitlements",
                     stay=stay_name, product=product_name)
            continue
        if used > allowed:
            _problem(blockers, source, "overcommitted_open_service_entitlement",
                     stay=stay_name, product=product_name,
                     requested=str(used), available=str(allowed))
    for row in rows["experience_orders"]:
        original = next(item for item in operations["experience_orders"]
                        if item["name"] == row["name"])
        context = {"doctype": "HS Experience Order", "name": row["name"]}
        booking = by_booking.get(row.get("booking"))
        product = frappe.db.get_value("HS Product", row.get("pms_product"),
            ["property", "organization", "product_type", "active",
             "tax_profile", "income_account"], as_dict=True) if row.get(
                 "pms_product") else None
        experience = frappe.db.get_value("HS Experience", row.get("experience"),
            ["property", "company", "pms_product", "active"],
            as_dict=True) if row.get("experience") else None
        try:
            quantity = int(row.get("quantity"))
            participants = int(row.get("participants"))
            rate = Decimal(str(row.get("unit_rate")))
            price = Decimal(str(row.get("amount")))
            valid_terms = (1 <= quantity <= 1000 and
                1 <= participants <= 1000 and rate.is_finite() and rate > 0 and
                price.is_finite() and price > 0 and
                (rate * quantity).quantize(Decimal("0.01"),
                    rounding=ROUND_HALF_UP) == price and
                row.get("currency") == target.currency)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            valid_terms = False
        if (not valid_terms or row.get("status") not in
                ("Reserved", "Confirmed") or not row.get("customer") or
                not row.get("experience") or not original.get("item") or
                original.get("charge") or original.get("pms_receivable") or
                original.get("sales_invoice") or row.get("stay") or
                row.get("folio") or row.get("status") == "Confirmed" and
                not row.get("scheduled_at") or
                not product or product.property != target.name or
                product.organization != target.organization or
                product.product_type != "Service" or not product.active or
                not product.tax_profile or
                not _service_tax_profile(target, product.tax_profile) or
                not experience or experience.property != target.name or
                experience.company != target.company or
                experience.pms_product != row.get("pms_product") or
                not experience.active):
            _problem(blockers, source, "invalid_open_experience_order", **context)
            continue
        if booking:
            if (booking.get("customer") != row["customer"] or
                    not _service_account(target, product.income_account,
                                         "Income") or
                    any(original.get(field) for field in ("accepted_net",
                        "accepted_tax", "accepted_total", "income_account",
                        "tax_account"))):
                _problem(blockers, source,
                         "invalid_booked_experience_terms", **context)
            row["accepted_tax_profile"] = None
        else:
            if original.get("booking"):
                _problem(blockers, source,
                         "dangling_open_experience_booking", **context,
                         booking=original["booking"])
                continue
            tax = _experience_tax(target, product.tax_profile, row["amount"])
            try:
                accepted = tuple(Decimal(str(row.get(field))) for field in
                    ("accepted_net", "accepted_tax", "accepted_total"))
            except (InvalidOperation, TypeError, ValueError):
                accepted = None
            if (not tax or not accepted or
                    accepted != (tax["net"], tax["tax"], tax["total"]) or
                    not _service_account(target, row.get("income_account"),
                                         "Income") or
                    row.get("tax_account") != tax["tax_account"] or
                    not original.get("accepted_tax_profile")):
                _problem(blockers, source,
                         "invalid_direct_experience_terms", **context)
            row["accepted_tax_profile"] = product.tax_profile
    for row in rows["allocations"]:
        if (row.get("status") != "Active" or not row.get("category") or
                not row.get("starts_at") or
                not row.get("ends_at") and not (
                    row.get("kind") == "Maintenance" and
                    by_maintenance.get(row.get("maintenance"), {}).get(
                        "until_reopened"))):
            _problem(blockers, source, "incomplete_open_allocation",
                     source=row["name"])
    for row in rows["room_blocks"]:
        if (row.get("status") != "Active" or not row.get("room") or
                not row.get("reason") or not row.get("starts_at") or
                not row.get("ends_at") or
                not any(allocation.get("room_block") == row["name"] and
                        allocation.get("room") == row["room"] and
                        allocation.get("kind") == "Room Block" for allocation
                        in rows["allocations"])):
            _problem(blockers, source, "invalid_open_room_block_graph",
                     source=row["name"])
    for row in rows["maintenance_orders"]:
        if (row.get("status") not in ("Open", "In Progress") or
                not (row.get("room") or row.get("equipment")) or
                not row.get("title") or not row.get("starts_at") or
                not row.get("until_reopened") and not row.get("ends_at") or
                row.get("until_reopened") and row.get("ends_at") or
                row.get("blocks_room") and not row.get("room") or
                row.get("blocks_room") and not any(
                    allocation.get("maintenance") == row["name"] and
                    allocation.get("room") == row["room"] and
                    allocation.get("kind") == "Maintenance" for allocation
                    in rows["allocations"])):
            _problem(blockers, source, "invalid_open_maintenance_graph",
                     source=row["name"])
        if row.get("assigned_to") and (
                not frappe.db.get_value("User", row["assigned_to"], "enabled") or
                target.name not in allowed_properties(row["assigned_to"]) or
                not set(frappe.get_roles(row["assigned_to"])).intersection({
                    "HS Maintenance", "HS Supervisor", "HS Manager",
                    "HS Administrator", "System Manager"})):
            _problem(blockers, source, "invalid_target_maintenance_assignee",
                     source=row["name"])
    parts_by_order = {}
    for original in operations["maintenance_parts"]:
        parts_by_order.setdefault(original.get("parent"), []).append(original)
    for original in operations["maintenance_orders"]:
        try:
            cost = Decimal(str(original.get("cost") or 0))
            issued_cost = sum((Decimal(str(part["cost"])) for part in
                parts_by_order.get(original["name"], [])
                if part.get("status") == "Issued"), Decimal(0))
        except (InvalidOperation, TypeError, ValueError):
            cost = issued_cost = None
        parts = parts_by_order.get(original["name"], [])
        evidence_ok = (not original.get("evidence") or
            isinstance(original.get("evidence_sha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", original["evidence_sha256"]) and
            isinstance(original.get("evidence_size"), int) and
            0 < original["evidence_size"] <= 25 * 1024 * 1024 and
            isinstance(original.get("evidence_file_name"), str) and
            0 < len(original["evidence_file_name"]) <= 180 and
            not any(char in original["evidence_file_name"]
                for char in ("/", "\\")))
        if (not evidence_ok or cost is None or
                not cost.is_finite() or cost != issued_cost or
                (original.get("stock_entry") and not any(
                    part.get("stock_entry") == original["stock_entry"]
                    for part in parts))):
            _problem(blockers, source, "unreplayable_open_maintenance_cost",
                     source=original["name"])
    mapped_parts = {part["name"]: part for part in rows["maintenance_parts"]}
    grouped_issues = {}
    claimed_details = set()
    for original in operations["maintenance_parts"]:
        mapped = mapped_parts.get(original.get("name"))
        if original.get("status") == "Issued":
            issue = original.get("source_stock_issue")
            try:
                opening = frappe.parse_json(mapped.get("opening_stock_issue"))
                part_cost = Decimal(str(original["cost"]))
                group_cost = Decimal(str(issue["voucher_total_cost"]))
                group_count = int(issue["group_count"])
                expected_qty = Decimal(str(original["quantity"]))
                opening_total = Decimal(str(opening.get("voucher_total_cost")))
            except (AttributeError, InvalidOperation, KeyError,
                    TypeError, ValueError):
                opening = None
                part_cost = group_cost = expected_qty = opening_total = Decimal(0)
                group_count = 0
            valid = (isinstance(issue, dict) and isinstance(opening, dict) and
                sha256(canonical(issue).encode()).hexdigest() ==
                    original.get("source_stock_issue_sha256") and
                issue.get("voucher") == original.get("stock_entry") and
                issue.get("item") == original.get("item") and
                isinstance(issue.get("detail"), str) and issue["detail"] and
                _same_positive_quantity(issue.get("quantity"),
                    expected_qty) and
                _positive_number(issue.get("cost")) and
                Decimal(str(issue["cost"])) == part_cost and
                group_count > 0 and group_cost > 0 and
                part_cost.is_finite() and group_cost.is_finite() and
                opening.get("voucher") == issue["voucher"] and
                opening.get("detail") == issue["detail"] and
                opening.get("warehouse") == cfg.get("warehouses", {}).get(
                    issue.get("warehouse")) and
                opening.get("expense_account") == cfg.get("accounts", {}).get(
                    issue.get("expense_account")) and
                opening.get("inventory_account") == cfg.get("accounts", {}).get(
                    issue.get("inventory_account")) and
                opening.get("quantity") == issue["quantity"] and
                opening.get("cost") == issue["cost"] and
                opening.get("group_count") == group_count and
                opening_total == group_cost and
                mapped.get("item") and
                frappe.db.get_value("HS Product", mapped["item"],
                    "product_type") == "Stock" and
                _service_account(target, opening.get("expense_account"),
                    "Expense") and
                _service_account(target, opening.get("inventory_account"),
                    "Asset") and
                opening.get("expense_account") != opening.get(
                    "inventory_account") and
                frappe.db.get_value("HS Warehouse", opening.get("warehouse"),
                    "property") == target.name)
            if not valid:
                _problem(blockers, source, "unreplayable_open_maintenance_part",
                         source=original["name"])
                continue
            detail_key = (issue["voucher"], issue["detail"])
            if detail_key in claimed_details:
                _problem(blockers, source, "duplicate_open_maintenance_part",
                         source=original["name"])
            claimed_details.add(detail_key)
            grouped_issues.setdefault(issue["voucher"], []).append(
                (group_count, group_cost, part_cost))
            continue
        entry = original.get("source_returned_entry")
        try:
            quantity = Decimal(str(original["quantity"]))
            cost = Decimal(str(original["cost"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            quantity = cost = None
        product = frappe.db.get_value("HS Product", mapped.get("item"),
            ["property", "organization", "product_type"], as_dict=True) if mapped else None
        if (original.get("status") != "Returned" or
                quantity is None or not quantity.is_finite() or quantity <= 0 or
                cost is None or not cost.is_finite() or cost < 0 or
                not isinstance(entry, dict) or
                entry.get("voucher") != original.get("stock_entry") or
                entry.get("company") != source.get("company") or
                entry.get("property") != source.get("property") or
                entry.get("docstatus") != 2 or
                entry.get("stock_entry_type") != "Material Issue" or
                not product or product.property != target.name or
                product.organization != target.organization or
                product.product_type != "Stock"):
            _problem(blockers, source, "unreplayable_open_maintenance_part",
                     source=original["name"])
    for voucher, group in grouped_issues.items():
        if (len(group) != group[0][0] or
                any((count, total) != group[0][:2]
                    for count, total, _ in group) or
                sum((part_cost for _, _, part_cost in group), Decimal(0)) !=
                    group[0][1]):
            _problem(blockers, source, "incomplete_open_maintenance_stock_issue",
                     stock_entry=voucher)
    for kind, fields in (("stays", ("booking",)),
                         ("folios", ("booking", "stay")),
                         ("charges", ("stay", "folio")),
                         ("service_requests", ("stay", "folio")),
                         ("cleaning_tasks", ("stay",)),
                         ("guest_tickets", ("stay",)),
                         ("ticket_events", ("ticket",)),
                         ("experience_orders", ("booking",)),
                         ("laundry_orders", ("stay", "folio")),
                         ("portal_requests", ("booking",)),
                         ("allocations", ("booking", "stay", "portal_request",
                                          "booking_room", "room_block",
                                          "maintenance"))):
        targets = {"booking": names["bookings"], "stay": names["stays"],
                   "folio": names["folios"],
                   "portal_request": names["portal_requests"],
                   "booking_room": names["booking_rooms"],
                   "room_block": names["room_blocks"],
                   "maintenance": names["maintenance_orders"],
                   "ticket": names["guest_tickets"]}
        for row in rows[kind]:
            for field in fields:
                if row.get(field) and row[field] not in targets[field]:
                    _problem(blockers, source, "dangling_open_operation_link",
                             doctype=DOCTYPES[kind], name=row["name"],
                             field=field, target=row[field])
    for row in rows["folios"]:
        booking = by_booking.get(row.get("booking"))
        stay = by_stay.get(row.get("stay"))
        if (not booking and not stay or
                booking and booking["customer"] != row["customer"] or
                stay and (stay["customer"] != row["customer"] or
                          booking and stay["booking"] != booking["name"])):
            _problem(blockers, source, "invalid_open_folio_graph",
                     source=row["name"])
    for row in rows["stays"]:
        booking = by_booking.get(row.get("booking"))
        if (not booking or booking.get("customer") != row.get("customer") or
                not any(folio.get("stay") == row["name"] for folio in
                        rows["folios"]) or
                not any(allocation.get("stay") == row["name"] and
                        allocation.get("kind") == "Stay" and
                        allocation.get("room") == row.get("room") for allocation
                        in rows["allocations"])):
            _problem(blockers, source, "invalid_open_stay_graph",
                     source=row["name"])
    for row in rows["charges"]:
        stay, folio = by_stay.get(row.get("stay")), by_folio.get(row.get("folio"))
        if not stay or not folio or (folio.get("stay") and
                                     folio["stay"] != stay["name"]):
            _problem(blockers, source, "invalid_open_charge_graph",
                     source=row["name"])
    for kind, fields in (("bookings", ("fee_invoice", "fee_receivable",
                                      "agent_commission_invoice",
                                      "pms_agent_commission")),
                         ("charges", ("sales_invoice", "pms_receivable",
                                      "applies_to_charge"))):
        for original in operations[kind]:
            for field in fields:
                if original.get(field):
                    _problem(blockers, source, "unplanned_open_operation_reference",
                             doctype=DOCTYPES[kind], name=original["name"],
                             field=field, target=original[field])
    for row in rows["allocations"]:
        if row.get("kind") not in ("Reservation", "Stay", "Room Block",
                                  "Maintenance"):
            _problem(blockers, source, "unplanned_allocation_kind",
                     source=row["name"], kind=row.get("kind"))
        if (row.get("kind") == "Stay" and not row.get("stay") or
                row.get("kind") == "Reservation" and
                not (row.get("booking") or row.get("portal_request")) or
                row.get("kind") == "Room Block" and not row.get("room_block") or
                row.get("kind") == "Maintenance" and
                not row.get("maintenance") or
                row.get("booking_room") and
                not row.get("booking")):
            _problem(blockers, source, "invalid_open_allocation_graph",
                     source=row["name"])
    return {"rows": rows, "blockers": blockers}


def publish(target, projected, evidence_payloads=None, created_files=None):
    """Insert the planned graph inside the caller's savepoint and scope lock."""
    if projected["blockers"]:
        frappe.throw(_("Las operaciones abiertas contienen referencias sin resolver"))
    rows = projected["rows"]
    evidence_payloads = evidence_payloads or {}
    expected_evidence = {(DOCTYPES[kind], row["name"])
        for kind in ("incidents", "maintenance_orders") for row in rows[kind]
        if row.get("source_evidence_sha256")}
    if set(evidence_payloads) != expected_evidence or created_files is None:
        frappe.throw(_("Faltan evidencias verificadas de operaciones abiertas"))
    refs = {kind: [] for kind in KINDS}
    children = {kind: {} for kind in ("booking_rooms", "stay_guests",
                                     "maintenance_parts", "laundry_items")}
    for kind in children:
        for row in rows[kind]:
            children[kind].setdefault(row["parent"], []).append(row)
    for kind in ("bookings", "stays", "folios", "charges", "service_requests",
                 "cleaning_tasks", "guest_tickets", "ticket_events", "incidents",
                 "day_passes",
                 "experience_orders", "laundry_orders",
                 "portal_requests", "room_blocks", "maintenance_orders",
                 "allocations"):
        for row in rows[kind]:
            values = dict(row)
            if kind == "cleaning_tasks":
                room_status = values.pop("room_cleaning_status")
            if kind in ("incidents", "maintenance_orders"):
                evidence_sha = values.pop("source_evidence_sha256", None)
                evidence_size = values.pop("source_evidence_size", None)
                evidence_name = values.pop("source_evidence_file_name", None)
            values["doctype"] = DOCTYPES[kind]
            if kind == "bookings":
                values["rooms"] = [{key: value for key, value in child.items()
                    if key not in ("parent", "parenttype", "parentfield")}
                    for child in children["booking_rooms"].get(row["name"], [])]
            elif kind == "stays":
                values["guests"] = [{key: value for key, value in child.items()
                    if key not in ("parent", "parenttype", "parentfield")}
                    for child in children["stay_guests"].get(row["name"], [])]
            elif kind == "maintenance_orders":
                values["parts"] = [{key: value for key, value in child.items()
                    if key not in ("parent", "parenttype", "parentfield")}
                    for child in children["maintenance_parts"].get(row["name"], [])]
            elif kind == "laundry_orders":
                values["items"] = [{key: value for key, value in child.items()
                    if key not in ("parent", "parenttype", "parentfield")}
                    for child in children["laundry_items"].get(row["name"], [])]
            prior_opening = getattr(frappe.local, "hs_reverse_opening", False)
            if (kind == "day_passes" or
                    kind == "service_requests" and values.get("opening_stock_issue") or
                    kind == "maintenance_orders" and any(
                        part.get("opening_stock_issue")
                        for part in values.get("parts", []))):
                frappe.local.hs_reverse_opening = True
            try:
                doc = frappe.get_doc(values).insert(ignore_permissions=True,
                    set_name=row["name"], set_child_names=False)
            finally:
                frappe.local.hs_reverse_opening = prior_opening
            refs[kind].append(doc.name)
            if kind in ("incidents", "maintenance_orders") and evidence_sha:
                from frappe.utils.file_manager import save_file

                payload = evidence_payloads[(doc.doctype, doc.name)]
                content = payload.get("content")
                if (not isinstance(content, bytes) or
                        len(content) != evidence_size or
                        sha256(content).hexdigest() != evidence_sha or
                        payload.get("file_name") != evidence_name or
                        payload.get("sha256") != evidence_sha):
                    frappe.throw(_("Cambió la evidencia de la operación"))
                attachment = save_file(evidence_name, content,
                    doc.doctype, doc.name, is_private=1, df="evidence")
                created_files.append((attachment.file_url,
                    Path(attachment.get_full_path())))
                frappe.db.set_value(doc.doctype, doc.name, "evidence",
                    attachment.file_url, update_modified=False)
            if kind == "cleaning_tasks":
                room = frappe.get_doc("HS Room", doc.room)
                room.cleaning_status = room_status
                room.save(ignore_permissions=True)
            if kind == "bookings":
                refs["booking_rooms"].extend(child.name for child in doc.rooms)
            elif kind == "stays":
                refs["stay_guests"].extend(child.name for child in doc.guests)
            elif kind == "maintenance_orders":
                refs["maintenance_parts"].extend(child.name for child in doc.parts)
            elif kind == "laundry_orders":
                refs["laundry_items"].extend(child.name for child in doc.items)
    for kind in KINDS:
        if set(refs[kind]) != {row["name"] for row in rows[kind]}:
            frappe.throw(_("La apertura PMS cambió identificadores operativos"))
    _advance_imported_series(refs)
    return refs


def _advance_imported_series(refs):
    """Keep the next local name above names preserved from the ERP source."""
    from frappe.model.naming import NamingSeries

    for kind, names in refs.items():
        if not names:
            continue
        series_format = frappe.get_meta(DOCTYPES[kind]).autoname or ""
        counter = series_format.rsplit(".", 1)[-1]
        if not counter or set(counter) != {"#"}:
            continue
        head, year_token, tail = series_format.partition(".YYYY.")
        if year_token:
            suffix = tail.removesuffix("." + counter)
            pattern = re.compile(re.escape(head) +
                r"(?P<year>[0-9]{4})" + re.escape(suffix) +
                r"(?P<sequence>[0-9]{" + str(len(counter)) + r"})")
            highest = {}
            for name in names:
                if match := pattern.fullmatch(name):
                    year = match.group("year")
                    highest[year] = max(highest.get(year, 0),
                        int(match.group("sequence")))
            series_values = ((NamingSeries(series_format.replace(
                ".YYYY.", f".{year}.")), number)
                for year, number in highest.items())
        else:
            series = NamingSeries(series_format)
            prefix = series.get_prefix()
            imported = [int(name[len(prefix):]) for name in names
                if name.startswith(prefix) and re.fullmatch(
                    r"[0-9]{" + str(len(counter)) + r"}",
                    name[len(prefix):])]
            series_values = ((series, max(imported)),) if imported else ()
        for series, high_watermark in series_values:
            if series.get_current_value() < high_watermark:
                series.update_counter(high_watermark)
