"""Verify the scope and references of phase review; no new UI or full-suite claim."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from specification_audit import inventory

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
source=Path('C:/Users/Ernesto/Downloads/Prompt_Codex_Hoteles_Moteles_Frappe_ERPNext.txt')
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
assert sha(source)==audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
assert [(row['id'],row['line'],row['requirement']) for row in audit['items']]==[(row['id'],row['line'],row['requirement']) for row in inventory(source)]
states=Counter(row['status'] for row in audit['items']);assert states==Counter(V=208,I=10)
expected_open={'S00-01','S00-02','S01-12','S04-14','S04-16','S04-20','S18-01','S19-02','S19-07','S19-08'}
assert {row['id'] for row in audit['items'] if row['status']!='V'}==expected_open
assert all(row['implementation'] and row['evidence'] and row['remaining'] for row in audit['items'] if row['status']=='I')
crosswalk=read('phase-review-crosswalk.json')
verified={'S19-01','S19-03','S19-04','S19-05','S19-06','S19-09'}
assert {key for key,row in crosswalk['phases'].items() if row['reviewed_status']=='V'}==verified
for key,row in crosswalk['phases'].items():
    current=next(item for item in audit['items'] if item['id']==key)
    assert current['status']==row['reviewed_status'] and current['remaining']==row['remaining']
    assert row['basis'] and row['implementation'] and row['evidence']
    if current['status']=='V':assert not current['remaining']
for name,digest in crosswalk['source_and_evidence_sha256'].items():assert sha(ROOT/name)==digest,name
assert crosswalk['application_matches_executed_revision']=='fb8c022' and crosswalk['application_version']=='0.8.8'
assert crosswalk['native_execution']['tests']==404 and crosswalk['client_execution']['tests']==210
assert not any(crosswalk[name] for name in ['ui_replay','full_suite_rerun','new_backup_or_restore','external_providers_activated','all_requirements_completed'])
native=ET.parse(E/'provider-contracts-native-tests.xml').getroot()
assert len(native.findall('.//testcase'))==404 and not any(native.findall('.//'+name) for name in ['error','failure','skipped'])
artifacts=read('phase-review-native-artifacts.json');assert artifacts['version']=='0.8.8'
assert all((row['doctypes'],row['pages'],row['print_formats'],row['patches'])==(35,11,9,6) for row in artifacts['sites'].values())
architecture=read('phase-review-architecture.json')
assert architecture['app_version']=='0.8.8' and len(architecture['model'])==35 and len(architecture['pages'])==11 and len(architecture['roles'])==9
assert all(row['clean'] for row in architecture['core'].values())
preserved=read('phase-review-preservation.json')
assert preserved['sites']['hospitality.localhost']==dict(tables=72,rows=1246,private_files=2,exact_match=True,business_date='2026-10-19')
assert preserved['sites']['hospitality-acceptance.localhost']==dict(tables=72,rows=250,private_files=0,exact_match=True)
assert preserved['main_http']==200 and not preserved['ports']['8089'] and not preserved['database_mutations']
names=['tools/verify_phase_review.py','tools/verify_delivery_status.py','tools/review_implementation_phases.py','tools/audit_operational_actions.cjs',
       'tools/verify_architecture.py','tools/verify_native_artifacts.py','tools/verify_phase_preservation.py','README.md',
       'docs/REVISION_FASES_Y_ACCIONES.md','docs/AVANCE.md','docs/PENDIENTES.md','docs/REQUISITOS.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md',
       'docs/specification-audit.json','docs/AUDITORIA_ESPECIFICACION.md']
names += [path.relative_to(ROOT).as_posix() for path in E.glob('phase-review-*') if path.name!='phase-review-verification.json']
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),application_version='0.8.8',specification_sha256=audit['sha256'],entries=218,
           statuses={key:states[key] for key in ['V','I','P','R']},open_entries=10,verified_phase_entries=sorted(verified),remaining_entries=sorted(expected_open),
           application_matches_executed_revision='fb8c022',native=dict(tests=404,reused_execution=True),javascript=dict(tests=210,reused_execution=True),
           current_checks=['bundle action/RPC/command bindings','native environment/model/indexes','installed metadata both sites','protected data and files'],
           sources_sha256={name:sha(ROOT/name) for name in sorted(set(names))},ui_replay=False,full_suite_rerun=False,
           database_mutations=False,new_backup_or_restore=False,external_providers_activated=False,ota_sync_deferred_by_user=True,all_requirements_completed=False)
(E/'phase-review-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(statuses=proof['statuses'],open_entries=10,phase_entries_verified=6,application_code_unchanged=True,all_requirements_completed=False)))
