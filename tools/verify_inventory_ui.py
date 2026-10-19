"""Read-only native ledger checkpoints of the UX-INV-001 Page workflow."""
import json
import os
from pathlib import Path

import frappe

bench=Path('/home/frappe/benches/hospitality-bench')
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    laundry=frappe.get_doc('Warehouse',{'warehouse_name':'Lavandería UX-INV-001'})
    assert prop.laundry_warehouse==laundry.name and laundry.hs_property==prop.name
    transfer=frappe.get_doc('Stock Entry',{'remarks':'Traslado sintético de agua UX-INV-001 a ubicación de lavandería'})
    assert transfer.docstatus==1 and transfer.hs_stock_purpose=='Transfer' and len(transfer.items)==1
    line=transfer.items[0]
    assert line.item_code=='HS-DEMO-WATER' and line.qty==2 and line.s_warehouse==prop.warehouse and line.t_warehouse==laundry.name
    audits=frappe.get_all('HS Audit Event',filters={'reason':'Conteo sintético UX-INV-001: dos esperadas y una encontrada'},fields=['source_doctype','source_name'])
    assert len(audits)==1 and audits[0].source_doctype=='Stock Reconciliation'
    count=frappe.get_doc('Stock Reconciliation',audits[0].source_name)
    assert count.docstatus==1 and len(count.items)==1 and count.items[0].qty==1
    linen=frappe.get_all('HS Incident',filters={'property':prop.name,'kind':'Linen','description':['like','%UX-INV-001%']},fields=['name','description','quantity','stock_entry','owner'],order_by='creation')
    assert len(linen)==3
    for row,qty,purpose in zip(linen,[2,1,1],['Laundry','Laundry','Waste']):
        assert row.quantity==qty and row.owner=='housekeeping@hospitality.example.invalid'
        entry=frappe.get_doc('Stock Entry',row.stock_entry)
        assert entry.docstatus==1 and entry.hs_property==prop.name and entry.hs_stock_purpose==purpose
        assert len(entry.items)==1 and entry.items[0].item_code=='HS-DEMO-LINEN' and entry.items[0].qty==qty
        if purpose=='Waste':
            assert not entry.items[0].t_warehouse and entry.items[0].s_warehouse==laundry.name
        assert frappe.db.count('Stock Ledger Entry',{'voucher_no':entry.name,'is_cancelled':0})==(1 if purpose=='Waste' else 2)
    water={w:frappe.db.get_value('Bin',{'item_code':'HS-DEMO-WATER','warehouse':w},'actual_qty') for w in (prop.warehouse,laundry.name)}
    sheets={w:frappe.db.get_value('Bin',{'item_code':'HS-DEMO-LINEN','warehouse':w},'actual_qty') for w in (prop.warehouse,laundry.name)}
    assert list(water.values())==[91,1] and list(sheets.values())==[1,0]
    assert frappe.db.count('GL Entry',{'voucher_no':count.name,'is_cancelled':0})==2
    result=dict(synthetic=True,transfer=transfer.name,stock_reconciliation=count.name,count_gl_entries=2,
                water=water,linen=sheets,linen_movements=[dict(name=r.name,stock_entry=r.stock_entry,quantity=r.quantity,actor=r.owner) for r in linen])
    Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/inventory-ui.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
finally:
    frappe.db.rollback()
    frappe.destroy()
