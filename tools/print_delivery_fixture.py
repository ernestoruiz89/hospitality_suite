"""Explicit, disposable API fixture for reviewing print access from role Pages."""
import argparse
import json
import os
from pathlib import Path

import frappe
from hospitality_suite.tests.test_print_delivery import fingerprints, make_scenario

BENCH = Path('/home/frappe/benches/hospitality-bench')
ROOT = Path(__file__).resolve().parents[1]
SITE = 'hospitality-acceptance.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['prepare', 'inspect'])
args = parser.parse_args()
path = BENCH/'sites'/SITE/'private/print-delivery-fixture.json'
os.chdir(BENCH/'sites')
frappe.init(site=SITE, sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler
    assert frappe.conf.hospitality_integration_test_site and (BENCH/'.hospitality-print-delivery-ux-baseline.json').is_file()
    frappe.set_user('Administrator')
    if args.action == 'prepare':
        assert not any(frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Payment', 'Sales Invoice', 'HS Daily Close'])
        scenario = make_scenario()
        proof = dict(scenario=scenario, fixture_origin='Native API fixture; role Page test covers print access, not UI creation of these records.',
                     business_fingerprints=fingerprints())
        frappe.db.commit()
        path.write_text(json.dumps(proof))
        path.chmod(0o600)
        print('Disposable native print fixture prepared; no external provider contacted.')
    else:
        saved = json.loads(path.read_text())
        assert fingerprints() == saved['business_fingerprints']
        names = saved['scenario']
        assert frappe.db.get_value('HS Stay', names['registration'], 'status') == 'Active'
        assert frappe.db.get_value('HS Daily Close', names['daily_close'], 'status') == 'Closed'
        assert frappe.db.get_value('HS Shift', names['shift'], 'status') == 'Closed'
        assert frappe.db.get_value('Sales Invoice', names['invoice'], 'outstanding_amount') == 1000
        counts = {dt: frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift', 'HS Cleaning Task',
                  'HS Maintenance Order', 'HS Daily Close', 'Sales Invoice', 'Payment Entry', 'Journal Entry']}
        assert counts == {name: int(name != 'Journal Entry') for name in counts}
        proof = dict(site=SITE, fixture_origin=saved['fixture_origin'], print_access_only=True,
                     operations_created_by_ui=False, business_documents_unchanged_by_print_review=True, operation_counts=counts,
                     sources=names, business_fingerprints=saved['business_fingerprints'])
        (ROOT/'docs/evidence/print-delivery-ui-data.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
        print(json.dumps(dict(business_documents_unchanged=True, operation_counts=counts)))
finally:
    frappe.db.rollback()
    frappe.destroy()
