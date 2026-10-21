"""Record actual clean-bench dependency/source identity; no settings or rows are changed."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import frappe
import erpnext
import hospitality_suite

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
SITE = 'hospitality-release.localhost'
output = ROOT / 'docs/evidence/release-install-environment.json'
assert not output.exists()
assert Path(sys.executable).parent == BENCH / 'env/bin'
package = json.loads((ROOT / 'docs/evidence/release-install-package-final.json').read_text())
installed = BENCH / 'apps/hospitality_suite'
git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT)
files = git('ls-tree', '-r', '--name-only', package['revision'], '--', 'hospitality_suite').decode().splitlines()
assert len(files) == package['application_files'] == 332
hashes = {}
for name in files:
    raw = (installed / name).read_bytes()
    assert raw == (ROOT / name).read_bytes() == git('show', package['revision'] + ':' + name), name
    hashes[name] = hashlib.sha256(raw).hexdigest()
sources = {}
for name, module in [('frappe', frappe), ('erpnext', erpnext), ('hospitality_suite', hospitality_suite)]:
    path = BENCH / 'apps' / name
    assert not path.is_symlink() and Path(module.__file__).resolve().is_relative_to(path)
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=path)
    sources[name] = dict(version=module.__version__, revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path, text=True).strip(), module=module.__file__)
assert (sources['frappe']['version'], sources['erpnext']['version'], sources['hospitality_suite']['version']) == ('16.52.0', '16.51.1', '0.8.8')
assert sources['frappe']['revision'] == '4515014c87ece6cb20ee91d2cfb121c5cbd1ff4a'
assert sources['erpnext']['revision'] == '5af6561f5aa48104559692fb4fd82f2580e8d338'
pdf = Path('/home/frappe/benches/hospitality-bench/.runtime/wkhtmltox/usr/local/bin/wkhtmltopdf')
pdf_version = subprocess.check_output([str(pdf), '--version'], text=True).strip()
assert 'with patched qt' in pdf_version
dependencies = {item.metadata['Name']: item.version for item in importlib.metadata.distributions() if item.metadata['Name']}
assert dependencies['unittest-xml-reporting'] == '4.0.0'
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_release' and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
    proof = dict(observed_at_utc=datetime.now(timezone.utc).isoformat(), site=SITE, python=sys.version.split()[0],
        node=subprocess.check_output(['/usr/bin/node', '--version'], text=True).strip(), mariadb=frappe.db.sql('SELECT VERSION()')[0][0],
        sources=sources, packaged_revision=package['revision'], application_file_hashes=hashes,
        dependencies=dict(sorted(dependencies.items())), shared_host_pdf=dict(version=pdf_version, path=str(pdf), sha256=hashlib.sha256(pdf.read_bytes()).hexdigest()),
        independent_app_code_python_assets_redis_database=True, shared_os_and_mariadb_service=True, database_mutations=False,
        only_changes_since_initial_clean_install=git('diff', '--name-only', 'eb0a452', package['revision'], '--', 'hospitality_suite').decode().splitlines())
    assert all(name.startswith('hospitality_suite/tests/') for name in proof['only_changes_since_initial_clean_install'])
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(python=proof['python'], node=proof['node'], mariadb=proof['mariadb'], independent=True, application_files=len(files))))
finally:
    frappe.db.rollback()
    frappe.destroy()
