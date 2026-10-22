"""Assemble and independently read back the already built 0.8.9 delivery.

The source archives retain their immutable Git cut. Post-build audit receipts
are supplied alongside them, avoiding a self-referential rebuild/manifest.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
DEST = ROOT / 'output/entrega-0.8.9'
RECEIPT = E / 'delivery-final-artifacts.json'
assert not DEST.exists() and not RECEIPT.exists(), 'Preserve existing delivery artifacts'
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
sha = lambda raw: hashlib.sha256(raw).hexdigest()
describe = lambda path: dict(bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
package = read(E / 'delivery-package-final.json')
review = read(E / 'completion-final-review.json')
matrix = read(ROOT / 'docs/specification-audit.json')
runtime = read(E / 'delivery-final-runtime.json')
native = read(E / 'final-recovery-native-run.json')
js = read(E / 'f26-js-run.json')
tested = read(E / 'f26-candidate-environment.json')['application_file_sha256']
assert package['application_bytes_identical'] and package['application_files'] == len(tested) == 332
assert package['app_version'] == '0.8.9'
assert review['stage'] == 'final' and review['statuses'] == {'V': 218}
assert len(matrix['items']) == len({row['id'] for row in matrix['items']}) == 218
assert Counter(row['status'] for row in matrix['items']) == {'V': 218}
assert review['original_source_sha256'] == matrix['sha256']
assert native['tests'] == 410 and js['tests'] == js['pass_count'] == 232
assert not any(native[name] for name in ['failures', 'errors', 'skipped', 'exit_code'])
assert not js['exit_code'] and not js['failures']
assert runtime['http_status'] == 200 and runtime['application_files_match_tested_candidate'] == 332
names = ['hospitality-suite-repository.tar.gz', 'hospitality_suite-0.8.9.tar.gz',
         'hospitality_suite-0.8.9-py3-none-any.whl']
source = ROOT / package['output']
for name in names:
    assert describe(source / name) == package['files'][name], name

# Compare archive members directly; never extract or execute delivery content.
with tarfile.open(source / names[0]) as archive:
    repository = {member.name: archive.extractfile(member).read()
                  for member in archive.getmembers() if member.isfile()}
with tarfile.open(source / names[1]) as archive:
    prefix = archive.getnames()[0].split('/')[0] + '/'
    sdist = {member.name.removeprefix(prefix): archive.extractfile(member).read()
             for member in archive.getmembers() if member.isfile()}
with zipfile.ZipFile(source / names[2]) as archive:
    wheel = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
for name, digest in tested.items():
    assert sha(repository[name]) == sha(sdist[name]) == sha(wheel[name]) == sha((ROOT / name).read_bytes()) == digest
for members in [repository, sdist, wheel]:
    assert not any(Path(name).is_absolute() or '..' in Path(name).parts for name in members)
    assert not any(set(Path(name).parts) & {'.local', '.git', 'sites', 'env', 'output', '__pycache__'} for name in members)
assert 'docs/REVISION_KAMRA_PMS.md' not in repository
assert read(ROOT / 'docs/specification-audit.json') == json.loads(repository['docs/specification-audit.json'])

DEST.mkdir(parents=True)
for name in names:
    shutil.copyfile(source / name, DEST / name)
closing = ['README.md', 'docs/ENTREGA_FINAL.md', 'docs/COTEJO_FINAL.md',
           'docs/AUDITORIA_ESPECIFICACION.md', 'docs/specification-audit.json',
           'tools/verify_delivery_runtime.py', 'tools/verify_company_cache.py', 'tools/assemble_delivery.py']
closing += ['docs/evidence/' + name for name in [
    'delivery-package-final.json', 'completion-final-review.json', 'delivery-final-runtime.json',
    'delivery-final-company-cache.json', 'final-recovery-native-run.json', 'f26-js-run.json']]
for name in closing:
    target = DEST / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / name, target)
(DEST / 'LEAME.txt').write_text(
    'Hospitality Suite 0.8.9\n\n'
    'Los tres archivos de distribución conservan la revisión Git indicada en manifest.json.\n'
    'Extraiga hospitality-suite-repository.tar.gz para consultar el código, todos los manuales\n'
    'y las evidencias históricas. Las auditorías posteriores a su construcción se incluyen\n'
    'aquí como documentación de cierre en docs/evidence; no forman parte de ese corte Git.\n'
    'El repositorio Git completo sigue disponible en el directorio del proyecto.\n'
    'Instalación y acceso al sitio WSL: docs/ENTREGA_FINAL.md y README.md.\n'
    '218 requisitos verificados; 410 pruebas nativas y 232 JavaScript aprobadas.\n'
    'Sincronización real con Airbnb/Booking aplazada por el usuario.\n'
    'No incluye bases de datos, archivos privados, configuraciones de sitio ni credenciales.\n',
    encoding='utf-8', newline='\n')
payload = {path.relative_to(DEST).as_posix(): describe(path) for path in sorted(DEST.rglob('*')) if path.is_file()}
manifest = dict(version='0.8.9', source_revision=package['revision'],
                at_utc=datetime.now(timezone.utc).isoformat(), requirements=218,
                requirement_statuses={'V': 218}, original_specification_sha256=matrix['sha256'],
                native_tests=410, javascript_tests=232, application_files=332,
                application_bytes_identical_to_tested_candidate=True,
                external_OTA_sync_deferred_by_user=True, files=payload,
                scope='Immutable source archives plus separately identified post-build closing audits.')
(DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
payload['manifest.json'] = describe(DEST / 'manifest.json')
checksums = lambda files: ''.join(value['sha256'] + '  ' + name + '\n' for name, value in sorted(files.items()))
(DEST / 'SHA256SUMS').write_text(checksums(payload), encoding='utf-8', newline='\n')
members = sorted(path for path in DEST.rglob('*') if path.is_file())
zip_path = DEST / 'hospitality-suite-0.8.9-entrega.zip'
with zipfile.ZipFile(zip_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in members:
        archive.write(path, 'entrega-0.8.9/' + path.relative_to(DEST).as_posix())
with zipfile.ZipFile(zip_path) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(members)
    for path in members:
        assert archive.read('entrega-0.8.9/' + path.relative_to(DEST).as_posix()) == path.read_bytes()
    inner = json.loads(archive.read('entrega-0.8.9/manifest.json'))
    assert inner['requirements'] == 218 and inner['native_tests'] == 410 and inner['javascript_tests'] == 232
# The outer checksums additionally cover the ZIP without placing it inside itself.
payload[zip_path.name] = describe(zip_path)
(DEST / 'SHA256SUMS').write_text(checksums(payload), encoding='utf-8', newline='\n')
proof = dict(at_utc=datetime.now(timezone.utc).isoformat(), version='0.8.9',
             source_revision=package['revision'], output=DEST.relative_to(ROOT).as_posix(),
             requirements=218, native_tests=410, javascript_tests=232, application_files=332,
             archive_app_bytes_match_current_and_tested_candidate=True,
             delivery_zip_readback_verified=True, zip_members=len(members), files=payload,
             outer_checksums_include_zip=True, inner_checksums_cover_payload=True,
             public_archives_exclude_private_runtime_and_unrelated_untracked_files=True,
             external_OTA_sync_deferred_by_user=True)
RECEIPT.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(output=proof['output'], zip=describe(zip_path), requirements=218,
                      native_tests=410, javascript_tests=232, zip_members=len(members))))
