"""Read-only quantity queries over the reservation engine's category capacity."""
from decimal import Decimal, InvalidOperation

import frappe

from hospitality_suite.availability import capacity
from hospitality_suite.security import document, require
from hospitality_suite.service import current_all
from hospitality_suite.time import to_site


def positive_integer(value, label):
    try:
        if isinstance(value, bool) or len(str(value)) > 32:
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or not 1 <= number <= 2147483647 or number != number.to_integral_value():
            raise ValueError()
        return int(number)
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(frappe._('{0} debe ser un número entero mayor que cero').format(label))


def search(property_name, starts_at, ends_at, category, people=1, quantity=1):
    prop = require(property_name, 'reserve')
    cat = document('HS Category', category, 'reserve')
    if cat.property != prop.name:
        frappe.throw(frappe._('La categoría no pertenece al establecimiento consultado'), frappe.PermissionError)
    people = positive_integer(people, frappe._('Personas por habitación'))
    quantity = positive_integer(quantity, frappe._('Cantidad de habitaciones'))
    if people > cat.capacity:
        frappe.throw(frappe._('Las personas por habitación superan la capacidad de la categoría'))
    start, end = to_site(starts_at, prop), to_site(ends_at, prop)
    inventory = capacity(prop, cat.name, start, end)
    rooms = current_all('HS Room', filters={'property': prop.name, 'name': ['in', inventory['candidates']]},
        fields=['name', 'room_number', 'cleaning_status']) if inventory['candidates'] else []
    rooms.sort(key=lambda r: (r.room_number.casefold(), r.name))
    return dict(property=prop.name, category=cat.name, category_label=cat.category_name,
        starts_at=str(start), ends_at=str(end), time_zone=prop.time_zone, people=people, quantity=quantity,
        available=inventory['available'], enough=quantity <= inventory['available'],
        physical_available=len(rooms), needs_assignment_review=quantity <= inventory['available'] and quantity > len(rooms),
        rooms=rooms)
