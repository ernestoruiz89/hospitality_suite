"""Read-only installed inventory for S18-02; not proof of overall completion."""
from datetime import datetime, timezone
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path

import frappe
from frappe.model.base_document import get_controller
import hospitality_suite
from hospitality_suite import api, hooks
from hospitality_suite.controllers import ScopedDocument
from hospitality_suite.schema import SCHEMA, PAGES

ROOT = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--phase',choices=['print-delivery','provider-contracts'],default='print-delivery')
args=parser.parse_args()
BENCH = Path('/home/frappe/benches/hospitality-bench')
META = ROOT / 'hospitality_suite/hospitality_suite'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
sources = [ROOT/'hospitality_suite/hooks.py', ROOT/'hospitality_suite/install.py', ROOT/'hospitality_suite/api.py',
           ROOT/'hospitality_suite/schema.py', ROOT/'hospitality_suite/controllers.py', ROOT/'hospitality_suite/printing.py', ROOT/'hospitality_suite/demo.py',
           ROOT/'hospitality_suite/tests/setup.py', ROOT/'hospitality_suite/patches.txt']
if args.phase=='provider-contracts':
    sources += [ROOT/'hospitality_suite/provider_adapters.py',ROOT/'hospitality_suite/tests/test_provider_adapters.py']
formats = []
for path in sorted((META/'print_format').glob('*/*.json')):
    source = json.loads(path.read_text())
    template = ROOT/'hospitality_suite/templates/print'/path.parent.name.removeprefix('hs_')
    template = template.with_suffix('.html')
    assert source['html'] == template.read_text()
    formats.append((path, source))
    sources += [path, template]
assert len(formats) == 9
patches = [line for line in (ROOT/'hospitality_suite/patches.txt').read_text().splitlines() if line and not line.startswith(('[', '#'))]
assert len(patches) == 6
whitelisted = [name for name, method in inspect.getmembers(api, inspect.isfunction) if method in frappe.whitelisted]
assert {'bootstrap', 'execute', 'preview', 'stay_detail', 'booking_detail', 'availability_search', 'export_report'}.issubset(whitelisted)
assert 'hospitality_suite.printing' in hooks.jinja['methods']
jobs = hooks.scheduler_events['cron']['*/5 * * * *']
assert jobs == ['hospitality_suite.jobs.expire_holds']
proof = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), version=hospitality_suite.__version__, requirement='S18-02',
    database_mutations=False, overall_application_acceptance=False, sites={}, api_methods=whitelisted,
    fixture_strategy='App-owned native JSON plus idempotent install/migrate roles, fields and permissions; explicit demo/test fixtures, never business demo seeding on install.',
    provider_activation=False)
os.chdir(BENCH/'sites')
for site, database in [('hospitality.localhost', 'hospitality_dev'), ('hospitality-acceptance.localhost', 'hospitality_acceptance')]:
    frappe.init(site=site, sites_path=str(BENCH/'sites'))
    frappe.connect()
    try:
        assert frappe.conf.db_name == database and frappe.conf.allow_tests
        assert all(callable(frappe.get_attr(name+'.execute')) for name in patches)
        assert all(callable(frappe.get_attr(name)) for name in [hooks.after_install, hooks.after_migrate, hooks.before_tests, 'hospitality_suite.demo.seed', jobs[0]])
        assert all(callable(frappe.get_attr(fn)) for events in hooks.doc_events.values() for fn in events.values())
        for name, spec in SCHEMA.items():
            slug = name.lower().replace(' ', '_')
            path = META/'doctype'/slug/(slug+'.json')
            source = json.loads(path.read_text())
            controller = META/'doctype'/slug/(slug+'.py')
            sources += [path, controller]
            actual = frappe.get_meta(name)
            for key in ['autoname', 'module', 'title_field']:
                assert (actual.get(key) or '') == (source.get(key) or ''), (site, name, key)
            assert bool(actual.istable) == bool(spec.get('child'))
            assert issubclass(get_controller(name), ScopedDocument)
            for field in spec['fields']:
                installed = actual.get_field(field['fieldname'])
                assert installed and installed.fieldtype == field['fieldtype'] and installed.label == field['label']
                assert (installed.options or '') == (field.get('options') or '')
                assert bool(installed.reqd) == bool(field.get('reqd'))
            keys = ['role', 'permlevel', 'read', 'write', 'create', 'print', 'report', 'export', 'delete']
            normalized = lambda row: tuple(row.get(key) if key == 'role' else int(row.get(key) or 0) for key in keys)
            actual_permissions = frappe.get_doc('DocType', name).permissions
            assert {normalized(row) for row in actual_permissions} == {normalized(row) for row in source['permissions']}, (site, name, 'permissions')
        for route in PAGES:
            slug = route.replace('-', '_')
            path = META/'page'/slug/(slug+'.json')
            script = path.with_suffix('.js')
            source = json.loads(path.read_text())
            page = frappe.get_doc('Page', route)
            assert page.title == source['title'] and {row.role for row in page.roles} == {row['role'] for row in source['roles']}
            assert 'new hospitality_suite.Desk(wrapper, "'+route+'")' in script.read_text()
            sources += [path, script]
        for path, source in formats:
            installed = frappe.get_doc('Print Format', source['name'])
            for key in ['doc_type', 'module', 'standard', 'print_format_type', 'html', 'css']:
                assert installed.get(key) == source.get(key), (site, source['name'], key)
        for patch in patches:
            assert frappe.db.exists('Patch Log', {'patch': patch}), (site, patch)
        job = frappe.get_doc('Scheduled Job Type', {'method': jobs[0]})
        assert job.frequency == 'Cron' and job.cron_format == '*/5 * * * *'
        assert set(frappe.get_installed_apps()) >= {'frappe', 'erpnext', 'hospitality_suite'}
        proof['sites'][site] = dict(doctypes=len(SCHEMA), pages=len(PAGES), print_formats=len(formats), patches=len(patches),
            scoped_controllers_verified=True, fields_and_permissions_match_source=True, installed_scheduler_method=job.method,
            installed_scheduler_enabled=not bool(job.stopped), site_scheduler_paused=bool(frappe.conf.pause_scheduler))
    finally:
        frappe.db.rollback()
        frappe.destroy()
proof['source_sha256'] = {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(set(sources))}
(ROOT/f'docs/evidence/{args.phase}-native-artifacts.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(doctypes=len(SCHEMA), pages=len(PAGES), formats=9, patches=6, api_methods=len(whitelisted), sites=2)))
