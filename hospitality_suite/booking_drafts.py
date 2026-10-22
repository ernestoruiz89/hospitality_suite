"""Incomplete drafts carry intent, never allocations or accepted prices."""
from datetime import timedelta
import hashlib

import frappe
from frappe.utils import now_datetime

from hospitality_suite import availability, operations
from hospitality_suite.availability_search import positive_integer
from hospitality_suite.security import document
from hospitality_suite.service import assert_version, audit, canonical, current_all, insert
from hospitality_suite.time import local, to_site


def _text(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        frappe.throw(frappe._('Revise los textos y las referencias del borrador'))
    return value


def _number(value):
    if value in (None, ''):
        return None
    return positive_integer(value,frappe._('Cantidad de personas o camas'),allow_zero=True)


def normalize(prop, values):
    if not isinstance(values, dict):
        frappe.throw(frappe._('Revise los datos del borrador'))
    from hospitality_suite.mode import normalize_mode
    mode = normalize_mode(values.get('mode') or ('Por tiempo' if prop.mode == 'Por tiempo' else 'Hotel'))
    if mode not in ('Hotel', 'Por tiempo', 'Day Pass') or (prop.mode != 'Mixed' and ('Por tiempo' if mode=='Day Pass' else mode) != prop.mode):
        frappe.throw(frappe._('El establecimiento no permite esa modalidad'))
    hold = values.get('hold')
    if hold not in (None,False,True,0,1):
        frappe.throw(frappe._('Revise la opción de retención temporal del borrador'))
    result = dict(mode=mode, hold=bool(hold), rooms=[])
    for name in ('guest', 'customer', 'channel', 'instructions', 'travel_agent'):
        result[name] = _text(values.get(name))
    result['channel'] = result['channel'] or 'Recepción'
    if result['guest']:
        guest = document('HS Guest', result['guest'], 'reserve')
        if guest.property != prop.name:
            frappe.throw(frappe._('El huésped no pertenece al establecimiento'), frappe.PermissionError)
    if result['customer']:
        frappe.get_doc('Customer', result['customer']).check_permission('read')
    if result['travel_agent']:
        from hospitality_suite.travel_experiences import agent
        agent(prop,result['travel_agent'])
    result['experiences']=values.get('experiences') or []
    if not isinstance(result['experiences'],list) or len(result['experiences'])>20 or any(not isinstance(row,dict) for row in result['experiences']):
        frappe.throw(frappe._('Revise las experiencias del borrador'))
    result['experiences']=[dict(experience=_text(row.get('experience')),quantity=_number(row.get('quantity'))) for row in result['experiences']]
    for name in ('starts_at', 'ends_at'):
        value = _text(values.get(name))
        result[name] = local(to_site(value, prop), prop).isoformat() if value else None
    rows = values.get('rooms') or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        frappe.throw(frappe._('Revise las habitaciones del borrador'))
    for row in rows:
        target = {}
        for name, dt in (('category', 'HS Category'), ('room', 'HS Room'), ('rate', 'HS Rate')):
            target[name] = _text(row.get(name))
            if target[name] and document(dt, target[name], 'reserve').property != prop.name:
                frappe.throw(frappe._('Una referencia de habitación o tarifa pertenece a otro establecimiento'), frappe.PermissionError)
        target['people'], target['extra_beds'] = _number(row.get('people')), _number(row.get('extra_beds'))
        result['rooms'].append(target)
    return result


def values_for(doc, prop):
    metadata = {}
    if doc.get('draft_data'):
        metadata = frappe.parse_json(doc.draft_data)
        if not isinstance(metadata, dict):
            frappe.throw(frappe._('El borrador guardado necesita revisión'))
    elif doc.quote_snapshot:
        previous = frappe.parse_json(doc.quote_snapshot)
        lines = previous.get('lines',[]) if isinstance(previous,dict) else []
        if lines:
            metadata['mode'] = lines[0].get('stay_type') or lines[0].get('rules',{}).get('mode')
    from hospitality_suite.mode import normalize_mode
    return dict(mode=normalize_mode(metadata.get('mode') or ('Por tiempo' if prop.mode == 'Por tiempo' else 'Hotel')),
        hold=bool(metadata.get('hold')), guest=doc.guest, customer=doc.customer,
        starts_at=local(doc.starts_at, prop).isoformat() if doc.starts_at else None,
        ends_at=local(doc.ends_at, prop).isoformat() if doc.ends_at else None,
        channel=doc.channel, instructions=doc.instructions, travel_agent=doc.travel_agent,
        experiences=metadata.get('experiences',[]),
        rooms=metadata.get('rooms', [dict(category=r.category, room=r.room, people=r.people, extra_beds=r.extra_beds, rate=r.rate) for r in doc.rooms]))


def _storage(values):
    # Contact references, dates and notes already have native fields; do not
    # duplicate them inside an opaque payload or an audit event.
    return canonical({key:values.get(key) for key in ('mode','hold','rooms','experiences')})


def _changes(before, after):
    return dict(fields_changed=[key for key in after if not before or before.get(key)!=after.get(key)])


def _draft(prop, data):
    doc = document('HS Booking', data['booking'], 'reserve')
    if doc.property != prop.name:
        frappe.throw(frappe._('El borrador no pertenece al establecimiento'), frappe.PermissionError)
    if doc.status != 'Draft':
        frappe.throw(frappe._('Este registro ya no es un borrador; revise su estado actual'))
    assert_version(doc, data.get('modified'))
    if current_all('HS Allocation', filters={'booking':doc.name, 'status':'Active'}):
        frappe.throw(frappe._('El borrador conserva asignaciones y requiere una revisión antes de editarlo'))
    return doc


def _projection(prop, values):
    return dict(customer=values['customer'], guest=values['guest'],
        starts_at=to_site(values['starts_at'], prop) if values['starts_at'] else None,
        ends_at=to_site(values['ends_at'], prop) if values['ends_at'] else None,
        channel=values['channel'], instructions=values['instructions'],travel_agent=values['travel_agent'],currency=prop.currency)


def save(prop, data):
    doc = _draft(prop, data) if data.get('booking') else None
    values = normalize(prop, data.get('values', {}))
    before = values_for(doc, prop) if doc else None
    projection = dict(**_projection(prop, values), status='Draft', amount=0,
        quote_snapshot=None, draft_data=_storage(values), hold_until=None, rooms=[])
    if doc:
        doc.update(projection)
        doc.save()
    else:
        doc = insert('HS Booking', prop, **projection)
    audit(prop, 'Save booking draft', doc, details=_changes(before, values))
    return dict(booking=doc.name, status=doc.status, modified=str(doc.modified))


def _review(prop, data):
    doc = _draft(prop, data)
    values = normalize(prop, data.get('values') if 'values' in data else values_for(doc, prop))
    if not values['customer'] or not values['starts_at'] or not values['ends_at'] or not values['rooms']:
        frappe.throw(frappe._('Complete pagador, entrada, salida y habitaciones antes de confirmar el borrador'))
    for index, row in enumerate(values['rooms'], 1):
        if not row['category']:
            frappe.throw(frappe._('Indique la categoría de la habitación solicitada {0}').format(index))
        positive_integer(row['people'], frappe._('Personas por habitación'))
    calculation = operations.quote_request(prop, values)
    accepted = hashlib.sha256(canonical(dict(booking=doc.name, modified=str(doc.modified),
        values=values, quote=calculation['acceptance'])).encode()).hexdigest()
    return doc, values, calculation, accepted


def preview(prop, data):
    doc, values, calculation, accepted = _review(prop, data)
    return dict(**calculation, draft=doc.name, draft_modified=str(doc.modified), draft_acceptance=accepted)


def confirm(prop, data):
    availability.expire_locked(prop)
    doc, values, calculation, accepted = _review(prop, data)
    if data.get('draft_acceptance') != accepted:
        frappe.throw(frappe._('Revise y acepte la cotización vigente del borrador antes de confirmar'))
    before = values_for(doc, prop)
    status = 'Hold' if values['hold'] else 'Confirmed'
    from hospitality_suite.travel_experiences import attribution,book_experiences
    commission=attribution(prop,values['travel_agent'],calculation['amount'])
    doc.update({**_projection(prop, values), **commission, 'status':status, 'amount':calculation['amount'],
        'draft_data':None,'quote_snapshot':canonical(calculation),
        'hold_until':now_datetime()+timedelta(minutes=prop.hold_minutes or 15) if status == 'Hold' else None})
    doc.set('rooms', [dict(category=row['category'], room=row['room'], people=row['people'], extra_beds=row['extra_beds'] or 0,
        rate=line['rules']['name']) for row, line in zip(values['rooms'], calculation['lines'])])
    doc.save()
    operations.allocate_booking(prop, doc, calculation)
    book_experiences(prop,doc,calculation['experiences'])
    audit(prop, 'Confirm booking draft', doc, details=dict(**_changes(before,values), quote=calculation, status=status))
    return dict(booking=doc.name, status=doc.status, modified=str(doc.modified))


def discard(prop, data):
    doc = _draft(prop, data)
    reason = _text(data.get('reason'))
    if not reason or not reason.strip():
        frappe.throw(frappe._('Indique el motivo para descartar el borrador'))
    doc.draft_data = _storage(values_for(doc, prop))
    doc.status, doc.reason = 'Cancelled', reason
    doc.save()
    audit(prop, 'Discard booking draft', doc, doc.reason)
    return dict(booking=doc.name, status=doc.status, modified=str(doc.modified))
