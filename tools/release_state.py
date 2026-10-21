"""Read only the named release site's explicit setup/test state."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import frappe

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
SITE = 'hospitality-release.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('stage', choices=['setup', 'restored', 'native-fixture', 'after-concurrency'])
args = parser.parse_args()
output = ROOT / f'docs/evidence/release-install-state-{args.stage}.json'
assert not output.exists()
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name == 'hospitality_release' and frappe.conf.pause_scheduler and frappe.conf.allow_tests
    frappe.set_user('Administrator')
    counts = {name: frappe.db.count(name) for name in ['Company', 'HS Property', 'HS Category', 'HS Room', 'HS Rate',
        'HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift', 'HS Daily Close', 'Sales Invoice',
        'Payment Entry', 'Journal Entry', 'GL Entry', 'Stock Entry']}
    assert not any(counts[name] for name in ['HS Stay', 'HS Charge', 'HS Payment', 'HS Shift', 'HS Daily Close',
        'Sales Invoice', 'Payment Entry', 'Journal Entry'])
    opening_stock = []
    if args.stage == 'setup':
        assert counts['Stock Entry'] == counts['GL Entry'] == 0
        assert counts['Company'] == counts['HS Property'] == 1
        assert not any(counts[name] for name in ['HS Category', 'HS Room', 'HS Rate', 'HS Booking'])
        assert frappe.db.exists('Company', 'Instalación PMS')
        prop = frappe.get_doc('HS Property', {'property_name': 'Hotel de instalación'})
        assert (prop.company, prop.mode, prop.currency, prop.time_zone, prop.financial_enabled) == ('Instalación PMS', 'Hotel', 'NIO', 'America/Managua', 0)
        assert frappe.db.get_single_value('System Settings', 'setup_complete')
    elif args.stage == 'restored':
        assert not any(counts.values())
    else:
        assert (counts['Company'], counts['HS Property'], counts['HS Category'], counts['HS Rate']) == (1, 2, 2, 2), counts
        assert counts['HS Room'] == 20
        assert counts['Stock Entry'] == 1, counts
        for name in frappe.get_all('Stock Entry', pluck='name'):
            entry = frappe.get_doc('Stock Entry', name)
            assert entry.stock_entry_type == 'Material Receipt' and entry.docstatus == 1 and len(entry.items) == 1
            item = entry.items[0]
            assert item.item_code == 'HS-DEMO-WATER' and item.qty == 100 and item.basic_rate == 10
            ledger = frappe.get_all('GL Entry', filters={'voucher_type': 'Stock Entry', 'voucher_no': name}, fields=['company', 'debit', 'credit'])
            assert len(ledger) == 2 and all(row.company == entry.company for row in ledger)
            assert sum(row.debit for row in ledger) == sum(row.credit for row in ledger) == entry.total_incoming_value
            opening_stock.append(dict(voucher=name, company=entry.company, item=item.item_code, quantity=item.qty,
                native_ledger_entries=len(ledger), balanced_in_company_currency=True))
        assert counts['GL Entry'] == 2, counts
        if args.stage == 'native-fixture':
            assert counts['HS Booking'] == 0
        else:
            assert counts['HS Booking'] > 0
            assert all(row.status == 'Cancelled' and row.channel == 'Prueba de concurrencia'
                for row in frappe.get_all('HS Booking', fields=['status', 'channel']))
    proof = dict(observed_at_utc=datetime.now(timezone.utc).isoformat(), site=SITE, stage=args.stage, counts=counts,
        scheduler_paused=True, database_mutations=False, explicit_fixture_opening_stock=opening_stock,
        app_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=BENCH / 'apps/hospitality_suite', text=True).strip())
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(stage=args.stage, counts=counts)))
finally:
    frappe.db.rollback()
    frappe.destroy()
