"""Verify the bounded modal/attachment review without claiming all secondary flows."""
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

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
BENCH = Path('/home/frappe/benches/hospitality-bench')
read = lambda name: json.loads((E / name).read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
write = lambda name, value: (E / name).write_text(json.dumps(value, ensure_ascii=False,
    indent=2) + '\n', encoding='utf-8', newline='\n')

run = read('secondary-acceptance-native-run.json')
assert (run['tests'], run['integration'], run['unit']) == (405, 373, 32)
assert not any(run[key] for key in ['failures', 'errors', 'skipped'])
native = ET.parse(E / 'secondary-acceptance-native-tests.xml').getroot()
assert len(native.findall('.//testcase')) == 405
assert not any(native.findall('.//' + name) for name in ['failure', 'error', 'skipped'])
assert any(row.get('name') == 'test_assigned_technician_can_attach_private_evidence_without_cost_write_permission'
    for row in native.findall('.//testcase'))
js = (E / 'secondary-acceptance-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(rf'^# {key} {value}$', js, re.M) for key, value in
    [('tests', 222), ('pass', 222), ('fail', 0), ('cancelled', 0), ('skipped', 0), ('todo', 0)])
assert '# fail 1' in (E / 'secondary-acceptance-incident-link-red.log').read_text()

rapid = read('secondary-acceptance-rapid-browser.json')
assert rapid['paired_cycles'] == 6 and not rapid['business_mutations']
assert not rapid['full_secondary_acceptance']
old = next(row for row in rapid['events'] if row['label'] == 'rapid-before-close-hit-test')
assert old['dom']['hitClass'] == 'modal-backdrop fade'
assert float(old['dom']['backdrops'][0]['opacity']) > 0
assert len(rapid['rapid']) == 25
for row in rapid['rapid']:
    if row.get('stage', '').startswith('close-'):
        assert not row['backdrops'] and not row['visibleDialogs']
        assert row['hitAction'] == ('maintenance_parts' if row['stage'] == 'close-incident' else 'incident')
    elif row.get('stage') in ['parts-open', 'incident-open']:
        assert len(row['visibleDialogs']) == 1
        assert ' fade' not in row['visibleDialogs'][0]['classes']

trace = read('secondary-acceptance-browser.json')
events = {row['label']: row for row in trace['events']}
assert len(events) == 18
assert trace['roles'] == ['HS Maintenance', 'HS Supervisor'] and trace['last_session_logged_out']
assert trace['full_secondary_acceptance'] is False and trace['desktop_only']
assert 'Privado' in events['maintenance-upload-private-selected']['text']
assert events['maintenance-upload-finished-without-reference']['text'].count('Ver evidencia') == 0
assert events['maintenance-both-private-links-final']['text'].count('Ver evidencia') == 2
final_dom = events['supervisor-order-completed-evidence-link-retained']
assert final_dom['text'].count('Ver evidencia') == 2
assert 'Completada' in final_dom['text'] and 'Resuelto' in final_dom['text']
assert 'Bloqueo liberado' in final_dom['text'] and not any(row['visible'] for row in final_dom['dialogs'])
assert not final_dom['backdrops']
assert any('S27NPDSI' in path for path in final_dom['bundle'])

red = read('secondary-acceptance-maintenance-evidence-database.json')
fixed = read('secondary-acceptance-maintenance-evidence-fixed-database.json')
completed = read('secondary-acceptance-supervisor-completed-database.json')
assert red['private_attachments'] and not red['maintenance'][0]['evidence']
assert fixed['maintenance'][0]['evidence'] == '/private/files/secondary-acceptance-evidence.txt'
assert fixed['maintenance'][0]['modified_by'] == 'maintenance@hospitality.example.invalid'
order, incident = completed['maintenance'][0], completed['incidents'][0]
assert order['status'] == 'Completed' and order['evidence'] == fixed['maintenance'][0]['evidence']
assert order['modified_by'] == 'supervisor@hospitality.example.invalid'
assert incident['status'] == 'Resolved' and incident['resolved_by'] == order['modified_by']
assert incident['evidence'] == '/private/files/secondary-incident-evidence.txt'
assert len({row['file_url'] for row in completed['private_attachments']}) == 2
assert all(row['owner'] == 'maintenance@hospitality.example.invalid' for row in completed['private_attachments'])
assert completed['counts'] == dict(read('secondary-acceptance-prepared-database.json')['counts'],
    **{'HS Incident': 1, 'File': 7})
assert completed['stock'] == read('secondary-acceptance-prepared-database.json')['stock']

restored = read('secondary-acceptance-ux-restored.json')
assert restored['restored'] and (restored['tables'], restored['rows']) == (71, 185)
preserved = read('secondary-acceptance-upgrade.json')
assert preserved['previous_columns_preserved'] and preserved['sites'] == {
    'hospitality.localhost': dict(tables=72, rows=1246, private_files=2),
    'hospitality-acceptance.localhost': dict(tables=72, rows=250, private_files=0)}
physical = read('secondary-acceptance-files-restored.json')
assert physical['physical_file_tree_restored'] and physical['files'] == 741

audit = json.loads((ROOT / 'docs/specification-audit.json').read_text(encoding='utf-8'))
counts = Counter(row['status'] for row in audit['items'])
assert len(audit['items']) == 218 and counts == Counter(V=212, I=6)
assert audit['sha256'] == '876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
open_ids = [row['id'] for row in audit['items'] if row['status'] != 'V']
assert set(open_ids) == {'S00-01', 'S01-12', 'S04-16', 'S04-20', 'S19-07', 'S19-08'}
ports = {}
for port in [8086, 8089, 8091, 9001, 9003, 11001, 13001, 11003, 13003]:
    with socket.socket() as connection:
        connection.settimeout(.3)
        ports[str(port)] = connection.connect_ex(('127.0.0.1', port)) == 0
assert {key for key, value in ports.items() if value} == {'8086', '9001', '11001', '13001'}
for name, marker in [('web', '8086'), ('worker', 'worker')]:
    pid = (BENCH / '.hospitality-run' / (name + '.pid')).read_text().strip()
    proc = Path('/proc') / pid
    assert marker in (proc / 'cmdline').read_bytes().decode()
    assert (proc / 'cwd').resolve() in [BENCH, BENCH / 'sites']
    assert (BENCH / '.hospitality-secondary-acceptance-main-restarted.json').stat().st_mtime > (
        ROOT / 'hospitality_suite/housekeeping.py').stat().st_mtime
manifest = json.loads((BENCH / 'sites/assets/assets.json').read_text())
bundle = manifest['hospitality.bundle.js']
assert bundle.endswith('hospitality.bundle.S27NPDSI.js')
with urllib.request.urlopen('http://hospitality.localhost:8086/login', timeout=10) as response:
    assert response.status == 200
with urllib.request.urlopen('http://hospitality.localhost:8086' + bundle, timeout=10) as response:
    assert response.status == 200
    served = hashlib.sha256(response.read()).hexdigest()
assert served == sha((BENCH / 'sites' / bundle.lstrip('/')).resolve())
core = {}
for app in ['frappe', 'erpnext']:
    folder = BENCH / 'apps' / app
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=folder)
    core[app] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder, text=True).strip()
sources = {path.relative_to(ROOT).as_posix(): sha(path) for path in (ROOT / 'hospitality_suite').rglob('*')
    if path.suffix in ['.py', '.js'] and 'dist' not in path.parts}
proof = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(), statuses=dict(counts), open_ids=open_ids,
    newly_closed_requirements=[], native=dict(tests=405, integration=373, unit=32, failures=0, errors=0, skipped=0),
    javascript=dict(tests=222, desk=219, portal=3), browser=dict(roles=trace['roles'], events=len(events),
        paired_rapid_cycles=6, desktop_only=True, final_bundle='S27NPDSI'),
    source_sha256=audit['sha256'], sources_sha256=sources, core_revisions=core, main_bundle=bundle,
    main_bundle_sha256=served, ports=ports, acceptance_restored=True,
    all_original_physical_files_preserved=741, main_business_mutations=False,
    ota_sync_deferred_by_user=True, full_secondary_acceptance=False,
    final_recovery_F26_complete=False, current_package_includes_this_phase=False,
    evidence_sha256={path.name: sha(path) for path in E.glob('secondary-acceptance-*')
        if path.name != 'secondary-acceptance-verification.json'})
write('secondary-acceptance-verification.json', proof)
print(json.dumps(dict(native=405, javascript=222, newly_closed_requirements=0, open_requirements=6,
    acceptance_restored=True, physical_files_preserved=741, full_secondary_acceptance=False)))
