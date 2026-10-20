"""Back up before adding service accounting; compare every pre-existing column."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
RECEIPT=BENCH/'.hospitality-accounting-upgrade.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['before','verify']);args=parser.parse_args()
os.chdir(BENCH/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(BENCH/'sites'));frappe.connect()
try:
    assert frappe.conf.db_name=='hospitality_dev'
    from hospitality_suite.schema import SCHEMA
    native=json.loads((BENCH/'.hospitality-financial-upgrade.json').read_text())['tables']
    names=sorted(set(SCHEMA)|set(native))
    before=json.loads(RECEIPT.read_text()) if args.action=='verify' else None
    tables={}
    for dt in names:
        if args.action=='before' and not frappe.db.table_exists(dt):continue
        if before and dt not in before['tables']:continue
        columns=before['tables'][dt]['columns'] if before else sorted(frappe.db.get_table_columns(dt))
        rows=frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in columns)+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        tables[dt]=dict(columns=columns,rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    frappe.db.rollback()
    if args.action=='before':
        assert not RECEIPT.exists(),'Conserve el comprobante previo; no sustituya su línea de base'
        with (BENCH/'.hospitality-accounting-backup.log').open('w') as output:
            subprocess.run(['/home/frappe/.local/bin/bench','--site','hospitality.localhost','backup','--with-files'],cwd=BENCH,stdout=output,stderr=subprocess.STDOUT,check=True)
        backups=BENCH/'sites/hospitality.localhost/private/backups'
        database=max(backups.glob('*-database.sql.gz'),key=lambda p:p.stat().st_mtime)
        prefix=database.name.removesuffix('-database.sql.gz')
        files=[path for path in backups.glob(prefix+'*') if path.is_file()]
        assert len(files)>=4
        for path in files:path.chmod(0o600)
        RECEIPT.write_text(json.dumps(dict(tables=tables,backup_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})))
        RECEIPT.chmod(0o600)
        print('Respaldo con archivos y línea de base privada:',len(tables),'tablas;',sum(r['rows'] for r in tables.values()),'filas')
    else:
        assert tables==before['tables'],[dt for dt in tables if tables[dt]!=before['tables'][dt]]
        assert frappe.db.count('HS Service Account')==0
        props=frappe.get_all('HS Property',fields=['income_account','expense_account'])
        assert all(not row.income_account and not row.expense_account for row in props)
        proof=dict(site='hospitality.localhost',existing_tables_preserved=len(tables),existing_rows_preserved=sum(r['rows'] for r in tables.values()),
            compared_all_preexisting_columns=True,new_service_accounts=0,new_property_accounts_empty=True,backup_with_files=True)
        (ROOT/'docs/evidence/accounting-upgrade.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
finally:
    frappe.db.rollback();frappe.destroy()
