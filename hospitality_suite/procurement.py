"""Small purchasing/stock workflows; ERPNext owns quantities, valuation and ledgers."""
import hashlib

import frappe

from hospitality_suite.accounting import ready,post_standard,exchange
from hospitality_suite.pricing import decimal,money
from hospitality_suite.security import document,require
from hospitality_suite.service import current_all,locked_doc,insert,audit,canonical


def source(prop,dt,name):
    doc=locked_doc(dt,name)
    if doc.company!=prop.company or doc.get("hs_property")!=prop.name:
        frappe.throw(frappe._("El documento no pertenece a este establecimiento"),frappe.PermissionError)
    doc.check_permission("read")
    return doc


def warehouse(prop,name=None):
    name=name or prop.warehouse
    doc=locked_doc("Warehouse",name)
    if doc.company!=prop.company or doc.is_group or (name not in (prop.warehouse,prop.laundry_warehouse) and doc.hs_property!=prop.name):
        frappe.throw(frappe._("Seleccione un almacén asignado a este establecimiento"),frappe.PermissionError)
    return name


def warehouses(prop):
    names={prop.warehouse,prop.laundry_warehouse}
    names.update(current_all("Warehouse",filters={"hs_property":prop.name,"company":prop.company,"is_group":0},pluck="name"))
    return sorted(n for n in names if n)


def create_warehouse(prop,data):
    if not data.get("warehouse_name"):
        frappe.throw(frappe._("Indique el nombre del almacén o ubicación"))
    doc=frappe.get_doc(dict(doctype="Warehouse",warehouse_name=data["warehouse_name"],company=prop.company,is_group=0,hs_property=prop.name))
    doc.insert(ignore_permissions=True)
    audit(prop,"Create property warehouse",doc,data.get("reason"))
    return dict(warehouse=doc.name)


def stock_policy(prop,data):
    item=locked_doc("Item",data["item"])
    target=warehouse(prop,data.get("warehouse"))
    purpose=data.get("purpose")
    minimum,reorder=decimal(data.get("minimum")),decimal(data.get("reorder_quantity"))
    if purpose not in ("Merchandise","Cleaning","Linen","Parts","Asset") or min(minimum,reorder)<0 or bool(item.is_fixed_asset)!=(purpose=="Asset") or (purpose=="Asset" and (minimum or reorder)):
        frappe.throw(frappe._("Revise clasificación y mínimos; los activos usan su registro estándar, sin reorden por stock"))
    if not item.is_stock_item and purpose!="Asset":
        frappe.throw(frappe._("Los mínimos requieren un artículo de inventario"))
    name=frappe.db.get_value("HS Stock Policy",{"property":prop.name,"item":item.name,"warehouse":target})
    if name:
        policy=locked_doc("HS Stock Policy",name)
        policy.purpose=purpose
        policy.save()
    else:
        policy=insert("HS Stock Policy",prop,item=item.name,warehouse=target,purpose=purpose)
    if purpose!="Asset":
        existing=[row for row in item.reorder_levels if row.warehouse==target]
        if len(existing)>1:
            frappe.throw(frappe._("Revise los mínimos duplicados de este almacén en el artículo estándar"))
        row=existing[0] if existing else item.append("reorder_levels",dict(warehouse=target,material_request_type="Purchase"))
        row.warehouse_reorder_level=float(minimum)
        row.warehouse_reorder_qty=float(reorder)
        item.save(ignore_permissions=True)  # Only this property's native reorder row is changed.
    audit(prop,"Stock policy",policy,data.get("reason"),dict(minimum=str(minimum),reorder_quantity=str(reorder)))
    return dict(policy=policy.name)


def supplier(prop,name):
    if not current_all("HS Supplier",filters={"property":prop.name,"supplier":name,"active":1}):
        frappe.throw(frappe._("Seleccione un proveedor habilitado para el establecimiento"))
    doc=locked_doc("Supplier",name)
    if doc.disabled:
        frappe.throw(frappe._("El proveedor está deshabilitado"))
    return doc


def register_supplier(prop,data):
    if not data.get("supplier_name"):
        frappe.throw(frappe._("Indique el nombre comercial del proveedor"))
    vendor=frappe.get_doc(dict(doctype="Supplier",supplier_name=data["supplier_name"],supplier_type="Company",
                               supplier_group=frappe.db.get_value("Supplier Group",{"is_group":0},"name") or "All Supplier Groups"))
    vendor.insert(ignore_permissions=True)
    record=insert("HS Supplier",prop,supplier=vendor.name,active=1)
    audit(prop,"Register supplier",record,data.get("reason"))
    return dict(supplier=vendor.name,registration=record.name)


def draft_order(prop,data):
    ready(prop)
    vendor=supplier(prop,data["supplier"])
    items=data.get("items")
    if not isinstance(items,list) or not 1<=len(items)<=100 or not data.get("reason"):
        frappe.throw(frappe._("Indique artículos y motivo de la compra"))
    target=warehouse(prop,data.get("warehouse"))
    schedule=data.get("schedule_date") or frappe.utils.nowdate()
    if frappe.utils.getdate(schedule)<frappe.utils.getdate():
        frappe.throw(frappe._("La fecha prevista de recepción no puede estar vencida"))
    order=frappe.new_doc("Purchase Order")
    order.update(dict(company=prop.company,supplier=vendor.name,currency=prop.currency,transaction_date=frappe.utils.nowdate(),schedule_date=schedule,
                      conversion_rate=float(exchange(prop.currency,frappe.db.get_value("Company",prop.company,"default_currency"))),set_warehouse=target,
                      remarks=data["reason"],cost_center=prop.cost_center))
    for row in items:
        item=locked_doc("Item",row["item"])
        quantity,rate=decimal(row.get("quantity")),money(row.get("rate"),currency=prop.currency)
        if item.disabled or not item.is_purchase_item or quantity<=0 or rate<0:
            frappe.throw(frappe._("Revise artículo de compra, cantidad positiva y precio no negativo"))
        order.append("items",dict(item_code=item.name,qty=float(quantity),rate=float(rate),schedule_date=schedule,warehouse=target,cost_center=prop.cost_center))
    order.set_missing_values()
    order.calculate_taxes_and_totals()
    return order


def order_quote(order):
    q=dict(supplier=order.supplier,warehouse=order.set_warehouse,schedule_date=str(order.schedule_date),currency=order.currency,
           total=str(money(order.grand_total,currency=order.currency)),exchange_rate=str(decimal(order.conversion_rate)),
           items=[dict(item=r.item_code,quantity=str(decimal(r.qty)),rate=str(decimal(r.rate)),uom=r.uom) for r in order.items],
           taxes=[dict(account=r.account_head,rate=str(decimal(r.rate)),amount=str(decimal(r.tax_amount))) for r in order.taxes])
    q["acceptance"]=hashlib.sha256(canonical(q).encode()).hexdigest()
    return q


def purchase_order_quote(prop,data):
    return order_quote(draft_order(prop,data))


def purchase_order(prop,data):
    order=draft_order(prop,data)
    q=order_quote(order)
    if data.get("acceptance")!=q["acceptance"]:
        frappe.throw(frappe._("Revise y acepte el total de la orden de compra antes de confirmarla"))
    post_standard(order,prop)
    audit(prop,"Purchase order",order,data["reason"])
    return dict(order=order.name,total=str(order.grand_total),currency=order.currency)


def receive_purchase(prop,data):
    ready(prop)
    order=source(prop,"Purchase Order",data["order"])
    supplier(prop,order.supplier)
    if order.docstatus!=1 or order.status in ("Closed","Cancelled","Completed"):
        frappe.throw(frappe._("Seleccione una orden de compra presentada y pendiente"))
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
    target=frappe.new_doc("Purchase Receipt")
    target.flags.ignore_permissions=True
    target.hs_property=prop.name
    receipt=make_purchase_receipt(order.name,target_doc=target)
    requested=data.get("items")
    if not isinstance(requested,list) or not requested or len(requested)!=len({r.get("order_item") for r in requested}):
        frappe.throw(frappe._("Seleccione las líneas recibidas sin repetirlas"))
    quantities={r["order_item"]:decimal(r.get("quantity")) for r in requested}
    mapped={r.purchase_order_item:r for r in receipt.items}
    if set(quantities)-set(mapped) or any(q<=0 or q>decimal(mapped[n].qty) for n,q in quantities.items()):
        frappe.throw(frappe._("La cantidad recibida supera lo pendiente de la orden"))
    receipt.set("items",[r for r in receipt.items if r.purchase_order_item in quantities])
    for row in receipt.items:
        row.qty=float(quantities[row.purchase_order_item])
        row.received_qty=row.qty
        row.rejected_qty=0
        row.warehouse=warehouse(prop,data.get("warehouse") or row.warehouse)
        row.cost_center=prop.cost_center
    receipt.remarks=data.get("reason") or "Recepción de orden "+order.name
    receipt.set_missing_values()
    receipt.calculate_taxes_and_totals()
    post_standard(receipt,prop)
    audit(prop,"Receive purchase",receipt,receipt.remarks)
    return dict(receipt=receipt.name,order=order.name)


def purchase_invoice(prop,data):
    ready(prop)
    receipt=source(prop,"Purchase Receipt",data["receipt"])
    supplier(prop,receipt.supplier)
    if receipt.docstatus!=1 or receipt.is_return:
        frappe.throw(frappe._("Seleccione una recepción presentada"))
    if not data.get("bill_no") or not data.get("bill_date"):
        frappe.throw(frappe._("Indique número y fecha del documento del proveedor"))
    from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
    target=frappe.new_doc("Purchase Invoice")
    target.flags.ignore_permissions=True
    target.hs_property=prop.name
    invoice=make_purchase_invoice(receipt.name,target_doc=target)
    invoice.update(dict(bill_no=data["bill_no"],bill_date=data["bill_date"],update_stock=0,cost_center=prop.cost_center))
    for row in invoice.items:
        row.cost_center=prop.cost_center
    post_standard(invoice,prop)
    audit(prop,"Purchase invoice",invoice,data.get("reason"))
    return dict(invoice=invoice.name,total=str(invoice.grand_total),currency=invoice.currency)


def supplier_payment_quote(prop,data):
    invoice=source(prop,"Purchase Invoice",data["invoice"])
    supplier(prop,invoice.supplier)
    method=document("HS Payment Method",data["method"],"finance")
    if invoice.docstatus!=1 or invoice.is_return or invoice.outstanding_amount<=0:
        frappe.throw(frappe._("Seleccione una factura de compra con saldo pendiente"))
    base_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    account=locked_doc("Account",invoice.credit_to)
    fx=exchange(method.currency,base_currency)
    party_fx=exchange(account.account_currency,base_currency)
    amount=money(data.get("amount"),currency=method.currency)
    party_amount=money(amount*fx/party_fx,currency=account.account_currency)
    if amount<=0 or party_amount<=0 or party_amount>decimal(invoice.outstanding_amount):
        frappe.throw(frappe._("El pago supera el saldo pendiente del proveedor"))
    q=dict(invoice=invoice.name,modified=str(invoice.modified),supplier=invoice.supplier,method=method.name,amount=str(amount),currency=method.currency,
           party_amount=str(party_amount),party_currency=account.account_currency,exchange_rate=str(fx),party_rate=str(party_fx),base_currency=base_currency)
    q["acceptance"]=hashlib.sha256(canonical(q).encode()).hexdigest()
    return q


def supplier_payment(prop,data):
    ready(prop)
    from hospitality_suite.treasury import open_context
    from hospitality_suite.cashier import expected
    q=supplier_payment_quote(prop,data)
    if data.get("acceptance")!=q["acceptance"] or not data.get("reason"):
        frappe.throw(frappe._("Revise y acepte el pago al proveedor e indique el motivo"))
    shift,method=open_context(prop,data)
    if method.is_cash and decimal(q["amount"])>decimal(expected(shift).get(method.currency,0)):
        frappe.throw(frappe._("El pago supera el efectivo esperado del turno"))
    invoice=source(prop,"Purchase Invoice",q["invoice"])
    payment=frappe.new_doc("Payment Entry")
    payment.update(dict(company=prop.company,payment_type="Pay",party_type="Supplier",party=invoice.supplier,posting_date=frappe.utils.nowdate(),
                        paid_from=method.account,paid_to=invoice.credit_to,paid_amount=float(decimal(q["amount"])),received_amount=float(decimal(q["party_amount"])),
                        source_exchange_rate=float(decimal(q["exchange_rate"])),target_exchange_rate=float(decimal(q["party_rate"])),
                        mode_of_payment=method.mode_of_payment,cost_center=prop.cost_center,hs_shift=shift.name,
                        reference_no=data.get("reference") or invoice.name,reference_date=frappe.utils.nowdate(),remarks=data["reason"]))
    payment.append("references",dict(reference_doctype="Purchase Invoice",reference_name=invoice.name,allocated_amount=float(decimal(q["party_amount"]))))
    post_standard(payment,prop)
    record=insert("HS Payment",prop,shift=shift.name,method=method.name,supplier=invoice.supplier,purchase_invoice=invoice.name,
                  currency=method.currency,amount=q["amount"],exchange_rate=q["exchange_rate"],base_amount=money(decimal(q["amount"])*decimal(q["exchange_rate"]),currency=q["base_currency"]),
                  kind="Supplier Payment",status="Posted",payment_entry=payment.name,reason=data["reason"],reference=data.get("reference"))
    audit(prop,"Supplier payment",record,data["reason"])
    return dict(payment=record.name,payment_entry=payment.name,amount=q["amount"],currency=q["currency"])


def move_stock(prop,data):
    ready(prop)
    source_wh=warehouse(prop,data.get("source_warehouse"))
    direction=data.get("purpose")
    if direction not in ("Transfer","Cleaning","Waste","Linen Replacement") or not data.get("reason"):
        frappe.throw(frappe._("Seleccione uso del inventario e indique motivo"))
    target=warehouse(prop,data["target_warehouse"]) if direction in ("Transfer","Linen Replacement") else None
    if target==source_wh:
        frappe.throw(frappe._("Seleccione almacenes diferentes"))
    item=locked_doc("Item",data["item"])
    quantity=decimal(data.get("quantity"))
    if item.disabled or not item.is_stock_item or item.is_fixed_asset or quantity<=0:
        frappe.throw(frappe._("Seleccione un artículo de inventario habilitado y cantidad positiva; los activos usan su flujo estándar"))
    entry=frappe.new_doc("Stock Entry")
    entry.update(dict(company=prop.company,stock_entry_type="Material Transfer" if target else "Material Issue",remarks=data["reason"],hs_stock_purpose=direction))
    row=dict(item_code=item.name,qty=float(quantity),s_warehouse=source_wh,t_warehouse=target,cost_center=prop.cost_center)
    if not target:
        category=document("HS Expense Category",data["category"],"inventory")
        if not category.active:
            frappe.throw(frappe._("Seleccione una categoría de gasto activa"))
        row["expense_account"]=category.account
    entry.append("items",row)
    post_standard(entry,prop)
    audit(prop,"Stock "+direction,entry,data["reason"])
    return dict(stock_entry=entry.name,purpose=direction)


def adjustment_quote(prop,data):
    target=warehouse(prop,data.get("warehouse"))
    item=locked_doc("Item",data["item"])
    qty=decimal(data.get("counted_quantity"))
    if item.disabled or not item.is_stock_item or item.is_fixed_asset or qty<0:
        frappe.throw(frappe._("Revise artículo inventariable y conteo no negativo"))
    bin_name=frappe.db.get_value("Bin",{"item_code":item.name,"warehouse":target},"name")
    current=locked_doc("Bin",bin_name) if bin_name else frappe._dict(actual_qty=0,valuation_rate=0,modified=None)
    if not current.valuation_rate:
        frappe.throw(frappe._("Sin valoración existente: reciba la compra o transferencia de origen antes de ajustar"))
    q=dict(item=item.name,warehouse=target,current_quantity=str(decimal(current.actual_qty)),counted_quantity=str(qty),
           valuation_rate=str(decimal(current.valuation_rate)),bin_modified=str(current.modified))
    q["acceptance"]=hashlib.sha256(canonical(q).encode()).hexdigest()
    return q


def adjust_stock(prop,data):
    ready(prop)
    require(prop.name,"approve")
    q=adjustment_quote(prop,data)
    if data.get("acceptance")!=q["acceptance"] or not data.get("reason"):
        frappe.throw(frappe._("Revise el conteo actual y acepte el ajuste con motivo"))
    if decimal(q["counted_quantity"])==decimal(q["current_quantity"]):
        frappe.throw(frappe._("El conteo coincide: no hay ajuste que registrar"))
    category=document("HS Expense Category",data["category"],"approve")
    if not category.active:
        frappe.throw(frappe._("Seleccione una categoría de gasto activa"))
    doc=frappe.new_doc("Stock Reconciliation")
    doc.flags.hs_count_reviewed=True
    doc.update(dict(company=prop.company,purpose="Stock Reconciliation",expense_account=category.account,cost_center=prop.cost_center))
    doc.append("items",dict(item_code=q["item"],warehouse=q["warehouse"],qty=float(decimal(q["counted_quantity"])),valuation_rate=float(decimal(q["valuation_rate"]))))
    post_standard(doc,prop)
    audit(prop,"Stock count adjustment",doc,data["reason"],q)
    return dict(stock_reconciliation=doc.name,item=q["item"],warehouse=q["warehouse"],quantity=q["counted_quantity"])
