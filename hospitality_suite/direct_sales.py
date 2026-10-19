"""Counter sales use the same ERPNext inventory and receivable controllers."""
import hashlib

import frappe
from frappe.utils import nowdate

from hospitality_suite import accounting
from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import document,require
from hospitality_suite.service import current_all,locked_doc,insert,audit,canonical


def draft(prop,data):
    accounting.ready(prop)
    customer=data.get("customer")
    if not customer or not (current_all("HS Guest",filters={"property":prop.name,"customer":customer}) or current_all("HS Billing Party",filters={"property":prop.name,"customer":customer})):
        frappe.throw("Seleccione un pagador registrado en este establecimiento")
    item=locked_doc("Item",data["item"])
    quantity=decimal(data.get("quantity") or 0)
    if item.disabled or not item.is_sales_item or quantity<=0:
        frappe.throw("Artículo o cantidad inválida")
    price_list=prop.price_list or frappe.db.get_single_value("Selling Settings","selling_price_list")
    prices=current_all("Item Price",filters={"item_code":item.name,"price_list":price_list,"currency":prop.currency,"selling":1},fields=["price_list_rate","valid_from","valid_upto"])
    prices=[p for p in prices if (not p.valid_from or str(p.valid_from)<=nowdate()) and (not p.valid_upto or str(p.valid_upto)>=nowdate())]
    if len(prices)!=1:
        frappe.throw("Configure un precio de venta vigente e inequívoco para este artículo")
    inv=frappe.new_doc("Sales Invoice")
    inv.flags.ignore_permissions=True
    inv.update(dict(company=prop.company,customer=customer,currency=prop.currency,posting_date=nowdate(),due_date=nowdate(),
                    debit_to=prop.receivable_account,cost_center=prop.cost_center,hs_property=prop.name,update_stock=0,
                    taxes_and_charges=prop.tax_template))
    inv.append("items",dict(item_code=item.name,qty=float(quantity),rate=prices[0].price_list_rate,cost_center=prop.cost_center))
    inv.set_missing_values()
    if prop.tax_template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        inv.set("taxes",get_taxes_and_charges("Sales Taxes and Charges Template",prop.tax_template))
    inv.calculate_taxes_and_totals()
    method=document("HS Payment Method",data["method"],"finance")
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    fx=accounting.exchange(method.currency,company_currency)
    property_fx=accounting.exchange(prop.currency,company_currency)
    amount=money(decimal(inv.grand_total)*property_fx/fx)
    values=dict(item=item.name,quantity=str(quantity),rate=str(money(prices[0].price_list_rate)),customer=customer,
                total=str(money(inv.grand_total)),currency=prop.currency,tax_template=prop.tax_template,
                method=method.name,payment_amount=str(amount),payment_currency=method.currency,exchange_rate=str(fx),property_rate=str(property_fx))
    values["acceptance"]=hashlib.sha256(canonical(values).encode()).hexdigest()
    return inv,method,values


def quote(prop,data):
    return draft(prop,data)[2]


def sell(prop,data):
    inv,method,q=draft(prop,data)
    if data.get("acceptance")!=q["acceptance"]:
        frappe.throw("Revise la cotización de venta antes de confirmar")
    shift=document("HS Shift",data["shift"],"finance")
    if shift.status!="Open":
        frappe.throw("Abra un turno antes de vender")
    if shift.cashier!=frappe.session.user:
        require(prop.name,"approve")
    if method.reference_required and not data.get("reference"):
        frappe.throw("Indique la referencia bancaria")
    amount=money(q["payment_amount"])
    tendered=money(data.get("tendered") or amount)
    if tendered<amount or (tendered!=amount and not method.is_cash):
        frappe.throw("Revise el recibido y el vuelto en la moneda del medio")
    from hospitality_suite.inventory import stock_movement
    stock=stock_movement(prop,q["item"],float(decimal(q["quantity"])))
    inv.hs_shift=shift.name
    accounting.post_standard(inv,prop)
    pe=frappe.new_doc("Payment Entry")
    pe.update(dict(company=prop.company,payment_type="Receive",posting_date=nowdate(),party_type="Customer",party=inv.customer,
                   paid_from=prop.receivable_account,paid_to=method.account,paid_amount=inv.grand_total,received_amount=float(amount),
                   source_exchange_rate=float(decimal(q["property_rate"])),target_exchange_rate=float(decimal(q["exchange_rate"])),
                   mode_of_payment=method.mode_of_payment,reference_no=data.get("reference") or inv.name,reference_date=nowdate(),
                   cost_center=prop.cost_center,hs_shift=shift.name))
    pe.append("references",dict(reference_doctype="Sales Invoice",reference_name=inv.name,allocated_amount=inv.grand_total))
    accounting.post_standard(pe,prop)
    service=insert("HS Service Request",prop,customer=inv.customer,item=q["item"],quantity=float(decimal(q["quantity"])),
                   amount=inv.grand_total,currency=prop.currency,status="Delivered",stock_entry=stock.name if stock else None,
                   sales_invoice=inv.name,notes=data.get("notes"))
    payment=insert("HS Payment",prop,customer=inv.customer,shift=shift.name,method=method.name,amount=amount,currency=method.currency,
                   exchange_rate=decimal(q["exchange_rate"]),base_amount=money(amount*decimal(q["exchange_rate"])),kind="Payment",status="Posted",
                   payment_entry=pe.name,sales_invoice=inv.name,service=service.name,tendered=tendered,change_amount=money(tendered-amount),reference=data.get("reference"))
    audit(prop,"Direct sale",service,details=dict(invoice=inv.name,payment=payment.name,stock_entry=service.stock_entry))
    return dict(service=service.name,invoice=inv.name,payment=payment.name,amount=str(amount),currency=method.currency,change=str(money(tendered-amount)))


def return_sale(prop,data):
    require(prop.name,"approve")
    service=document("HS Service Request",data["service"],"approve")
    if service.stay or service.status!="Delivered" or not service.sales_invoice or not data.get("reason"):
        frappe.throw("Seleccione una venta directa entregada e indique el motivo")
    source=locked_doc("HS Payment",frappe.db.get_value("HS Payment",{"service":service.name,"kind":"Payment","status":"Posted"},"name"))
    shift=document("HS Shift",data["shift"],"approve")
    method=document("HS Payment Method",source.method,"approve")
    if shift.status!="Open":
        frappe.throw("Seleccione un turno abierto para devolver")
    credit=accounting.credit_note(prop,dict(invoice=service.sales_invoice,reason=data["reason"]))
    inv=locked_doc("Sales Invoice",credit["credit_note"])
    company_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    fx=accounting.exchange(method.currency,company_currency)
    property_fx=accounting.exchange(prop.currency,company_currency)
    pe=frappe.new_doc("Payment Entry")
    pe.update(dict(company=prop.company,payment_type="Pay",posting_date=nowdate(),party_type="Customer",party=source.customer,
                   paid_from=method.account,paid_to=prop.receivable_account,paid_amount=source.amount,received_amount=abs(inv.grand_total),
                   source_exchange_rate=float(fx),target_exchange_rate=float(property_fx),mode_of_payment=method.mode_of_payment,
                   reference_no=inv.name,reference_date=nowdate(),cost_center=prop.cost_center,hs_shift=shift.name,remarks=data["reason"]))
    pe.append("references",dict(reference_doctype="Sales Invoice",reference_name=inv.name,allocated_amount=inv.grand_total))
    accounting.post_standard(pe,prop)
    if service.stock_entry:
        stock=locked_doc("Stock Entry",service.stock_entry)
        stock.flags.ignore_permissions=True
        stock.hs_correction_reason=data["reason"]
        stock.cancel()
    payment=insert("HS Payment",prop,customer=source.customer,shift=shift.name,method=method.name,amount=source.amount,currency=source.currency,
                   exchange_rate=fx,base_amount=money(decimal(source.amount)*fx),kind="Refund",status="Posted",source_payment=source.name,
                   payment_entry=pe.name,sales_invoice=inv.name,service=service.name,reason=data["reason"])
    service.status,service.credit_note="Returned",inv.name
    service.save()
    audit(prop,"Return direct sale",service,data["reason"],dict(credit_note=inv.name,payment=payment.name))
    return dict(service=service.name,credit_note=inv.name,payment=payment.name)
