"""Guarded acceptance server and read-only inspection of the keyboard walkthrough."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
ROOT=Path(__file__).resolve().parents[1];STATE=BENCH/'.hospitality-keyboard-review-ui-scenario.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','begin','inspect','checkpoint']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-keyboard-review-ux-baseline.json').is_file()
pidfile=BENCH/'.hospitality-run/keyboard-review-web.pid';log=pidfile.with_suffix('.log')
if args.action=='checkpoint':
    # A read-only checkpoint before the financial/operational walkthrough.
    # It cannot be presented as the final restoration proof.
    import frappe
    from hospitality_suite.service import canonical
    baseline=json.loads((BENCH/'.hospitality-keyboard-review-upgrade.json').read_text())
    proof=dict(stage='Keyboard walkthrough incomplete; acceptance not restored.',mutations=False,sites={})
    os.chdir(BENCH/'sites')
    for site,database in [('hospitality.localhost','hospitality_dev'),(SITE,'hospitality_acceptance')]:
        frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
        try:
            assert frappe.conf.db_name==database and frappe.conf.allow_tests
            if site==SITE:assert frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
            frappe.set_user('Administrator');current={}
            for dt,expected in baseline[site]['tables'].items():
                assert all(name.replace('_','').isalnum() for name in expected['columns'])
                rows=frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in expected['columns'])+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
                current[dt]=dict(rows=len(rows),sha256=hashlib.sha256(canonical(rows).encode()).hexdigest())
            changes={dt:dict(before=expected['rows'],after=current[dt]['rows']) for dt,expected in baseline[site]['tables'].items() if current[dt]!={key:expected[key] for key in ('rows','sha256')}}
            private={}
            for name in frappe.get_all('File',filters={'is_private':1,'is_folder':0},pluck='name'):
                path=Path(frappe.get_doc('File',name).get_full_path()).resolve()
                assert path.is_relative_to(Path(frappe.get_site_path('private','files')).resolve())
                private[name]=hashlib.sha256(path.read_bytes()).hexdigest()
            assert private==baseline[site]['private_files']
            date=str(frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'},'business_date'));assert date=='2026-10-19'
            if site=='hospitality.localhost':assert not changes,changes
            native=[dt for dt in current if not dt.startswith('HS ') and dt!='Version']
            assert not set(native).intersection(changes),changes
            counts={dt:frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Shift','Sales Invoice','Payment Entry','Journal Entry')}
            if site==SITE:assert not any(counts.values()),counts
            proof['sites'][site]=dict(tables_checked=len(current),rows=sum(row['rows'] for row in current.values()),changed_tables=changes,
                unchanged_native_business_tables=len(native),private_files_preserved=len(private),business_date=date,operation_counts=counts)
        finally:frappe.db.rollback();frappe.destroy()
    listeners=subprocess.check_output(['ss','-ltn'],text=True)
    proof['ports']={str(port):':'+str(port)+' ' in listeners for port in (8086,8089,9001,11001,13001)}
    assert all(proof['ports'].values())
    (ROOT/'docs/evidence/keyboard-review-checkpoint.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))
elif args.action in ('begin','inspect'):
    import frappe
    from hospitality_suite.schema import SCHEMA
    from hospitality_suite.service import canonical
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        baseline=json.loads((BENCH/'.hospitality-keyboard-review-upgrade.json').read_text())[SITE]['tables']
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        def snapshot():
            result={}
            for dt,entry in baseline.items():
                rows=frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in entry['columns'])+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
                result[dt]=dict(rows=len(rows),sha256=hashlib.sha256(canonical(rows).encode()).hexdigest())
            return result
        if args.action=='begin':
            assert not STATE.exists(),'Conserve el escenario original'
            actual=snapshot();assert all(actual[dt]=={key:entry[key] for key in ('rows','sha256')} for dt,entry in baseline.items())
            assert all(not frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Shift','HS Cleaning Task','HS Maintenance Order'))
            state=dict(property=prop.name,business_date=str(prop.business_date),before=actual,
                baseline_native_counts={dt:frappe.db.count(dt) for dt in ('Stock Entry','GL Entry','Stock Ledger Entry','Sales Invoice','Payment Entry')})
            STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print('Original baseline recorded. All scenario operations must be performed from Pages.')
        else:
            state=json.loads(STATE.read_text());assert prop.name==state['property'] and str(prop.business_date)==state['business_date']
            guest=frappe.get_doc('HS Guest',{'property':prop.name,'full_name':'Visita teclado'})
            assert guest.owner=='receptionist@hospitality.example.invalid'
            category=frappe.get_doc('HS Category',{'property':prop.name,'category_name':'Categoría teclado'})
            assert category.owner=='administrator@hospitality.example.invalid'
            rate=frappe.get_doc('HS Rate',{'property':prop.name,'title':'Tarifa teclado'})
            assert rate.owner==category.owner and rate.amount==900
            assert sorted((row.item,float(row.quantity),row.basis) for row in rate.included_services)==[('HS-DEMO-EXTRA-HOUR',1.0,'Stay'),('HS-DEMO-WATER',2.0,'Night')]
            assert frappe.db.count('HS Rate',{'property':prop.name})==2,'The mobile draft must remain unsaved'
            assert frappe.db.count('HS Portal Request',{'property':prop.name})==0,'Portal review quotes only; no request was sent'
            booking=frappe.get_doc('HS Booking',{'property':prop.name,'guest':guest.name});assert booking.owner==guest.owner
            stay=frappe.get_doc('HS Stay',{'booking':booking.name});assert stay.status=='Checked Out'
            assert frappe.db.get_value('HS Room',stay.room,'room_number')=='H101'
            service=frappe.get_doc('HS Service Request',{'stay':stay.name});assert service.item=='HS-DEMO-WATER' and service.quantity==1 and service.status=='Delivered' and service.stock_entry
            charges=frappe.get_all('HS Charge',filters={'stay':stay.name},fields=['amount','status','sales_invoice'])
            assert len(charges)==2 and sum(float(row.amount) for row in charges)==1530 and all(row.status=='Invoiced' for row in charges)
            invoices={row.sales_invoice for row in charges};assert len(invoices)==1
            invoice=frappe.get_doc('Sales Invoice',next(iter(invoices)));assert invoice.docstatus==1 and invoice.grand_total==1530 and invoice.outstanding_amount==0
            payment=frappe.get_doc('HS Payment',{'stay':stay.name});entry=frappe.get_doc('Payment Entry',payment.payment_entry)
            assert payment.owner=='cashier@hospitality.example.invalid' and entry.docstatus==1 and entry.paid_amount==1530
            assert any(row.reference_name==invoice.name and row.allocated_amount==1530 for row in entry.references)
            shift=frappe.get_doc('HS Shift',payment.shift);assert shift.cashier==payment.owner and shift.status=='Closed' and shift.difference==0 and shift.counted_amount==1530
            cleaning=frappe.get_doc('HS Cleaning Task',{'stay':stay.name});assert cleaning.status=='Completed' and cleaning.inspected_by=='supervisor@hospitality.example.invalid'
            assert frappe.db.get_value('HS Room',stay.room,'cleaning_status')=='Clean'
            maintenance=frappe.get_doc('HS Maintenance Order',{'property':prop.name,'title':'Revisión por teclado'})
            assert maintenance.owner=='maintenance@hospitality.example.invalid' and maintenance.status=='Completed' and maintenance.reopened_by=='supervisor@hospitality.example.invalid'
            assert frappe.db.get_value('HS Room',maintenance.room,'room_number')=='H102'
            assert 'HS Cashier' not in frappe.get_roles(guest.owner)
            from hospitality_suite import api
            reconciliation=api.report(prop.name,'Conciliación',dict(stay=stay.name));assert reconciliation and all(row['status']=='OK' for row in reconciliation)
            counts={dt:frappe.db.count(dt) for dt in state['baseline_native_counts']}
            assert counts['Sales Invoice']==counts['Payment Entry']==1
            assert counts['Stock Entry']==state['baseline_native_counts']['Stock Entry']+1
            assert counts['Stock Ledger Entry']==state['baseline_native_counts']['Stock Ledger Entry']+1
            proof=dict(site=SITE,preparation='Original baseline only; no API-created operational fixtures.',
                category=category.name,rate=rate.name,rate_amount=900,rate_services=2,mobile_rate_draft_unsaved=True,portal_requests_sent=0,
                guest=guest.name,booking=booking.name,stay=stay.name,invoice=invoice.name,payment_entry=entry.name,
                total=1530,outstanding=0,shift_difference=0,cleaning_inspected=True,maintenance_reopened_by_supervisor=True,
                receptionist_cashier_permissions_separate=True,native_counts=counts,business_date_unchanged=True,
                browser_evidence='keyboard-review-roles-ui.json',mutations_by_inspector=False)
            (ROOT/'docs/evidence/keyboard-review-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
elif args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Acceptance keyboard review server started on 8089')
elif pidfile.exists():
    process_path=Path('/proc')/pidfile.read_text().strip()
    if process_path.exists():
        command=(process_path/'cmdline').read_bytes().decode(errors='replace')
        assert SITE in command and 'serve' in command and '8089' in command
        assert (process_path/'cwd').resolve() in (BENCH,BENCH/'sites')
        os.kill(int(process_path.name),signal.SIGTERM)
    print('Temporary keyboard review server stopped')
