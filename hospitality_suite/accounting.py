from hospitality_suite.service import current_all, locked_doc
"""ERPNext is the sole accounting system. All postings use standard controllers."""
from decimal import Decimal

import frappe
from frappe.utils import nowdate, now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, operation, canonical


def ready(prop):
    from hospitality_suite.install import validate_financial_configuration
    if not prop.financial_enabled:
        frappe.throw(frappe._("Habilite y valide la configuración financiera"))
    validate_financial_configuration(prop)


def post_standard(doc, prop):
    """Delegated, narrowly scoped integration: validated PMS action may post its own
    ERP document without granting operational users general accounting privileges.
    No caller supplies arbitrary account lines or a doctype to this helper.
    """
    doc.hs_property = prop.name
    if doc.doctype=="Sales Invoice":
        # Native defaults may belong to another warehouse in the same company.
        # Operational deliveries already own stock; their invoice stays scoped.
        for row in doc.items:
            if not row.warehouse:
                row.warehouse=prop.warehouse
    if doc.doctype=="Sales Invoice" and prop.get("invoice_series"):
        doc.naming_series=prop.invoice_series
    elif doc.doctype=="Payment Entry" and prop.get("payment_series"):
        doc.naming_series=prop.payment_series
    doc.flags.ignore_permissions = True
    before = getattr(frappe.local, "hs_posting", False)
    frappe.local.hs_posting = True
    try:
        doc.insert()
        doc.submit()
    finally:
        frappe.local.hs_posting = before
    return doc


def folio_balance(name):
    folio = document("HS Folio", name)
    pending = sum(decimal(r.amount) for r in current_all("HS Charge", filters={"folio": name, "status": "Pending"}, fields=["amount"]))
    invoices = current_all("Sales Invoice", filters={"hs_folio": name, "docstatus": 1}, pluck="name")
    outstanding = sum(decimal(locked_doc("Sales Invoice", inv).outstanding_amount) for inv in set(invoices) if inv)
    from hospitality_suite.periodic import scheduled_amount
    scheduled=scheduled_amount(name)
    return dict(pending=str(money(pending)),scheduled=str(money(scheduled)), outstanding=str(money(outstanding + pending + scheduled)), currency=folio.currency)


def folios_for_stay(stay):
    rows=current_all("HS Folio",filters={"stay":stay.name},fields=["*"])
    if stay.booking:
        rows+=current_all("HS Folio",filters={"property":stay.property,"booking":stay.booking,"stay":["is","not set"]},fields=["*"])
    return list({r.name:r for r in rows}.values())


def invoice_quote(prop,data):
    return invoice_folio(prop,data,preview=True)


def invoice_folio(prop, data, *, preview=False):
    ready(prop)
    folio = document("HS Folio", data["folio"])
    if folio.property!=prop.name or folio.company!=prop.company:
        frappe.throw(frappe._('La cuenta no corresponde al establecimiento de esta operación'),frappe.PermissionError)
    if not preview and data.get('invoice_acceptance'):
        if invoice_quote(prop,data).get('acceptance')!=data['invoice_acceptance']:
            frappe.throw(frappe._('La cuenta o la configuración de facturación cambió. Revise nuevamente la factura'))
    from hospitality_suite.periodic import settle_before_billing
    if not preview:
        settle_before_billing(prop,folio.name)
    charges = current_all("HS Charge", filters={"folio": folio.name, "status": ['in',['Pending','Scheduled']]}, fields=["*"],order_by='creation asc,name asc')
    if not charges:
        if preview:
            return dict(ready=False,folio=folio.name,currency=folio.currency)
        reconciled = reconcile_folio_advances(prop, folio)
        return dict(invoices=current_all("Sales Invoice", filters={"hs_folio":folio.name,"docstatus":1},pluck="name"),reconciled=reconciled)
    stay = locked_doc("HS Stay", folio.stay) if folio.stay else None
    booking_name=folio.booking or (stay.booking if stay else None)
    inv = frappe.new_doc("Sales Invoice")
    inv.flags.ignore_permissions=True
    from hospitality_suite.credit import invoice_due_date
    inv.update(dict(company=prop.company, customer=folio.customer, posting_date=nowdate(), due_date=invoice_due_date(prop, folio.customer),
                    currency=folio.currency, debit_to=prop.receivable_account, cost_center=prop.cost_center,
                    hs_stay=stay.name if stay else None,hs_booking=booking_name, hs_folio=folio.name, update_stock=0, taxes_and_charges=prop.tax_template))
    inv.party_account_currency=frappe.db.get_value('Account',prop.receivable_account,'account_currency') or frappe.db.get_value('Company',prop.company,'default_currency')
    mapping = []
    for charge in charges:
        if charge.applies_to_charge:
            continue
        related=[charge]+[r for r in charges if r.applies_to_charge==charge.name]
        total=sum(decimal(r.amount) for r in related)
        if total<0 or decimal(charge.quantity)<=0:
            frappe.throw(frappe._("El ajuste requiere una nota de crédito estándar sobre su factura de origen"))
        rate=total/decimal(charge.quantity)
        row = inv.append("items", dict(item_code=charge.item, qty=charge.quantity, rate=float(rate),price_list_rate=charge.rate,
                                       discount_amount=float(decimal(charge.rate)-rate),
                                       description=charge.description, cost_center=prop.cost_center, warehouse=prop.warehouse, hs_charge=charge.name,
                                       hs_charge_sources=frappe.as_json([r.name for r in related])))
        mapping.extend((r.name,row) for r in related)
    if len(mapping)!=len(charges):
        frappe.throw(frappe._("Traslade el cargo y sus ajustes a la misma cuenta antes de facturar"))
    inv.set_missing_values()
    if prop.tax_template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        inv.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", prop.tax_template))
    inv.calculate_taxes_and_totals()
    remaining = decimal(inv.rounded_total or inv.grand_total)
    advances = current_all("HS Payment", filters={"property": prop.name, "customer": folio.customer, "kind": ["in", ["Advance", "Guarantee Applied"]], "status": "Posted"}, fields=["*"])
    for payment in advances:
        matches=(stay and payment.stay==stay.name) or (booking_name and payment.booking==booking_name)
        if not matches:
            continue
        if payment.kind == "Guarantee Applied":
            journal = locked_doc("Journal Entry", payment.journal_entry)
            if journal.docstatus != 1:
                continue
            row = next((r for r in journal.accounts if r.party == folio.customer and r.account == prop.receivable_account and not r.reference_type and r.credit_in_account_currency>0), None)
            if not row:
                continue
            used = sum(decimal(r.allocated_amount) for r in current_all("Sales Invoice Advance", filters={"reference_type":"Journal Entry", "reference_name":journal.name,"reference_row":row.name}, fields=["allocated_amount", "parent"]) if frappe.db.get_value("Sales Invoice", r.parent, "docstatus") == 1)
            amount = min(remaining, decimal(row.credit_in_account_currency)-used)
            if amount > 0:
                inv.append("advances", dict(reference_type="Journal Entry", reference_name=journal.name, reference_row=row.name,
                                           advance_amount=float(amount), allocated_amount=float(amount), ref_exchange_rate=journal.accounts[0].exchange_rate))
                remaining -= amount
            continue
        pe = locked_doc("Payment Entry", payment.payment_entry)
        if pe.docstatus != 1 or pe.company != prop.company or pe.party != folio.customer or pe.paid_from != prop.receivable_account:
            continue
        amount = min(remaining, decimal(pe.unallocated_amount))
        if amount > 0:
            inv.append("advances", dict(reference_type="Payment Entry", reference_name=pe.name,
                                       advance_amount=pe.unallocated_amount, allocated_amount=float(amount), ref_exchange_rate=pe.source_exchange_rate))
            remaining -= amount
    if preview:
        # Native calculation, without insert/submit, naming series or allocations.
        inv.calculate_taxes_and_totals()
        from hashlib import sha256
        item_fields=('item_code','qty','rate','amount','net_rate','net_amount','income_account','expense_account','cost_center','warehouse','hs_charge','hs_charge_sources')
        tax_fields=('charge_type','account_head','rate','tax_amount','total','included_in_print_rate','cost_center','add_deduct_tax')
        advance_fields=('reference_type','reference_name','reference_row','advance_amount','allocated_amount','ref_exchange_rate')
        totals={key:inv.get(key) for key in ('currency','party_account_currency','posting_date','conversion_rate','net_total','total_taxes_and_charges','grand_total','rounded_total','disable_rounded_total','total_advance','outstanding_amount','debit_to','cost_center')}
        signature=dict(property_modified=str(prop.modified),folio_modified=str(folio.modified),charges=charges,totals=totals,
                       items=[{key:row.get(key) for key in item_fields} for row in inv.items],
                       taxes=[{key:row.get(key) for key in tax_fields} for row in inv.taxes],
                       advances=[{key:row.get(key) for key in advance_fields} for row in inv.advances])
        return dict(ready=True,folio=folio.name,label=folio.label,customer=frappe.db.get_value('Customer',folio.customer,'customer_name'),
                    posting_date=str(inv.posting_date),currency=inv.currency,net_total=str(money(inv.net_total,currency=inv.currency)),
                    taxes=str(money(inv.total_taxes_and_charges,currency=inv.currency)),total=str(money(inv.grand_total,currency=inv.currency)),
                    payable=str(money(inv.rounded_total or inv.grand_total,currency=inv.currency)),advance=str(money(inv.total_advance,currency=inv.currency)),
                    outstanding=str(money(inv.outstanding_amount,currency=inv.party_account_currency or inv.currency)),outstanding_currency=inv.party_account_currency or inv.currency,
                    scheduled=str(money(sum(decimal(row.amount) for row in charges if row.status=='Scheduled'),currency=inv.currency)),
                    lines=len(inv.items),acceptance=sha256(canonical(signature).encode()).hexdigest())
    post_standard(inv, prop)
    for name, row in mapping:
        doc = locked_doc("HS Charge", name)
        doc.status, doc.sales_invoice, doc.invoice_item = "Invoiced", inv.name, row.name
        doc.save()
    audit(prop, "Invoice", folio, details={"sales_invoice": inv.name, "charges": [r.name for r in charges]})
    return dict(invoice=inv.name, total=inv.grand_total, outstanding=inv.outstanding_amount, currency=inv.currency)


def reconcile_folio_advances(prop, folio):
    """Apply only this visit's available advances through ERPNext's controller.

    Reconciliation changes allocations, never the historic cash amount or shift.
    The standard controller also calculates exchange differences when applicable.
    """
    invoices=current_all("Sales Invoice",filters={"hs_folio":folio.name,"docstatus":1,"outstanding_amount":[">",0]},pluck="name")
    if not invoices:
        return []
    payments=current_all("HS Payment",filters={"property":prop.name,"customer":folio.customer,"kind":["in",["Advance","Guarantee Applied"]],"status":"Posted"},fields=["*"])
    stay=locked_doc("HS Stay",folio.stay) if folio.stay else None
    booking=folio.booking or (stay.booking if stay else None)
    origins={p.payment_entry or p.journal_entry for p in payments if (stay and p.stay==stay.name) or (booking and p.booking==booking)}
    if not origins:
        return []
    rec=frappe.new_doc("Payment Reconciliation")
    rec.update(dict(company=prop.company,party_type="Customer",party=folio.customer,
                    receivable_payable_account=prop.receivable_account,cost_center=prop.cost_center,
                    payment_limit=1000,invoice_limit=1000))
    rec.get_unreconciled_entries()
    selected_payments=[p.as_dict() for p in rec.payments if p.reference_name in origins and p.amount>0]
    selected_invoices=[i.as_dict() for i in rec.invoices if i.invoice_number in invoices and i.outstanding_amount>0]
    if not selected_payments or not selected_invoices:
        return []
    rec.set("payments",selected_payments)
    rec.set("invoices",selected_invoices)
    rec.allocate_entries(dict(payments=[p.copy() for p in selected_payments],invoices=[i.copy() for i in selected_invoices]))
    rec.validate_allocation()
    rec.reconcile_allocations()
    rows=[dict(payment=r.reference_name,invoice=r.invoice_number,amount=r.allocated_amount) for r in rec.allocation]
    audit(prop,"Reconcile advances",folio,details={"allocations":rows})
    return rows


def credit_draft(prop, data):
    ready(prop)
    require(prop.name, "approve")
    inv = locked_doc("Sales Invoice", data["invoice"])
    if inv.hs_property != prop.name or inv.company!=prop.company or inv.docstatus != 1 or inv.is_return or not data.get("reason"):
        frappe.throw(frappe._("Seleccione una factura presentada de este establecimiento e indique el motivo"))
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
    target=frappe.new_doc("Sales Invoice")
    target.flags.ignore_permissions=True
    credit = make_sales_return(inv.name,target_doc=target)
    selected = {r["invoice_item"]: decimal(r["quantity"]) for r in data.get("items", [])}
    if len(selected)!=len(data.get('items',[])):
        frappe.throw(frappe._('Seleccione cada línea de devolución una sola vez'))
    if 'items' in data and not selected:
        frappe.throw(frappe._('Seleccione al menos una cantidad para devolver'))
    if selected:
        kept = []
        for row in credit.items:
            if row.sales_invoice_item in selected:
                quantity = selected[row.sales_invoice_item]
                if quantity <= 0 or quantity > abs(decimal(row.qty)):
                    frappe.throw(frappe._("Cantidad de devolución inválida"))
                row.qty = -float(quantity)
                kept.append(row)
        if len(kept) != len(selected):
            frappe.throw(frappe._("Línea de factura desconocida"))
        credit.set("items", kept)
    credit.set('items',[row for row in credit.items if decimal(row.qty)<0])
    if not credit.items:
        frappe.throw(frappe._('La factura ya no tiene cantidades pendientes de devolución'))
    # Native POS invoices own their stock ledger; operational deliveries use
    # Stock Entry and keep update_stock=0 on both invoice and credit note.
    credit.update(dict(hs_stay=inv.hs_stay,hs_booking=inv.hs_booking, hs_folio=inv.hs_folio, update_stock=inv.update_stock, remarks=data["reason"]))
    for row in credit.items:
        row.hs_charge = None
        row.hs_charge_sources=None
    credit.calculate_taxes_and_totals()
    return inv,credit


def credit_review(prop,inv,credit,data):
    import hashlib
    from hospitality_suite.service import canonical
    from hospitality_suite.pos_returns import total
    returns=[locked_doc('Sales Invoice',name) for name in current_all('Sales Invoice',filters={'return_against':inv.name,'docstatus':1},pluck='name',order_by='name')]
    pos=None
    if inv.is_pos:
        from hospitality_suite.pos_returns import configure
        pos=configure(prop,inv,credit,data,returns)
    values=dict(invoice=inv.name,invoice_modified=str(inv.modified),currency=inv.currency,total=str(money(-total(credit),currency=inv.currency)),
                rounding_adjustment=str(money(-decimal(credit.rounding_adjustment),currency=inv.currency)),
                is_pos=bool(inv.is_pos),update_stock=bool(credit.update_stock),write_off=str(credit.write_off_amount),pos=pos,
                items=[dict(invoice_item=row.sales_invoice_item,item_name=row.item_name or row.item_code,quantity=str(-decimal(row.qty)),amount=str(-decimal(row.amount))) for row in credit.items if row.qty],
                returns=[dict(name=row.name,modified=str(row.modified),total=str(total(row))) for row in returns])
    values['acceptance']=hashlib.sha256(canonical(values).encode()).hexdigest()
    return values


def credit_note_quote(prop,data):
    inv,credit=credit_draft(prop,data)
    if current_all('HS Service Request',filters={'property':prop.name,'sales_invoice':inv.name,'stay':['is','not set']},pluck='name'):
        frappe.throw(frappe._('Para una venta directa, use Devolver en Consumos e inventario; ese flujo devuelve también el dinero y las existencias'))
    return credit_review(prop,inv,credit,data)


def credit_note(prop,data):
    inv,credit=credit_draft(prop,data)
    review=credit_review(prop,inv,credit,data)
    if (inv.is_pos or data.get('acceptance')) and data.get('acceptance')!=review['acceptance']:
        frappe.throw(frappe._('La factura o sus devoluciones cambiaron; revise la nota de crédito otra vez'))
    credit.flags.hs_credit_reviewed=bool(data.get('acceptance'))
    post_standard(credit, prop)
    refund_journal=None
    if review['pos']:
        from hospitality_suite.pos_returns import post
        refund_journal=post(prop,inv,credit,review['pos'],data)
    for row in credit.items:
        original = next((i for i in inv.items if i.name == row.sales_invoice_item), None)
        if original and abs(decimal(row.qty)) == decimal(original.qty):
            service_name = frappe.db.get_value("HS Service Request", {"charge": original.hs_charge}) if original.hs_charge else None
            if service_name:
                service = locked_doc("HS Service Request", service_name)
                service.credit_note = credit.name
                service.save()
    audit(prop, "Credit note", locked_doc("HS Folio",inv.hs_folio) if inv.hs_folio else inv, data["reason"], {"invoice": inv.name, "credit_note": credit.name,"refund_journal":refund_journal,"review":review},values_doc=credit)
    return dict(credit_note=credit.name, amount=credit.grand_total,currency=credit.currency,pos=review['pos'],refund_journal=refund_journal)


def apply_guarantee(prop, data):
    ready(prop)
    source = document("HS Payment", data["source_payment"], "approve")
    folio = document("HS Folio", data["folio"], "approve")
    matches=source.stay==folio.stay if folio.stay else source.booking==folio.booking
    if source.kind != "Guarantee" or source.status != "Posted" or not matches or source.customer != folio.customer or not data.get("reason"):
        frappe.throw(frappe._("Garantía, pagador o motivo incompatible"))
    used = sum(decimal(p.amount) for p in current_all("HS Payment", filters={"source_payment": source.name, "status":"Posted","kind":["in",["Guarantee Refund","Guarantee Applied"]]}, fields=["amount"]))
    amount = money(data["amount"],currency=source.currency)
    if amount <= 0 or amount + used > decimal(source.amount):
        frappe.throw(frappe._("El importe supera la garantía disponible"))
    shifts=current_all("HS Shift",filters={"property":prop.name,"cashier":frappe.session.user,"status":"Open"},fields=["name"])
    shift=document("HS Shift",data.get("shift") or (shifts[0].name if shifts else ""),"approve")
    if shift.status!="Open":
        frappe.throw(frappe._("Abra un turno para registrar la aplicación de garantía"))
    # The liability is measured in property currency at its original posting rate.
    base = money(amount * decimal(source.exchange_rate))
    company_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    fx = exchange(prop.currency, company_currency)
    liability=original_guarantee(source)
    liability_amount=money(decimal(liability.credit_in_account_currency)*amount/decimal(source.amount))
    party_amount = liability_amount
    journal = frappe.new_doc("Journal Entry")
    journal.update(dict(company=prop.company, posting_date=nowdate(), voucher_type="Journal Entry", multi_currency=1,
                        hs_stay=source.stay,hs_booking=source.booking,hs_shift=shift.name, hs_folio=folio.name, user_remark=data["reason"]))
    journal.append("accounts", dict(account=liability.account, debit_in_account_currency=float(liability_amount), exchange_rate=liability.exchange_rate, cost_center=prop.cost_center))
    remaining=party_amount
    for inv in current_all("Sales Invoice",filters={"hs_folio":folio.name,"docstatus":1,"outstanding_amount":[">",0]},fields=["name","outstanding_amount"],order_by="posting_date asc"):
        allocated=min(remaining,decimal(inv.outstanding_amount))
        if allocated>0:
            journal.append("accounts",dict(account=prop.receivable_account,party_type="Customer",party=folio.customer,
                                            credit_in_account_currency=float(allocated),exchange_rate=float(fx),cost_center=prop.cost_center,
                                            reference_type="Sales Invoice",reference_name=inv.name))
            remaining-=allocated
    if remaining>0:
        journal.append("accounts", dict(account=prop.receivable_account, party_type="Customer", party=folio.customer,
                                         credit_in_account_currency=float(remaining), exchange_rate=float(fx), is_advance="Yes", cost_center=prop.cost_center))
    balance_exchange(journal,prop)
    post_standard(journal, prop)
    record = insert("HS Payment", prop, stay=source.stay, booking=source.booking, folio=folio.name, customer=folio.customer,
                    shift=shift.name, method=source.method, amount=amount, currency=source.currency, exchange_rate=source.exchange_rate,
                    base_amount=base, kind="Guarantee Applied", status="Posted", journal_entry=journal.name, source_payment=source.name, reason=data["reason"])
    audit(prop, "Apply guarantee", record, data["reason"])
    return dict(payment=record.name, journal_entry=journal.name)


def cancellation_fee(prop,booking,status):
    import hashlib
    import json
    prefix="no_show" if status=="No Show" else "cancellation"
    mode=prop.get(prefix+"_fee_mode") or "None"
    value=decimal(prop.get(prefix+"_fee_value"))
    amount=decimal(0)
    if mode=="Fixed":
        amount=value
    elif mode=="Percent":
        if not 0<=value<=100:
            frappe.throw(frappe._("El porcentaje de penalización debe estar entre 0 y 100"))
        amount=decimal(booking.amount)*value/100
    elif mode=="First Night":
        snapshot=json.loads(booking.quote_snapshot)
        amount=sum(decimal(line["nightly"][0]["amount"]) if line.get("nightly") else decimal(line["amount"])/decimal(line.get("units") or 1) for line in snapshot["lines"])
    result=dict(amount=str(money(amount)),currency=booking.currency,mode=mode,status=status)
    from hospitality_suite.service import canonical
    result["acceptance"]=hashlib.sha256(canonical(dict(booking=booking.name,modified=str(booking.modified),**result)).encode()).hexdigest()
    return result


def invoice_cancellation(prop,booking,fee,reason):
    ready(prop)
    if not prop.get("penalty_item"):
        frappe.throw(frappe._("Configure el artículo de penalización antes de aplicar esta política"))
    invoice=frappe.new_doc("Sales Invoice")
    invoice.flags.ignore_permissions=True
    invoice.update(dict(company=prop.company,customer=booking.customer,currency=booking.currency,posting_date=nowdate(),due_date=nowdate(),
                        debit_to=prop.receivable_account,cost_center=prop.cost_center,hs_booking=booking.name,update_stock=0,remarks=reason,
                        taxes_and_charges=prop.tax_template))
    invoice.append("items",dict(item_code=prop.penalty_item,qty=1,rate=float(decimal(fee["amount"])),cost_center=prop.cost_center,warehouse=prop.warehouse,
                                description="Cancelación / no presentación: "+booking.name))
    invoice.set_missing_values()
    if prop.tax_template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        invoice.set("taxes",get_taxes_and_charges("Sales Taxes and Charges Template",prop.tax_template))
    invoice.calculate_taxes_and_totals()
    remaining=decimal(invoice.grand_total)
    for row in current_all("HS Payment",filters={"booking":booking.name,"customer":booking.customer,"kind":"Advance","status":"Posted"},fields=["payment_entry"]):
        pe=locked_doc("Payment Entry",row.payment_entry)
        allocation=min(remaining,decimal(pe.unallocated_amount))
        if pe.docstatus==1 and allocation>0:
            invoice.append("advances",dict(reference_type="Payment Entry",reference_name=pe.name,advance_amount=pe.unallocated_amount,
                                           allocated_amount=float(allocation),ref_exchange_rate=pe.source_exchange_rate))
            remaining-=allocation
    return post_standard(invoice,prop)


def exchange(from_currency, to_currency, posting_date=None):
    if from_currency == to_currency:
        return Decimal(1)
    from erpnext.setup.utils import get_exchange_rate
    rate = decimal(get_exchange_rate(from_currency, to_currency, posting_date or nowdate(), args="for_selling"))
    if rate <= 0:
        frappe.throw(frappe._("Configure un tipo de cambio válido en ERPNext"))
    return rate


def original_guarantee(source):
    doc=locked_doc("Journal Entry",source.journal_entry)
    if doc.docstatus!=1:
        frappe.throw(frappe._("La garantía no tiene un documento contable vigente"))
    rows=[r for r in doc.accounts if r.credit_in_account_currency>0 and frappe.db.get_value("Account",r.account,"root_type")=="Liability"]
    if len(rows)!=1:
        frappe.throw(frappe._("La garantía no conserva una línea de pasivo inequívoca"))
    return rows[0]


def balance_exchange(journal,prop):
    debit=sum(decimal(r.debit_in_account_currency)*decimal(r.exchange_rate or 1) for r in journal.accounts)
    credit=sum(decimal(r.credit_in_account_currency)*decimal(r.exchange_rate or 1) for r in journal.accounts)
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    difference=money(debit-credit,currency=company_currency)
    if not difference:
        return
    account=prop.get("exchange_gain_loss_account") or frappe.db.get_value("Company",prop.company,"exchange_gain_loss_account")
    if not account:
        frappe.throw(frappe._("Configure una cuenta de ganancia/pérdida cambiaria para registrar esta devolución"))
    details=locked_doc("Account",account)
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    if details.company!=prop.company or details.is_group or details.account_currency!=company_currency or details.root_type not in ("Income","Expense"):
        frappe.throw(frappe._("Revise la cuenta de diferencia cambiaria"))
    journal.append("accounts",dict(account=account,cost_center=prop.cost_center,exchange_rate=1,
                                    debit_in_account_currency=float(-difference) if difference<0 else 0,
                                    credit_in_account_currency=float(difference) if difference>0 else 0))


def payment(prop, data):
    ready(prop)
    shift = document("HS Shift", data["shift"], "finance")
    if shift.status != "Open":
        frappe.throw(frappe._("El turno no está abierto"))
    if shift.cashier != frappe.session.user:
        require(prop.name, "approve")
    method = document("HS Payment Method", data["method"], "finance")
    if method.reference_required and not data.get("reference"):
        frappe.throw(frappe._("La referencia bancaria es obligatoria"))
    amount = money(data["amount"],currency=method.currency)
    if amount <= 0:
        frappe.throw(frappe._("El importe debe ser positivo"))
    tendered=money(data.get("tendered") or amount,currency=method.currency)
    change=money(tendered-amount,currency=method.currency)
    if tendered<amount or (change and not method.is_cash):
        frappe.throw(frappe._("Revise el efectivo recibido; el vuelto solo se permite en medios de efectivo"))
    kind = data.get("kind", "Payment")
    if kind not in ("Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund"):
        frappe.throw(frappe._("Tipo de movimiento inválido"))
    from hospitality_suite.payment_policies import authorize
    policy=authorize(prop,kind)
    source = None
    if kind in ("Refund", "Guarantee Refund"):
        require(prop.name, "approve")
        if not data.get("reason") or not data.get("source_payment"):
            frappe.throw(frappe._("Indique el pago original y el motivo de devolución"))
        source = document("HS Payment", data["source_payment"], "finance")
        expected = "Guarantee" if kind == "Guarantee Refund" else ("Advance", "Payment", "Guarantee Applied")
        if (source.kind != expected if isinstance(expected, str) else source.kind not in expected) or source.status != "Posted":
            frappe.throw(frappe._("Origen de devolución inválido"))
        if source.currency != method.currency:
            frappe.throw(frappe._("Devuelva en la moneda del movimiento original"))
        refunded = sum(decimal(p.amount) for p in current_all("HS Payment", filters={"source_payment": source.name, "status": "Posted","kind":["in",["Refund","Guarantee Refund","Guarantee Applied"]]}, fields=["amount"]))
        if refunded + amount > decimal(source.amount):
            frappe.throw(frappe._("La devolución supera el importe disponible"))
        data = {**data, "stay": source.stay, "booking": source.booking, "customer": source.customer, "folio": source.folio}
    stay = document("HS Stay", data["stay"], "finance") if data.get("stay") else None
    booking = document("HS Booking", data["booking"], "finance") if data.get("booking") else None
    if kind in ("Advance","Guarantee") and ((stay and stay.status!="Active") or (booking and booking.status not in ("Hold","Confirmed","Checked In"))):
        frappe.throw(frappe._("No reciba anticipos o garantías en una visita terminada o reserva cancelada"))
    if stay and booking and stay.booking!=booking.name:
        frappe.throw(frappe._("La estancia y la reserva no tienen el mismo origen"))
    folio = document("HS Folio", data["folio"], "finance") if data.get("folio") else None
    if not stay and not booking and not (source and kind=='Refund'):
        frappe.throw(frappe._("El pago debe tener una estancia o reserva de origen"))
    if folio:
        matches=(stay and folio.stay==stay.name) if folio.stay else folio.booking==(booking.name if booking else stay.booking if stay else None)
        if not matches:
            frappe.throw(frappe._("La cuenta no corresponde a la estancia o grupo"))
    customer = folio.customer if folio else (source.customer if source else (stay.customer if stay else booking.customer))
    company_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    fx = exchange(method.currency, company_currency)
    property_fx = exchange(prop.currency, company_currency)
    refund_plan=None
    if source and kind=='Refund':
        from hospitality_suite.refunds import plan
        refund_plan=plan(prop,source,amount,method,data.get('credit_note'))
    if data.get("fx_acceptance") and data["fx_acceptance"]!=payment_quote(prop,data)["acceptance"]:
        frappe.throw(frappe._("Los importes o fondos disponibles cambiaron; revise el movimiento otra vez"))
    party_amount = refund_plan.party_amount if refund_plan else money(amount * fx / property_fx)
    party_rate=refund_plan.party_rate if refund_plan else property_fx
    is_refund = kind in ("Refund", "Guarantee Refund")
    if kind in ("Guarantee", "Guarantee Refund"):
        journal = frappe.new_doc("Journal Entry")
        journal.update(dict(company=prop.company, posting_date=nowdate(), voucher_type="Journal Entry", multi_currency=1,
                            hs_stay=stay.name if stay else None, hs_shift=shift.name, user_remark=data.get("reason") or "Garantía reembolsable"))
        liability_account=prop.guarantee_account
        liability_value=party_amount
        liability_rate=property_fx
        if is_refund:
            original=original_guarantee(source)
            liability_account=original.account
            liability_value=money(decimal(original.credit_in_account_currency)*amount/decimal(source.amount))
            liability_rate=decimal(original.exchange_rate)
        for account, value, is_debit, currency, rate in [
            (method.account, amount, not is_refund, method.currency, fx),
            (liability_account, liability_value, is_refund, prop.currency, liability_rate),
        ]:
            journal.append("accounts", dict(account=account, account_currency=currency, exchange_rate=float(rate), cost_center=prop.cost_center,
                                            debit_in_account_currency=float(value) if is_debit else 0,
                                            credit_in_account_currency=0 if is_debit else float(value)))
        balance_exchange(journal,prop)
        post_standard(journal, prop)
        pe = None
    elif refund_plan and not refund_plan.credit:
        # Settle unused customer credit with a native Journal Entry, then update
        # the original PE/JV allocation through ERPNext's reconciliation controller.
        original = refund_plan.original
        journal = frappe.new_doc("Journal Entry")
        journal.update(dict(company=prop.company,posting_date=nowdate(),voucher_type="Journal Entry",multi_currency=1,
                            hs_stay=stay.name if stay else None,hs_shift=shift.name,hs_folio=folio.name if folio else None,user_remark=data["reason"]))
        journal.append("accounts",dict(account=refund_plan.account,party_type="Customer",party=customer,
                                       debit_in_account_currency=float(party_amount),exchange_rate=float(party_rate),cost_center=prop.cost_center))
        journal.append("accounts",dict(account=method.account,credit_in_account_currency=float(amount),exchange_rate=float(fx),cost_center=prop.cost_center))
        balance_exchange(journal,prop)
        post_standard(journal,prop)
        from erpnext.accounts.utils import reconcile_against_document
        remaining=party_amount
        for row in refund_plan.available_rows:
            allocated=min(remaining,row['amount'])
            if allocated<=0:
                continue
            reconcile_against_document([frappe._dict(voucher_type=original.doctype,voucher_no=original.name,voucher_detail_no=row['name'],
                                                    against_voucher_type="Journal Entry",against_voucher=journal.name,
                                                    account=refund_plan.account,party_type="Customer",party=customer,
                                                    exchange_rate=float(party_rate),is_advance="Yes",dr_or_cr="credit_in_account_currency",
                                                    unadjusted_amount=float(row['amount']),unreconciled_amount=float(row['amount']),
                                                    allocated_amount=float(allocated),difference_amount=0,cost_center=prop.cost_center)])
            remaining-=allocated
        if remaining:
            frappe.throw(frappe._('Los fondos disponibles cambiaron; revise la devolución'))
        pe = None
    else:
        invoice = None
        if kind == "Payment":
            if not folio:
                frappe.throw(frappe._("Seleccione la cuenta de estancia a cobrar"))
            invoice_folio(prop, {"folio": folio.name})
            names = set(current_all("HS Charge", filters={"folio": folio.name, "status": "Invoiced"}, pluck="sales_invoice"))
            invoices = [locked_doc("Sales Invoice", n) for n in names if n]
            if party_amount > sum(decimal(inv.outstanding_amount) for inv in invoices):
                frappe.throw(frappe._("El cobro supera el saldo; registre un anticipo separado si corresponde"))
        elif refund_plan:
            refund_invoice=refund_plan.credit
        pe = frappe.new_doc("Payment Entry")
        pe.update(dict(company=prop.company, payment_type="Pay" if is_refund else "Receive", posting_date=nowdate(),
                       party_type="Customer", party=customer, mode_of_payment=method.mode_of_payment,
                       paid_from=method.account if is_refund else prop.receivable_account,
                       paid_to=refund_plan.account if refund_plan else prop.receivable_account if is_refund else method.account,
                       paid_amount=float(amount if is_refund else party_amount), received_amount=float(party_amount if is_refund else amount),
                       source_exchange_rate=float(fx if is_refund else property_fx), target_exchange_rate=float(party_rate if is_refund else fx),
                       reference_no=data.get("reference") or f"HS-{shift.name}", reference_date=nowdate(), cost_center=prop.cost_center,
                       hs_stay=stay.name if stay else None, hs_shift=shift.name, hs_folio=folio.name if folio else None, hs_booking=booking.name if booking else None))
        if kind == "Payment":
            remaining = party_amount
            for invoice in invoices:
                allocation = min(remaining, decimal(invoice.outstanding_amount))
                if allocation > 0:
                    pe.append("references", dict(reference_doctype="Sales Invoice", reference_name=invoice.name, allocated_amount=float(allocation)))
                    remaining -= allocation
        elif refund_plan and refund_plan.credit:
            pe.append("references",dict(reference_doctype="Sales Invoice",reference_name=refund_invoice.name,allocated_amount=-float(party_amount)))
            if prop.get('exchange_gain_loss_account') and money(amount*fx-party_amount*party_rate,currency=company_currency):
                account=locked_doc('Account',prop.exchange_gain_loss_account)
                if account.company!=prop.company or account.is_group or account.account_currency!=company_currency or account.root_type not in ('Income','Expense'):
                    frappe.throw(frappe._('Revise la cuenta de diferencia cambiaria'))
                pe.append('deductions',dict(account=account.name,cost_center=prop.cost_center,is_exchange_gain_loss=1))
        post_standard(pe, prop)
        journal = None
    record = insert("HS Payment", prop, stay=stay.name if stay else None, booking=booking.name if booking else (stay.booking if stay else None),
                    folio=folio.name if folio else None, customer=customer, shift=shift.name, method=method.name, amount=amount,
                    currency=method.currency, exchange_rate=fx, base_amount=money(amount * fx), kind=kind, status="Posted",
                    payment_entry=pe.name if pe else None, journal_entry=journal.name if journal else None,
                    sales_invoice=refund_plan.credit.name if refund_plan and refund_plan.credit else None,
                    source_payment=source.name if source else None, reference=data.get("reference"), reason=data.get("reason"),tendered=tendered,change_amount=change)
    audit(prop, kind, record, data.get("reason"),dict(payment_policy=policy,refund=refund_plan.proof if refund_plan else None) if policy or refund_plan else None)
    return dict(payment=record.name, payment_entry=record.payment_entry, journal_entry=record.journal_entry, amount=str(amount), currency=method.currency,
                tendered=str(tendered),change=str(change),exchange_rate=str(fx),base_amount=str(record.base_amount))


def payment_quote(prop,data):
    ready(prop)
    import hashlib
    from hospitality_suite.service import canonical
    from hospitality_suite.payment_policies import authorize
    policy=authorize(prop,data.get("kind","Payment"))
    method=document("HS Payment Method",data["method"],"finance")
    amount=money(data["amount"],currency=method.currency)
    tendered=money(data.get("tendered") or amount,currency=method.currency)
    if amount<=0 or tendered<amount or (tendered!=amount and not method.is_cash):
        frappe.throw(frappe._("Revise el importe y el efectivo recibido"))
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    fx=exchange(method.currency,company_currency)
    property_fx=exchange(prop.currency,company_currency)
    values=dict(amount=str(amount),currency=method.currency,exchange_rate=str(fx),base_amount=str(money(amount*fx,currency=company_currency)),
                base_currency=company_currency,property_amount=str(money(amount*fx/property_fx,currency=prop.currency)),property_currency=prop.currency,
                tendered=str(tendered),change=str(money(tendered-amount,currency=method.currency)),method=method.name)
    values["payment_policy"]=policy
    if data.get('kind')=='Refund':
        from hospitality_suite.refunds import plan
        source=document('HS Payment',data.get('source_payment'),'finance')
        refund=plan(prop,source,amount,method,data.get('credit_note'))
        values['refund']={**refund.proof,'exchange_difference':str(money(amount*fx-refund.party_amount*refund.party_rate,currency=company_currency))}
    values["acceptance"]=hashlib.sha256(canonical(values).encode()).hexdigest()
    return values


def sync_document(doc, method=None):
    """Includes external Desk postings/cancellations, without trusting a client link."""
    if not doc.get("hs_stay") and not doc.get("hs_property"):
        return
    stay = locked_doc("HS Stay", doc.hs_stay) if doc.get("hs_stay") else None
    prop = require(stay.property if stay else doc.hs_property)
    party = doc.get("customer") or doc.get("party")
    if doc.company != prop.company or (stay and doc.doctype in ("Sales Invoice", "Payment Entry") and party != stay.customer):
        # Split folios may have an explicitly assigned company/agency payer.
        customers = [r.customer for r in folios_for_stay(stay)] if stay else []
        if doc.company != prop.company or party not in customers:
            frappe.throw(frappe._("Compañía o pagador incompatible con la estancia"))
    from hospitality_suite.service import lock_property
    lock_property(prop.name)
    with operation():
        if doc.doctype == "Sales Invoice" and doc.docstatus == 1 and doc.is_return and doc.return_against:
            source_stays=current_all("HS Charge",filters={"sales_invoice":doc.return_against,
                "kind":"Lodging"},pluck="stay")
            for stay_name in set(source_stays):
                booking_name=frappe.db.get_value("HS Stay",stay_name,"booking") if stay_name else None
                if booking_name and frappe.db.get_value("HS Booking",booking_name,"agent_commission_invoice"):
                    frappe.throw(frappe._("Revierta primero la factura de comisión de la agencia"))
        if doc.doctype == "Purchase Invoice" and doc.docstatus == 2:
            booking_name = frappe.db.get_value("HS Booking", {"property": prop.name,
                "agent_commission_invoice": doc.name}, "name")
            if booking_name:
                booking = locked_doc("HS Booking", booking_name)
                booking.agent_commission_invoice = None
                booking.save()
                audit(prop, "Cancel agent commission", booking, doc.get("hs_correction_reason"),
                      dict(purchase_invoice=doc.name))
        if doc.doctype=='Sales Invoice' and doc.docstatus==1:
            from hospitality_suite.native_pos import validate_posted
            validate_posted(doc)
        if (stay or doc.get("hs_folio")) and doc.doctype == "Sales Invoice" and doc.docstatus == 1:
            folio_name = doc.get("hs_folio")
            if not folio_name and stay:
                candidates=[r for r in folios_for_stay(stay) if r.customer==doc.customer]
                if len(candidates)==1:
                    folio_name=candidates[0].name
            if not folio_name:
                frappe.throw(frappe._("Asigne una cuenta de estancia al cliente de la factura"))
            if not doc.get("hs_folio"):
                doc.db_set("hs_folio", folio_name, update_modified=False)
            for row in doc.items:
                charge = locked_doc("HS Charge", row.hs_charge) if row.get("hs_charge") else None
                if not charge:
                    original=None
                    if doc.is_return and row.get("sales_invoice_item"):
                        source=frappe.db.get_value("Sales Invoice Item",row.sales_invoice_item,"hs_charge")
                        original=locked_doc("HS Charge",source) if source else None
                    origin_stay=stay.name if stay else original.stay if original else None
                    if not origin_stay:
                        frappe.throw(frappe._("Seleccione un cargo de origen para cada línea de una factura grupal"))
                    charge = insert("HS Charge", prop, stay=origin_stay, folio=folio_name, item=row.item_code,
                                    description=row.description, quantity=row.qty, rate=row.rate, amount=row.amount,
                                    currency=doc.currency, business_date=prop.business_date,
                                    kind=original.kind if original else ("Lodging" if row.item_code == prop.lodging_item else "Service"),
                                    quote_snapshot=original.quote_snapshot if original else "{}",status="Invoiced",
                                    sales_invoice=doc.name, invoice_item=row.name)
                    row.db_set("hs_charge", charge.name, update_modified=False)
                else:
                    sources=frappe.parse_json(row.get("hs_charge_sources") or "[]") or [charge.name]
                    for source in sources:
                        linked=locked_doc("HS Charge",source)
                        if linked.status == "Invoiced" and linked.sales_invoice != doc.name:
                            frappe.throw(frappe._("Este cargo ya se facturó en otro documento"))
                        if linked.status=='Scheduled':
                            linked.posted_at=now_datetime()
                        linked.status, linked.sales_invoice, linked.invoice_item = "Invoiced", doc.name, row.name
                        linked.save(ignore_permissions=True)
        if doc.doctype == "Sales Invoice" and doc.docstatus == 2:
            for name in current_all("HS Charge", filters={"sales_invoice": doc.name}, pluck="name"):
                charge = locked_doc("HS Charge", name)
                charge.status, charge.sales_invoice, charge.invoice_item = "Pending", None, None
                charge.save(ignore_permissions=True)
        if doc.doctype in ("Payment Entry","Journal Entry") and doc.docstatus == 2:
            field="payment_entry" if doc.doctype=="Payment Entry" else "journal_entry"
            for name in current_all("HS Payment", filters={field: doc.name}, pluck="name"):
                payment_doc = locked_doc("HS Payment", name)
                payment_doc.status = "Cancelled"
                payment_doc.save(ignore_permissions=True)
            if doc.doctype == "Journal Entry":
                for name in current_all("HS Treasury Movement", filters={"journal_entry": doc.name}, pluck="name"):
                    movement = locked_doc("HS Treasury Movement", name)
                    movement.status = "Cancelled"
                    movement.save(ignore_permissions=True)
                    if movement.kind == "Replenishment" and movement.rendition:
                        rendition = locked_doc("HS Petty Cash Rendition", movement.rendition)
                        total = sum(decimal(r.amount) for r in current_all("HS Treasury Movement", filters={"rendition": rendition.name, "kind": "Replenishment", "status": "Posted"}, fields=["amount"]))
                        rendition.status = "Approved" if total == 0 else "Partially Reimbursed"
                        rendition.save(ignore_permissions=True)
                for name in current_all("HS Petty Cash Expense", filters={"journal_entry": doc.name}, pluck="name"):
                    expense = locked_doc("HS Petty Cash Expense", name)
                    expense.status = "Cancelled"
                    expense.save(ignore_permissions=True)
                for name in current_all("HS Petty Cash Rendition", filters={"variance_journal": doc.name}, pluck="name"):
                    rendition = locked_doc("HS Petty Cash Rendition", name)
                    rendition.status = "Returned"
                    rendition.variance_journal = None
                    rendition.variance_account = None
                    rendition.save(ignore_permissions=True)
        if doc.doctype == "Payment Entry" and doc.party_type in ("Customer","Supplier") and doc.docstatus == 1 and not frappe.db.exists("HS Payment", {"payment_entry": doc.name}) and not getattr(frappe.local, "hs_posting", False):
            account = doc.paid_to if doc.payment_type == "Receive" else doc.paid_from
            method_filters={"property":prop.name,"account":account}
            if doc.mode_of_payment:
                method_filters["mode_of_payment"]=doc.mode_of_payment
            methods=current_all("HS Payment Method",filters=method_filters,pluck="name")
            if doc.party_type=="Supplier" and not methods and not doc.get("hs_shift"):
                audit(prop,"Supplier payment outside front-desk accounts",doc)
                return
            method_name=methods[0] if len(methods)==1 else None
            if not doc.get("hs_shift") or not method_name:
                frappe.throw(frappe._("Asigne turno abierto y un medio de pago inequívoco de este establecimiento"))
            method_doc = locked_doc("HS Payment Method", method_name)
            if doc.party_type=="Supplier":
                from hospitality_suite.procurement import supplier as scoped_supplier
                scoped_supplier(prop,doc.party)
                if doc.payment_type!="Pay":
                    frappe.throw(frappe._("La devolución de proveedor requiere su flujo de devolución de compra"))
            insert("HS Payment", prop, stay=stay.name if stay else None, booking=doc.get("hs_booking") or (stay.booking if stay else None), folio=doc.get("hs_folio"), customer=doc.party if doc.party_type=="Customer" else None,
                   supplier=doc.party if doc.party_type=="Supplier" else None,
                   purchase_invoice=next((r.reference_name for r in doc.references if r.reference_doctype=="Purchase Invoice"),None) if doc.party_type=="Supplier" else None,
                   shift=doc.hs_shift, method=method_name, currency=method_doc.currency,
                   amount=doc.received_amount if doc.payment_type == "Receive" else doc.paid_amount,
                   base_amount=doc.base_received_amount if doc.payment_type == "Receive" else doc.base_paid_amount,
                   exchange_rate=doc.target_exchange_rate if doc.payment_type == "Receive" else doc.source_exchange_rate,
                   kind="Supplier Payment" if doc.party_type=="Supplier" else ("Payment" if doc.references else "Advance") if doc.payment_type == "Receive" else "Refund",
                   status="Posted", payment_entry=doc.name, reference=doc.reference_no, reason=doc.remarks)
        audit(prop, method or "ERP update", stay or doc, doc.get("hs_correction_reason"),details={"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus,"payment_policy":doc.flags.get("hs_payment_policy") or {}},values_doc=doc)
    from hospitality_suite.security import realtime
    realtime(prop.name)
