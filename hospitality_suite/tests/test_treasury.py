from datetime import timedelta
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation


class TestTreasury(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.cash=frappe.db.get_value("HS Payment Method",{"property":self.prop.name,"is_cash":1})
        room=frappe.get_doc("HS Room",{"property":self.prop.name})
        guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=guest.customer,guest=guest.name,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        self.stay=self.call("walk_in",values)
        self.shift=self.call("open_shift",dict(opening_amount=500))["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def account(self,label,root="Asset",account_type=None,currency=None):
        parent=frappe.db.get_value("Account",{"company":self.prop.company,"root_type":root,"is_group":1},"name")
        return frappe.get_doc(dict(doctype="Account",company=self.prop.company,parent_account=parent,account_name=label+uuid.uuid4().hex[:7],
                                   account_currency=currency or self.prop.currency,account_type=account_type)).insert().name

    def card(self,fee=3,fixed=2,withheld=1,currency=None):
        clearing=self.account("Compensación ficticia ",account_type="Bank",currency=currency)
        bank=self.account("Banco neto ficticio ",account_type="Bank",currency=currency)
        expense=self.account("Comisión ficticia ",root="Expense")
        tax=self.account("Retención ficticia ")
        with operation():
            method=frappe.get_doc(dict(doctype="HS Payment Method",property=self.prop.name,company=self.prop.company,
                                       mode_of_payment="Efectivo demo",is_cash=0,account=clearing,currency=currency or self.prop.currency,
                                       fee_percent=fee,fee_fixed=fixed,fee_account=expense,withholding_percent=withheld,
                                       withholding_account=tax,settlement_account=bank)).insert()
        return method,clearing,bank,expense,tax

    def receipt(self,method,amount):
        return self.call("payment",dict(stay=self.stay["stay"],folio=self.stay["folio"],shift=self.shift,method=method.name,amount=amount,
                                        kind="Advance",reference="Cobro ficticio de tarjeta"))

    def settle(self,payment,amount,key=None):
        values=dict(source_payment=payment,amount=amount,shift=self.shift,reference="Abono bancario ficticio")
        values["acceptance"]=api.preview(self.prop.name,values,"settle_payment")["acceptance"]
        return self.call("settle_payment",values,key)

    def test_cash_expense_native_cost_limit_retry_and_expected_drawer(self):
        account=self.account("Gasto operativo ficticio ",root="Expense")
        with operation():
            category=frappe.get_doc(dict(doctype="HS Expense Category",company=self.prop.company,property=self.prop.name,
                                         label="Reposición menor ficticia",account=account,max_amount=100,active=1)).insert()
        values=dict(shift=self.shift,method=self.cash,category=category.name,amount=80,reason="Egreso ficticio documentado")
        key=uuid.uuid4().hex
        frappe.set_user("cashier@hospitality.example.invalid")
        # A cashier cannot spend another user's drawer.
        with self.assertRaises(frappe.PermissionError):
            self.call("cash_expense",values,key)
        frappe.set_user("Administrator")
        result=self.call("cash_expense",values,key)
        self.assertEqual(self.call("cash_expense",values,key),result)
        from hospitality_suite.cashier import expected
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift))["NIO"],"420.00")
        journal=frappe.get_doc("Journal Entry",result["journal_entry"])
        self.assertEqual(sum(r.debit for r in journal.accounts if r.account==account),80)
        with self.assertRaises(frappe.ValidationError):
            self.call("cash_expense",dict(values,amount=120))
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])

    def test_react_cash_expense_review_and_shared_category_setup(self):
        account=self.account("Gasto React ficticio ",root="Expense")
        with operation():
            category=frappe.get_doc(dict(doctype="HS Expense Category",company=self.prop.company,
                property=self.prop.name,label="Gasto React ficticio",account=account,
                max_amount=100,active=1)).insert()
        values=dict(shift=self.shift,method=self.cash,category=category.name,
                    amount=80,reason="Comprobante de gasto ficticio")
        snapshot=api.erp_cash_snapshot(self.prop.name,self.shift)
        self.assertTrue(any(row.name==category.name for row in snapshot["categories"]))
        self.assertEqual(snapshot["selected"]["expected"]["NIO"],"500.00")
        quote=api.preview(self.prop.name,values,"cash_expense_reviewed")
        self.assertEqual((quote["debit"],quote["credit"],quote["available_after"]),
                         (account,frappe.db.get_value("HS Payment Method",self.cash,"account"),"420.00"))
        with self.assertRaises(frappe.ValidationError):
            self.call("cash_expense_reviewed",values)
        key=uuid.uuid4().hex
        result=self.call("cash_expense_reviewed",dict(values,acceptance=quote["acceptance"]),key)
        self.assertEqual(self.call("cash_expense_reviewed",dict(values,acceptance=quote["acceptance"]),key),result)
        journal=frappe.get_doc("Journal Entry",result["journal_entry"])
        self.assertEqual(journal.docstatus,1)
        self.assertEqual(sum(row.debit for row in journal.accounts if row.account==account),80)
        with self.assertRaises(frappe.ValidationError):
            self.call("cash_expense_reviewed",dict(values,acceptance=quote["acceptance"]))

        settings=api.erp_cash_settings(self.prop.name)
        row=next(row for row in settings["categories"] if row.name==category.name)
        updated=api.save_setup(self.prop.name,"expense_category",
            dict(name=category.name,label="Gasto React actualizado",account=account,
                 max_amount=90,active=1),uuid.uuid4().hex,expected_modified=str(row.modified))
        self.assertEqual(updated["name"],category.name)
        self.assertEqual(next(row.label for row in api.erp_cash_settings(self.prop.name)["categories"]
                              if row.name==category.name),"Gasto React actualizado")
        with self.assertRaises(frappe.ValidationError):
            api.save_setup(self.prop.name,"expense_category",
                dict(name=category.name,label="Cambio con versión antigua",account=account,
                     max_amount=90,active=1),uuid.uuid4().hex,expected_modified=str(row.modified))

    def test_react_payment_method_setup_creates_usable_settlement_policy(self):
        clearing=self.account("Compensación React ficticia ",account_type="Bank")
        bank=self.account("Banco React ficticio ",account_type="Bank")
        expense=self.account("Comisión React ficticia ",root="Expense")
        tax=self.account("Retención React ficticia ")
        mode=frappe.db.get_value("Mode of Payment",{"type":"Bank"},"name")
        result=api.save_setup(self.prop.name,"payment_method",dict(
            mode_of_payment=mode,account=clearing,currency=self.prop.currency,
            is_cash=0,reference_required=1,fee_percent=3,fee_fixed=2,
            fee_account=expense,withholding_percent=1,withholding_account=tax,
            settlement_account=bank,refund_fee_percent=0,refund_fee_fixed=0),
            uuid.uuid4().hex)
        settings=api.erp_cash_method_settings(self.prop.name)
        created=next(row for row in settings["methods"] if row.name==result["name"])
        self.assertEqual((created.settlement_account,created.core_locked),(bank,False))
        receipt=self.receipt(frappe.get_doc("HS Payment Method",result["name"]),100)
        quote=api.preview(self.prop.name,dict(source_payment=receipt["payment"],amount=100),"settle_payment")
        self.assertEqual((quote["fee"],quote["withholding"],quote["net"]),("5.00","1.00","94.00"))
        self.assertTrue(next(row for row in api.erp_cash_method_settings(self.prop.name)["methods"]
                             if row.name==result["name"]).core_locked)
        with self.assertRaises(frappe.ValidationError):
            api.save_setup(self.prop.name,"payment_method",
                dict(name=result["name"],account=bank),uuid.uuid4().hex,
                expected_modified=str(created.modified))

    def test_partial_card_settlement_preserves_gross_policy_and_all_native_ledgers(self):
        method,clearing,bank,expense,tax=self.card()
        receipt=self.receipt(method,100)
        sources=api.erp_cash_settlement_sources(self.prop.name,receipt["payment"])
        self.assertEqual(len(sources["sources"]),1)
        self.assertEqual((sources["sources"][0]["available"],sources["sources"][0]["direction"]),
                         ("100.00","Receive"))
        one=self.settle(receipt["payment"],40)
        self.assertEqual((one["fee"],one["withholding"],one["net"]),("2.00","0.40","37.60"))
        sources=api.erp_cash_settlement_sources(self.prop.name,receipt["payment"])
        self.assertEqual((sources["sources"][0]["settled"],sources["sources"][0]["available"]),
                         ("40.00","60.00"))
        settings=api.erp_cash_method_settings(self.prop.name)
        configured=next(row for row in settings["methods"] if row.name==method.name)
        self.assertTrue(configured.core_locked)
        api.save_setup(self.prop.name,"payment_method",
            dict(name=method.name,fee_percent=50,fee_fixed=0,withholding_percent=0),
            uuid.uuid4().hex,expected_modified=str(configured.modified))
        two=self.settle(receipt["payment"],60)
        self.assertEqual((two["fee"],two["withholding"],two["net"]),("3.00","0.60","56.40"))
        self.assertEqual(api.erp_cash_settlement_sources(self.prop.name,receipt["payment"])["sources"],[])
        vouchers=[receipt["payment_entry"],one["journal_entry"],two["journal_entry"]]
        rows=frappe.get_all("GL Entry",filters={"voucher_no":["in",vouchers],"is_cancelled":0},fields=["account","debit","credit"])
        balance=lambda account:sum(r.debit-r.credit for r in rows if r.account==account)
        self.assertEqual(balance(clearing),0)
        self.assertEqual(balance(bank),94)
        self.assertEqual(balance(expense),5)
        self.assertEqual(balance(tax),1)
        self.assertEqual(frappe.db.get_value("Payment Entry",receipt["payment_entry"],"received_amount"),100)
        self.assertEqual(frappe.db.count("Sales Invoice",{"hs_stay":self.stay["stay"]}),0)
        from hospitality_suite.cashier import expected
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift))["NIO"],"500.00")
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])
        native=frappe.get_doc("Payment Entry",receipt["payment_entry"])
        native.hs_correction_reason="No debe anularse con liquidación vigente"
        with self.assertRaises(frappe.ValidationError):
            native.cancel()
        last=frappe.get_doc("Journal Entry",two["journal_entry"])
        last.hs_correction_reason="Liquidación ficticia duplicada corregida"
        last.cancel()
        reopened=api.erp_cash_settlement_sources(self.prop.name,receipt["payment"])["sources"]
        self.assertEqual((len(reopened),reopened[0]["available"]),(1,"60.00"))
        q=api.preview(self.prop.name,dict(source_payment=receipt["payment"],amount=60),"settle_payment")
        self.assertEqual(q["fee"],"3.00")
        self.assertEqual(q["net"],"56.40")
        with operation():
            corrupted=frappe.get_doc("HS Payment",one["payment"])
            corrupted.net_amount=1
            corrupted.save()
        self.assertTrue(any(r["type"]=="Settlement net" for r in differences(self.prop)))

    def test_final_partial_settlement_absorbs_rounding_and_cannot_over_settle(self):
        method,*_=self.card(fee=0,fixed=.01,withheld=0)
        receipt=self.receipt(method,1)
        values=[self.settle(receipt["payment"],amount) for amount in (.33,.33,.34)]
        self.assertEqual([r["fee"] for r in values],["0.00","0.00","0.01"])
        self.assertEqual([r["net"] for r in values],["0.33","0.33","0.33"])
        with self.assertRaises(frappe.ValidationError):
            self.settle(receipt["payment"],.01)

    def test_cash_method_cannot_apply_card_fee(self):
        method=frappe.get_doc("HS Payment Method",self.cash)
        method.fee_percent=3
        with self.assertRaises(frappe.ValidationError):
            method.save()

    def test_usd_settlement_clears_historical_base_and_posts_exchange_gain(self):
        from decimal import Decimal
        from unittest.mock import patch
        method,clearing,bank,expense,tax=self.card(currency="USD")
        receipt=self.receipt(method,10)
        with patch("hospitality_suite.treasury.exchange",side_effect=lambda source,target,*args: Decimal(37) if source=="USD" else Decimal(1)):
            result=self.settle(receipt["payment"],10)
        vouchers=[receipt["payment_entry"],result["journal_entry"]]
        entries=frappe.get_all("GL Entry",filters={"voucher_no":["in",vouchers],"is_cancelled":0},fields=["account","debit","credit","debit_in_account_currency","credit_in_account_currency"])
        self.assertAlmostEqual(sum(r.debit-r.credit for r in entries if r.account==clearing),0,places=2)
        self.assertAlmostEqual(sum(r.debit_in_account_currency-r.credit_in_account_currency for r in entries if r.account==clearing),0,places=2)
        gain=frappe.db.get_value("Company",self.prop.company,"exchange_gain_loss_account")
        self.assertAlmostEqual(sum(r.credit-r.debit for r in entries if r.account==gain),3.76,places=2)
        self.assertAlmostEqual(sum(r.debit-r.credit for r in entries if r.account==bank),281.2,places=2)

    def test_card_refund_settlement_is_outgoing_without_duplicating_receipts(self):
        method,clearing,bank,*_=self.card()
        receipt=self.receipt(method,100)
        incoming=self.settle(receipt["payment"],100)
        refund=self.call("payment",dict(stay=self.stay["stay"],folio=self.stay["folio"],shift=self.shift,method=method.name,
                                        kind="Refund",amount=20,source_payment=receipt["payment"],reason="Devolución parcial ficticia"))
        returned=self.settle(refund["payment"],20)
        self.assertEqual(returned["net"],"20.00")
        record=frappe.get_doc("HS Payment",returned["payment"])
        self.assertEqual(record.settlement_direction,"Pay")
        vouchers=[receipt["payment_entry"],refund["payment_entry"] or refund["journal_entry"],incoming["journal_entry"],returned["journal_entry"]]
        entries=frappe.get_all("GL Entry",filters={"voucher_no":["in",vouchers],"is_cancelled":0},fields=["account","debit","credit"])
        self.assertEqual(sum(r.debit-r.credit for r in entries if r.account==clearing),0)
        self.assertEqual(sum(r.debit-r.credit for r in entries if r.account==bank),74)
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])
