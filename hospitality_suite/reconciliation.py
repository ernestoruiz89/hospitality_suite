"""Read-only cross-checks against submitted ERPNext documents, down to origin."""
import frappe

from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import require
from hospitality_suite.service import current_all,locked_doc


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
