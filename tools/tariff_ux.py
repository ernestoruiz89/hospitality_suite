"""Synthetic historical-price fixtures and read-only acceptance, fixed test site."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
from datetime import timedelta
import uuid

import frappe
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import operation,canonical

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
BASE=BENCH/'.hospitality-tariffs-ux-baseline.json'
FIXTURE=BENCH/'.hospitality-tariffs-ui-fixture.json'
PROOF=ROOT/'docs/evidence/tariffs-items-ui.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect','pdf']);args=parser.parse_args()
assert BASE.is_file(),'Conserve primero el respaldo con archivos y su línea de base'
baseline=json.loads(BASE.read_text())
os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()


def hashes():
    result={}
    for dt in sorted(set(baseline['tables'])|{'Version'}):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        result[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    return result


def command(prop,action,data):
    return api.execute(prop.name,action,uuid.uuid4().hex,data)


def prepare():
    assert not FIXTURE.exists(),'No sustituya el fixture original'
    before=hashes()
    assert all(before[dt]==expected for dt,expected in baseline['tables'].items())
    now=now_datetime().replace(microsecond=0)
    fixture={}
    for mode,title,prefix in [('Hotel','Hotel Jardín Demo','H'),('Motel','Motel Luna Demo','M')]:
        prop=frappe.get_doc('HS Property',{'property_name':title})
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':prefix+'101'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        rate=frappe.get_doc('HS Rate',{'property':prop.name,'category':room.category})
        with operation():
            category=frappe.get_doc('HS Category',room.category)
            category.capacity=4;category.max_extra_beds=1;category.save()
            rate.additional_person_rate=50;rate.extra_bed_rate=100
            rate.grace_minutes=10;rate.rounding_minutes=30;rate.save()
            if mode=='Hotel':
                seasonal=frappe.copy_doc(rate);seasonal.title='Temporada aceptada';seasonal.amount=2000;seasonal.priority=rate.priority+1
                seasonal.valid_from=(now+timedelta(days=1)).date();seasonal.valid_to=seasonal.valid_from;seasonal.insert()
            else:
                item=frappe.get_doc(dict(doctype='Item',item_code='HS-QA-TARIFF-HOUR',item_name='Horas adicionales de motel',
                                        item_group='Services',stock_uom='Hour',is_stock_item=0,is_sales_item=1)).insert()
                prop.extra_hour_item=item.name;prop.save()
        values=dict(starts_at=str(now),ends_at=str(now+(timedelta(days=2) if mode=='Hotel' else timedelta(hours=3,minutes=41))),
                    customer=guest.customer,guest=guest.name,rooms=[dict(category=room.category,room=room.name,people=3,extra_beds=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        entered=command(prop,'walk_in',values)
        rows=api.stay_detail(entered['stay'])['charges']
        if mode=='Hotel':
            command(prop,'adjustment',dict(charge=rows[0].name,adjustment_type='Discount',amount=100,reason='Descuento de prueba autorizado'))
        fixture[mode]=dict(property=prop.name,stay=entered['stay'],room=room.room_number,
                           accepted_amount='3800.00' if mode=='Hotel' else '750.00',pricing={r.name:r.pricing for r in api.stay_detail(entered['stay'])['charges']})
        with operation():
            rate.title='Tarifa actual modificada';rate.amount=9999;rate.grace_minutes=0;rate.rounding_minutes=15;rate.save()
            if mode=='Hotel':
                seasonal.title='Temporada actual modificada';seasonal.amount=8888;seasonal.save()
    frappe.db.commit()
    fixture['hashes']=hashes()
    FIXTURE.write_text(json.dumps(fixture,default=str,sort_keys=True));FIXTURE.chmod(0o600)
    print('Fixture API sintético: hotel 3800 menos descuento 100; motel 600 + 150; tarifarios modificados después. Sin facturas, pagos ni turnos.')


def inspect():
    fixture=json.loads(FIXTURE.read_text())
    assert hashes()==fixture['hashes'],'La consulta no debe modificar negocio ni Version'
    from hospitality_suite.pricing import decimal
    proof=dict(site=SITE,synthetic=True,fixture_source='API',pages_are_read_only=True,tables_unchanged=len(fixture['hashes']),cases={})
    for mode in ('Hotel','Motel'):
        case=fixture[mode]
        detail=api.stay_detail(case['stay'])
        # The user's later terminology change adds mode_label to the read model;
        # retain the original fixture and compare every original price field.
        projected={r.name:{k:v for k,v in r.pricing.items() if k!='mode_label'} for r in detail['charges']}
        assert projected==case['pricing']
        assert all(r.pricing.get('mode_label')==('Hotel' if mode=='Hotel' else 'Por tiempo') for r in detail['charges'])
        assert decimal(detail['stay'].amount)==decimal(case['accepted_amount'])
        text=canonical(case['pricing'])
        assert 'actual modificada' not in text
        if mode=='Hotel':
            assert 'Temporada aceptada' in text and 'Cortesía autorizada' not in text
            assert 'Descuento autorizado' in text and 'Descuento de prueba autorizado' in text
            assert sum(decimal(r.amount) for r in detail['charges'])==3700
        else:
            assert sum(decimal(r.amount) for r in detail['charges'])==750
            assert 'Fracciones aceptadas: 2 de 30 min.' in text and 'Tolerancia aceptada: 10 min' in text
        proof['cases'][mode]=dict(stay=case['stay'],room=case['room'],accepted_amount=case['accepted_amount'],
                                 actual_charge_amounts=[str(r.amount) for r in detail['charges']],pricing={r.name:r.pricing for r in detail['charges']})
        proof['terminology_change_preserves_original_pricing_fields']=True
    for dt in ('Sales Invoice','Payment Entry','HS Payment','HS Shift','Journal Entry','GL Entry','Stock Ledger Entry'):
        assert fixture['hashes'][dt]==baseline['tables'][dt],dt
    assert hashes()==fixture['hashes']
    if PROOF.exists():
        previous=json.loads(PROOF.read_text())
        if 'pdfs' in previous:proof['pdfs']=previous['pdfs']
        if 'pdf_asset_origin' in previous:proof['pdf_asset_origin']=previous['pdf_asset_origin']
    return fixture,proof


try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler
    frappe.set_user('Administrator')
    if args.action=='prepare':
        prepare()
    else:
        fixture,proof=inspect()
        if args.action=='pdf':
            from pypdf import PdfReader
            os.environ['PATH']=str(BENCH/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
            frappe.local.lang='es'
            # CLI has no request host/port; Qt does not resolve *.localhost.
            # Serve native print assets from the fixed preview, process-local.
            frappe.conf.host_name='http://127.0.0.1:8089'
            output=ROOT/'output/pdf';output.mkdir(parents=True,exist_ok=True)
            pdfs=[]
            for mode in ('Hotel','Motel'):
                pdf=frappe.get_print('HS Stay',fixture[mode]['stay'],print_format='HS Cuenta de estancia',as_pdf=True)
                path=output/('cuenta-historica-'+('hotel' if mode=='Hotel' else 'por-tiempo')+'.pdf');path.write_bytes(pdf)
                pages=PdfReader(io.BytesIO(pdf)).pages;text=''.join(p.extract_text() or '' for p in pages)
                assert 'Cálculo histórico del precio' in text and 'Importe histórico de referencia' in text
                assert 'actual modificada' not in text
                if mode=='Hotel':assert 'Temporada aceptada' in text and 'Descuento autorizado' in text and '3,700.00' in text
                else:assert 'Fracciones aceptadas: 2 de 30 min.' in text and '750.00' in text and 'Por tiempo' in text
                pdfs.append(dict(mode=mode,path=str(path.relative_to(ROOT)),pages=len(pages),sha256=hashlib.sha256(pdf).hexdigest()))
            proof['pdfs']=pdfs
            proof['pdf_asset_origin']='http://127.0.0.1:8089 (process-local CLI setting)'
            assert hashes()==fixture['hashes']
        PROOF.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(dict(site=SITE,tables_unchanged=proof['tables_unchanged'],cases=list(proof['cases']),pdfs=proof.get('pdfs',[]))))
finally:
    frappe.db.rollback();frappe.destroy()
