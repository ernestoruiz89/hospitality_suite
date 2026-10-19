"""Render existing synthetic vouchers and readable exports without creating data."""
import hashlib
import io
import json
import os
from pathlib import Path

import frappe
from openpyxl import load_workbook
from pypdf import PdfReader

bench=Path('/home/frappe/benches/hospitality-bench')
repo=Path(__file__).resolve().parents[1]
output=repo/'output/localization'
os.environ['PATH']=str(bench/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_dev'
    frappe.set_user('Administrator')
    frappe.local.lang='es'
    from hospitality_suite import api
    output.mkdir(parents=True,exist_ok=True)
    sources=json.loads((repo/'docs/evidence/patched-native-exports-manifest.json').read_text())['files']
    proof=[]
    for row in sources:
        if not row.get('source_doctype'):
            continue
        slug=Path(row['file']).stem
        template=(repo/f'hospitality_suite/templates/print/{slug}.html').read_text()
        assert frappe.get_doc('Print Format',row['format']).html==template,('Unsynced Print Format',slug)
        pdf=frappe.get_print(row['source_doctype'],row['source'],print_format=row['format'],as_pdf=True)
        path=output/(slug+'.pdf')
        path.write_bytes(pdf)
        pages=PdfReader(io.BytesIO(pdf)).pages
        assert all(len((page.extract_text() or '').strip())>80 for page in pages)
        proof.append(dict(file=path.name,pages=len(pages),format=row['format'],sha256=hashlib.sha256(pdf).hexdigest()))
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    records=api.report(prop.name,'Producción')
    for extension in ('xlsx','pdf'):
        frappe.local.response=frappe._dict()
        api.export_report(prop.name,'Producción',{},extension)
        content=frappe.local.response.filecontent
        (output/('production.'+extension)).write_bytes(content)
        if extension=='xlsx':
            workbook=load_workbook(io.BytesIO(content),read_only=True)
            values=list(workbook.active.values)
            assert len(values)-1==len(records)
            assert 'Referencia' not in values[0]
            assert not any('HS-DEMO-' in str(cell) for row in values for cell in row)
            workbook.close()
            proof.append(dict(file='production.xlsx',rows=len(values)-1,sha256=hashlib.sha256(content).hexdigest()))
        else:
            pages=PdfReader(io.BytesIO(content)).pages
            text=''.join(page.extract_text() for page in pages)
            assert 'HS-DEMO-' not in text
            assert all(row.name not in text for row in records)
            assert len(pages)==1
            proof.append(dict(file='production.pdf',rows=len(records),pages=len(pages),sha256=hashlib.sha256(content).hexdigest()))
    evidence=dict(site='hospitality.localhost',synthetic=True,mutations=False,source_formats_synced=9,files=proof)
    (repo/'docs/evidence/localization-exports.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(evidence,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
