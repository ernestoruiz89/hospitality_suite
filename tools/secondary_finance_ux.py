"""Explicit synthetic prerequisites; subsequent finance/supply writes use role Pages."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','checkpoint'])
parser.add_argument('--label',required=True)
args=parser.parse_args()
assert re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',args.label)
fixture_path=BENCH/'sites'/SITE/'private/secondary-finance-fixture.json'
output=ROOT/'docs/evidence'/f'secondary-finance-{args.label}.json'
assert not output.exists() and (BENCH/'.hospitality-secondary-finance-ux-baseline.json').is_file()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    from hospitality_suite import api
    from hospitality_suite.cashier import expected
    from frappe.permissions import has_permission
    require_test_site(paused=True)
    assert frappe.conf.db_name=='hospitality_acceptance'
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    assert str(prop.business_date)=='2026-10-19'
    if args.action=='prepare':
        assert not fixture_path.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Booking','HS Stay','HS Charge','HS Payment','HS Shift',
            'Sales Invoice','Payment Entry','Journal Entry','Purchase Order','Purchase Receipt','Purchase Invoice'])
        def account(label,root='Asset',kind=None):
            parent=frappe.db.get_value('Account',dict(company=prop.company,root_type=root,is_group=1,parent_account=['is','not set']),'name')
            assert parent
            return frappe.get_doc(dict(doctype='Account',company=prop.company,parent_account=parent,
                account_name=label,account_currency=prop.currency,account_type=kind)).insert().name
        accounts=dict(expense=account('Gasto de aceptación financiera','Expense'),
            clearing=account('Compensación de aceptación financiera',kind='Bank'),
            bank=account('Banco de aceptación financiera',kind='Bank'),
            withholding=account('Retención de aceptación financiera'))
        mode=frappe.get_doc(dict(doctype='Mode of Payment',mode_of_payment='Tarjeta de aceptación financiera',type='Bank',
            accounts=[dict(company=prop.company,default_account=accounts['clearing'])])).insert()
        from hospitality_suite.time import now_local
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        start=now_local(prop).replace(microsecond=0)
        values=dict(starts_at=start.isoformat(),ends_at=(start+timedelta(days=1)).isoformat(),guest=guest.name,
            customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        stay=api.execute(prop.name,'walk_in',uuid.uuid4().hex,values)
        fixture=dict(property=prop.name,accounts=accounts,card_mode=mode.name,stay=stay,
            origin='Native API fixture: four accounts, one standard payment mode and H101 stay. No expense category, configured HS card method, supplier, warehouse, purchase, shift, payment or settlement created by fixture.')
    else:
        fixture=json.loads(fixture_path.read_text())
    counts={dt:frappe.db.count(dt) for dt in ['HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','HS Expense Category',
        'HS Supplier','Sales Invoice','Payment Entry','Journal Entry','Purchase Order','Purchase Receipt','Purchase Invoice',
        'Stock Entry','Stock Reconciliation','GL Entry','Stock Ledger Entry','File']}
    payments=frappe.get_all('HS Payment',filters={'property':prop.name},fields=['name','kind','status','amount','currency','owner',
        'method','shift','reference','source_payment','fee_amount','withholding_amount','net_amount','journal_entry','payment_entry'],order_by='creation')
    shifts=frappe.get_all('HS Shift',filters={'property':prop.name},fields=['name','cashier','status','opening_amount','counted_amount','difference'])
    for shift in shifts:
        shift['expected_now']=expected(frappe.get_doc('HS Shift',shift.name))
    proof=dict(observed_at_utc=datetime.now(timezone.utc).isoformat(),label=args.label,site=SITE,
        fixture=fixture,database_mutation=args.action=='prepare',counts=counts,payments=payments,shifts=shifts,
        stock=frappe.get_all('Bin',filters={'item_code':'HS-DEMO-WATER'},fields=['warehouse','actual_qty','valuation_rate'],order_by='warehouse'),
        purchase_orders=frappe.get_all('Purchase Order',fields=['name','supplier','docstatus','grand_total','per_received']),
        purchase_receipts=frappe.get_all('Purchase Receipt',fields=['name','supplier','docstatus','grand_total']),
        purchase_invoices=frappe.get_all('Purchase Invoice',fields=['name','supplier','docstatus','grand_total','outstanding_amount','update_stock']),
        stock_reconciliations=frappe.get_all('Stock Reconciliation',fields=['name','docstatus','owner','modified_by','hs_property','difference_amount']),
        manager_has_general_count_write=bool(has_permission('Stock Reconciliation','write',user='manager@hospitality.example.invalid',print_logs=False)),
        count_audit=frappe.get_all('HS Audit Event',filters={'action':'Stock count adjustment'},fields=['actor','source_doctype','source_name','reason']),
        gl=frappe.get_all('GL Entry',fields=['voucher_type','voucher_no','account','debit','credit','owner'],order_by='creation'),
        stock_ledger=frappe.get_all('Stock Ledger Entry',fields=['voucher_type','voucher_no','warehouse','item_code','actual_qty','stock_value_difference','owner'],order_by='creation'),
        source_sha256={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/'hospitality_suite').rglob('*') if path.suffix in ['.py','.js'] and 'dist' not in path.parts})
    serialized=json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n'
    if args.action=='prepare':
        fixture_path.write_text(json.dumps(fixture,ensure_ascii=False))
        fixture_path.chmod(0o600)
        frappe.db.commit()
    output.write_text(serialized,encoding='utf-8',newline='\n')
    print(json.dumps(dict(stage=args.label,mutation=proof['database_mutation'],counts=counts)))
finally:
    frappe.db.rollback()
    frappe.destroy()
