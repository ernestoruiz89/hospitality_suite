"""Read-only native accounting/stock evidence for the browser fault/retry sale."""
import argparse
import json
import os
from pathlib import Path

import frappe
from hospitality_suite import api

parser=argparse.ArgumentParser()
parser.add_argument("stage",choices=("sale","returned"))
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
fixture=json.loads((bench/".hospitality-network-sale.json").read_text())
proxy=json.loads((bench/".hospitality-drop-response.json").read_text())
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user("Administrator")
    assert proxy["attempts"]==2 and proxy["dropped"]==1 and proxy["same_key"] and proxy["same_payload"] and proxy["same_result"]
    result=proxy["first_result"]
    service=frappe.get_doc("HS Service Request",result["service"])
    invoice=frappe.get_doc("Sales Invoice",result["invoice"])
    payment=frappe.get_doc("HS Payment",result["payment"])
    pe=frappe.get_doc("Payment Entry",payment.payment_entry)
    stock=frappe.get_doc("Stock Entry",service.stock_entry)
    assert invoice.docstatus==pe.docstatus==1 and invoice.update_stock==0 and invoice.outstanding_amount==0
    assert invoice.grand_total==payment.amount==pe.paid_amount==30
    assert frappe.db.count("HS Payment",{"shift":fixture["shift"],"kind":"Payment"})==1
    assert frappe.db.count("Sales Invoice",{"hs_shift":fixture["shift"],"is_return":0,"docstatus":1})==1
    assert frappe.db.count("HS Service Request",{"sales_invoice":invoice.name})==1
    assert len(stock.items)==1 and stock.items[0].item_code==fixture["item"] and stock.items[0].qty==1
    quantity=frappe.db.get_value("Bin",{"warehouse":fixture["warehouse"],"item_code":fixture["item"]},"actual_qty")
    result=dict(real_backend=True,successful_backend_requests=2,lost_successful_responses=1,same_idempotency_key=True,same_payload=True,same_result=True,
                service=service.name,invoice=invoice.name,payment=payment.name,payment_entry=pe.name,stock_entry=stock.name,amount=30,currency="NIO",
                original_sales_invoices=1,original_payments=1,original_stock_movements=1,quantity_before=fixture["before_quantity"],quantity_after_sale=fixture["before_quantity"]-1,
                invoice_update_stock=invoice.update_stock,invoice_outstanding=invoice.outstanding_amount)
    if args.stage=="sale":
        assert service.status=="Delivered" and stock.docstatus==1 and quantity==fixture["before_quantity"]-1
    else:
        credit=frappe.get_doc("Sales Invoice",service.credit_note)
        refunds=frappe.get_all("HS Payment",filters={"source_payment":payment.name,"kind":"Refund","status":"Posted"},pluck="name")
        assert len(refunds)==1
        refund=frappe.get_doc("HS Payment",refunds[0])
        refund_pe=frappe.get_doc("Payment Entry",refund.payment_entry)
        assert service.status=="Returned" and stock.docstatus==2 and quantity==fixture["before_quantity"]
        assert credit.docstatus==1 and credit.is_return and credit.return_against==invoice.name and credit.grand_total==-30 and credit.update_stock==0
        assert refund.amount==refund_pe.paid_amount==30 and refund_pe.docstatus==1 and refund_pe.payment_type=="Pay"
        result.update(returned=True,credit_note=credit.name,refund=refund.name,refund_payment_entry=refund_pe.name,stock_cancelled=True,quantity_after_return=quantity)
    shift=next(s for s in api.bootstrap(fixture["property"])["shifts"] if s.name==fixture["shift"])
    assert float(shift.expected_by_currency["NIO"])==(30 if args.stage=="sale" else 0)
    result.update(shift=shift.name,shift_expected=shift.expected_by_currency["NIO"],shift_status=shift.status)
    Path("/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/network-sale-"+args.stage+".json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
