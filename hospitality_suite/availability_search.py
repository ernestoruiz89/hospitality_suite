"""Read-only quantity queries over the reservation engine's category capacity."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import frappe

from hospitality_suite.availability import active_allocations, capacity, overlapping
from hospitality_suite.security import document, require
from hospitality_suite.service import current_all
from hospitality_suite.time import to_site


def positive_integer(value, label, allow_zero=False):
    try:
        if isinstance(value, bool) or len(str(value)) > 32:
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or not (0 if allow_zero else 1) <= number <= 2147483647 or number != number.to_integral_value():
            raise ValueError()
        return int(number)
    except (InvalidOperation, TypeError, ValueError):
        message = frappe._('{0}: introduzca un número entero no negativo') if allow_zero else frappe._('{0}: introduzca un número entero mayor que cero')
        frappe.throw(message.format(label))


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
        rooms=rooms, room_states=interval_states(prop,cat.name,start,end,inventory))


def interval_states(prop,category,start,end,inventory):
    """Explain the same physical conflicts and category quota used by capacity.

    Cleaning is current information, distinct from the requested interval.
    No guest, reservation identity, balance or arbitrary allocation is exposed.
    """
    horizon=end+timedelta(minutes=prop.cleaning_minutes or 0)
    allocations=active_allocations(prop,start,horizon)
    rooms=current_all('HS Room',filters={'property':prop.name,'category':category},
                      fields=['name','room_number','active','cleaning_status'])
    candidates=set(inventory['candidates']);result=[]
    labels={'Available':frappe._('Disponible en el intervalo'),'Reserved':frappe._('Reservada para el intervalo'),
        'Occupied':frappe._('Ocupada en el intervalo'),'Blocked':frappe._('Fuera de servicio en el intervalo'),
        'Buffer':frappe._('Colchón de limpieza'),'Inactive':frappe._('Habitación inactiva'),'Category Full':frappe._('Sin cupo por categoría')}
    for room in sorted(rooms,key=lambda r:(r.room_number.casefold(),r.name)):
        if not room.active:status='Inactive'
        elif room.name in candidates:status='Available' if inventory['available'] else 'Category Full'
        else:
            direct={row.kind for row in allocations if row.room==room.name and overlapping(start,end,row.starts_at,row.ends_at)}
            status=next((label for kind,label in (('Maintenance','Blocked'),('Stay','Occupied'),('Reservation','Reserved')) if kind in direct),'Buffer')
        result.append(dict(name=room.name,room_number=room.room_number,status=status,label=labels[status],cleaning_status=room.cleaning_status))
    return result
