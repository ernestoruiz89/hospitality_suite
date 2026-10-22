"""Native accounting contracts and visit/shift reconciliation, without ledger writes."""
from datetime import timedelta
import io
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.cashier import expected
from hospitality_suite.service import operation


class TestFinancialAudit(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','category'],order_by='room_number')
        self.cash=frappe.get_doc('HS Payment Method',{'property':self.prop.name,'is_cash':1,'currency':'NIO'})
        self.shift=self.call('open_shift',dict(opening_amount=0))['shift']

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def values(self,rooms=None,prop=None):
        prop=prop or self.prop
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        selected=rooms or [self.rooms[0]]
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(hours=3 if prop.mode=='Por tiempo' else 24)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(room=room.name,category=room.category,people=1) for room in selected])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        return values

    def stay(self,index=0):
        return self.call('walk_in',self.values([self.rooms[index]]))

    def pay(self,stay,amount,kind='Payment',**extra):
        values=dict(stay=stay['stay'],folio=stay['folio'],shift=self.shift,method=self.cash.name,amount=amount,kind=kind)
        values.update(extra)
        return self.call('payment',values)

    def report(self,**filters):
        return api.report(self.prop.name,'Conciliación',filters)

    def test_visit_reconciliation_includes_advances_guarantees_credit_and_refunds_without_other_visits(self):
        own,other=self.stay(),self.stay(1)
        advance=self.pay(own,500,'Advance')
        guarantee=self.pay(own,200,'Guarantee')
        invoice=self.call('invoice',dict(folio=own['folio']))['invoice']
        paid=self.pay(own,300)
        foreign=self.pay(other,700,'Advance')
        credit=self.call('credit_note',dict(invoice=invoice,reason='Devolución sintética de auditoría'))['credit_note']
        refunded=self.pay(own,200,'Refund',source_payment=paid['payment'],credit_note=credit,reason='Devolución parcial sintética')
        returned=self.pay(own,100,'Guarantee Refund',source_payment=guarantee['payment'],reason='Garantía parcial sintética')
        applied=self.call('apply_guarantee',dict(source_payment=guarantee['payment'],folio=own['folio'],amount=100,reason='Aplicación sintética del remanente'))
        rows=self.report(stay=own['stay'])
        payments=[row for row in rows if row['type']=='Payment']
        self.assertEqual({row['source'] for row in payments},{result['payment'] for result in (advance,guarantee,paid,refunded,returned,applied)})
        self.assertNotIn(foreign['payment_entry'],{row['erp_document'] for row in rows})
        self.assertEqual({row['erp_document'] for row in rows if row['type']=='Charge'},{invoice,credit})
        self.assertTrue(all(row['status']=='OK' for row in rows))
        page=api.report_page(self.prop.name,'Conciliación',dict(stay=own['stay']))
        self.assertIn('Anticipo',{row['_display'].get('type') for row in page['rows']})
        self.assertIn('Garantía',{row['_display'].get('type') for row in page['rows']})

    def test_shift_reconciliation_includes_invoices_referenced_by_its_payments(self):
        own,other=self.stay(),self.stay(1)
        paid=self.pay(own,100)
        invoice=frappe.get_doc('Payment Entry',paid['payment_entry']).references[0].reference_name
        unrelated=self.call('invoice',dict(folio=other['folio']))['invoice']
        self.assertFalse(frappe.db.get_value('Sales Invoice',invoice,'hs_shift'))
        rows=self.report(shift=self.shift)
        self.assertIn(invoice,{row['erp_document'] for row in rows if row['type']=='Charge'})
        self.assertNotIn(unrelated,{row['erp_document'] for row in rows})
        shift=frappe.get_doc('HS Shift',self.shift)
        self.call('close_shift',dict(shift=shift.name,modified=str(shift.modified),denominations={'NIO':[dict(value=100,count=1)]}))
        self.assertTrue(any(row['type']=='Closed shift' for row in self.report(shift=self.shift)))
        combined=self.report(stay=own['stay'],shift=self.shift)
        self.assertTrue(any(row['type']=='Charge' for row in combined))
        self.assertFalse(any(row['type']=='Closed shift' for row in combined))

    def test_shared_group_documents_are_complete_for_each_stay_and_export_has_a_readable_filter(self):
        unrelated=self.stay(2)
        excluded=self.pay(unrelated,10,'Advance')
        booking=self.call('reserve',self.values(self.rooms[:2]))
        first=self.call('check_in',dict(booking=booking['booking'],modified=booking['modified'],guest=self.guest.name))
        current=frappe.get_doc('HS Booking',booking['booking'])
        second=self.call('check_in',dict(booking=current.name,modified=str(current.modified),guest=self.guest.name))
        folio=self.call('create_folio',dict(stay=first['stay'],customer=self.guest.customer,group=1,label='Cuenta grupal de auditoría'))['folio']
        for name in frappe.get_all('HS Charge',filters={'stay':['in',[first['stay'],second['stay']]]},pluck='name'):
            self.call('move_charge',dict(charge=name,folio=folio,reason='Consolidación sintética'))
        self.call('payment',dict(booking=booking['booking'],folio=folio,shift=self.shift,method=self.cash.name,amount=500,kind='Advance'))
        invoice=self.call('invoice',dict(folio=folio))['invoice']
        self.call('payment',dict(booking=booking['booking'],folio=folio,shift=self.shift,method=self.cash.name,amount=200,kind='Payment'))
        a,b=self.report(stay=first['stay']),self.report(stay=second['stay'])
        self.assertEqual({row['source'] for row in a},{row['source'] for row in b})
        self.assertEqual(sum(float(row['expected']) for row in a if row['type']=='Charge'),3000)
        self.assertEqual({row['erp_document'] for row in a if row['type']=='Charge'},{invoice})
        self.assertNotIn(excluded['payment_entry'],{row['erp_document'] for row in a})
        self.assertTrue(all(row['status']=='OK' for row in a))
        api.export_report(self.prop.name,'Conciliación',dict(stay=first['stay']),file_format='xlsx')
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(frappe.local.response.filecontent),read_only=True)
        try:
            text=' '.join(str(cell.value or '') for row in book.active for cell in row)
            self.assertNotIn(first['stay'],text)
        finally:
            book.close()
        from hospitality_suite.report_queries import describe_filters
        selected_room=frappe.db.get_value('HS Stay',first['stay'],'room')
        number=frappe.db.get_value('HS Room',selected_room,'room_number')
        self.assertIn('Habitación '+number,describe_filters([self.prop],'Conciliación',dict(stay=first['stay'])))

    def test_reconciliation_options_and_filters_are_scoped_and_company_selection_narrows_to_the_visit(self):
        own=self.stay()
        self.call('invoice',dict(folio=own['folio']))
        other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        room=frappe.get_doc('HS Room',{'property':other.name})
        visit=api.execute(other.name,'walk_in',uuid.uuid4().hex,self.values([room],other))
        api.execute(other.name,'invoice',uuid.uuid4().hex,dict(folio=visit['folio']))
        foreign_shift=api.execute(other.name,'open_shift',uuid.uuid4().hex,dict(opening_amount=0))['shift']
        options=api.report_options(self.prop.name,'Conciliación')
        self.assertIn('stay',options['filters'])
        self.assertEqual({row['name'] for row in options['stays']},{own['stay']})
        self.assertIn('H101',options['stays'][0]['label'])
        self.assertNotIn(own['stay'],options['stays'][0]['label'])
        with self.assertRaises(frappe.PermissionError):self.report(stay=visit['stay'])
        with self.assertRaises(frappe.PermissionError):self.report(stay='nonexistent-visit')
        with self.assertRaises(frappe.PermissionError):self.report(shift=foreign_shift)
        with self.assertRaises(frappe.ValidationError):self.report(stay=['in',own['stay']])
        rows=api.report('','Conciliación',dict(company=self.prop.company,stay=visit['stay']))
        self.assertTrue(rows)
        self.assertEqual({row['property'] for row in rows},{other.name})
        self.assertEqual(api.report('','Conciliación',dict(company=self.prop.company,stay=own['stay'],shift=foreign_shift)),[])
        user='finance-audit-'+uuid.uuid4().hex[:8]+'@example.invalid'
        frappe.get_doc(dict(doctype='User',email=user,first_name='Contabilidad sintética',send_welcome_email=0,user_type='System User',roles=[dict(role='HS Accountant')])).insert()
        with operation():frappe.get_doc(dict(doctype='HS Access',user=user,property=self.prop.name,company=self.prop.company)).insert()
        frappe.set_user(user)
        self.assertEqual({row['name'] for row in api.report_options(self.prop.name,'Conciliación')['stays']},{own['stay']})
        with self.assertRaises(frappe.PermissionError):api.report('','Conciliación',dict(company=self.prop.company,stay=visit['stay']))

    def test_configured_bank_methods_require_reference_and_combine_with_partial_cash(self):
        own=self.stay()
        self.pay(own,350)
        parent=frappe.db.get_value('Account',{'company':self.prop.company,'root_type':'Asset','is_group':1},'name')
        for label,amount in [('Tarjeta',500),('Transferencia',400),('Otro medio',250)]:
            name=label+' auditoría '+uuid.uuid4().hex[:7]
            bank=frappe.get_doc(dict(doctype='Account',account_name=name,company=self.prop.company,parent_account=parent,account_type='Bank',account_currency='NIO')).insert()
            mode=frappe.get_doc(dict(doctype='Mode of Payment',mode_of_payment=name,type='Bank',accounts=[dict(company=self.prop.company,default_account=bank.name)])).insert()
            with operation():
                method=frappe.get_doc(dict(doctype='HS Payment Method',property=self.prop.name,company=self.prop.company,account=bank.name,mode_of_payment=mode.name,
                                           currency='NIO',is_cash=0,reference_required=1)).insert()
            before={dt:frappe.db.count(dt) for dt in ('HS Payment','Sales Invoice','Payment Entry','Journal Entry')}
            with self.assertRaises(frappe.ValidationError):self.pay(own,amount,method=method.name)
            with self.assertRaises(frappe.ValidationError):self.pay(own,amount,method=method.name,reference='REF',tendered=amount+10)
            self.assertEqual(before,{dt:frappe.db.count(dt) for dt in before})
            paid=self.pay(own,amount,method=method.name,reference='REF-'+name)
            native=frappe.get_doc('Payment Entry',paid['payment_entry'])
            row=frappe.get_doc('HS Payment',paid['payment'])
            self.assertEqual((native.reference_no,row.reference),('REF-'+name,'REF-'+name))
            self.assertEqual((row.currency,row.shift,row.exchange_rate),('NIO',self.shift,1))
        self.assertEqual(api.stay_detail(own['stay'])['folios'][0]['balance']['outstanding'],'0.00')
        self.assertEqual(expected(frappe.get_doc('HS Shift',self.shift))['NIO'],'350.00')

    def test_advance_does_not_post_income_and_never_pays_another_visit_of_the_same_customer(self):
        own,other=self.stay(),self.stay(1)
        advance=self.pay(own,500,'Advance')
        self.assertEqual(frappe.db.count('Sales Invoice'),0)
        ledger=frappe.get_all('GL Entry',filters={'voucher_type':'Payment Entry','voucher_no':advance['payment_entry'],'is_cancelled':0},fields=['account'])
        self.assertTrue(ledger)
        self.assertFalse(any(frappe.db.get_value('Account',row.account,'root_type')=='Income' for row in ledger))
        other_invoice=self.call('invoice',dict(folio=other['folio']))['invoice']
        self.assertEqual(frappe.db.get_value('Sales Invoice',other_invoice,'total_advance'),0)
        self.assertEqual(frappe.db.get_value('Payment Entry',advance['payment_entry'],'unallocated_amount'),500)
        own_invoice=self.call('invoice',dict(folio=own['folio']))['invoice']
        self.assertEqual(frappe.db.get_value('Sales Invoice',own_invoice,'total_advance'),500)
        self.assertEqual(frappe.db.get_value('Sales Invoice',own_invoice,'outstanding_amount'),1000)

    def test_closed_shift_rejects_new_money_and_preserves_original_count_after_authorized_reversal(self):
        own=self.stay()
        paid=self.pay(own,1500)
        shift=frappe.get_doc('HS Shift',self.shift)
        self.call('close_shift',dict(shift=shift.name,modified=str(shift.modified),denominations={'NIO':[dict(value=100,count=15)]}))
        shift.reload();frozen=shift.denominations
        before=frappe.db.count('HS Payment')
        with self.assertRaises(frappe.ValidationError):self.pay(own,10,'Advance')
        self.assertEqual(frappe.db.count('HS Payment'),before)
        native=frappe.get_doc('Payment Entry',paid['payment_entry'])
        with self.assertRaises(frappe.ValidationError):native.cancel()
        native.reload()
        native.hs_correction_reason='Corrección nativa sintética tras el arqueo'
        native.cancel()
        shift.reload()
        self.assertEqual(shift.denominations,frozen)
        self.assertEqual(shift.counted_amount,1500)
        self.assertEqual(frappe.db.get_value('HS Payment',paid['payment'],'status'),'Cancelled')
        changed=next(row for row in self.report(shift=self.shift) if row['type']=='Closed shift')
        self.assertEqual((changed['expected'],changed['actual'],changed['difference']),('1500.00','0.00','-1500.00'))
        events=frappe.get_all('HS Audit Event',filters={'property':self.prop.name,'action':'on_cancel'},fields=['reason','details','actor'])
        self.assertTrue(any(event.reason and event.actor=='Administrator' and json.loads(event.details)['name']==native.name for event in events))

    def test_untracked_native_cash_respects_the_selected_visit_and_local_dates(self):
        own,other=self.stay(),self.stay(1)
        names=[]
        for stay in (own,other):
            native=frappe.get_doc(dict(doctype='Journal Entry',company=self.prop.company,posting_date=frappe.utils.nowdate(),
                hs_property=self.prop.name,hs_stay=stay['stay'],hs_folio=stay['folio'],hs_shift=self.shift,
                accounts=[dict(account=self.cash.account,debit_in_account_currency=50),
                          dict(account=self.prop.guarantee_account,credit_in_account_currency=50)])).insert()
            native.submit();names.append(native.name)
        selected=self.report(stay=own['stay'],shift=self.shift)
        self.assertEqual({row['erp_document'] for row in selected if row['type']=='Untracked payment'},{names[0]})
        self.assertTrue(all(row['status']=='Difference' for row in selected))
        self.assertEqual(self.report(stay=own['stay'],from_date='2099-01-01'),[])
