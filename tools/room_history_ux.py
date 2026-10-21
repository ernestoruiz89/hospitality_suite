"""Guarded real-command fixture for the room history Page; restore its original backup."""
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
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-room-history-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-room-history-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/room-history-web.pid';log=pidfile.with_suffix('.log')
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
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-room-history-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Stay')
            before=snapshot();baseline=json.loads((BENCH/'.hospitality-room-history-upgrade.json').read_text())[SITE]['tables']
            assert all(before[dt]=={key:baseline[dt][key] for key in ('rows','sha256')} for dt in names)
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
            rooms=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number','category'],order_by='room_number')
            guest=frappe.get_doc('HS Guest',{'property':prop.name});now=now_datetime().replace(microsecond=0)
            call=lambda action,data:api.execute(prop.name,action,uuid.uuid4().hex,data)
            def reserve(index,enter=False):
                values=dict(starts_at=str(now),ends_at=str(now+timedelta(days=2)),guest=guest.name,customer=guest.customer,rooms=[dict(room=rooms[index].name,category=rooms[index].category,people=1)])
                values['acceptance']=api.preview(prop.name,values)['acceptance'];return call('walk_in' if enter else 'reserve',values)
            reserved=reserve(0);booking=frappe.get_doc('HS Booking',reserved['booking'])
            values=dict(booking=booking.name,modified=str(booking.modified),rooms=[dict(room=rooms[1].name,category=rooms[1].category,people=1)],reason='Cambio solicitado a habitación H102')
            values['acceptance']=api.preview(prop.name,values,'modify_reservation')['acceptance'];call('modify_reservation',values)
            booking.reload();call('booking_status',dict(booking=booking.name,modified=str(booking.modified),status='Cancelled',reason='Cancelación de ejemplo para revisar el historial'))
            entered=reserve(2,True);stay=frappe.get_doc('HS Stay',entered['stay'])
            values=dict(stay=stay.name,folio=entered['folio'],room=rooms[3].name,modified=str(stay.modified),reason='Cambio de H103 a H104 solicitado por el huésped')
            values['acceptance']=api.preview(prop.name,values,'change_room')['acceptance'];call('change_room',values)
            task=frappe.get_doc('HS Cleaning Task',{'room':rooms[2].name,'status':'Pending'})
            for status in ('In Progress','Inspection','Completed'):
                task.reload();call('cleaning',dict(task=task.name,modified=str(task.modified),status=status,checklist={key:True for key in ('baño','cama','minibar','superficies')},notes='Habitación revisada para el historial de ejemplo'))
            closed=call('maintenance',dict(room=rooms[4].name,title='Revisión de aire acondicionado',starts_at=str(now-timedelta(hours=2)),until_reopened=1))
            order=frappe.get_doc('HS Maintenance Order',closed['order']);call('maintenance',dict(order=order.name,modified=str(order.modified),status='Completed'))
            call('maintenance',dict(room=rooms[5].name,title='Bloqueo hasta revisión de instalaciones',starts_at=str(now-timedelta(hours=1)),until_reopened=1))
            # Actual native saves, not fabricated Version rows, exercise the UI pager.
            room=frappe.get_doc('HS Room',rooms[8].name);room.room_number='H109A';room.save()
            for index in range(28):room.floor=str(index%3+1);room.save()
            query=dict(property_name=prop.name,starts_at=str(now-timedelta(days=1)),ends_at=str(now+timedelta(days=3)),view='all',page_length=200)
            histories={r.room_number:api.room_history(room=r.name,**query) for r in rooms}
            assert any(r['title']=='Reserva cancelada' for r in histories['H102']['rows'])
            assert any(r['title']=='Cambio de habitación' for r in histories['H103']['rows'])
            assert 'En limpieza' in canonical(histories['H103']) and 'Limpia' in canonical(histories['H103'])
            assert any(r['kind']=='period' and r['ends_at'] for r in histories['H105']['rows'])
            assert any(r['kind']=='period' and r['ends_at'] is None for r in histories['H106']['rows'])
            assert histories['H109']['total']>50
            state=dict(property=prop.name,business_date=str(prop.business_date),query=query,rooms={r.room_number:r.name for r in rooms},before=before,fixture=snapshot(),totals={key:row['total'] for key,row in histories.items()})
            frappe.db.commit();STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,real_commands=True,totals=state['totals'])))
        else:
            state=json.loads(STATE.read_text());actual=snapshot();assert actual==state['fixture'],'La consulta modificó tablas de negocio'
            assert str(frappe.db.get_value('HS Property',state['property'],'business_date'))==state['business_date']
            assert all(actual[dt]==state['before'][dt] for dt in names if dt not in {'Version'} and not dt.startswith('HS '))
            proof=dict(site=SITE,real_native_command_fixture=True,ui_operations_read_only=True,unchanged_tables=len(names),all_native_tables_unchanged=True,business_date_unchanged=True,history_counts=state['totals'])
            (ROOT/'docs/evidence/room-history-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
