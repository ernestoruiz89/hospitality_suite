"""Assemble the numeric UX evidence without claiming full role acceptance."""
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
read = lambda name: json.loads((E / name).read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT)
audit = json.loads((ROOT / 'docs/specification-audit.json').read_text(encoding='utf-8'))
assert len(audit['items']) == 218 and Counter(row['status'] for row in audit['items']) == Counter(V=208, I=10)
assert next(row for row in audit['items'] if row['id'] == 'S04-16')['status'] == 'I'
assert audit['sha256'] == '876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'

changed = set(git('diff', '--name-only', 'fb8c022', '--', 'hospitality_suite').decode().splitlines())
expected = {'hospitality_suite/public/js/hospitality.js', 'hospitality_suite/public/js/hospitality_forms.js'}
assert changed == expected, changed
sources = {name: sha(ROOT / name) for name in sorted(expected)}
backend = {}
for name in git('ls-tree', '-r', '--name-only', 'fb8c022', '--', 'hospitality_suite').decode().splitlines():
    if name.endswith('.py'):
        assert (ROOT / name).read_bytes() == git('show', f'fb8c022:{name}'), name
        backend[name] = sha(ROOT / name)
assert backend
log = (E / 'numeric-review-js-tests.log').read_text(encoding='utf-8')
assert re.search(r'tests 215\b', log) and re.search(r'pass 215\b', log)
assert all(re.search(rf'{key} 0\b', log) for key in ('fail', 'cancelled', 'skipped', 'todo'))
red = (E / 'numeric-review-red-tests.log').read_text(encoding='utf-8')
assert 'fail 3' in red and 'pass 19' in red
wire = read('numeric-review-wire-invariants.json')
assert len(wire['files']) == 30 and all(row.get('unchanged') for row in wire['files'])
native = ET.parse(E / 'provider-contracts-native-tests.xml').getroot()
assert len(native.findall('.//testcase')) == 404
assert not any(native.findall('.//' + key) for key in ('failure', 'error', 'skipped'))

browser = read('numeric-review-browser.json')
assert browser['roles'] == ['HS Manager', 'HS Receptionist'] and browser['limitations']
events = {row['label']: row for row in browser['events']}
capacity = events['manager-capacity-fraction-blocked']
assert 'Indique un número entero.' in capacity['text']
assert any(row['value'] == '1.5' and row['invalid'] == 'true' for row in capacity['inputs'])
for label in ['reception-collapsed-row-partial-save-blocked', 'reception-collapsed-row-review-blocked']:
    assert 'Fila 1, Personas: Indique un número entero.' in events[label]['text']
assert 'Fila 1, Camas adicionales: Indique un número entero.' in events['reception-optional-beds-malformed-blocked']['text']
assert any(row['name'] == 'people' and row['value'] == '1.5' for row in events['reception-reopened-row-retains-fraction']['inputs'])
assert any(row['name'] == 'extra_beds' and row['value'] == '2abc' for row in events['reception-reopened-row-retains-malformed-beds']['inputs'])
assert any(row['name'] == 'people' and row['value'] == '2' for row in events['reception-saved-draft-reopened-values']['inputs'])
for stage in ['scalar', 'grid-blocked', 'grid-saved']:
    observed = read(f'numeric-review-{stage}-database.json')
    assert observed['sources'] == sources
    assert {row['category_name']: row['capacity'] for row in observed['categories']} == {
        'Revisión numérica temporal': 1, 'Capacidad corregida temporal': 2}
    if stage == 'grid-saved':
        assert len(observed['bookings']) == 1 and observed['bookings'][0]['status'] == 'Draft'
        assert observed['draft_rooms'] == [dict(people=2, extra_beds=0)] and not observed['rooms']
    else:
        assert not observed['bookings'] and not observed['rooms']
cards = read('numeric-review-availability.json')
assert cards['read_only_query'] and len(cards['cards']) == 10
assert Counter(row['classes'] for row in cards['cards']) == Counter({'hs-room-state is-available': 9, 'hs-room-state is-unavailable': 1})
assert all('intervalo' not in row['text'].lower() for row in cards['cards'])
assert next(row for row in cards['cards'] if row['text'].startswith('H105'))['background'] == 'rgb(252, 236, 238)'
assert all(row['background'] == 'rgb(234, 246, 237)' for row in cards['cards'] if 'is-available' in row['classes'])
assert all('OTTQHYJ4' in url for row in browser['events'] for url in row['bundle'])
assert any('OTTQHYJ4' in url for url in cards['bundle'])
assert 'hospitality.bundle.OTTQHYJ4.js' in (E / 'numeric-review-build.log').read_text(encoding='utf-8')

restored = read('numeric-review-ux-restored.json')
assert restored['restored'] and (restored['tables'], restored['rows']) == (71, 185)
upgrade = read('numeric-review-upgrade.json')
assert upgrade['previous_columns_preserved']
assert upgrade['sites'] == {'hospitality.localhost': dict(tables=72, rows=1246, private_files=2),
    'hospitality-acceptance.localhost': dict(tables=72, rows=250, private_files=0)}
assert read('numeric-review-acceptance-restored.json')['exit_code'] == 0
final = read('numeric-review-final-state.json')
assert not any(final['acceptance']['operation_counts'].values())
assert not final['ports']['8089'] and final['main_http'] == 200 and final['main']['business_date'] == '2026-10-19'
screenshots = ['352-capacidad-entera-validacion.png', '353-fila-personas-validacion.png',
    '354-borrador-cantidades-corregidas.png', '355-disponibilidad-sin-repeticion.png']
assert all((E / name).stat().st_size > 1000 for name in screenshots)
references = {path.relative_to(ROOT).as_posix(): sha(path) for path in E.glob('numeric-review-*')
    if path.name != 'numeric-review-verification.json'}
references.update({f'docs/evidence/{name}': sha(E / name) for name in screenshots})
proof = dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(), statuses=dict(Counter(row['status'] for row in audit['items'])),
    source_sha256=audit['sha256'], changed_application_sources=sources, javascript=dict(tests=215, desk=212, portal=3, skipped=0),
    historical_native=dict(tests=404, executed_in='fb8c022', rerun=False, unchanged_python_sources=backend),
    browser=dict(events=len(browser['events']), roles=browser['roles'], installed_bundle='OTTQHYJ4', limitations=browser['limitations']),
    acceptance_restored=True, main_business_mutations=False, ota_sync_deferred_by_user=True,
    all_requirements_completed=False, references_sha256=references)
(E / 'numeric-review-verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(javascript=215, browser_events=len(browser['events']), historical_native=404, open_requirements=10,
    acceptance_restored=True, all_requirements_completed=False)))
