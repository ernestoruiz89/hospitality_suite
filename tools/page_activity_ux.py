"""Isolated native app server with one-shot synthetic latency/failure for UX QA.

The wrapper changes only transport timing/status in this private test process.
It does not alter Frappe files, Page HTML or operational command responses.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import threading
import time

BENCH=Path('/home/frappe/benches/hospitality-bench');SITE='hospitality-acceptance.localhost'
ROOT=Path(__file__).resolve().parents[1];STATE=BENCH/'.hospitality-run'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','serve','stop','mode','inspect','inspect-final'])
parser.add_argument('--mode',choices=['normal','slow-bootstrap','failed-bootstrap','slow-booking'],default='normal');args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('hospitality_integration_test_site') and config.get('allow_tests')
assert (BENCH/'.hospitality-page-activity-ux-baseline.json').is_file()
pidfile=STATE/'page-activity-web.pid';log=STATE/'page-activity-web.log';control=STATE/'page-activity-transport.json'
def mode(value):
    data=dict(mode=value,remaining=0 if value=='normal' else 1)
    control.write_text(json.dumps(data));control.chmod(0o600)
    return data
if args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    mode('normal')
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen([str(BENCH/'env/bin/python'),str(Path(__file__).resolve()),'serve'],cwd=BENCH/'sites',stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Isolated native UX server started on 127.0.0.1:8089')
elif args.action=='stop':
    if pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert 'page_activity_ux.py' in command and 'serve' in command and (process/'cwd').resolve()==BENCH/'sites'
            os.kill(int(process.name),signal.SIGTERM)
    print('Isolated UX server stopped')
elif args.action=='mode':print(json.dumps(mode(args.mode)))
elif args.action=='serve':
    import frappe.app as app
    from werkzeug.serving import run_simple
    os.chdir(BENCH/'sites');app._site=SITE;app._sites_path=str(BENCH/'sites')
    native=app.application;lock=threading.Lock()
    def transport(environ,start_response):
        assert environ.get('HTTP_HOST','').split(':')[0]==SITE
        selected=None
        with lock:
            data=json.loads(control.read_text())
            target='booking_detail' if data['mode']=='slow-booking' else 'bootstrap'
            if data['remaining'] and environ.get('PATH_INFO')=='/api/method/hospitality_suite.api.'+target and environ.get('REQUEST_METHOD')=='POST':
                selected=data['mode'];data['remaining']-=1;control.write_text(json.dumps(data))
        if selected:
            print('SYNTHETIC_TRANSPORT '+json.dumps(dict(mode=selected,path=environ['PATH_INFO'],delay_seconds=0 if selected=='failed-bootstrap' else 8)),flush=True)
            if selected=='failed-bootstrap':
                start_response('503 Service Unavailable',[('Content-Type','application/json')]);return [b'{"message":"Synthetic QA transport interruption"}']
            time.sleep(8)
        return native(environ,start_response)
    app.application=transport
    run_simple('127.0.0.1',8089,app.application_with_statics(),threaded=True,use_reloader=False,use_debugger=False,use_evalex=False)
elif args.action=='inspect-final':
    import frappe
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        counts={dt:frappe.db.count(dt) for dt in ('HS Shift','HS Booking','HS Stay','HS Charge','HS Payment','Sales Invoice','Payment Entry','Journal Entry','HS Allocation')}
        assert counts=={'HS Shift':0,'HS Booking':1,'HS Stay':0,'HS Charge':0,'HS Payment':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0,'HS Allocation':0}
        booking=frappe.get_doc('HS Booking',frappe.db.get_value('HS Booking',{'status':'Draft'}))
        assert booking.owner=='receptionist@hospitality.example.invalid' and booking.status=='Draft' and booking.amount==0
        raw=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',log.read_text())
        events=[json.loads(line.split('SYNTHETIC_TRANSPORT ',1)[1]) for line in raw.splitlines() if line.startswith('SYNTHETIC_TRANSPORT ')]
        assert [event['mode'] for event in events]==['slow-bootstrap']*3+['slow-booking','failed-bootstrap','slow-booking']
        assert len(re.findall(r'"POST /api/method/hospitality_suite.api.execute HTTP/1.1" 200',raw))==4
        assert len(re.findall(r'"POST /api/method/hospitality_suite.api.booking_detail HTTP/1.1" 200',raw))==2
        assert not re.findall(r'HTTP/1.1" 500 ',raw) and json.loads(control.read_text())['remaining']==0
        proof=dict(site=SITE,stage='Final bundle: local progress regression after first restore',mutations_by_inspector=False,fixture_origin='Pages UI only',
            operation_counts=counts,booking=dict(name=booking.name,status=booking.status,amount=0),transport_events=events,
            first_items_receipt='page-activity-items-ui.json',first_restore_receipt='page-activity-first-ux-restored.json')
        (ROOT/'docs/evidence/page-activity-final-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
else:
    import frappe
    from hospitality_suite.time import local
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator');prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        shifts=frappe.get_all('HS Shift',fields=['name','status','cashier','opening_amount','counted_amount','difference'])
        assert len(shifts)==1 and all(row.status=='Closed' and row.cashier=='cashier@hospitality.example.invalid' and row.opening_amount==row.counted_amount==row.difference==0 for row in shifts)
        counts={dt:frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Charge','HS Payment','Sales Invoice','Payment Entry','Journal Entry')}
        assert counts=={'HS Booking':1,'HS Stay':0,'HS Charge':0,'HS Payment':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0}
        booking=frappe.get_doc('HS Booking',frappe.db.get_value('HS Booking',{'property':prop.name}))
        assert booking.owner=='receptionist@hospitality.example.invalid' and booking.status=='Confirmed' and len(booking.rooms)==1 and booking.amount==1500
        assert local(booking.starts_at,prop).isoformat()=='2026-10-25T14:00:00-06:00' and local(booking.ends_at,prop).isoformat()=='2026-10-26T12:00:00-06:00'
        assert frappe.db.get_value('HS Room',booking.rooms[0].room,'room_number')=='H101' and booking.rooms[0].people==2
        assert str(prop.business_date)=='2026-10-19'
        raw=log.read_text();events=[json.loads(line.split('SYNTHETIC_TRANSPORT ',1)[1]) for line in raw.splitlines() if line.startswith('SYNTHETIC_TRANSPORT ')]
        assert json.loads(control.read_text())['remaining']==0
        assert [event['mode'] for event in events]==['slow-bootstrap']*3+['slow-booking','failed-bootstrap']
        http=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',raw)
        statuses={name:re.findall(r'"POST /api/method/'+re.escape(name)+r' HTTP/1.1" (\d+)',http) for name in ['hospitality_suite.api.execute','hospitality_suite.api.booking_detail','hospitality_suite.api.bootstrap','logout']}
        assert statuses['hospitality_suite.api.execute']==['200']*3 and statuses['hospitality_suite.api.booking_detail']==['200'] and statuses['logout']==['200']*2
        assert statuses['hospitality_suite.api.bootstrap'].count('503')==1 and set(statuses['hospitality_suite.api.bootstrap'])=={'200','503'}
        assert not re.findall(r'HTTP/1.1" 500 ',http)
        proof=dict(site=SITE,synthetic_transport=True,native_application=True,core_files_modified=False,mutations_by_inspector=False,fixture_origin='Pages UI only',
            shifts=shifts,operation_counts=counts,booking=dict(name=booking.name,status=booking.status,room='H101',amount=1500),transport_events=events,http_statuses=statuses,http_500=0,business_date='2026-10-19')
        (ROOT/'docs/evidence/page-activity-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof,ensure_ascii=False,default=str))
    finally:frappe.db.rollback();frappe.destroy()
