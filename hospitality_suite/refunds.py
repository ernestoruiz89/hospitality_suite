"""Refund original customer funds using their native allocations and book value."""
import frappe

from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import require
from hospitality_suite.service import current_all,locked_doc


def original_funds(prop,source):
    if source.kind in ('Advance','Payment') and source.payment_entry:
        doc=locked_doc('Payment Entry',source.payment_entry)
        currency=doc.paid_from_account_currency
        if doc.docstatus!=1 or doc.payment_type!='Receive' or doc.party_type!='Customer' or doc.party!=source.customer or doc.company!=prop.company or doc.hs_property!=prop.name or currency!=prop.currency:
            frappe.throw(frappe._('El movimiento original no conserva una cuenta de cliente y moneda compatibles'))
        return frappe._dict(doc=doc,account=doc.paid_from,currency=currency,total=decimal(doc.paid_amount),rate=decimal(doc.source_exchange_rate),
                            references=[dict(invoice=row.reference_name,amount=decimal(row.allocated_amount)) for row in doc.references if row.reference_doctype=='Sales Invoice'],
                            unallocated=decimal(doc.unallocated_amount),available_rows=[dict(name=None,amount=decimal(doc.unallocated_amount))])
    if source.kind!='Guarantee Applied' or not source.journal_entry or not source.source_payment:
        frappe.throw(frappe._('Origen de devolución inválido'))
    received=locked_doc('HS Payment',source.source_payment)
    doc=locked_doc('Journal Entry',source.journal_entry)
    if source.property!=prop.name or received.property!=prop.name or received.kind!='Guarantee' or received.status!='Posted' or received.currency!=source.currency or received.customer!=source.customer or doc.docstatus!=1 or doc.company!=prop.company or doc.hs_property!=prop.name:
        frappe.throw(frappe._('La aplicación no conserva una garantía y un documento de origen vigentes'))
    rows=[row for row in doc.accounts if row.party_type=='Customer' and row.party==source.customer and decimal(row.credit_in_account_currency)>0]
    keys={(row.account,row.account_currency,decimal(row.exchange_rate)) for row in rows}
    if len(keys)!=1:
        frappe.throw(frappe._('La aplicación no conserva una cuenta y valoración de cliente inequívocas'))
    account,currency,rate=next(iter(keys))
    if currency!=prop.currency:
        frappe.throw(frappe._('La moneda de la aplicación no coincide con la cuenta del cliente'))
    available=[dict(name=row.name,amount=decimal(row.credit_in_account_currency)) for row in rows if not row.reference_type]
    return frappe._dict(doc=doc,account=account,currency=currency,total=sum(decimal(row.credit_in_account_currency) for row in rows),rate=rate,
                        references=[dict(invoice=row.reference_name,amount=decimal(row.credit_in_account_currency)) for row in rows if row.reference_type=='Sales Invoice'],
                        unallocated=sum((row['amount'] for row in available),decimal(0)),available_rows=available)


def plan(prop,source,amount,method,credit_note=None):
    require(prop.name,'approve')
    if source.kind not in ('Advance','Payment','Guarantee Applied') or source.status!='Posted' or source.currency!=method.currency:
        frappe.throw(frappe._('Origen de devolución inválido'))
    funds=original_funds(prop,source)
    original,currency=funds.doc,funds.currency
    refunded=decimal(0)
    returned_party=decimal(0)
    by_invoice={}
    for row in current_all('HS Payment',filters={'source_payment':source.name,'kind':'Refund','status':'Posted'},fields=['name','amount','payment_entry','journal_entry']):
        refunded+=decimal(row.amount)
        native=locked_doc('Payment Entry' if row.payment_entry else 'Journal Entry',row.payment_entry or row.journal_entry)
        if native.docstatus!=1:
            frappe.throw(frappe._('Conciliación pendiente: una devolución no conserva su documento presentado'))
        if row.payment_entry:
            returned_party+=decimal(native.received_amount)
            for reference in native.references:
                if reference.reference_doctype=='Sales Invoice' and decimal(reference.allocated_amount)<0:
                    parent=frappe.db.get_value('Sales Invoice',reference.reference_name,'return_against')
                    by_invoice[parent]=by_invoice.get(parent,decimal(0))-decimal(reference.allocated_amount)
        else:
            returned_party+=sum(decimal(line.debit_in_account_currency)-decimal(line.credit_in_account_currency) for line in native.accounts if line.account==funds.account and line.party_type=='Customer' and line.party==source.customer)
    remaining=money(decimal(source.amount)-refunded,currency=source.currency)
    if amount<=0 or amount>remaining:
        frappe.throw(frappe._('La devolución supera el importe disponible'))
    remaining_party=money(funds.total-returned_party,currency=currency)
    # The last refund absorbs currency rounding, without leaving book-value dust.
    party_amount=remaining_party if amount==remaining else money(funds.total*amount/decimal(source.amount),currency=currency)
    if party_amount<=0 or party_amount>remaining_party:
        frappe.throw(frappe._('Revise el importe de devolución y su precisión en la moneda del cliente'))
    credit=None
    if credit_note:
        credit=locked_doc('Sales Invoice',credit_note)
        if credit.docstatus!=1 or not credit.is_return or credit.company!=prop.company or credit.hs_property!=prop.name or credit.customer!=source.customer or credit.debit_to!=funds.account:
            frappe.throw(frappe._('La nota de crédito no corresponde al pagador, cuenta y establecimiento originales'))
        allocated=sum((row['amount'] for row in funds.references if row['invoice']==credit.return_against),decimal(0))
        available=money(allocated-by_invoice.get(credit.return_against,decimal(0)),currency=currency)
        if party_amount>available:
            frappe.throw(frappe._('La devolución supera lo aplicado por este movimiento a la factura de origen'))
        if party_amount>abs(min(decimal(0),decimal(credit.outstanding_amount))):
            frappe.throw(frappe._('La devolución supera el crédito disponible'))
        mode='Applied Advance' if source.kind=='Advance' else 'Applied Guarantee' if source.kind=='Guarantee Applied' else 'Invoice Payment'
    else:
        if source.kind not in ('Advance','Guarantee Applied'):
            frappe.throw(frappe._('Seleccione la nota de crédito para devolver un pago facturado'))
        if party_amount>funds.unallocated:
            frappe.throw(frappe._('El anticipo ya está aplicado; seleccione una nota de crédito de su factura de origen'))
        mode='Unallocated Advance' if source.kind=='Advance' else 'Unallocated Guarantee Application'
    proof=dict(mode=mode,source=source.name,original=original.name,original_doctype=original.doctype,original_modified=str(original.modified),
               remaining=str(remaining),remaining_party=str(remaining_party),party_amount=str(party_amount),party_currency=currency,
               party_rate=str(funds.rate),account=funds.account,
               credit_note=credit.name if credit else None,invoice=credit.return_against if credit else None,
               credit_modified=str(credit.modified) if credit else None,credit_outstanding=str(credit.outstanding_amount) if credit else None,
               allocated=str(available) if credit else None,unallocated=str(funds.unallocated))
    return frappe._dict(original=original,credit=credit,party_amount=party_amount,party_rate=funds.rate,account=funds.account,available_rows=funds.available_rows,proof=proof)
