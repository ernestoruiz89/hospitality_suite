"""Explicit, reversible Home/filter fixture on the designated acceptance site."""
import argparse
from datetime import datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import uuid

BENCH=Path('/home/frappe/benches/hospitality-bench');ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-navigation-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-navigation-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/navigation-web.pid';log=pidfile.with_suffix('.log')
    if args.action=='start':
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
        with log.open('ab') as stream:
            log.chmod(0o600)
            process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
        pidfile.write_text(str(process.pid));print('Acceptance Page server started on 8089')
    elif pidfile.exists():
        process_path=Path('/proc')/pidfile.read_text().strip()
        if process_path.exists():
            cmd=(process_path/'cmdline').read_bytes().decode(errors='replace');assert SITE in cmd and 'serve' in cmd and '8089' in cmd
            assert (process_path/'cwd').resolve() in (BENCH,BENCH/'sites');os.kill(int(process_path.name),signal.SIGTERM)
        print('Temporary Page server stopped')
else:
    import frappe
    from frappe.utils import now_datetime
    from hospitality_suite import api
    from hospitality_suite.service import canonical
    from hospitality_suite.time import now_local, to_site
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-navigation-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Stay')
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});before=snapshot()
            rooms=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number','category'],order_by='room_number')
            guest=frappe.get_doc('HS Guest',{'property':prop.name});now=now_datetime().replace(microsecond=0);day=now_local(prop).date()
            suite=frappe.copy_doc(frappe.get_doc('HS Category',rooms[0].category));suite.category_name='Suite UX';suite.insert()
            rate=frappe.copy_doc(frappe.get_doc('HS Rate',{'property':prop.name,'category':rooms[0].category}));rate.category=suite.name;rate.title='Suite UX';rate.insert()
            for index,room in enumerate(rooms):
                category=suite.name if index in (1,3) else room.category
                frappe.db.set_value('HS Room',room.name,dict(floor='2' if index in (1,2,3) else '1',category=category,zone='Jardín' if index==1 else '',active=0 if index==5 else 1,cleaning_status='Dirty' if index==3 else 'Clean'))
                room.category=category
            other=frappe.get_doc('HS Property',{'mode':'Motel'})
            for room in frappe.get_all('HS Room',filters={'property':other.name},pluck='name'):frappe.db.set_value('HS Room',room,'floor','3')
            call=lambda action,data:api.execute(prop.name,action,uuid.uuid4().hex,data)
            call('schedule_cleaning',dict(room=rooms[3].name,kind='Deep',priority='Normal',notes='Fixture sintético de filtros'))
            def reserve(lines,start,end):
                values=dict(starts_at=str(start),ends_at=str(end),guest=guest.name,customer=guest.customer,rooms=lines)
                values['acceptance']=api.preview(prop.name,values)['acceptance'];return call('reserve',values)['booking']
            one=reserve([dict(room=rooms[0].name,category=rooms[0].category,people=1)],now-timedelta(minutes=30),to_site(datetime.combine(day,time(23,59,59)),prop))
            booking=frappe.get_doc('HS Booking',one);allocation=frappe.db.get_value('HS Allocation',{'booking':one,'kind':'Reservation','status':'Active','room':rooms[0].name},'name')
            stay=call('check_in',dict(booking=one,modified=str(booking.modified),allocation=allocation,guest=guest.name,room=rooms[0].name))['stay']
            starts=now+timedelta(minutes=10);ends=now+timedelta(days=2)
            arrivals=reserve([dict(room=rooms[1].name,category=suite.name,people=1),dict(category=rooms[2].category,people=1)],starts,ends)
            next_day=reserve([dict(room=rooms[2].name,category=rooms[2].category,people=1)],to_site(datetime.combine(day+timedelta(days=1),time(14)),prop),ends+timedelta(days=1))
            call('maintenance',dict(room=rooms[4].name,title='Bloqueo de prueba de Inicio',kind='Corrective',starts_at=str(now-timedelta(minutes=5)),until_reopened=1))
            frappe.set_user('manager@hospitality.example.invalid')
            board=api.stay_board(prop.name,date=str(day),view='arrivals',page_length=1)
            assert board['counts']==dict(hosted=1,arrivals=2,departures=1,accounts=1),board['counts']
            state=dict(property=prop.name,other_property=other.name,date=str(day),business_date=str(prop.business_date),stay=stay,arrivals=arrivals,next_day=next_day,counts=board['counts'],before=before,fixture=snapshot())
            frappe.db.commit();STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,synthetic_api_fixture=True,date=str(day),counts=board['counts'],matching_clean_suite='H102',blocked='H105',inactive='H106',dirty='H104')))
        else:
            state=json.loads(STATE.read_text());assert snapshot()==state['fixture'],'La consulta de interfaz modificó datos de negocio'
            frappe.set_user('manager@hospitality.example.invalid');board=api.stay_board(state['property'],date=state['date'],view='arrivals',page_length=25)
            assert board['counts']==state['counts'] and len(board['rows'])==2
            assert state['next_day'] not in [row['booking'] for row in board['rows']]
            assert any(not row['room'] for row in board['rows']) and any(row['room'] for row in board['rows'])
            assert str(frappe.db.get_value('HS Property',state['property'],'business_date'))==state['business_date']
            for dt in ('Sales Invoice','Payment Entry','Journal Entry','Stock Entry','GL Entry','Stock Ledger Entry'):assert snapshot()[dt]==state['before'][dt],dt
            proof=dict(site=SITE,synthetic_api_fixture=True,home_calendar_date=state['date'],counts=board['counts'],unassigned_arrival_included=True,next_day_excluded=True,
                ui_operations_read_only=True,unchanged_tables=len(names),business_date_unchanged=True,all_native_tables_unchanged=True)
            (ROOT/'docs/evidence/navigation-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
