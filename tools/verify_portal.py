"""Read-only proof of the public UX-PORTAL-001 request and Page conversion."""
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
    requests=frappe.get_all('HS Portal Request',filters={'email':'ux-portal-001@example.invalid'},pluck='name')
    assert len(requests)==1
    request=frappe.get_doc('HS Portal Request',requests[0])
    assert request.status=='Converted' and request.amount==1500 and request.owner=='Guest'
    booking=frappe.get_doc('HS Booking',request.booking)
    assert booking.status=='Confirmed' and booking.channel=='Web' and booking.amount==1500
    assert len(booking.rooms)==1 and not booking.rooms[0].room
    assert frappe.db.count('HS Allocation',{'portal_request':request.name,'status':'Active'})==0
    assert frappe.db.count('HS Allocation',{'booking':booking.name,'status':'Active'})==1
    assert frappe.db.count('HS Payment',{'booking':booking.name})==0
    assert frappe.db.count('HS Stay',{'booking':booking.name})==0
    result=dict(synthetic=True,request=request.name,request_owner=request.owner,status=request.status,booking=booking.name,
                booking_status=booking.status,channel=booking.channel,amount=booking.amount,
                starts_at=str(booking.starts_at),ends_at=str(booking.ends_at),rooms=1,
                request_active_allocations=0,booking_active_allocations=1,payments=0,stays=0)
    Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/portal-converted.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
finally:
    frappe.db.rollback()
    frappe.destroy()
