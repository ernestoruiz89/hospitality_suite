"""Live roomless Day Pass access and its financial graph survive cutover."""

from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import pms_cutover, pms_cutover_plan


class TestPmsCutoverDayPassInventory(IntegrationTestCase):
    def test_freezes_live_pass_links_and_accepted_quote(self):
        now = datetime(2026, 10, 25, 12)
        quote = ('{"customer":"P-A","guest":"G-A","people":2,'
            '"currency":"NIO","product":"PRODUCT-A",'
            '"starts_at":"2026-10-25T12:00:00",'
            '"ends_at":"2026-10-25T15:00:00",'
            '"income_account":"INCOME-A",'
            '"receivable_account":"AR-ACCOUNT-A",'
            '"tax_profile":"TAX-A","unit_rate":"10",'
            '"net_amount":"18","tax_amount":"2",'
            '"total_amount":"20"}')
        active = frappe._dict(name="DAY-A", customer="P-A", guest="G-A",
            people=2, starts_at=now, ends_at=now + timedelta(hours=3),
            status="Issued", pms_receivable="AR-A", sales_invoice=None,
            payment=None, quote_snapshot=quote,
            modified=now)
        expired = frappe._dict({**active, "name": "DAY-B",
            "ends_at": now - timedelta(seconds=1)})
        missing_end = frappe._dict({**active, "name": "DAY-C",
            "ends_at": None})
        blockers = []
        with patch.object(pms_cutover, "_rows",
                return_value=[active, expired, missing_end]), \
                patch.object(pms_cutover, "now_datetime", return_value=now), \
                patch.object(pms_cutover, "to_site",
                    side_effect=lambda value, _prop:
                        datetime.fromisoformat(value)), \
                patch.object(pms_cutover, "_day_pass_receivable",
                    return_value={"receivable": "AR-A"}), \
                patch.object(pms_cutover, "_day_pass_fiscal",
                    return_value={"invoice": None, "credits": [],
                                  "credited_amount": "0"}), \
                patch.object(pms_cutover, "_day_pass_settlements",
                    return_value={"allocations": [], "allocated_amount": "0"}):
            result = pms_cutover._active_day_passes(
                frappe._dict(name="HOTEL-A", currency="NIO"), blockers)

        self.assertEqual([row["name"] for row in result], ["DAY-A", "DAY-C"])
        self.assertEqual(result[0]["pms_receivable"], "AR-A")
        self.assertEqual(result[0]["quote_sha256"], sha256(
            active.quote_snapshot.encode()).hexdigest())
        self.assertNotIn("quote_snapshot", result[0])
        self.assertEqual(result[0]["accepted_sale"]["total_amount"], "20")
        self.assertEqual(result[0]["source_financial"]["receivable"], "AR-A")
        self.assertIsNone(result[0]["source_fiscal"]["invoice"])
        self.assertFalse(any(row["code"] == "active_pms_day_pass_at_cutover"
                             for row in blockers))
        self.assertEqual([row["source"] for row in blockers
            if row["code"] == "invalid_active_pms_day_pass_quote"],
            ["DAY-C"])

    def test_invalid_accepted_sale_is_reported_without_dropping_live_access(self):
        now = datetime(2026, 10, 25, 12)
        row = frappe._dict(name="DAY-X", customer="P-A", guest=None, people=1,
            starts_at=now, ends_at=now + timedelta(hours=2), status="Issued",
            pms_receivable="AR-X", sales_invoice=None, payment=None,
            quote_snapshot='{"total_amount":"99"}', modified=now)
        blockers = []
        with patch.object(pms_cutover, "_rows", return_value=[row]), \
                patch.object(pms_cutover, "now_datetime", return_value=now):
            result = pms_cutover._active_day_passes(
                frappe._dict(name="HOTEL-A", currency="NIO"), blockers)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["accepted_sale"])
        self.assertEqual({item["code"] for item in blockers},
            {"invalid_active_pms_day_pass_quote"})

    def test_fully_credited_active_pass_requires_pms_cancellation(self):
        now = datetime(2026, 10, 25, 12)
        quote = ('{"customer":"P-A","people":1,"currency":"NIO",'
            '"product":"PRODUCT-A","starts_at":"2026-10-25T12:00:00",'
            '"ends_at":"2026-10-25T15:00:00","income_account":"INCOME-A",'
            '"receivable_account":"AR-A","tax_profile":"TAX-A",'
            '"unit_rate":"20","net_amount":"20","tax_amount":"0",'
            '"total_amount":"20"}')
        row = frappe._dict(name="DAY-CREDITED", customer="P-A", guest=None,
            people=1, starts_at=now, ends_at=now + timedelta(hours=3),
            status="Issued", pms_receivable="AR-CREDITED", sales_invoice=None,
            payment=None, quote_snapshot=quote, modified=now)
        blockers = []
        with patch.object(pms_cutover, "_rows", return_value=[row]), \
                patch.object(pms_cutover, "now_datetime", return_value=now), \
                patch.object(pms_cutover, "to_site",
                    side_effect=lambda value, _prop:
                        datetime.fromisoformat(value)), \
                patch.object(pms_cutover, "_day_pass_receivable",
                    return_value={"receivable": "AR-CREDITED",
                                  "outstanding_amount": "0"}), \
                patch.object(pms_cutover, "_day_pass_fiscal",
                    return_value={"invoice": None, "credits": [],
                                  "credited_amount": "20"}), \
                patch.object(pms_cutover, "_day_pass_settlements",
                    return_value={"allocations": [], "allocated_amount": "0"}):
            active = pms_cutover._active_day_passes(
                frappe._dict(name="HOTEL-A", currency="NIO"), blockers)
        self.assertEqual([item["name"] for item in active], ["DAY-CREDITED"])
        self.assertEqual([item["code"] for item in blockers],
            ["fully_credited_active_pms_day_pass"])

    def test_receivable_requires_the_original_balanced_pms_journal(self):
        prop = frappe._dict(name="HOTEL-A", company="COMP-A",
            organization="ORG-A", currency="NIO")
        day_pass = frappe._dict(pms_receivable="AR-A", customer="P-A")
        sale = {"receivable_account": "AR-ACCOUNT-A",
            "income_account": "INCOME-A", "tax_profile": "TAX-A",
            "net_amount": "18", "tax_amount": "2", "total_amount": "20"}
        receivable = frappe._dict(name="AR-A", property=prop.name,
            company=prop.company, organization=prop.organization,
            party=day_pass.customer, reference="Day Pass test", currency="NIO",
            amount="20", net_amount="18", tax_amount="2",
            tax_profile="TAX-A", receivable_account="AR-ACCOUNT-A",
            income_account="INCOME-A", tax_account="TAX-ACCOUNT-A",
            journal="J-A", status="Posted", folio=None, booking=None,
            source_charge=None, experience_order=None, opening_source_name=None)
        journal = frappe._dict(property=prop.name,
            organization=prop.organization, source_doctype="HS PMS Receivable",
            source_name=receivable.reference, purpose="Receivable",
            status="Posted")
        lines = [frappe._dict(account=account, party=party,
            account_currency="NIO", debit=debit, credit=credit,
            debit_in_account_currency=debit,
            credit_in_account_currency=credit) for account, party, debit, credit in (
                ("AR-ACCOUNT-A", "P-A", "20", "0"),
                ("INCOME-A", None, "0", "18"),
                ("TAX-ACCOUNT-A", None, "0", "2"))]

        def value(doctype, name, fields, as_dict=True):
            return {"HS PMS Receivable": receivable,
                "HS Journal": journal}.get(doctype)

        with patch.object(frappe.db, "get_value", side_effect=value), \
                patch.object(frappe, "get_all", return_value=lines), \
                patch("hospitality_suite.standalone_receivables.outstanding",
                    return_value=Decimal("20")):
            snapshot = pms_cutover._day_pass_receivable(prop, day_pass, sale)
            self.assertEqual(snapshot["total_amount"], "20")
            self.assertEqual(snapshot["outstanding_amount"], "20")
            lines[2].credit = "3"
            self.assertIsNone(pms_cutover._day_pass_receivable(
                prop, day_pass, sale))

    def test_fiscal_history_keeps_invoice_and_partial_credit(self):
        prop = frappe._dict(name="HOTEL-A", company="COMP-A",
            organization="ORG-A", currency="NIO")
        day_pass = frappe._dict(customer="P-A")
        sale = {"product": "PRODUCT-A", "net_amount": "18",
            "tax_amount": "2", "total_amount": "20"}
        financial = {"receivable": "AR-A", "income_account": "INCOME-A",
            "tax_account": "TAX-A"}
        lines = [frappe._dict(name="LINE-I", parent="INV-A",
            parenttype="HS PMS Fiscal Document", product=None,
            income_account="INCOME-A", tax_account="TAX-A",
            net_amount="18", tax_amount="2", total_amount="20"),
            frappe._dict(name="LINE-C", parent="CREDIT-A",
            parenttype="HS PMS Fiscal Document", product="PRODUCT-A",
            income_account="INCOME-A", tax_account="TAX-A",
            net_amount="9", tax_amount="1", total_amount="10")]
        documents = [frappe._dict(name=name, company=prop.company,
            property=prop.name, organization=prop.organization,
            party=day_pass.customer, currency="NIO", status="Posted",
            document_type=kind, document_number=name,
            source_invoice=source, journal=journal)
            for name, kind, source, journal in (
                ("INV-A", "Invoice", None, None),
                ("CREDIT-A", "Credit Note", "INV-A", "J-C"))]

        def rows(doctype, **kwargs):
            return lines if doctype == "HS PMS Fiscal Line" else documents

        with patch.object(frappe, "get_all", side_effect=rows):
            snapshot = pms_cutover._day_pass_fiscal(
                prop, day_pass, sale, financial)
            self.assertEqual(snapshot["invoice"]["document"], "INV-A")
            self.assertEqual(snapshot["credited_amount"], "10")
            documents[1].source_invoice = "WRONG-INVOICE"
            self.assertIsNone(pms_cutover._day_pass_fiscal(
                prop, day_pass, sale, financial))

    def test_split_payments_and_partial_refund_reconcile_day_pass(self):
        prop = frappe._dict(name="HOTEL-A", company="COMP-A",
            organization="ORG-A", currency="NIO")
        sale = {"total_amount": "100"}
        financial = {"receivable": "AR-A", "outstanding_amount": "55"}
        fiscal = {"credited_amount": "10"}
        day_pass = frappe._dict(customer="P-A")
        rows = [frappe._dict(name=name, company=prop.company,
            property=prop.name, organization=prop.organization,
            receivable="AR-A", payment=payment,
            opening_credit=None, opening_guarantee=None, kind=kind,
            reverses=reverses, business_date="2026-10-25", currency="NIO",
            amount=amount, journal=journal)
            for name, payment, kind, reverses, amount, journal in (
                ("APL-A", "PAY-A", "Direct", None, "20", "J-A"),
                ("APL-B", "PAY-B", "Direct", None, "20", "J-B"),
                ("APL-C", "REF-A", "Direct Reversed", "APL-A", "5", "J-C"))]
        payments = [frappe._dict(name=name, company=prop.company,
            property=prop.name, pms_party=day_pass.customer, kind=kind,
            status="Posted", method="METHOD-A", currency="NIO", amount=amount,
            exchange_rate="1", pms_counter_account="AR-ACCOUNT-A",
            base_amount=amount, pms_receivable="AR-A", pms_journal=journal,
            source_payment=source) for name, kind, amount, journal, source in (
                ("PAY-A", "Payment", "20", "J-A", None),
                ("PAY-B", "Payment", "20", "J-B", None),
                ("REF-A", "Refund", "5", "J-C", "PAY-A"))]
        journals = [frappe._dict(name=name, property=prop.name,
            organization=prop.organization, status="Posted")
            for name in ("J-A", "J-B", "J-C")]

        def fetch(doctype, **_kwargs):
            return {"HS PMS Allocation": rows, "HS Payment": payments,
                "HS Journal": journals}[doctype]

        with patch.object(frappe, "get_all", side_effect=fetch):
            result = pms_cutover._day_pass_settlements(
                prop, day_pass, sale, financial, fiscal)
            self.assertEqual(result["allocated_amount"], "35")
            self.assertEqual(len(result["allocations"]), 3)
            rows[2].amount = "21"
            self.assertIsNone(pms_cutover._day_pass_settlements(
                prop, day_pass, sale, financial, fiscal))
            rows[2].amount = "5"
            rows[1].property = "OTHER-HOTEL"
            self.assertIsNone(pms_cutover._day_pass_settlements(
                prop, day_pass, sale, financial, fiscal))

    def test_continuation_plan_maps_original_sale_to_opening_balance(self):
        financial = {"receivable": "AR-A", "outstanding_amount": "55",
            "receivable_account": "PMS-AR", "income_account": "PMS-SALES",
            "tax_account": "PMS-TAX"}
        day_pass = {"name": "DAY-A", "customer": "P-A", "people": 2,
            "starts_at": "2026-10-25 12:00:00",
            "ends_at": "2026-10-25 15:00:00",
            "accepted_sale": {"product": "PMS-DAY", "total_amount": "100"},
            "source_financial": financial,
            "source_fiscal": {"invoice": None, "credits": [],
                              "credited_amount": "10"},
            "source_settlements": {"allocations": [],
                                   "allocated_amount": "35"}}
        source = {"property": "HOTEL-A",
            "open_operations": {"day_passes": [day_pass]}}
        mapping = {"company": "COMP-A", "products": {"PMS-DAY": "ERP-DAY"},
            "parties": {"P-A": {"customer": "ERP-CUSTOMER"}},
            "accounts": {"PMS-AR": "ERP-AR", "PMS-SALES": "ERP-SALES",
                         "PMS-TAX": "ERP-TAX"}}
        receivables = [{"source": "AR-A", "outstanding": "55"}]
        blockers = []
        service_item = frappe._dict(is_sales_item=1, is_stock_item=0,
            is_fixed_asset=0, disabled=0)
        with patch.object(frappe.db, "get_value", return_value=service_item), \
                patch.object(frappe.db, "exists", return_value=True):
            result = pms_cutover_plan._day_pass_continuations(
                source, mapping, receivables, blockers)
            self.assertFalse(blockers)
            self.assertEqual(result[0]["opening_receivable_source"], "AR-A")
            self.assertEqual(result[0]["customer"], "ERP-CUSTOMER")
            self.assertEqual(result[0]["target_accounts"]["income_account"],
                             "ERP-SALES")
            self.assertEqual(result[0]["outstanding"], "55")
            receivables[0]["outstanding"] = "54"
            self.assertFalse(pms_cutover_plan._day_pass_continuations(
                source, mapping, receivables, blockers))
            self.assertEqual(blockers[0]["code"],
                             "unmapped_day_pass_continuation")
