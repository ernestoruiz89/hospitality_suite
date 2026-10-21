"""Check current reference-contract evidence; never activate a provider or replay tests."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

from specification_audit import inventory

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
specification=Path('C:/Users/Ernesto/Downloads/Prompt_Codex_Hoteles_Moteles_Frappe_ERPNext.txt')
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
assert sha(specification)==audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
assert [(row['id'],row['line'],row['requirement']) for row in audit['items']]==[(row['id'],row['line'],row['requirement']) for row in inventory(specification)]
assert len(audit['items'])==218 and Counter(row['status'] for row in audit['items'])=={'V':202,'I':4,'R':12}
for row in audit['items']:
    if row['id'] in ['S14-05','S14-07']:assert row['status']=='V' and row['implementation'] and row['evidence'] and not row['remaining']
    if row['status']!='V':assert row['remaining']
cases=ET.parse(E/'provider-contracts-native-tests.xml').getroot().findall('.//testcase')
assert len(cases)==404 and len({(row.get('classname'),row.get('name')) for row in cases})==404
assert not any(row.find(key) is not None for row in cases for key in ['failure','error','skipped'])
adapter_cases={row.get('name') for row in cases if row.get('classname')=='hospitality_suite.tests.test_provider_adapters.TestProviderAdapters'}
tree=ast.parse((ROOT/'hospitality_suite/tests/test_provider_adapters.py').read_text(encoding='utf-8'))
source_tests={node.name for cls in tree.body if isinstance(cls,ast.ClassDef) and cls.name=='TestProviderAdapters' for node in cls.body if isinstance(node,ast.FunctionDef) and node.name.startswith('test_')}
assert adapter_cases==source_tests and len(adapter_cases)==18
assert {row.get('name') for row in cases}.issuperset({'test_signature_and_expiration','test_receipt_drops_all_provider_content_including_unknown_fields','test_signed_duplicate_is_recorded_once_without_financial_effects'})
raw=(E/'provider-contracts-native-tests.log').read_text(encoding='utf-8')
assert 'Ran 372 tests' in raw and 'Ran 32 tests' in raw and raw.count('\nOK\n')==2
assert not any(value in raw for value in ['FAILED','ResourceWarning','FICTIONAL-PRIVATE-TOKEN'])
focused=(E/'provider-contracts-focused-tests.log').read_text(encoding='utf-8')
assert 'Ran 18 tests' in focused and '\nOK\n' in focused and 'ResourceWarning' not in focused
run=read('provider-contracts-native-run.json')
assert run['tests']==404 and run['integration']==372 and run['unit']==32 and run['exit_code']==0
assert run['source_xml_documents']==2 and run['all_cases_preserved'] and not any(run[key] for key in ['failures','errors','skipped','external_providers_activated'])
js=(E/'provider-contracts-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(r'\b'+key+r'\s+'+str(value)+r'\b',js) for key,value in [('tests',210),('pass',210),('fail',0),('cancelled',0),('skipped',0)])
boundaries=read('provider-contracts-boundaries.json')
assert boundaries['versions']=={'frappe':'16.52.0','erpnext':'16.51.1','hospitality_suite':'0.8.8'}
assert boundaries['adapter_rpc_methods']==0 and boundaries['registered_api_methods']==28
assert boundaries['disabled_transport_rejects_send'] and boundaries['channel_publication_deferred']
assert not any(boundaries[key] for key in ['scheduled_or_business_hook_activation','provider_network_requests','database_mutations','real_vendor_connector_claimed'])
assert all(site['enabled_providers']==0 and not site['credentials_disclosed'] for site in boundaries['sites'].values())
package=ROOT/'hospitality_suite'
production_callers=[]
for path in package.rglob('*.py'):
    if path.name=='provider_adapters.py' or 'tests' in path.relative_to(package).parts:continue
    if 'provider_adapters' in path.read_text(encoding='utf-8'):production_callers.append(path.relative_to(ROOT).as_posix())
assert production_callers==[],'Do not silently activate adapters from production workflows'
sdk_tree=ast.parse((package/'provider_adapters.py').read_text(encoding='utf-8'))
assert not any(node.decorator_list for node in ast.walk(sdk_tree) if isinstance(node,(ast.FunctionDef,ast.ClassDef)))
artifacts=read('provider-contracts-native-artifacts.json')
assert artifacts['version']=='0.8.8' and not artifacts['database_mutations'] and not artifacts['provider_activation']
assert set(artifacts['sites'])=={'hospitality.localhost','hospitality-acceptance.localhost'}
for value in artifacts['sites'].values():
    assert (value['doctypes'],value['pages'],value['print_formats'],value['patches'])==(35,11,9,6)
    assert value['fields_and_permissions_match_source'] and value['scoped_controllers_verified']
for name,digest in artifacts['source_sha256'].items():assert sha(ROOT/name)==digest,name
restored=read('provider-contracts-ux-restored.json');assert restored['restored'] and restored['tables']==71 and restored['rows']==185
upgrade=read('provider-contracts-upgrade.json');assert upgrade['previous_columns_preserved']
assert upgrade['sites']=={'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('provider-contracts-final-state.json')
assert state['main_http']==200 and state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
assert state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
for name in ['provider-contracts-acceptance-migrate.json','provider-contracts-main-migrate.json']:assert read(name)['exit_code']==0
cores={}
for app in ['frappe','erpnext']:
    command=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C','/home/frappe/benches/hospitality-bench/apps/'+app]
    assert not subprocess.check_output(command+['status','--porcelain'],text=True).strip()
    cores[app]=subprocess.check_output(command+['rev-parse','HEAD'],text=True).strip()
sources=['hospitality_suite/provider_adapters.py','hospitality_suite/integrations.py','hospitality_suite/__init__.py','hospitality_suite/tests/test_provider_adapters.py',
         'tools/run_native_tests.py','tools/migrate_isolated_site.py','tools/verify_provider_boundaries.py','tools/verify_provider_contracts.py','tools/verify_native_artifacts.py',
         'tools/verify_delivery_status.py','tools/periodic_upgrade.py','tools/service_ux.py','tools/verify_acceptance_site.py',
         'README.md','docs/API.md','docs/CONTRATOS_PROVEEDORES.md','docs/AVANCE.md','docs/PENDIENTES.md','docs/REQUISITOS.md',
         'docs/specification-audit.json','docs/AUDITORIA_ESPECIFICACION.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md']
sources += [path.relative_to(ROOT).as_posix() for path in E.glob('provider-contracts-*') if path.name!='provider-contracts-verification.json']
proof=dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),version='0.8.8',requirements=['S14-05','S14-07'],
           scope='Prepared reference contract/adapters and clearly simulated tests; no operational vendor integration. Channel outbound synchronization explicitly deferred.',
           specification_sha256=audit['sha256'],entries=218,statuses=dict(Counter(row['status'] for row in audit['items'])),open_entries=16,
           native=dict(tests=404,integration=372,unit=32,new_adapter_cases=18),javascript=dict(tests=210,desk=207,portal=3),
           native_interfaces=dict(doctypes=35,pages=11,print_formats=9,patches=6,rpc=28,new_adapter_rpc=0),
           source_and_evidence_sha256={name:sha(ROOT/name) for name in sorted(set(sources))},clean_core_commits=cores,
           main_data_preserved=True,acceptance_restored=True,real_vendor_connector_claimed=False,external_providers_activated=False,
           ui_replay=False,new_visual_acceptance=False,new_pdf_generated=False,ota_sync_deferred_by_user=True,all_requirements_completed=False)
(E/'provider-contracts-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(native_tests=404,new_reference_cases=18,js_tests=210,statuses=proof['statuses'],open_entries=16,providers_activated=False,all_requirements_completed=False)))
