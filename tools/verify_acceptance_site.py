"""Read-only proof of the isolated acceptance baseline and main native ledger."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request

import frappe

bench=Path('/home/frappe/benches/hospitality-bench')
parser=argparse.ArgumentParser()
parser.add_argument('--phase',choices=['financial','service','pos','refund','guarantee','credits','mixed','accounting','integration','forms','periodic','billing','board','availability','drafts'],default='financial')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
os.chdir(bench/'sites')
proof={}
for site,database in [('hospitality-acceptance.localhost','hospitality_acceptance'),('hospitality.localhost','hospitality_dev')]:
    frappe.init(site=site,sites_path=str(bench/'sites'))
    frappe.connect()
    try:
        assert frappe.conf.allow_tests and frappe.conf.db_name==database
        frappe.set_user('Administrator')
        if site=='hospitality-acceptance.localhost':
            assert frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
            counts={dt:frappe.db.count(dt) for dt in ('HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','HS Daily Close','Sales Invoice','Payment Entry','Journal Entry')}
            assert not any(counts.values()),counts
            assert len(frappe.get_all('HS Property'))==2
            backups=list((bench/'sites'/site/'private/backups').glob('*-database.sql.gz'))
            assert backups
            proof['acceptance']=dict(site=site,installed_apps=frappe.get_installed_apps(),operation_counts=counts,
                                      designated_test_site=True,scheduler_paused=True,initial_backup_exists=True)
        else:
            from hospitality_suite.tests.setup import before_tests
            try:
                before_tests()
            except frappe.ValidationError as error:
                assert 'Designe un sitio vacío' in str(error)
            else:
                raise AssertionError('The demo must not run integration fixtures')
            before=json.loads((bench/'.hospitality-financial-upgrade.json').read_text())
            checked=[]
            refreshed=[]
            for dt,expected in before['tables'].items():
                if dt.startswith('HS '):continue
                rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
                raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
                actual=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
                if args.phase in ('accounting','integration','forms','periodic','billing','board','availability','drafts') and dt=='Company' and actual!=expected:
                    cache=json.loads((bench/'.hospitality-accounting-company-cache.json').read_text())
                    assert cache['source_company_sha256']==expected['sha256'] and cache['current_company_sha256']==actual['sha256']
                    assert cache['changed_fields']==['modified','sales_monthly_history','transactions_annual_history']
                    assert cache['company_matches_pre_phase_backup'] and cache['cached_histories_match_native_read_functions']
                    refreshed.append(dt)
                    continue
                assert actual==expected,dt
                checked.append(dt)
            proof['main']=dict(site=site,integration_fixture_guard_rejects=True,native_tables_unchanged=len(checked),business_date=str(frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'},'business_date')))
            if refreshed:
                proof['main'].update(native_derived_cache_refreshed=refreshed,native_tables_equal_pre_phase_backup=len(checked)+len(refreshed),company_cache_evidence='accounting-company-cache.json')
    finally:
        frappe.db.rollback()
        frappe.destroy()
listeners=subprocess.check_output(['ss','-ltnp'],text=True)
proof['ports']={str(p):(':'+str(p)+' ') in listeners for p in (8086,8089,9001,11001,13001)}
assert proof['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
with urllib.request.urlopen('http://localhost:8086/login') as response:
    assert response.status==200
proof['main_http']=200
proof['mutations']=False
(root/('docs/evidence/'+args.phase+'-final-state.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(proof,ensure_ascii=False))
