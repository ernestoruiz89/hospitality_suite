"""Cash expenses and card clearing use native journal controllers and snapshots."""
import hashlib

import frappe

from hospitality_suite.accounting import ready,post_standard,exchange
from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import document,require
from hospitality_suite.service import current_all,locked_doc,insert,audit,canonical

METHOD_FIELDS=("fee_percent","fee_fixed","fee_account","withholding_percent","withholding_account","settlement_account","refund_fee_percent","refund_fee_fixed")


def method_snapshot(method,refund=False):
    values={field:method.get(field) for field in METHOD_FIELDS}
    if refund:
        values.update(fee_percent=method.refund_fee_percent or 0,fee_fixed=method.refund_fee_fixed or 0,withholding_percent=0)
    return values


def validate_method(method):
    fee,withheld,fixed=decimal(method.fee_percent),decimal(method.withholding_percent),decimal(method.fee_fixed)
    refund_fee,refund_fixed=decimal(method.refund_fee_percent),decimal(method.refund_fee_fixed)
    if min(fee,withheld,fixed,refund_fee,refund_fixed)<0 or fee+withheld>100 or refund_fee>100 or (method.is_cash and (fee or withheld or fixed or refund_fee or refund_fixed)):
        frappe.throw(frappe._("Revise comisión/retención: importes no negativos, porcentajes totales hasta 100 y medio no efectivo"))
    company_currency=frappe.db.get_value("Company",method.company,"default_currency")
    for field,root in (("fee_account","Expense"),("withholding_account","Asset"),("settlement_account","Asset")):
        value=method.get(field)
        required=(field=="fee_account" and (fee or fixed or refund_fee or refund_fixed)) or (field=="withholding_account" and withheld) or (field=="settlement_account" and (fee or fixed or withheld or refund_fee or refund_fixed))
        if required and not value:
            frappe.throw(frappe._("Complete las cuentas de comisión, retención y liquidación que correspondan"))
        if value:
            account=locked_doc("Account",value)
            currency=method.currency if field=="settlement_account" else company_currency
            if account.company!=method.company or account.is_group or account.root_type!=root or account.account_currency!=currency or value==method.account:
                frappe.throw(frappe._("La cuenta de liquidación/comisión/retención no coincide con compañía, moneda o naturaleza"))
            if (field=="settlement_account" and account.account_type!="Bank") or (field=="withholding_account" and account.account_type in ("Bank","Cash","Receivable","Payable")):
                frappe.throw(frappe._("La liquidación requiere cuenta bancaria y la retención un activo tributario separado de caja/clientes/proveedores"))


def open_context(prop,data):
    shift=document("HS Shift",data["shift"],"finance")
    method=document("HS Payment Method",data["method"],"finance")
    if shift.status!="Open":
        frappe.throw(frappe._("Seleccione un turno abierto"))
    if shift.cashier!=frappe.session.user:
        require(prop.name,"approve")
    if method.reference_required and not data.get("reference"):
        frappe.throw(frappe._("Indique la referencia bancaria"))
    return shift,method


def expense(prop,data):
    ready(prop)
    from hospitality_suite.cashier import expected
    shift,method=open_context(prop,data)
    category=document("HS Expense Category",data["category"],"finance")
    amount=money(data.get("amount"),currency=method.currency)
    if not category.active or not method.is_cash or amount<=0 or not data.get("reason"):
        frappe.throw(frappe._("Seleccione categoría activa, medio en efectivo, importe positivo y motivo del egreso"))
    fx=exchange(method.currency,category.currency)
    base=money(amount*fx,currency=category.currency)
    if (category.max_amount and base>decimal(category.max_amount)) or amount>decimal(expected(shift).get(method.currency,0)):
        frappe.throw(frappe._("El egreso supera el límite de la categoría o el efectivo esperado del turno"))
    account=locked_doc("Account",category.account)
    if account.company!=prop.company or account.is_group or account.root_type!="Expense" or account.account_currency!=category.currency:
        frappe.throw(frappe._("Revise la cuenta de gasto configurada"))
    journal=frappe.new_doc("Journal Entry")
    journal.update(dict(company=prop.company,posting_date=frappe.utils.nowdate(),voucher_type="Cash Entry",multi_currency=1,hs_shift=shift.name,user_remark=data["reason"]))
    journal.append("accounts",dict(account=category.account,debit_in_account_currency=float(base),exchange_rate=1,cost_center=prop.cost_center))
    journal.append("accounts",dict(account=method.account,credit_in_account_currency=float(amount),exchange_rate=float(fx),cost_center=prop.cost_center))
    post_standard(journal,prop)
    payment=insert("HS Payment",prop,shift=shift.name,method=method.name,expense_category=category.name,currency=method.currency,
                   amount=amount,exchange_rate=fx,base_amount=base,kind="Expense",status="Posted",journal_entry=journal.name,reason=data["reason"])
    audit(prop,"Cash expense",payment,data["reason"])
    return dict(payment=payment.name,journal_entry=journal.name,amount=str(amount),currency=method.currency)


def settlement_quote(prop,data):
    source=document("HS Payment",data["source_payment"],"finance")
    method=document("HS Payment Method",source.method,"finance")
    snapshot=frappe.parse_json(source.fee_snapshot or "{}")
    direction="Pay" if source.kind in ("Refund","Guarantee Refund") else "Receive"
    if source.status!="Posted" or source.kind not in ("Payment","Advance","Guarantee","Refund","Guarantee Refund") or method.is_cash or not snapshot.get("settlement_account"):
        frappe.throw(frappe._("Seleccione un cobro no efectivo con cuentas de liquidación aceptadas al cobrar"))
    previous=current_all("HS Payment",filters={"source_payment":source.name,"kind":"Settlement","status":"Posted"},fields=["amount","fee_amount","withholding_amount","clearing_base_amount"])
    settled=sum(decimal(p.amount) for p in previous)
    amount=money(data.get("amount"),currency=source.currency)
    remaining=decimal(source.amount)-settled
    if amount<=0 or amount>remaining:
        frappe.throw(frappe._("La liquidación supera el importe bruto pendiente"))
    total_fee=money(decimal(source.amount)*decimal(snapshot.get("fee_percent"))/100+decimal(snapshot.get("fee_fixed")),currency=source.currency)
    total_withheld=money(decimal(source.amount)*decimal(snapshot.get("withholding_percent"))/100,currency=source.currency)
    final=amount==remaining
    fee=total_fee-sum(decimal(p.fee_amount) for p in previous) if final else money(total_fee*amount/decimal(source.amount),currency=source.currency)
    withheld=total_withheld-sum(decimal(p.withholding_amount) for p in previous) if final else money(total_withheld*amount/decimal(source.amount),currency=source.currency)
    net=money(amount+fee if direction=="Pay" else amount-fee-withheld,currency=source.currency)
    if min(fee,withheld,net)<0:
        frappe.throw(frappe._("La comisión o retención supera el bruto; revise la política aceptada"))
    base_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    fx=exchange(source.currency,base_currency)
    native=locked_doc("Payment Entry" if source.payment_entry else "Journal Entry",source.payment_entry or source.journal_entry)
    if native.docstatus!=1 or native.hs_property!=prop.name:
        frappe.throw(frappe._("El cobro original no tiene documento contable vigente"))
    original_base=sum((decimal(r.credit)-decimal(r.debit)) if direction=="Pay" else (decimal(r.debit)-decimal(r.credit)) for r in current_all("GL Entry",filters={"voucher_type":native.doctype,"voucher_no":native.name,"account":method.account,"is_cancelled":0},fields=["debit","credit"]))
    cleared=sum(decimal(r.clearing_base_amount) for r in previous)
    historical_base=original_base-cleared if final else money(original_base*amount/decimal(source.amount),currency=base_currency)
    if historical_base<=0:
        frappe.throw(frappe._("La fracción no admite valoración histórica positiva; agrupe una cantidad mayor"))
    q=dict(source_payment=source.name,method=method.name,amount=str(amount),fee=str(fee),withholding=str(withheld),net=str(net),
           currency=source.currency,direction=direction,exchange_rate=str(fx),clearing_base=str(historical_base),clearing_rate=str(historical_base/amount),policy=snapshot,previous=str(settled),base_currency=base_currency)
    q["acceptance"]=hashlib.sha256(canonical(q).encode()).hexdigest()
    return q


def settle(prop,data):
    ready(prop)
    q=settlement_quote(prop,data)
    if data.get("acceptance")!=q["acceptance"] or not data.get("reference"):
        frappe.throw(frappe._("Revise y acepte la liquidación e indique su referencia bancaria"))
    shift,method=open_context(prop,{**data,"method":q["method"]})
    policy=q["policy"]
    company_currency=q["base_currency"]
    fx=decimal(q["exchange_rate"])
    journal=frappe.new_doc("Journal Entry")
    journal.update(dict(company=prop.company,posting_date=frappe.utils.nowdate(),voucher_type="Bank Entry",multi_currency=1,hs_shift=shift.name,
                        cheque_no=data["reference"],cheque_date=frappe.utils.nowdate(),user_remark="Liquidación "+q["source_payment"]+" · "+data["reference"]))
    outgoing=q["direction"]=="Pay"
    lines=[(policy["settlement_account"],decimal(q["net"]),outgoing,method.currency,fx,"Asset"),
           (method.account,decimal(q["amount"]),not outgoing,method.currency,decimal(q["clearing_rate"]),"Asset")]
    if decimal(q["fee"]):
        lines.append((policy["fee_account"],money(decimal(q["fee"])*fx,currency=company_currency),False,company_currency,decimal(1),"Expense"))
    if decimal(q["withholding"]):
        lines.append((policy["withholding_account"],money(decimal(q["withholding"])*fx,currency=company_currency),False,company_currency,decimal(1),"Asset"))
    for name,amount,credit,currency,rate,root in lines:
        account=locked_doc("Account",name)
        if account.company!=prop.company or account.is_group or account.root_type!=root or account.account_currency!=currency:
            frappe.throw(frappe._("Una cuenta de la política aceptada ya no es válida"))
        journal.append("accounts",dict(account=name,credit_in_account_currency=float(amount) if credit else 0,
                                        debit_in_account_currency=0 if credit else float(amount),exchange_rate=float(rate),cost_center=prop.cost_center))
    from hospitality_suite.accounting import balance_exchange
    balance_exchange(journal,prop)
    post_standard(journal,prop)
    payment=insert("HS Payment",prop,shift=shift.name,method=method.name,amount=q["amount"],currency=q["currency"],exchange_rate=fx,
                   base_amount=money(decimal(q["amount"])*fx,currency=company_currency),kind="Settlement",status="Posted",source_payment=q["source_payment"],
                   fee_amount=q["fee"],withholding_amount=q["withholding"],net_amount=q["net"],journal_entry=journal.name,reference=data["reference"],fee_snapshot=canonical(policy))
    payment.clearing_base_amount=q["clearing_base"]
    payment.settlement_direction=q["direction"]
    payment.save()
    audit(prop,"Card settlement",payment,data.get("reason"),q)
    return dict(payment=payment.name,journal_entry=journal.name,**{k:q[k] for k in ("amount","fee","withholding","net","currency")})
