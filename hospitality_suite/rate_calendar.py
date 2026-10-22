"""Bounded, read-only date-by-date quotes from the operational pricing engine."""
from datetime import date, datetime, time, timedelta
import re

import frappe

from hospitality_suite import availability, pricing
from hospitality_suite.availability_search import positive_integer
from hospitality_suite.security import document, require, selected_property
from hospitality_suite.time import to_site


def view(property_name, category, from_date, days=14, mode=None, people=1, hours=3):
    prop = require(property_name, 'reserve')
    cat = document('HS Category', category, 'reserve')
    if cat.property != prop.name or cat.company != prop.company:
        frappe.throw(frappe._('La categoría no pertenece al establecimiento consultado'), frappe.PermissionError)
    if not isinstance(from_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', from_date):
        frappe.throw(frappe._('Indique una fecha válida para el calendario de tarifas'))
    try:
        start_day = date.fromisoformat(from_date)
    except ValueError:
        frappe.throw(frappe._('Indique una fecha válida para el calendario de tarifas'))
    days = positive_integer(days, frappe._('Días'))
    people = positive_integer(people, frappe._('Personas por habitación'))
    hours = positive_integer(hours, frappe._('Horas del bloque'))
    if days > 31 or hours > 24 or people > cat.capacity:
        frappe.throw(frappe._('Revise días, horas y capacidad de personas'))
    try:
        start_day + timedelta(days=days)
    except OverflowError:
        frappe.throw(frappe._('El período del calendario queda fuera de las fechas admitidas'))
    from hospitality_suite.mode import normalize_mode
    selected_mode = normalize_mode(mode or (prop.mode if prop.mode != 'Mixed' else 'Hotel'))
    if selected_mode not in ('Hotel', 'Por tiempo', 'Day Pass') or (prop.mode != 'Mixed' and ('Por tiempo' if selected_mode=='Day Pass' else selected_mode) != prop.mode):
        frappe.throw(frappe._('El establecimiento no permite esa modalidad'))
    if selected_mode=='Day Pass' and hours>15:
        frappe.throw(frappe._('El calendario Day Pass admite hasta 15 horas desde las 08:00'))

    rows = []
    with selected_property(prop):
        for index in range(days):
            day = start_day + timedelta(days=index)
            starts_local = datetime.combine(day, time(8 if selected_mode=='Day Pass' else 14))
            ends_local = (datetime.combine(day + timedelta(days=1), time(11)) if selected_mode == 'Hotel'
                          else starts_local + timedelta(hours=hours))
            start, end = to_site(starts_local, prop), to_site(ends_local, prop)
            available = availability.capacity(prop, cat.name, start, end)['available']
            row = dict(date=str(day), available=available, starts_at=starts_local.isoformat(),
                       ends_at=ends_local.isoformat(), rate_status='ok', amount=None, currency=prop.currency,
                       rate=None, rate_title=None)
            try:
                result = pricing.quote(prop, cat.name, start, end, people, mode=selected_mode)
            except frappe.ValidationError as error:
                no_rate = frappe._('No existe una tarifa aplicable a la fecha y al pagador')
                collision = frappe._('Hay tarifas con la misma prioridad; defina una prioridad inequívoca')
                row['rate_status'] = 'no_rate' if no_rate in str(error) else 'collision' if collision in str(error) else 'review_rate'
            else:
                if result['currency'] != prop.currency:
                    row['rate_status'] = 'wrong_currency'
                else:
                    row.update(amount=result['amount'], currency=result['currency'],
                               rate=result['rules']['name'], rate_title=result['rules']['title'])
            rows.append(row)
    return dict(property=prop.name, category=cat.name, category_label=cat.category_name, mode=selected_mode,
                from_date=str(start_day), days=days, people=people, hours=hours if selected_mode in ('Por tiempo','Day Pass') else None,
                time_zone=prop.time_zone, rows=rows, read_only=True)
