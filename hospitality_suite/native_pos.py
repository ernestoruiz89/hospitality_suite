"""Project POS Sales Invoice receipts from ERPNext GL, without another payment."""
from collections import defaultdict

import frappe

from hospitality_suite.pricing import decimal
from hospitality_suite.service import current_all,locked_doc,lock_property,operation


def method_used(method):
    lock_property(method.property)
    with operation():
        invoices=current_all("Sales Invoice",filters={"hs_property":method.property,"is_pos":1,"docstatus":["!=",0]},pluck="name")
        return bool(invoices and current_all("Sales Invoice Payment",filters={"parenttype":"Sales Invoice","parent":["in",invoices],"account":method.account,"mode_of_payment":method.mode_of_payment},pluck="name"))


def validate(doc,prop):
    if not doc.is_pos or not any(decimal(row.amount) for row in doc.payments):
        return
    lock_property(prop.name)
    if not doc.get("hs_shift"):
        frappe.throw(frappe._("Asigne un turno abierto a la factura POS de este establecimiento"))
    shift=frappe.get_doc("HS Shift",doc.hs_shift,for_update=True)
    if shift.property!=prop.name or shift.status!="Open":
        frappe.throw(frappe._("No puede registrar movimientos en un turno cerrado"))
    if shift.cashier!=frappe.session.user:
        from hospitality_suite.security import require
        require(prop.name,"approve")
    with operation():
        methods=current_all("HS Payment Method",filters={"property":prop.name},fields=["account","mode_of_payment","reference_required","is_cash"])
    for row in doc.payments:
        if not decimal(row.amount):
            continue
        matches=[method for method in methods if method.account==row.account and method.mode_of_payment==row.mode_of_payment]
        if len(matches)!=1 or len({bool(method.is_cash) for method in methods if method.account==row.account})!=1:
            frappe.throw(frappe._("Configure un medio de pago inequívoco del establecimiento para cada cobro POS"))
        if matches[0].reference_required and not row.reference_no:
            frappe.throw(frappe._("La referencia bancaria es obligatoria"))
    if decimal(doc.change_amount) and not any(method.account==doc.account_for_change_amount and method.is_cash for method in methods):
        frappe.throw(frappe._("El vuelto POS debe salir de un medio de efectivo del establecimiento"))


def movements(property_name,shift=None):
    """Called only inside already authorized projections/commands for this property."""
    filters={"hs_property":property_name,"docstatus":1,"is_pos":1}
    if shift:
        filters["hs_shift"]=shift
    methods=current_all("HS Payment Method",filters={"property":property_name},fields=["account","currency","is_cash"])
    result=[]
    documents=[locked_doc('Sales Invoice',name) for name in current_all('Sales Invoice',filters=filters,pluck='name')]
    originals=current_all('Sales Invoice',filters={'hs_property':property_name,'is_pos':1,'is_return':0,'docstatus':1},pluck='name')
    credits=current_all('Sales Invoice',filters={'hs_property':property_name,'return_against':['in',originals],'is_return':1,'docstatus':1},pluck='name') if originals else []
    from hospitality_suite.pos_returns import linked_vouchers
    for dt,names in linked_vouchers(property_name,credits).items():
        field='journal_entry' if dt=='Journal Entry' else 'payment_entry'
        for name in names:
            if current_all('HS Payment',filters={field:name,'status':'Posted'},pluck='name'):
                continue
            doc=locked_doc(dt,name)
            if not shift or doc.hs_shift==shift:
                documents.append(doc)
    for invoice in documents:
        name=invoice.name
        if invoice.doctype=='Sales Invoice':
            accounts={row.account for row in invoice.payments if row.account}
            if invoice.account_for_change_amount:
                accounts.add(invoice.account_for_change_amount)
        else:
            accounts={row.account for row in methods}
        sums=defaultdict(lambda:decimal(0))
        for entry in current_all("GL Entry",filters={"voucher_type":invoice.doctype,"voucher_no":name,"is_cancelled":0},
                                 fields=["account","account_currency","debit_in_account_currency","credit_in_account_currency"]):
            if entry.account in accounts:
                sums[(entry.account,entry.account_currency)]+=decimal(entry.debit_in_account_currency)-decimal(entry.credit_in_account_currency)
        for (account,currency),amount in sorted(sums.items()):
            if not amount:
                continue
            mappings={(row.currency,bool(row.is_cash)) for row in methods if row.account==account}
            mapped=len(mappings)==1 and next(iter(mappings))[0]==currency
            result.append(dict(name=name,doctype=invoice.doctype,shift=invoice.hs_shift,creation=invoice.creation,
                               posting_date=invoice.posting_date,account=account,currency=currency,amount=amount,
                               is_cash=next(iter(mappings))[1] if mapped else False,mapped=mapped))
    return result


def validate_posted(doc):
    if not doc.is_pos:
        return
    from hospitality_suite.pos_returns import ledger,validate_valuation
    accounts={row.account for row in doc.payments if row.account}
    if doc.account_for_change_amount:
        accounts.add(doc.account_for_change_amount)
    validate_valuation(doc,ledger([doc.name],accounts))
