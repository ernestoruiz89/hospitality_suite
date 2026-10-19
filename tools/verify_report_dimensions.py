"""Read-only HTTP/native proof for the synthetic Gerencia report walkthrough."""
import io
import json
import os
import re
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
    frappe.set_user('manager@hospitality.example.invalid')
    from hospitality_suite import api
    from hospitality_suite.pricing import decimal
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    rooms={r.room_number:r.name for r in frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','room_number'])}
    old=api.report(prop.name,'Producción',dict(room=rooms['H104']))
    current=api.report(prop.name,'Producción',dict(room=rooms['H105']))
    stay='9mfspa61cd'
    assert sum(decimal(r.amount) for r in old if r.stay==stay)==1600
    assert sum(decimal(r.amount) for r in current if r.stay==stay)==1500
    sales=api.report(prop.name,'Producción',dict(channel='Venta directa'))
    assert len([r for r in sales if r.name.startswith('aman49j68q')])==2
    assert sum(decimal(r.amount) for r in sales if r.name.startswith('aman49j68q'))==0
    interval=dict(starts_at='2026-10-20 10:00:00',ends_at='2026-10-21 10:00:00')
    stock=api.report(prop.name,'Disponibilidad',dict(interval,room=rooms['H104']))
    assert stock and not stock[0].selected_room_available and 'H104' not in stock[0].candidate_rooms
    all_stock=api.report('','Disponibilidad',dict(interval,company=prop.company))
    assert len({r.property for r in all_stock})==2
    arrivals=api.report(prop.name,'Llegadas',dict(from_date='2026-10-23',to_date='2026-10-23',channel='Web'))
    assert 'i99qbv6dtl' in {r.name for r in arrivals}
    pending=api.report(prop.name,'Cuentas pendientes',dict(room=rooms['H105']))
    assert all(decimal(r.outstanding)>0 for r in pending)
    output=repo/'output/report-dimensions'
    output.mkdir(parents=True,exist_ok=True)
    credentials=json.loads((bench/'sites/hospitality.localhost/private/hospitality-demo-users.json').read_text())
    exports=[]
    with requests.Session() as session:
        response=session.post('http://127.0.0.1:8086/api/method/login',data=dict(usr='manager@hospitality.example.invalid',pwd=credentials['manager@hospitality.example.invalid']),timeout=20)
        response.raise_for_status()
        for filename,property_name,report,filters in (
            ('production-readable',prop.name,'Producción',{}),
            ('production-technical',prop.name,'Producción',dict(detail_level='technical')),
            ('production-room',prop.name,'Producción',dict(group_by='room')),
            ('availability-company','','Disponibilidad',dict(interval,company=prop.company)),
            ('arrivals',prop.name,'Llegadas',dict(from_date='2026-10-23',to_date='2026-10-23',channel='Web')),
        ):
            params=dict(property_name=property_name,report_name=report,filters=json.dumps(filters))
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.report_page',params=params,timeout=30)
            response.raise_for_status()
            result=response.json()['message']
            assert '_display' not in result['columns']
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.export_report',params=dict(params,file_format='xlsx'),timeout=40)
            response.raise_for_status()
            workbook=load_workbook(io.BytesIO(response.content),read_only=True)
            values=list(workbook.active.values)
            assert len(values)-1==result['total']
            if 'Importe' in values[0]:
                index=values[0].index('Importe')
                assert all(isinstance(r[index],(int,float)) for r in values[1:])
            workbook.close()
            (output/(filename+'.xlsx')).write_bytes(response.content)
            response=session.get('http://127.0.0.1:8086/api/method/hospitality_suite.api.export_report',params=dict(params,file_format='pdf'),timeout=60)
            response.raise_for_status()
            pdf=PdfReader(io.BytesIO(response.content))
            assert all(len(p.extract_text().strip())>60 for p in pdf.pages)
            native=api.report(property_name,report,filters)
            text=''.join(''.join(p.extract_text().split()) for p in pdf.pages)
            technical='name' in result['columns']
            if technical:
                assert all(row.name in text for row in native if row.get('name'))
            elif filename=='production-readable':
                assert all(row.name not in text for row in native if row.get('name'))
                assert 'HS-DEMO-' not in text
                assert 'Alojamiento' in text and 'Aguaminibar' in text
            sections=re.split(r'Detalle\d+de\d+',text)[1:]
            if technical:
                assert all(row.name in section for row in native if row.get('name') for section in sections)
            (output/(filename+'.pdf')).write_bytes(response.content)
            exports.append(dict(file=filename,rows=result['total'],xlsx_rows=len(values)-1,pdf_pages=len(pdf.pages),column_sections=max(1,len(sections)),technical_references=technical,reference_check='all source keys in every section' if technical else 'operational descriptions; internal keys hidden',http_status=response.status_code))
    proof=dict(synthetic=True,mutations=False,history=dict(stay=stay,original_room='H104',original_production=1600,current_room='H105',extension_production=1500),
               returned_sale=dict(reference='aman49j68q',rows=2,total=0),availability=stock,authorized_company_properties=len({r.property for r in all_stock}),
               arrivals=[r.name for r in arrivals],pending_accounts=len(pending),exports=exports)
    (repo/'docs/evidence/report-dimensions.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(proof,ensure_ascii=False,default=str))
finally:
    frappe.db.rollback()
    frappe.destroy()
