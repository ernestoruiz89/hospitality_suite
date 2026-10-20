"""Applied guarantees are native customer credits, independent of the liability."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.close_financials import snapshot
from hospitality_suite.refunds import original_funds
from hospitality_suite.service import operation


class TestGuaranteeRefunds(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        room=frappe.get_doc('HS Room',{'property':self.prop.name})
        guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.method=frappe.get_doc('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
        self.stay=self.call('walk_in',dict(values,acceptance=api.preview(self.prop.name,values)['acceptance']))
        self.shift=self.call('open_shift',dict(opening_amount=0))['shift']

    def tearDown(self):
        frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def pay(self,amount,kind='Guarantee',**extra):
        return self.call('payment',dict(stay=self.stay['stay'],folio=self.stay['folio'],shift=self.shift,method=extra.pop('method',self.method.name),amount=amount,kind=kind,**extra))

    def apply(self,source,amount):
        return self.call('apply_guarantee',dict(source_payment=source['payment'],folio=self.stay['folio'],amount=amount,reason='Aplicación sintética autorizada'))

    def invoice(self):return self.call('invoice',dict(folio=self.stay['folio']))['invoice']

    def credit(self,invoice):return self.call('credit_note',dict(invoice=invoice,reason='Nota sintética para devolución'))['credit_note']

    def refund(self,source,amount,credit=None,**extra):
        return self.pay(amount,'Refund',source_payment=source['payment'],credit_note=credit,reason='Devuelve fondos aplicados sin reabrir el pasivo',**extra)

    def test_return_after_invoice_preserves_application_and_remaining_liability(self):
        received=self.pay(300)
        applied=self.apply(received,200)
        invoice=self.invoice()
        credit=self.credit(invoice)
        result=self.refund(applied,200,credit)
        self.assertTrue(result['payment_entry'])
        native=frappe.get_doc('Journal Entry',applied['journal_entry'])
        self.assertEqual(native.docstatus,1)
        self.assertEqual(sum(row.credit_in_account_currency for row in native.accounts if row.reference_type=='Sales Invoice' and row.reference_name==invoice),200)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'100.00')
        with self.assertRaises(frappe.ValidationError):self.refund(applied,1,credit)
        with self.assertRaises(frappe.ValidationError):self.pay(101,'Guarantee Refund',source_payment=received['payment'],reason='Solo quedan cien de garantía')
        self.pay(100,'Guarantee Refund',source_payment=received['payment'],reason='Devuelve la garantía sin aplicar')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'0.00')
        entries=frappe.get_all('GL Entry',filters={'account':self.prop.guarantee_account,'is_cancelled':0},fields=['debit','credit'])
        self.assertEqual(sum(Decimal(str(row.debit))-Decimal(str(row.credit)) for row in entries),0)

    def test_pos_credit_returns_cash_and_applied_guarantee_from_separate_origins(self):
        stay=frappe.get_doc('HS Stay',self.stay['stay'])
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=self.prop.company,hs_property=self.prop.name,
            hs_stay=stay.name,hs_folio=self.stay['folio'],hs_shift=self.shift,customer=stay.customer,currency='NIO',
            debit_to=self.prop.receivable_account,cost_center=self.prop.cost_center,is_pos=1,update_stock=1,disable_rounded_total=1))
        invoice.append('items',dict(item_code='HS-DEMO-WATER',qty=2,rate=30,cost_center=self.prop.cost_center,warehouse=self.prop.warehouse))
        invoice.append('payments',dict(mode_of_payment=self.method.mode_of_payment,account=self.method.account,amount=30))
        invoice.set_missing_values();invoice.insert().submit()
        received=self.pay(30)
        applied=self.apply(received,30)
        values=dict(invoice=invoice.name,shift=self.shift,reason='Devuelve cobro POS y garantía aplicada')
        quote=api.preview(self.prop.name,values,'credit_note')
        self.assertEqual(quote['pos']['additional_sources'][0]['kind'],'Guarantee Applied')
        returned=self.call('credit_note',dict(values,acceptance=quote['acceptance']))
        self.assertEqual((returned['pos']['refund'],returned['pos']['remaining_credit']),('30.00','30.00'))
        self.refund(applied,30,returned['credit_note'])
        self.assertEqual(frappe.db.get_value('Sales Invoice',returned['credit_note'],'outstanding_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'0.00')
        entries=frappe.get_all('GL Entry',filters={'account':self.prop.guarantee_account,'is_cancelled':0},fields=['debit','credit'])
        self.assertEqual(sum(Decimal(str(row.debit))-Decimal(str(row.credit)) for row in entries),0)
        self.assertFalse(frappe.db.exists('HS Payment',{'kind':'Guarantee Refund'}))

    def test_partial_unallocated_return_then_invoice_uses_only_remaining_native_credit(self):
        received=self.pay(300)
        applied=self.apply(received,300)
        returned=self.refund(applied,100)
        self.assertTrue(returned['journal_entry'])
        source=frappe.get_doc('HS Payment',applied['payment'])
        self.assertEqual(original_funds(self.prop,source).unallocated,200)
        totals={row['currency']:row for row in snapshot(self.prop,{})['currencies']}
        self.assertEqual(totals['NIO']['unallocated_advances'],'200.00')
        self.assertEqual(totals['NIO']['guarantees_held'],'0.00')
        invoice=self.invoice()
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'total_advance'),200)
        self.refund(applied,200,self.credit(invoice))
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'0.00')

    def test_existing_invoice_usd_return_has_native_exchange_difference_and_requires_approval(self):
        invoice=self.invoice()
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'account_type':'Cash','is_group':1})
        cash=frappe.get_doc(dict(doctype='Account',company=self.prop.company,parent_account=parent,account_name='USD garantía aplicada '+uuid.uuid4().hex[:6],account_type='Cash',account_currency='USD')).insert()
        with operation():method=frappe.get_doc(dict(doctype='HS Payment Method',company=self.prop.company,property=self.prop.name,account=cash.name,currency='USD',mode_of_payment=self.method.mode_of_payment,is_cash=1)).insert()
        received=self.pay(10,method=method.name)
        applied=self.apply(received,10)
        credit=self.credit(invoice)
        frappe.set_user('supervisor@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):self.refund(applied,10,credit,method=method.name)
        frappe.set_user('Administrator')
        with patch('hospitality_suite.accounting.exchange',side_effect=lambda source,target,*args:Decimal(37) if source=='USD' else Decimal(1)):
            returned=self.refund(applied,10,credit,method=method.name)
        native=frappe.get_doc('Payment Entry',returned['payment_entry'])
        self.assertEqual(native.received_amount,366.24)
        self.assertEqual(native.difference_amount,0)
        loss=frappe.db.get_value('Company',self.prop.company,'exchange_gain_loss_account')
        entries=frappe.get_all('GL Entry',filters={'voucher_type':'Payment Entry','voucher_no':native.name,'account':loss},fields=['debit','credit'])
        self.assertAlmostEqual(sum(row.debit-row.credit for row in entries),3.76,places=2)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['USD'],'0.00')

    def test_unallocated_return_reconciles_closed_original_shift_without_new_receipt(self):
        applied=self.apply(self.pay(200),200)
        old=self.shift
        shift=frappe.get_doc('HS Shift',old)
        self.call('close_shift',dict(shift=old,modified=str(shift.modified),denominations={'NIO':[dict(value=100,count=2)]}))
        self.shift=self.call('open_shift',dict(opening_amount=200))['shift']
        values=dict(stay=self.stay['stay'],folio=self.stay['folio'],shift=self.shift,method=self.method.name,amount=50,kind='Refund',source_payment=applied['payment'],reason='Devolución en turno posterior')
        key=uuid.uuid4().hex
        result=self.call('payment',values,key)
        self.assertEqual(result,self.call('payment',values,key))
        self.assertEqual(expected(frappe.get_doc('HS Shift',old))['NIO'],'200.00')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'150.00')
        self.assertEqual(frappe.db.get_value('Journal Entry',applied['journal_entry'],'hs_shift'),old)
