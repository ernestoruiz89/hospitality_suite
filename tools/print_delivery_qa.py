"""Render nine real installed formats on a rolled-back, synthetic native scenario."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import frappe
from hospitality_suite.tests.test_print_delivery import FORMATS, fingerprints, make_scenario

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-acceptance.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='output/pdf/print-delivery')
args = parser.parse_args()
output = (ROOT / args.output).resolve()
assert output.is_relative_to(ROOT / 'output/pdf')
os.environ['PATH'] = str(BENCH / '.runtime/wkhtmltox/usr/local/bin') + os.pathsep + os.environ.get('PATH', '')
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler
    assert (BENCH / '.hospitality-print-delivery-ux-baseline.json').is_file()
    # wkhtmltopdf's resolver does not apply the browser's *.localhost rule.
    # Only this CLI render uses loopback for CSS/assets; the temporary server
    # is explicitly bound to this acceptance site. No site setting is changed.
    frappe.local.conf.host_name = 'http://127.0.0.1:8089'
    assert not any(frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Payment', 'Sales Invoice', 'HS Daily Close'])
    before = fingerprints()
    scenario = make_scenario()
    output.mkdir(parents=True, exist_ok=True)
    records = []
    frappe.local.lang = 'es'
    for slug, (doctype, fmt, actor) in FORMATS.items():
        frappe.set_user(actor + '@hospitality.example.invalid')
        html = frappe.get_print(doctype, scenario[slug], print_format=fmt)
        pdf = frappe.get_print(doctype, scenario[slug], print_format=fmt, as_pdf=True)
        assert pdf.startswith(b'%PDF-')
        path = output / (slug + '.pdf')
        path.write_bytes(pdf)
        records.append(dict(file=path.relative_to(ROOT).as_posix(), source_doctype=doctype, source=scenario[slug],
                            format=fmt, actor=actor, bytes=len(pdf), sha256=hashlib.sha256(pdf).hexdigest(),
                            html_sha256=hashlib.sha256(html.encode()).hexdigest()))
    frappe.db.rollback()
    frappe.set_user('Administrator')
    assert fingerprints() == before
    proof = dict(site=SITE, version='0.8.7', synthetic_native_scenario=True, provider_simulation=False,
                 render_asset_origin='http://127.0.0.1:8089', persisted_host_configuration_changed=False,
                 configured_format='App-owned defaults; custom format selection covered separately by tests.',
                 documents_committed=False, business_tables_equal_after_rollback=True, files=records)
    (ROOT / 'docs/evidence/print-delivery-pdfs.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(files=len(records), rolled_back=True, output=str(output))))
finally:
    frappe.db.rollback()
    frappe.destroy()
