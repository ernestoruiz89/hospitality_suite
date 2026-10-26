"""Race real PMS folio billing in two database sessions on a disposable site."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_cash import expected as cash_expected
from hospitality_suite.standalone_accounting import balance, provider
from hospitality_suite.standalone_receivables import outstanding
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
    scoped = ("HS PMS Allocation", "HS Payment", "HS Shift", "HS Journal",
        "HS PMS Receivable", "HS Charge",
        "HS Folio", "HS Stay", "HS Guest", "HS Product", "HS Rate",
        "HS Room", "HS Category", "HS Party", "HS Payment Method",
        "HS Account",
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
        bank = api.execute(property_name, "pms_account", "billing-bank-" + suffix,
            {"account_code": "1010" + suffix, "account_name": "Banco de prueba",
             "root_type": "Asset", "account_type": "Bank"})["account"]
        cash = api.execute(property_name, "pms_account", "billing-cash-" + suffix,
            {"account_code": "1000" + suffix, "account_name": "Caja de prueba",
             "root_type": "Asset", "account_type": "Cash"})["account"]
        bank_method = api.execute(property_name, "pms_payment_method",
            "billing-bank-method-" + suffix,
            {"label": "Banco de facturación", "account": bank})["method"]
        cash_method = api.execute(property_name, "pms_payment_method",
            "billing-cash-method-" + suffix,
            {"label": "Efectivo de facturación", "account": cash})["method"]
        shift = api.execute(property_name, "pms_open_shift",
            "billing-shift-" + suffix,
            {"opening_by_currency": {"NIO": "0.00"}})["shift"]
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
        sites_path = Path(frappe.local.sites_path).resolve()
        for index, same_key in enumerate((True, False)):
            receivable = (first_result if index == 0 else second_result)[
                "receivables"][0]["receivable"]
            value = "100" if index == 0 else "40"
            payment = {"kind": "Payment", "amount": value,
                "method": cash_method if index == 0 else bank_method,
                "receivable": receivable,
                "reference": f"BILLING-RACE-PAY-{index}-{suffix}",
                "reason": "Cobro concurrente de cuenta de prueba"}
            if index == 0:
                payment["shift"] = shift
            reviewed = api.pms_cash_preview(property_name, payment)
            if Decimal(str(reviewed["base_amount"])) != Decimal(value):
                raise AssertionError("Payment quote changed the reviewed amount")
            payment.update(expected_exchange_rate=reviewed["exchange_rate"],
                expected_rate_record=reviewed["exchange_rate_record"],
                expected_debit=reviewed["debit"],
                expected_credit=reviewed["credit"])
            frappe.db.commit()
            posted = race_command(SITE, sites_path, property_name,
                "pms_cash_movement", payment,
                f"billing-race-payment-{index}-{suffix}",
                same_key=same_key)
            frappe.db.rollback()
            if (not posted["allocation"] or
                    outstanding(frappe.get_doc("HS Property", property_name),
                        receivable) != 0 or
                    frappe.db.count("HS Payment", {"property": property_name,
                        "kind": "Payment", "status": "Posted"}) != index + 1 or
                    frappe.db.count("HS PMS Allocation", {
                        "property": property_name, "kind": "Direct"}) != index + 1 or
                    frappe.db.count("HS Request", {"property": property_name,
                        "operation": "pms_cash_movement"}) != index + 1):
                raise AssertionError("Concurrent collection duplicated a payment")
        actual = frappe.get_doc("HS Property", property_name)
        if (Decimal(balance(actual, ar)) != 0 or
                Decimal(balance(actual, cash)) != Decimal("100") or
                Decimal(balance(actual, bank)) != Decimal("40") or
                Decimal(balance(actual, income)) != Decimal("-140") or
                cash_expected(frappe.get_doc("HS Shift", shift))["NIO"] !=
                    "100.00" or
                frappe.db.count("HS Journal", {"property": property_name,
                    "purpose": "Payment"}) != 2 or
                frappe.db.count("HS Payment", {"property": property_name,
                    "method": cash_method, "shift": shift,
                    "status": "Posted"}) != 1 or
                frappe.db.count("HS Payment", {"property": property_name,
                    "method": bank_method, "status": "Posted"}) != 1 or
                frappe.db.count("HS Audit Event", {"property": property_name,
                    "action": "pms_cash_movement_posted"}) != 2):
            raise AssertionError("Collected funds, receivables and income diverged")
        return {"site": SITE, "same_key": "same_result",
            "distinct_key": "rejected", "receivables": 2,
            "payments": 2, "payment_journals": 2,
            "receivable_balance": "0.00", "cash_expected": "100.00",
            "bank_balance": "40.00"}
    finally:
        _remove(property_name, organization)
