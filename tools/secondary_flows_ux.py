"""Explicit test prerequisites and native read-only observations for secondary Pages."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
TARGET=BENCH/'sites'/SITE
STATE=BENCH/'.hospitality-secondary-flows-fixture.json'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','checkpoint'])
parser.add_argument('--label',required=True)
args=parser.parse_args()
assert re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',args.label)
assert (BENCH/'.hospitality-secondary-flows-ux-baseline.json').is_file()
output=ROOT/f'docs/evidence/secondary-flows-{args.label}.json'
assert not output.exists()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    from hospitality_suite.accounting import post_standard
    require_test_site(paused=True)
    assert frappe.conf.db_name=='hospitality_acceptance'
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    assert str(prop.business_date)=='2026-10-19'
    if args.action=='prepare':
        assert not STATE.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','HS Incident'])
        original={p.relative_to(TARGET).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for kind in ['public','private'] for p in (TARGET/kind/'files').rglob('*') if p.is_file()}
        reserve=frappe.get_doc(dict(doctype='Warehouse',warehouse_name='Reserva de ropa de aceptación',company=prop.company,
            parent_warehouse=frappe.db.get_value('Warehouse',{'company':prop.company,'is_group':1},'name'),hs_property=prop.name)).insert()
        item=frappe.get_doc(dict(doctype='Item',item_code='HS-UX-LINEN-SF',item_name='Sábana de aceptación operativa',
            item_group='Products',stock_uom='Nos',is_stock_item=1,is_sales_item=0,is_purchase_item=1)).insert()
        receipt=frappe.new_doc('Stock Entry')
        receipt.update(dict(company=prop.company,stock_entry_type='Material Receipt'))
        for warehouse,qty in [(prop.warehouse,10),(reserve.name,5)]:
            receipt.append('items',dict(item_code=item.name,qty=qty,t_warehouse=warehouse,basic_rate=25))
        post_standard(receipt,prop)
        state=dict(property=prop.name,item=item.name,reserve=reserve.name,operational=prop.warehouse,receipt=receipt.name,original_files=original)
    else:state=json.loads(STATE.read_text())
    proof=dict(label=args.label,at_utc=datetime.now(timezone.utc).isoformat(),site=SITE,mutation=args.action=='prepare',
        fixture=dict(origin='Native API/standard documents: one linen item, reserve warehouse and opening stock 10 operational + 5 reserve at 25. No linen movement, laundry warehouse, policy or portal request created by this fixture.',
            item=state['item'],reserve=state['reserve'],operational=state['operational'],receipt=state['receipt']),
        property=prop.as_dict(),
        stock=frappe.get_all('Bin',filters={'item_code':state['item']},fields=['warehouse','actual_qty','valuation_rate'],order_by='warehouse'),
        stock_entries=frappe.get_all('Stock Entry',fields=['name','stock_entry_type','docstatus','hs_stock_purpose','owner','modified_by','total_outgoing_value'],order_by='creation'),
        linen_incidents=frappe.get_all('HS Incident',filters={'kind':'Linen'},fields=['name','status','item','quantity','description','stock_entry','owner']),
        stock_policies=frappe.get_all('HS Stock Policy',filters={'item':state['item']},fields=['name','warehouse','purpose','owner']),
        reorder=frappe.get_all('Item Reorder',filters={'parent':state['item']},fields=['warehouse','warehouse_reorder_level','warehouse_reorder_qty']),
        gl=frappe.get_all('GL Entry',fields=['voucher_type','voucher_no','account','debit','credit','owner'],order_by='creation'),
        stock_ledger=frappe.get_all('Stock Ledger Entry',filters={'item_code':state['item']},fields=['voucher_type','voucher_no','warehouse','actual_qty','stock_value_difference','owner'],order_by='creation'),
        audit=frappe.get_all('HS Audit Event',filters={'property':prop.name},fields=['actor','action','source_doctype','source_name','reason'],order_by='creation'),
        finance_counts={dt:frappe.db.count(dt) for dt in ['HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry']},
        original_physical_files=len(state['original_files']))
    # Configuration contains server/account references, no credentials. Only export
    # fields relevant to the workflows, never a complete user/site configuration.
    proof['property']={key:proof['property'].get(key) for key in ['name','modified','business_date','laundry_warehouse','warehouse',
        'check_in_time','check_out_time','cancellation_fee_mode','cancellation_fee_value','no_show_fee_mode','no_show_fee_value',
        'advance_policy','guarantee_policy','retention_days','portal_enabled','guest_id_required']}
    serialized=json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n'
    if args.action=='prepare':
        STATE.write_text(json.dumps(state));STATE.chmod(0o600)
        frappe.db.commit()
    output.write_text(serialized,encoding='utf-8',newline='\n')
    print(json.dumps(dict(label=args.label,mutation=proof['mutation'],stock=proof['stock'],linen=len(proof['linen_incidents']),finance_counts=proof['finance_counts']),ensure_ascii=False))
finally:
    frappe.db.rollback();frappe.destroy()
