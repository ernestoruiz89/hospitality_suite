"""Synthetic applied-advance fixture; only the refund is submitted from the Page."""
import argparse,json,os,uuid
from datetime import timedelta
from pathlib import Path

import frappe
from frappe.utils import now_datetime

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
FIXTURE=BENCH/'.hospitality-refund-ux-fixture.json'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','inspect'])
args=parser.parse_args()
os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
    frappe.set_user('Administrator')
    from hospitality_suite import api
    from hospitality_suite.cashier import expected
    if args.action=='prepare':
        assert (BENCH/'.hospitality-refund-ux-baseline.json').is_file()
        assert all(frappe.db.count(dt)==0 for dt in ('HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'))
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'})
        method=frappe.get_doc('HS Payment Method',{'property':prop.name,'is_cash':1,'currency':'NIO'})
        def call(action,data):return api.execute(prop.name,action,uuid.uuid4().hex,data)
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(room=room.name,category=room.category,people=1)])
        stay=call('walk_in',dict(values,acceptance=api.preview(prop.name,values)['acceptance']))
        shift=call('open_shift',dict(opening_amount=0))['shift']
        paid=call('payment',dict(stay=stay['stay'],folio=stay['folio'],shift=shift,method=method.name,kind='Advance',amount=1500))
        invoice=call('invoice',dict(folio=stay['folio']))['invoice']
        credit=call('credit_note',dict(invoice=invoice,reason='Cancelación sintética para UX de devolución'))['credit_note']
        proof=dict(property=prop.name,shift=shift,stay=stay['stay'],folio=stay['folio'],source=paid['payment'],original=paid['payment_entry'],invoice=invoice,credit=credit)
        FIXTURE.write_text(json.dumps(proof));FIXTURE.chmod(0o600)
        frappe.db.commit()
        print('Fixture sintético: H101, anticipo 1500 aplicado, factura y nota de crédito estándar; devolución pendiente de la Page')
    else:
        fixture=json.loads(FIXTURE.read_text())
        refunds=frappe.get_all('HS Payment',filters={'source_payment':fixture['source'],'kind':'Refund','status':'Posted'},fields=['name','payment_entry','sales_invoice','amount','currency'])
        assert len(refunds)==1 and refunds[0].amount==1500 and refunds[0].sales_invoice==fixture['credit']
        original=frappe.get_doc('Payment Entry',fixture['original'])
        returned=frappe.get_doc('Payment Entry',refunds[0].payment_entry)
        credit=frappe.get_doc('Sales Invoice',fixture['credit'])
        assert original.docstatus==1 and original.received_amount==1500 and original.unallocated_amount==0 and original.hs_shift==fixture['shift']
        assert [(row.reference_name,row.allocated_amount) for row in original.references]==[(fixture['invoice'],1500)]
        assert returned.docstatus==1 and returned.payment_type=='Pay' and returned.received_amount==1500 and credit.outstanding_amount==0
        assert expected(frappe.get_doc('HS Shift',fixture['shift']))=={'NIO':'0.00'}
        event=frappe.get_doc('HS Audit Event',{'source_doctype':'HS Payment','source_name':refunds[0].name,'action':'Refund'})
        assert frappe.parse_json(event.details)['refund']['mode']=='Applied Advance'
        proof=dict(site=SITE,synthetic=True,fixture_origin='application API / native ERPNext controllers',refund_from_page=True,
                   original=original.name,invoice=fixture['invoice'],credit=credit.name,refund=returned.name,refund_actor=event.actor,
                   original_amount='1500.00',refund_amount='1500.00',currency='NIO',credit_outstanding='0.00',shift_expected='0.00',original_allocation_preserved=True)
        (ROOT/'docs/evidence/refund-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
