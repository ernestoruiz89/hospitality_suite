"""Native synthetic masters; configuration, sale and closure use the Desk Pages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
FIXTURE=BENCH/'.hospitality-accounting-ux-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect']);args=parser.parse_args()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
    frappe.set_user('Administrator')
    from hospitality_suite import api
    from hospitality_suite.cashier import expected
    def shared_defaults():
        rows=frappe.get_all('Item Default',filters={'parent':'HS-DEMO-WATER'},fields=['*'],order_by='name')
        return hashlib.sha256(json.dumps(rows,default=str,sort_keys=True).encode()).hexdigest()
    if args.action=='prepare':
        assert (BENCH/'.hospitality-accounting-ux-baseline.json').is_file()
        assert all(frappe.db.count(dt)==0 for dt in ('HS Stay','HS Booking','HS Payment','HS Shift','Sales Invoice','Payment Entry'))
        baseline=json.loads((BENCH/'.hospitality-accounting-ux-baseline.json').read_text())
        assert frappe.db.count('Stock Entry')==baseline['tables']['Stock Entry']['rows']
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        def account(root,name):
            return frappe.get_doc(dict(doctype='Account',company=prop.company,account_name=name,account_currency='NIO',
                parent_account=frappe.db.get_value('Account',{'company':prop.company,'root_type':root,'is_group':1}))).insert().name
        def center(name):
            return frappe.get_doc(dict(doctype='Cost Center',company=prop.company,cost_center_name=name,
                parent_cost_center=frappe.db.get_value('Cost Center',{'company':prop.company,'is_group':1}))).insert().name
        defaults=dict(income_account=account('Income','Ingresos sede UX'),expense_account=account('Expense','Gastos sede UX'),cost_center=center('Operación sede UX'))
        service=dict(item='HS-DEMO-WATER',income_account=account('Income','Ingresos minibar UX'),expense_account=account('Expense','Costos minibar UX'),cost_center=center('Minibar UX'))
        shift=api.execute(prop.name,'open_shift',uuid.uuid4().hex,dict(opening_amount=100))['shift']
        FIXTURE.write_text(json.dumps(dict(property=prop.name,defaults=defaults,service=service,shift=shift,shared_defaults=shared_defaults())))
        FIXTURE.chmod(0o600);frappe.db.commit()
        print('Cuentas y centros de costo sintéticos creados. Turno abierto con fondo 100; sin configuración ni ventas preparadas.')
    else:
        fixture=json.loads(FIXTURE.read_text())
        prop=frappe.get_doc('HS Property',fixture['property'])
        assert all(prop.get(field)==name for field,name in fixture['defaults'].items())
        assert len(prop.service_accounts)==1
        mapping=prop.service_accounts[0]
        assert all(mapping.get(field)==name for field,name in fixture['service'].items())
        assert shared_defaults()==fixture['shared_defaults']
        event=frappe.get_doc('HS Audit Event',{'property':prop.name,'action':'Service accounting configuration'})
        assert event.actor=='manager@hospitality.example.invalid'
        service=frappe.get_doc('HS Service Request',{'property':prop.name,'status':'Delivered'})
        assert not service.stay and service.item=='HS-DEMO-WATER' and service.amount==30
        invoice=frappe.get_doc('Sales Invoice',service.sales_invoice)
        stock=frappe.get_doc('Stock Entry',service.stock_entry)
        for doc in (invoice,stock):
            assert doc.docstatus==1 and doc.items[0].cost_center==mapping.cost_center
        assert invoice.items[0].income_account==mapping.income_account
        assert stock.items[0].expense_account==mapping.expense_account
        revenue=frappe.get_all('GL Entry',filters={'voucher_type':'Sales Invoice','voucher_no':invoice.name,'account':mapping.income_account,'is_cancelled':0},fields=['debit','credit','cost_center'])
        cost=frappe.get_all('GL Entry',filters={'voucher_type':'Stock Entry','voucher_no':stock.name,'account':mapping.expense_account,'is_cancelled':0},fields=['debit','credit','cost_center'])
        assert sum(row.credit-row.debit for row in revenue)==30 and sum(row.debit-row.credit for row in cost)>0
        assert all(row.cost_center==mapping.cost_center for row in revenue+cost)
        shift=frappe.get_doc('HS Shift',fixture['shift'])
        assert shift.status=='Closed' and shift.expected_amount==shift.counted_amount==130 and not shift.difference and expected(shift)=={'NIO':'130.00'}
        sales=frappe.get_all('HS Audit Event',filters={'property':prop.name,'action':'Direct sale'},fields=['actor'])
        assert len(sales)==1 and sales[0].actor==event.actor
        proof=dict(site=SITE,synthetic=True,fixture_origin='ERPNext Account and Cost Center controllers; application shift API',
            configuration_from_page=True,sale_from_page=True,closed_from_page=True,actor=event.actor,
            defaults=fixture['defaults'],service=fixture['service'],service_label=frappe.db.get_value('Item',mapping.item,'item_name'),
            invoice=invoice.name,stock_entry=stock.name,revenue='30.00',cost=str(sum(row.debit-row.credit for row in cost)),
            revenue_and_cost_center_preserved=True,shared_item_defaults_unchanged=True,opening='100.00',final_expected='130.00',difference='0.00')
        (ROOT/'docs/evidence/accounting-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback();frappe.destroy()
