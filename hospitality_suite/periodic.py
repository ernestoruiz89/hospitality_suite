"""Accepted nightly charges: scheduled obligations, never another accounting ledger.

The caller owns the property lock and transaction. A night keeps its accepted
price and deterministic origin even after billing, reopening or an HTTP retry.
"""
import hashlib

import frappe
from frappe.utils import now_datetime

from hospitality_suite.pricing import decimal
from hospitality_suite.service import audit, current_all, locked_doc


def schedule(prop, stay, folio, snapshot, origin, expected):
    if stay.lodging_charge_policy!='Nightly' or snapshot['rules']['mode']!='Hotel':
        return False
    nights=snapshot.get('nightly') or []
    if not nights or sum(decimal(row['amount']) for row in nights)!=decimal(expected):
        frappe.throw(frappe._('La programación nocturna no coincide con el importe aceptado'))
    from hospitality_suite.operations import charge
    from hospitality_suite.item_configuration import bound_item
    item=bound_item(prop,snapshot,'lodging_item')
    for index,night in enumerate(nights):
        key=hashlib.sha256(f'{stay.name}|{origin}|{night["date"]}|{index}'.encode()).hexdigest()
        if current_all('HS Charge',filters={'period_key':key}):
            continue
        # Each source snapshot contains exactly this night, so report attribution
        # cannot spread one nightly amount across the entire accepted stay.
        details={**snapshot,'nightly':[night],'amount':night['amount'],'units':1}
        record=charge(prop,stay,folio,item,night['amount'],'Lodging',
                      frappe._('Alojamiento · noche {0}').format(night['date']),details)
        record.update(dict(status='Scheduled',period_key=key,service_date=night['date'],business_date=night['date']))
        record.save()
    return True


def generate(prop):
    """Only the current operational date and overdue nights; no wall-clock advance."""
    due=current_all('HS Charge',filters={'property':prop.name,'status':'Scheduled','service_date':['<=',prop.business_date]},fields=['name'])
    generated=[]
    for row in due:
        record=locked_doc('HS Charge',row.name)
        record.status='Pending'
        record.posted_at=now_datetime()
        record.save()
        generated.append(record.name)
    if generated:
        audit(prop,'Generate nightly charges',prop,details=dict(business_date=str(prop.business_date),charges=generated))
    return dict(generated=len(generated),business_date=str(prop.business_date))


def generate_command(prop,data):
    return generate(prop)


def scheduled_amount(folio):
    return sum(decimal(row.amount) for row in current_all('HS Charge',filters={'folio':folio,'status':'Scheduled'},fields=['amount']))


def settle_before_billing(prop,folio):
    """Explicit invoicing settles accepted future nights once, including early exit."""
    sources=current_all('HS Charge',filters={'property':prop.name,'folio':folio,'status':'Scheduled'},fields=['name'])
    for row in sources:
        record=locked_doc('HS Charge',row.name)
        record.status='Pending'
        record.posted_at=now_datetime()
        record.save()
    if sources:
        audit(prop,'Settle accepted nightly charges',locked_doc('HS Folio',folio),details=dict(charges=[row.name for row in sources]))
