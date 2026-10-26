"""Departure review scoped to a property and its active accounting provider."""

from decimal import Decimal

import frappe
from frappe import _

from hospitality_suite.security import document, require
from hospitality_suite.service import current_all
from hospitality_suite.standalone_accounting import provider, require_pms
from hospitality_suite.standalone_receivables import deposit_available


def unsettled_guarantees(prop, stay):
    """A booking guarantee is due at the last departure; a stay folio is due now."""
    from hospitality_suite.accounting import folios_for_stay

    last_departure = not frappe.db.exists("HS Stay", {
        "property": prop.name, "booking": stay.booking, "status": "Active",
        "name": ["!=", stay.name],
    }) if stay.booking else True
    folio_names = [row.name for row in folios_for_stay(stay)
                   if row.stay == stay.name or (last_departure and not row.stay)]
    payments = {}
    if folio_names:
        for row in current_all("HS Payment", filters={
                "property": prop.name, "kind": "Guarantee", "status": "Posted",
                "folio": ["in", folio_names]}, fields=["name", "currency", "folio", "booking"]):
            payments[row.name] = row
    if last_departure and stay.booking:
        for row in current_all("HS Payment", filters={
                "property": prop.name, "kind": "Guarantee", "status": "Posted",
                "booking": stay.booking}, fields=["name", "currency", "folio", "booking"]):
            payments[row.name] = row
    result = []
    for row in payments.values():
        available = deposit_available(prop, row.name, "Guarantee")
        if available > 0:
            result.append({"payment": row.name, "currency": prop.currency,
                           "available": format(available.quantize(Decimal("0.01")), "f")})
    return result


def _property(property_name, accounting_provider):
    prop = require(property_name, "stay")
    if provider() != accounting_provider:
        frappe.throw(_("La salida solicitada no corresponde al modo contable activo"))
    if accounting_provider == "pms":
        require_pms(prop)
    return prop


def snapshot(property_name, accounting_provider="pms"):
    prop = _property(property_name, accounting_provider)
    rows = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"},
        fields=["name", "guest", "room", "booking", "starts_at", "ends_at", "modified"],
        order_by="ends_at asc", limit_page_length=500)
    from hospitality_suite.time import local
    for row in rows:
        row["guest_label"] = frappe.db.get_value("HS Guest", row.guest, "full_name") or row.guest
        row["room_label"] = frappe.db.get_value("HS Room", row.room, "room_number") or row.room
        row["ends_at_local"] = local(row.ends_at, prop).strftime("%Y-%m-%d %H:%M")
    return {"property": prop.name, "currency": prop.currency, "stays": rows}


def detail(property_name, stay_name, accounting_provider="pms"):
    prop = _property(property_name, accounting_provider)
    stay = document("HS Stay", stay_name, "stay")
    if stay.property != prop.name or stay.status != "Active":
        frappe.throw(_("Seleccione una estancia activa del establecimiento"))
    from hospitality_suite.accounting import folio_balance, folios_for_stay
    from hospitality_suite.timing import departure

    if accounting_provider == "pms":
        from hospitality_suite.standalone_credit import snapshot as credit_snapshot
        guarantees = unsettled_guarantees(prop, stay)
    else:
        from hospitality_suite.credit import snapshot as credit_snapshot
        from hospitality_suite.accounting import unsettled_guarantees as erp_guarantees

        guarantees = [{"payment": row["payment"], "currency": prop.currency,
                       "available": format(Decimal(str(row["available"])).quantize(
                           Decimal("0.01")), "f")}
                      for row in erp_guarantees(prop, stay)
                      if Decimal(str(row["available"])) > 0]
    folios = []
    credit_by_party = {}
    for row in folios_for_stay(stay):
        balance = folio_balance(row.name)
        if Decimal(balance["outstanding"]) > 0 and row.customer not in credit_by_party:
            review = credit_snapshot(prop, row.customer)
            if accounting_provider == "pms":
                credit_by_party[row.customer] = {key: review[key] for key in (
                    "party_name", "status", "limit", "exposure", "overdue",
                    "property_credit_enabled", "credit_authorized")}
            else:
                credit_by_party[row.customer] = {
                    "party_name": frappe.db.get_value("Customer", row.customer,
                        "customer_name") or row.customer,
                    "status": review["status"], "limit": review["limit"],
                    "exposure": review["exposure"], "overdue": review["overdue"],
                    "property_credit_enabled": bool(prop.allow_credit),
                    "credit_authorized": review["credit_authorized"]}
        folios.append({"name": row.name, "label": row.label, "stay": row.stay,
                       "customer": row.customer, "balance": balance,
                       "credit": credit_by_party.get(row.customer)})
    laundry = frappe.db.count("HS Laundry Order", {"property": prop.name,
        "stay": stay.name, "status": ["in", ["Requested", "Collected", "In Process", "Ready"]]})
    services = frappe.db.count("HS Service Request", {"property": prop.name,
        "stay": stay.name, "status": ["in", ["Requested", "In Progress"]]})
    last_departure = not frappe.db.exists("HS Stay", {"property": prop.name,
        "booking": stay.booking, "status": "Active", "name": ["!=", stay.name]}) if stay.booking else True
    experiences = frappe.db.count("HS Experience Order", {"property": prop.name,
        "booking": stay.booking, "status": ["in", ["Reserved", "Confirmed"]]}) if stay.booking and last_departure else 0
    inspection = bool(prop.checkout_inspection_required)
    quote = departure(prop, {"stay": stay.name})
    return {"stay": stay.name, "modified": str(stay.modified), "currency": prop.currency,
            "room": stay.room, "booking": stay.booking, "folios": folios,
            "guarantees": guarantees, "laundry_pending": laundry,
            "services_pending": services, "experiences_pending": experiences,
            "inspection_required": inspection,
            "inspected": bool(stay.departure_inspected_by), "timing": quote,
            "departure_expires_at": str(stay.departure_expires_at or "")}
