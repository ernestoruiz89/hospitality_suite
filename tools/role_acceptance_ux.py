"""A real native demo plus an empty H101 for the combined-role Pages walkthrough."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import uuid

BENCH=Path('/home/frappe/benches/hospitality-bench');ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-role-acceptance-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-role-acceptance-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/role-acceptance-web.pid';log=pidfile.with_suffix('.log')
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
    from frappe.utils.password import update_password
    from hospitality_suite import api
    from hospitality_suite.demo_scenario import build
    from hospitality_suite.service import canonical
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-role-acceptance-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking') and not frappe.db.count('HS Stay')
            before=snapshot();baseline=json.loads((BENCH/'.hospitality-role-acceptance-upgrade.json').read_text())[SITE]['tables']
            assert all(before[dt]=={key:baseline[dt][key] for key in ('rows','sha256')} for dt in names)
            previous=frappe.conf.get('hospitality_allow_demo');frappe.conf.hospitality_allow_demo=True
            try:
                demo=build();first=snapshot();assert build()==demo and snapshot()==first
            finally:frappe.conf.hospitality_allow_demo=previous
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'})
            user='reception-cashier-demo@hospitality.example.invalid';password=secrets.token_urlsafe(30)
            assert not frappe.db.exists('User',user)
            previous_test=frappe.in_test;frappe.in_test=True
            try:api.execute(prop.name,'assign_user',uuid.uuid4().hex,dict(email=user,first_name='Recepción y caja de demostración',roles=['HS Receptionist','HS Cashier'],reason='Recorrido explícito de aceptación con ambos roles'))
            finally:frappe.in_test=previous_test
            update_password(user,password)
            assert not frappe.db.count('HS Booking',{'owner':user})
            state=dict(property=prop.name,room=room.name,user=user,password=password,business_date=str(prop.business_date),demo=demo,before=before,fixture=snapshot())
            frappe.db.commit();STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,demo_properties=2,demo_stays=2,demo_services=2,repeat_has_no_business_changes=True,combined_user_has_only_explicit_reception_and_cashier_roles=True,h101_empty_for_pages=True)))
        else:
            state=json.loads(STATE.read_text());actual=snapshot();user=state['user'];prop=state['property']
            assert frappe.db.count('HS Booking',{'owner':user})==1
            booking=frappe.get_doc('HS Booking',{'owner':user});stay=frappe.get_doc('HS Stay',{'booking':booking.name})
            assert booking.property==prop and stay.room==state['room'] and stay.status=='Checked Out'
            service=frappe.get_doc('HS Service Request',{'stay':stay.name});assert service.status=='Delivered' and service.stock_entry
            charges=frappe.get_all('HS Charge',filters={'stay':stay.name},fields=['amount','sales_invoice','status'])
            assert len(charges)==3 and sum(float(row.amount) for row in charges)==3030 and all(row.status=='Invoiced' for row in charges)
            invoices={row.sales_invoice for row in charges};assert len(invoices)==1
            invoice=frappe.get_doc('Sales Invoice',next(iter(invoices)));assert invoice.docstatus==1 and invoice.grand_total==3030 and invoice.outstanding_amount==0
            payment=frappe.get_doc('HS Payment',{'stay':stay.name});entry=frappe.get_doc('Payment Entry',payment.payment_entry)
            assert payment.owner==user and entry.docstatus==1 and entry.paid_amount==3030
            assert any(row.reference_name==invoice.name and row.allocated_amount==3030 for row in entry.references)
            shift=frappe.get_doc('HS Shift',payment.shift);assert shift.cashier==user and shift.status=='Closed' and shift.difference==0
            cleaning=frappe.get_doc('HS Cleaning Task',{'stay':stay.name});assert cleaning.status=='Completed' and cleaning.inspected_by=='supervisor@hospitality.example.invalid'
            assert frappe.db.get_value('HS Room',state['room'],'cleaning_status')=='Clean'
            assert 'HS Cashier' not in frappe.get_roles('receptionist@hospitality.example.invalid')
            reconciliation=api.report(prop,'Conciliación',dict(stay=stay.name));assert reconciliation and all(row['status']=='OK' for row in reconciliation)
            assert {invoice.name,entry.name}.issubset({row['erp_document'] for row in reconciliation})
            assert str(frappe.db.get_value('HS Property',prop,'business_date'))==state['business_date']
            # Repeat the explicit loader after real user work. It must preserve that work.
            old=frappe.conf.get('hospitality_allow_demo');frappe.conf.hospitality_allow_demo=True
            try:assert build()==state['demo'] and snapshot()==actual
            finally:frappe.conf.hospitality_allow_demo=old
            proof=dict(site=SITE,roles=['HS Receptionist + HS Cashier','HS Housekeeping','HS Supervisor','HS Accountant','HS Manager'],
                       preparation='Two fictional property scenarios and one explicitly combined operator; H101 operations are performed from Pages.',
                       demo_repeat_before_and_after_pages_unchanged=True,booking=booking.name,stay=stay.name,invoice=invoice.name,payment_entry=entry.name,
                       total=3030,outstanding=0,shift_difference=0,cleaning_completed_and_inspected=True,room_clean=True,reconciliation_all_ok=True,
                       receptionist_role_not_expanded=True,business_date_unchanged=True,
                       native_counts={dt:frappe.db.count(dt) for dt in ('Sales Invoice','Payment Entry','Stock Entry','GL Entry','Stock Ledger Entry')})
            (ROOT/'docs/evidence/role-acceptance-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
