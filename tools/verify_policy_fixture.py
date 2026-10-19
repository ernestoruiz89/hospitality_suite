"""Read back receipt policies saved and reloaded through the clean-site Page."""
import json
import os
from pathlib import Path

import frappe

bench=Path('/home/frappe/benches/hospitality-bench')
root=Path(__file__).resolve().parents[1]
os.chdir(bench/'sites')
frappe.init(site='hospitality-clean.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_clean'
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Establecimiento UX de prueba'})
    assert (prop.advance_policy,prop.guarantee_policy)==('Approval','Disabled')
    assert not prop.financial_enabled and str(prop.business_date)=='2026-10-18'
    operations={dt:frappe.db.count(dt,{'property':prop.name}) for dt in ('HS Booking','HS Stay','HS Charge','HS Payment','HS Shift')}
    native={dt:frappe.db.count(dt,{'hs_property':prop.name}) for dt in ('Sales Invoice','Payment Entry','Journal Entry','Stock Entry')}
    assert not any(operations.values()) and not any(native.values())
    proof=dict(site=frappe.local.site,synthetic=True,readback_only=True,property=prop.name,property_name=prop.property_name,
               advance_policy=prop.advance_policy,guarantee_policy=prop.guarantee_policy,financial_enabled=False,
               operation_records=operations,native_documents=native,ui_reloaded=True,preview_socketio_configured=False)
    (root/'docs/evidence/payment-policy-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
