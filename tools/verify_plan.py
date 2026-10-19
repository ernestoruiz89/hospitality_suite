"""Native read-only checkpoints of UX-PLAN-001 configured through Pages."""
import argparse
import json
import os
from pathlib import Path

import frappe

parser=argparse.ArgumentParser()
parser.add_argument("stage",choices=("configured","stay","delivered","conflict","moved","extended"))
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user("Administrator")
    rate=frappe.get_doc("HS Rate",{"title":"Plan con agua UX-PLAN-001"})
    included=[dict(item=row.item,quantity=row.quantity,basis=row.basis) for row in rate.included_services]
    assert rate.amount==1600 and rate.priority==30 and rate.active
    assert str(rate.valid_from)==str(rate.valid_to)=="2026-10-19"
    assert len(included)==1 and included[0]["item"]=="HS-DEMO-WATER" and included[0]["quantity"]==1 and included[0]["basis"]=="Stay"
    result=dict(synthetic=True,rate=rate.name,amount=rate.amount,priority=rate.priority,valid_from=str(rate.valid_from),valid_to=str(rate.valid_to),included=included)
    if args.stage!="configured":
        bookings=frappe.get_all("HS Booking",filters={"instructions":"Estancia sintética UX-PLAN-001 para plan incluido y conflicto"},pluck="name")
        assert len(bookings)==1
        stay=frappe.get_doc("HS Stay",{"booking":bookings[0]})
        accepted=frappe.parse_json(stay.quote_snapshot)
        assert accepted["rules"]["name"]==rate.name and stay.amount==(3100 if args.stage=="extended" else 1600)
        assert frappe.parse_json(stay.service_entitlements)
        result.update(booking=bookings[0],stay=stay.name,room=frappe.db.get_value("HS Room",stay.room,"room_number"),accepted_amount=stay.amount,entitlements=frappe.parse_json(stay.service_entitlements))
        if args.stage in ("delivered","conflict","moved","extended"):
            assert frappe.db.count("HS Service Request",{"stay":stay.name,"included":1})==1
            service=frappe.get_doc("HS Service Request",{"stay":stay.name,"included":1})
            assert service.status=="Delivered" and service.quantity==1 and service.amount==0 and not service.charge
            stock=frappe.get_doc("Stock Entry",service.stock_entry)
            assert stock.docstatus==1 and len(stock.items)==1 and stock.items[0].qty==1
            charges=frappe.get_all("HS Charge",filters={"stay":stay.name},fields=["name","kind","amount"])
            assert len(charges)==(2 if args.stage=="extended" else 1) and all(c.kind=="Lodging" for c in charges)
            result.update(service=service.name,charge=service.charge,service_amount=service.amount,stock_entry=stock.name,charges=len(charges),charge_amounts=[c.amount for c in charges])
        if args.stage in ("conflict","moved","extended"):
            future=frappe.get_doc("HS Booking",{"instructions":"Reserva posterior UX-PLAN-001 protege extensión"})
            assert future.status=="Confirmed" and future.amount==1500 and len(future.rooms)==1
            assert frappe.db.get_value("HS Room",future.rooms[0].room,"room_number")=="H104"
            assert str(future.starts_at)=="2026-10-20 10:00:00"
            assert result["room"]==("H104" if args.stage=="conflict" else "H105")
            assert str(stay.ends_at)==("2026-10-21 09:30:00" if args.stage=="extended" else "2026-10-20 09:30:00")
            result.update(future_booking=future.name,future_status=future.status,future_starts_at=str(future.starts_at),ends_at=str(stay.ends_at))
            if args.stage!="conflict":
                segments=frappe.get_all("HS Allocation",filters={"stay":stay.name},fields=["room","starts_at","ends_at"],order_by="starts_at")
                assert len(segments)==2 and segments[0].ends_at==segments[1].starts_at
                result["segments"]=[dict(room=frappe.db.get_value("HS Room",s.room,"room_number"),starts_at=str(s.starts_at),ends_at=str(s.ends_at)) for s in segments]
                assert frappe.db.get_value("HS Room",segments[0].room,"cleaning_status")=="Dirty"
    Path("/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/plan-"+args.stage+".json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
