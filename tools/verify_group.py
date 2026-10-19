"""Read-only checkpoints of the explicit UX-GRP-001 browser workflow."""
import argparse
import json
import os
from pathlib import Path

import frappe

parser=argparse.ArgumentParser()
parser.add_argument("stage",choices=("reserved","modified","stays","companions","billed","checked-out"))
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user("Administrator")
    names=frappe.get_all("HS Booking",filters={"instructions":"Grupo sintético UX-GRP-001: dos habitaciones por asignar"},pluck="name")
    assert len(names)==1
    booking=frappe.get_doc("HS Booking",names[0])
    assert len(booking.rooms)==2 and [r.people for r in booking.rooms]==[2,1]
    allocations=frappe.get_all("HS Allocation",filters={"booking":booking.name,"kind":"Reservation","status":"Active"},fields=["name","room","starts_at","ends_at"])
    result=dict(synthetic=True,booking=booking.name,status=booking.status,starts_at=str(booking.starts_at),ends_at=str(booking.ends_at),amount=booking.amount,
                people=[r.people for r in booking.rooms],requested_rooms=[r.room for r in booking.rooms],active_reservation_allocations=len(allocations))
    if args.stage in ("reserved","modified"):
        assert not any(r.room for r in booking.rooms) and len(allocations)==2 and not any(r.room for r in allocations)
        assert booking.status=="Confirmed" and booking.amount==(3000 if args.stage=="reserved" else 6000)
        assert str(booking.ends_at)==("2026-10-20 09:00:00" if args.stage=="reserved" else "2026-10-21 09:00:00")
    else:
        stays=frappe.get_all("HS Stay",filters={"booking":booking.name},pluck="name")
        result["stays"]=stays
        assert len(stays)==2
        result["rooms"]=[frappe.db.get_value("HS Room",frappe.db.get_value("HS Stay",name,"room"),"room_number") for name in stays]
        assert set(result["rooms"])=={"H102","H103"} and not allocations
        documents=[frappe.get_doc("HS Stay",name) for name in stays]
        assert all(doc.status==("Checked Out" if args.stage=="checked-out" else "Active") for doc in documents) and sum(doc.amount for doc in documents)==6000
        result["registered_guests"]={room:[row.guest for row in doc.guests] for room,doc in zip(result["rooms"],documents)}
        if args.stage=="companions":
            principal=frappe.db.get_value("HS Guest",{"property":booking.property,"full_name":"Huésped ficticio H1"})
            companion=frappe.db.get_value("HS Guest",{"property":booking.property,"full_name":"Huésped ficticio H3"})
            assert result["registered_guests"]["H102"]==[principal,companion]
        if args.stage in ("billed","checked-out"):
            from hospitality_suite import api
            group=frappe.get_doc("HS Folio",{"booking":booking.name,"label":"Cuenta empresarial del grupo UX-GRP-001"})
            charges=frappe.get_all("HS Charge",filters={"folio":group.name},fields=["name","stay","sales_invoice","invoice_item","amount","status"])
            assert not group.stay and len(charges)==2 and sum(c.amount for c in charges)==6000
            assert {c.stay for c in charges}==set(stays) and all(c.status=="Invoiced" for c in charges)
            invoices={c.sales_invoice for c in charges};assert len(invoices)==1
            company_invoice=frappe.get_doc("Sales Invoice",invoices.pop())
            assert company_invoice.docstatus==1 and company_invoice.grand_total==6000 and company_invoice.outstanding_amount==0
            assert company_invoice.customer==group.customer and frappe.db.get_value("Customer",group.customer,"customer_type")=="Company"
            assert len(company_invoice.items)==2 and company_invoice.update_stock==0
            assert {c.invoice_item for c in charges}=={row.name for row in company_invoice.items}
            service=frappe.get_doc("HS Service Request",{"notes":"Consumo personal UX-GRP-001, separado de la empresa"})
            guest_charge=frappe.get_doc("HS Charge",service.charge)
            guest_invoice=frappe.get_doc("Sales Invoice",guest_charge.sales_invoice)
            assert guest_charge.folio!=group.name and guest_charge.amount==30 and service.status=="Delivered"
            assert guest_invoice.docstatus==1 and guest_invoice.customer==booking.customer and guest_invoice.grand_total==30 and guest_invoice.outstanding_amount==0 and guest_invoice.update_stock==0
            payments=frappe.get_all("HS Payment",filters={"folio":["in",[group.name,guest_charge.folio]],"status":"Posted","kind":"Payment"},fields=["name","shift","amount","payment_entry"])
            assert len(payments)==2 and sorted(p.amount for p in payments)==[30,6000] and len({p.shift for p in payments})==1,payments
            assert all(frappe.db.get_value("Payment Entry",p.payment_entry,"docstatus")==1 for p in payments)
            references={row.reference_name for p in payments for row in frappe.get_doc("Payment Entry",p.payment_entry).references if row.reference_doctype=="Sales Invoice"}
            assert references=={company_invoice.name,guest_invoice.name}
            for stay in stays:
                assert all(float(f.balance["outstanding"])==0 for f in api.stay_detail(stay)["folios"])
            stock=frappe.get_doc("Stock Entry",service.stock_entry)
            assert stock.docstatus==1 and len(stock.items)==1 and stock.items[0].qty==1
            result.update(company_customer=group.customer,company_invoice=company_invoice.name,company_invoice_lines=2,company_amount=6000,
                          personal_invoice=guest_invoice.name,personal_amount=30,payments=[p.name for p in payments],payment_entries=[p.payment_entry for p in payments],
                          shift=payments[0].shift,shared_balances_zero=True,service=service.name,stock_entry=stock.name,stock_quantity=1)
            shift=frappe.get_doc("HS Shift",payments[0].shift)
            assert shift.status=="Closed" and shift.expected_amount==shift.counted_amount==6030 and shift.difference==0
            result.update(shift_status=shift.status,counted=shift.counted_amount,expected=shift.expected_amount,difference=shift.difference)
            if args.stage=="checked-out":
                assert booking.status=="Completed"
                assert not frappe.db.exists("HS Allocation",{"stay":["in",stays],"status":"Active"})
                tasks=frappe.get_all("HS Cleaning Task",filters={"stay":["in",stays]},fields=["name","status","room"])
                assert len(tasks)==2 and all(t.status=="Pending" for t in tasks)
                result["cleaning_tasks"]=[t.name for t in tasks]
    path=Path("/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/group-"+args.stage+".json")
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
