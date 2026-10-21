"""Isolated browser server and read-only inspection for action-context recovery."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess

BENCH=Path('/home/frappe/benches/hospitality-bench');SITE='hospitality-acceptance.localhost'
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','checkpoint','inspect']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('hospitality_integration_test_site') and config.get('allow_tests')
assert (BENCH/'.hospitality-action-context-ux-baseline.json').is_file()
pidfile=BENCH/'.hospitality-run/action-context-web.pid';log=pidfile.with_suffix('.log')
if args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Temporary action-context server started on 8089')
elif args.action=='stop':
    if pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert SITE in command and 'serve' in command and '8089' in command
            assert (process/'cwd').resolve() in (BENCH,BENCH/'sites')
            os.kill(int(process.name),signal.SIGTERM)
    print('Temporary action-context server stopped')
else:
    import frappe
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator');prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        shifts=frappe.get_all('HS Shift',filters={'property':prop.name},fields=['name','status','cashier','opening_amount','counted_amount','difference'])
        assert shifts and all(row.status=='Closed' and row.cashier=='cashier@hospitality.example.invalid' and row.opening_amount==row.counted_amount==row.difference==0 for row in shifts)
        counts={dt:frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Payment','HS Charge','Sales Invoice','Payment Entry','Journal Entry')}
        assert str(prop.business_date)=='2026-10-19'
        proof=dict(site=SITE,mutations_by_inspector=False,fixture_origin='User actions from Pages',shifts=shifts,operation_counts=counts,business_date='2026-10-19')
        http=log.read_text();availability=re.findall(r'"POST /api/method/hospitality_suite.api.availability_search HTTP/1.1" (\d+)',http)
        logouts=re.findall(r'"POST /api/method/logout HTTP/1.1" (\d+)',http)
        proof.update(availability_http_statuses=availability,logout_http_statuses=logouts,http_500=len(re.findall(r'HTTP/1.1" 500 ',http)))
        assert not proof['http_500'] and len(shifts)==2
        if args.action=='checkpoint':
            assert not any(counts.values()) and not availability and logouts==['200']
            filename='action-context-invalid-checkpoint.json'
        else:
            # The user requested colors after the invalid-input checkpoint.
            # One actual Page-created reservation supplies the red state;
            # do not rewrite the earlier zero-query checkpoint.
            assert counts=={'HS Booking':1,'HS Stay':0,'HS Payment':0,'HS Charge':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0}
            booking=frappe.get_doc('HS Booking',frappe.db.get_value('HS Booking',{'property':prop.name}))
            assert booking.status=='Confirmed' and booking.owner=='receptionist@hospitality.example.invalid' and len(booking.rooms)==1
            room=frappe.get_doc('HS Room',booking.rooms[0].room)
            assert room.room_number=='H101' and booking.rooms[0].people==2 and booking.amount==1500
            allocations=frappe.get_all('HS Allocation',fields=['kind','status','booking','room','starts_at','ends_at'])
            assert len(allocations)==1 and allocations[0].kind=='Reservation' and allocations[0].status=='Active' and allocations[0].booking==booking.name and allocations[0].room==room.name
            from hospitality_suite.availability_search import search
            result=search(prop.name,'2026-10-24T14:00:00-06:00','2026-10-25T12:00:00-06:00',room.category,2,1)
            states=[dict(room=row['room_number'],status=row['status'],cleaning_status=row['cleaning_status']) for row in result['room_states']]
            assert result['available']==9 and result['enough'] and states[0]['room']=='H101' and states[0]['status']=='Reserved'
            assert len(states)==10 and all(row['status']=='Available' for row in states[1:])
            from hospitality_suite.time import local
            from frappe.utils import get_system_timezone
            assert local(booking.starts_at,prop).isoformat()=='2026-10-24T14:00:00-06:00' and local(booking.ends_at,prop).isoformat()=='2026-10-25T12:00:00-06:00'
            proof.update(booking=dict(name=booking.name,status=booking.status,room='H101',people=2,amount=1500,starts_at=str(booking.starts_at),ends_at=str(booking.ends_at)),
                         interval_states=states,available=9,native_read_only_query_by_inspector=True,system_timezone=get_system_timezone(),property_timezone=prop.time_zone)
            assert availability==['200']*3 and logouts==['200','200']
            filename='action-context-items-ui.json'
        (ROOT/'docs/evidence'/filename).write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof,ensure_ascii=False,default=str))
    finally:frappe.db.rollback();frappe.destroy()
