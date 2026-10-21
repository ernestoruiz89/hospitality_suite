"""Assemble 0.8.7 evidence with scope checks; never replay UI or mutate databases."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence';L=ROOT/'.local/print-delivery'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8-sig'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
trace=read('print-delivery-browser.json')
assert len(trace['events'])==22 and trace['viewport_override_reset'] and trace['intermediate_defects_preserved']
assert set(trace['roles'])=={'HS Receptionist','HS Cashier','HS Housekeeping','HS Maintenance','HS Manager'}
assert trace['final_bundle']=='hospitality.bundle.TFVL2SJI.js'
views=[row for row in trace['events'] if row.get('format')]
assert len(views)==11
families={row['format'].replace('-final','').replace('-mobile','') for row in views}
assert families=={'reservation','registration','folio','invoice','receipt','shift','cleaning','maintenance','daily_close'}
for row in views:
    parsed=urlparse(row['observed']['url'])
    assert parsed.netloc=='hospitality-acceptance.localhost:8089' and parsed.path=='/printview'
    assert set(parse_qs(parsed.query))=={'doctype','name','format'} and row['observed']['pdfLink']
    assert 'No permitido' not in row['observed']['text'] and 'Hotel Jardín Demo' in row['observed']['text']
registration=next(row for row in views if row['format']=='registration')['observed']['text']
assert 'Sin acompañantes registrados.' in registration
folio=next(row for row in views if row['format']=='folio')['observed']['text']
assert 'C$ 1,000.00' in folio and 'Cálculo histórico' not in folio
events={row['screenshot']:row for row in trace['events'] if row.get('screenshot')}
first=events['331-boton-cuenta-deshabilitado-defecto.jpg']['observed']
assert first['actionState']['pageBusy']=='false' and first['actionState']['buttons']==[{'text':'Ver estancia y cuenta','disabled':True}]
assert events['332-boton-recreado-defecto.jpg']['observed']['bundle'].endswith('hospitality.bundle.VBL4AU4J.js')
assert events['333-impresiones-recepcion-desde-cuenta.jpg']['observed']['bundle'].endswith(trace['final_bundle'])
assert 'Imprimir registro de huésped' in events['333-impresiones-recepcion-desde-cuenta.jpg']['snapshot']
assert 'print_registration' not in events['335-factura-desde-estancia-caja.jpg']['snapshot']
assert all(not button['disabled'] for button in events['335-factura-desde-estancia-caja.jpg']['observed']['buttons'])
mobile=events['337-imprimir-limpieza-movil-390.jpg']['observed']
assert mobile['width']==mobile['documentWidth']==390 and mobile['printButton'][0]['disabled'] is False
assert 0<=mobile['printButton'][0]['top']<mobile['printButton'][0]['bottom']<=844
assert events['336-imprimir-limpieza-escritorio.jpg']['observed']['width']==1280
items=read('print-delivery-ui-data.json')
assert items['print_access_only'] and not items['operations_created_by_ui'] and items['business_documents_unchanged_by_print_review']
assert items['operation_counts']=={dt:1 for dt in ['HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','HS Cleaning Task','HS Maintenance Order','HS Daily Close','Sales Invoice','Payment Entry']}|{'Journal Entry':0}
native=ET.parse(E/'print-delivery-native-tests.xml').getroot()
assert len(native.findall('.//testcase'))==386 and not any(native.findall('.//'+key) for key in ['failure','error','skipped'])
assert sum('TestPrintDelivery' in row.get('classname','') for row in native.findall('.//testcase'))==6
raw=(E/'print-delivery-native-tests.log').read_text(encoding='utf-8')
assert 'Ran 372 tests' in raw and 'Ran 14 tests' in raw and raw.count('\nOK\n')==2 and 'FAILED' not in raw
js=(E/'print-delivery-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(r'\b'+key+r'\s+'+str(value)+r'\b',js) for key,value in [('tests',210),('pass',210),('fail',0),('skipped',0),('cancelled',0)])
build=(E/'print-delivery-build.log').read_text(encoding='utf-8')
assert 'hospitality.bundle.TFVL2SJI.js' in build and 'hospitality.bundle.WZFA272S.css' in build and 'DONE' in build
wire=read('print-delivery-wire-invariants.json')
assert wire['baseline'].startswith('b5e67b1') and len(wire['files'])==30 and all(row['unchanged'] for row in wire['files'])
artifacts=read('print-delivery-native-artifacts.json')
assert artifacts['version']=='0.8.7' and not artifacts['database_mutations'] and len(artifacts['api_methods'])==28
assert set(artifacts['sites'])=={'hospitality.localhost','hospitality-acceptance.localhost'}
for row in artifacts['sites'].values():
    assert (row['doctypes'],row['pages'],row['print_formats'],row['patches'])==(35,11,9,6)
for name,digest in artifacts['source_sha256'].items():assert sha(ROOT/name)==digest,name
pdfs=read('print-delivery-pdfs.json');structure=read('print-delivery-pdf-structure.json')
assert len(pdfs['files'])==len(structure)==9 and sum(row['pages'] for row in structure)==10
assert pdfs['business_tables_equal_after_rollback'] and not pdfs['documents_committed'] and not pdfs['persisted_host_configuration_changed']
assert {row['file']:row['pages'] for row in structure}=={name+'.pdf':2 if name=='daily_close' else 1 for name in families}
for row in pdfs['files']:
    path=ROOT/row['file'];assert sha(path)==row['sha256'] and path.stat().st_size==row['bytes']
    pages=PdfReader(path).pages;assert all(len(page.extract_text().strip())>80 for page in pages)
restored=read('print-delivery-ux-restored.json');assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
upgrade=read('print-delivery-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites']=={'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('print-delivery-final-state.json')
assert state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True} and state['main_http']==200
assert state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
language=read('print-delivery-language-installed.json');assert (language['desk_modules'],language['portal_modules'])==(29,1)
versions=[]
for site,migration in [('main','migrate-main.log'),('acceptance','migrate-restored.log')]:
    listing=L/f'list-{site}.log';assert re.search(r'hospitality_suite\s+0\.8\.7\b',listing.read_text(encoding='utf-8-sig'))
    text=(L/migration).read_text(encoding='utf-8-sig');assert 'Updating installed applications...' in text and 'Executing `after_migrate` hooks...' in text and 'Traceback' not in text
    versions.append(dict(site=site,version='0.8.7',listing_sha256=sha(listing),migration_sha256=sha(L/migration)))
core={}
for app in ['frappe','erpnext']:
    cmd=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C','/home/frappe/benches/hospitality-bench/apps/'+app]
    core[app]=dict(commit=subprocess.check_output([*cmd,'rev-parse','HEAD'],text=True).strip(),clean=not subprocess.check_output([*cmd,'status','--porcelain'],text=True));assert core[app]['clean']
audit=read('../specification-audit.json');counts=dict(Counter(row['status'] for row in audit['items']))
assert len(audit['items'])==218 and counts=={'R':12,'I':6,'V':200}
assert read('delivery-review-matrix.json')['audit_sha256']==sha(ROOT/'docs/specification-audit.json')
assert all(next(row for row in audit['items'] if row['id']==identifier)['status']=='V' for identifier in ['S18-02','S18-03'])
images=[]
for number in range(320,340):
    paths=[*E.glob(str(number)+'-*.png'),*E.glob(str(number)+'-*.jpg')];assert len(paths)==1
    path=paths[0];assert path.read_bytes().startswith(b'\x89PNG' if path.suffix=='.png' else b'\xff\xd8')
    images.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),scope='Native PDF render' if number<330 else 'Observed defect' if number in [331,332] else 'Initial L7TWF4HE Page' if number==330 else 'Final TFVL2SJI Page',bytes_unchanged=True))
references=['print-delivery-'+name for name in ['browser.json','ui-data.json','native-tests.xml','native-tests.log','js-tests.log','build.log',
 'pdfs.json','pdf-structure.json','native-artifacts.json','wire-invariants.json','ux-restored.json','upgrade.json','final-state.json','language-installed.json']]
sources=['hospitality_suite/'+name for name in ['__init__.py','printing.py','public/js/hospitality.js','public/js/hospitality_workflows.js','public/js/hospitality_housekeeping.js','tests/test_print_delivery.py']]
sources+=['tools/'+name for name in ['test_print_delivery_ui.cjs','test_desk_transport.cjs','test_housekeeping_ui.cjs','verify_print_delivery.py','verify_native_artifacts.py','verify_delivery_status.py','print_delivery_fixture.py','print_delivery_qa.py','print_delivery_server.py']]
sources+=['docs/IMPRESIONES_OPERATIVAS.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md','docs/specification-audit.json']
bundles=list((ROOT/'hospitality_suite/public/dist/js').glob('hospitality.bundle.*.js'));assert len(bundles)==1 and bundles[0].name=='hospitality.bundle.TFVL2SJI.js'
proof=dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(),version='0.8.7',requirements=['S18-02','S18-03'],evidence_assembly_only=True,database_mutations=False,ui_replay=False,
 scope='Installed native artifacts and operational print access; not full acceptance of all tasks or final deployment.',
 javascript=dict(tests=210,desk=207,portal=3,new_cases=7,failures=0,skipped=0),native=dict(tests=386,integration=372,pure=14,new_cases=6,rerun_in_this_phase=True),
 ui=dict(events=22,roles=5,print_families=9,fixture_created_by='Native APIs',scope='Print access only',final_bundle=trace['final_bundle'],intermediate_defects_preserved=True,mobile_width=390),
 pdfs=dict(files=9,pages=10,manual_render_review=True,account_pages=1,close_pages=2),native_versions=versions,core=core,statuses=counts,open_requirements=18,all_requirements_completed=False,
 protected_sites=upgrade['sites'],final_services=state['ports'],source_sha256={name:sha(ROOT/name) for name in sources},references={name:sha(E/name) for name in references},screenshots=images,
 raw_command_outputs={name:sha(L/name) for name in ['native-targeted.log','native-full.log','native-complete.log','js.log','js-history.log','js-owned-actions.log','js-reinserted-actions.log','build-final.log','build-owned-actions.log','build-reinserted-actions.log']},
 compiled_javascript=dict(name=bundles[0].name,sha256=sha(bundles[0])),external_providers_activated=False,ota_sync_deferred_by_user=True,final_deployment_rollback_proven=False)
(E/'print-delivery-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(native=386,javascript=210,ui_events=22,pdf_files=9,pdf_pages=10,statuses=counts,open_requirements=18)))
