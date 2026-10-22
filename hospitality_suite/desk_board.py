"""Read-only operational queues. Reservation demand is never current occupancy."""
from datetime import date as calendar_date, datetime, time, timedelta
import re
from decimal import Decimal

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.security import require, is_system
from hospitality_suite.schema import OPERATORS
from hospitality_suite.paging import permitted_all, page
from hospitality_suite.time import now_local, to_site


def authorize(property_name):
    prop=require(property_name)
    if not is_system() and not set(frappe.get_roles()).intersection(OPERATORS):
        frappe.throw(frappe._('No tiene permiso para consultar las estancias'),frappe.PermissionError)
    return prop


def pending_arrivals(prop):
    now=now_datetime()
    bookings={r.name:r for r in permitted_all('HS Booking',filters={'property':prop.name,'status':['in',['Confirmed','Hold','Checked In']]},
        fields=['name','guest','customer','starts_at','ends_at','status','hold_until'])
        if r.status!='Hold' or (r.hold_until and get_datetime(r.hold_until)>now)}
    rows=[]
    for allocation in permitted_all('HS Allocation',filters={'property':prop.name,'kind':'Reservation','status':'Active'},
            fields=['name','booking','booking_room','room','category','starts_at','ends_at'],order_by='starts_at asc,name asc'):
        booking=bookings.get(allocation.booking)
        if booking:
            rows.append(dict(allocation=allocation.name,booking=booking.name,room=allocation.room,category=allocation.category,
                             guest=booking.guest,customer=booking.customer,starts_at=allocation.starts_at,ends_at=allocation.ends_at,status=booking.status))
    return rows


def room_arrivals(prop):
    # No guest names or prices: one pending arrival per assigned room.
    result={}
    for row in pending_arrivals(prop):
        if row['room'] and row['room'] not in result:
            result[row['room']]={key:row[key] for key in ('room','booking','starts_at','ends_at','status')}
    return list(result.values())


def board(property_name,date=None,view='hosted',offset=0,page_length=25):
    prop=authorize(property_name)
    if view not in ('hosted','arrivals','departures','accounts'):
        frappe.throw(frappe._('Seleccione una vista de estancias válida'))
    day=str(date or now_local(prop).date())
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError()
        chosen=calendar_date.fromisoformat(day)
        # Local calendar date, explicitly distinct from the operational close date.
        end=to_site(datetime.combine(chosen+timedelta(days=1),time()),prop)
    except (ValueError,TypeError,OverflowError):
        frappe.throw(frappe._('Indique una fecha válida para llegadas y salidas'))
    scope={'property':prop.name}
    stays=permitted_all('HS Stay',filters=scope,fields=['name','room','guest','customer','booking','starts_at','ends_at','status'],order_by='ends_at asc,name asc')
    active=[dict(row) for row in stays if row.status=='Active']
    arrivals=[row for row in pending_arrivals(prop) if get_datetime(row['starts_at'])<end]
    departures=[row for row in active if get_datetime(row['ends_at'])<end]
    folios=permitted_all('HS Folio',filters={**scope,'status':'Open'},fields=['name','label','stay','booking','customer','currency'],order_by='modified desc,name desc')
    queues=dict(hosted=active,arrivals=arrivals,departures=departures,accounts=[dict(row) for row in folios])
    result=page(queues[view],offset,page_length)
    rooms={r.name:r for r in permitted_all('HS Room',filters=scope,fields=['name','room_number','cleaning_status'])}
    categories={r.name:r.category_name for r in permitted_all('HS Category',filters=scope,fields=['name','category_name'])}
    for row in result['rows']:
        physical_room=rooms.get(row.get('room'))
        row['room_label']=physical_room.room_number if physical_room else frappe._('Por asignar')
        row['cleaning_status']=physical_room.cleaning_status if physical_room else None
        if row.get('category'):row['category_label']=categories.get(row['category'],frappe._('Categoría'))
        if row.get('guest'):
            row['guest_label']=frappe._('Huésped registrado') if prop.discreet_mode else frappe.db.get_value('HS Guest',{'name':row['guest'],'property':prop.name},'full_name') or frappe._('Huésped registrado')
        else:row['guest_label']=frappe._('Huésped por registrar')
        if row.get('customer'):
            row['customer_label']=frappe._('Cliente registrado') if prop.discreet_mode else frappe.db.get_value('Customer',row['customer'],'customer_name') or frappe._('Cliente registrado')
        if view=='accounts':
            from hospitality_suite.accounting import folio_balance
            associated=[s for s in stays if s.name==row.get('stay') or (not row.get('stay') and row.get('booking') and s.booking==row['booking'])]
            associated.sort(key=lambda s:(s.status!='Active',s.name))
            row['detail_stay']=associated[0].name if associated else None
            row['room_label']=', '.join(sorted({rooms[s.room].room_number if s.room in rooms else frappe._('Habitación') for s in associated})) or frappe._('Grupo sin entrada')
            row['shared']=not bool(row.get('stay'))
            row['balance']=folio_balance(row['name'])
        else:
            from hospitality_suite.accounting import folio_balance
            related=[f for f in folios if (f.stay and f.stay==row.get('name')) or
                     (not f.stay and f.booking and f.booking==row.get('booking'))]
            by_currency={}
            for folio in related:
                balance=folio_balance(folio.name)
                currency=balance['currency']
                by_currency[currency]=by_currency.get(currency,Decimal(0))+Decimal(balance['outstanding'])
            row['account_balances']=[dict(currency=currency,outstanding=str(amount)) for currency,amount in sorted(by_currency.items())]
            row['shared_account']=any(not folio.stay for folio in related)
    result.update(property=prop.name,date=day,view=view,counts={key:len(rows) for key,rows in queues.items()},server_time=str(now_datetime()))
    return result
