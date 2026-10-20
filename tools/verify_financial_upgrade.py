"""Compare business rows and private bytes across declared schema additions."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

import frappe
from hospitality_suite.schema import SCHEMA

parser=argparse.ArgumentParser()
parser.add_argument('stage',choices=['before','after'])
parser.add_argument('--profile',choices=['financial','service'],default='financial')
args=parser.parse_args()
bench=Path('/home/frappe/benches/hospitality-bench')
root=Path(__file__).resolve().parents[1]
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_dev'
    frappe.set_user('Administrator')
    native=['Company','Account','Cost Center','Warehouse','Customer','Supplier','Contact','Address','Dynamic Link','Item','Item Price','Item Reorder','Asset','File',
            'Sales Invoice','Sales Invoice Item','Sales Taxes and Charges','Payment Entry','Payment Entry Reference','Payment Entry Deduction',
            'Journal Entry','Journal Entry Account','Stock Entry','Stock Entry Detail','Stock Reconciliation','Stock Reconciliation Item','Bin',
            'GL Entry','Payment Ledger Entry','Stock Ledger Entry','Purchase Order','Purchase Order Item','Purchase Receipt','Purchase Receipt Item','Purchase Invoice','Purchase Invoice Item']
    additions={'HS Property':{'advance_policy','guarantee_policy'},'HS Payment':{'business_date','business_date_source'}} if args.profile=='financial' else {'HS Property':{'extra_hour_item'}}
    tables={}
    for dt in sorted(set(SCHEMA)|set(native)):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        for row in rows:
            for field in additions.get(dt,()):
                row.pop(field,None)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        tables[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    files={}
    private=(bench/'sites'/frappe.local.site/'private/files').resolve()
    for url in frappe.get_all('File',filters={'is_private':1},pluck='file_url'):
        if url and url.startswith('/private/files/'):
            path=(bench/'sites'/frappe.local.site/url.lstrip('/')).resolve()
            assert path.is_relative_to(private) and path.is_file()
            files[url]=hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint=dict(tables=tables,files=files)
    saved=bench/('.hospitality-'+args.profile+'-upgrade.json')
    if args.stage=='before':
        saved.write_text(json.dumps(fingerprint,sort_keys=True))
        saved.chmod(0o600)
    else:
        assert fingerprint==json.loads(saved.read_text()),'Business rows or private bytes changed during migration'
        properties=frappe.get_all('HS Property',fields=['advance_policy','guarantee_policy'])
        assert all(p.advance_policy and p.guarantee_policy for p in properties)
        payments=frappe.get_all('HS Payment',fields=['business_date','business_date_source'])
        assert all(bool(p.business_date)==(p.business_date_source!='Unknown') for p in payments)
        if args.profile=='service':
            assert all(not r.lodging_item or r.extra_hour_item for r in frappe.get_all('HS Property',fields=['lodging_item','extra_hour_item']))
    proof=dict(stage=args.stage,site=frappe.local.site,passed=True,tables=len(tables),rows=sum(r['rows'] for r in tables.values()),
               private_files=len(files),excluded_new_columns={dt:sorted(fields) for dt,fields in additions.items()},
               aggregate_sha256=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest())
    if args.stage=='after':
        proof['payment_dates']=dict(Counter(p.business_date_source for p in payments))
        proof['property_policies']=dict(Counter(p.advance_policy+'/'+p.guarantee_policy for p in properties))
    (root/('docs/evidence/'+args.profile+'-upgrade-'+args.stage+'.json')).write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof))
finally:
    frappe.db.rollback()
    frappe.destroy()
