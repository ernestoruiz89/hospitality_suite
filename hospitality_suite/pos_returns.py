"""Native credit notes and linked journals return POS net receipts by currency."""
from collections import defaultdict

import frappe
from frappe.utils import nowdate

from hospitality_suite.pricing import decimal, money, currency_precision
from hospitality_suite.security import document
from hospitality_suite.service import current_all


def total(doc):
    return decimal(doc.grand_total if doc.disable_rounded_total else doc.rounded_total)


def ledger(names, accounts, doctype='Sales Invoice'):
    result=defaultdict(lambda: dict(amount=decimal(0),base=decimal(0)))
    if names and accounts:
        for row in current_all('GL Entry',filters={'voucher_type':doctype,'voucher_no':['in',names],
                                                  'account':['in',list(accounts)],'is_cancelled':0},
                               fields=['account','account_currency','debit','credit','debit_in_account_currency','credit_in_account_currency']):
            values=result[(row.account,row.account_currency)]
            values['amount']+=decimal(row.debit_in_account_currency)-decimal(row.credit_in_account_currency)
            values['base']+=decimal(row.debit)-decimal(row.credit)
    return result


def linked_vouchers(property_name, credits):
    result={}
    for dt,child,field in (('Journal Entry','Journal Entry Account','reference_type'),('Payment Entry','Payment Entry Reference','reference_doctype')):
        names=current_all(child,filters={field:'Sales Invoice','reference_name':['in',credits],'docstatus':1},pluck='parent') if credits else []
        result[dt]=current_all(dt,filters={'name':['in',names],'hs_property':property_name,'docstatus':1},pluck='name',order_by='name') if names else []
    return result


def is_last(invoice,credit,returns):
    quantities=defaultdict(lambda:decimal(0))
    for doc in [*returns,credit]:
        for row in doc.items:
            quantities[row.sales_invoice_item]-=decimal(row.qty)
    return all(quantities[row.name]>=decimal(row.qty) for row in invoice.items if row.qty>0)


def validate_valuation(invoice,funds):
    company_currency=frappe.get_cached_value('Company',invoice.company,'default_currency')
    tolerance=decimal(10)**-currency_precision(company_currency)*(len(invoice.payments)+1)
    for (account,currency),values in funds.items():
        if currency not in (company_currency,invoice.currency):
            frappe.throw(frappe._('Revise la moneda del medio POS en ERPNext'))
        rate=decimal(1) if currency==company_currency else decimal(invoice.conversion_rate)
        if abs(money(values['amount']*rate,currency=company_currency)-money(values['base'],currency=company_currency))>tolerance:
            frappe.throw(frappe._('La valoración del cobro POS no conserva su moneda. Revise el documento en ERPNext; para nuevos cobros con vuelto en moneda extranjera utilice Venta directa'))


def configure(prop, invoice, credit, data, returns):
    from hospitality_suite.accounting import exchange
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_total_in_party_account_currency
    shift=document('HS Shift',data.get('shift'),'approve')
    if shift.property!=prop.name or shift.status!='Open':
        frappe.throw(frappe._('Seleccione un turno abierto de este establecimiento para la devolución POS'))
    # The credit owns stock; a linked journal expresses mixed signs/currencies.
    credit.update(dict(hs_shift=shift.name,is_pos=0,update_outstanding_for_self=1,change_amount=0,base_change_amount=0,
                       write_off_amount=0,base_write_off_amount=0,redeem_loyalty_points=0,loyalty_amount=0))
    credit.set('payments',[])
    credit.calculate_taxes_and_totals()
    amount=-total(credit)
    original_total=total(invoice)
    if original_total<=0 or amount<=0:
        frappe.throw(frappe._('La nota debe contener cantidades pendientes de devolución'))
    ratio=amount/original_total
    last=is_last(invoice,credit,returns)
    returned_ratio=sum((-total(row) for row in returns),decimal(0))/original_total
    company_currency=frappe.get_cached_value('Company',invoice.company,'default_currency')
    accounts={row.account for row in invoice.payments if row.account}
    if invoice.account_for_change_amount:
        accounts.add(invoice.account_for_change_amount)
    original=ledger([invoice.name],accounts)
    validate_valuation(invoice,original)
    previous=ledger([row.name for row in returns],accounts)
    linked=linked_vouchers(prop.name,[row.name for row in returns])
    for dt,names in linked.items():
        for key,values in ledger(names,accounts,dt).items():
            previous[key]['amount']+=values['amount']
            previous[key]['base']+=values['base']
    methods=current_all('HS Payment Method',filters={'property':prop.name},fields=['name','account','currency','mode_of_payment','is_cash','reference_required','modified'])
    payments=[]
    for (account,currency),funds in sorted(original.items()):
        if not funds['amount']:
            continue
        received=money(funds['amount'],currency=currency)
        prior=money(previous[(account,currency)]['amount'],currency=currency)
        available=received+prior
        # Do not sweep money belonging to an earlier unpaid credit note. Only
        # accumulated currency rounding may be absorbed by the final quantity.
        tolerance=decimal(10)**-currency_precision(currency)*(len(returns)+1)
        previous_difference=prior+received*returned_ratio
        absorb=last and abs(previous_difference)<=tolerance
        value=money(available if absorb else received*ratio,currency=currency)
        if (received>0 and not 0<=value<=max(available,decimal(0))) or (received<0 and not min(available,decimal(0))<=value<=0):
            frappe.throw(frappe._('Los medios originales no conservan fondos suficientes para esta devolución'))
        matching=[row for row in methods if row.account==account and row.currency==currency]
        original_modes={row.mode_of_payment for row in invoice.payments if row.account==account}
        matching=[row for row in matching if row.mode_of_payment in original_modes] or matching
        if not matching or len({bool(row.is_cash) for row in matching})!=1:
            frappe.throw(frappe._('Configure los medios de pago originales de la factura POS'))
        method=sorted(matching,key=lambda row:(row.mode_of_payment,row.name))[0]
        if not value:
            continue
        if method.reference_required and not data.get('reference'):
            frappe.throw(frappe._('Indique la referencia bancaria de la devolución POS'))
        fx=exchange(currency,company_currency)
        payments.append(dict(account=account,method=method.name,mode_of_payment=method.mode_of_payment,currency=currency,
                             amount=str(value),exchange_rate=str(fx),base_amount=str(money(value*fx,currency=company_currency)),
                             is_cash=bool(method.is_cash),method_modified=str(method.modified)))
    party_currency=invoice.party_account_currency
    party_rate=decimal(1) if party_currency==company_currency else decimal(invoice.conversion_rate)
    original_party=ledger([invoice.name],{invoice.debit_to})[(invoice.debit_to,party_currency)]['amount']
    offset=money(min(max(decimal(0),decimal(invoice.outstanding_amount)),max(decimal(0),original_party)*(1 if last else ratio)),currency=party_currency)
    book=money(-decimal(get_total_in_party_account_currency(credit)),currency=party_currency)
    write_off=money(decimal(invoice.write_off_amount)*ratio,currency=invoice.currency)
    write_off_base=money(write_off*decimal(invoice.conversion_rate),currency=company_currency)
    base_out=sum((decimal(row['base_amount']) for row in payments),decimal(0))
    difference=money((book-offset)*party_rate-base_out-write_off_base,currency=company_currency)
    historical_out=decimal(0)
    for row in payments:
        funds=original[(row['account'],row['currency'])]
        historical_out+=decimal(row['amount'])*funds['base']/funds['amount']
    expected_fx=money(historical_out-base_out,currency=company_currency)
    tolerance=decimal(10)**-currency_precision(company_currency)*(len(returns)+len(credit.items)+len(payments)+1)
    if abs(difference-expected_fx)>tolerance:
        frappe.throw(frappe._('La nota incluye fondos o ajustes de otros movimientos; concilie sus orígenes antes de devolver. No se registró la devolución'))
    return dict(shift=shift.name,shift_modified=str(shift.modified),payments=payments,
                refund=str(money(base_out/decimal(invoice.conversion_rate),currency=invoice.currency)),
                party_account=invoice.debit_to,party_currency=party_currency,party_rate=str(party_rate),party_amount=str(book),offset=str(offset),
                write_off_account=invoice.write_off_account,write_off_base=str(write_off_base),exchange_difference=str(difference),base_currency=company_currency,
                source_receipts=[dict(account=key[0],currency=key[1],amount=str(value['amount']),base=str(value['base'])) for key,value in sorted(original.items())],
                previous_receipts=[dict(account=key[0],currency=key[1],amount=str(value['amount']),base=str(value['base'])) for key,value in sorted(previous.items())],
                linked_vouchers=linked)


def post(prop,invoice,credit,review,data):
    from hospitality_suite.accounting import post_standard,balance_exchange
    journal=frappe.new_doc('Journal Entry')
    journal.update(dict(company=prop.company,posting_date=nowdate(),voucher_type='Journal Entry',multi_currency=1,
                        hs_property=prop.name,hs_shift=review['shift'],hs_stay=invoice.hs_stay,hs_booking=invoice.hs_booking,hs_folio=invoice.hs_folio,
                        user_remark=data['reason'],cheque_no=data.get('reference') or credit.name,cheque_date=nowdate()))
    common=dict(account=review['party_account'],party_type='Customer',party=invoice.customer,exchange_rate=float(decimal(review['party_rate'])),cost_center=prop.cost_center,reference_type='Sales Invoice')
    journal.append('accounts',dict(common,reference_name=credit.name,debit_in_account_currency=float(decimal(review['party_amount']))))
    if decimal(review['offset']):
        journal.append('accounts',dict(common,reference_name=invoice.name,credit_in_account_currency=float(decimal(review['offset']))))
    for row in review['payments']:
        amount=decimal(row['amount'])
        journal.append('accounts',dict(account=row['account'],account_currency=row['currency'],exchange_rate=float(decimal(row['exchange_rate'])),cost_center=prop.cost_center,
                                       credit_in_account_currency=float(amount) if amount>0 else 0,debit_in_account_currency=float(-amount) if amount<0 else 0))
    if decimal(review['write_off_base']):
        journal.append('accounts',dict(account=review['write_off_account'],exchange_rate=1,cost_center=prop.cost_center,credit_in_account_currency=float(decimal(review['write_off_base']))))
    balance_exchange(journal,prop)
    post_standard(journal,prop)
    actual=ledger([journal.name],{row['account'] for row in review['payments']},'Journal Entry')
    if any(money(actual[(row['account'],row['currency'])]['amount'],currency=row['currency'])!=-decimal(row['amount']) for row in review['payments']):
        frappe.throw(frappe._('La devolución contable no coincide con los medios revisados; no se registró la operación'))
    return journal.name
