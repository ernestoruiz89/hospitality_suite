"""Seal reviewed shared states, two bounded GUI runs and exact data conservation."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.request
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence'
BENCH=Path('/home/frappe/benches/hospitality-bench')
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
counts=Counter(row['status'] for row in audit['items'])
assert len(audit['items'])==218 and counts=={'V':213,'I':5}
assert {row['id'] for row in audit['items'] if row['status']!='V'}=={'S00-01','S01-12','S04-20','S19-07','S19-08'}
assert audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
previous=read('secondary-finance-verification.json')
python={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'hospitality_suite').rglob('*.py')}
assert python==previous['current_python_sha256'],'A changed backend requires a new native run'
native=read('secondary-finance-native-run.json')
assert (native['tests'],native['integration'],native['unit'])==(407,375,32)
assert not any(native[key] for key in ['failures','errors','skipped'])
xml=ET.parse(E/'secondary-finance-native-tests.xml').getroot()
assert len(xml.findall('.//testcase'))==407 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
for name,total in [('stay-panel-js-tests.log',229),('stay-panel-initial-js-tests.log',228)]:
    text=(E/name).read_text()
    assert all(re.search(rf'^# {key} {value}$',text,re.M) for key,value in [('tests',total),('pass',total),('fail',0),('cancelled',0),('skipped',0),('todo',0)])
red=(E/'stay-panel-red-js-tests.log').read_text()
assert '# tests 32' in red and '# fail 3' in red and '# cancelled 0' in red
for name in ['queued stay-panel activations prepare one child action through the Page coordinator',
    'stay-panel transport errors recover once and a reopened panel permits a deliberate retry',
    'an offline stay panel remains open and its native close has no fading overlay']:
    assert 'not ok' in red and name in red
inventory=read('stay-panel-actions.json')
assert inventory['handler_count']==84 and len(inventory['buttons'])==97 and len(inventory['sources_sha256'])==30
assert not inventory['unbound_literal_actions'] and not inventory['unresolved_dynamic_buttons']
assert all(sha(ROOT/name)==digest for name,digest in inventory['sources_sha256'].items())
first=read('stay-panel-browser.json');final=read('stay-panel-final-browser.json')
assert first['role']==final['role']=='HS Manager' and first['viewport']==final['viewport']=='desktop'
events={row['label']:row for row in final['events']}
active=lambda row:[d for d in row['dialogs'] if d['visible'] and 'hs-form-suspended' not in d['classes']]
slow=events['slow-preparation-visible']
assert not active(slow) and not slow['backdrops'] and len(slow['statuses'])==1
notice=slow['statuses'][0]
assert notice['visible'] and notice['role']=='status' and notice['parent']=='BODY'
assert 'Preparando acción' in notice['text']
rect=notice['rect'];viewport=slow['viewport']
assert 0<=rect['left']<rect['right']<=viewport['width'] and 0<=rect['top']<rect['bottom']<=viewport['height']
assert all(button['disabled'] for button in slow['buttons'] if button['action'])
ready=events['one-child-ready-status-cleared']
assert [d['title'] for d in active(ready)]==['Facturar cuenta'] and not ready['statuses']
error=events['failed-read-status-cleared']
assert [d['title'] for d in active(error)]==['No se completó la acción'] and not error['statuses']
assert [d['title'] for d in active(events['retry-form-ready'])]==['Facturar cuenta']
assert 'Total a facturar: C$ 1,500.00' in events['invoice-review-ready']['text']
cancel=events['review-cancelled-same-account']
assert [d['title'] for d in active(cancel)]==['Facturar cuenta']
assert any(row['value']=='CTA-2026-00001' for row in cancel['inputs'])
validation=events['extension-inline-validation']
assert 'Complete Nueva salida.' in validation['text'] and 'Complete Cuenta para la extensión.' in validation['text']
assert any(row.get('name')=='ends_at' and row['invalid']=='true' for row in validation['inputs'])
for label in ['failure-dismissed-ready','forms-closed-no-overlay','manager-logged-out']:
    row=events[label]
    assert not active(row) and not row['backdrops'] and not row['statuses']
assert events['manager-logged-out']['url'].split('/')[3].startswith('login')
for name in ['stay-panel-items-ui.json','stay-panel-final-items-ui.json']:
    data=read(name)
    assert data['protected_tables_unchanged']==72 and data['physical_files_unchanged']==741
    assert data['financial_commands_from_UI']==data['http_500']==0 and not data['inspector_mutations']
for name in ['stay-panel-first-ux-restored.json','stay-panel-ux-restored.json']:
    restored=read(name)
    assert restored['restored'] and restored['tables']==71 and restored['rows']==185
for name in ['stay-panel-files-restored.json','stay-panel-final-files-restored.json']:
    restored=read(name)
    assert restored['original_files']==741 and restored['all_original_bytes_preserved'] and restored['new_files']==0
upgrade=read('stay-panel-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
ports={}
for port in [8086,8089,8091,9001,9003,11001,13001,11003,13003]:
    with socket.socket() as connection:
        connection.settimeout(.3);ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert {p for p,on in ports.items() if on}=={'8086','9001','11001','13001'}
assets=json.loads((BENCH/'sites/assets/assets.json').read_text())
served={}
for key in ['hospitality.bundle.js','hospitality.bundle.css']:
    asset=assets[key]
    with urllib.request.urlopen('http://hospitality.localhost:8086'+asset,timeout=10) as response:
        assert response.status==200
        digest=hashlib.sha256(response.read()).hexdigest()
    assert digest==sha((BENCH/'sites'/asset.lstrip('/')).resolve())
    served[key]=dict(path=asset,sha256=digest)
assert any(served['hospitality.bundle.js']['path'] in url for url in slow['bundle'])
for app in ['frappe','erpnext']:
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=BENCH/'apps'/app)
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),statuses=dict(counts),newly_closed_requirements=['S04-16'],
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),
    native=dict(tests=407,integration=375,unit=32,execution='Historical fbb4ce7; all application Python identical; not rerun in this JS/CSS phase'),
    current_python_sha256=python,javascript=dict(tests=229,desk=226,portal=3),
    browser=dict(roles=['HS Manager'],initial_events=len(first['events']),final_events=len(final['events']),desktop_only=True,
        fixture='Native API; not attributed to UI',synthetic_transport='Two one-shot 8-second delays and two 503s across two restored scenarios'),
    state_contract_review='PANEL_ESTANCIA_Y_ESTADOS.md; historical and current GUI evidence are explicitly distinguished',
    queued_duplicate_preparation_reproduced_by='Registered callback regression; no GUI double invoice claimed',
    acceptance_restored=True,original_physical_files=741,main_business_mutations=False,assets=served,ports=ports,
    full_secondary_acceptance=False,final_F26_complete=False,current_package_contains_this_phase=False,ota_sync_deferred_by_user=True,
    references_sha256={p.name:sha(p) for p in E.glob('stay-panel-*') if p.name!='stay-panel-verification.json'},
    screenshots_sha256={p.name:sha(p) for n in range(375,380) for p in E.glob(str(n)+'-*')})
(E/'stay-panel-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(verified=213,open=5,newly_closed=['S04-16'],javascript=229,historical_native=407,acceptance_restored=True)))
