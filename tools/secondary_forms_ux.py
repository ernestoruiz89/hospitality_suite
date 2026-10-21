"""Guarded temporary acceptance web and read-only proof of secondary forms."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

BENCH=Path('/home/frappe/benches/hospitality-bench');SITE='hospitality-acceptance.localhost'
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','inspect']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('hospitality_integration_test_site') and config.get('allow_tests')
assert (BENCH/'.hospitality-secondary-forms-ux-baseline.json').is_file()
pidfile=BENCH/'.hospitality-run/secondary-forms-web.pid';log=pidfile.with_suffix('.log')
if args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Temporary secondary forms server started on 8089')
elif args.action=='stop':
    if pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert SITE in command and 'serve' in command and '8089' in command
            assert (process/'cwd').resolve() in (BENCH,BENCH/'sites')
            os.kill(int(process.name),signal.SIGTERM)
    print('Temporary secondary forms server stopped')
else:
    import frappe
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        category=frappe.get_doc('HS Category',{'property':prop.name,'category_name':'Revisión de formularios'})
        assert category.owner=='administrator@hospitality.example.invalid' and category.capacity==2
        assert frappe.db.count('HS Category',{'property':prop.name,'category_name':category.category_name})==1
        assert frappe.db.count('HS Rate',{'property':prop.name})==1,'The rate draft must stay unsaved'
        shifts=frappe.get_all('HS Shift',filters={'property':prop.name},fields=['name','status','cashier','opening_amount','counted_amount','difference'])
        assert len(shifts)==1 and shifts[0].status=='Closed' and shifts[0].cashier=='cashier@hospitality.example.invalid'
        assert shifts[0].opening_amount==shifts[0].counted_amount==shifts[0].difference==0
        assert str(prop.business_date)=='2026-10-19'
        counts={dt:frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Payment','HS Charge','Sales Invoice','Payment Entry','Journal Entry')}
        assert not any(counts.values())
        proof=dict(site=SITE,mutations_by_inspector=False,fixture_origin='User actions from Pages',category=category.name,category_records=1,capacity=2,
            rate_draft_unsaved=True,shift=shifts[0].name,shift_opening=0,shift_counted=0,shift_difference=0,operation_counts=counts,business_date='2026-10-19')
        (ROOT/'docs/evidence/secondary-forms-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
    finally:frappe.db.rollback();frappe.destroy()
