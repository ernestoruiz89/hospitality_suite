"""Verify 0.8.6 evidence delivery/list scope; no claim the app is complete."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,re,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence';OUTPUT=E/'delivery-status-review.json'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'));counts=dict(Counter(row['status'] for row in audit['items']))
assert len(audit['items'])==218 and counts=={'R':14,'I':6,'V':198}
phase=json.loads((E/'friendly-links-verification.json').read_text(encoding='utf-8'));assert phase['javascript']['tests']==203 and not phase['all_requirements_completed']
native=ET.parse(E/'keyboard-review-native-tests.xml').getroot();assert len(native.findall('.//testcase'))==380
assert not any(native.findall('.//'+key) for key in ('failure','error','skipped'))
raw=(E/'keyboard-review-native-tests.log').read_text(encoding='utf-8');assert 'Ran 366 tests' in raw and 'Ran 14 tests' in raw and raw.count('\nOK\n')==2
references={}
for name in ['docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md','docs/ACTIVIDAD_Y_RECUPERACION_PAGES.md','docs/SELECTORES_Y_RESERVA_MANUAL.md']:
    path=ROOT/name;content=path.read_text(encoding='utf-8');references[name]=sha(path)
    for target in re.findall(r'\]\(([^)]+)\)',content):
        resolved=(path.parent/target.partition('#')[0]).resolve()
        assert resolved.is_relative_to(ROOT)
        if resolved==OUTPUT:continue # This document links to the receipt being assembled.
        assert resolved.is_file(),target
        references[resolved.relative_to(ROOT).as_posix()]=sha(resolved)
    assert 'S18-11' in content and 'S18-12' in content
for row in audit['items']:
    if row['id'] in ['S18-11','S18-12']:assert row['status']=='V' and not row['remaining']
assert all(row['remaining'] for row in audit['items'] if row['status']!='V')
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),requirements=['S18-11','S18-12'],scope='Delivered evidence and differentiated status list, not proof of overall app completion.',
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),statuses=counts,
    verified_ids=[row['id'] for row in audit['items'] if row['status']=='V'],open_entries=[dict(id=row['id'],status=row['status'],remaining=row['remaining']) for row in audit['items'] if row['status']!='V'],
    current_javascript=dict(tests=203,desk=200,portal=3,phase='0.8.6',executed_log_sha256=sha(E/'friendly-links-js-tests.log')),
    historical_native=dict(tests=380,integration=366,pure=14,phase='0.8.2',revision='beac44d',rerun_in_current_phase=False,junit_sha256=sha(E/'keyboard-review-native-tests.xml'),raw_output_sha256=sha(E/'keyboard-review-native-tests.log')),
    current_ui=dict(events=14,intermediate_bundles=['7GSBLVX5','KLCLM4FU','2ID7RQ6C'],workflow_bundle='P3YHSTYY',installed_bundle='DYBXC4MH',
        final_readonly_checks=['friendly-links-final-presentation.json','friendly-links-final-colors.json'],workflow_repeated_on_installed_bundle=False,
        intermediate_defects_preserved=True,limitations_preserved=True),
    references_sha256=references,database_mutations=False,ui_replay=False,all_requirements_completed=False,external_providers_activated=False,ota_sync_deferred_by_user=True)
OUTPUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
assert OUTPUT.is_file();print(json.dumps(dict(requirements=proof['requirements'],references=len(references),open_requirements=20,all_requirements_completed=False)))
