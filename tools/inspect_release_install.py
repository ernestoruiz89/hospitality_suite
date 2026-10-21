"""Read-only verification of a genuinely empty, independently installed app."""
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import frappe
from frappe.model.base_document import get_controller
import hospitality_suite
from hospitality_suite import api, hooks
from hospitality_suite.controllers import ScopedDocument
from hospitality_suite.schema import SCHEMA, PAGES, ROLES

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
SITE = 'hospitality-release.localhost'
output = ROOT / 'docs/evidence/release-install-clean.json'
assert not output.exists(), 'Preserve the original clean-site check'
assert Path(sys.executable).parent == BENCH / 'env/bin'
package = json.loads((ROOT / 'docs/evidence/release-install-package.json').read_text())
installed = BENCH / 'apps/hospitality_suite'
assert not installed.is_symlink()
assert Path(hospitality_suite.__file__).resolve().is_relative_to(installed)
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=installed, text=True).strip() == package['revision']
files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'HEAD', '--', 'hospitality_suite'], cwd=installed, text=True).splitlines()
assert len(files) == package['application_files']
assert all((installed / name).read_bytes() == (ROOT / name).read_bytes() for name in files)
cores = {}
for name, expected in [('frappe', '4515014c87ece6cb20ee91d2cfb121c5cbd1ff4a'), ('erpnext', '5af6561f5aa48104559692fb4fd82f2580e8d338')]:
    path = BENCH / 'apps' / name
    assert not path.is_symlink()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path, text=True).strip()
    assert revision == expected
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=path)
    cores[name] = dict(revision=revision, path=str(path), module_path=__import__(name).__file__)
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_release' and frappe.conf.pause_scheduler and frappe.conf.allow_tests
    assert not frappe.conf.get('hospitality_allow_demo')
    frappe.set_user('Administrator')
    assert frappe.get_installed_apps() == ['frappe', 'erpnext', 'hospitality_suite']
    counts = {name: frappe.db.count(name) for name in SCHEMA if not SCHEMA[name].get('child')}
    counts.update({name: frappe.db.count(name) for name in ['Company', 'Account', 'Warehouse', 'Customer', 'Supplier',
        'Item', 'Sales Invoice', 'Payment Entry', 'Journal Entry', 'Stock Entry', 'Stock Reconciliation']})
    assert not any(counts.values()), counts
    assert all(frappe.db.exists('Role', role) for role in ROLES)
    permissions = ['role', 'permlevel', 'read', 'write', 'create', 'print', 'report', 'export', 'delete']
    for name, spec in SCHEMA.items():
        slug = name.lower().replace(' ', '_')
        original = json.loads((installed / 'hospitality_suite/hospitality_suite/doctype' / slug / (slug + '.json')).read_text())
        actual = frappe.get_meta(name)
        assert issubclass(get_controller(name), ScopedDocument)
        assert bool(actual.istable) == bool(spec.get('child'))
        for key in ['autoname', 'module', 'title_field']:
            assert (actual.get(key) or '') == (original.get(key) or ''), (name, key)
        for field in spec['fields']:
            value = actual.get_field(field['fieldname'])
            assert value and all((value.get(key) or '') == (field.get(key) or '') for key in ['fieldtype', 'label', 'options'])
            assert bool(value.reqd) == bool(field.get('reqd'))
        normalize = lambda row: tuple(row.get(key) if key == 'role' else int(row.get(key) or 0) for key in permissions)
        assert sorted(map(normalize, actual.permissions)) == sorted(map(normalize, original.get('permissions', [])))
    for route, (_, roles) in PAGES.items():
        page = frappe.get_doc('Page', route)
        slug = route.replace('-', '_')
        original = json.loads((installed / 'hospitality_suite/hospitality_suite/page' / slug / (slug + '.json')).read_text())
        assert {row.role for row in page.roles} == {row['role'] for row in original['roles']} == set(roles) | {'System Manager'}
        assert Path(frappe.get_app_path('hospitality_suite')).resolve() == installed / 'hospitality_suite'
    formats = []
    for path in sorted((installed / 'hospitality_suite/hospitality_suite/print_format').glob('*/*.json')):
        source = json.loads(path.read_text())
        actual = frappe.get_doc('Print Format', source['name'])
        assert all((actual.get(key) or '') == (source.get(key) or '') for key in ['doc_type', 'html', 'css', 'print_format_type'])
        formats.append(source['name'])
    assert len(formats) == 9
    patches = [line for line in (installed / 'hospitality_suite/patches.txt').read_text().splitlines() if line and not line.startswith(('[', '#'))]
    assert len(patches) == 6 and all(frappe.db.exists('Patch Log', {'patch': patch}) for patch in patches)
    assert all(callable(frappe.get_attr(patch + '.execute')) for patch in patches)
    assert all(callable(frappe.get_attr(name)) for name in [hooks.after_install, hooks.after_migrate, hooks.before_tests])
    initial = api.bootstrap()
    assert not initial['properties'] and len(initial['pages']) == 11 and initial['can_create_property']
    methods = sorted(name for name, method in inspect.getmembers(api, inspect.isfunction) if method in frappe.whitelisted)
    assert len(methods) == 28 and {'bootstrap', 'execute', 'preview', 'stay_detail', 'booking_detail', 'availability_search', 'export_report'}.issubset(methods)
    job = frappe.get_doc('Scheduled Job Type', {'method': 'hospitality_suite.jobs.expire_holds'})
    assert job.frequency == 'Cron' and job.cron_format == '*/5 * * * *'
    proof = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), site=SITE, database=frappe.conf.db_name,
        bench=str(BENCH), app_version=hospitality_suite.__version__, app_revision=package['revision'],
        independent_python_and_source=True, no_implicit_demo=True, empty_business_counts=counts,
        doctypes=len(SCHEMA), pages=len(PAGES), roles=len(ROLES), print_formats=formats, patches=patches,
        bootstrap=dict(properties=0, pages=len(initial['pages']), can_create_property=initial['can_create_property']),
        cores=cores, application_files_sha256={name: hashlib.sha256((installed / name).read_bytes()).hexdigest() for name in files},
        metadata_and_permissions_match=True, api_methods=methods, scheduler_paused=True, external_providers_activated=False)
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(site=SITE, doctypes=len(SCHEMA), pages=11, roles=9, formats=9, no_implicit_demo=True)))
finally:
    frappe.db.rollback()
    frappe.destroy()
