"""A migrated Day Pass points to its opening balance without another sale."""

from hashlib import sha256
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import day_pass, pms_cutover_writer
from hospitality_suite.service import canonical


class TestPmsCutoverDayPassWriter(IntegrationTestCase):
    def test_binds_only_the_matching_opening_invoice(self):
        quote = '{"product":"PMS-DAY","total_amount":"80"}'
        planned = {"source": "DAY-A", "property": "HOTEL-A",
            "company": "COMP-A", "customer": "ERP-CUSTOMER",
            "source_receivable": "AR-A",
            "opening_receivable_source": "AR-A", "outstanding": "40",
            "source_hashes": {"quote_sha256":
                sha256(quote.encode()).hexdigest()}}
        property_plan = {"property": "HOTEL-A", "company": "COMP-A",
            "opening_receivables": [{"source": "AR-A"}],
            "continuing_day_passes": [planned]}
        refs = {"receivables": ["INV-OPEN-A"], "day_passes": [],
            "source_documents": []}
        day_pass = frappe._dict(name="DAY-A", property="HOTEL-A",
            company="COMP-A", customer="ERP-CUSTOMER", status="Issued",
            pms_receivable="AR-A", quote_snapshot=quote, service=None,
            sales_invoice=None, payment=None, erp_opening_invoice=None,
            erp_opening_snapshot=None, erp_opening_sha256=None)
        invoice = frappe._dict(company="COMP-A", hs_property="HOTEL-A",
            customer="ERP-CUSTOMER", docstatus=1, outstanding_amount="40")
        writes = []

        def value(doctype, _name, _fields, as_dict=True):
            return {"HS Day Pass": day_pass,
                    "Sales Invoice": invoice}[doctype]

        def write(_doctype, _name, fields, update_modified=False):
            writes.append(fields)

        with patch.object(frappe.db, "get_value", side_effect=value), \
                patch.object(frappe.db, "set_value", side_effect=write):
            pms_cutover_writer._bind_day_passes(property_plan, refs)
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]["erp_opening_invoice"], "INV-OPEN-A")
            self.assertEqual(refs["day_passes"][0]["snapshot_sha256"],
                             writes[0]["erp_opening_sha256"])
            self.assertEqual(refs["source_documents"][0]["relationship"],
                             "outstanding_balance")
            writes.clear()
            invoice.outstanding_amount = "39"
            with self.assertRaises(frappe.ValidationError):
                pms_cutover_writer._bind_day_passes(property_plan, refs)
            self.assertFalse(writes)

    def test_fully_paid_pass_gets_proof_without_an_opening_invoice(self):
        quote = '{"total_amount":"80"}'
        planned = {"source": "DAY-B", "property": "HOTEL-A",
            "company": "COMP-A", "customer": "ERP-CUSTOMER",
            "source_receivable": "AR-B",
            "opening_receivable_source": None, "outstanding": "0",
            "source_hashes": {"quote_sha256":
                sha256(quote.encode()).hexdigest()}}
        prop = {"property": "HOTEL-A", "company": "COMP-A",
            "opening_receivables": [], "continuing_day_passes": [planned]}
        refs = {"receivables": [], "day_passes": [], "source_documents": []}
        day_pass = frappe._dict(name="DAY-B", property="HOTEL-A",
            company="COMP-A", customer="ERP-CUSTOMER", status="Issued",
            pms_receivable="AR-B", quote_snapshot=quote, service=None,
            sales_invoice=None, payment=None, erp_opening_invoice=None,
            erp_opening_snapshot=None, erp_opening_sha256=None)
        with patch.object(frappe.db, "get_value", return_value=day_pass), \
                patch.object(frappe.db, "set_value") as write:
            pms_cutover_writer._bind_day_passes(prop, refs)
            self.assertIsNone(write.call_args.args[2]["erp_opening_invoice"])
            self.assertFalse(refs["source_documents"])

    def test_erp_view_separates_original_sale_from_opening_balance(self):
        prop = frappe._dict(name="HOTEL-A", company="COMP-A", currency="NIO",
            time_zone="America/Managua", day_pass_item=None,
            price_list=None, receivable_account="ERP-AR")
        proof = canonical({"source": "DAY-A", "property": prop.name,
            "customer": "ERP-CUSTOMER", "source_receivable": "AR-A",
            "opening_invoice": "INV-OPEN-A",
            "accepted_sale": {"total_amount": "80"},
            "source_fiscal": {"invoice": {
                "document_number": "PMS-FISCAL-001"}}})
        row = frappe._dict(name="DAY-A", customer="ERP-CUSTOMER",
            guest=None, people=2, starts_at="2026-10-25 12:00:00",
            ends_at="2026-10-25 15:00:00", status="Issued",
            service=None, sales_invoice=None, payment=None,
            pms_receivable="AR-A", erp_opening_invoice="INV-OPEN-A",
            erp_opening_snapshot=proof,
            erp_opening_sha256=sha256(proof.encode()).hexdigest())
        invoice = frappe._dict(name="INV-OPEN-A", company=prop.company,
            hs_property=prop.name, customer="ERP-CUSTOMER", docstatus=1,
            grand_total="40", outstanding_amount="40", currency="NIO")
        old_legacy = frappe._dict({**row, "name": "DAY-OLD",
            "pms_receivable": "AR-OLD", "erp_opening_invoice": None,
            "erp_opening_snapshot": None, "erp_opening_sha256": None})

        def fetch(doctype, **_kwargs):
            return {"HS Day Pass": [row, old_legacy],
                    "Sales Invoice": [invoice]}.get(
                doctype, [])

        with patch("hospitality_suite.security.require", return_value=prop), \
                patch("hospitality_suite.standalone_accounting.provider",
                    return_value="erpnext"), \
                patch.object(frappe, "get_all", side_effect=fetch), \
                patch.object(frappe.db, "get_value", return_value=None):
            snapshot = day_pass.erp_snapshot(prop.name)
            visible = snapshot["day_passes"][0]
            self.assertEqual(visible["amount"], "80")
            self.assertEqual(visible["outstanding"], "40")
            self.assertEqual(visible["historical_invoice_number"],
                             "PMS-FISCAL-001")
            self.assertTrue(visible["historical"])
            self.assertTrue(snapshot["day_passes"][1]["transfer_problem"])
            row.erp_opening_sha256 = "bad"
            with self.assertRaises(frappe.ValidationError):
                day_pass.erp_snapshot(prop.name)
