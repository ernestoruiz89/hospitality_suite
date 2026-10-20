"""Back up both isolated sites and prove the receipt-policy upgrade preserves them."""
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
BASE=BENCH/'.hospitality-integration-upgrade.json'
SITES={'hospitality.localhost':'hospitality_dev','hospitality-acceptance.localhost':'hospitality_acceptance'}
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['before','verify']);args=parser.parse_args()
native=json.loads((BENCH/'.hospitality-financial-upgrade.json').read_text())['tables']
names=sorted(set(SCHEMA)|set(native)|{'Version'})
previous=json.loads(BASE.read_text()) if args.action=='verify' else None
if args.action=='before':
    assert not BASE.exists(),'Conserve la línea de base anterior; no sustituirla'
os.chdir(BENCH/'sites')
current={}
for site,database in SITES.items():
    frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        assert frappe.conf.db_name==database
        if site=='hospitality-acceptance.localhost':
            assert frappe.conf.allow_tests and frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
            assert not any(frappe.db.count(dt) for dt in ('HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'))
        # The fixture sites have no external-provider receipts to redact. Legacy
        # bodies/versions are exercised transactionally in TestWebhook instead.
        assert frappe.db.count('HS Integration Event')==0
        tables={}
        for dt in names:
            rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            tables[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        private={}
        private_root=Path(frappe.get_site_path('private','files')).resolve()
        for name in frappe.get_all('File',filters={'is_private':1,'is_folder':0},pluck='name'):
            file=frappe.get_doc('File',name)
            path=Path(file.get_full_path()).resolve()
            assert path.is_relative_to(private_root) and path.is_file()
            private[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        current[site]=dict(tables=tables,private_files=private)
    finally:
        frappe.db.rollback();frappe.destroy()
    if args.action=='before':
        log=BENCH/('.hospitality-integration-backup-'+site+'.log')
        with log.open('w') as output:
            subprocess.run(['/home/frappe/.local/bin/bench','--site',site,'backup','--with-files'],cwd=BENCH,stdout=output,stderr=subprocess.STDOUT,check=True)
        log.chmod(0o600)
        backup_root=BENCH/'sites'/site/'private/backups'
        db=max(backup_root.glob('*-database.sql.gz'),key=lambda path:path.stat().st_mtime)
        prefix=db.name.removesuffix('-database.sql.gz')
        files=list(backup_root.glob(prefix+'*'))
        assert len(files)>=4
        for path in files:path.chmod(0o600)
        current[site]['backup_files']={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files}

if args.action=='before':
    BASE.write_text(json.dumps(current),encoding='utf-8');BASE.chmod(0o600)
    print('Dos respaldos nativos con archivos; línea de base privada guardada.')
else:
    result={}
    for site in SITES:
        assert current[site]['tables']==previous[site]['tables'],[dt for dt in names if current[site]['tables'][dt]!=previous[site]['tables'][dt]]
        assert current[site]['private_files']==previous[site]['private_files']
        backup_root=BENCH/'sites'/site/'private/backups'
        assert all(hashlib.sha256((backup_root/name).read_bytes()).hexdigest()==digest for name,digest in previous[site]['backup_files'].items())
        result[site]=dict(tables_preserved=len(names),rows_preserved=sum(row['rows'] for row in current[site]['tables'].values()),
                          private_files_preserved=len(current[site]['private_files']),backup_with_files=True,existing_integration_events=0)
    proof=dict(sites=result,all_columns_compared=True,legacy_migration_evidence='integration-native-tests.xml::TestWebhook',
               synchronization_enabled=False)
    (ROOT/'docs/evidence/integration-upgrade.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof))
