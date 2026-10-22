"""Verify retention/portal acceptance without treating inventory as GUI execution."""
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
run=read('privacy-portal-native-run.json')
assert (run['tests'],run['integration'],run['unit'])==(410,378,32)
assert not any(run[key] for key in ['errors','failures','skipped','exit_code'])
xml=ET.parse(E/'privacy-portal-native-tests.xml').getroot()
cases=xml.findall('.//testcase')
assert len(cases)==410 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
for name in ['test_candidate_labels_identify_closed_incidents_without_exposing_their_description',
             'test_request_hold_signature_conversion_and_expiry','test_portal_disabled_by_default']:
    assert any(row.get('name')==name for row in cases)
js=(E/'privacy-portal-js-tests.log').read_text()
assert all(re.search(rf'^# {key} {value}$',js,re.M) for key,value in
    [('tests',232),('pass',232),('fail',0),('cancelled',0),('skipped',0),('todo',0)])
assert '# fail 2' in (E/'privacy-portal-conversion-red-js-tests.log').read_text()
browser=read('privacy-portal-browser.json')
public=read('privacy-portal-public-browser.json')
assert len(browser['events'])==29 and len(public['events'])==10
events={row['label']:row for row in browser['events']}
public_events={row['label']:row for row in public['events']}
for label in ['manager-retention-reason-required','manager-retention-retry-reason-required']:
    assert any(row.get('name')=='reason' and row['invalid']=='true' and not row['value']
               for row in events[label]['inputs'])
assert any(row.get('name')=='confirm' and row['invalid']=='true' and row['checked'] is False
           for row in events['manager-retention-acknowledgement-required']['inputs'])
for label,text in [('manager-retention-failed-three-attempts-visible','Reintentar'),
                   ('manager-retention-completed-visible','Completada'),
                   ('reception-portal-context-final','2 habitaciones'),
                   ('reception-portal-price-review','Pagador'),
                   ('reception-converted-booking-detail','Por asignar')]:
    assert text in events[label]['text'],label
options=next(row['options'] for row in events['manager-candidates-identifiable-final']['inputs']
             if row.get('name')=='target')
assert any('INC-2026-00001' in row['label'] and 'H101' in row['label'] for row in options)
assert any('INC-2026-00002' in row['label'] and 'H102' in row['label'] for row in options)
assert 'Iniciar Sesión' in events['reception-logged-out']['text']
last=public_events['converted-confirmation-instructions-corrected']
assert 'Iniciar sesión' in last['text'] and 'Solicitud convertida en reserva' in last['text']
assert 'Para cambios o consultas' in last['text'] and 'Recepción debe confirmar la solicitud' not in last['text']
assert last['confirmation_token_present'] and '?' not in last['url']
assert not re.search(r'[?&]token=',json.dumps(public,ensure_ascii=False))
assert 'Cupo conservado hasta' in public_events['portal-public-hold-confirmation']['text']
assert 'Consulte nuevamente' in public_events['portal-edited-quote-invalidated']['text']

recent=read('privacy-portal-recent-preserved.json')
cancel=read('privacy-portal-preview-cancelled.json')
assert recent['counts']['File']==cancel['counts']['File']==7
assert recent['counts']['HS Retention Run']==cancel['counts']['HS Retention Run']==0
assert not recent['candidates']['targets']
old=read('privacy-portal-eligible-fault-before.json')['candidates']['targets']
fixed=read('privacy-portal-candidate-labels-fixed.json')['candidates']['targets']
assert len(old)==len(fixed)==2 and len({row['label'] for row in old})==1 and len({row['label'] for row in fixed})==2
failed=read('privacy-portal-retention-first-result.json')['runs'][0]
assert (failed['status'],failed['attempts'])==('Failed',3)
assert Counter(row['status'] for row in failed['files'])=={'Deleted':2,'Failed':1}
assert any(row['last_error']=='IsADirectoryError errno=21' for row in failed['files'])
done=read('privacy-portal-completed-ui.json')
retention=done['runs'][0]
assert retention['status']=='Completed' and retention['approved_by']=='manager@hospitality.example.invalid'
assert len(retention['files'])==3 and all(row['status']=='Deleted' and not row['retained_path'] and not row['retained_hash'] for row in retention['files'])
incidents={row['name']:row for row in done['incidents']}
assert incidents['INC-2026-00001']['evidence'] is None
assert incidents['INC-2026-00002']['evidence']=='/private/files/evidencia-control-ficticia.txt'
assert all(row['status']=='Resolved' and row['resolution'] for row in incidents.values())
paths=done['file_state']['known_paths']
assert len(paths)==3 and all(not row['exists'] for name,row in paths.items() if name.endswith('.pdf'))
control=paths['private/files/evidencia-control-ficticia.txt']
assert control['is_file'] and control['sha256']==control['original_sha256']
histories={row['incident']:row for row in done['history']}
assert histories['INC-2026-00001']['versions_with_private_file_urls']==histories['INC-2026-00001']['attachment_comments']==0
assert histories['INC-2026-00002']['versions_with_private_file_urls']==1 and histories['INC-2026-00002']['attachment_comments']==2
assert len(done['file_docs'])==2 and all(row['is_private'] and row['attached_to_name']=='INC-2026-00002' for row in done['file_docs'])
review=read('privacy-portal-portal-review-cancelled.json')
assert review['counts']['HS Booking']==0 and sum(row['status']=='Active' for row in review['allocations'])==2
assert len(done['portal_requests'])==len(done['bookings'])==1
request,booking=done['portal_requests'][0],done['bookings'][0]
assert request['owner']=='Guest' and request['status']=='Converted' and request['booking']==booking['name']
assert (request['rooms'],request['people'],request['amount'])==(2,2,3000)
assert booking['owner']=='receptionist@hospitality.example.invalid' and booking['status']=='Confirmed' and booking['amount']==3000
assert len(done['allocations'])==4
assert sum(row['status']=='Released' and row['portal_request']==request['name'] for row in done['allocations'])==2
assert sum(row['status']=='Active' and row['booking']==booking['name'] and not row['room'] for row in done['allocations'])==2
assert all(done['counts'][dt]==0 for dt in ['HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'])
assert any(row['action']=='Retry file disposal' and row['actor']=='manager@hospitality.example.invalid' for row in done['audit'])
assert any(row['action']=='Convert portal request' and row['actor']=='receptionist@hospitality.example.invalid' for row in done['audit'])

for name in ['privacy-portal-first-ux-restored.json','privacy-portal-ux-restored.json']:
    restored=read(name)
    assert restored['restored'] and restored['tables']==71 and restored['rows']==185
gui=read('privacy-portal-gui-files-restored.json')
assert gui['original_files']==741 and gui['all_original_bytes_preserved'] and gui['GUI_artifacts_preserved_outside_site']==3
files=read('privacy-portal-files-restored.json')
assert files['original_physical_files']==741 and files['all_original_bytes_preserved']
assert files['native_artifacts_preserved_outside_site']==13
upgrade=read('privacy-portal-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
inventory=read('privacy-portal-actions.json')
assert inventory['handler_count']==84 and len(inventory['buttons'])==97 and len(inventory['sources_sha256'])==30
assert not inventory['unbound_literal_actions'] and not inventory['unresolved_dynamic_buttons']
assert all(sha(ROOT/name)==digest for name,digest in inventory['sources_sha256'].items())
crosswalk=read('privacy-portal-task-acceptance.json')
assert len(crosswalk['task_families'])==22 and crosswalk['handler_count']==84
assert all((ROOT/name).is_file() for row in crosswalk['task_families'] for name in row['evidence'])
assert all(sha(ROOT/name)==digest for row in crosswalk['task_families'] for name,digest in row['evidence_sha256'].items())
assert sorted(action for row in crosswalk['task_families'] for action in row['actions'])==sorted(inventory['effective_handlers'])
ports={}
for port in [8086,8089,8091,9001,9003,11001,13001,11003,13003]:
    with socket.socket() as connection:
        connection.settimeout(.3);ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert {p for p,on in ports.items() if on}=={'8086','9001','11001','13001'}
restart=json.loads((BENCH/'.hospitality-privacy-portal-main-restarted.json').read_text())
assert restart['privacy_sha256']==sha(ROOT/'hospitality_suite/privacy.py')
for name in ['web','worker']:assert (BENCH/'.hospitality-run'/f'{name}.pid').read_text().strip()==restart['after'][name]
assets=json.loads((BENCH/'sites/assets/assets.json').read_text());bundle=assets['hospitality.bundle.js']
with urllib.request.urlopen('http://hospitality.localhost:8086'+bundle,timeout=10) as response:
    assert response.status==200;served=hashlib.sha256(response.read()).hexdigest()
assert served==sha((BENCH/'sites'/bundle.lstrip('/')).resolve())
assert any(bundle in url for url in events['reception-portal-price-review']['bundle'])
for app in ['frappe','erpnext']:assert not subprocess.check_output(['git','status','--porcelain'],cwd=BENCH/'apps'/app)
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'));counts=Counter(row['status'] for row in audit['items'])
assert len(audit['items'])==218 and counts=={'V':214,'I':4}
assert {row['id'] for row in audit['items'] if row['status']!='V'}=={'S00-01','S01-12','S19-07','S19-08'}
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),statuses=dict(counts),newly_closed_requirements=['S04-20'],
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),
    native=dict(tests=410,integration=378,unit=32,failures=0,errors=0,skipped=0),javascript=dict(tests=232,desk=229,portal=3),
    browser=dict(roles=['HS Housekeeping','HS Manager','HS Receptionist','Guest'],desk_observations=29,public_observations=10,
                 historical_acceptance_preserved=True,not_84_new_GUI_runs=True),
    acceptance_restored=True,main_business_mutations=False,original_physical_files=741,
    GUI_artifacts_archived=3,native_artifacts_quarantined=files['native_artifacts_preserved_outside_site'],
    current_python_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'hospitality_suite').rglob('*.py')},
    confirmation_template_sha256=sha(ROOT/'hospitality_suite/www/hospitality-confirmation.html'),
    bundle=bundle,served_bundle_sha256=served,ports=ports,final_F26_complete=False,current_package_contains_this_phase=False,
    remaining=['F26-package-delivery','general-objective-closure'],ota_sync_deferred_by_user=True,
    references_sha256={p.name:sha(p) for p in E.glob('privacy-portal-*') if p.name!='privacy-portal-verification.json'},
    screenshots_sha256={p.name:sha(p) for n in range(383,395) for p in E.glob(str(n)+'-*')})
(E/'privacy-portal-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(native=410,javascript=232,desk=29,public=10,verified=214,open=4,acceptance_restored=True)))
