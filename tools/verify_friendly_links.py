"""Assemble bounded 0.8.6 evidence; no browser replay or database writes."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
L = ROOT / '.local/friendly-links'


def read(name):
    return json.loads((E / name).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


trace = read('friendly-links-browser.json')
assert trace['role'] == 'HS Receptionist' and trace['viewport_override_reset']
assert len(trace['events']) == 14 and len(trace['intermediate_defects']) == 2
assert set(trace['properties']) == {'Hotel Jardín Demo', 'Motel Luna Demo'}
assert trace['final_bundle'] == 'hospitality.bundle.P3YHSTYY.js'
events = {row['screenshot']: row for row in trace['events'] if row.get('screenshot')}
for number in [307, 308, 310, 317]:
    row = next(row for name, row in events.items() if name.startswith(str(number)))
    assert len(row['observed']['options']) == 2
    assert not any('Crear' in text or 'property=' in text for text in row['observed']['options'])
assert events['307-selector-categoria-claro.jpg']['observed']['options'][0] == 'EstándarCapacidad: 3 personas'
assert events['308-selector-habitacion-claro.jpg']['observed']['options'][0] == 'H101Categoría: Estándar'
assert 'Por tiempo · Precio base: C$ 450.00' in events['317-selector-tarifa-por-tiempo.jpg']['observed']['options'][0]
for number in [313, 314, 315, 316]:
    row = next(row for name, row in events.items() if name.startswith(str(number)))
    assert row['observed']['width'] == row['observed']['documentWidth'] == 390
    assert row['observed']['bundle'].endswith(trace['final_bundle'])
assert 'No hay reservas confirmadas ni retenciones vigentes.' in events['313-borrador-y-vacio-reservas-movil.jpg']['snapshot']
assert 'Borradores por completar' in events['313-borrador-y-vacio-reservas-movil.jpg']['snapshot']
visible = next(row['observed'] for row in trace['events'] if isinstance(row['observed'], list))
assert {row['field']: row['value'] for row in visible if row['field']} == {
    'category': 'Estándar', 'room': 'H101', 'people': '2', 'extra_beds': '0', 'rate': 'Noche estándar'}
assert all(row['label'] for row in visible)

observed = read('friendly-links-observed-draft-ui.json')
draft = read('friendly-links-draft-ui.json')
confirmed = read('friendly-links-confirmed-ui.json')
assert observed['people'] == 1 and draft['people'] == confirmed['people'] == 2
assert observed['booking'] == draft['booking'] == confirmed['booking'] == 'RES-2026-00001'
assert observed['ids'] == draft['ids'] == confirmed['ids']
assert confirmed['keys_preserved_from_draft'] and confirmed['status'] == 'Confirmed' and confirmed['amount'] == 1500
assert draft['status'] == observed['status'] == 'Draft' and draft['amount'] == observed['amount'] == 0
for count, receipt in enumerate([observed, draft, confirmed], start=1):
    assert receipt['fixture_origin'] == 'Pages UI only' and not receipt['mutations_by_inspector']
    assert receipt['extra_beds'] == 0 and not receipt['http_500'] and receipt['business_date'] == '2026-10-19'
    assert receipt['execute_http_statuses'] == ['200'] * count
    assert receipt['operation_counts'] == {'HS Booking': 1, 'HS Stay': 0, 'HS Charge': 0, 'HS Payment': 0,
        'HS Shift': 0, 'Sales Invoice': 0, 'Payment Entry': 0, 'Journal Entry': 0, 'HS Allocation': int(count == 3)}

presentation = read('friendly-links-final-presentation.json')
colors = read('friendly-links-final-colors.json')
for receipt in [presentation, colors]:
    assert receipt['site'] == 'hospitality.localhost:8086'
    assert receipt['observed']['bundle'].endswith('hospitality.bundle.DYBXC4MH.js')
assert presentation['observed']['options'] == ['H101Categoría: Estándar', 'Opciones de Hotel Jardín Demo']
inputs = {row['field']: row for row in presentation['observed']['inputs'] if row['field']}
assert set(inputs) == {'category', 'room', 'people', 'extra_beds', 'rate'}
assert all(row['label'] for row in inputs.values())
assert inputs['category']['value'] == 'Estándar' and inputs['room']['value'] == 'H101'
cards = colors['observed']['cards']
assert len(cards) == 10 and colors['observed']['width'] == colors['observed']['documentWidth']
red = [row for row in cards if 'is-unavailable' in row['className']]
green = [row for row in cards if 'is-available' in row['className']]
assert len(red) == 1 and len(green) == 9
assert red[0]['text'].startswith('H105\n× No disponible\nOcupada en el intervalo')
assert red[0]['background'] == 'rgb(252, 236, 238)' and red[0]['color'] == 'rgb(161, 38, 46)'
assert all(row['background'] == 'rgb(234, 246, 237)' and row['color'] == 'rgb(23, 100, 58)' and '✓ Disponible' in row['text'] for row in green)
assert sum('Limpieza actual: Sucia' in row['text'] for row in green) == 3

restored = read('friendly-links-ux-restored.json')
assert restored['restored'] and (restored['tables'], restored['rows']) == (71, 185)
upgrade = read('friendly-links-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites'] == {
    'hospitality.localhost': {'tables': 72, 'rows': 1246, 'private_files': 2},
    'hospitality-acceptance.localhost': {'tables': 72, 'rows': 250, 'private_files': 0}}
state = read('friendly-links-final-state.json')
assert state['main_http'] == 200 and state['ports'] == {'8086': True, '8089': False, '9001': True, '11001': True, '13001': True}
assert state['main']['business_date'] == '2026-10-19' and not any(state['acceptance']['operation_counts'].values())
language = read('friendly-links-language-installed.json')
assert language['desk_modules'] == 29 and language['portal_modules'] == 1
assert all(row['fields_checked'] == 446 and not row['mutations'] for row in language['sites'].values())
js = (E / 'friendly-links-js-tests.log').read_text(encoding='utf-8')
assert all(re.search(r'\b' + key + r'\s+' + str(value) + r'\b', js) for key, value in [('tests', 203), ('pass', 203), ('fail', 0), ('skipped', 0), ('cancelled', 0)])
build = (E / 'friendly-links-build.log').read_text(encoding='utf-8')
assert 'hospitality.bundle.DYBXC4MH.js' in build and 'hospitality.bundle.QHFOLBWK.css' in build and 'DONE' in build
assert 'hospitality.bundle.P3YHSTYY.js' in (E / 'friendly-links-workflow-build.log').read_text(encoding='utf-8')
wire = read('friendly-links-wire-invariants.json')
assert wire['baseline'].startswith('b59f953') and len(wire['files']) == 30
assert sum(row.get('unchanged', False) for row in wire['files']) == 29
assert [row['file'] for row in wire['files'] if row.get('new_source')] == ['hospitality_suite/public/js/hospitality_links.js']
native = ET.parse(E / 'keyboard-review-native-tests.xml').getroot()
assert len(native.findall('.//testcase')) == 380 and not any(native.findall('.//' + key) for key in ('failure', 'error', 'skipped'))
changed = subprocess.check_output(['git', 'diff', 'beac44d', '--name-only'], cwd=ROOT, text=True).splitlines()
assert [name for name in changed if name.startswith('hospitality_suite/') and name.endswith('.py')] == ['hospitality_suite/__init__.py']
versions = []
for site in ['main', 'acceptance']:
    listing = L / f'list-{site}.log'
    migration = L / f'migrate-{site}.log'
    assert re.search(r'hospitality_suite\s+0\.8\.6\b', listing.read_text(encoding='utf-8-sig'))
    log = migration.read_text(encoding='utf-8-sig')
    assert 'Updating installed applications...' in log and 'Executing `after_migrate` hooks...' in log and 'Traceback' not in log
    versions.append(dict(site=site, version='0.8.6', listing_sha256=sha(listing), migration_sha256=sha(migration)))
core = {}
for app in ['frappe', 'erpnext']:
    command = ['wsl', '-d', 'Ubuntu-24.04', '-u', 'frappe', '--', 'git', '-C', '/home/frappe/benches/hospitality-bench/apps/' + app]
    revision = subprocess.check_output([*command, 'rev-parse', 'HEAD'], text=True).strip()
    assert not subprocess.check_output([*command, 'status', '--porcelain'], text=True), app
    core[app] = dict(commit=revision, clean=True)
audit = read('../specification-audit.json')
counts = dict(Counter(row['status'] for row in audit['items']))
assert len(audit['items']) == 218 and counts == {'R': 14, 'I': 6, 'V': 198}
assert audit['sha256'] == '876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
assert read('delivery-review-matrix.json')['audit_sha256'] == sha(ROOT / 'docs/specification-audit.json')
images = []
for number in range(307, 320):
    paths = list(E.glob(str(number) + '-*.jpg'))
    assert len(paths) == 1 and paths[0].read_bytes().startswith(b'\xff\xd8')
    scope = ('Observed defect before correction' if number in (309, 311) else
             'Final installed DYBXC4MH read-only query' if number >= 318 else
             'Initial friendly names: 7GSBLVX5' if number <= 308 else
             'Names/labels before numeric correction: 2ID7RQ6C' if number == 310 else 'Corrected P3YHSTYY workflow')
    images.append(dict(path=paths[0].relative_to(ROOT).as_posix(), sha256=sha(paths[0]), captured_bytes_unchanged=True, scope=scope))
references = ['friendly-links-' + name for name in ['browser.json', 'observed-draft-ui.json', 'draft-ui.json', 'confirmed-ui.json',
    'final-presentation.json', 'final-colors.json', 'ux-restored.json', 'upgrade.json', 'final-state.json', 'language-installed.json',
    'js-tests.log', 'build.log', 'workflow-build.log', 'wire-invariants.json']]
sources = ['hospitality_suite/' + name for name in ['__init__.py', 'public/js/hospitality.js', 'public/js/hospitality_links.js',
    'public/js/hospitality_drafts.js', 'public/js/hospitality_keyboard.js', 'public/hospitality.bundle.js']]
sources += ['tools/test_links_ui.cjs', 'tools/test_desk_transport.cjs', 'tools/test_booking_drafts_ui.cjs', 'tools/friendly_links_ux.py',
    'tools/verify_friendly_links.py', 'docs/SELECTORES_Y_RESERVA_MANUAL.md', 'docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md', 'docs/specification-audit.json']
bundles = list((ROOT / 'hospitality_suite/public/dist/js').glob('hospitality.bundle.*.js'))
assert len(bundles) == 1 and bundles[0].name == 'hospitality.bundle.DYBXC4MH.js'
proof = dict(assembled_at_utc=datetime.now(timezone.utc).isoformat(), version='0.8.6', evidence_assembly_only=True,
    database_mutations=False, ui_replay=False, scope='Friendly operational Links, complete room row editor and reservation empty states; final read-only colors regression.',
    javascript=dict(tests=203, desk=200, portal=3, new_cases=7, failures=0, skipped=0),
    workflow=dict(events=14, bundle=trace['final_bundle'], repeated_on_final_installed_bundle=False, intermediate_defects_preserved=True),
    installed_readonly_queries=dict(count=2, bundle='hospitality.bundle.DYBXC4MH.js', malicious_markup_browser_test=False,
        native_description_encoding_unit_regression=True),
    native=dict(tests=380, rerun_in_this_phase=False, revision='beac44d', junit_sha256=sha(E / 'keyboard-review-native-tests.xml')),
    native_python_behavior_unchanged=True, native_versions=versions, core=core, statuses=counts, open_requirements=20,
    all_requirements_completed=False, known_open_observations=trace['known_open_observations'], protected_sites=upgrade['sites'],
    final_services=state['ports'], source_sha256={name: sha(ROOT / name) for name in sources}, references={name: sha(E / name) for name in references},
    screenshots=images, compiled_javascript=dict(name=bundles[0].name, sha256=sha(bundles[0])),
    raw_command_outputs={name: sha(L / name) for name in ['js-security.log', 'build-security.log', 'build-rows.log']},
    public_log_normalization='UTF-8 LF and trailing whitespace removed; original private command output retained.',
    external_providers_activated=False, ota_sync_deferred_by_user=True, final_deployment_rollback_proven=False)
(E / 'friendly-links-verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(javascript=203, workflow_events=14, final_readonly_queries=2, screenshots=len(images), statuses=counts, open_requirements=20)))
