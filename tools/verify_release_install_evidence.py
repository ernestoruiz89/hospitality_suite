"""Check the clean-install evidence at its actual scope, keeping final acceptance open."""
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
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
git=lambda *args:subprocess.check_output(['git',*args],cwd=ROOT)
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
assert len(audit['items'])==218 and Counter(r['status'] for r in audit['items'])==Counter(V=210,I=8)
assert audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
open_ids={'S00-01','S00-02','S01-12','S04-14','S04-16','S04-20','S19-07','S19-08'}
assert {r['id'] for r in audit['items'] if r['status']!='V'}==open_ids
for key in ['S18-01','S19-02']:
    row=next(r for r in audit['items'] if r['id']==key)
    assert row['status']=='V' and not row['remaining'] and 'docs/INSTALACION_LIMPIA.md' in row['evidence']
package=read('release-install-package-final.json')
assert package['revision'].startswith('3a8d0bf') and package['application_files']==332
assert package['application_bytes_identical'] and package['docs_and_test_tools_in_sdist']
assert package['bench_dependencies']=={'frappe':'>=16.52.0,<17.0.0','erpnext':'>=16.51.1,<17.0.0'}
folder=ROOT/package['output']
for name,expected in package['files'].items():
    path=folder/name
    assert path.is_file() and path.stat().st_size==expected['bytes'] and sha(path)==expected['sha256']
clean=read('release-install-clean.json')
assert clean['app_revision'].startswith('eb0a452') and clean['no_implicit_demo']
assert clean['independent_python_and_source'] and clean['metadata_and_permissions_match']
assert (clean['doctypes'],clean['pages'],clean['roles'],len(clean['print_formats']),len(clean['patches']),len(clean['api_methods']))==(35,11,9,9,6,28)
assert not any(clean['empty_business_counts'].values())
assert clean['bootstrap']==dict(properties=0,pages=11,can_create_property=True)
environment=read('release-install-environment.json')
assert (environment['python'],environment['node'])==('3.14.6','v24.18.0') and environment['mariadb'].startswith('10.11.14-')
assert environment['packaged_revision']==package['revision']
assert environment['sources']['hospitality_suite']['revision'].startswith('be67c92')
assert environment['independent_app_code_python_assets_redis_database'] and environment['shared_os_and_mariadb_service']
changed={name for name,digest in clean['application_files_sha256'].items() if digest!=environment['application_file_hashes'][name]}
assert changed=={'hospitality_suite/tests/'+name for name in ['concurrency.py','setup.py','test_print_delivery.py','test_tariff_explanations.py']}
assert set(environment['only_changes_since_initial_clean_install'])==changed
assert not git('diff','--name-only',package['revision'],'--','hospitality_suite').strip()
assert all(sha(ROOT/name)==digest for name,digest in environment['application_file_hashes'].items())
assert not any(name.endswith(('.js','.cjs','.css')) for name in git('diff','--name-only','93b4e07','--','hospitality_suite/public','tools').decode().splitlines())
first=ET.parse(E/'release-install-native-first-attempt.xml').getroot()
final=ET.parse(E/'release-install-native-tests.xml').getroot()
cases=lambda tree:{(row.get('classname'),row.get('name')) for row in tree.findall('.//testcase')}
assert cases(first)==cases(final) and len(cases(final))==404
assert len(first.findall('.//failure'))==7 and not first.findall('.//error')
assert not any(final.findall('.//'+kind) for kind in ['failure','error','skipped'])
failed=Counter(row.get('classname').rsplit('.',1)[0] for row in first.findall('.//testcase') if row.find('failure') is not None)
assert sorted(failed.values())==[1,6]
native=read('release-install-native-run.json')
assert (native['tests'],native['integration'],native['unit'],native['source_xml_documents'])==(404,372,32,2)
assert not any(native[key] for key in ['exit_code','failures','errors','skipped'])
assert native['site']=='hospitality-release.localhost' and native['all_cases_preserved']
js=(E/'release-install-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(rf'{key} {value}\b',js) for key,value in [('tests',215),('pass',215),('fail',0),('skipped',0)])
setup=read('release-install-state-setup.json')
assert setup['counts']['Company']==setup['counts']['HS Property']==1 and setup['counts']['HS Room']==0
assert not any(read('release-install-state-restored.json')['counts'].values())
ui=read('release-install-setup-browser.json')
assert ui['role']=='Administrator' and ui['explicit_native_setup'] and not ui['setup_demo']
assert 'Prepare su primer establecimiento' in ui['events'][0]['text']
assert 'Hotel de instalación' in ui['events'][1]['text']
assets=json.loads(Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench/sites/assets/assets.json').read_text())
bundle=assets['hospitality.bundle.js']
assert all(any(url.endswith(bundle) for url in event['bundles']) for event in ui['events'])
assert '/setup-wizard/' in read('release-install-first-boot.json')['url']
guard=read('release-install-concurrency-guard-final.json')
assert guard['main_site_rejected'] and not guard['database_mutations']
for name in ['room','category']:
    trial=read(f'release-install-concurrency-{name}.json')
    assert trial['passed'] and trial['site']=='hospitality-release.localhost' and trial['case']==name
    assert sorted(row['result'] for row in trial['sessions'])==['confirmed','rejected']
    assert trial['audited_cleanup_committed'] and trial['active_reservations']==0
    assert trial['source_sha256']==environment['application_file_hashes']['hospitality_suite/tests/concurrency.py']
state=read('release-install-state-after-concurrency.json')
assert (state['counts']['Company'],state['counts']['HS Property'],state['counts']['HS Room'],state['counts']['HS Booking'])==(1,2,20,3)
assert (state['counts']['Stock Entry'],state['counts']['GL Entry'])==(1,2)
assert len(state['explicit_fixture_opening_stock'])==1
assert read('release-install-restore-clean-sites.json')['exit_code']==0
assert read('release-install-migrate-restored.json')['exit_code']==0
for step in ['init-isolated-parent','get-erpnext','create-site','get-app','install-app','migrate','build','backup-clean','test-deps']:
    assert read('release-install-'+step+'.json')['exit_code']==0
assert read('release-install-init.json')['exit_code']==read('release-install-restore-clean.json')['exit_code']==1
preserved=read('release-install-upgrade.json')
assert preserved['previous_columns_preserved'] and preserved['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
health=read('release-install-main-browser.json')
assert health['read_only'] and health['title']=='Reservas' and 'conectado' in health['connection']
ports={}
for port in [8086,9001,11001,13001,8089,8091,9003,11003,13003]:
    with socket.socket() as connection:
        ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert ports=={'8086':True,'9001':True,'11001':True,'13001':True,'8089':False,'8091':False,'9003':False,'11003':False,'13003':False}
with urllib.request.urlopen('http://hospitality.localhost:8086/login') as response:
    assert response.status==200
(E/'release-install-final-state.json').write_text(json.dumps(dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),ports=ports,
    main_http=200,main_authenticated_browser_checked=True,temporary_release_processes_stopped=True,read_only=True),indent=2)+'\n',encoding='utf-8',newline='\n')
references={path.relative_to(ROOT).as_posix():sha(path) for path in E.glob('release-install-*') if path.name!='release-install-verification.json'}
for name in ['356-instalacion-primer-arranque.png','357-instalacion-pms-vacio.png','358-instalacion-primer-hotel.png']:
    assert (E/name).stat().st_size>1000
    references['docs/evidence/'+name]=sha(E/name)
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),requirements=['S18-01','S19-02'],statuses=dict(Counter(r['status'] for r in audit['items'])),
    source_sha256=audit['sha256'],packaged_revision=package['revision'],native_execution_revision=environment['sources']['hospitality_suite']['revision'],
    javascript_execution_revision='93b4e07',javascript=dict(tests=215,desk=212,portal=3),native=dict(tests=404,integration=372,unit=32,skipped=0),
    first_native_failures_preserved=7,all_original_test_cases_retained=True,installed_bundle=Path(bundle).name,real_races=2,one_winner_each=True,
    clean_install_verified=True,first_property_created_through_page=True,main_and_acceptance_preserved=True,
    temporary_release_processes_stopped=True,all_requirements_completed=False,ota_sync_deferred_by_user=True,
    limitations=['Initial setup UI only, not complete role/state acceptance','Shared OS/MariaDB service and declared host PDF binary','Final coordinated code/database/files recovery F26 remains pending'],
    references_sha256=references)
(E/'release-install-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(verified_requirements=proof['requirements'],native=404,javascript=215,real_races=2,open_requirements=8,all_requirements_completed=False)))
