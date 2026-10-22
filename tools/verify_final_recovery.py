"""Verify the coordinated deployment rehearsal and final native regressions."""
from datetime import datetime,timezone
import hashlib,json,socket,subprocess,urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence'
BENCH=Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
MAIN=Path('/home/frappe/benches/hospitality-bench')
PRIVATE=Path('/home/frappe/.hospitality-final-recovery')
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
state=json.loads((PRIVATE/'state.json').read_text())
candidate=read('f26-candidate-package.json');environment=read('f26-candidate-environment.json')
assert candidate['revision']==environment['candidate_package_revision']==state['current_revision']
assert candidate['app_version']=='0.8.9' and candidate['application_files']==332
assert environment['installed_versions']=={'frappe':'16.52.0','erpnext':'16.51.1','hospitality_suite':'0.8.9'}
assert environment['independent_app_code_python_assets_redis_database']
for name,digest in environment['application_file_sha256'].items():
    assert sha(ROOT/name)==sha(BENCH/'apps/hospitality_suite'/name)==digest
assert subprocess.check_output(['git','diff','--name-only','bcfcf09',candidate['revision'],'--','hospitality_suite'],cwd=ROOT,text=True).splitlines()==['hospitality_suite/__init__.py']
counts=read('f26-previous-data-baseline.json')['counts']
assert (counts['HS Booking'],counts['HS Stay'],counts['Sales Invoice'],counts['GL Entry'])==(23,5,7,66)
for label,version in [('upgraded-current','0.8.9'),('migration-repeat-identical','0.8.9'),('upgraded-after-ui','0.8.9'),
    ('recovered-previous','0.8.8'),('recovered-after-ui','0.8.8'),('redeployed-current','0.8.9')]:
    proof=read('f26-'+label+'.json')
    assert proof['counts']==counts and proof['version']==version
    assert proof['tables']==72 and proof['rows']==1246 and proof['private_files']==2
    assert proof['all_business_rows_and_columns_identical'] and proof['all_physical_files_identical']
for key in ['original_backup','baseline_backup','failed_backup']:
    for name,digest in state[key]['files'].items():assert sha(BENCH/'sites/hospitality-release.localhost/private/backups'/name)==digest
failed=read('f26-failed-state-scope.json')
assert set(failed['changed_compared_tables'])=={'File','HS Property','Version'}
assert failed['financial_and_operational_counts_preserved'] and failed['all_original_file_bytes_preserved']
assert (failed['original_physical_files'],failed['failed_state_physical_files'],failed['new_File_records'])==(13,15,1)
assert len(failed['new_physical_probe_files'])==2
for relative,digest in state['original']['physical_files'].items():
    kind,name=relative.split('/files/',1)
    assert sha(PRIVATE/'restore-source-copy-media'/kind/name)==digest
for relative,digest in state['failed_fingerprint']['physical_files'].items():
    kind,name=relative.split('/files/',1)
    assert sha(PRIVATE/'rollback-database-and-files-media'/kind/name)==digest
assert sha(Path(state['fault']['preserved']))==state['fault']['sha256']
assert len(state['native_test_files'])==14
for relative,digest in state['native_test_files'].items():
    kind,name=relative.split('/files/',1)
    assert sha(PRIVATE/'restore-original-release-media'/kind/name)==digest
first=read('f26-upgraded-http.json');fault=read('f26-failed-http-gate.json');recovered=read('f26-recovered-previous-http.json')
assert first['results'][first['bundle']]['status']==recovered['results'][recovered['bundle']]['status']==200
assert fault['results'][fault['bundle']]['status']==404 and first['bundle']!=recovered['bundle']
browser=read('f26-browser.json');events={row['label']:row for row in browser['events']}
assert len(events)==7
for label,text in [('upgraded-booking-detail','C$ 1,500.00'),('recovered-previous-stay-account','C$ 3,100.00')]:
    assert text in events[label]['text'] and 'receptionist@hospitality.example.invalid' in events[label]['text']
assert any(first['bundle'] in url for url in events['upgraded-booking-detail']['bundle'])
assert any(recovered['bundle'] in url for url in events['recovered-previous-stay-account']['bundle'])
empty=read('f26-uninstall-only-empty-app.json')
assert not any(empty['empty_business_counts_before_uninstall'].values()) and empty['native_framework_File_folders']==2
clean=read('f26-clean-install.json')
assert clean['app_version']=='0.8.9' and clean['app_revision']==candidate['revision']
assert clean['no_implicit_demo'] and not any(clean['empty_business_counts'].values())
assert (clean['doctypes'],clean['pages'],clean['roles'])==(35,11,9)
assert len(clean['print_formats'])==9 and len(clean['patches'])==6 and len(clean['api_methods'])==28
run=read('final-recovery-native-run.json')
assert (run['tests'],run['integration'],run['unit'])==(410,378,32)
assert run['site']=='hospitality-release.localhost' and not any(run[k] for k in ['exit_code','failures','errors','skipped'])
xml=ET.parse(E/'final-recovery-native-tests.xml').getroot()
assert len(xml.findall('.//testcase'))==410 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
assert run['raw_log_sha256']==sha(ROOT/'.local/final-recovery/native-full-1.log')
js=read('f26-js-run.json');assert js['exit_code']==0 and js['tests']==js['pass_count']==232 and not js['failures']
assert js['native_log_sha256']==sha(PRIVATE/'javascript-full-tap.log')
restored=read('f26-original-release-restored.json')
assert restored['original_release_rows_and_bytes_restored'] and restored['original_physical_files']==21 and restored['current_version']=='0.8.9'
assert restored['registered_versions']['hospitality_suite']=='0.8.9'
primary=read('f26-primary-upgrade.json')
assert all(versions=={'frappe':'16.52.0','erpnext':'16.51.1','hospitality_suite':'0.8.9'} for versions in primary['sites'].values())
launcher=read('f26-launcher.json')
assert launcher['exit_code']==0 and launcher['existing_managed_pids_preserved'] and launcher['managed_process_count']==4
assert launcher['health_check_context']=='WSL' and launcher['http_status']==200 and launcher['message']=='pong'
config=json.loads((BENCH/'sites/hospitality-release.localhost/site_config.json').read_text())
assert config['pause_scheduler'] and config['db_name']=='hospitality_release'
assert config.get('encryption_key')==state['original_config'].get('encryption_key')
upgrade=read('final-recovery-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
ports={}
for port in [8086,8089,8091,9001,9003,11001,13001,11003,13003]:
    with socket.socket() as conn:
        conn.settimeout(.3);ports[str(port)]=conn.connect_ex(('127.0.0.1',port))==0
assert {p for p,on in ports.items() if on}=={'8086','9001','11001','13001'}
for bench in [MAIN,BENCH]:
    for app in ['frappe','erpnext']:assert not subprocess.check_output(['git','status','--porcelain'],cwd=bench/'apps'/app)
assert not subprocess.check_output(['git','status','--porcelain'],cwd=BENCH/'apps/hospitality_suite')
with urllib.request.urlopen('http://hospitality.localhost:8086/api/method/ping',timeout=10) as response:assert response.status==200
primary_assets=json.loads((MAIN/'sites/assets/assets.json').read_text());primary_bundle=primary_assets['hospitality.bundle.js']
accepted=read('privacy-portal-verification.json');main_browser=read('f26-main-browser.json')
assert primary_bundle==accepted['bundle'] and any(primary_bundle in url for url in main_browser['bundle'])
assert 'receptionist@hospitality.example.invalid' in main_browser['text'] and 'Tiempo real conectado' in main_browser['text']
with urllib.request.urlopen('http://hospitality.localhost:8086'+primary_bundle,timeout=10) as response:
    served_sha256=hashlib.sha256(response.read()).hexdigest()
assert served_sha256==accepted['served_bundle_sha256']==sha((MAIN/'sites'/primary_bundle.lstrip('/')).resolve())
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
statuses=__import__('collections').Counter(row['status'] for row in audit['items'])
assert len(audit['items'])==218 and statuses=={'V':214,'I':4}
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),F26_coordinated_recovery_verified=True,
    previous_revision=state['previous_revision'],candidate_revision=state['current_revision'],versions=['0.8.8','0.8.9'],
    source_copy=dict(tables=72,rows=1246,private_files=2,physical_files=13),
    original_release_restored=True,original_release_physical_files=21,native_test_files_archived=14,failed_state_preserved=True,
    native=dict(tests=410,integration=378,unit=32,errors=0,failures=0,skipped=0),javascript=dict(tests=232,exit_code=0),
    browser=dict(role='HS Receptionist',observations=7,read_only_smoke=True,full_operational_GUI_acceptance_reference='privacy-portal-task-acceptance.json'),
    initial_clean_install_of_current_version_verified=True,main_and_acceptance_business_data_preserved=True,
    ports=ports,primary_bundle=primary_bundle,primary_served_bundle_sha256=served_sha256,
    external_OTA_sync_deferred_by_user=True,final_package_and_completion_audit_still_required=True,
    requirement_statuses=dict(statuses),audit_sha256=sha(ROOT/'docs/specification-audit.json'),
    manual_WSL_launcher_verified=True,
    references_sha256={p.name:sha(p) for p in E.glob('f26-*') if p.name!='f26-verification.json'})
(E/'f26-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(F26=True,native=410,javascript=232,original_release_restored=True,final_package_pending=True)))
