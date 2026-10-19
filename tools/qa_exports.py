"""Render the installed app's real print formats/exports using synthetic test data."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import uuid

import frappe
from frappe.utils import now_datetime

parser=argparse.ArgumentParser()
parser.add_argument("--site",default="hospitality.localhost")
parser.add_argument("--output",required=True)
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
pdf_runtime=bench/".runtime/wkhtmltox/usr/local/bin"
if (pdf_runtime/"wkhtmltopdf").is_file():
    os.environ["PATH"]=str(pdf_runtime)+os.pathsep+os.environ.get("PATH","")
os.chdir(bench/"sites")
frappe.init(site=args.site,sites_path=str(bench/"sites"))
frappe.connect()
try:
    if not args.site.endswith(".localhost") or not frappe.conf.allow_tests:
        raise SystemExit("La revisión requiere un sitio sintético con allow_tests")
    frappe.set_user("Administrator")
    from hospitality_suite import api
    prop=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
    stay=frappe.db.get_value("HS Stay",{"property":prop.name,"status":"Checked Out"},"name")
    if not stay:
        raise SystemExit("Complete primero un recorrido ficticio de entrada/cobro/salida desde las Pages")
    stay_doc=frappe.get_doc("HS Stay",stay)
    maintenance=frappe.db.get_value("HS Maintenance Order",{"property":prop.name,"title":"Orden sintética de impresión"},"name")
    if not maintenance:
        room=frappe.db.get_value("HS Room",{"property":prop.name,"room_number":"M102"},"name")
        start=now_datetime()+timedelta(days=2)
        maintenance=api.execute(prop.name,"maintenance",uuid.uuid4().hex,dict(room=room,title="Orden sintética de impresión",starts_at=str(start),ends_at=str(start+timedelta(hours=1))))["order"]
    close=api.execute(prop.name,"daily_close",uuid.uuid4().hex,dict(confirm=False))["close"]
    payment=frappe.db.get_value("HS Payment",{"stay":stay,"kind":"Payment","status":"Posted"},["name","shift"],as_dict=True)
    invoice=frappe.db.get_value("Sales Invoice",{"hs_stay":stay,"docstatus":1},"name")
    cleaning=frappe.db.get_value("HS Cleaning Task",{"stay":stay,"status":"Completed"},"name")
    sources=[("reservation","HS Booking",stay_doc.booking,"HS Confirmación de reserva"),
             ("registration","HS Stay",stay,"HS Registro de huésped"),("folio","HS Stay",stay,"HS Cuenta de estancia"),
             ("receipt","HS Payment",payment.name,"HS Recibo"),("shift","HS Shift",payment.shift,"HS Arqueo"),
             ("cleaning","HS Cleaning Task",cleaning,"HS Orden de limpieza"),("maintenance","HS Maintenance Order",maintenance,"HS Orden de mantenimiento"),
             ("daily_close","HS Daily Close",close,"HS Cierre diario"),("invoice","Sales Invoice",invoice,prop.invoice_print_format or "HS Factura")]
    output=Path(args.output)
    pdf_dir=output/"pdf"
    pdf_dir.mkdir(parents=True,exist_ok=True)
    records=[]
    for slug,dt,name,fmt in sources:
        if not name:
            raise RuntimeError("Falta origen sintético para "+slug)
        pdf=frappe.get_print(dt,name,print_format=fmt,as_pdf=True)
        path=pdf_dir/(slug+".pdf")
        path.write_bytes(pdf)
        records.append(dict(file=str(path),source_doctype=dt,source=name,format=fmt,bytes=len(pdf),sha256=hashlib.sha256(pdf).hexdigest()))
    for extension in ("xlsx","pdf"):
        frappe.local.response=frappe._dict()
        api.export_report(prop.name,"Conciliación",{},extension)
        content=frappe.local.response.filecontent
        path=(pdf_dir if extension=="pdf" else output)/("reconciliation."+extension)
        path.write_bytes(content)
        records.append(dict(file=str(path),format=extension,bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
    (output/"exports-manifest.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    frappe.db.commit()
    print(json.dumps(dict(pdf_files=10,xlsx_files=1,output=str(output)),ensure_ascii=False))
except Exception:
    frappe.db.rollback()
    raise
finally:
    frappe.destroy()
