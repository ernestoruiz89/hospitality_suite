"""Explicit, reversible current/interval room-state acceptance fixture."""
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
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-room-states-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-room-states-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/room-states-web.pid';log=pidfile.with_suffix('.log')
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
        names=json.loads((BENCH/'.hospitality-room-states-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Stay')
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});before=snapshot()
            baseline=json.loads((BENCH/'.hospitality-room-states-upgrade.json').read_text())[SITE]['tables']
            assert all(before[dt]=={key:baseline[dt][key] for key in ('rows','sha256')} for dt in names)
            rooms=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number','category'],order_by='room_number')
            guest=frappe.get_doc('HS Guest',{'property':prop.name});now=now_datetime().replace(microsecond=0)
            call=lambda action,data:api.execute(prop.name,action,uuid.uuid4().hex,data)
            def reserve(index,enter=False,end=None):
                values=dict(starts_at=str(now-timedelta(minutes=30)),ends_at=str(end or now+timedelta(days=2)),guest=guest.name,customer=guest.customer,
                            rooms=[dict(room=rooms[index].name,category=rooms[index].category,people=1)])
                values['acceptance']=api.preview(prop.name,values)['acceptance']
                return call('walk_in' if enter else 'reserve',values)
            near=reserve(0,enter=True,end=now+timedelta(minutes=30));reserved=reserve(1)
            late=reserve(9,enter=True,end=now+timedelta(minutes=30))
            # Synthetic historical clock fixture; the UI does not create or alter this stay.
            frappe.db.set_value('HS Stay',late['stay'],dict(ends_at=now-timedelta(minutes=5),actual_check_in=now-timedelta(minutes=30)))
            for allocation in frappe.get_all('HS Allocation',filters={'stay':late['stay'],'kind':'Stay','status':'Active'},pluck='name'):
                frappe.db.set_value('HS Allocation',allocation,'ends_at',now-timedelta(minutes=5))
            call('maintenance',dict(room=rooms[2].name,title='Fuera de servicio para contraste de estados',starts_at=str(now-timedelta(minutes=5)),until_reopened=1))
            inactive=frappe.get_doc('HS Room',rooms[3].name);inactive.active=0;inactive.save()
            for index in (4,5,6):
                task=call('schedule_cleaning',dict(room=rooms[index].name,kind='Deep',priority='Normal',notes='Estado sintético para revisar la interfaz'))['task']
                if index>=5:
                    doc=frappe.get_doc('HS Cleaning Task',task);call('cleaning',dict(task=task,modified=str(doc.modified),status='In Progress'))
                if index==6:
                    doc=frappe.get_doc('HS Cleaning Task',task);call('cleaning',dict(task=task,modified=str(doc.modified),status='Inspection',checklist={key:True for key in ('baño','cama','minibar','superficies')}))
            query=dict(property_name=prop.name,category=rooms[0].category,starts_at=str(now),ends_at=str(now+timedelta(days=1)),people=1,quantity=1)
            result=api.availability_search(**query);states={row['room_number']:row for row in result['room_states']}
            assert result['available']==5 and result['physical_available']==5
            expected={'H101':'Occupied','H102':'Reserved','H103':'Blocked','H104':'Inactive','H105':'Available','H106':'Available','H107':'Available','H108':'Available','H109':'Available','H110':'Occupied'}
            assert {number:row['status'] for number,row in states.items()}==expected
            assert [states[number]['cleaning_status'] for number in ('H105','H106','H107')]==['Dirty','Cleaning','Inspection']
            state=dict(property=prop.name,category=rooms[0].category,near_stay=near['stay'],late_stay=late['stay'],reserved=reserved['booking'],business_date=str(prop.business_date),
                       query=query,expected=expected,before=before,fixture=snapshot())
            frappe.db.commit();STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,synthetic_api_fixture=True,synthetic_overdue_timestamps=True,physical_available=5,states=expected,cleaning_states=['Dirty','Cleaning','Inspection'])))
        else:
            state=json.loads(STATE.read_text());actual=snapshot();assert actual==state['fixture'],'La consulta modificó tablas de negocio'
            result=api.availability_search(**state['query']);assert {row['room_number']:row['status'] for row in result['room_states']}==state['expected']
            assert not any(set(row)-{'name','room_number','status','label','cleaning_status'} for row in result['room_states'])
            assert str(frappe.db.get_value('HS Property',state['property'],'business_date'))==state['business_date']
            native=['Sales Invoice','Payment Entry','Journal Entry','Stock Entry','GL Entry','Stock Ledger Entry']
            assert all(actual[dt]==state['before'][dt] for dt in native)
            proof=dict(site=SITE,synthetic_api_fixture=True,overdue_timestamps_are_fixture=True,ui_operations_read_only=True,unchanged_tables=len(names),states=state['expected'],
                       physical_available=5,cleaning_states=['Dirty','Cleaning','Inspection'],all_native_tables_unchanged=True,business_date_unchanged=True)
            (ROOT/'docs/evidence/room-states-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
