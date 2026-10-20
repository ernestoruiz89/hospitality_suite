"""Prepare native original receipts; all returns and closure happen in the Page."""
import argparse
import json
import os
from pathlib import Path
import uuid

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
FIXTURE=BENCH/'.hospitality-mixed-ux-fixture.json'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','inspect'])
args=parser.parse_args()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
    frappe.set_user('Administrator')
    from hospitality_suite import api
    from hospitality_suite.cashier import expected
    from hospitality_suite.pos_returns import linked_vouchers,ledger
    if args.action=='prepare':
        assert (BENCH/'.hospitality-mixed-ux-baseline.json').is_file()
        assert all(frappe.db.count(dt)==0 for dt in ('HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'))
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        method=frappe.get_doc('HS Payment Method',{'property':prop.name,'is_cash':1,'currency':'NIO'})
        def call(action,data):return api.execute(prop.name,action,uuid.uuid4().hex,data)
        old=call('open_shift',dict(opening_amount=100))['shift']
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=prop.company,hs_property=prop.name,hs_shift=old,
            customer=guest.customer,currency='NIO',debit_to=prop.receivable_account,cost_center=prop.cost_center,
            is_pos=1,update_stock=1,account_for_change_amount=method.account,disable_rounded_total=1))
        invoice.append('items',dict(item_code='HS-DEMO-WATER',qty=2,rate=30,cost_center=prop.cost_center,warehouse=prop.warehouse))
        invoice.append('payments',dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=30))
        invoice.set_missing_values();invoice.insert().submit()
        entry=frappe.get_doc(dict(doctype='Payment Entry',company=prop.company,hs_property=prop.name,hs_shift=old,
            payment_type='Receive',posting_date=invoice.posting_date,party_type='Customer',party=guest.customer,
            paid_from=prop.receivable_account,paid_to=method.account,paid_amount=30,received_amount=30,
            source_exchange_rate=1,target_exchange_rate=1,mode_of_payment=method.mode_of_payment,
            reference_no='Segundo recibo sintético UX',reference_date=invoice.posting_date,cost_center=prop.cost_center))
        entry.append('references',dict(reference_doctype='Sales Invoice',reference_name=invoice.name,allocated_amount=30))
        entry.insert().submit()
        source=frappe.get_doc('HS Payment',{'payment_entry':entry.name})
        call('close_shift',dict(shift=old,modified=str(frappe.get_doc('HS Shift',old).modified),denominations={'NIO':[dict(value=10,count=16)]}))
        new=call('open_shift',dict(opening_amount=160))['shift']
        FIXTURE.write_text(json.dumps(dict(property=prop.name,original_shift=old,shift=new,invoice=invoice.name,
            method=method.name,account=method.account,receipt=entry.name,source=source.name)))
        FIXTURE.chmod(0o600);frappe.db.commit()
        print('Venta sintética 60: POS 30 y recibo adicional 30. Original cerrado 160, nuevo fondo 160; sin notas ni devoluciones preparadas.')
    else:
        fixture=json.loads(FIXTURE.read_text())
        original=frappe.get_doc('Sales Invoice',fixture['invoice'])
        entry=frappe.get_doc('Payment Entry',fixture['receipt'])
        old=frappe.get_doc('HS Shift',fixture['original_shift'])
        shift=frappe.get_doc('HS Shift',fixture['shift'])
        credits=frappe.get_all('Sales Invoice',filters={'return_against':original.name,'docstatus':1},fields=['name','grand_total','outstanding_amount','is_pos','update_stock','owner'])
        assert len(credits)==1 and credits[0].grand_total==-60 and credits[0].outstanding_amount==0 and not credits[0].is_pos and credits[0].update_stock
        vouchers=linked_vouchers(fixture['property'],[row.name for row in credits])
        assert len(vouchers['Journal Entry'])==len(vouchers['Payment Entry'])==1
        assert original.docstatus==1 and original.paid_amount==30 and original.change_amount==0 and original.hs_shift==old.name
        assert entry.docstatus==1 and entry.paid_amount==entry.received_amount==30 and entry.hs_shift==old.name
        assert [(row.reference_name,row.allocated_amount) for row in entry.references]==[(original.name,30)]
        assert old.status=='Closed' and old.expected_amount==old.counted_amount==160 and expected(old)=={'NIO':'160.00'}
        assert shift.status=='Closed' and shift.expected_amount==shift.counted_amount==100 and expected(shift)=={'NIO':'100.00'}
        assert frappe.db.count('HS Payment')==frappe.db.count('Payment Entry')==2
        refund=frappe.get_doc('HS Payment',{'source_payment':fixture['source'],'kind':'Refund','status':'Posted'})
        assert refund.amount==30 and refund.sales_invoice==credits[0].name and refund.payment_entry==vouchers['Payment Entry'][0]
        for dt in ('Journal Entry','Payment Entry'):
            assert ledger(vouchers[dt],{fixture['account']},dt)[(fixture['account'],'NIO')]['amount']==-30
        stock=frappe.get_all('Stock Ledger Entry',filters={'voucher_type':'Sales Invoice','voucher_no':['in',[original.name,credits[0].name]],'is_cancelled':0},pluck='actual_qty')
        assert sum(stock)==0
        events=frappe.get_all('HS Audit Event',filters={'property':fixture['property'],'action':['in',['Credit note','Refund']]},fields=['action','actor','details'])
        assert len(events)==2 and all(row.actor=='manager@hospitality.example.invalid' for row in events)
        review=json.loads(next(row.details for row in events if row.action=='Credit note'))['review']['pos']
        assert review['remaining_credit']=='30.00' and review['party_amount']=='30.00' and review['exchange_difference']=='0.00'
        from hospitality_suite.close_financials import snapshot
        prop=frappe.get_doc('HS Property',fixture['property'])
        financial=snapshot(prop,{})
        nio=next(row for row in financial['currencies'] if row['currency']=='NIO')
        assert nio['pos_collections']==nio['pos_refunds']=='30.00'
        assert len([row for row in financial['sources']['native_pos'] if row['doctype']=='Journal Entry'])==1
        assert not any(row['doctype']=='Payment Entry' for row in financial['sources']['native_pos'])
        from hospitality_suite.reconciliation import unmatched_cash
        assert not unmatched_cash(prop)
        proof=dict(site=SITE,synthetic=True,fixture_origin='ERPNext Sales Invoice / Payment Entry controllers and application shift API',
            credits_from_page=True,refund_from_page=True,closed_from_page=True,actors=[dict(action=row.action,actor=row.actor) for row in events],
            invoice=original.name,credit_note=credits[0].name,original_receipt=entry.name,refund_journal=vouchers['Journal Entry'][0],
            refund_entry=vouchers['Payment Entry'][0],pos_refund='30.00',remaining_credit_at_review='30.00',additional_refund='30.00',
            original_closed_expected='160.00',opening='160.00',final_expected='100.00',final_credit='0.00',exchange_difference='0.00',
            original_documents_preserved=True,stock_net='0',operational_payments=2,payment_entries=2,
            native_pos_collections=nio['pos_collections'],native_pos_refunds=nio['pos_refunds'],native_pos_does_not_repeat_operational_refund=True)
        (ROOT/'docs/evidence/mixed-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback();frappe.destroy()
