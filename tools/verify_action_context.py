"""Assemble bounded 0.8.4 evidence; no UI replay or database writes."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];EVIDENCE=ROOT/'docs/evidence';LOCAL=ROOT/'.local/action-context'
read=lambda name:json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
trace=read('action-context-browser.json')
assert trace['viewport_override_reset'] and len(trace['events'])==27 and len(trace['known_open_observations'])==2
assert set(trace['roles'])=={'HS Cashier','HS Receptionist'}
decimal=next(event for event in trace['events'] if event.get('screenshot')=='285-cantidad-decimal-validacion.jpg')['observed']
assert decimal['errors']==['Indique un número entero de 1 o más.'] and decimal['counts'][0]['value']=='1.5'
assert decimal['focus']=='Cantidad de habitaciones'
cards=next(event for event in trace['events'] if event['step'].startswith('Estados visibles del intervalo'))['observed']
assert len(cards)==10 and cards[0]['room']=='H101' and cards[0]['state']=='× No disponible'
assert cards[0]['background']=='rgb(252, 236, 238)' and cards[0]['color']=='rgb(161, 38, 46)'
assert all(row['state']=='✓ Disponible' and row['background']=='rgb(234, 246, 237)' and row['color']=='rgb(23, 100, 58)' for row in cards[1:])
mobile=next(event for event in trace['events'] if event['step'].startswith('Medidas de tarjetas'))['observed']
assert mobile['width']==mobile['documentWidth']==390 and mobile['modal']==[{'clientWidth':390,'scrollWidth':390}]
handoff=read('action-context-main-handoff.json');assert handoff['viewport_override_reset'] and handoff['bundle'].endswith('hospitality.bundle.DB4YLAYT.js')
assert len(handoff['cards'])==10 and handoff['cards'][4]['room']=='H105'
assert handoff['cards'][4]['description']=='Ocupada en el intervalo' and handoff['cards'][4]['background']=='rgb(252, 236, 238)'
assert all(row['background']=='rgb(234, 246, 237)' for row in handoff['cards'] if row['room']!='H105')
assert handoff['cards'][1]['cleaning']=='Limpieza actual: Sucia'
checkpoint=read('action-context-invalid-checkpoint.json');assert not checkpoint['availability_http_statuses'] and not any(checkpoint['operation_counts'].values())
items=read('action-context-items-ui.json')
assert len(items['shifts'])==2 and all(row['status']=='Closed' and row['opening_amount']==row['counted_amount']==row['difference']==0 for row in items['shifts'])
assert items['operation_counts']=={'HS Booking':1,'HS Stay':0,'HS Payment':0,'HS Charge':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0}
assert items['booking']['status']=='Confirmed' and items['booking']['room']=='H101' and items['available']==9
assert items['availability_http_statuses']==['200']*3 and items['logout_http_statuses']==['200']*2 and not items['http_500']
restored=read('action-context-ux-restored.json');assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
upgrade=read('action-context-upgrade.json');assert upgrade['sites']=={
    'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},
    'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('action-context-final-state.json');assert state['main_http']==200 and state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
assert state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
js=(EVIDENCE/'action-context-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(r'\b'+key+r'\s+'+str(number)+r'\b',js) for key,number in [('tests',191),('pass',191),('fail',0),('skipped',0)])
build=(EVIDENCE/'action-context-build.log').read_text(encoding='utf-8')
assert 'hospitality.bundle.DB4YLAYT.js' in build and 'hospitality.bundle.7ABEJ5NU.css' in build
assert len(read('action-context-wire-invariants.json')['files'])==29
prior=ET.parse(EVIDENCE/'keyboard-review-native-tests.xml').getroot();assert len(prior.findall('.//testcase'))==380
assert not any(prior.findall('.//'+key) for key in ('failure','error','skipped'))
changed=subprocess.check_output(['git','diff','211276b','--name-only'],cwd=ROOT,text=True).splitlines()
assert [name for name in changed if name.startswith('hospitality_suite/') and name.endswith('.py')]==['hospitality_suite/__init__.py']
assert 'HS action diagnostic' not in (ROOT/'hospitality_suite/public/js/hospitality.js').read_text(encoding='utf-8')

versions=[]
for site in ['main','acceptance']:
    listing=LOCAL/f'list-{site}.log';assert re.search(r'hospitality_suite\s+0\.8\.4\b',listing.read_text(encoding='utf-8-sig'))
    migrate=LOCAL/f'migrate-{site}.log';assert 'Updating installed applications...' in migrate.read_text(encoding='utf-8-sig')
    versions.append(dict(site=site,installed_version='0.8.4',version_output_sha256=sha(listing),migration_output_sha256=sha(migrate)))
core={}
for app in ['frappe','erpnext']:
    command=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C','/home/frappe/benches/hospitality-bench/apps/'+app]
    revision=subprocess.check_output([*command,'rev-parse','HEAD'],text=True).strip()
    assert not subprocess.check_output([*command,'status','--porcelain'],text=True),app
    core[app]=dict(commit=revision,clean=True)
for name,digest in read('delivery-review-guides.json')['documents'].items():
    assert hashlib.sha256(subprocess.check_output(['git','show','beac44d:'+name],cwd=ROOT)).hexdigest()==digest,name
audit=read('../specification-audit.json');counts=dict(Counter(row['status'] for row in audit['items']));assert counts=={'R':16,'I':6,'V':196}
assert read('delivery-review-matrix.json')['audit_sha256']==sha(ROOT/'docs/specification-audit.json')
images=[]
for number in range(283,294):
    paths=list(EVIDENCE.glob(str(number)+'-*.jpg'));assert len(paths)==1
    path=paths[0];assert path.read_bytes().startswith(b'\xff\xd8')
    images.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),captured_bytes_unchanged=True,
        scope='Bounds/action context before colors: DALLPPL6' if number<288 else 'Main read-only handoff: DB4YLAYT' if number==293 else 'Requested colors: DB4YLAYT'))
references=['action-context-browser.json','action-context-invalid-checkpoint.json','action-context-items-ui.json',
    'action-context-ux-restored.json','action-context-upgrade.json','action-context-final-state.json',
    'action-context-js-tests.log','action-context-build.log','action-context-language-installed.json','action-context-wire-invariants.json','action-context-main-handoff.json']
sources=['hospitality_suite/public/js/hospitality.js','hospitality_suite/public/js/hospitality_forms.js',
    'hospitality_suite/public/js/hospitality_availability.js','hospitality_suite/public/hospitality.bundle.css','hospitality_suite/__init__.py',
    'tools/test_forms_ui.cjs','tools/test_desk_transport.cjs','tools/test_availability_ui.cjs','docs/DISPONIBILIDAD_VISUAL_Y_LIMITES.md']
bundles=list((ROOT/'hospitality_suite/public/dist/js').glob('hospitality.bundle.*.js'))
assert len(bundles)==1 and bundles[0].name=='hospitality.bundle.DB4YLAYT.js'
proof=dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(),version='0.8.4',
    scope='Availability colors with written states and explicit quantity bounds; not acceptance of every secondary task.',
    evidence_assembly_only=True,ui_replay_by_verifier=False,database_mutations_by_verifier=False,
    javascript=dict(tests=191,desk=188,portal=3,failures=0,skipped=0,new_cases=8),
    native_regression=dict(tests=380,rerun_in_this_phase=False,revision='beac44d',junit='keyboard-review-native-tests.xml',junit_sha256=sha(EVIDENCE/'keyboard-review-native-tests.xml')),
    native_behavior_python_unchanged=True,version_metadata_only_python_change=True,native_versions=versions,core=core,
    known_open_observations=trace['known_open_observations'],statuses=counts,open_requirements=22,all_requirements_completed=False,
    protected_sites=upgrade['sites'],business_date_preserved='2026-10-19',final_services=state['ports'],historical_guide_review_verified_at='beac44d',
    source_sha256={name:sha(ROOT/name) for name in sources},references={name:sha(EVIDENCE/name) for name in references},screenshots=images,
    raw_command_outputs={name:sha(LOCAL/name) for name in ['js-colors.log','build-colors.log']},
    public_log_normalization='UTF-8 LF and trailing whitespace removed; original command outputs preserved privately with hashes.',
    compiled_javascript=dict(name=bundles[0].name,bytes=bundles[0].stat().st_size,sha256=sha(bundles[0])),
    external_providers_activated=False,final_deployment_rollback_proven=False)
(EVIDENCE/'action-context-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(javascript=191,ui_events=len(trace['events']),screenshots=len(images),baseline_preserved=True,statuses=counts,all_requirements_completed=False)))
