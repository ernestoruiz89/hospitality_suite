"""One explicit stock fixture and read-only checkpoints for role Page acceptance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import frappe

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-acceptance.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('stage', choices=['prepare-part', 'scalar', 'issued', 'returned', 'completed'])
args = parser.parse_args()
private = BENCH / 'sites' / SITE / 'private/task-state-fixture.json'
output = ROOT / 'docs/evidence' / f'task-state-{args.stage}-database.json'
assert not output.exists(), 'Preserve every observation'
assert (BENCH / '.hospitality-task-state-review-ux-baseline.json').is_file()
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    require_test_site(paused=True)
    assert frappe.conf.db_name == 'hospitality_acceptance'
    frappe.set_user('Administrator')
    prop = frappe.get_doc('HS Property', {'property_name': 'Hotel Jardín Demo'})
    assert str(prop.business_date) == '2026-10-19'
    categories = frappe.get_all('HS Category', filters={'property': prop.name, 'category_name': 'Capacidad clara temporal'},
        fields=['category_name', 'capacity', 'owner'])
    if args.stage == 'scalar':
        assert len(categories) == 1 and categories[0].capacity == 2
        assert categories[0].owner == 'manager@hospitality.example.invalid'
    if args.stage == 'prepare-part':
        assert not private.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Maintenance Order', 'HS Booking', 'HS Stay', 'HS Charge', 'HS Payment'])
        item = frappe.get_doc(dict(doctype='Item', item_code='HS-UX-PART-TS', item_name='Válvula de prueba temporal',
            item_group='Products', stock_uom='Nos', is_stock_item=1, is_sales_item=0, is_purchase_item=1)).insert()
        from hospitality_suite.accounting import post_standard
        receipt = frappe.new_doc('Stock Entry')
        receipt.update(dict(company=prop.company, stock_entry_type='Material Receipt'))
        receipt.append('items', dict(item_code=item.name, qty=10, t_warehouse=prop.warehouse, basic_rate=20))
        post_standard(receipt, prop)
        fixture = dict(item=item.name, item_label=item.item_name, receipt=receipt.name, warehouse=prop.warehouse,
            initial_quantity=10, unit_cost=20, fixture_origin='Explicit native Item and opening Stock Entry only; maintenance actions must come from role Pages.')
        private.write_text(json.dumps(fixture))
        private.chmod(0o600)
        frappe.db.commit()
    else:
        fixture = json.loads(private.read_text()) if private.exists() else None
    proof = dict(stage=args.stage, observed_at_utc=datetime.now(timezone.utc).isoformat(), site=SITE,
        database_mutation=args.stage == 'prepare-part', categories=categories)
    if fixture:
        proof['fixture'] = fixture
        proof['quantity'] = frappe.db.get_value('Bin', {'item_code': fixture['item'], 'warehouse': fixture['warehouse']}, 'actual_qty')
    if args.stage in ['issued', 'returned', 'completed']:
        orders = frappe.get_all('HS Maintenance Order', filters={'property': prop.name, 'title': 'Revisar grifería temporal'}, pluck='name')
        assert len(orders) == 1
        order = frappe.get_doc('HS Maintenance Order', orders[0])
        assert order.owner == 'maintenance@hospitality.example.invalid'
        assert order.assigned_to == order.owner and order.blocks_room and order.until_reopened
        assert order.parts and len(order.parts) == 1
        part = order.parts[0]
        assert part.item == fixture['item'] and part.quantity == 2
        entry = frappe.get_doc('Stock Entry', part.stock_entry)
        assert entry.stock_entry_type == 'Material Issue'
        assert entry.owner == 'maintenance@hospitality.example.invalid'
        if args.stage == 'issued':
            assert order.status == 'In Progress' and order.cost == 40 and proof['quantity'] == 8
            assert part.status == 'Issued' and entry.docstatus == 1
        else:
            assert order.cost == 0 and proof['quantity'] == 10
            assert part.status == 'Returned' and entry.docstatus == 2
        allocations = frappe.get_all('HS Allocation', filters={'maintenance': order.name},
            fields=['status', 'starts_at', 'ends_at', 'room'])
        assert len(allocations) == 1
        assert allocations[0].status == ('Released' if args.stage == 'completed' else 'Active')
        if args.stage == 'completed':
            assert order.status == 'Completed'
            assert order.modified_by == 'supervisor@hospitality.example.invalid'
            incident = frappe.get_doc('HS Incident', {'property': prop.name,
                'description': 'Llave sintética encontrada durante la revisión temporal de H101.'})
            assert incident.owner == 'maintenance@hospitality.example.invalid'
            assert incident.status == 'Resolved' and incident.resolved_by == 'manager@hospitality.example.invalid'
            assert incident.resolved_at and incident.resolution.startswith('Llave sintética entregada')
            proof['incident'] = dict(name=incident.name, status=incident.status, owner=incident.owner,
                resolved_by=incident.resolved_by, resolved_at=incident.resolved_at, resolution=incident.resolution)
            proof['audit'] = frappe.get_all('HS Audit Event', filters={'source_name': ['in', [order.name, incident.name]]},
                fields=['action', 'actor', 'source_name'], order_by='creation asc')
            assert {'maintenance@hospitality.example.invalid', 'manager@hospitality.example.invalid',
                'supervisor@hospitality.example.invalid'} <= {row.actor for row in proof['audit']}
        proof.update(order=dict(name=order.name, owner=order.owner, status=order.status, cost=order.cost,
            room=frappe.db.get_value('HS Room', order.room, 'room_number'), assigned_to=order.assigned_to),
            part=dict(item=part.item, quantity=part.quantity, status=part.status, stock_entry=entry.name,
                native_document_status=entry.docstatus, owner=entry.owner), allocations=allocations)
    proof['financial_operation_counts'] = {dt: frappe.db.count(dt) for dt in
        ['HS Booking', 'HS Stay', 'HS Charge', 'HS Payment', 'HS Shift', 'Sales Invoice', 'Payment Entry', 'Journal Entry']}
    assert not any(proof['financial_operation_counts'].values())
    proof['sources_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
        ['hospitality_suite/public/js/hospitality_forms.js', 'hospitality_suite/public/js/hospitality_workflows.js']}
    output.write_text(json.dumps(proof, default=str, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(stage=args.stage, categories=len(categories), quantity=proof.get('quantity'), order=proof.get('order'))))
finally:
    frappe.db.rollback()
    frappe.destroy()
