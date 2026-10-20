"""Refund original customer funds using their native allocations and book value."""
import frappe

from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import require
from hospitality_suite.service import current_all,locked_doc


def plan(prop,source,amount,method,credit_note=None):
    require(prop.name,'approve')
    if source.kind not in ('Advance','Payment') or source.status!='Posted' or source.currency!=method.currency or not source.payment_entry:
        frappe.throw(frappe._('Origen de devolución inválido'))
    original=locked_doc('Payment Entry',source.payment_entry)
    currency=original.paid_from_account_currency
    if original.docstatus!=1 or original.payment_type!='Receive' or original.party_type!='Customer' or original.party!=source.customer or original.company!=prop.company or original.hs_property!=prop.name or currency!=prop.currency:
        frappe.throw(frappe._('El movimiento original no conserva una cuenta de cliente y moneda compatibles'))
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
            returned_party+=sum(decimal(line.debit_in_account_currency)-decimal(line.credit_in_account_currency) for line in native.accounts if line.account==original.paid_from and line.party_type=='Customer' and line.party==original.party)
    remaining=money(decimal(source.amount)-refunded,currency=source.currency)
    if amount<=0 or amount>remaining:
        frappe.throw(frappe._('La devolución supera el importe disponible'))
    remaining_party=money(decimal(original.paid_amount)-returned_party,currency=currency)
    # The last refund absorbs currency rounding, without leaving book-value dust.
    party_amount=remaining_party if amount==remaining else money(decimal(original.paid_amount)*amount/decimal(source.amount),currency=currency)
    if party_amount<=0 or party_amount>remaining_party:
        frappe.throw(frappe._('Revise el importe de devolución y su precisión en la moneda del cliente'))
    credit=None
    if credit_note:
        credit=locked_doc('Sales Invoice',credit_note)
        if credit.docstatus!=1 or not credit.is_return or credit.company!=prop.company or credit.hs_property!=prop.name or credit.customer!=source.customer or credit.debit_to!=original.paid_from:
            frappe.throw(frappe._('La nota de crédito no corresponde al pagador, cuenta y establecimiento originales'))
        allocated=sum(decimal(row.allocated_amount) for row in original.references if row.reference_doctype=='Sales Invoice' and row.reference_name==credit.return_against)
        available=money(allocated-by_invoice.get(credit.return_against,decimal(0)),currency=currency)
        if party_amount>available:
            frappe.throw(frappe._('La devolución supera lo aplicado por este movimiento a la factura de origen'))
        if party_amount>abs(min(decimal(0),decimal(credit.outstanding_amount))):
            frappe.throw(frappe._('La devolución supera el crédito disponible'))
        mode='Applied Advance' if source.kind=='Advance' else 'Invoice Payment'
    else:
        if source.kind!='Advance':
            frappe.throw(frappe._('Seleccione la nota de crédito para devolver un pago facturado'))
        if party_amount>decimal(original.unallocated_amount):
            frappe.throw(frappe._('El anticipo ya está aplicado; seleccione una nota de crédito de su factura de origen'))
        mode='Unallocated Advance'
    proof=dict(mode=mode,source=source.name,original=original.name,original_modified=str(original.modified),
               remaining=str(remaining),remaining_party=str(remaining_party),party_amount=str(party_amount),party_currency=currency,
               party_rate=str(original.source_exchange_rate),account=original.paid_from,
               credit_note=credit.name if credit else None,invoice=credit.return_against if credit else None,
               credit_modified=str(credit.modified) if credit else None,credit_outstanding=str(credit.outstanding_amount) if credit else None,
               allocated=str(available) if credit else None,unallocated=str(original.unallocated_amount))
    return frappe._dict(original=original,credit=credit,party_amount=party_amount,party_rate=decimal(original.source_exchange_rate),account=original.paid_from,proof=proof)
