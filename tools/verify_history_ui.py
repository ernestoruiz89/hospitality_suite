"""Read-only native proof behind the pagination/companion Page screenshots."""
import io
import json
import os
from pathlib import Path

import frappe
from openpyxl import load_workbook
from pypdf import PdfReader

from hospitality_suite import api

bench=Path('/home/frappe/benches/hospitality-bench')
repo=Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel')
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user('manager@hospitality.example.invalid')
    prop=frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'})
    first=api.report_page(prop,'Auditoría')
    second=api.report_page(prop,'Auditoría',offset=50)
    assert first['total']==second['total'] and first['total']>100
    assert len(first['rows'])==len(second['rows'])==50
    assert not {r.name for r in first['rows']}&{r.name for r in second['rows']}
    records=api.report(prop,'Auditoría')
    assert len(records)==first['total']
    api.export_report(prop,'Auditoría',file_format='xlsx')
    workbook=load_workbook(io.BytesIO(frappe.local.response.filecontent),read_only=True)
    xlsx_count=sum(1 for _ in workbook.active.rows)-1
    workbook.close()
    assert xlsx_count==len(records)
    api.export_report(prop,'Auditoría',file_format='pdf')
    data=frappe.local.response.filecontent
    pdf=PdfReader(io.BytesIO(data))
    text=''.join(''.join(page.extract_text().split()) for page in pdf.pages)
    assert all(r.name in text for r in records),'A report row is missing from the PDF'
    (repo/'output/history-audit.pdf').write_bytes(data)
    guest=frappe.db.get_value('HS Guest',{'property':prop,'full_name':'Huésped ficticio H3'})
    history=api.guest_history(guest)
    assert history['total']==2
    assert {r.relationship for r in history['rows']}=={'Principal','Acompañante'}
    proof=dict(synthetic=True,audit_total=first['total'],first_page=50,second_page=50,duplicate_rows=0,
               xlsx_rows=xlsx_count,pdf_rows_verified=len(records),pdf_pages=len(pdf.pages),
               guest_history=[dict(stay=r.name,relationship=r.relationship) for r in history['rows']])
    (repo/'docs/evidence/history-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
