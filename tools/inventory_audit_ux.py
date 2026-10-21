"""Synthetic acceptance-only fixture; Page actions and native preservation stay separate."""
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
SITE='hospitality-acceptance.localhost';STATE=BENCH/'.hospitality-inventory-audit-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-inventory-audit-ux-baseline.json').is_file()
if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/inventory-audit-web.pid';log=pidfile.with_suffix('.log')
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
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        names=json.loads((BENCH/'.hospitality-inventory-audit-upgrade.json').read_text())[SITE]['tables']
        def snapshot():return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest()) for dt in names}
        if args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Stay')
            prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});before=snapshot()
            call=lambda action,data:api.execute(prop.name,action,uuid.uuid4().hex,data)
            floor=call('create_warehouse',dict(warehouse_name='Piso de prueba de inventario'))['warehouse']
            for wh,minimum in ((prop.warehouse,120),(floor,4)):
                call('stock_policy',dict(item='HS-DEMO-WATER',warehouse=wh,purpose='Merchandise',minimum=minimum,reorder_quantity=8))
            transfer=call('move_stock',dict(item='HS-DEMO-WATER',quantity=2,purpose='Transfer',source_warehouse=prop.warehouse,target_warehouse=floor,reason='Fixture API explícito: dos unidades en piso'))['stock_entry']
            room=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number','category'],order_by='room_number')[0]
            guest=frappe.get_doc('HS Guest',{'property':prop.name});start=now_datetime().replace(microsecond=0)
            values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
            values['acceptance']=api.preview(prop.name,values)['acceptance'];stay=call('walk_in',values)
            service=call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item='HS-DEMO-WATER',quantity=2))['service']
            frappe.db.commit();state=dict(property=prop.name,room=room.room_number,service=service,stay=stay['stay'],floor=floor,warehouse=prop.warehouse,transfer=transfer,before=before,fixture=snapshot())
            STATE.write_text(json.dumps(state));STATE.chmod(0o600)
            print(json.dumps(dict(prepared=True,synthetic_api_fixture=True,room=room.room_number,requested_quantity=2,main_water=98,floor_water=2,minimums=[120,4],invoices=0,payments=0)))
        else:
            state=json.loads(STATE.read_text());actual=snapshot();changed={dt for dt in actual if actual[dt]!=state['fixture'][dt]}
            allowed={'HS Service Request','HS Charge','HS Audit Event','HS Request','Stock Entry','Stock Entry Detail','Stock Ledger Entry','GL Entry','Bin','Version'}
            assert changed<=allowed,changed-allowed
            service=frappe.get_doc('HS Service Request',state['service']);assert service.status=='Returned'
            assert frappe.db.get_value('HS Charge',service.charge,'status')=='Reversed'
            entry=frappe.get_doc('Stock Entry',service.stock_entry);assert entry.docstatus==2 and entry.hs_stock_purpose=='Sale'
            assert entry.owner=='manager@hospitality.example.invalid'
            actions=frappe.get_all('HS Audit Event',filters={'source_name':service.name},fields=['action','actor'])
            statuses=[r for r in actions if r.action in ('Service In Progress','Service Delivered','Service Returned')]
            assert len(statuses)==3 and all(r.actor=='manager@hospitality.example.invalid' for r in statuses)
            stock={wh:frappe.db.get_value('Bin',{'item_code':'HS-DEMO-WATER','warehouse':wh},'actual_qty') for wh in (state['warehouse'],state['floor'])}
            assert stock=={state['warehouse']:98,state['floor']:2},stock
            forbidden=('Sales Invoice','Payment Entry','Journal Entry','Purchase Order','Purchase Receipt','Purchase Invoice','HS Property','Company')
            assert all(actual[dt]==state['fixture'][dt] for dt in forbidden)
            proof=dict(site=SITE,synthetic_api_fixture=True,manager_page_states=['In Progress','Delivered','Returned'],room=state['room'],quantity=2,native_issue_status=entry.docstatus,pending_service_charge_reversed=True,
                main_water=98,floor_water=2,unchanged_tables=len(actual)-len(changed),changed_tables=sorted(changed),financial_and_purchase_tables_unchanged=True,installed_apps=frappe.get_installed_apps(),read_only_inventory_queries=True)
            (ROOT/'docs/evidence/inventory-audit-items-ui.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
