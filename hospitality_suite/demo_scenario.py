"""Opt-in fictional operations, independent of installation and the empty test seed.

Run explicitly with bench execute hospitality_suite.demo_scenario.build on a
development site with allow_tests and hospitality_allow_demo. Never posts money,
sends messages or activates external providers. Stock uses native ERPNext.
"""
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.schema import ROLES
from hospitality_suite.service import command
from hospitality_suite.time import local

VERSION=1
OPERATION='demo_scenario_v1'
KEY='hospitality-fictional-scenario-v1'
PROPERTIES=(('Hotel Jardín Demo','Hotel','H'),('Motel Luna Demo','Motel','M'))


def authorize():
    if frappe.session.user!='Administrator':
        frappe.throw(frappe._('La demostración operativa requiere Administrator'),frappe.PermissionError)
    if not frappe.conf.get('allow_tests') or not frappe.conf.get('hospitality_allow_demo') or not frappe.local.site.endswith('.localhost'):
        frappe.throw(frappe._('Active allow_tests y hospitality_allow_demo en un sitio local de demostración'),frappe.PermissionError)


def operation_counts(prop):
    return any(frappe.db.count(dt,{'property':prop.name}) for dt in ('HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','HS Service Request'))


def validate_base(prop,mode,prefix):
    if prop.company!='Alojamiento Demostración' or prop.mode!=mode:
        frappe.throw(frappe._('La demostración requiere sus establecimientos ficticios originales'))
    rooms=frappe.get_all('HS Room',filters={'property':prop.name,'company':prop.company},fields=['name','room_number','category'],order_by='room_number')
    if len(rooms)<10 or any(not any(room.room_number==prefix+str(number) for room in rooms) for number in range(101,111)):
        frappe.throw(frappe._('Prepare primero las diez habitaciones ficticias de cada establecimiento'))
    for role in ROLES:
        email=role.lower().replace('hs ','').replace(' ','-')+'@hospitality.example.invalid'
        if role not in frappe.get_roles(email) or not frappe.db.exists('HS Access',{'property':prop.name,'user':email}):
            frappe.throw(frappe._('Prepare primero los usuarios ficticios por rol'))
    return rooms


def make_property(prop,rooms,prefix):
    start=now_datetime().replace(microsecond=0)
    duration=timedelta(days=1) if prop.mode=='Hotel' else timedelta(hours=3)
    guest=frappe.get_doc('HS Guest',{'property':prop.name,'full_name':'Huésped ficticio '+prefix+'1'})
    def booking_values(room,at):
        return dict(mode=prop.mode,guest=guest.name,customer=guest.customer,
                    starts_at=local(at,prop).isoformat(),ends_at=local(at+duration,prop).isoformat(),
                    channel='Demostración ficticia',instructions='Escenario reproducible; no corresponde a huéspedes reales.',
                    rooms=[dict(room=room.name,category=room.category,people=1)])
    def call(action,values):return api.execute(prop.name,action,KEY+':'+action,values)
    future=next(room for room in rooms if room.room_number==prefix+'106')
    current=next(room for room in rooms if room.room_number==prefix+'107')
    values=booking_values(future,start+timedelta(days=7));values['acceptance']=api.preview(prop.name,values)['acceptance']
    reserved=call('reserve',values)
    values=booking_values(current,start);values['acceptance']=api.preview(prop.name,values)['acceptance']
    entered=call('walk_in',values)
    service=call('request_service',dict(stay=entered['stay'],folio=entered['folio'],item='HS-DEMO-WATER',quantity=1,notes='Consumo ficticio del escenario reproducible'))
    request=frappe.get_doc('HS Service Request',service['service'])
    call('update_service',dict(service=request.name,modified=str(request.modified),status='Delivered'))
    return dict(property=prop.name,property_label=prop.property_name,mode=mode_label(prop.mode),room=current.name,room_label=current.room_number,
                reservation_room=future.name,booking=reserved['booking'],stay=entered['stay'],folio=entered['folio'],service=request.name,
                starts_at=values['starts_at'],ends_at=values['ends_at'],synthetic=True,version=VERSION)


def mode_label(mode):return frappe._('Hotel') if mode=='Hotel' else frappe._('Por tiempo')


def validate_result(prop,result):
    references={'HS Booking':'booking','HS Stay':'stay','HS Folio':'folio','HS Service Request':'service','HS Room':'room'}
    for dt,key in references.items():
        if not frappe.db.exists(dt,{'name':result.get(key),'property':prop.name,'company':prop.company}):
            frappe.throw(frappe._('El escenario guardado perdió una referencia. Restaure su respaldo de demostración; no se duplicarán operaciones.'))
    if frappe.db.get_value('HS Service Request',result['service'],'stay')!=result['stay'] or frappe.db.get_value('HS Folio',result['folio'],'stay')!=result['stay']:
        frappe.throw(frappe._('Las referencias del escenario guardado no corresponden a la estancia'))
    return {**result,'current':dict(reservation=frappe.db.get_value('HS Booking',result['booking'],'status'),
                                  stay=frappe.db.get_value('HS Stay',result['stay'],'status'),
                                  service=frappe.db.get_value('HS Service Request',result['service'],'status'))}


def build():
    """One transaction, repeatable per property; existing demo work is never reset."""
    authorize()
    frappe.db.savepoint('hs_demo_scenario')
    try:
        existing=frappe.get_all('HS Property',pluck='property_name')
        if any(label not in existing for label,_,_ in PROPERTIES):
            frappe.throw(frappe._('Ejecute primero la carga base demo.seed en un sitio local dedicado con los dos establecimientos ficticios'))
        prepared=[]
        for label,mode,prefix in PROPERTIES:
            prop=frappe.get_doc('HS Property',{'property_name':label});rooms=validate_base(prop,mode,prefix)
            if not frappe.db.exists('HS Request',{'property':prop.name,'operation':OPERATION}) and operation_counts(prop):
                frappe.throw(frappe._('El establecimiento ya tiene operaciones ajenas al escenario. Use otro sitio local de demostración.'))
            prepared.append((prop,rooms,prefix))
        result=[]
        for prop,rooms,prefix in prepared:
            saved=command(prop.name,'setup',KEY,dict(operation=OPERATION,version=VERSION),lambda prop:make_property(prop,rooms,prefix))
            result.append(validate_result(prop,saved))
        return dict(version=VERSION,synthetic=True,external_providers_active=False,properties=result)
    except Exception:
        frappe.db.rollback(save_point='hs_demo_scenario')
        raise
