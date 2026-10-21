import frappe


def execute():
    for name in frappe.get_all("HS Booking", pluck="name"):
        booking = frappe.get_doc("HS Booking",name)
        used = set()
        for allocation in frappe.get_all("HS Allocation", filters={"booking":name,"kind":"Reservation"}, fields=["name","booking_room","category","room"], order_by="creation asc"):
            if allocation.booking_room:
                used.add(allocation.booking_room)
                continue
            row = next((r for r in booking.rooms if r.name not in used and r.category==allocation.category and (r.room or "")== (allocation.room or "")),None)
            if not row:
                frappe.throw(frappe._("No se puede reconstruir la línea de la asignación {0}").format(allocation.name))
            frappe.db.set_value("HS Allocation",allocation.name,"booking_room",row.name,update_modified=False)
            used.add(row.name)
