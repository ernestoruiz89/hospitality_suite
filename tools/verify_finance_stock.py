"""Read-only verification of the synthetic purchase/treasury browser circuit."""
import argparse
import json
import os
from pathlib import Path

import frappe

parser=argparse.ArgumentParser()
parser.add_argument("--output",required=True)
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
pdf_runtime=bench/".runtime/wkhtmltox/usr/local/bin"
if (pdf_runtime/"wkhtmltopdf").is_file():
    os.environ["PATH"]=str(pdf_runtime)+os.pathsep+os.environ.get("PATH","")
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests, "Requires the synthetic test site"
    frappe.set_user("Administrator")
    from hospitality_suite.reconciliation import differences
    from hospitality_suite.cashier import expected
    from hospitality_suite import api
    prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
    invoice=frappe.get_doc("Purchase Invoice",{"hs_property":prop.name,"bill_no":"DEMO-UI-001","docstatus":1})
    receipt=frappe.get_doc("Purchase Receipt",invoice.items[0].purchase_receipt)
    order=frappe.get_doc("Purchase Order",receipt.items[0].purchase_order)
    settlement=frappe.get_doc("HS Payment",{"property":prop.name,"kind":"Settlement","reference":"EXTRACTO-UI-001","status":"Posted"})
    source=frappe.get_doc("HS Payment",settlement.source_payment)
    shift=frappe.get_doc("HS Shift",settlement.shift)
    method=frappe.get_doc("HS Payment Method",source.method)
    policy=frappe.parse_json(settlement.fee_snapshot)
    assert order.docstatus==receipt.docstatus==invoice.docstatus==1
    assert invoice.outstanding_amount==0 and invoice.update_stock==0
    assert frappe.db.get_value("Bin",{"item_code":"HS-DEMO-LINEN","warehouse":prop.warehouse},"actual_qty")==2
    assert (settlement.amount,settlement.fee_amount,settlement.withholding_amount,settlement.net_amount)==(30,2.9,.3,26.8)
    assert shift.status=="Closed" and expected(shift)["NIO"]=="380.00" and shift.difference==0
    assert differences(prop)==[]
    vouchers=[source.payment_entry,settlement.journal_entry]
    gl=frappe.get_all("GL Entry",filters={"voucher_no":["in",vouchers],"is_cancelled":0},fields=["account","debit","credit"])
    balance=lambda account:round(sum(r.debit-r.credit for r in gl if r.account==account),2)
    assert balance(method.account)==0
    assert balance(policy["settlement_account"])==26.8
    assert balance(policy["fee_account"])==2.9
    assert balance(policy["withholding_account"])==.3
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    for label,dt,name,fmt in [("settlement","HS Payment",settlement.name,"HS Recibo"),("expense","HS Payment",frappe.db.get_value("HS Payment",{"journal_entry":"ACC-JV-2026-00001"},"name"),"HS Recibo"),("finance-stock-shift","HS Shift",shift.name,"HS Arqueo")]:
        (output/(label+".pdf")).write_bytes(frappe.get_print(dt,name,print_format=fmt,as_pdf=True))
    for report in ("Liquidaciones","Egresos","Movimientos de inventario"):
        for extension in ("xlsx","pdf"):
            frappe.local.response=frappe._dict()
            api.export_report(prop.name,report,{},extension)
            (output/(report.lower()+"."+extension)).write_bytes(frappe.local.response.filecontent)
    result=dict(site=frappe.local.site,order=order.name,receipt=receipt.name,invoice=invoice.name,supplier_outstanding=invoice.outstanding_amount,
                linen_quantity=2,invoice_update_stock=invoice.update_stock,source_payment=source.payment_entry,settlement=settlement.journal_entry,
                gross=settlement.amount,fee=settlement.fee_amount,withholding=settlement.withholding_amount,net=settlement.net_amount,
                clearing_balance=balance(method.account),shift=shift.name,shift_status=shift.status,expected_cash=expected(shift),difference=shift.difference,reconciliation_differences=[])
    (output/"finance-stock.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
