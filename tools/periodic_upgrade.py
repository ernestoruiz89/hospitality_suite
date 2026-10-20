"""Back up isolated sites and compare every pre-existing column after upgrade."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import frappe
from hospitality_suite.schema import SCHEMA

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['before','verify']);parser.add_argument('--phase',choices=['periodic','billing-ui','board','availability','drafts','tariffs','account-summary','guest-profiles','background-jobs','countdown','finance-audit','housekeeping-audit','permissions-audit'],default='periodic');args=parser.parse_args()
BASE=BENCH/f'.hospitality-{args.phase}-upgrade.json'
assert args.action!='before' or not BASE.exists(),'Conserve la línea de base original'
old=json.loads(BASE.read_text()) if args.action=='verify' else None
native=json.loads((BENCH/'.hospitality-financial-upgrade.json').read_text())['tables']
names=sorted(set(SCHEMA)|set(native)|{'Version'})
os.chdir(BENCH/'sites')
result={}
for site,database in {'hospitality.localhost':'hospitality_dev','hospitality-acceptance.localhost':'hospitality_acceptance'}.items():
    frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        assert frappe.conf.db_name==database
        if site=='hospitality-acceptance.localhost':
            assert frappe.conf.pause_scheduler and frappe.conf.allow_tests and frappe.conf.hospitality_integration_test_site
            assert not any(frappe.db.count(dt) for dt in ('HS Stay','HS Charge','HS Payment','Sales Invoice','Payment Entry'))
        tables={}
        for dt in names:
            columns=old[site]['tables'][dt]['columns'] if old else sorted(frappe.db.get_table_columns(dt))
            assert all(column.replace('_','').isalnum() for column in columns)
            rows=frappe.db.sql('SELECT '+','.join('`'+column+'`' for column in columns)+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            tables[dt]=dict(columns=columns,rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        private={}
        for name in frappe.get_all('File',filters={'is_private':1,'is_folder':0},pluck='name'):
            path=Path(frappe.get_doc('File',name).get_full_path()).resolve()
            assert path.is_relative_to(Path(frappe.get_site_path('private','files')).resolve())
            private[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        if old:
            assert tables==old[site]['tables'] and private==old[site]['private_files']
            if args.phase=='drafts':
                assert 'draft_data' in frappe.db.get_table_columns('HS Booking')
                assert not frappe.db.count('HS Booking',{'draft_data':['is','set']})
            assert not frappe.db.count('HS Charge',{'period_key':['is','set']})
            assert not frappe.db.count('HS Charge',{'status':'Scheduled'})
            assert not frappe.db.count('HS Charge',{'service_date':['is','set']})
            assert not frappe.db.count('HS Charge',{'posted_at':['is','set']})
            assert all(row.lodging_charge_policy=='Arrival' for row in frappe.get_all('HS Property',fields=['lodging_charge_policy']))
            assert all(row.lodging_charge_policy=='Arrival' for row in frappe.get_all('HS Stay',fields=['lodging_charge_policy']))
        result[site]=dict(tables=tables,private_files=private)
    finally:
        frappe.db.rollback();frappe.destroy()
    if args.action=='before':
        log=BENCH/('.hospitality-periodic-backup-'+site+'.log')
        with log.open('w') as stream:
            subprocess.run(['/home/frappe/.local/bin/bench','--site',site,'backup','--with-files'],cwd=BENCH,stdout=stream,stderr=subprocess.STDOUT,check=True)
        log.chmod(0o600)
        backups=BENCH/'sites'/site/'private/backups'
        db=max(backups.glob('*-database.sql.gz'),key=lambda path:path.stat().st_mtime)
        files=list(backups.glob(db.name.removesuffix('-database.sql.gz')+'*'))
        assert len(files)>=4
        for path in files:path.chmod(0o600)
        result[site]['backup_files']={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    else:
        backups=BENCH/'sites'/site/'private/backups'
        assert all(hashlib.sha256((backups/name).read_bytes()).hexdigest()==digest for name,digest in old[site]['backup_files'].items())
if args.action=='before':
    BASE.write_text(json.dumps(result));BASE.chmod(0o600)
    print('Respaldos con archivos y columnas previas conservados en la línea de base privada.')
else:
    proof=dict(previous_columns_preserved=True,default_policy_preserves_existing_stays=True,
               sites={site:dict(tables=len(value['tables']),rows=sum(row['rows'] for row in value['tables'].values()),private_files=len(value['private_files'])) for site,value in result.items()})
    (ROOT/f'docs/evidence/{args.phase}-upgrade.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof))
