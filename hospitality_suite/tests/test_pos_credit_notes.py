"""Page credit-note commands preserve native POS cash, stock and closed shifts."""
from decimal import Decimal
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.service import operation


class TestPosCreditNotes(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.method=frappe.get_doc('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        self.shift=self.call('open_shift',dict(opening_amount=100))['shift']

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def invoice(self,currency='NIO',rate=30,conversion=1,payments=None,item='HS-DEMO-WATER',quantity=2,**extra):
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=self.prop.company,hs_property=self.prop.name,hs_shift=self.shift,
            customer=self.guest.customer,currency=currency,conversion_rate=conversion,debit_to=self.prop.receivable_account,
            cost_center=self.prop.cost_center,is_pos=1,update_stock=1,account_for_change_amount=self.method.account,disable_rounded_total=1))
        invoice.update(extra)
        invoice.append('items',dict(item_code=item,qty=quantity,rate=rate,cost_center=self.prop.cost_center,warehouse=self.prop.warehouse))
        for method,amount in (payments or [(self.method,100)]):
            invoice.append('payments',dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=amount,reference_no='Recibo POS sintético'))
        invoice.set_missing_values()
        return invoice.insert().submit()

    def values(self,invoice,**extra):return dict(invoice=invoice.name,shift=self.shift,reason='Devolución POS sintética autorizada',**extra)

    def review(self,values):return api.preview(self.prop.name,values,'credit_note')

    def credit(self,values,key=None):
        quote=self.review(values)
        return self.call('credit_note',dict(values,acceptance=quote['acceptance']),key)

    def method_for(self,currency='NIO',cash=False,reference=False):
        kind='Cash' if cash else 'Bank'
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'account_type':kind,'is_group':1})
        account=frappe.get_doc(dict(doctype='Account',company=self.prop.company,parent_account=parent,account_name='POS retorno '+uuid.uuid4().hex[:6],account_type=kind,account_currency=currency)).insert()
        mode=frappe.get_doc(dict(doctype='Mode of Payment',mode_of_payment='POS retorno '+uuid.uuid4().hex[:6],type=kind,
                                 accounts=[dict(company=self.prop.company,default_account=account.name)])).insert()
        with operation():
            return frappe.get_doc(dict(doctype='HS Payment Method',company=self.prop.company,property=self.prop.name,account=account.name,currency=currency,
                                       mode_of_payment=mode.name,is_cash=int(cash),reference_required=int(reference))).insert()

    def test_net_change_closed_original_shift_and_retry_use_one_native_return(self):
        original=self.invoice()
        before=original.as_dict()
        shift=frappe.get_doc('HS Shift',self.shift)
        self.call('close_shift',dict(shift=self.shift,modified=str(shift.modified),denominations={'NIO':[dict(value=10,count=16)]}))
        old=self.shift
        self.shift=self.call('open_shift',dict(opening_amount=100))['shift']
        values=self.values(original)
        quote=self.review(values)
        self.assertEqual(quote['pos']['payments'][0]['amount'],'60.00')
        self.assertEqual(frappe.db.count('Sales Invoice'),1)
        key=uuid.uuid4().hex
        accepted=dict(values,acceptance=quote['acceptance'])
        frappe.msgprint('Aviso previo que debe conservarse')
        before_messages=len(frappe.local.message_log)
        one=self.call('credit_note',accepted,key)
        self.assertIn('Aviso previo que debe conservarse',str(frappe.local.message_log))
        hint=frappe._('You can use {0} to reconcile against {1} later.').split('{')[0]
        self.assertNotIn(hint,str(frappe.local.message_log[before_messages:]))
        self.assertFalse(frappe.flags.mute_messages)
        self.assertEqual(one,self.call('credit_note',accepted,key))
        credit=frappe.get_doc('Sales Invoice',one['credit_note'])
        self.assertEqual((credit.is_pos,credit.update_stock,credit.change_amount,len(credit.payments)),(0,1,0,0))
        self.assertTrue(one['refund_journal'])
        self.assertEqual(expected(frappe.get_doc('HS Shift',old))['NIO'],'160.00')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'40.00')
        self.assertEqual(frappe.db.count('HS Payment'),0)
        self.assertEqual(frappe.db.count('Payment Entry'),0)
        stock=frappe.get_all('Stock Ledger Entry',filters={'voucher_type':'Sales Invoice','voucher_no':['in',[original.name,credit.name]],'is_cancelled':0},pluck='actual_qty')
        self.assertEqual(sum(stock),0)
        original.reload()
        self.assertEqual((original.paid_amount,original.change_amount,original.hs_shift),(before.paid_amount,before.change_amount,old))
        with self.assertRaises(frappe.ValidationError):self.credit(values)
        credit.hs_correction_reason='Reversión sintética del retorno POS'
        with self.assertRaises(frappe.ValidationError):credit.cancel()
        journal=frappe.get_doc('Journal Entry',one['refund_journal'])
        journal.hs_correction_reason='Reversión sintética del asiento de devolución'
        journal.cancel()
        credit.reload()
        credit.hs_correction_reason='Reversión sintética del retorno POS'
        credit.cancel()
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        self.credit(values)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'40.00')

    def test_mixed_media_partial_quantities_and_reference_preserve_the_net(self):
        bank=self.method_for(reference=True)
        original=self.invoice(payments=[(self.method,100),(bank,40)])
        values=self.values(original,items=[dict(invoice_item=original.items[0].name,quantity=1)])
        with self.assertRaises(frappe.ValidationError):self.review(values)
        values['reference']='Salida bancaria sintética'
        quote=self.review(values)
        amounts={row['account']:row['amount'] for row in quote['pos']['payments']}
        self.assertEqual(amounts,{self.method.account:'10.00',bank.account:'20.00'})
        first=self.credit(values)
        second=self.credit(self.values(original,reference=values['reference']))
        self.assertEqual((first['amount'],second['amount']),(-30,-30))
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',original.name,'outstanding_amount'),0)
        self.assertEqual(frappe.db.count('HS Payment'),0)

    def test_usd_invoice_refunds_original_usd_medium_without_new_fx_or_payment_entry(self):
        self.invoice(payments=[(self.method,60)])  # Establish the customer's NIO receivable currency.
        usd=self.method_for(currency='USD',cash=True)
        original=self.invoice(currency='USD',rate=5,conversion=37,payments=[(usd,10)],account_for_change_amount=usd.account)
        returned=self.credit(self.values(original))
        self.assertEqual(returned['pos']['payments'][0]['amount'],'10.00')
        self.assertEqual(returned['pos']['payments'][0]['currency'],'USD')
        native=frappe.get_doc('Sales Invoice',returned['credit_note'])
        self.assertEqual((native.conversion_rate,native.base_grand_total),(37,-370))
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['USD'],'0.00')
        self.assertEqual(frappe.db.count('Payment Entry'),0)

    def test_usd_invoice_with_base_currency_medium_shows_its_real_account_amount(self):
        self.invoice(payments=[(self.method,60)])
        original=self.invoice(currency='USD',rate=5,conversion=37,payments=[(self.method,10)])
        quote=self.review(self.values(original))
        self.assertEqual((quote['currency'],quote['total']),('USD','10.00'))
        self.assertEqual((quote['pos']['payments'][0]['currency'],quote['pos']['payments'][0]['amount']),('NIO','370.00'))
        returned=self.credit(self.values(original))
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'base_grand_total'),-370)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'160.00')

    def test_review_rejects_another_return_and_unauthorized_or_foreign_closed_shift(self):
        original=self.invoice()
        values=self.values(original)
        quote=self.review(values)
        part=self.values(original,items=[dict(invoice_item=original.items[0].name,quantity=1)])
        self.credit(part)
        with self.assertRaises(frappe.ValidationError):self.call('credit_note',dict(values,acceptance=quote['acceptance']))
        with self.assertRaises(frappe.ValidationError):self.call('credit_note',part)
        with self.assertRaises(frappe.ValidationError):self.review(dict(part,items=part['items']*2))
        frappe.set_user('supervisor@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.review(part)
        frappe.set_user('Administrator')
        motel=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        other=api.execute(motel.name,'open_shift',uuid.uuid4().hex,dict(opening_amount=0))['shift']
        with self.assertRaises(frappe.ValidationError):self.review(dict(part,shift=other))

    def test_partially_paid_source_returns_only_received_money_and_reverses_write_off(self):
        original=self.invoice(payments=[(self.method,30)])
        returned=self.credit(self.values(original))
        self.assertEqual(returned['pos']['refund'],'30.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',original.name,'outstanding_amount'),0)
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        # A separate source exercises the native write-off reversal.
        write_off=frappe.db.get_value('Company',self.prop.company,'write_off_account')
        self.assertTrue(write_off)
        original=self.invoice(payments=[(self.method,59)],write_off_amount=1,write_off_account=write_off,write_off_cost_center=self.prop.cost_center)
        returned=self.credit(self.values(original))
        native=frappe.get_doc('Sales Invoice',returned['credit_note'])
        journal=frappe.get_doc('Journal Entry',returned['refund_journal'])
        self.assertEqual(sum(row.credit_in_account_currency for row in journal.accounts if row.account==write_off),1)
        self.assertEqual(returned['pos']['refund'],'59.00')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')

    def test_foreign_partial_returns_absorb_account_rounding_on_the_last_quantity(self):
        self.invoice(payments=[(self.method,60)])
        item=frappe.get_doc(dict(doctype='Item',item_code='POS redondeo '+uuid.uuid4().hex[:6],item_name='Servicio por hora',
                                 item_group='All Item Groups',stock_uom='Hour',is_stock_item=0,is_sales_item=1)).insert()
        original=self.invoice(currency='USD',rate=.01,conversion=36.624,quantity=3,item=item.name,payments=[(self.method,.03)])
        delivered=[]
        for _ in range(3):
            returned=self.credit(self.values(original,items=[dict(invoice_item=original.items[0].name,quantity=1)]))
            delivered.append(returned['pos']['payments'][0]['amount'])
        self.assertEqual(delivered,['0.37','0.37','0.36'])
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'160.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',original.name,'outstanding_amount'),0)

    def test_mixed_receipt_with_cash_change_from_other_medium_reverses_both_native_legs(self):
        bank=self.method_for()
        original=self.invoice(payments=[(self.method,40),(bank,100)])
        returned=self.credit(self.values(original))
        amounts={row['account']:row['amount'] for row in returned['pos']['payments']}
        self.assertEqual(amounts,{self.method.account:'-40.00',bank.account:'100.00'})
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')

    def test_preexisting_unpaid_credit_is_not_swept_into_the_next_refund(self):
        original=self.invoice()
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        from hospitality_suite.accounting import post_standard
        old=make_sales_return(original.name)
        old.update(dict(is_pos=0,update_outstanding_for_self=1))
        old.set('payments',[])
        old.items[0].qty=-1
        post_standard(old,self.prop)
        returned=self.credit(self.values(original))
        self.assertEqual(returned['pos']['payments'][0]['amount'],'30.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',old.name,'outstanding_amount'),-30)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'130.00')

    def test_last_quantity_uses_cash_residue_without_changing_native_credit_amount(self):
        item=frappe.get_doc(dict(doctype='Item',item_code='POS precio '+uuid.uuid4().hex[:6],item_name='Servicio por hora',
                                 item_group='All Item Groups',stock_uom='Hour',is_stock_item=0,is_sales_item=1)).insert()
        original=self.invoice(rate=15.005,quantity=2,item=item.name,payments=[(self.method,30.01)])
        returned=[]
        for _ in range(2):
            returned.append(self.credit(self.values(original,items=[dict(invoice_item=original.items[0].name,quantity=1)])))
        self.assertEqual([row['pos']['payments'][0]['amount'] for row in returned],['15.01','15.00'])
        self.assertEqual([row['amount'] for row in returned],[-15.01,-15.01])
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        self.assertTrue(all(frappe.db.get_value('Sales Invoice',row['credit_note'],'outstanding_amount')==0 for row in returned))

    def test_fx_change_requires_new_review_and_posts_native_difference(self):
        self.invoice(payments=[(self.method,60)])
        usd=self.method_for(currency='USD',cash=True)
        original=self.invoice(currency='USD',rate=5,conversion=37,payments=[(usd,10)],account_for_change_amount=usd.account)
        values=self.values(original)
        with patch('hospitality_suite.accounting.exchange',return_value=Decimal(37)):
            quote=self.review(values)
        with patch('hospitality_suite.accounting.exchange',return_value=Decimal(38)):
            with self.assertRaises(frappe.ValidationError):self.call('credit_note',dict(values,acceptance=quote['acceptance']))
            returned=self.credit(values)
        native=frappe.get_doc('Journal Entry',returned['refund_journal'])
        loss=frappe.db.get_value('Company',self.prop.company,'exchange_gain_loss_account')
        self.assertEqual(sum(row.debit-row.credit for row in native.accounts if row.account==loss),10)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['USD'],'0.00')

    def test_native_rounded_total_is_the_party_liquidation_not_the_unrounded_grand_total(self):
        original=self.invoice(rate=60.15,quantity=1,payments=[(self.method,60)],disable_rounded_total=0)
        self.assertEqual((original.grand_total,original.rounded_total),(60.15,60))
        quote=self.review(self.values(original))
        self.assertEqual((quote['total'],quote['pos']['party_amount'],quote['rounding_adjustment']),('60.00','60.00','-0.15'))
        returned=self.credit(self.values(original))
        self.assertEqual(returned['amount'],-60.15)
        self.assertEqual(returned['pos']['payments'][0]['amount'],'60.00')
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(frappe.db.get_value('Sales Invoice',original.name,'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')

    def receipt(self,allocations,method=None,amount=None,conversion=1):
        method=method or self.method
        total=sum(value for _,value in allocations)
        invoice=allocations[0][0]
        entry=frappe.get_doc(dict(doctype='Payment Entry',company=self.prop.company,hs_property=self.prop.name,hs_shift=self.shift,
            payment_type='Receive',posting_date=invoice.posting_date,party_type='Customer',party=self.guest.customer,
            paid_from=self.prop.receivable_account,paid_to=method.account,paid_amount=total,received_amount=amount or total,
            source_exchange_rate=1,target_exchange_rate=conversion,mode_of_payment=method.mode_of_payment,
            reference_no='Otro recibo nativo sintético',reference_date=invoice.posting_date,cost_center=self.prop.cost_center))
        for inv,value in allocations:
            entry.append('references',dict(reference_doctype='Sales Invoice',reference_name=inv.name,allocated_amount=value))
        entry.insert().submit()
        source=frappe.get_doc('HS Payment',{'payment_entry':entry.name})
        return entry,source

    def refund(self,source,credit,amount,method=None,key=None,**extra):
        values=dict(kind='Refund',source_payment=source.name,credit_note=credit,amount=amount,method=(method or self.method).name,
                    shift=self.shift,reason='Devuelve el recibo adicional de origen',**extra)
        quote=api.preview(self.prop.name,values,'payment')
        self.last_refund=dict(values,fx_acceptance=quote['acceptance'])
        return self.call('payment',self.last_refund,key)

    def test_additional_native_receipt_returns_its_own_funds_without_fake_exchange_income(self):
        original=self.invoice(payments=[(self.method,30)])
        entry,source=self.receipt([(original,30)])
        before=entry.as_dict()
        self.assertEqual(frappe.db.get_value('Sales Invoice',original.name,'outstanding_amount'),0)
        returned=self.credit(self.values(original))
        self.assertEqual((returned['pos']['party_amount'],returned['pos']['remaining_credit'],returned['pos']['exchange_difference']),('30.00','30.00','0.00'))
        self.assertEqual(returned['pos']['additional_sources'][0]['source'],source.name)
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),-30)
        key=uuid.uuid4().hex
        one=self.refund(source,returned['credit_note'],30,key=key)
        # The stored intention retries without requiring a now-spent quote.
        self.assertEqual(one,self.call('payment',self.last_refund,key))
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        entry.reload()
        self.assertEqual((entry.paid_amount,entry.received_amount,entry.hs_shift,entry.docstatus),(before.paid_amount,before.received_amount,before.hs_shift,1))
        self.assertEqual([(r.reference_name,r.allocated_amount) for r in entry.references],[(original.name,30)])
        loss=frappe.db.get_value('Company',self.prop.company,'exchange_gain_loss_account')
        self.assertFalse(frappe.db.exists('GL Entry',{'voucher_type':'Journal Entry','voucher_no':returned['refund_journal'],'account':loss,'is_cancelled':0}))
        with self.assertRaises(frappe.ValidationError):self.refund(source,returned['credit_note'],1)

    def test_repeated_partial_returns_keep_additional_receipts_out_of_pos_cash_budget(self):
        original=self.invoice(payments=[(self.method,30)])
        entry,source=self.receipt([(original,30)])
        values=self.values(original,items=[dict(invoice_item=original.items[0].name,quantity=1)])
        for _ in range(2):
            returned=self.credit(values)
            self.assertEqual((returned['pos']['payments'][0]['amount'],returned['pos']['remaining_credit']),('15.00','15.00'))
            self.refund(source,returned['credit_note'],15)
            self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        self.assertEqual(frappe.db.count('HS Payment',{'source_payment':source.name,'status':'Posted'}),2)

    def test_pos_funded_only_by_another_receipt_creates_no_empty_journal(self):
        original=self.invoice(payments=[(self.method,0)])
        entry,source=self.receipt([(original,60)])
        returned=self.credit(self.values(original))
        self.assertIsNone(returned['refund_journal'])
        self.assertEqual((returned['pos']['party_amount'],returned['pos']['remaining_credit']),('0.00','60.00'))
        self.refund(source,returned['credit_note'],60)
        self.assertEqual(frappe.db.count('Journal Entry'),0)
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')

    def test_foreign_receipt_shared_between_invoices_settles_exact_book_limits(self):
        original=self.invoice(quantity=1,rate=130,payments=[(self.method,30)])
        other=self.invoice(quantity=1,rate=266.24,payments=[(self.method,0)],is_pos=0)
        usd=self.method_for(currency='USD',cash=True)
        entry,source=self.receipt([(original,100),(other,266.24)],usd,10,36.624)
        first=self.credit(self.values(original))
        self.assertEqual(first['pos']['remaining_credit'],'100.00')
        with patch('hospitality_suite.accounting.exchange',side_effect=lambda currency,*args:Decimal('36.624') if currency=='USD' else Decimal(1)):
            one=self.refund(source,first['credit_note'],2.73,usd)
            self.assertEqual(frappe.db.get_value('Payment Entry',one['payment_entry'],'received_amount'),100)
            second=self.credit(self.values(other))
            two=self.refund(source,second['credit_note'],7.27,usd)
            self.assertEqual(frappe.db.get_value('Payment Entry',two['payment_entry'],'received_amount'),266.24)
        self.assertTrue(all(frappe.db.get_value('Sales Invoice',row['credit_note'],'outstanding_amount')==0 for row in (first,second)))
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift)),{'NIO':'100.00','USD':'0.00'})

    def test_inconsistent_native_foreign_change_rolls_back_and_legacy_receipt_is_not_refunded(self):
        self.invoice(payments=[(self.method,60)])
        usd=self.method_for(currency='USD',cash=True)
        settings=frappe.get_single('POS Settings')
        settings.post_change_gl_entries=0
        settings.save()
        values=dict(currency='USD',rate=5,conversion=37,payments=[(usd,12)],account_for_change_amount=usd.account)
        frappe.db.savepoint('pos_foreign_change')
        with self.assertRaises(frappe.ValidationError):self.invoice(**values)
        frappe.db.rollback(save_point='pos_foreign_change')
        self.assertEqual(frappe.db.count('Sales Invoice'),1)
        # Reproduce a pre-upgrade receipt through ERPNext, bypassing only the
        # new app check in this fixture; never write a ledger row directly.
        with patch('hospitality_suite.native_pos.validate_posted',return_value=None):
            legacy=self.invoice(**values)
        from hospitality_suite.pos_returns import ledger
        native=ledger([legacy.name],{usd.account})[(usd.account,'USD')]
        self.assertEqual((native['amount'],native['base']),(Decimal(12),Decimal(370)))
        with self.assertRaises(frappe.ValidationError):self.credit(self.values(legacy))
        self.assertEqual(frappe.db.count('Journal Entry'),0)
