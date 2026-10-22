"""One native H101 fixture; prove the panel review never posts a business operation."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
TARGET=BENCH/'sites'/SITE
STATE=BENCH/'.hospitality-stay-panel-fixture.json'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','inspect','files-restored'])
parser.add_argument('--run',choices=['initial','final'],default='initial')
args=parser.parse_args()
if args.run=='final':STATE=BENCH/'.hospitality-stay-panel-final-fixture.json'
BASE=BENCH/'.hospitality-stay-panel-upgrade.json'
assert BASE.is_file() and (BENCH/'.hospitality-stay-panel-ux-baseline.json').is_file()
sha=lambda value:hashlib.sha256(value).hexdigest()
def files():
    result={}
    for kind in ['public','private']:
        folder=TARGET/kind/'files'
        for path in folder.rglob('*'):
            assert not path.is_symlink() and path.resolve().is_relative_to(folder.resolve())
            if path.is_file():result[path.relative_to(TARGET).as_posix()]=sha(path.read_bytes())
    return result
def output(name,data):
    prefix='stay-panel-final' if args.run=='final' else 'stay-panel'
    path=ROOT/f'docs/evidence/{prefix}-{name}.json'
    assert not path.exists()
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(data,ensure_ascii=False,default=str))
if args.action=='files-restored':
    state=json.loads(STATE.read_text())
    receipt=json.loads((BENCH/'.hospitality-stay-panel-ux-restored-receipt.json').read_text())
    assert receipt['site']==SITE
    assert receipt['baseline_sha256']==sha((BENCH/'.hospitality-stay-panel-ux-baseline.json').read_bytes())
    assert files()==state['files']
    output('files-restored',dict(original_files=len(state['files']),all_original_bytes_preserved=True,new_files=0))
    raise SystemExit()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    require_test_site(paused=True)
    assert frappe.conf.db_name=='hospitality_acceptance'
    frappe.set_user('Administrator')
    columns=json.loads(BASE.read_text())[SITE]['tables']
    def tables():
        result={}
        for dt,entry in columns.items():
            assert all(column.replace('_','').isalnum() for column in entry['columns'])
            rows=frappe.db.sql('SELECT '+','.join('`'+column+'`' for column in entry['columns'])+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            result[dt]=dict(rows=len(rows),sha256=sha(raw))
        return result
    if args.action=='prepare':
        assert not STATE.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Stay','HS Booking','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'])
        from hospitality_suite import api
        from hospitality_suite.time import now_local
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        assert str(prop.business_date)=='2026-10-19'
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        start=now_local(prop).replace(microsecond=0)
        values=dict(starts_at=start.isoformat(),ends_at=(start+timedelta(days=1)).isoformat(),guest=guest.name,
            customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        stay=api.execute(prop.name,'walk_in',uuid.uuid4().hex,values)
        state=dict(stay=stay,tables=tables(),files=files())
        STATE.write_text(json.dumps(state));STATE.chmod(0o600)
        frappe.db.commit()
        output('fixture',dict(origin='Native API fixture only: one H101 stay, one lodging charge; no UI creation attributed.',stay=stay,
            tables=len(state['tables']),physical_files=len(state['files']),business_date=str(prop.business_date)))
    else:
        state=json.loads(STATE.read_text())
        assert tables()==state['tables'] and files()==state['files'],'Panel preparation/review must not mutate protected business tables or files'
        raw=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',(BENCH/'.hospitality-run/stay-panel-web.log').read_text())
        events=[json.loads(line.split('SYNTHETIC_TRANSPORT ',1)[1]) for line in raw.splitlines() if line.startswith('SYNTHETIC_TRANSPORT ')]
        assert [event['mode'] for event in events]==['slow-stay-detail','failed-stay-detail']*(2 if args.run=='final' else 1)
        assert not re.findall(r'HTTP/1.1" 500 ',raw)
        assert not re.findall(r'"POST /api/method/hospitality_suite.api.execute ',raw)
        statuses=re.findall(r'"POST /api/method/hospitality_suite.api.stay_detail HTTP/1.1" (\d+)',raw)
        assert statuses.count('503')==(2 if args.run=='final' else 1) and set(statuses)=={'200','503'}
        assert json.loads((BENCH/'.hospitality-run/stay-panel-transport.json').read_text())['remaining']==0
        output('items-ui',dict(site=SITE,at_utc=datetime.now(timezone.utc).isoformat(),native_application=True,
            core_files_modified=False,fixture_created_by='Native API',inspector_mutations=False,
            protected_tables_unchanged=len(state['tables']),physical_files_unchanged=len(state['files']),
            financial_commands_from_UI=0,stay_detail_statuses=statuses,transport_events=events,http_500=0))
finally:
    frappe.db.rollback();frappe.destroy()
