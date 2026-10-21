"""Verify 0.8.8 evidence delivery/list scope; no claim the app is complete."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,re,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence';OUTPUT=E/'delivery-status-review.json'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'));counts=dict(Counter(row['status'] for row in audit['items']))
assert len(audit['items'])==218 and counts=={'I':8,'V':210}
phase=json.loads((E/'phase-review-verification.json').read_text(encoding='utf-8'));assert phase['javascript']['tests']==210 and not phase['all_requirements_completed']
numeric=json.loads((E/'numeric-review-verification.json').read_text(encoding='utf-8'));assert numeric['javascript']['tests']==215 and numeric['acceptance_restored'] and not numeric['all_requirements_completed']
release=json.loads((E/'release-install-verification.json').read_text(encoding='utf-8'));assert release['clean_install_verified'] and release['real_races']==2 and not release['all_requirements_completed']
native=ET.parse(E/'release-install-native-tests.xml').getroot();assert len(native.findall('.//testcase'))==404
assert not any(native.findall('.//'+key) for key in ('failure','error','skipped'))
raw=(E/'release-install-native-tests.log').read_text(encoding='utf-8');assert 'Ran 372 tests' in raw and 'Ran 32 tests' in raw and raw.count('\nOK\n')==2
references={}
for name in ['docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md','docs/ACTIVIDAD_Y_RECUPERACION_PAGES.md','docs/SELECTORES_Y_RESERVA_MANUAL.md','docs/IMPRESIONES_OPERATIVAS.md','docs/CONTRATOS_PROVEEDORES.md','docs/REVISION_FASES_Y_ACCIONES.md','docs/VALIDACION_NUMERICA.md','docs/INSTALACION_LIMPIA.md']:
    path=ROOT/name;content=path.read_text(encoding='utf-8');references[name]=sha(path)
    for target in re.findall(r'\]\(([^)]+)\)',content):
        resolved=(path.parent/target.partition('#')[0]).resolve()
        assert resolved.is_relative_to(ROOT)
        if resolved==OUTPUT:continue # This document links to the receipt being assembled.
        assert resolved.is_file(),target
        references[resolved.relative_to(ROOT).as_posix()]=sha(resolved)
    if name not in ['docs/IMPRESIONES_OPERATIVAS.md','docs/CONTRATOS_PROVEEDORES.md','docs/REVISION_FASES_Y_ACCIONES.md','docs/VALIDACION_NUMERICA.md','docs/INSTALACION_LIMPIA.md']:assert 'S18-11' in content and 'S18-12' in content
for row in audit['items']:
    if row['id'] in ['S14-05','S14-07','S18-01','S19-02','S18-02','S18-03','S18-11','S18-12']:assert row['status']=='V' and not row['remaining']
assert all(row['remaining'] for row in audit['items'] if row['status']!='V')
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),requirements=['S18-01','S19-02','S18-02','S18-03','S18-11','S18-12'],scope='Package/clean installation, native artifacts, operational prints, delivered evidence and differentiated status list; not proof of overall app completion.',
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),statuses=counts,
    verified_ids=[row['id'] for row in audit['items'] if row['status']=='V'],open_entries=[dict(id=row['id'],status=row['status'],remaining=row['remaining']) for row in audit['items'] if row['status']!='V'],
    current_javascript=dict(tests=215,desk=212,portal=3,phase='release-install',execution_revision='93b4e07',executed_log_sha256=sha(E/'release-install-js-tests.log')),
    current_native=dict(tests=404,integration=372,pure=32,phase='0.8.8',execution_revision=release['native_execution_revision'],rerun=True,independent_bench=True,first_failures_preserved=7,source_comparison_sha256=sha(E/'release-install-environment.json'),junit_sha256=sha(E/'release-install-native-tests.xml'),raw_output_sha256=sha(E/'release-install-native-tests.log')),
    latest_ui=dict(phase='release-install',events=2,roles=1,installed_bundle=release['installed_bundle'],clean_state_restored_before_tests=True,scope='Administrator initial setup and first property through Page only; not complete role acceptance.'),
    historical_native=dict(tests=380,phase='0.8.2',revision='beac44d',superseded_by_current_full_regression=True,junit_sha256=sha(E/'keyboard-review-native-tests.xml')),
    last_print_ui=dict(phase='0.8.7',events=22,roles=5,print_families=9,fixture_created_by='Native APIs',ui_scope='Print access only; not a new visual pass in 0.8.8',
        intermediate_bundles=['L7TWF4HE','VBL4AU4J'],installed_bundle='TFVL2SJI',intermediate_defects_preserved=True,limitations_preserved=True),
    references_sha256=references,database_mutations=False,ui_replay=False,all_requirements_completed=False,external_providers_activated=False,ota_sync_deferred_by_user=True)
OUTPUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
assert OUTPUT.is_file();print(json.dumps(dict(requirements=proof['requirements'],references=len(references),open_requirements=8,all_requirements_completed=False)))
