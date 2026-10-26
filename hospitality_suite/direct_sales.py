"""Counter sales use the same ERPNext inventory and receivable controllers."""
import hashlib

import frappe
from frappe.utils import nowdate

from hospitality_suite import accounting
from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import document,require
from hospitality_suite.service import current_all,locked_doc,insert,audit,canonical


def _counter_property(property_name):
    from hospitality_suite.standalone_accounting import provider

    prop = require(property_name, "finance")
    if provider() != "erpnext":
        frappe.throw(frappe._("Use el flujo de ventas PMS de este sitio"))
    return prop


def options(property_name):
    """Payment choices for an ERPNext sale, scoped to the selected counter."""
    from hospitality_suite.security import ACTIONS, is_system

    prop = _counter_property(property_name)
    scope = {"property": prop.name, "company": prop.company}
    can_approve = is_system() or bool(set(frappe.get_roles()).intersection(ACTIONS["approve"]))
    shifts = frappe.get_all("HS Shift", filters={**scope, "status": "Open"},
        fields=["name", "cashier", "currency"], order_by="creation desc")
    return dict(property=prop.name, currency=prop.currency,
        can_approve=can_approve,
        methods=frappe.get_all("HS Payment Method", filters=scope,
            fields=["name", "mode_of_payment", "currency", "is_cash", "reference_required"],
            order_by="mode_of_payment asc, name asc"),
        shifts=[row for row in shifts if can_approve or row.cashier == frappe.session.user])


def customer_page(property_name, search="", offset=0, page_length=25):
    """Only payers attached to this hotel are selectable for a counter sale."""
    prop = _counter_property(property_name)
    start, length = _page_args(offset, page_length)
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de pagadores"))
    query = _like(search.strip())
    rows = frappe.db.sql("""
        SELECT c.name, c.customer_name
        FROM `tabCustomer` c
        WHERE c.disabled=0
          AND (EXISTS (SELECT 1 FROM `tabHS Guest` g
                       WHERE g.property=%s AND g.company=%s AND g.customer=c.name)
               OR EXISTS (SELECT 1 FROM `tabHS Billing Party` b
                          WHERE b.property=%s AND b.company=%s AND b.customer=c.name))
          AND (c.name LIKE %s OR c.customer_name LIKE %s)
        ORDER BY c.customer_name ASC, c.name ASC
        LIMIT %s OFFSET %s
    """, (prop.name, prop.company, prop.name, prop.company,
          query, query, length + 1, start), as_dict=True)
    return dict(property=prop.name, offset=start, has_more=len(rows) > length,
        rows=rows[:length])


def history(property_name, search="", offset=0, page_length=25, returnable=0):
    """Counter invoices and full returns, excluding roomless Day Pass."""
    prop = _counter_property(property_name)
    start, length = _page_args(offset, page_length)
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de ventas"))
    if str(returnable) not in ("0", "1"):
        frappe.throw(frappe._("Revise el filtro de devoluciones"))
    query = _like(search.strip())
    pending = str(returnable) == "1"
    rows = frappe.db.sql("""
        SELECT s.name, s.creation, s.customer, c.customer_name, s.item,
               i.item_name,
               s.quantity, s.amount, s.currency, s.status, s.sales_invoice,
               s.credit_note
        FROM `tabHS Service Request` s
        LEFT JOIN `tabCustomer` c ON c.name=s.customer
        LEFT JOIN `tabItem` i ON i.name=s.item
        WHERE s.property=%s AND s.company=%s
          AND (s.stay IS NULL OR s.stay='')
          AND s.sales_invoice IS NOT NULL AND s.sales_invoice!=''
          AND NOT EXISTS (SELECT 1 FROM `tabHS Day Pass` d
                          WHERE d.property=s.property AND d.company=s.company
                            AND d.service=s.name)
          AND (%s=0 OR (s.status='Delivered' AND
                        (s.credit_note IS NULL OR s.credit_note='')))
          AND (s.name LIKE %s OR s.sales_invoice LIKE %s OR
               s.customer LIKE %s OR c.customer_name LIKE %s OR s.item LIKE %s)
        ORDER BY s.creation DESC, s.name DESC
        LIMIT %s OFFSET %s
    """, (prop.name, prop.company, int(pending), query, query, query, query, query,
          length + 1, start), as_dict=True)
    visible = rows[:length]
    names = [row.name for row in visible]
    payments = frappe.get_all("HS Payment", filters={
        "property": prop.name, "company": prop.company,
        "service": ["in", names], "kind": "Payment", "status": "Posted"},
        fields=["service", "method", "amount", "currency", "shift"]
    ) if names else []
    by_service = {row.service: row for row in payments}
    return dict(property=prop.name, offset=start, has_more=len(rows) > length,
        rows=[dict(**row, payment=by_service.get(row.name)) for row in visible])


def _page_args(offset, page_length):
    try:
        start, length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de ventas"))
    if start < 0 or start > 1000000 or not 1 <= length <= 50:
        frappe.throw(frappe._("Revise la paginación de ventas"))
    return start, length


def _like(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def draft(prop,data):
    accounting.ready(prop)
    customer=data.get("customer")
    if not customer or not (current_all("HS Guest",filters={"property":prop.name,"customer":customer}) or current_all("HS Billing Party",filters={"property":prop.name,"customer":customer})):
        frappe.throw(frappe._("Seleccione un pagador registrado en este establecimiento"))
    item=locked_doc("Item",data["item"])
    quantity=decimal(data.get("quantity") or 0)
    if item.disabled or not item.is_sales_item or item.is_fixed_asset or quantity<=0:
        frappe.throw(frappe._("Artículo o cantidad inválida"))
    from hospitality_suite.item_configuration import selling_price
    price=selling_price(prop,item.name,prop.currency,customer)
    inv=frappe.new_doc("Sales Invoice")
    inv.flags.ignore_permissions=True
    inv.update(dict(company=prop.company,customer=customer,currency=prop.currency,posting_date=nowdate(),due_date=nowdate(),
                    debit_to=prop.receivable_account,cost_center=prop.cost_center,hs_property=prop.name,update_stock=0,
                    selling_price_list=prop.price_list,price_list_currency=prop.currency,plc_conversion_rate=1,
                    taxes_and_charges=prop.tax_template))
    inv.append("items",dict(item_code=item.name,qty=float(quantity),rate=price.price_list_rate,cost_center=prop.cost_center,warehouse=prop.warehouse))
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
    values=dict(item=item.name,item_price=price.name,quantity=str(quantity),rate=str(money(price.price_list_rate)),customer=customer,
                total=str(money(inv.grand_total)),currency=prop.currency,tax_template=prop.tax_template,
                method=method.name,payment_amount=str(amount),payment_currency=method.currency,exchange_rate=str(fx),property_rate=str(property_fx))
    values["acceptance"]=hashlib.sha256(canonical(values).encode()).hexdigest()
    return inv,method,values


def quote(prop,data):
    return draft(prop,data)[2]


def sell(prop,data):
    inv,method,q=draft(prop,data)
    if data.get("acceptance")!=q["acceptance"]:
        frappe.throw(frappe._("Revise la cotización de venta antes de confirmar"))
    shift=document("HS Shift",data["shift"],"finance")
    if shift.status!="Open":
        frappe.throw(frappe._("Abra un turno antes de vender"))
    if shift.cashier!=frappe.session.user:
        require(prop.name,"approve")
    if method.reference_required and not data.get("reference"):
        frappe.throw(frappe._("Indique la referencia bancaria"))
    amount=money(q["payment_amount"])
    tendered=money(data.get("tendered") or amount)
    if tendered<amount or (tendered!=amount and not method.is_cash):
        frappe.throw(frappe._("Revise el recibido y el vuelto en la moneda del medio"))
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
        frappe.throw(frappe._("Seleccione una venta directa entregada e indique el motivo"))
    source=locked_doc("HS Payment",frappe.db.get_value("HS Payment",{"service":service.name,"kind":"Payment","status":"Posted"},"name"))
    shift=document("HS Shift",data["shift"],"approve")
    method=document("HS Payment Method",source.method,"approve")
    if shift.status!="Open":
        frappe.throw(frappe._("Seleccione un turno abierto para devolver"))
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
    for row in current_all("HS Day Pass",filters={"property":prop.name,"service":service.name,"status":"Issued"},fields=["name"]):
        day_pass=locked_doc("HS Day Pass",row.name)
        day_pass.status="Cancelled"
        day_pass.save()
        audit(prop,"Day Pass cancelled",day_pass,data["reason"],dict(credit_note=inv.name))
    audit(prop,"Return direct sale",service,data["reason"],dict(credit_note=inv.name,payment=payment.name))
    return dict(service=service.name,credit_note=inv.name,payment=payment.name)
