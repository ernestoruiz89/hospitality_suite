"""Real two-session races on release only; separately prove the main-site refusal."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import frappe
from hospitality_suite.tests import concurrency

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('case', choices=['guard', 'room', 'category'])
parser.add_argument('--label')
args = parser.parse_args()
assert args.label is None or re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', args.label)
if args.case == 'guard':
    bench = Path('/home/frappe/benches/hospitality-bench')
    site, database = 'hospitality.localhost', 'hospitality_dev'
else:
    bench = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
    site, database = 'hospitality-release.localhost', 'hospitality_release'
assert Path(sys.executable).parent == bench / 'env/bin'
output = ROOT / f'docs/evidence/release-install-concurrency-{args.label or args.case}.json'
assert not output.exists(), 'Preserve the original trial'
source = Path(concurrency.__file__)
assert source.read_bytes() == (ROOT / 'hospitality_suite/tests/concurrency.py').read_bytes()
os.chdir(bench / 'sites')
frappe.init(site=site, sites_path=str(bench / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == database and frappe.conf.allow_tests
    frappe.set_user('Administrator')
    if args.case == 'guard':
        assert not frappe.conf.get('hospitality_integration_test_site')
        try:
            concurrency.verify()
        except frappe.ValidationError as error:
            assert 'hospitality_integration_test_site' in str(error)
        else:
            raise AssertionError('The operational demonstration must never run committed race fixtures')
        result = dict(passed=True, main_site_rejected=True, database_mutations=False)
    else:
        assert frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
        result = concurrency.verify(args.case)
        frappe.db.commit()  # Same final success commit as native bench execute; retains audited cancellations.
        assert result['passed'] and sorted(row['result'] for row in result['sessions']) == ['confirmed', 'rejected']
        assert not frappe.db.count('HS Allocation', {'kind': 'Reservation', 'status': 'Active'})
        assert all(row.status == 'Cancelled' for row in frappe.get_all('HS Booking', fields=['status']))
        result.update(audited_cleanup_committed=True, active_reservations=0, database_mutations=True)
    result.update(observed_at_utc=datetime.now(timezone.utc).isoformat(), site=site, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
