"""Explicit disposable prerequisites and read-only checkpoints for secondary Pages."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import frappe

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-acceptance.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['prepare', 'checkpoint'])
parser.add_argument('--label', default='prepared')
args = parser.parse_args()
assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.label)
path = BENCH / 'sites' / SITE / 'private/secondary-acceptance-fixture.json'
output = ROOT / 'docs/evidence' / f'secondary-acceptance-{args.label}-database.json'
assert not output.exists(), 'Preserve each observation'
assert (BENCH / '.hospitality-secondary-acceptance-ux-baseline.json').is_file()
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    from hospitality_suite import api
    require_test_site(paused=True)
    assert frappe.conf.db_name == 'hospitality_acceptance'
    frappe.set_user('Administrator')
    prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
    assert str(prop.business_date) == '2026-10-19'
    if args.action == 'prepare':
        assert not path.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift',
            'HS Maintenance Order', 'HS Incident', 'HS Daily Close', 'Sales Invoice', 'Payment Entry', 'Journal Entry'])
        from hospitality_suite.accounting import post_standard
        from hospitality_suite.time import now_local
        def account(label, root='Asset', kind=None):
            parent = frappe.db.get_value('Account', dict(company=prop.company, root_type=root, is_group=1,
                parent_account=['is', 'not set']), 'name')
            assert parent
            return frappe.get_doc(dict(doctype='Account', company=prop.company, parent_account=parent,
                account_name=label, account_currency=prop.currency, account_type=kind)).insert().name
        accounts = dict(expense=account('Gasto de aceptación secundaria', 'Expense'),
            clearing=account('Compensación de aceptación secundaria', kind='Bank'),
            bank=account('Banco de aceptación secundaria', kind='Bank'),
            withholding=account('Retención de aceptación secundaria'))
        mode = frappe.get_doc(dict(doctype='Mode of Payment', mode_of_payment='Tarjeta de aceptación secundaria', type='Bank',
            accounts=[dict(company=prop.company, default_account=accounts['clearing'])])).insert()
        items = {}
        for code, label, rate in [('HS-UX-PART-SEC', 'Válvula de aceptación secundaria', 20),
                ('HS-UX-LINEN-SEC', 'Sábana de aceptación secundaria', 50)]:
            item = frappe.get_doc(dict(doctype='Item', item_code=code, item_name=label, item_group='Products', stock_uom='Nos',
                is_stock_item=1, is_sales_item=0, is_purchase_item=1)).insert()
            receipt = frappe.new_doc('Stock Entry')
            receipt.update(dict(company=prop.company, stock_entry_type='Material Receipt'))
            receipt.append('items', dict(item_code=item.name, qty=10, t_warehouse=prop.warehouse, basic_rate=rate))
            post_standard(receipt, prop)
            items[code] = dict(label=label, receipt=receipt.name, quantity=10, unit_rate=rate)
        def execute(action, values):
            return api.execute(prop.name, action, uuid.uuid4().hex, values)
        start = now_local(prop).replace(microsecond=0)
        order_room = frappe.db.get_value('HS Room', {'property': prop.name, 'room_number': 'H110'}, 'name')
        maintenance = execute('maintenance', dict(room=order_room, title='Orden de apoyo a aceptación secundaria', kind='Preventive',
            starts_at=start.isoformat(), until_reopened=1, assigned_to='maintenance@hospitality.example.invalid'))
        room = frappe.get_doc('HS Room', {'property': prop.name, 'room_number': 'H101'})
        guest = frappe.get_doc('HS Guest', {'property': prop.name})
        values = dict(starts_at=start.isoformat(), ends_at=(start + timedelta(days=1)).isoformat(), guest=guest.name,
            customer=guest.customer, rooms=[dict(room=room.name, category=room.category, people=1)])
        values['acceptance'] = api.preview(prop.name, values)['acceptance']
        stay = execute('walk_in', values)
        fixture = dict(property=prop.name, company=prop.company, warehouse=prop.warehouse, accounts=accounts,
            card_mode=mode.name, items=items, maintenance=maintenance, stay=stay,
            origin='Native fixture: four accounts, one payment mode, two Item/opening Stock Entries, H110 maintenance and H101 stay. Subsequent secondary commands must be submitted through role Pages.')
    else:
        fixture = json.loads(path.read_text(encoding='utf-8'))
    counts = {dt: frappe.db.count(dt) for dt in ['HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift',
        'HS Maintenance Order', 'HS Incident', 'HS Retention Run', 'Sales Invoice', 'Payment Entry', 'Journal Entry',
        'Purchase Order', 'Purchase Receipt', 'Purchase Invoice', 'Stock Entry', 'Stock Reconciliation', 'GL Entry', 'File']}
    stock = frappe.get_all('Bin', filters={'item_code': ['in', ['HS-DEMO-WATER', *fixture['items']]]},
        fields=['item_code', 'warehouse', 'actual_qty', 'valuation_rate'], order_by='item_code, warehouse')
    payments = frappe.get_all('HS Payment', filters={'property': prop.name},
        fields=['name', 'kind', 'amount', 'currency', 'owner', 'status', 'source_payment', 'journal_entry', 'payment_entry'], order_by='creation')
    proof = dict(observed_at_utc=datetime.now(timezone.utc).isoformat(), label=args.label, site=SITE,
        fixture_origin=fixture['origin'], database_mutation=args.action == 'prepare', fixture=fixture,
        counts=counts, stock=stock, payments=payments,
        maintenance=frappe.get_all('HS Maintenance Order', filters={'property': prop.name},
            fields=['name', 'title', 'status', 'evidence', 'modified', 'modified_by']),
        incidents=frappe.get_all('HS Incident', filters={'property': prop.name},
            fields=['name', 'kind', 'description', 'status', 'evidence', 'owner', 'resolved_by', 'resolution']),
        private_attachments=frappe.get_all('File', filters={'is_private': 1, 'attached_to_doctype': ['in', ['HS Maintenance Order', 'HS Incident', 'HS Guest']]},
            fields=['name', 'file_name', 'file_url', 'owner', 'attached_to_doctype', 'attached_to_name']),
        source_sha256=hashlib.sha256((ROOT / 'hospitality_suite/public/js/hospitality.js').read_bytes()).hexdigest())
    serialized = json.dumps(proof, ensure_ascii=False, indent=2, default=str) + '\n'
    if args.action == 'prepare':
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        path.chmod(0o600)
        frappe.db.commit()
    output.write_text(serialized, encoding='utf-8', newline='\n')
    print(json.dumps(dict(stage=args.label, mutation=proof['database_mutation'], counts=counts)))
finally:
    frappe.db.rollback()
    frappe.destroy()
