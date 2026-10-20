"""Captured financial totals with explicit periods, currencies and native sources."""
from collections import defaultdict

import frappe
from frappe.utils import getdate

from hospitality_suite.pricing import decimal,money,currency_precision
from hospitality_suite.service import current_all


METRICS=("production","invoices_net","invoices_tax","invoices_total","credit_notes_total","rounding_adjustment",
         "payable_billed","payments","advances","guarantees","refunds","guarantee_refunds","guarantees_applied","pos_collections","pos_refunds",
         "net_customer_receipts","pending_charges","receivables","customer_credits","unallocated_advances","guarantees_held")

GROUPS=(
    ("Producción operativa",(("production","Importe de cargos y ventas registrados"),)),
    ("Facturación por fecha contable",(("invoices_net","Neto sin impuestos"),("invoices_tax","Impuestos"),("invoices_total","Total con impuestos"),
        ("credit_notes_total","Notas de crédito, ya restadas del total"),("rounding_adjustment","Ajuste de redondeo"),("payable_billed","Total exigible con redondeo"))),
    ("Movimientos de clientes por fecha operativa",(("payments","Cobros de facturas"),("advances","Anticipos recibidos"),("guarantees","Garantías recibidas"),
        ("refunds","Devoluciones de cobros y anticipos"),("guarantee_refunds","Garantías devueltas"),("pos_collections","Cobros POS nativos, netos de vuelto"),("pos_refunds","Devoluciones POS nativas"),("net_customer_receipts","Dinero recibido de clientes, neto de devoluciones"),
        ("guarantees_applied","Garantías aplicadas, sin nuevo ingreso de dinero"))),
    ("Saldos capturados al ejecutar",(("pending_charges","Cargos pendientes de facturar"),("receivables","Facturas pendientes de cobro, en moneda de la cuenta"),
        ("customer_credits","Créditos pendientes a favor de clientes, en moneda de la cuenta"),("unallocated_advances","Anticipos por aplicar, en moneda de la cuenta"),("guarantees_held","Garantías disponibles, en moneda original")))
)


def display_groups():
    return [dict(title=frappe._(title),metrics=[dict(key=key,label=frappe._(label)) for key,label in items]) for title,items in GROUPS]


def snapshot(prop,operational):
    day=getdate(prop.business_date)
    totals=defaultdict(lambda:{key:decimal(0) for key in METRICS})
    sources=dict(invoices=[],movements=[],native_pos=[],pending_charges=[],receivables=[],unallocated_advances=[],guarantees=[],unattributed_movements=[])
    for currency,amount in operational.get("production_by_currency",{}).items():
        totals[currency]["production"]=decimal(amount)
    invoices=current_all("Sales Invoice",filters={"hs_property":prop.name,"company":prop.company,"docstatus":1},
                         fields=["name","posting_date","currency","party_account_currency","debit_to","net_total","total_taxes_and_charges","grand_total","rounded_total","rounding_adjustment","disable_rounded_total","outstanding_amount","is_return","is_pos"])
    for row in invoices:
        current=totals[row.currency]
        if getdate(row.posting_date)==day:
            current["invoices_net"]+=decimal(row.net_total)
            current["invoices_tax"]+=decimal(row.total_taxes_and_charges)
            current["invoices_total"]+=decimal(row.grand_total)
            current["rounding_adjustment"]+=decimal(row.rounding_adjustment)
            current["payable_billed"]+=decimal(row.grand_total if row.disable_rounded_total or row.rounded_total is None else row.rounded_total)
            if row.is_return:
                current["credit_notes_total"]-=decimal(row.grand_total)
            sources["invoices"].append(dict(row))
        outstanding=decimal(row.outstanding_amount)
        if outstanding:
            # Native outstanding_amount is in receivable-account currency,
            # which may differ from the currency printed on the invoice.
            account_currency=row.party_account_currency or frappe.db.get_value("Account",row.debit_to,"account_currency")
            totals[account_currency]["receivables"]+=max(decimal(0),outstanding)
            totals[account_currency]["customer_credits"]+=max(decimal(0),-outstanding)
            sources["receivables"].append(dict(name=row.name,currency=account_currency,invoice_currency=row.currency,outstanding=str(outstanding)))
    # POS Sales Invoice posts its receipt directly to GL, without Payment Entry.
    # Read the actual payment-account net, including change, in account currency.
    pos={row.name:row for row in invoices if row.is_pos}
    if pos:
        submissions={}
        for event in current_all("HS Audit Event",filters={"property":prop.name,"action":"on_submit"},fields=["business_date","details"],order_by="occurred_at asc,name asc"):
            detail=frappe.parse_json(event.details or "{}")
            if isinstance(detail,dict) and detail.get("doctype")=="Sales Invoice" and detail.get("docstatus")==1:
                submissions.setdefault(detail.get("name"),event.business_date)
        from hospitality_suite.native_pos import movements
        for movement in movements(prop.name):
            name,currency,amount=movement["name"],movement["currency"],movement["amount"]
            record=dict(name=name,account=movement["account"],currency=currency,net=str(amount),business_date=str(submissions[name]) if submissions.get(name) else None)
            if not record["business_date"]:
                sources["unattributed_movements"].append(record)
            elif getdate(record["business_date"])==day:
                totals[currency]["pos_collections" if amount>0 else "pos_refunds"]+=abs(amount)
                sources["native_pos"].append(record)
    for row in current_all("HS Charge",filters={"property":prop.name,"status":"Pending"},fields=["name","currency","amount","folio"]):
        totals[row.currency]["pending_charges"]+=decimal(row.amount)
        sources["pending_charges"].append(dict(row))
    kinds={"Payment":"payments","Advance":"advances","Guarantee":"guarantees","Refund":"refunds","Guarantee Refund":"guarantee_refunds","Guarantee Applied":"guarantees_applied"}
    movements=current_all("HS Payment",filters={"property":prop.name,"status":"Posted"},
                           fields=["name","kind","currency","amount","business_date","business_date_source","payment_entry","journal_entry","source_payment"])
    used=defaultdict(lambda:decimal(0))
    for row in movements:
        if row.source_payment and row.kind in ("Guarantee Refund","Guarantee Applied"):
            used[row.source_payment]+=decimal(row.amount)
        if not row.business_date:
            sources["unattributed_movements"].append(dict(row))
        elif getdate(row.business_date)==day and row.kind in kinds:
            totals[row.currency][kinds[row.kind]]+=decimal(row.amount)
            sources["movements"].append(dict(row))
    for row in movements:
        if row.kind=="Guarantee":
            held=max(decimal(0),decimal(row.amount)-used[row.name])
            if held:
                totals[row.currency]["guarantees_held"]+=held
                sources["guarantees"].append(dict(source=row.name,currency=row.currency,available=str(held),journal_entry=row.journal_entry))
    advances=current_all("Payment Entry",filters={"hs_property":prop.name,"company":prop.company,"docstatus":1,"party_type":"Customer","payment_type":"Receive","unallocated_amount":[">",0]},
                         fields=["name","paid_from_account_currency","unallocated_amount"])
    for row in advances:
        currency=row.paid_from_account_currency or prop.currency
        totals[currency]["unallocated_advances"]+=decimal(row.unallocated_amount)
        sources["unallocated_advances"].append(dict(name=row.name,currency=currency,unallocated=str(row.unallocated_amount)))
    from hospitality_suite.refunds import original_funds
    for application in current_all('HS Payment',filters={'property':prop.name,'kind':'Guarantee Applied','status':'Posted'},fields=['*']):
        funds=original_funds(prop,application)
        if funds.unallocated>0:
            totals[funds.currency]['unallocated_advances']+=funds.unallocated
            sources['unallocated_advances'].append(dict(name=funds.doc.name,doctype='Journal Entry',currency=funds.currency,unallocated=str(funds.unallocated)))
    currencies=[]
    for currency,current in sorted(totals.items()):
        current["net_customer_receipts"]=current["payments"]+current["advances"]+current["guarantees"]+current["pos_collections"]-current["refunds"]-current["guarantee_refunds"]-current["pos_refunds"]
        currencies.append(dict(currency=currency,precision=currency_precision(currency),**{key:str(money(value,currency=currency)) for key,value in current.items()}))
    for records in sources.values():
        records.sort(key=lambda r:(r.get("name") or r.get("source") or "",r.get("currency") or "",r.get("account") or ""))
    from hospitality_suite.time import now_local
    return dict(version=1,captured_at=now_local(prop).isoformat(),business_date=str(day),posting_date=str(day),
                movement_basis="HS Payment.business_date; native POS: immutable on_submit audit business_date",invoice_basis="Sales Invoice.posting_date",balance_basis="Outstanding amounts captured at execution, all posting dates",
                currencies=currencies,sources=sources)
