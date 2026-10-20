"""Native POS receipts, change, currencies and corrections in the shift count."""
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.close_financials import snapshot
from hospitality_suite.native_pos import movements
from hospitality_suite.reconciliation import rows,unmatched_cash
from hospitality_suite.service import operation


class TestNativePos(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        self.method=frappe.get_doc("HS Payment Method",{"property":self.prop.name,"is_cash":1,"currency":"NIO"})
        self.shift=self.call("open_shift",dict(opening_amount=100))["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def invoice(self,method=None,currency="NIO",rate=30,tendered=100,**extra):
        method=method or self.method
        invoice=frappe.get_doc(dict(doctype="Sales Invoice",company=self.prop.company,hs_property=self.prop.name,hs_shift=self.shift,
                  customer=self.guest.customer,currency=currency,conversion_rate=37 if currency=="USD" else 1,debit_to=self.prop.receivable_account,
                  cost_center=self.prop.cost_center,is_pos=1,update_stock=1,account_for_change_amount=method.account,disable_rounded_total=1))
        invoice.update(extra)
        invoice.append("items",dict(item_code="HS-DEMO-WATER",qty=2,rate=rate,cost_center=self.prop.cost_center,warehouse=self.prop.warehouse))
        invoice.append("payments",dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=tendered))
        invoice.set_missing_values()
        return invoice

    def credit(self,invoice,shift):
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        credit=make_sales_return(invoice.name)
        credit.update(dict(hs_property=self.prop.name,hs_shift=shift,change_amount=0,base_change_amount=0))
        credit.set("payments",[dict(mode_of_payment=self.method.mode_of_payment,account=self.method.account,amount=-60)])
        return credit

    def test_change_refund_and_correction_preserve_closed_count(self):
        invoice=self.invoice().insert().submit()
        original=frappe.get_doc("HS Shift",self.shift)
        self.assertEqual(expected(original),{"NIO":"160.00"})
        self.assertEqual(frappe.db.count("HS Payment"),0)
        self.assertEqual(frappe.db.count("Payment Entry"),0)
        self.assertEqual(movements(self.prop.name)[0]["amount"],60)
        self.assertEqual(len(api.bootstrap(self.prop.name)["native_pos"]),1)
        printed=frappe.get_print("HS Shift",original.name,print_format="HS Arqueo")
        self.assertIn(invoice.name,printed)
        self.assertIn("Movimientos POS vigentes",printed)
        self.assertFalse(unmatched_cash(self.prop))
        self.call("close_shift",dict(shift=self.shift,modified=str(original.modified),denominations={"NIO":[dict(value=10,count=16)]}))
        with self.assertRaises(frappe.ValidationError):
            self.credit(invoice,self.shift).insert()
        next_shift=self.call("open_shift",dict(opening_amount=100))["shift"]
        credit=self.credit(invoice,next_shift).insert().submit()
        self.assertEqual(expected(frappe.get_doc("HS Shift",next_shift))["NIO"],"40.00")
        self.assertEqual(expected(original)["NIO"],"160.00")
        credit.hs_correction_reason="Reversión nativa sintética del reembolso"
        credit.cancel()
        self.assertEqual(expected(frappe.get_doc("HS Shift",next_shift))["NIO"],"100.00")
        invoice.reload()
        invoice.hs_correction_reason="Corrección autorizada después del arqueo sintético"
        invoice.cancel()
        original.reload()
        self.assertEqual(frappe.parse_json(original.denominations)["expected"]["NIO"],"160.00")
        difference=next(row for row in rows(self.prop) if row["type"]=="Closed shift")
        self.assertEqual(difference["difference"],"-60.00")

    def test_native_posting_requires_own_open_shift_and_bank_reference(self):
        with self.assertRaises(frappe.ValidationError):
            self.invoice(hs_shift=None).insert()
        motel=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        other=api.execute(motel.name,"open_shift",uuid.uuid4().hex,dict(opening_amount=0))["shift"]
        with self.assertRaises(frappe.ValidationError):
            self.invoice(hs_shift=other).insert()
        invoice=self.invoice()
        invoice.flags.ignore_permissions=True  # Exercise the integration hook, not an added native create grant.
        frappe.set_user("cashier@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            invoice.insert()
        frappe.set_user("Administrator")
        with operation():
            self.method.reference_required=1
            self.method.save()
        with self.assertRaises(frappe.ValidationError):
            self.invoice(tendered=60).insert()
        accepted=self.invoice(tendered=60)
        accepted.payments[0].reference_no="POS-REFERENCE-SYNTHETIC"
        accepted.insert().submit()
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift))["NIO"],"160.00")

    def test_foreign_cash_and_non_cash_keep_native_currencies_separate(self):
        cash_parent=frappe.db.get_value("Account",{"company":self.prop.company,"account_type":"Cash","is_group":1})
        cash=frappe.get_doc(dict(doctype="Account",company=self.prop.company,parent_account=cash_parent,account_name="USD POS prueba "+uuid.uuid4().hex[:6],account_type="Cash",account_currency="USD")).insert()
        bank_parent=frappe.db.get_value("Account",{"company":self.prop.company,"account_type":"Bank","is_group":1})
        bank=frappe.get_doc(dict(doctype="Account",company=self.prop.company,parent_account=bank_parent,account_name="Banco POS prueba "+uuid.uuid4().hex[:6],account_type="Bank",account_currency="NIO")).insert()
        mode=frappe.get_doc(dict(doctype="Mode of Payment",mode_of_payment="Banco POS "+uuid.uuid4().hex[:6],type="Bank",
                                accounts=[dict(company=self.prop.company,default_account=bank.name)])).insert()
        usd_mode=frappe.get_doc(dict(doctype="Mode of Payment",mode_of_payment="USD POS "+uuid.uuid4().hex[:6],type="Cash",
                                    accounts=[dict(company=self.prop.company,default_account=cash.name)])).insert()
        with operation():
            usd=frappe.get_doc(dict(doctype="HS Payment Method",property=self.prop.name,company=self.prop.company,mode_of_payment=usd_mode.name,account=cash.name,currency="USD",is_cash=1)).insert()
            non_cash=frappe.get_doc(dict(doctype="HS Payment Method",property=self.prop.name,company=self.prop.company,mode_of_payment=mode.name,account=bank.name,currency="NIO",is_cash=0)).insert()
        # Establish the party's NIO receivable currency before the USD invoice.
        self.invoice(method=non_cash,tendered=60).insert().submit()
        self.invoice(method=usd,currency="USD",rate=5,tendered=10).insert().submit()
        self.assertEqual(expected(frappe.get_doc("HS Shift",self.shift)),{"NIO":"100.00","USD":"10.00"})
        totals={row["currency"]:row for row in snapshot(self.prop,{})["currencies"]}
        self.assertEqual(totals["NIO"]["pos_collections"],"60.00")
        self.assertEqual(totals["USD"]["pos_collections"],"10.00")
        self.assertFalse(unmatched_cash(self.prop,self.shift))
        self.assertEqual(frappe.db.count("HS Payment"),0)

    def test_used_method_and_unassigned_legacy_receipt_remain_auditable(self):
        invoice=self.invoice().insert().submit()
        with operation():
            self.method.is_cash=0
            with self.assertRaises(frappe.ValidationError):
                self.method.save()
        self.method.reload()
        with operation():
            with self.assertRaises(frappe.ValidationError):
                frappe.get_doc(dict(doctype="HS Payment Method",property=self.prop.name,company=self.prop.company,
                                   mode_of_payment=self.method.mode_of_payment,account=self.method.account,currency="NIO",is_cash=0)).insert()
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("HS Payment Method",self.method.name)
        # Reproduce a pre-upgrade native receipt without a shift; test rolls back.
        frappe.db.set_value("Sales Invoice",invoice.name,"hs_shift",None,update_modified=False)
        missing=unmatched_cash(self.prop)
        self.assertEqual(len(missing),1)
        self.assertEqual((missing[0]["name"],missing[0]["amount"]),(invoice.name,60))
        difference=next(row for row in rows(self.prop) if row["type"]=="Untracked payment")
        self.assertEqual(difference["difference"],"60.00")

    def test_supervisor_can_approve_count_difference_without_adjusting_money(self):
        frappe.set_user("cashier@hospitality.example.invalid")
        shift=self.call("open_shift",dict(opening_amount=100))["shift"]
        frappe.set_user("Administrator")
        self.invoice(hs_shift=shift).insert().submit()
        frappe.set_user("cashier@hospitality.example.invalid")
        counted=dict(shift=shift,denominations={"NIO":[dict(value=10,count=15)]},reason="Faltante sintético de diez")
        result=self.call("close_shift",dict(counted,modified=str(frappe.get_doc("HS Shift",shift).modified)))
        self.assertEqual(result["status"],"Review")
        with self.assertRaises(frappe.PermissionError):
            self.call("close_shift",dict(counted,approve=True,modified=str(frappe.get_doc("HS Shift",shift).modified)))
        frappe.set_user("supervisor@hospitality.example.invalid")
        self.call("close_shift",dict(counted,approve=True,modified=str(frappe.get_doc("HS Shift",shift).modified)))
        closed=frappe.get_doc("HS Shift",shift)
        self.assertEqual((closed.status,closed.expected_amount,closed.counted_amount,closed.difference),("Closed",160,150,-10))
        self.assertEqual(closed.approved_by,"supervisor@hospitality.example.invalid")
        self.assertEqual(frappe.db.count("Journal Entry"),0)
        self.assertEqual(frappe.db.count("HS Payment"),0)
        self.assertEqual(expected(closed)["NIO"],"160.00")

    def test_standard_format_refreshes_by_content_and_preserves_site_options(self):
        from hospitality_suite.install import sync_print_formats
        frappe.db.set_value('Print Format','HS Arqueo',dict(html='old app format',modified='2099-01-01 00:00:00',disabled=1),update_modified=False)
        sync_print_formats()
        current=frappe.get_doc('Print Format','HS Arqueo')
        self.assertIn('hs_shift_pos',current.html)
        self.assertEqual(current.disabled,1)
        modified=current.modified
        sync_print_formats()
        self.assertEqual(frappe.get_doc('Print Format','HS Arqueo').modified,modified)
        frappe.db.set_value('Print Format','HS Arqueo',dict(standard='No',html='site-owned custom format'),update_modified=False)
        sync_print_formats()
        self.assertEqual(frappe.get_doc('Print Format','HS Arqueo').html,'site-owned custom format')
