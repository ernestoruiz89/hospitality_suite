"""Build and inspect distributable files from an immutable local Git revision.

Run with Python >=3.14, build and flit_core in a separate build environment.
Artifacts go to ignored output/releases; no installed bench is changed.
"""
import argparse
from email.parser import Parser
import gzip
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--revision', default='HEAD')
parser.add_argument('--verify-existing', action='store_true', help='Verify retained artifacts without replacing their build output')
args = parser.parse_args()
revision = subprocess.check_output(['git', 'rev-parse', '--verify', args.revision + '^{commit}'], cwd=ROOT, text=True).strip()
destination = ROOT / 'output/releases' / revision[:12]
source = ROOT / '.local/release-build' / revision[:12] / 'source'
repository = destination / 'hospitality-suite-repository.tar.gz'
log = destination / 'build.log'
if args.verify_existing:
    assert destination.is_dir() and source.is_dir() and repository.is_file() and log.is_file()
    assert not (destination / 'manifest.json').exists(), 'Preserve the preceding verified manifest'
else:
    assert not destination.exists() and not source.exists(), 'Preserve existing artifacts; build a new explicit revision'
    destination.mkdir(parents=True)
    source.mkdir(parents=True)
    archive = subprocess.check_output(['git', 'archive', '--format=tar', revision], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    with repository.open('wb') as output:
        with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed:
            compressed.write(archive)
    with log.open('w') as output:
        result = subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '--outdir', str(destination), str(source)],
            stdout=output, stderr=subprocess.STDOUT)
    assert result.returncode == 0, 'Inspect the preserved build.log'
sdist, = destination.glob('hospitality_suite-*.tar.gz')
wheel, = destination.glob('hospitality_suite-*.whl')
expected = set(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', revision, '--', 'hospitality_suite'], cwd=ROOT, text=True).splitlines())
with tarfile.open(sdist) as bundle:
    top = bundle.getnames()[0].split('/')[0]
    sdist_files = {member.name.removeprefix(top + '/'): bundle.extractfile(member).read()
        for member in bundle.getmembers() if member.isfile()}
with zipfile.ZipFile(wheel) as bundle:
    wheel_files = {name: bundle.read(name) for name in bundle.namelist() if not name.endswith('/')}
for name in expected:
    original = (source / name).read_bytes()
    assert sdist_files.get(name) == original, 'Source distribution missing/changed: ' + name
    assert wheel_files.get(name) == original, 'Wheel missing/changed: ' + name
for name in ['README.md', 'LICENSE', 'pyproject.toml', 'docs/OPERACION.md', 'docs/REQUISITOS.md',
    'tools/run_ui_tests.cjs', 'tools/normalize_junit.py', 'tools/generate_schema.py']:
    assert sdist_files.get(name) == (source / name).read_bytes(), name
blocked = {'.local', 'output', 'node_modules', 'env', 'sites', '__pycache__', '.git'}
assert not any(blocked.intersection(Path(name).parts) or name.endswith('.pyc') for name in sdist_files | wheel_files)
assert any(name.endswith('/LICENSE') for name in wheel_files)
metadata, = [value.decode() for name, value in wheel_files.items() if name.endswith('.dist-info/METADATA')]
headers = Parser().parsestr(metadata)
project = tomllib.loads((source / 'pyproject.toml').read_text())
assert 'Name: hospitality_suite' in metadata and 'Requires-Python: >=3.14' in metadata
assert 'unittest-xml-reporting==4.0.0' in metadata and headers.get_all('License-File') == ['LICENSE']
assert any(name.endswith('/LICENSE') and content == (source / 'LICENSE').read_bytes() for name, content in wheel_files.items())
assert project['tool']['bench']['frappe-dependencies'] == {'frappe': '>=16.52.0,<17.0.0', 'erpnext': '>=16.51.1,<17.0.0'}
proof = dict(revision=revision, app_version=headers['Version'],
    build_versions={name: importlib.metadata.version(name) for name in ('build', 'flit_core')},
    application_files=len(expected), sdist_files=len(sdist_files), wheel_files=len(wheel_files),
    application_bytes_identical=True, native_assets_included=True, docs_and_test_tools_in_sdist=True,
    bench_dependencies=project['tool']['bench']['frappe-dependencies'], python_requires=project['project']['requires-python'],
    files={path.name: dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (repository, sdist, wheel, log)}, output=destination.relative_to(ROOT).as_posix())
(destination / 'manifest.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(ROOT / 'docs/evidence/release-install-package.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(proof, ensure_ascii=False))
