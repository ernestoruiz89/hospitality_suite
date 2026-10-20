"""Native original allocations bound applied-advance refunds and their FX value."""
from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.service import operation


class TestAppliedRefunds(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.method=frappe.get_doc('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        self.stay=self.call('walk_in',dict(values,acceptance=api.preview(self.prop.name,values)['acceptance']))
        self.shift=self.call('open_shift',dict(opening_amount=0))['shift']

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def pay(self,amount,kind='Advance',**extra):
        values=dict(stay=self.stay['stay'],folio=self.stay['folio'],shift=self.shift,method=self.method.name,amount=amount,kind=kind)
        return self.call('payment',dict(values,**extra))

    def refund_values(self,source,credit,amount,**extra):
        return dict(kind='Refund',source_payment=source['payment'],credit_note=credit,amount=amount,method=self.method.name,
                    shift=self.shift,reason='Devolución sintética autorizada',**extra)

    def credit(self,invoice,**extra):
        return self.call('credit_note',dict(invoice=invoice,reason='Nota de crédito sintética',**extra))['credit_note']

    def usd_method(self):
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'account_type':'Cash','is_group':1})
        cash=frappe.get_doc(dict(doctype='Account',company=self.prop.company,parent_account=parent,account_name='USD anticipo devolución '+uuid.uuid4().hex[:6],account_type='Cash',account_currency='USD')).insert()
        with operation():
            return frappe.get_doc(dict(doctype='HS Payment Method',property=self.prop.name,company=self.prop.company,account=cash.name,currency='USD',mode_of_payment=self.method.mode_of_payment,is_cash=1)).insert()

    def test_applied_advance_refund_retries_and_rejects_stale_review_on_new_shift(self):
        source=self.pay(1500)
        invoice=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        original=frappe.get_doc('Payment Entry',source['payment_entry'])
        before=original.as_dict()
        credit=self.credit(invoice)
        shift=frappe.get_doc('HS Shift',self.shift)
        old_shift=self.shift
        self.call('close_shift',dict(shift=self.shift,modified=str(shift.modified),denominations={'NIO':[dict(value=100,count=15)]}))
        self.shift=self.call('open_shift',dict(opening_amount=1500))['shift']
        values=self.refund_values(source,credit,750)
        quote=api.preview(self.prop.name,values,'payment')
        self.assertEqual(quote['refund']['mode'],'Applied Advance')
        key=uuid.uuid4().hex
        accepted=dict(values,fx_acceptance=quote['acceptance'])
        one=self.call('payment',accepted,key)
        self.assertEqual(one,self.call('payment',accepted,key))
        with self.assertRaises(frappe.ValidationError):
            self.call('payment',accepted)
        latest=api.preview(self.prop.name,values,'payment')
        self.call('payment',dict(values,fx_acceptance=latest['acceptance']))
        self.assertEqual(frappe.db.get_value('Sales Invoice',credit,'outstanding_amount'),0)
        original.reload()
        self.assertEqual((original.paid_amount,original.received_amount,original.hs_shift,original.unallocated_amount),(before['paid_amount'],before['received_amount'],old_shift,0))
        self.assertEqual([(r.reference_name,r.allocated_amount) for r in original.references],[(invoice,1500)])
        self.assertEqual(expected(frappe.get_doc('HS Shift',old_shift))['NIO'],'1500.00')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'0.00')
        self.assertEqual(frappe.db.count('HS Payment',{'source_payment':source['payment'],'kind':'Refund'}),2)
        self.assertEqual(frappe.db.get_value('HS Payment',one['payment'],'sales_invoice'),credit)
        returned=frappe.get_doc('Payment Entry',one['payment_entry'])
        returned.hs_correction_reason='Reversión autorizada del reembolso sintético'
        returned.cancel()
        self.assertEqual(frappe.db.get_value('HS Payment',one['payment'],'status'),'Cancelled')
        self.call('payment',values)
        self.assertEqual(frappe.db.get_value('Sales Invoice',credit,'outstanding_amount'),0)
        self.assertEqual(frappe.db.count('HS Payment',{'source_payment':source['payment'],'kind':'Refund','status':'Posted'}),2)

    def test_refund_is_bounded_by_each_original_invoice_allocation(self):
        source=self.pay(2000)
        first=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        stay=frappe.get_doc('HS Stay',self.stay['stay'])
        extend=dict(stay=stay.name,folio=self.stay['folio'],ends_at=str(stay.ends_at+timedelta(days=1)),modified=str(stay.modified))
        quote=api.preview(self.prop.name,extend,'extend')
        self.call('extend',dict(extend,acceptance=quote['acceptance']))
        second=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        native=frappe.get_doc('Payment Entry',source['payment_entry'])
        allocated={r.reference_name:r.allocated_amount for r in native.references}
        self.assertEqual(allocated,{first:1500,second:500})
        credit=self.credit(second)
        with self.assertRaises(frappe.ValidationError):
            self.call('payment',self.refund_values(source,credit,600))
        self.call('payment',self.refund_values(source,credit,500))
        with self.assertRaises(frappe.ValidationError):
            self.call('payment',self.refund_values(source,credit,1))
        self.assertEqual(frappe.db.get_value('Sales Invoice',credit,'outstanding_amount'),-1000)
        self.assertEqual(frappe.db.count('HS Payment',{'source_payment':source['payment']}),1)

    def test_unallocated_remainder_and_credit_limit_share_the_same_original_funds(self):
        item=frappe.get_doc('Item',self.prop.lodging_item)
        item.stock_uom='Hour'  # A fractional return uses a native fraction-capable UOM.
        item.save()
        source=self.pay(2000)
        invoice=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        item=frappe.get_doc('Sales Invoice',invoice).items[0]
        credit=self.credit(invoice,items=[dict(invoice_item=item.name,quantity=.25)])
        with self.assertRaises(frappe.ValidationError):
            self.call('payment',self.refund_values(source,credit,400))
        self.call('payment',self.refund_values(source,credit,375))
        self.pay(500,'Refund',source_payment=source['payment'],reason='Devuelve solo la parte no aplicada')
        remaining=self.credit(invoice)
        self.call('payment',self.refund_values(source,remaining,1125))
        self.assertEqual(frappe.db.get_value('Payment Entry',source['payment_entry'],'unallocated_amount'),0)
        with self.assertRaises(frappe.ValidationError):
            self.pay(1,'Refund',source_payment=source['payment'],reason='No quedan fondos')

    def test_usd_applied_refund_settles_historic_value_and_native_exchange_loss(self):
        with operation():
            self.prop.exchange_gain_loss_account=frappe.db.get_value('Company',self.prop.company,'exchange_gain_loss_account')
            self.prop.save()
        method=self.usd_method()
        source=self.pay(10,method=method.name)
        invoice=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        credit=self.credit(invoice)
        values=self.refund_values(source,credit,10)
        values['method']=method.name
        with patch('hospitality_suite.accounting.exchange',side_effect=lambda source,target,*args:Decimal(37) if source=='USD' else Decimal(1)):
            quote=api.preview(self.prop.name,values,'payment')
            self.assertEqual(quote['refund']['party_amount'],'366.24')
            self.assertEqual(quote['refund']['exchange_difference'],'3.76')
            returned=self.call('payment',dict(values,fx_acceptance=quote['acceptance']))
        native=frappe.get_doc('Payment Entry',returned['payment_entry'])
        self.assertEqual(native.references[0].allocated_amount,-366.24)
        self.assertEqual(native.difference_amount,0)
        self.assertEqual(native.received_amount,366.24)
        loss=frappe.db.get_value('Company',self.prop.company,'exchange_gain_loss_account')
        ledger=frappe.get_all('GL Entry',filters={'voucher_type':'Payment Entry','voucher_no':native.name,'account':loss},fields=['debit','credit'])
        self.assertAlmostEqual(sum(row.debit-row.credit for row in ledger),3.76,places=2)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['USD'],'0.00')

    def test_unallocated_usd_refund_and_approval_respect_original_value(self):
        method=self.usd_method()
        source=self.pay(10,method=method.name)
        values=self.refund_values(source,None,10)
        values['method']=method.name
        frappe.set_user('cashier@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):
            api.preview(self.prop.name,values,'payment')
        frappe.set_user('Administrator')
        with patch('hospitality_suite.accounting.exchange',side_effect=lambda source,target,*args:Decimal(37) if source=='USD' else Decimal(1)):
            quote=api.preview(self.prop.name,values,'payment')
            self.assertEqual(quote['refund']['mode'],'Unallocated Advance')
            returned=self.call('payment',dict(values,fx_acceptance=quote['acceptance']))
        native=frappe.get_doc('Journal Entry',returned['journal_entry'])
        party=next(row for row in native.accounts if row.party_type=='Customer')
        self.assertEqual(party.debit_in_account_currency,366.24)
        self.assertEqual(frappe.db.get_value('Payment Entry',source['payment_entry'],'unallocated_amount'),0)
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['USD'],'0.00')

    def test_last_partial_refund_absorbs_native_currency_rounding(self):
        method=self.usd_method()
        source=self.pay(.03,method=method.name)
        invoice=self.call('invoice',dict(folio=self.stay['folio']))['invoice']
        credit=self.credit(invoice)
        amounts=[]
        for _ in range(3):
            values=self.refund_values(source,credit,.01)
            values['method']=method.name
            result=self.call('payment',values)
            amounts.append(frappe.db.get_value('Payment Entry',result['payment_entry'],'received_amount'))
        self.assertEqual(amounts,[.37,.37,.36])
        self.assertEqual(sum(Decimal(str(value)) for value in amounts),Decimal('1.10'))
