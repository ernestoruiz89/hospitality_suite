"""Read-only comparison with the protected 0.8.8 baselines for phase review."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import urllib.request

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
baseline_path=BENCH/'.hospitality-provider-contracts-upgrade.json'
baseline=json.loads(baseline_path.read_text())
os.chdir(BENCH/'sites')
sites={}
for site,database in [('hospitality.localhost','hospitality_dev'),('hospitality-acceptance.localhost','hospitality_acceptance')]:
    frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        assert frappe.conf.allow_tests and frappe.conf.db_name==database
        if site=='hospitality-acceptance.localhost':assert frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
        expected=baseline[site];tables={}
        for dt,spec in expected['tables'].items():
            columns=spec['columns'];assert all(name.replace('_','').isalnum() for name in columns)
            rows=frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in columns)+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            tables[dt]=dict(columns=columns,rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        assert tables==expected['tables'],site
        private={}
        for name in frappe.get_all('File',filters={'is_private':1,'is_folder':0},pluck='name'):
            path=Path(frappe.get_doc('File',name).get_full_path()).resolve()
            assert path.is_relative_to(Path(frappe.get_site_path('private','files')).resolve())
            private[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        assert private==expected['private_files']
        sites[site]=dict(tables=len(tables),rows=sum(value['rows'] for value in tables.values()),private_files=len(private),exact_match=True)
        if site=='hospitality.localhost':
            sites[site]['business_date']=str(frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'},'business_date'))
            assert sites[site]['business_date']=='2026-10-19'
        else:
            assert not any(frappe.db.count(dt) for dt in ['HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry'])
    finally:frappe.db.rollback();frappe.destroy()
ports={}
for port in [8086,8089,9001,11001,13001]:
    with socket.socket() as connection:
        connection.settimeout(.3);ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert ports=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
with urllib.request.urlopen('http://hospitality.localhost:8086/login',timeout=10) as response:assert response.status==200
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
           sites=sites,ports=ports,main_http=200,database_mutations=False,new_backup_or_restore=False)
(ROOT/'docs/evidence/phase-review-preservation.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(proof))
