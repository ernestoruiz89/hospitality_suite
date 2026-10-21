"""Assemble bounded evidence for 0.8.3; does not replay UI or write databases."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];EVIDENCE=ROOT/'docs/evidence';LOCAL=ROOT/'.local/secondary-forms'
read=lambda name:json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
trace=read('secondary-forms-browser.json');assert trace['viewport_override_reset'] and len(trace['known_open_observations'])==2
assert set(trace['roles'])=={'HS Administrator','HS Cashier'}
fixed=next(event for event in trace['events'] if event.get('screenshot')=='277-tarifa-fila-validacion-final-movil.jpg')
assert fixed['observed']['errors']==['Fila 1: revise Artículo.']
assert fixed['form_values']==[{'name':'title','value':'Tarifa sin guardar'},{'name':'amount','value':'0.00'}]
assert any(event['observed']['errors']==['La salida o fecha final debe ser posterior al inicio.'] and event['observed']['focused']=='Salida prevista' for event in trace['events'])
items=read('secondary-forms-items-ui.json');assert items['category_records']==1 and items['capacity']==2 and items['rate_draft_unsaved']
assert items['shift_opening']==items['shift_counted']==items['shift_difference']==0 and not any(items['operation_counts'].values())
restored=read('secondary-forms-ux-restored.json');assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
upgrade=read('secondary-forms-upgrade.json');assert upgrade['sites']=={
    'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},
    'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('secondary-forms-final-state.json');assert state['main_http']==200 and state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
assert state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
js=(EVIDENCE/'secondary-forms-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(r'\b'+key+r'\s+'+str(number)+r'\b',js) for key,number in [('tests',183),('pass',183),('fail',0),('skipped',0)])
build=(EVIDENCE/'secondary-forms-build.log').read_text(encoding='utf-8');assert 'hospitality.bundle.TU7AFJT4.js' in build
assert len(read('secondary-forms-wire-invariants.json')['files'])==29
prior=ET.parse(EVIDENCE/'keyboard-review-native-tests.xml').getroot();assert len(prior.findall('.//testcase'))==380
assert not any(prior.findall('.//'+key) for key in ('failure','error','skipped'))
changed=subprocess.check_output(['git','diff','beac44d','--name-only'],cwd=ROOT,text=True).splitlines()
assert [name for name in changed if name.startswith('hospitality_suite/') and name.endswith('.py')]==['hospitality_suite/__init__.py']

native=[]
for site in ['main','acceptance']:
    path=LOCAL/f'list-{site}.log';text=path.read_text(encoding='utf-8-sig');assert re.search(r'hospitality_suite\s+0\.8\.3\b',text)
    migrate=LOCAL/f'migrate-{site}.log';assert 'Updating installed applications...' in migrate.read_text(encoding='utf-8-sig')
    native.append(dict(site=site,installed_version='0.8.3',version_output_sha256=sha(path),migration_output_sha256=sha(migrate)))
core={}
for app in ['frappe','erpnext']:
    location='/home/frappe/benches/hospitality-bench/apps/'+app
    command=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C',location]
    revision=subprocess.check_output([*command,'rev-parse','HEAD'],text=True).strip()
    status=subprocess.check_output([*command,'status','--porcelain'],text=True);assert not status,app
    core[app]=dict(commit=revision,clean=True)

# The guide review is a historical artifact of beac44d. New progress/version
# paragraphs in README do not silently rewrite its earlier reviewed content.
guides=read('delivery-review-guides.json')
for name,digest in guides['documents'].items():
    content=subprocess.check_output(['git','show','beac44d:'+name],cwd=ROOT)
    assert hashlib.sha256(content).hexdigest()==digest,name
audit=read('../specification-audit.json');counts=dict(Counter(row['status'] for row in audit['items']));assert counts=={'R':16,'I':6,'V':196}
assert read('delivery-review-matrix.json')['audit_sha256']==sha(ROOT/'docs/specification-audit.json')
images=[]
for number in range(274,283):
    paths=list(EVIDENCE.glob(str(number)+'-*.jpg'));assert len(paths)==1
    path=paths[0];assert path.read_bytes().startswith(b'\xff\xd8')
    images.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),captured_bytes_unchanged=True,
        scope='Intermediate defect/known open observation' if number in (276,281) else 'Observed UI state; incremental build scope in browser trace'))
references=['secondary-forms-browser.json','secondary-forms-items-ui.json','secondary-forms-ux-restored.json','secondary-forms-upgrade.json',
    'secondary-forms-final-state.json','secondary-forms-js-tests.log','secondary-forms-build.log','secondary-forms-language-installed.json','secondary-forms-wire-invariants.json']
sources=['hospitality_suite/public/js/hospitality.js','hospitality_suite/public/js/hospitality_forms.js','hospitality_suite/public/hospitality.bundle.css',
    'hospitality_suite/__init__.py','tools/test_forms_ui.cjs','tools/test_desk_transport.cjs','docs/VALIDACION_FORMULARIOS.md']
bundles=list((ROOT/'hospitality_suite/public/dist/js').glob('hospitality.bundle.*.js'));assert len(bundles)==1 and bundles[0].name=='hospitality.bundle.TU7AFJT4.js'
proof=dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(),version='0.8.3',scope='Shared local form validation and pending-input preservation; not acceptance of all secondary tasks.',
    evidence_assembly_only=True,ui_replay_by_verifier=False,database_mutations_by_verifier=False,
    javascript=dict(tests=183,desk=180,portal=3,failures=0,skipped=0,new_cases=9),
    native_regression=dict(tests=380,rerun_in_this_phase=False,revision='beac44d',junit='keyboard-review-native-tests.xml',junit_sha256=sha(EVIDENCE/'keyboard-review-native-tests.xml')),
    native_behavior_python_unchanged=True,version_metadata_only_python_change=True,native_versions=native,core=core,
    known_open_observations=trace['known_open_observations'],statuses=counts,open_requirements=22,all_requirements_completed=False,
    protected_sites=upgrade['sites'],business_date_preserved='2026-10-19',final_services=state['ports'],
    historical_guide_review_verified_at='beac44d',source_sha256={name:sha(ROOT/name) for name in sources},
    references={name:sha(EVIDENCE/name) for name in references},screenshots=images,
    compiled_javascript=dict(name=bundles[0].name,bytes=bundles[0].stat().st_size,sha256=sha(bundles[0])),external_providers_activated=False,final_deployment_rollback_proven=False)
(EVIDENCE/'secondary-forms-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(javascript=183,ui_events=len(trace['events']),screenshots=len(images),baseline_preserved=True,statuses=counts,all_requirements_completed=False)))
