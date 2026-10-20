"""Prepare a native POS receipt; credit notes are submitted only from the Page."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
FIXTURE=BENCH/'.hospitality-credits-ux-fixture.json'
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
        assert (BENCH/'.hospitality-credits-ux-baseline.json').is_file()
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
        invoice.append('payments',dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=100))
        invoice.set_missing_values()
        invoice.insert().submit()
        call('close_shift',dict(shift=old,modified=str(frappe.get_doc('HS Shift',old).modified),denominations={'NIO':[dict(value=10,count=16)]}))
        new=call('open_shift',dict(opening_amount=160))['shift']
        FIXTURE.write_text(json.dumps(dict(property=prop.name,original_shift=old,shift=new,invoice=invoice.name,method=method.name,account=method.account)))
        FIXTURE.chmod(0o600)
        frappe.db.commit()
        print('POS sintético: venta 60, recibido 100, vuelto 40; turno original cerrado en 160 y nuevo fondo 160. Sin notas ni devoluciones preparadas.')
    else:
        fixture=json.loads(FIXTURE.read_text())
        original=frappe.get_doc('Sales Invoice',fixture['invoice'])
        old=frappe.get_doc('HS Shift',fixture['original_shift'])
        shift=frappe.get_doc('HS Shift',fixture['shift'])
        credits=frappe.get_all('Sales Invoice',filters={'return_against':original.name,'docstatus':1},fields=['name','grand_total','outstanding_amount','is_pos','update_stock','owner'])
        assert len(credits)==2 and all(row.grand_total==-30 and row.outstanding_amount==0 and not row.is_pos and row.update_stock for row in credits)
        vouchers=linked_vouchers(fixture['property'],[row.name for row in credits])
        assert len(vouchers['Journal Entry'])==2 and not vouchers['Payment Entry']
        assert original.docstatus==1 and original.paid_amount==100 and original.change_amount==40 and original.hs_shift==old.name
        assert old.status=='Closed' and old.expected_amount==old.counted_amount==160 and expected(old)=={'NIO':'160.00'}
        assert shift.status=='Closed' and shift.expected_amount==shift.counted_amount==100 and expected(shift)=={'NIO':'100.00'}
        assert frappe.db.count('HS Payment')==frappe.db.count('Payment Entry')==0
        rows=ledger(vouchers['Journal Entry'],{fixture['account']},'Journal Entry')
        assert rows[(fixture['account'],'NIO')]['amount']==-60
        stock=frappe.get_all('Stock Ledger Entry',filters={'voucher_type':'Sales Invoice','voucher_no':['in',[original.name]+[row.name for row in credits]],'is_cancelled':0},pluck='actual_qty')
        assert sum(stock)==0
        events=frappe.get_all('HS Audit Event',filters={'property':fixture['property'],'action':'Credit note'},fields=['actor','details'])
        assert len(events)==2 and all(row.actor=='manager@hospitality.example.invalid' for row in events)
        from hospitality_suite.close_financials import snapshot
        prop=frappe.get_doc('HS Property',fixture['property'])
        financial=snapshot(prop,{})
        nio=next(row for row in financial['currencies'] if row['currency']=='NIO')
        assert nio['pos_collections']==nio['pos_refunds']=='60.00'
        assert len([row for row in financial['sources']['native_pos'] if row['doctype']=='Journal Entry'])==2
        from hospitality_suite.reconciliation import unmatched_cash
        assert not unmatched_cash(prop)
        os.environ['PATH']=str(BENCH/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
        frappe.local.lang='es'
        frappe.local.conf.host_name='http://localhost:8089'
        html=frappe.get_print('HS Shift',shift.name,print_format='HS Arqueo')
        assert 'Documento ERPNext' in html and all(name in html for name in vouchers['Journal Entry'])
        pdf=frappe.get_print('HS Shift',shift.name,print_format='HS Arqueo',as_pdf=True)
        (ROOT/'output/native-pos/credits-shift.pdf').write_bytes(pdf)
        proof=dict(site=SITE,synthetic=True,fixture_origin='ERPNext Sales Invoice controller / application shift API',
                   credits_from_page=True,closed_from_page=True,credit_actor=events[0].actor,invoice=original.name,original_tendered='100.00',original_change='40.00',
                   net_receipt='60.00',credit_notes=[row.name for row in credits],refund_journals=vouchers['Journal Entry'],
                   refunds=['30.00','30.00'],original_closed_expected='160.00',opening='160.00',final_expected='100.00',
                   original_preserved=True,stock_net='0',operational_payments=0,payment_entries=0,
                   native_pos_collections=nio['pos_collections'],native_pos_refunds=nio['pos_refunds'],
                   pdf_sha256=hashlib.sha256(pdf).hexdigest())
        (ROOT/'docs/evidence/credits-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
