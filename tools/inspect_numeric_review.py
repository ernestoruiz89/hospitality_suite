"""Read-only database checks for the isolated numeric UX reproduction."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import frappe

parser = argparse.ArgumentParser()
parser.add_argument('--stage', choices=['scalar', 'grid-blocked', 'grid-saved'], required=True)
args = parser.parse_args()
bench = Path('/home/frappe/benches/hospitality-bench')
root = Path(__file__).resolve().parents[1]
assert (bench / '.hospitality-numeric-review-ux-baseline.json').is_file()
output = root / 'docs/evidence' / f'numeric-review-{args.stage}-database.json'
assert not output.exists(), 'Preserve each original observation'
os.chdir(bench / 'sites')
frappe.init(site='hospitality-acceptance.localhost', sites_path=str(bench / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_acceptance'
    assert frappe.conf.allow_tests and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
    frappe.set_user('Administrator')
    categories = frappe.get_all('HS Category', filters={'category_name': ['in', [
        'Revisión numérica temporal', 'Capacidad corregida temporal']]},
        fields=['category_name', 'capacity'], order_by='category_name')
    assert {row.category_name: row.capacity for row in categories} == {
        'Revisión numérica temporal': 1, 'Capacidad corregida temporal': 2}
    bookings = frappe.get_all('HS Booking', fields=['name', 'status'], order_by='name')
    rows = frappe.get_all('HS Booking Room', fields=['parent', 'idx', 'people', 'extra_beds'], order_by='parent, idx')
    draft_rooms = []
    if args.stage == 'grid-saved':
        assert len(bookings) == 1 and bookings[0].status == 'Draft' and not rows
        metadata = json.loads(frappe.db.get_value('HS Booking', bookings[0].name, 'draft_data'))
        draft_rooms = [{key: row.get(key) for key in ('people', 'extra_beds')} for row in metadata['rooms']]
        assert draft_rooms == [dict(people=2, extra_beds=0)]
    else:
        assert not bookings and not rows
    proof = dict(stage=args.stage, observed_at=datetime.now(timezone.utc).isoformat(),
        site=frappe.local.site, categories=categories, bookings=bookings, rooms=rows, draft_rooms=draft_rooms,
        method='Read-only database observation; not a network request trace',
        sources={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
            'hospitality_suite/public/js/hospitality.js', 'hospitality_suite/public/js/hospitality_forms.js')})
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    print(f'Numeric UX database observation: {args.stage}, {len(bookings)} reservations')
finally:
    frappe.db.rollback()
    frappe.destroy()
