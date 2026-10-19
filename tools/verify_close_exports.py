"""Export the existing reviewed close; never recalculate or change its snapshot."""
import hashlib
import io
import json
import os
from pathlib import Path

import frappe
from pypdf import PdfReader

bench=Path('/home/frappe/benches/hospitality-bench')
root=Path(__file__).resolve().parents[1]
os.environ['PATH']=str(bench/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_dev'
    frappe.set_user('Administrator')
    frappe.local.lang='es'
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    doc=frappe.get_doc('HS Daily Close',{'property':prop.name,'business_date':prop.business_date})
    before=(doc.summary,doc.modified,doc.status,doc.blockers)
    data=frappe.parse_json(doc.summary)
    finance=data['financial']
    assert doc.status=='Review' and finance['sources']['movements']
    source=(root/'hospitality_suite/templates/print/daily_close.html').read_text()
    assert frappe.get_doc('Print Format','HS Cierre diario').html==source
    pdf=frappe.get_print(doc.doctype,doc.name,print_format='HS Cierre diario',as_pdf=True)
    output=root/'output/financial-close'
    output.mkdir(parents=True,exist_ok=True)
    (output/'daily-close.pdf').write_bytes(pdf)
    pages=PdfReader(io.BytesIO(pdf)).pages
    text='\n'.join(p.extract_text() or '' for p in pages)
    for value in ('Facturación por fecha contable','Movimientos de clientes por fecha operativa','Saldos capturados al ejecutar','3100.00','9120.00','Notas de crédito'):
        assert value in text,value
    assert all(len((p.extract_text() or '').strip())>100 for p in pages)
    doc.reload()
    assert (doc.summary,doc.modified,doc.status,doc.blockers)==before
    proof=dict(site=frappe.local.site,synthetic=True,export_mutations=False,source=doc.name,status=doc.status,
               business_date=str(doc.business_date),snapshot_sha256=hashlib.sha256(doc.summary.encode()).hexdigest(),
               posting_date=finance['posting_date'],movement_date=finance['business_date'],currencies=finance['currencies'],
               source_counts={k:len(v) for k,v in finance['sources'].items()},blockers=[dict(type=r['type'],count=len(r['documents'])) for r in frappe.parse_json(doc.blockers)],
               close_confirmed=False,pages=len(pages),pdf_sha256=hashlib.sha256(pdf).hexdigest(),pdf='output/financial-close/daily-close.pdf')
    (root/'docs/evidence/financial-close-ui-export.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(source=doc.name,status=doc.status,pages=len(pages),export_mutations=False)))
finally:
    frappe.db.rollback()
    frappe.destroy()
