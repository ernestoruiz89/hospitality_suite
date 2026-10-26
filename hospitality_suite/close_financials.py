"""Captured financial totals with explicit periods, currencies and native sources."""
from collections import defaultdict
from decimal import Decimal

import frappe
from frappe.utils import getdate

from hospitality_suite.pricing import decimal,money,currency_precision
from hospitality_suite.service import current_all


METRICS=("production","cutover_opening_receivables","invoices_net","invoices_tax","invoices_total","credit_notes_total","rounding_adjustment",
         "payable_billed","payments","advances","guarantees","refunds","guarantee_refunds","guarantees_applied","pos_collections","pos_refunds",
         "net_customer_receipts","pending_charges","scheduled_charges","receivables","customer_credits","unallocated_advances","guarantees_held",
         "petty_initial","petty_replenishment","petty_expenses","petty_overage","petty_shortage",
         "other_income","loans_received","loans_repaid","capital_contributed","capital_withdrawn",
         "treasury_cash_in","treasury_cash_out","treasury_bank_in","treasury_bank_out")

GROUPS=(
    ("Producción operativa",(("production","Importe de cargos y ventas registrados"),)),
    ("Apertura contable del corte",(("cutover_opening_receivables","Cartera PMS trasladada, separada de ventas"),)),
    ("Facturación por fecha contable",(("invoices_net","Neto sin impuestos"),("invoices_tax","Impuestos"),("invoices_total","Total con impuestos"),
        ("credit_notes_total","Notas de crédito, ya restadas del total"),("rounding_adjustment","Ajuste de redondeo"),("payable_billed","Total exigible con redondeo"))),
    ("Movimientos de clientes por fecha operativa",(("payments","Cobros de facturas"),("advances","Anticipos recibidos"),("guarantees","Garantías recibidas"),
        ("refunds","Devoluciones de cobros y anticipos"),("guarantee_refunds","Garantías devueltas"),("pos_collections","Cobros POS nativos, netos de vuelto"),("pos_refunds","Devoluciones POS nativas"),("net_customer_receipts","Dinero recibido de clientes, neto de devoluciones"),
        ("guarantees_applied","Garantías aplicadas, sin nuevo ingreso de dinero"))),
    ("Caja Chica por fecha operativa",(("petty_initial","Fondo inicial entregado"),("petty_replenishment","Reposiciones entregadas"),
        ("petty_expenses","Desembolsos contabilizados"),("petty_overage","Sobrantes aprobados"),("petty_shortage","Faltantes aprobados"))),
    ("Otros movimientos, separados de ventas y cobros",(("other_income","Otros ingresos sin factura"),
        ("loans_received","Préstamos recibidos"),("loans_repaid","Principal de préstamos devuelto"),
        ("capital_contributed","Aportes de capital"),("capital_withdrawn","Retiros de capital"),
        ("treasury_cash_in","Entradas de efectivo"),("treasury_cash_out","Salidas de efectivo"),
        ("treasury_bank_in","Entradas bancarias"),("treasury_bank_out","Salidas bancarias"))),
    ("Saldos capturados al ejecutar",(("pending_charges","Cargos pendientes de facturar"),("scheduled_charges","Alojamiento programado, aún sin generar"),("receivables","Facturas pendientes de cobro, en moneda de la cuenta"),
        ("customer_credits","Créditos pendientes a favor de clientes, en moneda de la cuenta"),("unallocated_advances","Anticipos por aplicar, en moneda de la cuenta"),("guarantees_held","Garantías disponibles, en moneda original")))
)


def display_groups():
    return [dict(title=frappe._(title),metrics=[dict(key=key,label=frappe._(label)) for key,label in items]) for title,items in GROUPS]


def snapshot(prop,operational):
    day=getdate(prop.business_date)
    totals=defaultdict(lambda:{key:decimal(0) for key in METRICS})
    sources=dict(invoices=[],cutover_opening_invoices=[],movements=[],native_pos=[],pending_charges=[],scheduled_charges=[],receivables=[],unallocated_advances=[],guarantees=[],
                 petty_expenses=[],petty_variances=[],treasury_movements=[],unattributed_movements=[])
    from hospitality_suite.reconciliation import cutover_history, historical_pms_payment
    cutover_recorded, opening_vouchers = cutover_history(prop)
    for currency,amount in operational.get("production_by_currency",{}).items():
        totals[currency]["production"]=decimal(amount)
    invoices=current_all("Sales Invoice",filters={"hs_property":prop.name,"company":prop.company,"docstatus":1},
                         fields=["name","posting_date","currency","party_account_currency","debit_to","net_total","total_taxes_and_charges","grand_total","rounded_total","rounding_adjustment","disable_rounded_total","outstanding_amount","is_return","is_pos"])
    for row in invoices:
        current=totals[row.currency]
        if getdate(row.posting_date)==day:
            if ("Sales Invoice", row.name) in opening_vouchers:
                current["cutover_opening_receivables"]+=decimal(row.grand_total)
                sources["cutover_opening_invoices"].append(dict(row))
            else:
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
            if isinstance(detail,dict) and detail.get("doctype") in ('Sales Invoice','Journal Entry','Payment Entry') and detail.get("docstatus")==1:
                submissions.setdefault((detail.get('doctype'),detail.get("name")),event.business_date)
        from hospitality_suite.native_pos import movements
        for movement in movements(prop.name):
            name,currency,amount=movement["name"],movement["currency"],movement["amount"]
            date=submissions.get((movement['doctype'],name))
            record=dict(name=name,doctype=movement['doctype'],account=movement["account"],currency=currency,net=str(amount),business_date=str(date) if date else None)
            if not record["business_date"]:
                sources["unattributed_movements"].append(record)
            elif getdate(record["business_date"])==day:
                totals[currency]["pos_collections" if amount>0 else "pos_refunds"]+=abs(amount)
                sources["native_pos"].append(record)
    for row in current_all("HS Charge",filters={"property":prop.name,"status":"Pending"},fields=["name","currency","amount","folio"]):
        totals[row.currency]["pending_charges"]+=decimal(row.amount)
        sources["pending_charges"].append(dict(row))
    for row in current_all('HS Charge',filters={'property':prop.name,'status':'Scheduled'},fields=['name','currency','amount','folio','service_date']):
        totals[row.currency]['scheduled_charges']+=decimal(row.amount)
        sources['scheduled_charges'].append(dict(row))
    kinds={"Payment":"payments","Advance":"advances","Guarantee":"guarantees","Refund":"refunds","Guarantee Refund":"guarantee_refunds","Guarantee Applied":"guarantees_applied"}
    movements=current_all("HS Payment",filters={"property":prop.name,"status":"Posted"},
                           fields=["name","property","kind","currency","amount","business_date","business_date_source","payment_entry","journal_entry","pms_journal","source_payment"])
    for row in movements:
        if historical_pms_payment(prop, row, opening_vouchers, cutover_recorded):
            continue
        if not row.business_date:
            sources["unattributed_movements"].append(dict(row))
        elif getdate(row.business_date)==day and row.kind in kinds:
            totals[row.currency][kinds[row.kind]]+=decimal(row.amount)
            sources["movements"].append(dict(row))
    for row in movements:
        if row.kind=="Guarantee":
            from hospitality_suite.accounting import guarantee_balance
            held=guarantee_balance(prop,frappe.get_doc("HS Payment",row.name)).nominal
            if held:
                totals[row.currency]["guarantees_held"]+=held
                sources["guarantees"].append(dict(source=row.name,currency=row.currency,available=str(held),journal_entry=row.journal_entry))
    petty_keys={"Initial Fund":"petty_initial","Replenishment":"petty_replenishment","Other Income":"other_income",
                "Loan Received":"loans_received","Loan Repayment":"loans_repaid","Capital Contribution":"capital_contributed",
                "Capital Withdrawal":"capital_withdrawn"}
    for row in current_all("HS Treasury Movement", filters={"property":prop.name,"status":"Posted"}, fields=["name","kind","concept","concept_label","source_movement","rendition","cash_account","counter_account","currency","amount","business_date","shift","journal_entry"]):
        if not row.business_date:
            sources["unattributed_movements"].append(dict(row))
        elif getdate(row.business_date)==day:
            amount=decimal(row.amount)
            totals[row.currency][petty_keys[row.kind]]+=amount
            if row.kind not in ("Initial Fund","Replenishment"):
                channel="cash" if row.shift else "bank"
                direction="in" if row.kind in ("Other Income","Loan Received","Capital Contribution") else "out"
                totals[row.currency][f"treasury_{channel}_{direction}"]+=amount
            sources["treasury_movements"].append(dict(row,property=prop.name))
    for row in current_all("HS Petty Cash Expense",filters={"property":prop.name,"status":"Posted"},
                           fields=["name","category","category_label","beneficiary","concept","receipt_reference","expense_account","petty_account","currency","amount","business_date","journal_entry","rendition"]):
        if row.business_date and getdate(row.business_date)==day:
            totals[row.currency]["petty_expenses"]+=decimal(row.amount)
            sources["petty_expenses"].append(dict(row,property=prop.name))
    for row in current_all("HS Petty Cash Rendition",filters={"property":prop.name,"status":["in",["Approved","Partially Reimbursed","Reimbursed"]]},
                           fields=["name","variance","variance_account","variance_journal","currency","approved_business_date","responsible"]):
        if row.variance_journal and row.approved_business_date and getdate(row.approved_business_date)==day:
            key="petty_overage" if decimal(row.variance)>0 else "petty_shortage"
            totals[row.currency][key]+=abs(decimal(row.variance))
            sources["petty_variances"].append(dict(row,property=prop.name))
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
    treasury_breakdown=defaultdict(lambda:Decimal(0))
    petty_breakdown=defaultdict(lambda:Decimal(0))
    for row in sources["treasury_movements"]:
        key=(row["property"],row["kind"],row.get("concept_label") or "",row["counter_account"],row["cash_account"],row["currency"],"Cash" if row["shift"] else "Bank" if row["cash_account"] else "Petty Cash")
        treasury_breakdown[key]+=decimal(row["amount"])
    for row in sources["petty_expenses"]:
        key=(row["property"],row["category"],row.get("category_label") or "",row["expense_account"],row["petty_account"],row["currency"])
        petty_breakdown[key]+=decimal(row["amount"])
    breakdown=dict(
        treasury=[dict(property=k[0],kind=k[1],concept=k[2],counter_account=k[3],cash_account=k[4],currency=k[5],channel=k[6],amount=str(money(v,currency=k[5]))) for k,v in sorted(treasury_breakdown.items())],
        petty_expenses=[dict(property=k[0],category=k[1],category_label=k[2],expense_account=k[3],petty_account=k[4],currency=k[5],amount=str(money(v,currency=k[5]))) for k,v in sorted(petty_breakdown.items())])
    from hospitality_suite.time import now_local
    return dict(version=2,property=prop.name,captured_at=now_local(prop).isoformat(),business_date=str(day),posting_date=str(day),
                movement_basis="HS Payment.business_date; native POS: immutable on_submit audit business_date",invoice_basis="Sales Invoice.posting_date",balance_basis="Outstanding amounts captured at execution, all posting dates",
                currencies=currencies,sources=sources,breakdown=breakdown)
