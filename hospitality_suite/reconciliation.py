"""Read-only cross-checks against submitted ERPNext documents, down to origin."""
import frappe

from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import require
from hospitality_suite.service import current_all,locked_doc


def unmatched_cash(prop,shift=None):
    """Internal reconciliation used by authorized reporting and shift commands.

    A tagged native voucher touching a configured cash/bank account must have an
    operational payment, including vouchers entered through standard ERP forms.
    """
    methods=current_all("HS Payment Method",filters={"property":prop.name},fields=["account","currency"])
    accounts={m.account:m.currency for m in methods}
    result=[]
    for dt,field in (("Payment Entry","payment_entry"),("Journal Entry","journal_entry")):
        filters={"hs_property":prop.name,"docstatus":1}
        if shift:
            filters["hs_shift"]=shift
        for name in current_all(dt,filters=filters,pluck="name"):
            if current_all("HS Payment",filters={field:name,"status":"Posted"},pluck="name"):
                continue
            native=locked_doc(dt,name)
            movements={}
            if dt=="Payment Entry":
                for account,value in ((native.paid_to,native.received_amount),(native.paid_from,native.paid_amount)):
                    if account in accounts:
                        movements[account]=decimal(value)
            else:
                for row in native.accounts:
                    if row.account in accounts:
                        movements[row.account]=movements.get(row.account,decimal(0))+abs(decimal(row.debit_in_account_currency)-decimal(row.credit_in_account_currency))
            for account,amount in movements.items():
                if amount:
                    result.append(dict(name=name,doctype=dt,account=account,amount=amount,currency=accounts[account],shift=native.hs_shift,creation=native.creation))
    return result


def rows(prop,filters=None,limit=1000):
    require(prop.name,"report")
    filters=filters or {}
    result=[]
    def record(kind,name,origin,expected,actual,currency,detail):
        difference=money(decimal(actual)-decimal(expected))
        result.append(dict(type=kind,source=name,erp_document=origin or "—",expected=str(money(expected)),actual=str(money(actual)),
                           difference=str(difference),currency=currency,status="Difference" if difference else "OK",detail=detail))
    def selected(row,date_field="creation"):
        date=str(row.get(date_field) or "")[:10]
        return (not filters.get("from_date") or date>=filters["from_date"]) and (not filters.get("to_date") or date<=filters["to_date"]) and (not filters.get("shift") or row.get("shift")==filters["shift"])
    charges=current_all("HS Charge",filters={"property":prop.name,"status":"Invoiced"},fields=["*"])
    seen=set()
    for charge in charges:
        if not selected(charge,"business_date"):
            continue
        key=(charge.sales_invoice,charge.invoice_item)
        if key in seen:
            continue
        seen.add(key)
        peers=[r for r in charges if (r.sales_invoice,r.invoice_item)==key]
        expected=sum(decimal(r.amount) for r in peers)
        inv=locked_doc("Sales Invoice",charge.sales_invoice) if charge.sales_invoice and frappe.db.exists("Sales Invoice",charge.sales_invoice) else None
        item=next((i for i in inv.items if i.name==charge.invoice_item and i.hs_charge in [r.name for r in peers]),None) if inv else None
        actual=decimal(item.amount) if item and inv.docstatus==1 and inv.hs_property==prop.name and inv.currency==charge.currency else decimal(0)
        record("Charge",", ".join(r.name for r in peers),charge.sales_invoice,expected,actual,charge.currency,"Verificación de línea y ajustes de factura")
    for payment in current_all("HS Payment",filters={"property":prop.name,"status":"Posted"},fields=["*"]):
        if not selected(payment):
            continue
        dt="Payment Entry" if payment.payment_entry else "Journal Entry"
        name=payment.payment_entry or payment.journal_entry
        native=locked_doc(dt,name) if name and frappe.db.exists(dt,name) else None
        actual=decimal(0)
        if native and native.docstatus==1 and native.hs_property==prop.name and native.hs_shift==payment.shift:
            if dt=="Payment Entry":
                actual=decimal(native.received_amount if native.payment_type=="Receive" else native.paid_amount)
            elif payment.kind=="Guarantee Applied":
                # This is a liability transfer, with no second cash movement.
                original=locked_doc("HS Payment",payment.source_payment)
                source=locked_doc("Journal Entry",original.journal_entry)
                liability=next((r for r in source.accounts if r.credit_in_account_currency>0 and frappe.db.get_value("Account",r.account,"root_type")=="Liability"),None)
                transferred=sum(decimal(r.debit_in_account_currency) for r in native.accounts if liability and r.account==liability.account)
                actual=transferred*decimal(original.amount)/decimal(liability.credit_in_account_currency) if liability else decimal(0)
            else:
                account=frappe.db.get_value("HS Payment Method",payment.method,"account")
                actual=abs(sum(decimal(r.debit_in_account_currency)-decimal(r.credit_in_account_currency) for r in native.accounts if r.account==account))
        record("Payment",payment.name,name,payment.amount,actual,payment.currency,"Verificación de importe, documento y turno")
        if payment.kind=="Settlement":
            policy=frappe.parse_json(payment.fee_snapshot or "{}")
            base_currency=frappe.db.get_value("Company",prop.company,"default_currency")
            valid=native and native.docstatus==1 and native.hs_property==prop.name and native.hs_shift==payment.shift
            def posted(account,base=False,credit=False):
                debit_field="debit" if base else "debit_in_account_currency"
                credit_field="credit" if base else "credit_in_account_currency"
                return sum((decimal(r.get(credit_field))-decimal(r.get(debit_field))) if credit else (decimal(r.get(debit_field))-decimal(r.get(credit_field))) for r in native.accounts if r.account==account) if valid else decimal(0)
            outgoing=payment.settlement_direction=="Pay"
            record("Settlement net",payment.name,name,payment.net_amount,posted(policy.get("settlement_account"),credit=outgoing),payment.currency,"Depósito o débito bancario neto de liquidación")
            record("Settlement fee",payment.name,name,money(decimal(payment.fee_amount)*decimal(payment.exchange_rate),currency=base_currency),posted(policy.get("fee_account"),base=True),base_currency,"Comisión contabilizada como gasto")
            record("Settlement withholding",payment.name,name,money(decimal(payment.withholding_amount)*decimal(payment.exchange_rate),currency=base_currency),posted(policy.get("withholding_account"),base=True),base_currency,"Retención contabilizada como activo")
            record("Settlement clearing",payment.name,name,payment.clearing_base_amount,posted(frappe.db.get_value("HS Payment Method",payment.method,"account"),base=True,credit=not outgoing),base_currency,"Liquidación de la valoración histórica del movimiento")
    for native in unmatched_cash(prop,filters.get("shift")):
        if selected(native):
            record("Untracked payment",native["name"],native["name"],0,native["amount"],native["currency"],"Movimiento nativo sin registro operativo: "+native["account"])
    for name in current_all("Sales Invoice",filters={"hs_property":prop.name,"hs_folio":["is","set"],"docstatus":1},pluck="name"):
        native=locked_doc("Sales Invoice",name)
        if not selected(native,"posting_date"):
            continue
        for item in native.items:
            mapped=[r for r in charges if r.sales_invoice==name and r.invoice_item==item.name]
            if not mapped:
                record("Untracked charge",item.name,name,0,item.amount,native.currency,"Línea de factura de cuenta sin cargo operativo")
    for shift in current_all("HS Shift",filters={"property":prop.name,"status":"Closed"},fields=["*"]):
        if not selected(shift) or (filters.get("shift") and shift.name!=filters["shift"]):
            continue
        from hospitality_suite.cashier import expected
        frozen=frappe.parse_json(shift.denominations or "{}").get("expected",{})
        current=expected(shift)
        for currency in set(frozen)|set(current):
            record("Closed shift",shift.name,None,frozen.get(currency,0),current.get(currency,0),currency,"Efectivo actual contra arqueo original")
    return result if limit is None else result[:limit]


def differences(prop):
    return [row for row in rows(prop,limit=None) if row["status"]=="Difference"]
