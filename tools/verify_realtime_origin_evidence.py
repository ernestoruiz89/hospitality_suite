"""Read-only evidence gate for named local origins; does not replay UI or restore."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
source=Path('C:/Users/Ernesto/Downloads/Prompt_Codex_Hoteles_Moteles_Frappe_ERPNext.txt')
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
assert sha(source)==audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
assert len(audit['items'])==218 and Counter(row['status'] for row in audit['items'])=={'V':200,'I':6,'R':12}
original=source.read_text(encoding='utf-8-sig')
assert all(row['requirement'] in original for row in audit['items'])
hosts=read('realtime-origins-hosts.json')
assert hosts['existing_bytes_preserved'] and hosts['second_execution_unchanged']
assert set(hosts['dns_after'])=={'hospitality.localhost','hospitality-acceptance.localhost'}
assert all(value==['127.0.0.1'] for value in hosts['dns_after'].values())
assert all(value=={'error_code':-2} for value in hosts['dns_before'].values())
log=(E/'realtime-origins-hosts-tests.log').read_text(encoding='utf-8')
assert 'Ran 5 tests' in log and '\nOK\n' in log and 'FAILED' not in log
transport=read('realtime-origins-transport.json')
assert transport['authenticated_socket_sessions']==5 and transport['main_business_writes']==0
assert transport['main_origin']=='http://hospitality.localhost:8086' and transport['acceptance_origin']=='http://hospitality-acceptance.localhost:8089'
assert transport['main_distinct_users']==2 and transport['acceptance_roles']==['HS Receptionist','HS Cashier']
assert all(transport[key]==0 for key in ['other_property_events','cross_site_events','before_commit_events','after_rollback_events','provider_requests'])
assert transport['payload_keys']==['property'] and transport['acceptance_committed_test_guests']==3
assert all(transport[key] for key in ['disconnect','reconnect','missed_commit_recovered_by_native_bootstrap','event_after_reconnect'])
browser=read('realtime-origins-browser.json');events={row['stage']:row for row in browser['events']}
before=events['before_api_stay'];first=events['after_first_api_commit_without_refresh']
assert before['reception']['occupied']==0 and 'Abierto' not in before['cashier']['text']
assert first['reception']['occupied']==1 and 'Abierto' in first['cashier']['text']
for row in [before,first,events['recovered_after_actualizar']]:
    assert row['reception']['connection']==row['cashier']['connection']=='● Tiempo real conectado'
for key in ['socket_service_cut','committed_during_cut','service_restarted_before_manual_action']:
    row=events[key];assert row['reception']['occupied']==1
    assert row['reception']['connection']==row['cashier']['connection']=='Sin tiempo real · pulse Actualizar'
    assert 'Abierto' in row['cashier']['text']
recovered=events['recovered_after_actualizar']
assert recovered['reception']['rooms']==['H101','H102'] and recovered['reception']['occupied']==2
assert 'Cerrado' in recovered['cashier']['text'] and 'Abierto' not in recovered['cashier']['text']
assert len(recovered['manual_actions'])==2 and browser['business_mutations_submitted_from_ui']==0
assert browser['ui_sessions']==2 and browser['ui_user_role']=='HS Manager in both UI tabs'
assert browser['automatic_refresh_before_cut']
data=read('realtime-origins-ui-data.json');assert data['api_fixture_stays']==2 and not data['ui_created_operations']
assert data['counts']=={'HS Stay':2,'HS Booking':2,'HS Charge':2,'HS Payment':0,'HS Shift':1,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0}
restored=read('realtime-origins-ux-restored.json');assert restored['restored'] and restored['tables']==71 and restored['rows']==185
preserved=read('realtime-origins-upgrade.json');assert preserved['previous_columns_preserved']
assert preserved['sites']=={'hospitality.localhost':{'tables':72,'rows':1246,'private_files':2},'hospitality-acceptance.localhost':{'tables':72,'rows':250,'private_files':0}}
state=read('realtime-origins-final-state.json')
assert state['main_http']==200 and state['main']['business_date']=='2026-10-19' and not any(state['acceptance']['operation_counts'].values())
assert state['ports']=={'8086':True,'8089':False,'9001':True,'11001':True,'13001':True}
cores={}
for app in ['frappe','erpnext']:
    command=['wsl','-d','Ubuntu-24.04','-u','frappe','--','git','-C','/home/frappe/benches/hospitality-bench/apps/'+app]
    assert not subprocess.check_output(command+['status','--porcelain'],text=True).strip()
    cores[app]=subprocess.check_output(command+['rev-parse','HEAD'],text=True).strip()
names=['tools/configure_local_hosts.py','tools/test_local_hosts.py','tools/run_dev.py','tools/realtime_origin_probe.py','tools/verify_realtime_origins.cjs',
       'tools/print_delivery_server.py','tools/service_ux.py','tools/periodic_upgrade.py','tools/verify_acceptance_site.py','tools/verify_realtime_origin_evidence.py',
       'README.md','docs/OPERACION.md','docs/AVANCE.md','docs/PENDIENTES.md','docs/REQUISITOS.md','docs/specification-audit.json','docs/TIEMPO_REAL_SITIOS_LOCALES.md']
names += [path.relative_to(ROOT).as_posix() for path in E.glob('realtime-origins-*') if path.name!='realtime-origins-verification.json']
names += [path.relative_to(ROOT).as_posix() for path in E.glob('*.png') if path.name[:3].isdigit() and 344<=int(path.name[:3])<=351]
assert len([name for name in names if re.match(r'docs/evidence/\d{3}-',name)])==8
proof=dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),requirement='S04-18',status_preserved='V',
           specification_sha256=audit['sha256'],requirements=218,statuses=dict(Counter(row['status'] for row in audit['items'])),open_entries=18,
           target_versions={'frappe':'16.52.0','erpnext':'16.51.1','hospitality_suite':'0.8.7'},clean_core_commits=cores,
           named_origin_authenticated_sockets=5,local_host_helper_tests=5,ui_sessions=2,ui_user_role='HS Manager',
           automatic_refresh_when_connected=True,long_cut_recovery='Explicit Actualizar after native retries exhausted',
           main_business_mutations=0,acceptance_restored=True,source_and_evidence_sha256={name:sha(ROOT/name) for name in sorted(set(names))},
           full_native_or_js_suite_rerun=False,ui_replay=False,all_requirements_completed=False,external_providers_activated=False,ota_sync_deferred_by_user=True)
(E/'realtime-origins-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(authenticated_sockets=5,helper_tests=5,ui_sessions=2,preserved_main_rows=1246,restored=True,open_entries=18,all_requirements_completed=False)))
