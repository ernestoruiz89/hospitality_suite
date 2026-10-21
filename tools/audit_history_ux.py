"""Backed-up acceptance-only API fixture and checks for the real management Page."""
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
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-audit-history-ui-fixture-v2.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop','formats']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-audit-history-ux-baseline.json').is_file()
if args.action=='formats':
    import frappe
    source=json.loads((ROOT/'hospitality_suite/hospitality_suite/print_format/hs_daily_close/hs_daily_close.json').read_text())
    os.chdir(BENCH/'sites');proof=dict(format=source['name'],html_sha256=hashlib.sha256(source['html'].encode()).hexdigest(),sites={})
    for site,database in (('hospitality.localhost','hospitality_dev'),(SITE,'hospitality_acceptance')):
        frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
        try:
            assert frappe.conf.db_name==database
            assert frappe.db.get_value('Print Format',source['name'],'html')==source['html']
            proof['sites'][site]=dict(installed_matches_source=True,mutations=False)
        finally:frappe.db.rollback();frappe.destroy()
    (ROOT/'docs/evidence/audit-history-installed.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
elif args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/audit-history-web.pid';log=pidfile.with_suffix('.log')
    if args.action=='start':
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
        with log.open('ab') as stream:
            log.chmod(0o600)
            process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,
                stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
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
    from hospitality_suite.service import operation,insert,canonical
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-audit-history-upgrade.json').read_text())[SITE]['tables']
        def snapshot():
            return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Daily Close')
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});before=snapshot()
            rate=frappe.get_doc('HS Rate',{'property':prop.name,'mode':'Hotel'});rate.amount=1800;rate.change_reason='Temporada de prueba revisada por gerencia';rate.save()
            rate_event=frappe.db.get_value('HS Audit Event',{'source_name':rate.name,'action':'Rate changed'})
            guest=frappe.get_doc('HS Guest',{'property':prop.name});room=frappe.get_doc('HS Room',{'property':prop.name});start=now_datetime().replace(microsecond=0)+timedelta(days=2)
            values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,rooms=[dict(category=room.category,room=room.name,people=1)])
            frappe.set_user('receptionist@hospitality.example.invalid');values['acceptance']=api.preview(prop.name,values)['acceptance']
            name=api.execute(prop.name,'reserve',uuid.uuid4().hex,values)['booking'];doc=frappe.get_doc('HS Booking',name)
            api.execute(prop.name,'booking_status',uuid.uuid4().hex,dict(booking=name,modified=str(doc.modified),status='Cancelled',reason='Solicitud del cliente de prueba, sin penalización'))
            frappe.set_user('Administrator')
            with operation(prop):
                old=insert('HS Audit Event',prop,action='Legacy record',source_doctype='HS Property',source_name=prop.name,actor='Administrator',
                    occurred_at=now_datetime(),business_date=prop.business_date,reason='Registro anterior sin desglose',details='{}')
            frappe.db.commit();state=dict(property=prop.name,business_date=str(prop.business_date),rate_event=rate_event,legacy_event=old.name,before=before,fixture=snapshot())
            STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,api_fixture=True,rate_before='1500.00',rate_after='1800.00',cancelled_bookings=1,financial_operations=0)))
        else:
            state=json.loads(STATE.read_text());actual=snapshot()
            changed=[dt for dt in actual if actual[dt]!=state['fixture'][dt]]
            assert set(changed)=={'HS Property','HS Daily Close','HS Audit Event','HS Request','Version'},changed
            prop=frappe.get_doc('HS Property',state['property']);close=frappe.get_doc('HS Daily Close',{'property':prop.name,'business_date':state['business_date']})
            assert close.status=='Closed' and str(prop.business_date)==str(frappe.utils.add_days(state['business_date'],1))
            review=frappe.parse_json(close.summary)['audit_review'];assert len(review['rows'])==2
            assert {'Tarifa modificada','Reserva cancelada'}=={row['action'] for row in review['rows']}
            assert close.modified_by=='manager@hospitality.example.invalid'
            events=frappe.get_all('HS Audit Event',filters={'property':prop.name,'source_name':close.name},fields=['action','actor','business_date'])
            assert {'Daily close Review','Daily close Closed'}=={row.action for row in events}
            assert all(row.actor=='manager@hospitality.example.invalid' and str(row.business_date)==state['business_date'] for row in events)
            operational_types=('HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry','Stock Entry')
            added={dt:frappe.db.count(dt)-state['fixture'][dt]['rows'] for dt in operational_types}
            assert not any(added.values()),added
            proof=dict(site=SITE,synthetic_api_fixture=True,manager_prepared_and_closed_from_page=True,operational_date_before=state['business_date'],operational_date_after=str(prop.business_date),
                captured_exception_events=2,close_status=close.status,unchanged_tables=len(actual)-len(changed),changed_tables=changed,
                fixture_run=2,financial_and_stock_operations_added=added,opening_stock_entries_preserved=state['fixture']['Stock Entry']['rows'],api_fixture_rate_detail=api.audit_detail(prop.name,state['rate_event']),
                historical_entry_has_no_values=not api.audit_detail(prop.name,state['legacy_event'])['historical_values_available'])
            (ROOT/'docs/evidence/audit-history-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
            print(json.dumps({key:value for key,value in proof.items() if key!='api_fixture_rate_detail'},ensure_ascii=False))
    finally:frappe.db.rollback();frappe.destroy()
