"""Native ledger events, immutable close snapshots and operational-date attribution."""
from datetime import timedelta
from pathlib import Path
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,getdate

from hospitality_suite import api,reports
from hospitality_suite.close_financials import snapshot
from hospitality_suite.service import operation,insert


class TestCloseFinancials(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.rooms=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["name","category"],order_by="room_number")
        self.guest=frappe.get_doc("HS Guest",{"property":self.prop.name})
        self.method=frappe.get_doc("HS Payment Method",{"property":self.prop.name,"is_cash":1,"currency":"NIO"})
        self.stay=self.enter(self.rooms[0])
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def enter(self,room,days=1):
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=days)),customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        return self.call("walk_in",dict(values,acceptance=api.preview(self.prop.name,values)["acceptance"]))

    def pay(self,amount,kind="Payment",**extra):
        return self.call("payment",dict(stay=self.stay["stay"],folio=self.stay["folio"],shift=self.shift,method=extra.pop("method",self.method.name),kind=kind,amount=amount,**extra))

    def finance(self):
        self.prop.reload()
        return snapshot(self.prop,reports.summary(self.prop))

    def close_shift(self,amount):
        shift=frappe.get_doc("HS Shift",self.shift)
        return self.call("close_shift",dict(shift=shift.name,modified=str(shift.modified),denominations={"NIO":[dict(value=1,count=amount)]}))

    def test_separate_billing_cash_balances_returns_and_original_currencies(self):
        self.pay(500,"Advance")
        self.pay(200,"Guarantee")
        invoice=self.call("invoice",dict(folio=self.stay["folio"]))["invoice"]
        payment=self.pay(400)
        self.enter(self.rooms[1])
        company=frappe.get_doc("Company",self.prop.company)
        bank=frappe.get_doc(dict(doctype="Account",account_name="USD cierre "+uuid.uuid4().hex[:6],company=company.name,
                           parent_account=frappe.db.get_value("Account",{"company":company.name,"account_type":"Cash","is_group":1}),account_type="Cash",account_currency="USD")).insert()
        with operation():
            usd=frappe.get_doc(dict(doctype="HS Payment Method",property=self.prop.name,company=company.name,account=bank.name,currency="USD",mode_of_payment=self.method.mode_of_payment,is_cash=1)).insert()
        self.pay(10,"Advance",method=usd.name)
        self.pay(20,"Guarantee",method=usd.name)
        data=self.finance()
        nio=next(row for row in data["currencies"] if row["currency"]=="NIO")
        dollars=next(row for row in data["currencies"] if row["currency"]=="USD")
        self.assertEqual(nio["invoices_total"],"1500.00")
        self.assertEqual(nio["payments"],"400.00")
        self.assertEqual(nio["advances"],"500.00")
        self.assertEqual(nio["net_customer_receipts"],"1100.00")
        self.assertEqual(nio["receivables"],"600.00")
        self.assertEqual(nio["pending_charges"],"1500.00")
        self.assertEqual(nio["unallocated_advances"],"366.24")
        self.assertEqual(nio["guarantees_held"],"200.00")
        self.assertEqual(dollars["advances"],"10.00")
        self.assertEqual(dollars["guarantees"],"20.00")
        self.assertEqual(dollars["net_customer_receipts"],"30.00")
        self.assertEqual(dollars["guarantees_held"],"20.00")
        credit=self.call("credit_note",dict(invoice=invoice,reason="Devolución ficticia del cierre"))["credit_note"]
        self.pay(100,"Refund",source_payment=payment["payment"],credit_note=credit,reason="Devolución parcial ficticia")
        nio=next(row for row in self.finance()["currencies"] if row["currency"]=="NIO")
        self.assertEqual(nio["invoices_total"],"0.00")
        self.assertEqual(nio["credit_notes_total"],"1500.00")
        self.assertEqual(nio["refunds"],"100.00")
        self.assertEqual(nio["net_customer_receipts"],"1000.00")
        # ERPNext leaves the original invoice and the unapplied return separate.
        # A report must not silently reconcile them or net different customers.
        self.assertEqual(nio["receivables"],"600.00")
        self.assertEqual(nio["customer_credits"],"1400.00")
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"outstanding_amount"),600)
        self.assertEqual(frappe.db.get_value("Sales Invoice",credit,"outstanding_amount"),-1400)

    def test_review_changes_are_rejected_and_closed_snapshot_survives_later_posting(self):
        invoice=self.call("invoice",dict(folio=self.stay["folio"]))["invoice"]
        self.close_shift(0)
        first=self.call("daily_close",dict(confirm=False))
        self.assertFalse(first["blockers"])
        again=self.call("daily_close",dict(confirm=False))
        self.assertEqual(first["review_acceptance"],again["review_acceptance"])
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]
        self.pay(500)
        self.close_shift(500)
        with self.assertRaisesRegex(frappe.ValidationError,"resumen del cierre cambió"):
            self.call("daily_close",dict(confirm=True,review_acceptance=first["review_acceptance"]))
        review=self.call("daily_close",dict(confirm=False))
        key=uuid.uuid4().hex
        values=dict(confirm=True,review_acceptance=review["review_acceptance"])
        closed=self.call("daily_close",values,key)
        self.assertEqual(closed,self.call("daily_close",values,key))
        doc=frappe.get_doc("HS Daily Close",closed["close"])
        saved=doc.summary
        original=getdate(doc.business_date)
        self.assertEqual(next(row for row in frappe.parse_json(saved)["financial"]["currencies"] if row["currency"]=="NIO")["receivables"],"1000.00")
        self.shift=self.call("open_shift",dict(opening_amount=0))["shift"]
        paid=self.pay(100)
        record=frappe.get_doc("HS Payment",paid["payment"])
        self.assertEqual(getdate(record.business_date),original+timedelta(days=1))
        self.assertEqual(record.business_date_source,"Recorded")
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice,"outstanding_amount"),900)
        self.assertEqual(doc.reload().summary,saved)
        rows=api.report(self.prop.name,"Cobros",dict(date_field="business_date",from_date=str(record.business_date),to_date=str(record.business_date)))
        self.assertEqual([r.name for r in rows],[record.name])
        current=self.finance()
        nio=next(row for row in current["currencies"] if row["currency"]=="NIO")
        self.assertEqual(nio["invoices_total"],"0.00")
        self.assertEqual(nio["payments"],"100.00")
        self.assertEqual(nio["receivables"],"900.00")

    def test_backfill_uses_audit_and_never_guesses_an_orphan_date(self):
        received=self.pay(100,"Advance")
        record=frappe.get_doc("HS Payment",received["payment"])
        day=getdate(record.business_date)
        frappe.db.set_value("HS Payment",record.name,dict(business_date=None,business_date_source="Unknown"),update_modified=False)
        with operation():
            self.prop.business_date=day+timedelta(days=1)
            self.prop.save()
            # Deliberate legacy orphan fixture: there is no ledger or immutable
            # creation audit from which an operational date can be established.
            orphan=insert("HS Payment",self.prop,stay=self.stay["stay"],folio=self.stay["folio"],customer=self.guest.customer,
                          shift=self.shift,method=self.method.name,kind="Advance",amount=5,currency="NIO",status="Posted")
        frappe.db.set_value("HS Payment",orphan.name,dict(business_date=None,business_date_source="Unknown"),update_modified=False)
        from hospitality_suite.patches.v0_3.payment_business_dates import execute
        execute();execute()
        self.assertEqual(getdate(record.reload().business_date),day)
        self.assertEqual(record.business_date_source,"Audit")
        self.assertFalse(orphan.reload().business_date)
        self.assertEqual(orphan.business_date_source,"Unknown")
        data=self.finance()
        self.assertEqual([r["name"] for r in data["sources"]["unattributed_movements"]],[orphan.name])
        motel=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        other=snapshot(motel,reports.summary(motel))
        self.assertFalse(other["sources"]["movements"])
        self.assertFalse(other["sources"]["unallocated_advances"])

    def test_tax_totals_use_invoice_values_and_old_prints_remain_historical(self):
        parent=frappe.db.get_value("Account",{"company":self.prop.company,"root_type":"Liability","is_group":1})
        account=frappe.get_doc(dict(doctype="Account",company=self.prop.company,account_name="Impuesto cierre "+uuid.uuid4().hex[:6],parent_account=parent,account_type="Tax",account_currency="NIO")).insert()
        template=frappe.get_doc(dict(doctype="Sales Taxes and Charges Template",title="Impuesto cierre "+uuid.uuid4().hex[:6],company=self.prop.company,
                     taxes=[dict(charge_type="On Net Total",account_head=account.name,description="Impuesto sintético",rate=15,included_in_print_rate=1,cost_center=self.prop.cost_center)])).insert()
        with operation():
            self.prop.tax_template=template.name
            self.prop.save()
        self.call("invoice",dict(folio=self.stay["folio"]))
        nio=next(row for row in self.finance()["currencies"] if row["currency"]=="NIO")
        self.assertEqual(nio["invoices_net"],"1304.35")
        self.assertEqual(nio["invoices_tax"],"195.65")
        self.assertEqual(nio["invoices_total"],"1500.00")
        source=Path(frappe.get_app_path("hospitality_suite","templates","print","daily_close.html")).read_text()
        old=frappe._dict(name="historical",property=self.prop.name,business_date=self.prop.business_date,status="Closed",closed_at=None,summary="{}",blockers="[]",reason="")
        html=frappe.render_template(source,dict(doc=old))
        self.assertIn("Este cierre histórico no conserva el resumen financiero ampliado.",html)

    def test_native_pos_uses_posted_money_net_of_change_and_its_own_operational_date(self):
        invoice=frappe.get_doc(dict(doctype="Sales Invoice",company=self.prop.company,hs_property=self.prop.name,
                    customer=self.guest.customer,currency=self.prop.currency,debit_to=self.prop.receivable_account,
                    cost_center=self.prop.cost_center,is_pos=1,update_stock=1,account_for_change_amount=self.method.account))
        invoice.append("items",dict(item_code="HS-DEMO-WATER",qty=2,rate=30,cost_center=self.prop.cost_center,warehouse=self.prop.warehouse))
        invoice.append("payments",dict(mode_of_payment=self.method.mode_of_payment,account=self.method.account,amount=100))
        invoice.set_missing_values()
        invoice.insert().submit()
        self.assertFalse(frappe.db.exists("HS Payment",{"payment_entry":invoice.name}))
        nio=next(row for row in self.finance()["currencies"] if row["currency"]=="NIO")
        self.assertEqual(nio["pos_collections"],"60.00")
        self.assertEqual(nio["payments"],"0.00")
        self.assertEqual(nio["net_customer_receipts"],"60.00")
        original=getdate(self.prop.business_date)
        with operation():
            self.prop.business_date=original+timedelta(days=1)
            self.prop.save()
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        credit=make_sales_return(invoice.name)
        credit.hs_property=self.prop.name
        # The native mapper copies the tender (100), but a refund returns 60.
        credit.set("payments",[dict(mode_of_payment=self.method.mode_of_payment,account=self.method.account,amount=-60)])
        credit.change_amount=credit.base_change_amount=0
        credit.insert().submit()
        nio=next(row for row in self.finance()["currencies"] if row["currency"]=="NIO")
        self.assertEqual(nio["pos_collections"],"0.00")
        self.assertEqual(nio["pos_refunds"],"60.00")
        self.assertEqual(nio["net_customer_receipts"],"-60.00")
        self.assertEqual(nio["invoices_total"],"0.00","Posting date and the operational date are distinct")

    def test_foreign_invoice_balance_uses_receivable_account_currency(self):
        # Establish the party's NIO ledger currency through a normal invoice.
        self.call("invoice",dict(folio=self.stay["folio"]))
        invoice=frappe.get_doc(dict(doctype="Sales Invoice",company=self.prop.company,hs_property=self.prop.name,
                    customer=self.guest.customer,currency="USD",conversion_rate=37,debit_to=self.prop.receivable_account,
                    cost_center=self.prop.cost_center))
        invoice.append("items",dict(item_code=self.prop.lodging_item,qty=1,rate=5,cost_center=self.prop.cost_center))
        invoice.set_missing_values()
        invoice.insert().submit()
        data=self.finance()
        nio=next(row for row in data["currencies"] if row["currency"]=="NIO")
        usd=next(row for row in data["currencies"] if row["currency"]=="USD")
        self.assertEqual(invoice.party_account_currency,"NIO")
        self.assertEqual(invoice.outstanding_amount,185)
        self.assertEqual(usd["invoices_total"],"5.00")
        self.assertEqual(usd["receivables"],"0.00")
        self.assertEqual(nio["receivables"],"1685.00")
        source=next(row for row in data["sources"]["receivables"] if row["name"]==invoice.name)
        self.assertEqual((source["currency"],source["invoice_currency"]),("NIO","USD"))
