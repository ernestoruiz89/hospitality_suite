"""Read-only labels for an authorized booking; no price or capacity changes."""
import frappe

from hospitality_suite.display_labels import MODE_LABELS


def summary(booking, prop):
    from hospitality_suite.security import document

    def label(dt, name, field):
        filters = {'name': name, 'property': prop.name} if dt.startswith('HS ') else {'name': name}
        return frappe.db.get_value(dt, filters, field) if name else None

    def guest(name):
        return (frappe._('Huésped registrado') if prop.discreet_mode and name else
                label('HS Guest', name, 'full_name')) or frappe._('Por registrar')

    try:
        snapshot = frappe.parse_json(booking.quote_snapshot or '{}')
    except (ValueError, TypeError):
        snapshot = {}
    lines = snapshot.get('lines', []) if isinstance(snapshot, dict) else []
    modes = list(dict.fromkeys(line.get('stay_type') or ('Day Pass' if line['rules'].get('day_pass') else line['rules'].get('mode')) for line in (lines or [])
                              if isinstance(line, dict) and isinstance(line.get('rules'), dict)))
    modes = [MODE_LABELS[mode] for mode in modes if mode in MODE_LABELS]
    allocations = frappe.get_all('HS Allocation', filters={'property': prop.name, 'booking': booking.name},
                                 fields=['booking_room', 'stay'])
    rooms = []
    for row in booking.rooms:
        stays = []
        for name in dict.fromkeys(a.stay for a in allocations if a.booking_room == row.name and a.stay):
            try:
                stay = document('HS Stay', name)
            except frappe.PermissionError:
                continue
            if stay.property != prop.name or stay.booking != booking.name:
                continue
            stays.append(dict(name=stay.name, status=stay.status, guest_label=guest(stay.guest),
                              room_label=label('HS Room', stay.room, 'room_number') or frappe._('Por asignar')))
        rooms.append(dict(number=row.idx, category_label=label('HS Category', row.category, 'category_name') or frappe._('Categoría por definir'),
                          room_label=label('HS Room', row.room, 'room_number') or frappe._('Por asignar'),
                          people=row.people, extra_beds=row.extra_beds, stays=stays))
    return dict(guest_label=guest(booking.guest), customer_label=label('Customer', booking.customer, 'customer_name') or frappe._('Por definir'),
                mode_label=' / '.join(modes) or frappe._('Por definir'), rooms=rooms)
