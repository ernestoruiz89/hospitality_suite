"""Race real PMS folio billing in two database sessions on a disposable site."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_accounting import balance, provider
from hospitality_suite.tests.financial_race import race_command


SITE = "hs-pms-smoke-room.local"


def _charge(prop, folio, stay, product, value, suffix):
    def create(locked):
        return insert("HS Charge", locked, stay=stay, folio=folio,
            item=product, description="Noche de prueba " + suffix,
            quantity=1, rate=value, currency=locked.currency, amount=value,
            business_date=locked.business_date, kind="Lodging",
            status="Pending").name

    return command(prop.name, "stay", "billing-charge-" + suffix,
        {"operation": "billing_race_fixture"}, create)


def _verify(prop, folio, charge_names, account, income, expected):
    frappe.db.rollback()
    actual = frappe.get_doc("HS Property", prop.name)
    receivables = frappe.get_all("HS PMS Receivable", filters={
        "property": prop.name, "folio": folio, "status": "Posted"},
        fields=["name", "journal", "amount"])
    journals = frappe.get_all("HS Journal", filters={
        "property": prop.name, "purpose": "Receivable"}, pluck="name")
    if (len(receivables) != len(charge_names) or
            set(journals) != {row.journal for row in receivables} or
            Decimal(balance(actual, account)) != expected or
            Decimal(balance(actual, income)) != -expected or
            sum((Decimal(str(row.amount)) for row in receivables),
                Decimal(0)) != expected or
            any(frappe.db.get_value("HS Charge", name, "pms_receivable")
                not in {row.name for row in receivables} for name in charge_names) or
            any(frappe.db.get_value("HS Charge", name, "status") != "Posted"
                for name in charge_names)):
        raise AssertionError("Folio, receivables and ledger did not reconcile")
    return receivables


def _remove(property_name, organization):
    frappe.db.rollback()
    scoped = ("HS Journal", "HS PMS Receivable", "HS Charge",
        "HS Folio", "HS Stay", "HS Guest", "HS Product", "HS Rate",
        "HS Room", "HS Category", "HS Party", "HS Account",
        "HS Audit Event", "HS Request")
    journals = []
    if property_name:
        journals = frappe.get_all("HS Journal", filters={
            "property": property_name}, pluck="name", limit_page_length=0)
        if journals:
            frappe.db.delete("HS Journal Line", {"parent": ["in", journals]})
        for doctype in scoped:
            frappe.db.delete(doctype, {"property": property_name})
        frappe.db.delete("HS Property", {"name": property_name})
    if organization:
        frappe.db.delete("HS Organization", {"name": organization})
    frappe.db.commit()
    if (property_name and frappe.db.exists("HS Property", property_name) or
            organization and frappe.db.exists("HS Organization", organization) or
            property_name and any(frappe.db.count(doctype, {
                "property": property_name}) for doctype in scoped) or
            journals and frappe.db.count("HS Journal Line", {
                "parent": ["in", journals]})):
        raise AssertionError("Disposable billing fixture was not removed")


def run():
    if (frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps() or
            provider() != "pms" or frappe.session.user != "Administrator"):
        frappe.throw("Use only the disposable Frappe-only PMS site as Administrator")
    suffix = uuid4().hex[:12]
    property_name = None
    organization = None
    try:
        created = api.create_property({
            "property_name": "Billing Race QA " + suffix,
            "new_organization": {"legal_name": "Billing Race Legal " + suffix},
            "currency": "NIO", "mode": "Hotel",
        }, "billing-race-property-" + suffix)
        property_name = created["property"]
        prop = frappe.get_doc("HS Property", property_name)
        organization = prop.organization
        ar = api.execute(property_name, "pms_account", "billing-ar-" + suffix,
            {"account_code": "1200" + suffix, "account_name": "Cartera de prueba",
             "root_type": "Asset", "account_type": "Receivable"})["account"]
        income = api.execute(property_name, "pms_account", "billing-income-" + suffix,
            {"account_code": "4000" + suffix, "account_name": "Ingreso de prueba",
             "root_type": "Income"})["account"]
        party = api.execute(property_name, "pms_customer",
            "billing-party-" + suffix,
            {"party_name": "Huésped facturación " + suffix})["party"]

        def masters(locked):
            category = insert("HS Category", locked,
                category_name="Categoría facturación", capacity=2)
            room = insert("HS Room", locked, room_number="RACE-" + suffix,
                category=category.name, active=1, cleaning_status="Clean")
            rate = insert("HS Rate", locked, title="Tarifa facturación",
                category=category.name, mode="Hotel", currency=locked.currency,
                amount=100, active=1)
            guest = insert("HS Guest", locked,
                full_name="Huésped facturación", customer=party)
            start = frappe.utils.now_datetime()
            stay = insert("HS Stay", locked, guest=guest.name, customer=party,
                room=room.name, rate=rate.name, currency=locked.currency,
                amount="100", starts_at=start,
                ends_at=start + timedelta(days=1), status="Active",
                lodging_charge_policy="Arrival")
            folio = insert("HS Folio", locked, stay=stay.name, customer=party,
                currency=locked.currency, status="Open", label="Cuenta principal")
            product = insert("HS Product", locked, organization=organization,
                product_code="ROOM" + suffix, product_name="Alojamiento",
                product_type="Service", income_account=income, active=1)
            return {"folio": folio.name, "stay": stay.name,
                "product": product.name}

        fixture = command(property_name, "setup", "billing-masters-" + suffix,
            {"operation": "billing_race_masters"}, masters)
        first_charge = _charge(prop, fixture["folio"], fixture["stay"],
            fixture["product"], "100", suffix + "-first")
        quote = api.pms_folio_quote(property_name, {
            "folio": fixture["folio"], "receivable_account": ar})
        if quote["total"] != "100.00" or len(quote["lines"]) != 1:
            raise AssertionError("The first charge was not quotable")
        frappe.db.commit()
        payload = {"folio": fixture["folio"], "receivable_account": ar,
            "acceptance": quote["acceptance"]}
        first_result = race_command(SITE,
            Path(frappe.local.sites_path).resolve(), property_name,
            "pms_bill_folio", payload,
            "billing-race-same-" + suffix, same_key=True)
        first_rows = _verify(prop, fixture["folio"], [first_charge],
            ar, income, Decimal("100"))
        if (first_result["receivables"][0]["receivable"] !=
                first_rows[0].name or frappe.db.count("HS Request", {
                    "property": property_name,
                    "operation": "pms_bill_folio"}) != 1):
            raise AssertionError("Same-key billing created another receivable")

        second_charge = _charge(prop, fixture["folio"], fixture["stay"],
            fixture["product"], "40", suffix + "-second")
        quote = api.pms_folio_quote(property_name, {
            "folio": fixture["folio"], "receivable_account": ar})
        if quote["total"] != "40.00" or len(quote["lines"]) != 1:
            raise AssertionError("The second charge was not quotable")
        frappe.db.commit()
        payload["acceptance"] = quote["acceptance"]
        second_result = race_command(SITE,
            Path(frappe.local.sites_path).resolve(), property_name,
            "pms_bill_folio", payload,
            "billing-race-distinct-" + suffix, same_key=False)
        rows = _verify(prop, fixture["folio"],
            [first_charge, second_charge], ar, income, Decimal("140"))
        if (second_result["receivables"][0]["receivable"] not in
                {row.name for row in rows} or
                frappe.db.count("HS Request", {"property": property_name,
                    "operation": "pms_bill_folio"}) != 2 or
                frappe.db.count("HS Audit Event", {"property": property_name,
                    "action": "pms_folio_billed"}) != 2):
            raise AssertionError("Distinct-key billing posted twice")
        return {"site": SITE, "same_key": "same_result",
            "distinct_key": "rejected", "receivables": 2,
            "journals": 2, "balance": "140.00"}
    finally:
        _remove(property_name, organization)
