"""Check the bounded role/task review, restored sites and current served assets."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import urllib.request

import frappe

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
BENCH = Path('/home/frappe/benches/hospitality-bench')
read = lambda name: json.loads((E / name).read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
crosswalk = read('task-state-crosswalk.json')
assert len(crosswalk['task_families']) == 22 and crosswalk['handlers'] == 84
assert len(crosswalk['pages']) == 11 and len(crosswalk['hs_roles']) == 9
assert not crosswalk['native_form_navigation_required'] and not crosswalk['all_requirements_completed']
assert crosswalk['native_regression']['tests'] == 404 and not crosswalk['native_regression']['rerun']
assert all(sha(ROOT / name) == digest for name, digest in crosswalk['sources_sha256'].items())
assert all(sha(ROOT / name) == digest for name, digest in crosswalk['unchanged_python_sources_sha256'].items())
log = (E / 'task-state-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(rf'^# {key} {value}$', log, re.M) for key, value in
    [('tests', 221), ('pass', 221), ('fail', 0), ('cancelled', 0), ('skipped', 0), ('todo', 0)])
red = (E / 'task-state-native-numeric-red.log').read_text(encoding='utf-8')
assert '# fail 3' in red and '# pass 2' in red
red = (E / 'task-state-part-label-red.log').read_text(encoding='utf-8')
assert '# fail 1' in red and '# pass 5' in red and 'INTERNAL-PART-KEY' in red
trace = read('task-state-browser.json')
assert set(trace['roles']) == {'HS Manager', 'HS Maintenance', 'HS Supervisor'}
assert trace['last_session_logged_out'] and trace['known_open_observations'] and trace['limitations']
events = {row['label']: row for row in trace['events']}
for label, value in [('manager-integer-exponent-blocked', '1e2'), ('manager-integer-radix-blocked', '0x10')]:
    event = events[label]
    assert event['focused'] == 'capacity' and 'Indique un número entero.' in event['text']
    assert any(row['name'] == 'capacity' and row['value'] == value and row['invalid'] == 'true' for row in event['inputs'])
assert 'No permitido' in events['maintenance-cannot-open-manager-setup']['text']
assert 'No hay pendientes en esta vista.' in events['maintenance-empty']['text']
assert 'Complete Trabajo requerido.' in events['maintenance-required-work-inline']['text']
assert 'No hay artículos que coincidan' in events['maintenance-parts-search-empty']['text']
assert 'Completar y liberar bloqueo' not in events['maintenance-no-release-option']['text']
assert 'Devolver MAT-STE' not in events['maintenance-no-return-option']['text']
assert 'Devolver MAT-STE' in events['manager-return-option-visible']['text']
assert 'Complete Motivo.' in events['manager-return-reason-inline']['text']
assert 'Indique un número válido.' in events['maintenance-decimal-radix-blocked']['text']
assert events['maintenance-decimal-radix-blocked']['focused'] == 'quantity'
assert 'HS-UX-PART-TS × 2' in events['maintenance-parts-issued']['text']
assert 'Válvula de prueba temporal × 2' in events['maintenance-part-name-final']['text']
assert 'HS-UX-PART-TS' not in events['maintenance-part-name-final']['text']
assert 'Completar y liberar bloqueo' in events['supervisor-release-option-visible']['text']
assert 'Bloqueo liberado' in events['supervisor-maintenance-completed']['text']
assert events['supervisor-reception-after-release']['rooms'][0]['canReserve']
assert read('task-state-scalar-database.json')['categories'][0]['capacity'] == 2
issued, returned, completed = [read(f'task-state-{stage}-database.json') for stage in ['issued', 'returned', 'completed']]
assert (issued['quantity'], issued['order']['cost'], issued['part']['native_document_status']) == (8, 40, 1)
assert (returned['quantity'], returned['order']['cost'], returned['part']['native_document_status']) == (10, 0, 2)
assert completed['order']['status'] == 'Completed' and completed['allocations'][0]['status'] == 'Released'
assert completed['incident']['status'] == 'Resolved' and completed['incident']['resolved_by'] == 'manager@hospitality.example.invalid'
assert all(not any(row['financial_operation_counts'].values()) for row in [issued, returned, completed])
assert all(sha(ROOT / name) == digest for row in [returned, completed] for name, digest in row['sources_sha256'].items())

audit = json.loads((ROOT / 'docs/specification-audit.json').read_text(encoding='utf-8'))
counts = Counter(row['status'] for row in audit['items'])
assert len(audit['items']) == 218 and counts == Counter(V=212, I=6)
assert audit['sha256'] == '876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
for key in ['S00-02', 'S04-14']:
    row = next(row for row in audit['items'] if row['id'] == key)
    assert row['status'] == 'V' and not row['remaining']
assert {row['id'] for row in audit['items'] if row['status'] != 'V'} == {'S00-01', 'S01-12', 'S04-16', 'S04-20', 'S19-07', 'S19-08'}
restored = read('task-state-review-ux-restored.json')
assert restored['restored'] and (restored['tables'], restored['rows']) == (71, 185)
preserved = read('task-state-review-upgrade.json')
assert preserved['previous_columns_preserved'] and preserved['sites'] == {
    'hospitality.localhost': dict(tables=72, rows=1246, private_files=2),
    'hospitality-acceptance.localhost': dict(tables=72, rows=250, private_files=0)}
os.chdir(BENCH / 'sites')
states = {}
for site, database in [('hospitality.localhost', 'hospitality_dev'), ('hospitality-acceptance.localhost', 'hospitality_acceptance')]:
    frappe.init(site=site, sites_path=str(BENCH / 'sites'))
    frappe.connect()
    try:
        assert frappe.conf.db_name == database
        if 'acceptance' in site:
            assert frappe.conf.allow_tests and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
        operations = {dt: frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift', 'Sales Invoice', 'Payment Entry']}
        if 'acceptance' in site:
            assert not any(operations.values())
            assert not frappe.db.exists('Item', 'HS-UX-PART-TS')
        states[site] = dict(business_date=str(frappe.db.get_value('HS Property', {'property_name': 'Hotel Jardín Demo'}, 'business_date')),
            operation_counts=operations)
        assert states[site]['business_date'] == '2026-10-19'
    finally:
        frappe.db.rollback()
        frappe.destroy()
ports = {}
for port in [8086, 8089, 8091, 9001, 9003, 11001, 13001, 11003, 13003]:
    with socket.socket() as connection:
        connection.settimeout(.3)
        ports[str(port)] = connection.connect_ex(('127.0.0.1', port)) == 0
assert {key for key, value in ports.items() if value} == {'8086', '9001', '11001', '13001'}
with urllib.request.urlopen('http://hospitality.localhost:8086/login', timeout=10) as response:
    assert response.status == 200
manifest = json.loads((BENCH / 'sites/assets/assets.json').read_text())
bundle = manifest['hospitality.bundle.js']
assert bundle.endswith('hospitality.bundle.5IE6WQ4O.js')
with urllib.request.urlopen('http://hospitality.localhost:8086' + bundle, timeout=10) as response:
    assert response.status == 200
    served = hashlib.sha256(response.read()).hexdigest()
assert served == sha((BENCH / 'sites' / bundle.lstrip('/')).resolve())
screens = ['359-capacidad-sin-conversion.png', '360-mantenimiento-codigo-anterior.png',
    '361-mantenimiento-repuesto-legible.png', '362-mantenimiento-reapertura-autorizada.png']
assert all((E / name).stat().st_size > 1000 for name in screens)
final = dict(observed_at_utc=datetime.now(timezone.utc).isoformat(), sites=states, ports=ports, main_http=200,
    bundle=bundle, served_bundle_sha256=served, acceptance_restored=True, main_business_mutations=False,
    independent_release_bench_stopped=True, ota_sync_deferred_by_user=True)
(E / 'task-state-final-state.json').write_text(json.dumps(final, indent=2) + '\n', encoding='utf-8')
references = {path.name: sha(path) for path in E.glob('task-state-*') if path.name != 'task-state-verification.json'}
references.update({name: sha(E / name) for name in screens})
proof = dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(), statuses=dict(counts),
    source_sha256=audit['sha256'], audit_sha256=sha(ROOT / 'docs/specification-audit.json'),
    verified_requirements=['S00-02', 'S04-14'], javascript=dict(tests=221, desk=218, portal=3, skipped=0),
    historical_native=dict(tests=404, rerun=False, execution_revision='be67c92', current_python_identical=True),
    browser=dict(roles=trace['roles'], events=len(trace['events']), final_bundle='5IE6WQ4O',
        intermediate_bundle='46PQW7RZ', open_observations=trace['known_open_observations']),
    task_families=22, handlers=84, acceptance_restored=True, main_business_mutations=False,
    current_distribution_package_includes_this_ui_delta=False, references_sha256=references,
    all_requirements_completed=False, ota_sync_deferred_by_user=True)
(E / 'task-state-verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(verified_requirements=proof['verified_requirements'], javascript=221,
    historical_native=404, roles=len(trace['roles']), browser_events=len(trace['events']), open_requirements=6,
    acceptance_restored=True, all_requirements_completed=False)))
