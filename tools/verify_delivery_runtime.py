"""Read-only final delivery gate against the preserved WSL test environment.

This checks the current site and data, not a replay of operational GUI tests.
Run with the main bench's Python as its existing frappe OS user.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import urllib.request

import frappe

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
MAIN = Path('/home/frappe/benches/hospitality-bench')
RELEASE = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
OUTPUT = E / 'delivery-final-runtime.json'
assert not OUTPUT.exists(), 'Preserve previous observations'
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
original = read(MAIN / '.hospitality-final-recovery-upgrade.json')
tested = read(E / 'f26-candidate-environment.json')
sites = {}
os.chdir(MAIN / 'sites')
for site, database in [('hospitality.localhost', 'hospitality_dev'),
                       ('hospitality-acceptance.localhost', 'hospitality_acceptance')]:
    frappe.init(site=site, sites_path=str(MAIN / 'sites'))
    frappe.connect()
    try:
        assert frappe.conf.db_name == database
        if site == 'hospitality-acceptance.localhost':
            assert frappe.conf.pause_scheduler and frappe.conf.allow_tests
            assert frappe.conf.hospitality_integration_test_site
            assert not any(frappe.db.count(dt) for dt in
                           ['HS Stay', 'HS Charge', 'HS Payment', 'Sales Invoice', 'Payment Entry'])
        frappe.set_user('Administrator')
        tables = {}
        for dt, previous in original[site]['tables'].items():
            columns = previous['columns']
            assert all(name.replace('_', '').isalnum() for name in columns)
            assert dt.replace(' ', '').replace('_', '').isalnum()
            rows = frappe.db.sql('SELECT ' + ','.join('`' + name + '`' for name in columns)
                                 + ' FROM `tab' + dt + '` ORDER BY name', as_dict=True)
            raw = json.dumps(rows, default=str, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()
            tables[dt] = dict(columns=columns, rows=len(rows), sha256=hashlib.sha256(raw).hexdigest())
        changed = [dt for dt in tables if tables[dt] != original[site]['tables'][dt]]
        cache_reference = None
        if site == 'hospitality.localhost' and changed == ['Company']:
            cache = read(E / 'delivery-final-company-cache.json')
            assert cache['phase_company_sha256'] == original[site]['tables']['Company']['sha256']
            assert cache['current_company_sha256'] == tables['Company']['sha256']
            assert cache['source_backup_row_matches_original'] and cache['phase_backup_row_matches']
            assert cache['all_other_company_fields_preserved'] and cache['noncache_fields_match_pre_phase_backup']
            assert cache['cached_histories_match_native_read_functions'] and cache['job_status'] == 'Complete'
            assert set(cache['changed_fields']).issubset({'modified', 'sales_monthly_history', 'transactions_annual_history'})
            assert cache['attestation_source_sha256'] == sha(ROOT / 'tools/verify_company_cache.py')
            cache_reference = dict(path='docs/evidence/delivery-final-company-cache.json',
                                   sha256=sha(E / 'delivery-final-company-cache.json'))
            changed = []
        assert not changed, (site, 'Changed preserved business tables', changed)
        private = {}
        for name in frappe.get_all('File', filters={'is_private': 1, 'is_folder': 0}, pluck='name'):
            path = Path(frappe.get_doc('File', name).get_full_path()).resolve()
            assert path.is_relative_to((MAIN / 'sites' / site / 'private/files').resolve())
            private[name] = sha(path)
        assert private == original[site]['private_files']
        versions = {row.app_name: row.app_version for row in
                    frappe.get_single('Installed Applications').installed_applications}
        assert versions == {'frappe': '16.52.0', 'erpnext': '16.51.1', 'hospitality_suite': '0.8.9'}
        sites[site] = dict(tables=len(tables), rows=sum(row['rows'] for row in tables.values()),
                           private_files=len(private), all_business_rows_preserved=True,
                           private_file_bytes_identical=True, attested_native_company_cache=cache_reference,
                           registered_versions=versions)
    finally:
        frappe.db.rollback()
        frappe.destroy()

for name, digest in tested['application_file_sha256'].items():
    assert sha(ROOT / name) == sha(RELEASE / 'apps/hospitality_suite' / name) == digest
cores = {}
for bench in [MAIN, RELEASE]:
    for app in ['frappe', 'erpnext']:
        location = bench / 'apps' / app
        assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=location)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=location, text=True).strip()
        assert revision == tested['sources'][app]['revision']
        cores.setdefault(app, revision)
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=RELEASE / 'apps/hospitality_suite')
ports = {}
for port in [8086, 8089, 8091, 9001, 9003, 11001, 13001, 11003, 13003]:
    with socket.socket() as connection:
        connection.settimeout(.3)
        ports[str(port)] = connection.connect_ex(('127.0.0.1', port)) == 0
assert {port for port, on in ports.items() if on} == {'8086', '9001', '11001', '13001'}
with urllib.request.urlopen('http://hospitality.localhost:8086/api/method/ping', timeout=10) as response:
    assert response.status == 200 and json.load(response)['message'] == 'pong'
bundle = read(MAIN / 'sites/assets/assets.json')['hospitality.bundle.js']
accepted = read(E / 'privacy-portal-verification.json')
assert bundle == accepted['bundle']
with urllib.request.urlopen('http://hospitality.localhost:8086' + bundle, timeout=10) as response:
    assert response.status == 200
    served = hashlib.sha256(response.read()).hexdigest()
assert served == accepted['served_bundle_sha256'] == sha((MAIN / 'sites' / bundle.lstrip('/')).resolve())
proof = dict(at_utc=datetime.now(timezone.utc).isoformat(), read_only=True,
             sites=sites, application_files_match_tested_candidate=332, core_revisions=cores,
             core_worktrees_clean=True, ports=ports, http_status=200, ping='pong',
             primary_bundle=bundle, served_bundle_sha256=served, accepted_UI_bundle_unchanged=True,
             external_OTA_sync_deferred_by_user=True)
OUTPUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(site_http=200, sites=sites, files_match_tested_candidate=332)))
