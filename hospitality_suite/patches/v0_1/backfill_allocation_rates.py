import json
import frappe


def execute():
    for name in frappe.get_all("HS Allocation",filters={"kind":["in",["Reservation","Stay"]]},pluck="name"):
        doc=frappe.get_doc("HS Allocation",name)
        if doc.quote_snapshot:
            continue
        snapshot=None
        if doc.stay:
            snapshot=json.loads(frappe.db.get_value("HS Stay",doc.stay,"quote_snapshot") or "{}")
        elif doc.booking and doc.booking_room:
            booking=frappe.get_doc("HS Booking",doc.booking)
            row=next((r for r in booking.rooms if r.name==doc.booking_room),None)
            if row:
                snapshot=json.loads(booking.quote_snapshot)["lines"][row.idx-1]
        if snapshot and snapshot.get("rules"):
            frappe.db.set_value("HS Allocation",name,dict(rate=snapshot["rules"]["name"],currency=snapshot["currency"],
                                                          accepted_amount=snapshot["amount"],quote_snapshot=json.dumps(snapshot,default=str)),update_modified=False)
