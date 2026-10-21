"""Backed-up acceptance fixture for pending-work review; never confirms the day."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import uuid

BENCH=Path('/home/frappe/benches/hospitality-bench');ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-closing-checks-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-closing-checks-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/closing-checks-web.pid';log=pidfile.with_suffix('.log')
    if args.action=='start':
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
        with log.open('ab') as stream:
            log.chmod(0o600)
            process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
        pidfile.write_text(str(process.pid));print('Acceptance Page server started on 8089')
    elif pidfile.exists():
        path=Path('/proc')/pidfile.read_text().strip()
        if path.exists():
            cmd=(path/'cmdline').read_bytes().decode(errors='replace');assert SITE in cmd and 'serve' in cmd and '8089' in cmd
            assert (path/'cwd').resolve() in (BENCH,BENCH/'sites');os.kill(int(path.name),signal.SIGTERM)
        print('Temporary Page server stopped')
else:
    import frappe
    from frappe.utils import now_datetime
    from hospitality_suite import api
    from hospitality_suite.service import canonical
    from hospitality_suite.time import business_window
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-closing-checks-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Daily Close')
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});before=snapshot();window=business_window(prop)
            rooms=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number','category'],order_by='room_number');guest=frappe.get_doc('HS Guest',{'property':prop.name})
            call=lambda action,data:api.execute(prop.name,action,uuid.uuid4().hex,data)
            def reserve(indices,start):
                values=dict(starts_at=str(start),ends_at=str(now_datetime().replace(microsecond=0)+timedelta(days=2)),guest=guest.name,customer=guest.customer,rooms=[dict(room=rooms[n].name,category=rooms[n].category,people=1) for n in indices])
                values['acceptance']=api.preview(prop.name,values)['acceptance'];return call('reserve',values)['booking']
            partial=reserve([0,1],window['ends_at']-timedelta(hours=1));booking=frappe.get_doc('HS Booking',partial)
            allocation=frappe.db.get_value('HS Allocation',{'booking':partial,'kind':'Reservation','status':'Active','room':rooms[0].name},'name')
            entered=call('check_in',dict(booking=partial,modified=str(booking.modified),allocation=allocation,guest=guest.name,room=rooms[0].name))
            confirmed=reserve([2],window['ends_at']-timedelta(minutes=30));next_day=reserve([3],window['ends_at']+timedelta(hours=2))
            frappe.set_user('manager@hospitality.example.invalid');shift=call('open_shift',dict(opening_amount=0))['shift']
            frappe.db.commit();state=dict(property=prop.name,business_date=str(prop.business_date),partial=partial,confirmed=confirmed,next_day=next_day,stay=entered['stay'],shift=shift,before=before,fixture=snapshot())
            STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,synthetic_api_fixture=True,business_date=state['business_date'],pending_arrival_rooms=['H102','H103'],next_day_room_excluded='H104',pending_charge_room='H101',open_shifts=1,invoices=0,payments=0)))
        else:
            state=json.loads(STATE.read_text());actual=snapshot();changed={dt for dt in actual if actual[dt]!=state['fixture'][dt]}
            assert changed=={'HS Daily Close','HS Audit Event','HS Request'},changed
            assert actual['Version']==state['fixture']['Version']
            close=frappe.get_doc('HS Daily Close',{'property':state['property'],'business_date':state['business_date']});groups=frappe.parse_json(close.blockers)
            arrivals=next(g for g in groups if g['type']=='Llegadas pendientes');assert set(arrivals['documents'])=={state['partial'],state['confirmed']}
            assert state['next_day'] not in arrivals['documents']
            assert close.status=='Review' and close.modified_by=='manager@hospitality.example.invalid'
            assert str(frappe.db.get_value('HS Property',state['property'],'business_date'))==state['business_date']
            assert not frappe.db.exists('HS Audit Event',{'property':state['property'],'action':'Daily close Closed'})
            labels=frappe.parse_json(close.summary)['close_review'];assert labels['business_date']==state['business_date']
            assert {g['type'] for g in groups}=={'Llegadas pendientes','Turnos sin cerrar','Cargos sin facturar'}
            for group in groups:
                assert group['hint'] and len(group['documents'])==len(group['items'])
                assert all(row['name'] not in row['label'] for row in group['items'])
            proof=dict(site=SITE,synthetic_api_fixture=True,manager_prepared_and_consulted_page=True,not_confirmed=True,business_date=state['business_date'],pending_types=[g['type'] for g in groups],pending_arrival_rooms=['H102','H103'],next_day_arrival_excluded=True,
                readable_frozen_items=True,close_status=close.status,unchanged_tables=len(actual)-len(changed),changed_tables=sorted(changed),all_native_tables_unchanged=True,operational_date_unchanged=True)
            (ROOT/'docs/evidence/closing-checks-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
