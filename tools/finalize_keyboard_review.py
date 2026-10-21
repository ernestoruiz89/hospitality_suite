"""Assemble existing keyboard evidence; no browser operations or database writes."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import struct
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'docs/evidence'
LOCAL=ROOT/'.local/keyboard-review'

def read(name):return json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))
def write(name,value):(EVIDENCE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def image_size(raw):
    if raw[:8]==b'\x89PNG\r\n\x1a\n':return 'image/png',struct.unpack('>II',raw[16:24])
    assert raw[:2]==b'\xff\xd8','Unexpected capture encoding'
    offset=2
    while offset<len(raw):
        assert raw[offset]==255
        while raw[offset]==255:offset+=1
        marker=raw[offset];offset+=1
        if marker in (1,216,217,*range(208,216)):continue
        length=int.from_bytes(raw[offset:offset+2],'big')
        if marker in (192,193,194,195,197,198,199,201,202,203,205,206,207):
            return 'image/jpeg',(int.from_bytes(raw[offset+5:offset+7],'big'),int.from_bytes(raw[offset+3:offset+5],'big'))
        offset+=length
    raise AssertionError('Missing capture dimensions')

# The browser returns JPEG bytes even when a caller chose a .png filename.
# Correct names and references only; preserve every captured byte.
renames={}
for number in range(247,274):
    paths=[p for p in EVIDENCE.glob(str(number)+'-*') if p.suffix in ('.png','.jpg')];assert len(paths)==1,number
    path=paths[0];mime,_=image_size(path.read_bytes());target=path.with_suffix('.jpg' if mime=='image/jpeg' else '.png')
    if target!=path:
        assert path.resolve().parent==target.resolve().parent==EVIDENCE.resolve() and not target.exists()
        before=digest(path);path.rename(target);assert digest(target)==before;renames[path.name]=target.name
for path in (ROOT/'docs/TECLADO_Y_FOCO.md',EVIDENCE/'keyboard-review-roles-ui.json'):
    text=path.read_text(encoding='utf-8-sig')
    for old,new in renames.items():text=text.replace(old,new)
    path.write_text(text,encoding='utf-8',newline='\n')

for source,target in [('native-final.log','keyboard-review-native-tests.log'),('js-twentieth.log','keyboard-review-js-tests.log'),('build-thirteenth.log','keyboard-review-build.log')]:
    text=(LOCAL/source).read_text(encoding='utf-8-sig')
    (EVIDENCE/target).write_text('\n'.join(line.rstrip() for line in text.splitlines())+'\n',encoding='utf-8',newline='\n')

cases=ET.parse(EVIDENCE/'keyboard-review-native-tests.xml').getroot()
assert len(cases.findall('.//testcase'))==380
assert not any(cases.findall('.//'+tag) for tag in ('error','failure','skipped'))
classes=Counter(case.get('classname').split('.')[-1] for case in cases.findall('.//testcase'))
js=(EVIDENCE/'keyboard-review-js-tests.log').read_text()
assert all(re.search(r'\b'+key+r'\s+'+str(number)+r'\b',js) for key,number in [('tests',174),('pass',174),('fail',0),('skipped',0)])
assert 'hospitality.bundle.TSVX6BYI.js' in (EVIDENCE/'keyboard-review-build.log').read_text()

roles=read('keyboard-review-roles-ui.json')
actors={e['role'] for e in roles['events'] if e.get('actor_observed_in_ui')}
assert len(actors)==9 and actors==set(roles['completed_roles'])
assert len(roles['events'])==180 and roles['viewport_override_reset']
scenario=read('keyboard-review-items-ui.json')
assert scenario['total']==1530 and scenario['outstanding']==scenario['shift_difference']==0
assert scenario['mobile_rate_draft_unsaved'] and scenario['portal_requests_sent']==0
restored=read('keyboard-review-ux-restored.json');assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
upgrade=read('keyboard-review-upgrade.json')
assert upgrade['sites']['hospitality.localhost']==dict(tables=72,rows=1246,private_files=2)
assert upgrade['sites']['hospitality-acceptance.localhost']==dict(tables=72,rows=250,private_files=0)
state=read('keyboard-review-final-state.json')
assert state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True} and state['main_http']==200
assert state['main']['business_date']=='2026-10-19'
assert not any(state['acceptance']['operation_counts'].values())
prints=read('account-summary-installed.json')
assert prints['html_sha256']=='e1accf8743960381bd560aa4d1af99574599e2daf39d72adc04139252836e15a'
assert all(value['installed_html_matches_source'] for value in prints['sites'].values())
architecture=read('architecture-current.json');assert all(row['clean'] for row in architecture['core'].values())
cli=read('delivery-review-cli.json');assert len(cli['commands'])==13 and all(row['exit_code']==0 for row in cli['commands'])
assert any(re.search(r'hospitality_suite\s+0\.8\.2\b',row.get('output','')) for row in cli['commands'])

roles['status']='Browser walkthrough, native regression and acceptance restoration verified.'
roles['final_checks']=['keyboard-review-native-tests.xml','keyboard-review-js-tests.log','keyboard-review-items-ui.json','keyboard-review-ux-restored.json','keyboard-review-upgrade.json','keyboard-review-final-state.json']
roles['portal_source_sha256']={str(path.relative_to(ROOT)).replace('\\','/'):digest(path) for path in (ROOT/'hospitality_suite/www/hospitality.js',ROOT/'hospitality_suite/www/hospitality.html')}
write('keyboard-review-roles-ui.json',roles)

images=[]
for number in range(247,274):
    paths=[p for p in EVIDENCE.glob(str(number)+'-*') if p.suffix in ('.png','.jpg')];assert len(paths)==1,number
    path=paths[0];mime,(width,height)=image_size(path.read_bytes())
    images.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path),mime_type=mime,width=width,height=height,captured_bytes_unchanged=True,
        scope='Before/intermediate defect observation, not final acceptance' if number in (247,271) else 'Observed browser state; see role trace for its step and build'))

references=['keyboard-review-roles-ui.json','keyboard-review-items-ui.json','keyboard-review-logout.json','keyboard-review-native-tests.xml','keyboard-review-native-tests.log',
    'keyboard-review-js-tests.log','keyboard-review-build.log','keyboard-review-wire-invariants.json','keyboard-review-language-installed.json','keyboard-review-permissions-source.json',
    'keyboard-review-ux-restored.json','keyboard-review-upgrade.json','keyboard-review-final-state.json','account-summary-installed.json','architecture-current.json']
proof=dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(),requirement='S04-17',evidence_assembly_only=True,not_an_independent_browser_replay=True,
    tests=dict(native=380,integration=366,pure=14,javascript=174,desk=171,portal=3,failures=0,errors=0,skipped=0),
    verified_ui_roles=sorted(actors),actor_observations=sum(bool(e.get('actor_observed_in_ui')) for e in roles['events']),ui_events=len(roles['events']),
    scenario=scenario,restored=restored,protected_data=upgrade['sites'],services=state['ports'],main_http=200,business_date='2026-10-19',
    installed_compact_print_preserved=True,external_providers_activated=False,final_deployment_rollback_proven=False,
    references={name:digest(EVIDENCE/name) for name in references},screenshots=images)
write('keyboard-review-acceptance.json',proof)

documents=['README.md','docs/MANUAL.md','docs/CONTABILIDAD.md','docs/OPERACION.md','docs/ENTREGABLES_Y_REVISION.md','pyproject.toml']
sources=['hospitality_suite/install.py','hospitality_suite/setup.py','hospitality_suite/accounting.py','hospitality_suite/payment_policies.py','hospitality_suite/service_accounting.py','hospitality_suite/treasury.py','hospitality_suite/reports.py','hospitality_suite/security.py','hospitality_suite/hooks.py']
assert all((ROOT/name).is_file() for name in documents+sources)
financial_classes=['TestInitialSetup','TestFinance','TestFinancialAudit','TestAppliedRefunds','TestGuaranteeRefunds','TestServiceAccounting','TestTreasury','TestCloseFinancials']
assert all(classes[name]>0 for name in financial_classes)
guides=dict(review_date='2026-10-21',requirements=['S18-06','S18-07','S18-08','S18-09'],artifact_review_only=True,
    scope='Delivery and consistency of the Spanish guides; not completion of every described flow or final deployment/rollback.',
    review_document='docs/ENTREGABLES_Y_REVISION.md',documents={name:digest(ROOT/name) for name in documents},reviewed_sources={name:digest(ROOT/name) for name in sources},
    cli_evidence='delivery-review-cli.json',cli_sha256=digest(EVIDENCE/'delivery-review-cli.json'),native_commands_checked=13,
    native_junit='keyboard-review-native-tests.xml',native_junit_sha256=digest(EVIDENCE/'keyboard-review-native-tests.xml'),financial_classes_passed={name:classes[name] for name in financial_classes},
    manual_ui_evidence='keyboard-review-roles-ui.json',manual_ui_sha256=digest(EVIDENCE/'keyboard-review-roles-ui.json'),manual_roles_observed=sorted(actors),
    restoration_evidence='keyboard-review-upgrade.json',restoration_sha256=digest(EVIDENCE/'keyboard-review-upgrade.json'),final_deployment_rollback_proven=False,database_mutations=False)
write('delivery-review-guides.json',guides)
print(json.dumps(dict(native=380,javascript=174,ui_roles=len(actors),screenshots=len(images),guide_requirements=guides['requirements'],restoration_verified=True),ensure_ascii=False))
