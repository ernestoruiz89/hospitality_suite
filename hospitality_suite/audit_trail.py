"""Small, explicit historical projections; arbitrary payloads and identity data stay out."""
import hashlib

import frappe

from hospitality_suite.security import require,property_document

FIELDS={
    'HS Rate':('title','category','mode','currency','amount','block_hours','extra_hour_rate','grace_minutes','rounding_minutes','included_people','additional_person_rate','extra_bed_rate','priority','valid_from','valid_to','weekdays','night_start','night_end','active','customer'),
    'HS Booking':('status','starts_at','ends_at','amount','currency','fee_amount','fee_invoice','rooms'),
    'HS Room':('room_number','category','floor','zone','beds','parking','active','cleaning_status'),
    'HS Cleaning Task':('room','kind','priority','status','assigned_to','started_at','completed_at','notes'),
    'HS Maintenance Order':('room','title','equipment','starts_at','ends_at','until_reopened','blocks_room','kind','status','assigned_to','notes'),
    'HS Stay':('status','room','starts_at','ends_at','amount','currency','actual_check_out'),
    'HS Charge':('status','quantity','rate','amount','currency','adjustment_type','applies_to_charge','folio'),
    'HS Payment':('kind','status','amount','currency','base_amount','exchange_rate','method','shift','payment_entry','journal_entry','source_payment','fee_amount','withholding_amount','net_amount'),
    'HS Shift':('status','currency','opening_amount','expected_amount','counted_amount','difference','closed_at','approved_by'),
    'HS Daily Close':('business_date','status','closed_at','reason'),
    'Sales Invoice':('docstatus','currency','net_total','total_taxes_and_charges','grand_total','rounded_total','outstanding_amount','is_return','return_against'),
    'Payment Entry':('docstatus','payment_type','paid_from_account_currency','paid_to_account_currency','paid_amount','received_amount','base_paid_amount','base_received_amount'),
    'Journal Entry':('docstatus','voucher_type','total_debit','total_credit'),
}


def values(doc):
    if not doc or doc.doctype not in FIELDS:return None
    result={field:doc.get(field) for field in FIELDS[doc.doctype]}
    if doc.doctype in ('HS Room','HS Booking','HS Stay','HS Cleaning Task','HS Maintenance Order'):
        result.update(property=doc.property,company=doc.company)
    if doc.doctype=='HS Booking':
        result['rooms']=[dict(room=row.room,category=row.category,
            room_number=frappe.db.get_value('HS Room',{'name':row.room,'property':doc.property,'company':doc.company},'room_number') if row.room else None) for row in doc.rooms]
    if doc.doctype=='HS Rate':
        result['included_services']=[{key:row.get(key) for key in ('item','quantity','basis')} for row in doc.included_services]
    if doc.doctype=='HS Shift':
        data=frappe.parse_json(doc.denominations or '{}')
        result['denominations']=data if isinstance(data,dict) else {}
    if doc.doctype=='HS Daily Close':
        summary=frappe.parse_json(doc.summary or '{}')
        result['financial_totals']=(summary.get('financial') or {}).get('currencies',[]) if isinstance(summary,dict) else []
        result['summary_sha256']=hashlib.sha256((doc.summary or '').encode()).hexdigest()
        result['close_snapshot']=summary
        result['close_blockers']=frappe.parse_json(doc.blockers or '[]')
    return result


def enrich(doc,details,before=None):
    result=dict(details or {})
    after=values(doc)
    if after is not None:
        old=before if before is not None else values(doc.get_doc_before_save())
        if old and old.get('property') and after.get('property') and (old.get('property'),old.get('company'))!=(after.get('property'),after.get('company')):
            old=None;result['_scope_boundary']=True
        result['_values']=dict(version=1,doctype=doc.doctype,name=doc.name,before=old,after=after)
    return result


def rate_changed(doc):
    previous=doc.get_doc_before_save();old=values(previous);new=values(doc)
    if old==new:return
    from hospitality_suite.service import operation,audit
    prop=require(doc.property,'setup')
    with operation(prop):
        audit(prop,'Rate changed' if previous else 'Rate created',doc,
              doc.change_reason or frappe._('Registro inicial de tarifa'),before=old)


def room_changed(doc):
    """Keep raw identities and before/after values even when a native Version is skipped."""
    if any(frappe.flags.get(key) for key in ('in_install','in_migrate','in_patch','in_import')):return
    previous=doc.get_doc_before_save()
    if not previous:return
    old,new=values(previous),values(doc)
    if old==new:return
    from hospitality_suite.service import operation,audit
    prop=require(doc.property)
    with operation(prop):audit(prop,'Room changed',doc,frappe._('Cambio de datos de habitación'),before=old)


EXTRAS={'HS Rate':('included_services',),'HS Shift':('denominations',),'HS Daily Close':('financial_totals',)}
CONTEXT_LABELS={'HS Maintenance Order':{'title':'Trabajo requerido','starts_at':'Inicio del trabajo','ends_at':'Fin previsto'}}
LABELS={'rooms':'Habitaciones registradas','room_number':'Número de habitación','floor':'Piso','zone':'Zona','beds':'Camas','parking':'Estacionamiento','cleaning_status':'Estado de limpieza',
    'equipment':'Equipo','until_reopened':'Hasta reapertura autorizada','blocks_room':'Bloquea habitación','assigned_to':'Responsable','started_at':'Inicio registrado','completed_at':'Finalización registrada','notes':'Observaciones',
    'included_services':'Servicios incluidos','denominations':'Arqueo por moneda','financial_totals':'Resumen financiero conservado',
    'title':'Nombre de tarifa','category':'Categoría','mode':'Modalidad','currency':'Moneda','amount':'Importe','block_hours':'Horas del bloque',
    'extra_hour_rate':'Precio de hora adicional','grace_minutes':'Tolerancia (minutos)','rounding_minutes':'Fracción de cobro (minutos)',
    'included_people':'Personas incluidas','additional_person_rate':'Precio de persona adicional','extra_bed_rate':'Precio de cama adicional',
    'priority':'Prioridad','valid_from':'Vigente desde','valid_to':'Vigente hasta','weekdays':'Días de la semana','night_start':'Inicio de paquete nocturno',
    'night_end':'Fin de paquete nocturno','active':'Habilitada','customer':'Pagador de la tarifa','status':'Estado','starts_at':'Entrada prevista','ends_at':'Salida prevista',
    'fee_amount':'Penalización','fee_invoice':'Factura de penalización','room':'Habitación','actual_check_out':'Salida registrada','quantity':'Cantidad','rate':'Precio unitario',
    'adjustment_type':'Tipo de ajuste','applies_to_charge':'Cargo de origen','folio':'Cuenta','kind':'Concepto','base_amount':'Importe en moneda de la compañía',
    'exchange_rate':'Tipo de cambio','method':'Medio de pago','shift':'Turno','payment_entry':'Comprobante de pago','journal_entry':'Asiento contable',
    'source_payment':'Movimiento de origen','fee_amount':'Comisión / penalización','withholding_amount':'Retención','net_amount':'Importe neto','opening_amount':'Fondo inicial',
    'expected_amount':'Efectivo esperado','counted_amount':'Efectivo contado','difference':'Diferencia','closed_at':'Cierre registrado','approved_by':'Aprobado por',
    'business_date':'Fecha operativa','reason':'Motivo documentado','docstatus':'Estado contable','net_total':'Neto sin impuestos','total_taxes_and_charges':'Impuestos','grand_total':'Total',
    'rounded_total':'Total con redondeo','outstanding_amount':'Saldo pendiente','is_return':'Es devolución','return_against':'Factura de origen',
    'payment_type':'Dirección del pago','paid_from_account_currency':'Moneda de cuenta de origen','paid_to_account_currency':'Moneda de cuenta de destino',
    'paid_amount':'Importe desde origen','received_amount':'Importe en destino','base_paid_amount':'Importe desde origen en moneda de la compañía',
    'base_received_amount':'Importe en destino en moneda de la compañía','voucher_type':'Tipo de asiento','total_debit':'Total debe','total_credit':'Total haber'}


def display_value(prop,dt,field,value,df,state,context):
    if value is None or value=='':return frappe._('Sin dato')
    from hospitality_suite.printing import hs_label
    if field=='rooms':
        if not isinstance(value,list):return frappe._('Habitaciones registradas sin desglose recuperable')
        return '; '.join((row.get('room_number') if isinstance(row.get('room_number'),str) else None) or (context.master('HS Room',row.get('room'),'room_number') if isinstance(row.get('room'),str) and row['room'] else frappe._('Por asignar')) for row in value if isinstance(row,dict)) or frappe._('Sin habitaciones asignadas')
    if field=='cleaning_status' and isinstance(value,str):
        from hospitality_suite.display_labels import cleaning_label
        return cleaning_label(value)
    if field=='included_services':
        return '; '.join(f"{context.master('Item',row.get('item'),'item_name')} × {row.get('quantity')} · {frappe._('Por noche') if row.get('basis')=='Night' else frappe._('Por estancia')}" for row in value) or frappe._('Sin servicios incluidos')
    if field=='denominations':
        expected=value.get('expected') or {};counts=value.get('counts') or {};differences=value.get('differences') or {}
        return '; '.join(f"{currency} · {frappe._('Esperado')}: {expected.get(currency,'—')} · {frappe._('Contado')}: {sum(float(r['value'])*int(r['count']) for r in counts.get(currency,[]))} · {frappe._('Diferencia')}: {differences.get(currency,'—')}" for currency in sorted(set(expected)|set(counts))) or frappe._('Sin arqueo registrado')
    if field=='financial_totals':
        return '; '.join(f"{row['currency']} · {frappe._('Facturación')}: {row.get('invoices_total','0')} · {frappe._('Dinero neto recibido')}: {row.get('net_customer_receipts','0')} · {frappe._('Pendiente de cobro')}: {row.get('receivables','0')}" for row in value) or frappe._('Sin movimientos financieros')
    if field=='docstatus':return frappe._({0:'Borrador',1:'Presentado',2:'Anulado'}.get(int(value),str(value)))
    if field=='mode':return frappe._({'Hotel':'Hotel','Motel':'Por tiempo','Mixed':'Hotel y por tiempo'}.get(value,value))
    if df and df.fieldtype=='Check':return frappe._('Sí') if value else frappe._('No')
    if df and df.fieldtype=='Select':return hs_label(value)
    if df and df.fieldtype=='Datetime':
        from hospitality_suite.time import local
        return local(value,prop).strftime('%d/%m/%Y %H:%M:%S')
    if df and df.fieldtype=='Date':return frappe.utils.getdate(value).strftime('%d/%m/%Y')
    if df and df.fieldtype=='Currency':
        from hospitality_suite.pricing import currency_precision
        base=frappe.db.get_value('Company',prop.company,'default_currency')
        currency=(state.get('paid_from_account_currency') if field=='paid_amount' else state.get('paid_to_account_currency')) if dt=='Payment Entry' and field in ('paid_amount','received_amount') else base if field.startswith('base_') or dt=='Journal Entry' else state.get('currency') or prop.currency
        return frappe.utils.fmt_money(value,precision=currency_precision(currency))+' '+currency
    if df and df.fieldtype=='Link':
        if df.options.startswith('HS '):return context.origin(df.options,value)
        if df.options=='Customer':return context.master('Customer',value,'customer_name')
        if df.options=='User':return context.master('User',value,'full_name')
    return str(value)


def detail(prop,name):
    event=property_document(prop,'HS Audit Event',name,'report')
    from hospitality_suite.report_presentation import action_label,Descriptions,TITLES
    from hospitality_suite.time import local
    try:data=frappe.parse_json(event.details or '{}')
    except (ValueError,TypeError):data={}
    stored=data.get('_values') if isinstance(data,dict) else None
    rows=[];context=Descriptions([prop])
    if isinstance(stored,dict) and stored.get('version')==1 and stored.get('doctype') in FIELDS:
        dt=stored['doctype'];allowed=(*FIELDS[dt],*EXTRAS.get(dt,()))
        before=stored.get('before') or {};after=stored.get('after') or {}
        if isinstance(before,dict) and isinstance(after,dict):
            meta=frappe.get_meta(dt)
            for field in allowed:
                if field not in before and field not in after:continue
                df=meta.get_field(field)
                rows.append(dict(field=field,label=frappe._(CONTEXT_LABELS.get(dt,{}).get(field) or LABELS.get(field) or (df.label if df else field)),
                    before=display_value(prop,dt,field,before.get(field),df,before,context),after=display_value(prop,dt,field,after.get(field),df,after,context),
                    changed=before.get(field)!=after.get(field),fieldtype=df.fieldtype if df else 'Data'))
    recorded_title=(stored.get('after') or {}).get('title') if rows and stored.get('doctype')=='HS Rate' else None
    values_document=None
    if rows:
        dt=stored['doctype'];reference=stored.get('name') or event.source_name
        caption=recorded_title or context.origin(dt,reference) if dt.startswith('HS ') else reference
        values_document=frappe._(TITLES.get(dt,dt))+' · '+str(caption or '')
    return dict(name=event.name,action=action_label(event.action),actor=frappe.db.get_value('User',event.actor,'full_name') or event.actor,
        occurred_at=local(event.occurred_at,prop).strftime('%d/%m/%Y %H:%M:%S'),business_date=str(event.business_date),
        document_type=frappe._(TITLES.get(event.source_doctype,event.source_doctype)),document=recorded_title or context.origin(event.source_doctype,event.source_name),
        reason=event.reason,values=rows,historical_values_available=bool(rows),
        values_document=values_document,
        close_snapshot=(stored.get('after') or {}).get('close_snapshot') if rows and stored['doctype']=='HS Daily Close' else None,
        close_blockers=(stored.get('after') or {}).get('close_blockers') if rows and stored['doctype']=='HS Daily Close' else None)


def review(prop):
    """Freeze exceptional events by their recorded operational date, never live totals."""
    from hospitality_suite.paging import permitted_all
    from hospitality_suite.report_presentation import action_label,Descriptions
    from hospitality_suite.time import local
    context=Descriptions([prop]);rows=[]
    for event in permitted_all('HS Audit Event',filters={'property':prop.name,'company':prop.company,'business_date':prop.business_date},
            fields=['name','action','actor','occurred_at','source_doctype','source_name','reason'],order_by='occurred_at asc,name asc'):
        action=event.action
        category=('Cancelaciones y no presentaciones' if action in ('Cancelled','No Show') else
            'Descuentos y cortesías' if action in ('Adjustment Discount','Adjustment Courtesy') else
            'Devoluciones' if action in ('Refund','Guarantee Refund','Credit note','Return direct sale') else
            'Anulaciones de documentos' if action=='on_cancel' else
            'Cambios manuales' if action in ('Rate changed','Rate created','Modify reservation','Change room','Move charge','Extend','Adjustment Surcharge','Service Cancelled','on_update_after_submit') or action.startswith('Setup ') else None)
        if category:
            rows.append(dict(name=event.name,category=frappe._(category),action=action_label(action),actor=frappe.db.get_value('User',event.actor,'full_name') or event.actor,
                occurred_at=local(event.occurred_at,prop).strftime('%d/%m/%Y %H:%M:%S'),document=context.origin(event.source_doctype,event.source_name),reason=event.reason))
    return dict(version=1,business_date=str(prop.business_date),rows=rows)
