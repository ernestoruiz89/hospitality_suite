"""Bounded, read-only fingerprints for the isolated backup/reversal exercise.

Only counts and SHA-256 hashes leave the bench. No rows, files or credentials are
exported. Snapshot before starting UI sessions; user/session metadata is excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import frappe
from hospitality_suite.schema import SCHEMA

parser=argparse.ArgumentParser()
parser.add_argument('stage',choices=['baseline','source','restored','migrated','reversed','redeployed','ui'])
args=parser.parse_args()
bench=Path('/home/frappe/benches/hospitality-bench')
site='hospitality.localhost' if args.stage in ('baseline','source') else 'hospitality-restore.localhost'
os.chdir(bench/'sites')
frappe.init(site=site,sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    assert frappe.conf.db_name==('hospitality_dev' if site=='hospitality.localhost' else 'hospitality_restore')
    frappe.set_user('Administrator')
    native=['Company','Account','Cost Center','Warehouse','Customer','Supplier','Contact','Address','Dynamic Link',
            'Item','Item Price','Item Reorder','Asset','File','Sales Invoice','Sales Invoice Item','Sales Taxes and Charges',
            'Payment Entry','Payment Entry Reference','Payment Entry Deduction','Journal Entry','Journal Entry Account',
            'Stock Entry','Stock Entry Detail','Stock Reconciliation','Stock Reconciliation Item','Bin',
            'GL Entry','Payment Ledger Entry','Stock Ledger Entry','Purchase Order','Purchase Order Item',
            'Purchase Receipt','Purchase Receipt Item','Purchase Invoice','Purchase Invoice Item']
    tables={}
    for dt in sorted(set(SCHEMA)|set(native)):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        tables[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    files={}
    root=(bench/'sites'/site/'private/files').resolve()
    for url in frappe.get_all('File',filters={'is_private':1},pluck='file_url'):
        if not url or not url.startswith('/private/files/'):
            continue
        path=(bench/'sites'/site/url.lstrip('/')).resolve()
        assert path.is_relative_to(root) and path.is_file(), 'Private File bytes missing or outside site'
        files[url]=hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint=dict(tables=tables,private_files=files)
    baseline=bench/'.hospitality-final-fingerprint.json'
    if args.stage=='baseline':
        baseline.write_text(json.dumps(fingerprint,sort_keys=True))
        baseline.chmod(0o600)
    else:
        expected=json.loads(baseline.read_text())
        changed=[dt for dt in tables if tables[dt]!=expected['tables'].get(dt)]
        assert not changed, 'Changed business tables: '+','.join(changed)
        assert fingerprint['private_files']==expected['private_files'], 'Private bytes differ'
    result=dict(stage=args.stage,site=site,passed=True,tables=len(tables),rows=sum(r['rows'] for r in tables.values()),
                hs_doctypes=len(SCHEMA),private_files=len(files),
                aggregate_sha256=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest(),
                data_sha256=hashlib.sha256(json.dumps(tables,sort_keys=True).encode()).hexdigest(),
                private_bytes_sha256=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest())
    evidence=Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/recovery-final-'+args.stage+'.json')
    evidence.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
finally:
    frappe.db.rollback()
    frappe.destroy()
