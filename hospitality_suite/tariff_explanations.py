"""Read accepted charge snapshots; never consult today's rate or reprice a stay."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json

import frappe


def _number(value):
    result=Decimal(str(value or 0))
    if not result.is_finite():
        raise ValueError('Non-finite historical number')
    return result


def _n(value):
    return format(_number(value),'f')


def _date(value):
    if not value:
        return None
    result=datetime.fromisoformat(str(value))
    if len(str(value))==10:
        return result.strftime('%d/%m/%Y')
    offset=result.strftime('%z')
    return result.strftime('%d/%m/%Y %H:%M:%S')+((' UTC'+offset[:3]+':'+offset[3:]) if offset else '')


def _text(value):
    return [value] if isinstance(value,str) and value else [v for v in value if isinstance(v,str)] if isinstance(value,list) else []


def _supplements(snapshot,rules,currency):
    lines=[]
    if snapshot.get('people') is None or snapshot.get('extra_beds') is None:
        return [frappe._('El documento no conserva el detalle numérico de ocupación y camas; se mantiene el importe aceptado.')]
    accepted_people,accepted_beds=_number(snapshot['people']),_number(snapshot['extra_beds'])
    if accepted_people<1 or accepted_beds<0 or accepted_people%1 or accepted_beds%1:
        raise ValueError('Invalid historical occupancy')
    people=max(0,int(accepted_people)-int(rules.get('included_people') or 2))
    beds=int(accepted_beds)
    for label,quantity,unit in ((frappe._('Personas adicionales'),people,rules.get('additional_person_rate')),
                                (frappe._('Camas adicionales'),beds,rules.get('extra_bed_rate'))):
        if quantity:
            lines.append(frappe._('{0}: {1} × {2} = {3} {4}').format(label,quantity,_n(unit),_n(quantity*_number(unit)),currency))
    if not lines:
        lines.append(frappe._('Sin suplementos de personas o camas en esta cotización.'))
    return lines


def _entry(snapshot,rules,currency,label,amount):
    return dict(label=label,details=[frappe._('Precio base: {0} {1}').format(_n(rules.get('amount')),currency),
                                   *_supplements(snapshot,rules,currency)],amount=_n(amount),currency=currency)


def _historical(snapshot,row,result):
    rules=snapshot.get('rules') or {}
    if not isinstance(rules,dict):
        raise ValueError('Invalid historical rules')
    currency=row.get('currency') or snapshot.get('currency') or ''
    mode=rules.get('mode')
    from hospitality_suite.display_labels import MODE_LABELS
    result['mode_label']=frappe._(MODE_LABELS[mode]) if mode in MODE_LABELS else None
    reference=None
    # Timing/services may carry a lodging rule as context, not as their price.
    if row.get('kind')=='Lodging' and mode=='Hotel' and snapshot.get('nightly'):
        if not isinstance(snapshot['nightly'],list):
            raise ValueError('Invalid historical nights')
        result['title']=frappe._('Tarifas aceptadas por noche')
        reference=Decimal(0)
        for night in snapshot['nightly']:
            if not isinstance(night,dict) or not isinstance(night.get('rules') or {},dict):
                raise ValueError('Invalid historical night')
            rule=night.get('rules') or {}
            label=frappe._('Noche del {0} · {1}').format(_date(night['date']),rule.get('title') or frappe._('Tarifa histórica'))
            result['entries'].append(_entry(snapshot,rule,currency,label,night['amount']))
            reference+=_number(night['amount'])
    elif row.get('kind')=='Lodging' and mode=='Motel':
        result['title']=frappe._('Bloque y tiempo adicional aceptados')
        title=rules.get('title') or frappe._('Tarifa histórica')
        bindings=snapshot.get('charge_items') or {}
        if not isinstance(bindings,dict):
            raise ValueError('Invalid historical item bindings')
        separate=bindings.get('lodging_item') and bindings.get('extra_hour_item') and bindings['lodging_item']!=bindings['extra_hour_item']
        hours=separate and row.get('item')==bindings['extra_hour_item']
        base=separate and row.get('item')==bindings['lodging_item']
        if separate and not (hours or base):
            raise ValueError('Charge item differs from accepted bindings')
        label=frappe._('Bloque de {0} h · {1}').format(_n(rules.get('block_hours') or 3),title)
        if not hours:
            amount=snapshot.get('lodging_amount',snapshot.get('segment_amount',snapshot.get('amount')))
            result['entries'].append(_entry(snapshot,rules,currency,label,amount))
        if not base:
            extra=snapshot.get('extra_hours_amount')
            details=[frappe._('Tolerancia aceptada: {0} min; fracción de cobro: {1} min.').format(_n(rules.get('grace_minutes')),_n(rules.get('rounding_minutes') or 60))]
            if snapshot.get('extra_hours_quantity') is not None and extra is not None:
                fractions=_number(snapshot['extra_hours_quantity'])*60/_number(rules.get('rounding_minutes') or 60)
                details.append(frappe._('Fracciones aceptadas: {0} de {1} min.').format(_n(fractions),_n(rules.get('rounding_minutes') or 60)))
                details.append(frappe._('Tiempo adicional facturable: {0} h × {1} {2} por hora.').format(_n(snapshot['extra_hours_quantity']),_n(rules.get('extra_hour_rate')),currency))
                result['entries'].append(dict(label=frappe._('Tiempo adicional · {0}').format(title),details=details,amount=_n(extra),currency=currency))
            else:
                result['notes'].extend(details+_text(snapshot.get('explanation')))
        reference=_number(snapshot.get('extra_hours_amount')) if hours else _number(snapshot.get('lodging_amount')) if base else _number(snapshot.get('segment_amount',snapshot.get('amount')))
        if not separate:
            # One legacy lodging article may contain both base and overtime.
            # Its first entry is the quote total; do not add overtime twice.
            result['notes'].append(frappe._('Los componentes de tiempo describen la cotización completa; no son nuevos cargos para sumar.'))
        interval=' → '.join(filter(None,(_date(snapshot.get('service_start') or snapshot.get('start')),_date(snapshot.get('service_end') or snapshot.get('end')))))
        if interval:
            result['notes'].append(frappe._('Intervalo conservado: {0}').format(interval))
    else:
        result['notes'].extend(_text(snapshot.get('explanation')))
        if not result['notes']:
            result['notes'].append(frappe._('El documento no conserva un desglose histórico de tarifa. Se muestra el importe registrado.'))
    base_explanation=snapshot.get('base_explanation')
    explanations=snapshot.get('explanation')
    if result['entries'] and (snapshot.get('people') is None or snapshot.get('extra_beds') is None):
        result['notes'].extend(_text(explanations))
    if isinstance(base_explanation,list) and isinstance(explanations,list) and explanations[:len(base_explanation)]==base_explanation:
        benefits=_text(explanations[len(base_explanation):])
        if benefits:
            result['notes'].append(frappe._('Beneficios de la cotización de origen; no son cargos adicionales:'))
            result['notes'].extend(benefits)
    adjustment=row.get('adjustment_type')
    if adjustment:
        result['title']={"Discount":frappe._('Descuento autorizado'),"Courtesy":frappe._('Cortesía autorizada'),"Surcharge":frappe._('Recargo autorizado')}.get(adjustment,frappe._('Ajuste autorizado'))
        result['scope']=frappe._('Este movimiento es un ajuste al cargo original. El desglose de tarifa es una referencia, no otro cobro.')
    elif row.get('applies_to_charge'):
        result['scope']=frappe._('Abono sobre un cargo anterior. Se conserva su tarifa como referencia; el importe de este movimiento es el abono registrado.')
    elif reference is not None and reference!=_number(row.get('amount')):
        result['scope']=frappe._('El cargo registra solamente una diferencia o parte de la cotización. Los importes de referencia siguientes no se suman otra vez a la cuenta.')
    elif reference is None and not result['entries']:
        result['scope']=frappe._('Explicación conservada; el importe se toma del cargo registrado.')
    else:
        result['scope']=frappe._('Desglose del cargo registrado, según la cotización aceptada.')
    if row.get('reason'):
        result['notes'].append(frappe._('Motivo: {0}').format(row['reason']))
    if row.get('status')=='Reversed':
        result['scope']=frappe._('Cargo revertido: no forma parte del saldo actual. Se conserva este detalle histórico.')
    elif row.get('status')=='Scheduled':
        result['scope']=frappe._('Cargo programado, todavía sin generar ni facturar.')+' '+result['scope']
    if result['entries']:
        precision=snapshot.get('precision')
        if precision is not None and str(precision).isdigit() and 0<=int(precision)<=9:
            result['notes'].append(frappe._('Los importes aceptados conservan el redondeo histórico a {0} decimales.').format(int(precision)))
        else:
            result['notes'].append(frappe._('El documento no conserva la precisión del redondeo; los importes aceptados se muestran sin recalcular.'))


def describe_charge(row):
    """Plain-text projection only; callers authorize the enclosing stay/folio."""
    result=dict(title=frappe._('Explicación del cargo'),scope='',entries=[],notes=[],
                recorded_amount=str(row.get('amount') or 0),currency=row.get('currency'))
    try:
        raw=row.get('quote_snapshot')
        snapshot=json.loads(raw) if isinstance(raw,str) and raw else raw or {}
        if not isinstance(snapshot,dict):
            raise ValueError('Invalid historical snapshot')
        _historical(snapshot,row,result)
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
        result.update(entries=[],scope=frappe._('Importe registrado; no se ha recalculado la tarifa.'),
                      notes=[frappe._('El documento no conserva un desglose histórico válido. Solicite la revisión del registro original.')])
    return result
