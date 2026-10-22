"""Native postings and approvals for the two new treasury ledgers."""
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.financial_movements import balance, outstanding
from hospitality_suite.close_financials import snapshot
from hospitality_suite.service import operation
from hospitality_suite.service import lock_property


class TestFinancialMovements(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        self.cash = frappe.db.get_value("HS Payment Method", {"property": self.prop.name, "is_cash": 1, "currency": "NIO"})
        self.shift = self.call("open_shift", {"opening_amount": 500})["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self, action, data, key=None):
        return api.execute(self.prop.name, action, key or uuid.uuid4().hex, data)

    def account(self, label, root="Asset", kind=None):
        parent = frappe.db.get_value("Account", {"company": self.prop.company, "root_type": root, "is_group": 1}, "name")
        return frappe.get_doc(dict(doctype="Account", company=self.prop.company, parent_account=parent,
                                   account_name=label + uuid.uuid4().hex[:7], account_currency="NIO",
                                   account_type=kind)).insert().name

    def petty(self):
        self.prop.petty_cash_account = self.account("Caja Chica prueba ", kind="Cash")
        self.prop.petty_cash_overage_account = self.account("Sobrante prueba ", "Income")
        self.prop.petty_cash_shortage_account = self.account("Faltante prueba ", "Expense")
        self.prop.petty_cash_responsible = "Administrator"
        self.prop.save()
        expense_account = self.account("Gasto menor prueba ", "Expense")
        with operation(self.prop):
            category = frappe.get_doc(dict(doctype="HS Expense Category", company=self.prop.company,
                                           property=self.prop.name, label="Prueba Caja Chica", account=expense_account,
                                           max_amount=100, active=1)).insert()
        return category

    def concept(self, nature):
        account = self.account("Concepto prueba ", {"Other Income": "Income", "Loan": "Liability", "Capital": "Equity"}[nature])
        with operation(self.prop):
            concept = frappe.get_doc(dict(doctype="HS Treasury Concept", property=self.prop.name,
                                          company=self.prop.company, label="Concepto " + nature,
                                          nature=nature, account=account, active=1)).insert()
        return concept

    def test_petty_cash_posts_variance_and_only_replenishes_approved_expenses(self):
        category = self.petty()
        fund_data = dict(kind="Initial Fund", shift=self.shift, method=self.cash, amount=200)
        with self.assertRaises(frappe.ValidationError):
            self.call("petty_fund", dict(fund_data, amount=501))
        key = uuid.uuid4().hex
        fund = self.call("petty_fund", fund_data, key)
        self.assertEqual(self.call("petty_fund", fund_data, key), fund)
        self.assertEqual(expected(frappe.get_doc("HS Shift", self.shift))["NIO"], "300.00")
        with self.assertRaises(frappe.ValidationError):
            self.call("petty_fund", fund_data)
        with self.assertRaises(frappe.ValidationError):
            self.call("petty_expense", dict(category=category.name, amount=101, beneficiary="Proveedor",
                                           concept="Compra", receipt_reference="REC-1"))
        expense = self.call("petty_expense", dict(category=category.name, amount=50, beneficiary="Proveedor",
                                                   concept="Compra menor", receipt_reference="REC-1"))
        self.assertEqual(balance(self.prop), 150)
        lines = frappe.get_doc("Journal Entry", expense["journal_entry"]).accounts
        self.assertEqual(sum(row.debit for row in lines if row.account == category.account), 50)
        rendition = self.call("petty_rendition", dict(counted_cash=155, explanation="Sobrante contado"))
        with self.assertRaises(frappe.ValidationError):
            self.call("petty_review", dict(rendition=rendition["rendition"], approve=1))
        frappe.set_user("manager@hospitality.example.invalid")
        approved = self.call("petty_review", dict(rendition=rendition["rendition"], approve=1))
        self.assertEqual(approved["status"], "Approved")
        frappe.set_user("Administrator")
        self.assertEqual(balance(self.prop), 155)
        self.call("petty_fund", dict(kind="Replenishment", rendition=rendition["rendition"], shift=self.shift,
                                      method=self.cash, amount=20))
        self.assertEqual(balance(self.prop), 175)
        with self.assertRaises(frappe.ValidationError):
            self.call("petty_fund", dict(kind="Replenishment", rendition=rendition["rendition"], shift=self.shift,
                                          method=self.cash, amount=31))
        self.call("petty_fund", dict(kind="Replenishment", rendition=rendition["rendition"], shift=self.shift,
                                      method=self.cash, amount=30))
        self.assertEqual(frappe.db.get_value("HS Petty Cash Rendition", rendition["rendition"], "status"), "Reimbursed")
        self.assertEqual(expected(frappe.get_doc("HS Shift", self.shift))["NIO"], "250.00")

    def test_financing_approval_original_principal_and_bank_or_cash(self):
        concept = self.concept("Loan")
        bank = self.account("Banco préstamo ", kind="Bank")
        request = self.call("finance_request", dict(kind="Loan Received", concept=concept.name, amount=100))
        with self.assertRaises(frappe.ValidationError):
            self.call("finance_approve", dict(movement=request["movement"]))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("finance_approve", dict(movement=request["movement"]))
        frappe.set_user("Administrator")
        received = self.call("finance_post", dict(movement=request["movement"], channel="Bank",
                                                  bank_account=bank, reference="BAN-1"))
        self.assertEqual((received["debit"], received["credit"]), (bank, concept.account))
        source = frappe.get_doc("HS Treasury Movement", request["movement"])
        repayment = self.call("finance_request", dict(kind="Loan Repayment", source_movement=source.name, amount=40))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("finance_approve", dict(movement=repayment["movement"]))
        frappe.set_user("Administrator")
        self.call("finance_post", dict(movement=repayment["movement"], channel="Cash", shift=self.shift, method=self.cash))
        self.assertEqual(outstanding(source), 60)
        self.assertEqual(expected(frappe.get_doc("HS Shift", self.shift))["NIO"], "460.00")
        with self.assertRaises(frappe.ValidationError):
            self.call("finance_request", dict(kind="Loan Repayment", source_movement=source.name, amount=61))
        income = self.concept("Other Income")
        self.call("finance_post", dict(kind="Other Income", concept=income.name, amount=10,
                                        channel="Cash", shift=self.shift, method=self.cash))
        self.assertEqual(expected(frappe.get_doc("HS Shift", self.shift))["NIO"], "470.00")
        totals = next(row for row in snapshot(self.prop, {})["currencies"] if row["currency"] == "NIO")
        self.assertEqual((totals["other_income"], totals["loans_received"], totals["loans_repaid"]),
                         ("10.00", "100.00", "40.00"))
        self.assertEqual((totals["treasury_cash_in"], totals["treasury_cash_out"], totals["treasury_bank_in"]),
                         ("10.00", "40.00", "100.00"))

    def test_handover_needs_both_acceptances(self):
        self.petty()
        request = self.call("petty_handover", dict(incoming="manager@hospitality.example.invalid", counted_cash=0))
        self.call("petty_accept", dict(handover=request["handover"]))
        self.assertEqual(frappe.db.get_value("HS Property", self.prop.name, "petty_cash_responsible"), "Administrator")
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("petty_accept", dict(handover=request["handover"]))
        self.assertEqual(frappe.db.get_value("HS Property", self.prop.name, "petty_cash_responsible"), "manager@hospitality.example.invalid")

    def test_account_cannot_be_removed_with_balance_or_unsettled_expense(self):
        category = self.petty()
        self.call("petty_fund", dict(kind="Initial Fund", shift=self.shift, method=self.cash, amount=50))
        changed = frappe.get_doc("HS Property", self.prop.name)
        for field in ("petty_cash_account", "petty_cash_responsible", "petty_cash_overage_account", "petty_cash_shortage_account"):
            changed.set(field, None)
        with self.assertRaises(frappe.ValidationError):
            changed.save()
        self.call("petty_expense", dict(category=category.name, amount=50, beneficiary="Proveedor",
                                          concept="Gasto total", receipt_reference="REC-ZERO"))
        self.assertEqual(balance(self.prop), 0)
        changed = frappe.get_doc("HS Property", self.prop.name)
        changed.petty_cash_account = self.account("Otra caja chica ", kind="Cash")
        with self.assertRaises(frappe.ValidationError):
            changed.save()

    def test_returned_rendition_shortage_and_close_snapshot(self):
        category = self.petty()
        self.call("petty_fund", dict(kind="Initial Fund", shift=self.shift, method=self.cash, amount=200))
        self.call("petty_expense", dict(category=category.name, amount=50, beneficiary="Proveedor",
                                         concept="Repuesto", receipt_reference="REC-2"))
        submitted = self.call("petty_rendition", dict(counted_cash=145, explanation="Faltante de arqueo"))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("petty_review", dict(rendition=submitted["rendition"], approve=0, note="Completar comprobante"))
        with self.assertRaises(frappe.PermissionError):
            self.call("petty_expense", dict(category=category.name, amount=1, beneficiary="No responsable",
                                             concept="Otro", receipt_reference="REC-3"))
        frappe.set_user("Administrator")
        expense = frappe.db.get_value("HS Petty Cash Expense", {"rendition": submitted["rendition"]}, "name")
        self.call("petty_correct", dict(expense=expense, receipt_reference="REC-2-C", reason="Corrección descriptiva"))
        self.call("petty_rendition", dict(rendition=submitted["rendition"], counted_cash=145,
                                          explanation="Faltante de arqueo"))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("petty_review", dict(rendition=submitted["rendition"], approve=1))
        frappe.set_user("Administrator")
        rendition = frappe.get_doc("HS Petty Cash Rendition", submitted["rendition"])
        self.assertEqual(rendition.variance, -5)
        lines = frappe.get_doc("Journal Entry", rendition.variance_journal).accounts
        self.assertEqual(sum(row.debit for row in lines if row.account == self.prop.petty_cash_shortage_account), 5)
        self.assertEqual(balance(self.prop), 145)
        close = snapshot(self.prop, {})
        totals = next(row for row in close["currencies"] if row["currency"] == "NIO")
        self.assertEqual((totals["petty_initial"], totals["petty_expenses"], totals["petty_shortage"]),
                         ("200.00", "50.00", "5.00"))
        self.assertEqual(totals["production"], "0.00")
        self.assertEqual(close["sources"]["petty_variances"][0]["variance_account"], self.prop.petty_cash_shortage_account)
        self.assertEqual(close["breakdown"]["treasury"][0]["property"], self.prop.name)
        self.assertEqual(close["breakdown"]["petty_expenses"][0]["amount"], "50.00")
        self.assertEqual(close["breakdown"]["petty_expenses"][0]["category_label"], "Prueba Caja Chica")

    def test_capital_principal_and_dependency_safe_reversal(self):
        concept = self.concept("Capital")
        bank = self.account("Banco capital ", kind="Bank")
        contribution = self.call("finance_request", dict(kind="Capital Contribution", concept=concept.name, amount=100))["movement"]
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("finance_approve", dict(movement=contribution))
        frappe.set_user("Administrator")
        self.call("finance_post", dict(movement=contribution, channel="Bank", bank_account=bank, reference="CAP-1"))
        withdrawal = self.call("finance_request", dict(kind="Capital Withdrawal", source_movement=contribution, amount=40))["movement"]
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("finance_approve", dict(movement=withdrawal))
        frappe.set_user("Administrator")
        quote = api.preview(self.prop.name, dict(movement=withdrawal, kind="Capital Withdrawal", amount=40,
                                                 source_movement=contribution, channel="Bank", bank_account=bank,
                                                 reference="CAP-2"), "finance_post")
        self.assertEqual((quote["debit"], quote["credit"]), (concept.account, bank))
        self.call("finance_post", dict(movement=withdrawal, channel="Bank", bank_account=bank, reference="CAP-2"))
        with self.assertRaises(frappe.ValidationError):
            self.call("finance_request", dict(kind="Capital Withdrawal", source_movement=contribution, amount=61))
        with self.assertRaises(frappe.ValidationError):
            self.call("finance_reverse", dict(doctype="HS Treasury Movement", name=contribution, reason="Revertir"))
        self.call("finance_reverse", dict(doctype="HS Treasury Movement", name=withdrawal, reason="Corrección de retiro"))
        self.assertEqual(outstanding(frappe.get_doc("HS Treasury Movement", contribution)), 100)
        self.call("finance_reverse", dict(doctype="HS Treasury Movement", name=contribution, reason="Corrección de aporte"))
        self.assertEqual(frappe.db.get_value("HS Treasury Movement", contribution, "status"), "Cancelled")

    def test_cross_property_references_and_changed_concept_are_isolated(self):
        self.petty()
        self.call("petty_fund", dict(kind="Initial Fund", shift=self.shift, method=self.cash, amount=100))
        other = frappe.get_doc("HS Property", {"property_name": "Luna Demo · Por tiempo"})
        foreign_account = self.account("Gasto externo ", "Expense")
        with operation(other):
            category = frappe.get_doc(dict(doctype="HS Expense Category", company=other.company, property=other.name,
                                           label="Categoría externa", account=foreign_account, active=1)).insert()
        with self.assertRaises(frappe.PermissionError):
            self.call("petty_expense", dict(category=category.name, amount=5, beneficiary="Proveedor",
                                             concept="No autorizado", receipt_reference="REC-X"))
        concept = self.concept("Loan")
        first_account = concept.account
        request = self.call("finance_request", dict(kind="Loan Received", concept=concept.name, amount=35))["movement"]
        second_account = self.account("Nuevo pasivo ", "Liability")
        self.call("finance_concept", dict(concept=concept.name, modified=str(concept.modified),
                                           label="Nombre actualizado", nature="Loan", account=second_account, active=0))
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("finance_approve", dict(movement=request))
        frappe.set_user("Administrator")
        bank = self.account("Banco vigente ", kind="Bank")
        posted = self.call("finance_post", dict(movement=request, channel="Bank", bank_account=bank, reference="OLD-1"))
        self.assertEqual(posted["credit"], first_account)
        movement = frappe.get_doc("HS Treasury Movement", request)
        self.assertEqual((movement.counter_account, movement.concept_label), (first_account, "Concepto Loan"))

    def test_returned_rendition_can_replace_reversed_expense(self):
        category = self.petty()
        self.call("petty_fund", dict(kind="Initial Fund", shift=self.shift, method=self.cash, amount=100))
        old = self.call("petty_expense", dict(category=category.name, amount=30, beneficiary="Proveedor",
                                               concept="Importe errado", receipt_reference="REC-OLD"))["expense"]
        rendition = self.call("petty_rendition", dict(counted_cash=70))["rendition"]
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("petty_review", dict(rendition=rendition, approve=0, note="Corregir importe"))
        self.call("finance_reverse", dict(doctype="HS Petty Cash Expense", name=old, reason="Importe corregido"))
        frappe.set_user("Administrator")
        new = self.call("petty_expense", dict(category=category.name, amount=40, beneficiary="Proveedor",
                                               concept="Importe correcto", receipt_reference="REC-NEW"))["expense"]
        self.call("petty_rendition", dict(rendition=rendition, counted_cash=60))
        saved = frappe.get_doc("HS Petty Cash Rendition", rendition)
        self.assertEqual(saved.expense_total, 40)
        self.assertEqual(frappe.parse_json(saved.expenses), [new])
        frappe.set_user("manager@hospitality.example.invalid")
        self.call("petty_review", dict(rendition=rendition, approve=1))
        frappe.set_user("Administrator")
        self.assertEqual(balance(self.prop), 60)


class TestFinanceConcurrency(IntegrationTestCase):
    def test_property_lock_serializes_independent_financial_sessions(self):
        """The same row lock protecting a fund command excludes a second session."""
        frappe.set_user("Administrator")
        prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        site, sites_path = frappe.local.site, frappe.local.sites_path
        acquired = threading.Event()
        attempting = threading.Event()
        release = threading.Event()
        second_acquired = threading.Event()

        def first():
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                lock_property(prop.name, "finance")
                acquired.set()
                if not release.wait(10):
                    raise AssertionError("El segundo turno no liberó la prueba")
                frappe.db.rollback()
            finally:
                frappe.destroy()

        def second():
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                if not acquired.wait(10):
                    raise AssertionError("No se obtuvo el primer bloqueo")
                attempting.set()
                lock_property(prop.name, "finance")
                second_acquired.set()
                frappe.db.rollback()
            finally:
                frappe.destroy()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(first)
            b = pool.submit(second)
            try:
                self.assertTrue(acquired.wait(10))
                self.assertTrue(attempting.wait(10))
                self.assertFalse(second_acquired.wait(0.2))
            finally:
                release.set()
            a.result(timeout=15)
            b.result(timeout=15)
        self.assertTrue(second_acquired.is_set())
