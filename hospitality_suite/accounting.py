from hospitality_suite.service import current_all, locked_doc
"""ERPNext is the sole accounting system. All postings use standard controllers."""
from decimal import Decimal

import frappe
from frappe.utils import nowdate, now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, operation


def ready(prop):
    from hospitality_suite.install import validate_financial_configuration
    if not prop.financial_enabled:
        frappe.throw("Habilite y valide la configuración financiera")
    validate_financial_configuration(prop)


def post_standard(doc, prop):
    """Delegated, narrowly scoped integration: validated PMS action may post its own
    ERP document without granting operational users general accounting privileges.
    No caller supplies arbitrary account lines or a doctype to this helper.
    """
    doc.hs_property = prop.name
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
    return dict(pending=str(money(pending)), outstanding=str(money(outstanding + pending)), currency=folio.currency)


def folios_for_stay(stay):
    rows=current_all("HS Folio",filters={"stay":stay.name},fields=["*"])
    if stay.booking:
        rows+=current_all("HS Folio",filters={"property":stay.property,"booking":stay.booking,"stay":["is","not set"]},fields=["*"])
    return list({r.name:r for r in rows}.values())


def invoice_folio(prop, data):
    ready(prop)
    folio = document("HS Folio", data["folio"])
    charges = current_all("HS Charge", filters={"folio": folio.name, "status": "Pending"}, fields=["*"])
    if not charges:
        reconciled = reconcile_folio_advances(prop, folio)
        return dict(invoices=current_all("Sales Invoice", filters={"hs_folio":folio.name,"docstatus":1},pluck="name"),reconciled=reconciled)
    stay = locked_doc("HS Stay", folio.stay) if folio.stay else None
    booking_name=folio.booking or (stay.booking if stay else None)
    inv = frappe.new_doc("Sales Invoice")
    inv.flags.ignore_permissions=True
    inv.update(dict(company=prop.company, customer=folio.customer, posting_date=nowdate(), due_date=nowdate(),
                    currency=folio.currency, debit_to=prop.receivable_account, cost_center=prop.cost_center,
                    hs_stay=stay.name if stay else None,hs_booking=booking_name, hs_folio=folio.name, update_stock=0, taxes_and_charges=prop.tax_template))
    mapping = []
    for charge in charges:
        if charge.applies_to_charge:
            continue
        related=[charge]+[r for r in charges if r.applies_to_charge==charge.name]
        total=sum(decimal(r.amount) for r in related)
        if total<0 or decimal(charge.quantity)<=0:
            frappe.throw("El ajuste requiere una nota de crédito estándar sobre su factura de origen")
        rate=total/decimal(charge.quantity)
        row = inv.append("items", dict(item_code=charge.item, qty=charge.quantity, rate=float(rate),price_list_rate=charge.rate,
                                       discount_amount=float(decimal(charge.rate)-rate),
                                       description=charge.description, cost_center=prop.cost_center, hs_charge=charge.name,
                                       hs_charge_sources=frappe.as_json([r.name for r in related])))
        mapping.extend((r.name,row) for r in related)
    if len(mapping)!=len(charges):
        frappe.throw("Traslade el cargo y sus ajustes a la misma cuenta antes de facturar")
    inv.set_missing_values()
    if prop.tax_template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        inv.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", prop.tax_template))
    inv.calculate_taxes_and_totals()
    remaining = decimal(inv.grand_total)
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


def credit_note(prop, data):
    ready(prop)
    require(prop.name, "approve")
    inv = locked_doc("Sales Invoice", data["invoice"])
    if inv.hs_property != prop.name or inv.docstatus != 1 or inv.is_return or not data.get("reason"):
        frappe.throw("Seleccione una factura presentada de este establecimiento e indique el motivo")
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
    target=frappe.new_doc("Sales Invoice")
    target.flags.ignore_permissions=True
    credit = make_sales_return(inv.name,target_doc=target)
    selected = {r["invoice_item"]: decimal(r["quantity"]) for r in data.get("items", [])}
    if selected:
        kept = []
        for row in credit.items:
            if row.sales_invoice_item in selected:
                quantity = selected[row.sales_invoice_item]
                if quantity <= 0 or quantity > abs(decimal(row.qty)):
                    frappe.throw("Cantidad de devolución inválida")
                row.qty = -float(quantity)
                kept.append(row)
        if len(kept) != len(selected):
            frappe.throw("Línea de factura desconocida")
        credit.set("items", kept)
    credit.update(dict(hs_stay=inv.hs_stay,hs_booking=inv.hs_booking, hs_folio=inv.hs_folio, update_stock=0, remarks=data["reason"]))
    for row in credit.items:
        row.hs_charge = None
        row.hs_charge_sources=None
    post_standard(credit, prop)
    for row in credit.items:
        original = next((i for i in inv.items if i.name == row.sales_invoice_item), None)
        if original and abs(decimal(row.qty)) == decimal(original.qty):
            service_name = frappe.db.get_value("HS Service Request", {"charge": original.hs_charge}) if original.hs_charge else None
            if service_name:
                service = locked_doc("HS Service Request", service_name)
                service.credit_note = credit.name
                service.save()
    audit(prop, "Credit note", locked_doc("HS Folio",inv.hs_folio) if inv.hs_folio else inv, data["reason"], {"invoice": inv.name, "credit_note": credit.name})
    return dict(credit_note=credit.name, amount=credit.grand_total)


def apply_guarantee(prop, data):
    ready(prop)
    source = document("HS Payment", data["source_payment"], "approve")
    folio = document("HS Folio", data["folio"], "approve")
    matches=source.stay==folio.stay if folio.stay else source.booking==folio.booking
    if source.kind != "Guarantee" or source.status != "Posted" or not matches or source.customer != folio.customer or not data.get("reason"):
        frappe.throw("Garantía, pagador o motivo incompatible")
    used = sum(decimal(p.amount) for p in current_all("HS Payment", filters={"source_payment": source.name, "status":"Posted"}, fields=["amount"]))
    amount = money(data["amount"])
    if amount <= 0 or amount + used > decimal(source.amount):
        frappe.throw("El importe supera la garantía disponible")
    shifts=current_all("HS Shift",filters={"property":prop.name,"cashier":frappe.session.user,"status":"Open"},fields=["name"])
    shift=document("HS Shift",data.get("shift") or (shifts[0].name if shifts else ""),"approve")
    if shift.status!="Open":
        frappe.throw("Abra un turno para registrar la aplicación de garantía")
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
            frappe.throw("El porcentaje de penalización debe estar entre 0 y 100")
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
        frappe.throw("Configure el artículo de penalización antes de aplicar esta política")
    invoice=frappe.new_doc("Sales Invoice")
    invoice.flags.ignore_permissions=True
    invoice.update(dict(company=prop.company,customer=booking.customer,currency=booking.currency,posting_date=nowdate(),due_date=nowdate(),
                        debit_to=prop.receivable_account,cost_center=prop.cost_center,hs_booking=booking.name,update_stock=0,remarks=reason,
                        taxes_and_charges=prop.tax_template))
    invoice.append("items",dict(item_code=prop.penalty_item,qty=1,rate=float(decimal(fee["amount"])),cost_center=prop.cost_center,
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
        frappe.throw("Configure un tipo de cambio válido en ERPNext")
    return rate


def original_guarantee(source):
    doc=locked_doc("Journal Entry",source.journal_entry)
    if doc.docstatus!=1:
        frappe.throw("La garantía no tiene un documento contable vigente")
    rows=[r for r in doc.accounts if r.credit_in_account_currency>0 and frappe.db.get_value("Account",r.account,"root_type")=="Liability"]
    if len(rows)!=1:
        frappe.throw("La garantía no conserva una línea de pasivo inequívoca")
    return rows[0]


def balance_exchange(journal,prop):
    debit=sum(decimal(r.debit_in_account_currency)*decimal(r.exchange_rate or 1) for r in journal.accounts)
    credit=sum(decimal(r.credit_in_account_currency)*decimal(r.exchange_rate or 1) for r in journal.accounts)
    difference=money(debit-credit)
    if not difference:
        return
    account=prop.get("exchange_gain_loss_account") or frappe.db.get_value("Company",prop.company,"exchange_gain_loss_account")
    if not account:
        frappe.throw("Configure una cuenta de ganancia/pérdida cambiaria para registrar esta devolución")
    details=locked_doc("Account",account)
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    if details.company!=prop.company or details.is_group or details.account_currency!=company_currency or details.root_type not in ("Income","Expense"):
        frappe.throw("Revise la cuenta de diferencia cambiaria")
    journal.append("accounts",dict(account=account,cost_center=prop.cost_center,exchange_rate=1,
                                    debit_in_account_currency=float(-difference) if difference<0 else 0,
                                    credit_in_account_currency=float(difference) if difference>0 else 0))


def payment(prop, data):
    ready(prop)
    shift = document("HS Shift", data["shift"], "finance")
    if shift.status != "Open":
        frappe.throw("El turno no está abierto")
    if shift.cashier != frappe.session.user:
        require(prop.name, "approve")
    method = document("HS Payment Method", data["method"], "finance")
    if method.reference_required and not data.get("reference"):
        frappe.throw("La referencia bancaria es obligatoria")
    amount = money(data["amount"])
    if amount <= 0:
        frappe.throw("El importe debe ser positivo")
    tendered=money(data.get("tendered") or amount)
    change=money(tendered-amount)
    if tendered<amount or (change and not method.is_cash):
        frappe.throw("Revise el efectivo recibido; el vuelto solo se permite en medios de efectivo")
    kind = data.get("kind", "Payment")
    if kind not in ("Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund"):
        frappe.throw("Tipo de movimiento inválido")
    source = None
    if kind in ("Refund", "Guarantee Refund"):
        require(prop.name, "approve")
        if not data.get("reason") or not data.get("source_payment"):
            frappe.throw("Indique el pago original y el motivo de devolución")
        source = document("HS Payment", data["source_payment"], "finance")
        expected = "Guarantee" if kind == "Guarantee Refund" else ("Advance", "Payment")
        if (source.kind != expected if isinstance(expected, str) else source.kind not in expected) or source.status != "Posted":
            frappe.throw("Origen de devolución inválido")
        if source.currency != method.currency:
            frappe.throw("Devuelva en la moneda del movimiento original")
        refunded = sum(decimal(p.amount) for p in current_all("HS Payment", filters={"source_payment": source.name, "status": "Posted"}, fields=["amount"]))
        if refunded + amount > decimal(source.amount):
            frappe.throw("La devolución supera el importe disponible")
        data = {**data, "stay": source.stay, "booking": source.booking, "customer": source.customer, "folio": source.folio}
    stay = document("HS Stay", data["stay"], "finance") if data.get("stay") else None
    booking = document("HS Booking", data["booking"], "finance") if data.get("booking") else None
    if kind in ("Advance","Guarantee") and ((stay and stay.status!="Active") or (booking and booking.status not in ("Hold","Confirmed","Checked In"))):
        frappe.throw("No reciba anticipos o garantías en una visita terminada o reserva cancelada")
    if stay and booking and stay.booking!=booking.name:
        frappe.throw("La estancia y la reserva no tienen el mismo origen")
    folio = document("HS Folio", data["folio"], "finance") if data.get("folio") else None
    if not stay and not booking:
        frappe.throw("El pago debe tener una estancia o reserva de origen")
    if folio:
        matches=(stay and folio.stay==stay.name) if folio.stay else folio.booking==(booking.name if booking else stay.booking if stay else None)
        if not matches:
            frappe.throw("La cuenta no corresponde a la estancia o grupo")
    customer = folio.customer if folio else (source.customer if source else (stay.customer if stay else booking.customer))
    company_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    fx = exchange(method.currency, company_currency)
    property_fx = exchange(prop.currency, company_currency)
    if data.get("fx_acceptance") and data["fx_acceptance"]!=payment_quote(prop,data)["acceptance"]:
        frappe.throw("El tipo de cambio cambió; revise el movimiento otra vez")
    party_amount = money(amount * fx / property_fx)
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
    elif source and source.kind == "Advance":
        # ERPNext 16.51.1 validates customer references on Payment Entry as invoice
        # fields, so use a standard party Journal Entry and reconcile the original
        # advance through ERPNext's supported reconciliation controller.
        original = locked_doc("Payment Entry", source.payment_entry)
        if party_amount > decimal(original.unallocated_amount):
            frappe.throw("El anticipo ya está aplicado; use una nota de crédito")
        journal = frappe.new_doc("Journal Entry")
        journal.update(dict(company=prop.company,posting_date=nowdate(),voucher_type="Journal Entry",multi_currency=1,
                            hs_stay=stay.name if stay else None,hs_shift=shift.name,hs_folio=folio.name if folio else None,user_remark=data["reason"]))
        journal.append("accounts",dict(account=prop.receivable_account,party_type="Customer",party=customer,
                                       debit_in_account_currency=float(party_amount),exchange_rate=float(property_fx),cost_center=prop.cost_center))
        journal.append("accounts",dict(account=method.account,credit_in_account_currency=float(amount),exchange_rate=float(fx),cost_center=prop.cost_center))
        post_standard(journal,prop)
        from erpnext.accounts.utils import reconcile_against_document
        reconcile_against_document([frappe._dict(voucher_type="Payment Entry",voucher_no=original.name,voucher_detail_no=None,
                                                against_voucher_type="Journal Entry",against_voucher=journal.name,
                                                account=prop.receivable_account,party_type="Customer",party=customer,
                                                exchange_rate=float(property_fx),is_advance="Yes",dr_or_cr="credit_in_account_currency",
                                                unadjusted_amount=original.unallocated_amount,unreconciled_amount=original.unallocated_amount,
                                                allocated_amount=float(party_amount),difference_amount=0,cost_center=prop.cost_center)])
        pe = None
    else:
        invoice = None
        if kind == "Payment":
            if not folio:
                frappe.throw("Seleccione la cuenta de estancia a cobrar")
            invoice_folio(prop, {"folio": folio.name})
            names = set(current_all("HS Charge", filters={"folio": folio.name, "status": "Invoiced"}, pluck="sales_invoice"))
            invoices = [locked_doc("Sales Invoice", n) for n in names if n]
            if party_amount > sum(decimal(inv.outstanding_amount) for inv in invoices):
                frappe.throw("El cobro supera el saldo; registre un anticipo separado si corresponde")
        elif source and source.kind == "Advance":
            unallocated = decimal(frappe.db.get_value("Payment Entry", source.payment_entry, "unallocated_amount"))
            if party_amount > unallocated:
                frappe.throw("El anticipo ya está aplicado; use nota de crédito y devolución contra factura")
        elif source and source.kind == "Payment":
            if not data.get("credit_note"):
                frappe.throw("Seleccione la nota de crédito para devolver un pago facturado")
            refund_invoice=locked_doc("Sales Invoice",data["credit_note"])
            original=locked_doc("Payment Entry",source.payment_entry)
            if refund_invoice.docstatus!=1 or not refund_invoice.is_return or refund_invoice.hs_property!=prop.name or refund_invoice.customer!=customer:
                frappe.throw("La nota de crédito no corresponde al pagador y establecimiento")
            if refund_invoice.return_against not in [r.reference_name for r in original.references if r.reference_doctype=="Sales Invoice"]:
                frappe.throw("La nota de crédito no corresponde a una factura del pago original")
            if party_amount>abs(min(decimal(0),decimal(refund_invoice.outstanding_amount))):
                frappe.throw("La devolución supera el crédito disponible")
        pe = frappe.new_doc("Payment Entry")
        pe.update(dict(company=prop.company, payment_type="Pay" if is_refund else "Receive", posting_date=nowdate(),
                       party_type="Customer", party=customer, mode_of_payment=method.mode_of_payment,
                       paid_from=method.account if is_refund else prop.receivable_account,
                       paid_to=prop.receivable_account if is_refund else method.account,
                       paid_amount=float(amount if is_refund else party_amount), received_amount=float(party_amount if is_refund else amount),
                       source_exchange_rate=float(fx if is_refund else property_fx), target_exchange_rate=float(property_fx if is_refund else fx),
                       reference_no=data.get("reference") or f"HS-{shift.name}", reference_date=nowdate(), cost_center=prop.cost_center,
                       hs_stay=stay.name if stay else None, hs_shift=shift.name, hs_folio=folio.name if folio else None, hs_booking=booking.name if booking else None))
        if kind == "Payment":
            remaining = party_amount
            for invoice in invoices:
                allocation = min(remaining, decimal(invoice.outstanding_amount))
                if allocation > 0:
                    pe.append("references", dict(reference_doctype="Sales Invoice", reference_name=invoice.name, allocated_amount=float(allocation)))
                    remaining -= allocation
        elif source and source.kind=="Payment":
            pe.append("references",dict(reference_doctype="Sales Invoice",reference_name=refund_invoice.name,allocated_amount=-float(party_amount)))
        post_standard(pe, prop)
        journal = None
    record = insert("HS Payment", prop, stay=stay.name if stay else None, booking=booking.name if booking else (stay.booking if stay else None),
                    folio=folio.name if folio else None, customer=customer, shift=shift.name, method=method.name, amount=amount,
                    currency=method.currency, exchange_rate=fx, base_amount=money(amount * fx), kind=kind, status="Posted",
                    payment_entry=pe.name if pe else None, journal_entry=journal.name if journal else None,
                    source_payment=source.name if source else None, reference=data.get("reference"), reason=data.get("reason"),tendered=tendered,change_amount=change)
    audit(prop, kind, record, data.get("reason"))
    return dict(payment=record.name, payment_entry=record.payment_entry, journal_entry=record.journal_entry, amount=str(amount), currency=method.currency,
                tendered=str(tendered),change=str(change),exchange_rate=str(fx),base_amount=str(record.base_amount))


def payment_quote(prop,data):
    import hashlib
    from hospitality_suite.service import canonical
    method=document("HS Payment Method",data["method"],"finance")
    amount=money(data["amount"])
    tendered=money(data.get("tendered") or amount)
    if amount<=0 or tendered<amount or (tendered!=amount and not method.is_cash):
        frappe.throw("Revise el importe y el efectivo recibido")
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    fx=exchange(method.currency,company_currency)
    property_fx=exchange(prop.currency,company_currency)
    values=dict(amount=str(amount),currency=method.currency,exchange_rate=str(fx),base_amount=str(money(amount*fx)),
                base_currency=company_currency,property_amount=str(money(amount*fx/property_fx)),property_currency=prop.currency,
                tendered=str(tendered),change=str(money(tendered-amount)),method=method.name)
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
            frappe.throw("Compañía o pagador incompatible con la estancia")
    from hospitality_suite.service import lock_property
    lock_property(prop.name)
    with operation():
        if (stay or doc.get("hs_folio")) and doc.doctype == "Sales Invoice" and doc.docstatus == 1:
            folio_name = doc.get("hs_folio")
            if not folio_name and stay:
                candidates=[r for r in folios_for_stay(stay) if r.customer==doc.customer]
                if len(candidates)==1:
                    folio_name=candidates[0].name
            if not folio_name:
                frappe.throw("Asigne una cuenta de estancia al cliente de la factura")
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
                        frappe.throw("Seleccione un cargo de origen para cada línea de una factura grupal")
                    charge = insert("HS Charge", prop, stay=origin_stay, folio=folio_name, item=row.item_code,
                                    description=row.description, quantity=row.qty, rate=row.rate, amount=row.amount,
                                    currency=doc.currency, business_date=prop.business_date,
                                    kind=original.kind if original else ("Lodging" if row.item_code == prop.lodging_item else "Service"),
                                    quote_snapshot=original.quote_snapshot if original else "{}",status="Invoiced",
                                    sales_invoice=doc.name, invoice_item=row.name)
                    row.db_set("hs_charge", charge.name, update_modified=False)
                else:
                    if charge.status == "Invoiced" and charge.sales_invoice != doc.name:
                        frappe.throw("Este cargo ya se facturó en otro documento")
                    charge.status, charge.sales_invoice, charge.invoice_item = "Invoiced", doc.name, row.name
                    charge.save(ignore_permissions=True)
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
        if (stay or doc.get("hs_booking")) and doc.doctype == "Payment Entry" and doc.docstatus == 1 and not frappe.db.exists("HS Payment", {"payment_entry": doc.name}) and not getattr(frappe.local, "hs_posting", False):
            account = doc.paid_to if doc.payment_type == "Receive" else doc.paid_from
            method_name = frappe.db.get_value("HS Payment Method", {"property": prop.name, "account": account})
            if not doc.get("hs_shift") or not method_name:
                frappe.throw("Asigne turno abierto y medio de pago configurado al cobro de estancia")
            method_doc = locked_doc("HS Payment Method", method_name)
            insert("HS Payment", prop, stay=stay.name if stay else None, booking=doc.get("hs_booking") or (stay.booking if stay else None), folio=doc.get("hs_folio"), customer=doc.party,
                   shift=doc.hs_shift, method=method_name, currency=method_doc.currency,
                   amount=doc.received_amount if doc.payment_type == "Receive" else doc.paid_amount,
                   base_amount=doc.base_received_amount if doc.payment_type == "Receive" else doc.base_paid_amount,
                   exchange_rate=doc.target_exchange_rate if doc.payment_type == "Receive" else doc.source_exchange_rate,
                   kind=("Payment" if doc.references else "Advance") if doc.payment_type == "Receive" else "Refund",
                   status="Posted", payment_entry=doc.name, reference=doc.reference_no, reason=doc.remarks)
        audit(prop, method or "ERP update", stay or doc, doc.get("hs_correction_reason"),details={"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus})
    from hospitality_suite.security import realtime
    realtime(prop.name)
