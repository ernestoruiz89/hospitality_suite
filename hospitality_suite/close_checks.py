"""Capture actionable pending work for an explicit operational window."""
import frappe
from frappe.utils import get_datetime,now_datetime

from hospitality_suite.service import current_all
from hospitality_suite.time import business_window,local


def period_labels(prop):
    window=business_window(prop)
    return dict(version=1,business_date=str(prop.business_date),date_label=frappe.utils.getdate(prop.business_date).strftime('%d/%m/%Y'),
        starts_at=local(window['starts_at'],prop).strftime('%d/%m/%Y %H:%M'),ends_at=local(window['ends_at'],prop).strftime('%d/%m/%Y %H:%M'),
        close_time=window['close_time'],time_zone=window['time_zone'])


def blockers(prop):
    from hospitality_suite.reconciliation import differences
    from hospitality_suite.pricing import currency_precision
    from hospitality_suite.printing import hs_label
    end=business_window(prop)['ends_at'];clock=now_datetime();result=[]
    scope={'property':prop.name,'company':prop.company}
    def stamp(value):return local(value,prop).strftime('%d/%m/%Y %H:%M')
    def room(name):return frappe.db.get_value('HS Room',name,'room_number') or frappe._('Sin asignar')
    def amount(value,currency):return frappe.utils.fmt_money(value,precision=currency_precision(currency))+' '+currency
    def add(label,rows,hint,page):
        if rows:result.append(dict(type=label,documents=[row['name'] for row in rows],items=rows,hint=hint,page=page))
    stays=current_all('HS Stay',filters={**scope,'status':'Active','ends_at':['<',end]},fields=['name','room','ends_at'],order_by='ends_at asc,name asc')
    for overdue,title in ((True,'Estancias vencidas'),(False,'Salidas pendientes')):
        add(title,[dict(name=row.name,stay=row.name,label=frappe._('Habitación {0}').format(room(row.room)),detail=frappe._('Salida prevista: {0}').format(stamp(row.ends_at))) for row in stays if (get_datetime(row.ends_at)<clock)==overdue],
            frappe._('Revise la cuenta y registre la salida o una extensión autorizada.'),'hospitality-stays')
    allocations=current_all('HS Allocation',filters={**scope,'kind':'Reservation','status':'Active','starts_at':['<',end]},fields=['booking','room'])
    pending={}
    for row in allocations:pending.setdefault(row.booking,[]).append(row.room)
    bookings=current_all('HS Booking',filters={**scope,'status':['in',['Confirmed','Checked In']],'starts_at':['<',end]},fields=['name','status','starts_at'],order_by='starts_at asc,name asc')
    arrivals=[]
    for row in bookings:
        if row.status=='Checked In' and row.name not in pending:continue
        rooms=', '.join(room(value) for value in pending.get(row.name,[]))
        arrivals.append(dict(name=row.name,label=frappe._('Habitaciones: {0}').format(rooms) if rooms else frappe._('Reserva por asignar'),
            detail=frappe._('Entrada prevista: {0} · habitaciones pendientes: {1}').format(stamp(row.starts_at),len(pending.get(row.name,[])) or 1)))
    add('Llegadas pendientes',arrivals,frappe._('Registre las entradas restantes o revise la reserva, cancelación o no presentación.'),'hospitality-reservations')
    shifts=current_all('HS Shift',filters={**scope,'status':['in',['Open','Review']]},fields=['name','cashier','opened_at','status'],order_by='opened_at asc,name asc')
    add('Turnos sin cerrar',[dict(name=row.name,label=frappe._('Caja de {0}').format(frappe.db.get_value('User',row.cashier,'full_name') or frappe._('Usuario de caja')),
        detail=hs_label(row.status)+' · '+stamp(row.opened_at)) for row in shifts],frappe._('Realice el arqueo y resuelva las diferencias del turno antes de cerrar el día.'),'hospitality-cashier')
    for status,date_field,label,hint in (
        ('Pending','business_date','Cargos sin facturar',frappe._('Revise y facture las cuentas; no es necesario registrar un cobro para facturar.')),
        ('Scheduled','service_date','Cargos nocturnos sin generar',frappe._('Actualice la preparación del cierre y revise los cargos programados de esa fecha.'))):
        charges=current_all('HS Charge',filters={**scope,'status':status,date_field:['<=',prop.business_date]},fields=['name','stay','item','amount','currency','description'],order_by='creation asc,name asc')
        add(label,[dict(name=row.name,stay=row.stay,label=frappe._('Habitación {0}').format(room(frappe.db.get_value('HS Stay',row.stay,'room'))) if row.stay else frappe._('Cuenta por revisar'),
            detail=(frappe.db.get_value('Item',row.item,'item_name') or row.description or frappe._('Cargo'))+' · '+amount(row.amount,row.currency)) for row in charges],hint,'hospitality-stays')
    mismatches=differences(prop)
    add('Diferencias entre PMS y ERPNext',[dict(name=row['source'],label=hs_label(row['type']),
        detail=frappe._('Esperado: {0} · registrado: {1} · diferencia: {2}').format(amount(row['expected'],row['currency']),amount(row['actual'],row['currency']),amount(row['difference'],row['currency']))) for row in mismatches],
        frappe._('Abra Conciliación y corrija el documento de origen mediante su flujo autorizado.'),'hospitality-management')
    return result
