"""Assemble bounded 0.8.5 evidence, without replaying UI or changing databases."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,re,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence';L=ROOT/'.local/page-activity'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8-sig'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
initial=read('page-activity-browser.json');final=read('page-activity-final-browser.json')
assert len(initial['events'])==21 and len(final['events'])==3 and initial['viewport_override_reset'] and final['viewport_override_reset']
assert initial['batch_bundle']=='hospitality.bundle.YN2QKLHG.js' and final['bundle']=='hospitality.bundle.ITJVEKQP.js'
assert set(initial['roles'])=={'HS Cashier','HS Receptionist'} and final['role']=='HS Receptionist'
for image in ['294-actualizacion-en-proceso.jpg','295-arqueo-procesando.jpg','299-reserva-procesando-movil.jpg','301-detalle-preparando-movil.jpg']:
    event=next(row for row in initial['events'] if row.get('screenshot')==image)['observed']
    assert event['pageBusy']=='true' and event['propertyDisabled'] and all(row['disabled'] for row in event['actions'])
recovered=next(row for row in initial['events'] if row.get('screenshot')=='304-actualizacion-recuperada.jpg')['observed']
assert recovered['pageBusy']=='false' and all(not row['disabled'] for row in recovered['actions'])
pending=final['events'][0]['observed'];assert pending['width']==pending['scrollWidth']==390
assert pending['trigger'][0]['disabled'] and len(pending['statuses'])==1 and pending['statuses'][0]['role']=='status'
assert 0<=pending['statuses'][0]['rect']['top']<pending['statuses'][0]['rect']['bottom']<=844
assert final['events'][1]['observed']['localStatuses']==0 and final['events'][1]['observed']['pageBusy']=='false'
before=read('page-activity-native-title-before.json');assert all(len(row['matchingIds'])==1 and row['titleId']==row['labelledby'] for row in before['dialogs'])
items=read('page-activity-items-ui.json');assert items['synthetic_transport'] and len(items['shifts'])==1 and items['booking']['status']=='Confirmed'
assert items['operation_counts']=={'HS Booking':1,'HS Stay':0,'HS Charge':0,'HS Payment':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0}
assert items['http_statuses']['hospitality_suite.api.execute']==['200']*3 and items['http_statuses']['hospitality_suite.api.bootstrap'].count('503')==1 and not items['http_500']
second=read('page-activity-final-items-ui.json');assert second['booking']['status']=='Draft' and second['operation_counts']['HS Booking']==1
assert all(value==0 for key,value in second['operation_counts'].items() if key!='HS Booking') and len(second['transport_events'])==6
for name in ['page-activity-first-ux-restored.json','page-activity-ux-restored.json']:
    restored=read(name);assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
upgrade=read('page-activity-upgrade.json');assert upgrade['sites']=={'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('page-activity-final-state.json');assert state['main_http']==200 and state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
assert state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
for file,count in [('page-activity-initial-js-tests.log',195),('page-activity-js-tests.log',196)]:
    text=(E/file).read_text(encoding='utf-8');assert all(re.search(r'\b'+key+r'\s+'+str(value)+r'\b',text) for key,value in [('tests',count),('pass',count),('fail',0),('skipped',0)])
assert 'hospitality.bundle.ITJVEKQP.js' in (E/'page-activity-build.log').read_text(encoding='utf-8')
assert len(read('page-activity-wire-invariants.json')['files'])==29
native=ET.parse(E/'keyboard-review-native-tests.xml').getroot();assert len(native.findall('.//testcase'))==380 and not any(native.findall('.//'+key) for key in ('failure','error','skipped'))
changed=subprocess.check_output(['git','diff','beac44d','--name-only'],cwd=ROOT,text=True).splitlines()
assert [name for name in changed if name.startswith('hospitality_suite/') and name.endswith('.py')]==['hospitality_suite/__init__.py']
versions=[]
for site in ['main','acceptance']:
    path=L/f'list-{site}.log';assert re.search(r'hospitality_suite\s+0\.8\.5\b',path.read_text(encoding='utf-8-sig'))
    migrate=L/f'migrate-{site}.log';assert 'Updating installed applications...' in migrate.read_text(encoding='utf-8-sig')
    versions.append(dict(site=site,version='0.8.5',listing_sha256=sha(path),migration_sha256=sha(migrate)))
core={}
for app in ['frappe','erpnext']:
    command=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C','/home/frappe/benches/hospitality-bench/apps/'+app]
    core[app]=dict(commit=subprocess.check_output([*command,'rev-parse','HEAD'],text=True).strip(),clean=not subprocess.check_output([*command,'status','--porcelain'],text=True));assert core[app]['clean']
audit=read('../specification-audit.json');counts=dict(Counter(row['status'] for row in audit['items']));assert counts=={'R':14,'I':6,'V':198}
assert read('delivery-review-matrix.json')['audit_sha256']==sha(ROOT/'docs/specification-audit.json')
images=[]
for number in range(294,307):
    paths=list(E.glob(str(number)+'-*.jpg'));assert len(paths)==1 and paths[0].read_bytes().startswith(b'\xff\xd8')
    images.append(dict(path=paths[0].relative_to(ROOT).as_posix(),sha256=sha(paths[0]),captured_bytes_unchanged=True,
        scope='Known open selector issue' if number==298 else 'Intermediate mobile status outside viewport; corrected in 305' if number==301 else 'Initial YN2QKLHG batch' if number<305 else 'Final ITJVEKQP regression'))
references=['page-activity-browser.json','page-activity-final-browser.json','page-activity-items-ui.json','page-activity-final-items-ui.json',
    'page-activity-native-title-before.json','page-activity-first-ux-restored.json','page-activity-ux-restored.json','page-activity-upgrade.json','page-activity-final-state.json',
    'page-activity-initial-js-tests.log','page-activity-js-tests.log','page-activity-initial-build.log','page-activity-build.log','page-activity-wire-invariants.json','page-activity-language-installed.json']
sources=['hospitality_suite/public/js/hospitality.js','hospitality_suite/public/js/hospitality_workflows.js','hospitality_suite/public/hospitality.bundle.css','hospitality_suite/__init__.py',
    'tools/test_desk_transport.cjs','tools/test_countdown_ui.cjs','docs/ACTIVIDAD_Y_RECUPERACION_PAGES.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md']
bundles=list((ROOT/'hospitality_suite/public/dist/js').glob('hospitality.bundle.*.js'));assert len(bundles)==1 and bundles[0].name=='hospitality.bundle.ITJVEKQP.js'
proof=dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(),version='0.8.5',evidence_assembly_only=True,database_mutations=False,ui_replay=False,
    scope='Shared page activity, one-shot transport failure/latency and contextual mobile status. Does not accept all secondary tasks.',
    javascript=dict(initial=195,final=196,desk=193,portal=3,new_cases=5,failures=0,skipped=0),native=dict(tests=380,rerun_in_this_phase=False,revision='beac44d',junit_sha256=sha(E/'keyboard-review-native-tests.xml')),
    native_python_behavior_unchanged=True,native_versions=versions,core=core,statuses=counts,open_requirements=20,all_requirements_completed=False,
    known_open_observations=initial['known_open_observations']+final['known_open_observations'],protected_sites=upgrade['sites'],final_services=state['ports'],
    source_sha256={name:sha(ROOT/name) for name in sources},references={name:sha(E/name) for name in references},screenshots=images,
    compiled_javascript=dict(name=bundles[0].name,sha256=sha(bundles[0])),external_providers_activated=False,final_deployment_rollback_proven=False)
(E/'page-activity-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(javascript=196,initial_events=21,final_events=3,screenshots=len(images),statuses=counts,open_requirements=20)))
