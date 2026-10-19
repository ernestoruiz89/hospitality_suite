"""Read back the explicitly created UI fixture; never create or change records."""
import json
import os
from pathlib import Path

import frappe

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
os.chdir(BENCH/'sites')
frappe.init(site='hospitality-clean.localhost',sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_clean'
    frappe.set_user('Administrator')
    from hospitality_suite.time import cutoff_time
    label='Establecimiento UX de prueba'
    assert frappe.db.count('HS Property',{'property_name':label})==1
    prop=frappe.get_doc('HS Property',{'property_name':label})
    assert str(prop.business_date)=='2026-10-18' and cutoff_time(prop.close_time).isoformat()=='05:30:00'
    assert prop.mode=='Mixed' and prop.time_zone=='America/Managua' and prop.currency=='NIO'
    assert not prop.financial_enabled and not prop.receivable_account and not prop.tax_template
    operations={dt:frappe.db.count(dt,{'property':prop.name}) for dt in ('HS Booking','HS Stay','HS Charge','HS Payment','HS Shift')}
    native={dt:frappe.db.count(dt,{'hs_property':prop.name}) for dt in ('Sales Invoice','Payment Entry','Journal Entry','Stock Entry')}
    assert not any(operations.values()) and not any(native.values())
    assert frappe.db.count('HS Request',{'property':prop.name,'operation':'create_property'})==1
    event=frappe.get_doc('HS Audit Event',{'property':prop.name,'action':'Create property'})
    assert event.actor=='Administrator'
    details=frappe.parse_json(event.details)
    assert details['business_date']=='2026-10-18' and details['close_time']=='05:30:00'
    proof=dict(site=frappe.local.site,synthetic=True,readback_only=True,property=prop.name,property_name=label,
               business_date=str(prop.business_date),close_time=cutoff_time(prop.close_time).isoformat(),time_zone=prop.time_zone,
               mode=prop.mode,currency=prop.currency,financial_enabled=bool(prop.financial_enabled),
               operation_records=operations,native_documents=native,completed_creation_requests=1,audit_actor=event.actor,
               ui_reloaded=True,preview_socketio_configured=False)
    (ROOT/'docs/evidence/initial-setup-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
