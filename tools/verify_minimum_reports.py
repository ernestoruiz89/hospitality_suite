"""Read-only HTTP/export checks of real synthetic-site reports after the audit."""
import io
import hashlib
import json
import os
from pathlib import Path

import frappe
from openpyxl import load_workbook
from pypdf import PdfReader
import requests

bench=Path('/home/frappe/benches/hospitality-bench')
repo=Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel')
os.environ['PATH']=str(bench/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    user='manager@hospitality.example.invalid'
    frappe.set_user(user)
    from hospitality_suite import api
    from hospitality_suite.reports import REPORTS
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    census={}
    for scope in api.bootstrap()['properties']:
        census[scope.property_name]={name:len(api.report(scope.name,name)) for name in REPORTS}
    credentials=json.loads((bench/'sites/hospitality.localhost/private/hospitality-demo-users.json').read_text())
    output=repo/'output/minimum-reports'
    output.mkdir(parents=True,exist_ok=True)
    exports=[]
    with requests.Session() as session:
        response=session.post('http://127.0.0.1:8086/api/method/login',data=dict(usr=user,pwd=credentials[user]),timeout=20)
        response.raise_for_status()
        for filename,report in (('cleaning-productivity','Productividad de limpieza'),('cash-counts','Arqueos por moneda'),
                                ('cancellations','Cancelaciones y no presentaciones'),('production','Producción')):
            params=dict(property_name=prop.name,report_name=report,filters='{}')
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.report_page',params=params,timeout=30)
            response.raise_for_status()
            page=response.json()['message']
            assert 'name' not in page['columns'] and '_display' not in page['columns']
            native=api.report(prop.name,report)
            assert page['total']==len(native)
            if report=='Cancelaciones y no presentaciones':
                assert native and all(r.status_changed_at for r in native),'Every current cancellation, including expiry, has an immutable date'
            if report=='Arqueos por moneda':
                assert native and all(r.currency for r in native)
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.export_report',params=dict(params,file_format='xlsx'),timeout=40)
            response.raise_for_status()
            workbook=load_workbook(io.BytesIO(response.content),read_only=True)
            values=list(workbook.active.values)
            assert len(values)-1==len(native)
            workbook.close()
            (output/(filename+'.xlsx')).write_bytes(response.content)
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.export_report',params=dict(params,file_format='pdf'),timeout=60)
            response.raise_for_status()
            pdf=PdfReader(io.BytesIO(response.content))
            text=''.join(''.join(p.extract_text().split()) for p in pdf.pages)
            assert all(r.name not in text for r in native if r.get('name'))
            path=output/(filename+'.pdf')
            path.write_bytes(response.content)
            exports.append(dict(file=path.name,report=report,rows=len(native),xlsx_rows=len(values)-1,pdf_pages=len(pdf.pages),
                                sha256=hashlib.sha256(response.content).hexdigest(),http_status=response.status_code))
    proof=dict(synthetic=True,mutations=False,reports_by_property=census,exports=exports)
    (repo/'docs/evidence/minimum-reports-http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
