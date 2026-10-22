"""One explicit timed-stay fixture; Page queries must preserve its entire state."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import uuid

import frappe
from frappe.utils import now_datetime

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
BASE=BENCH/'.hospitality-countdown-ux-baseline.json'
FIXTURE=BENCH/'.hospitality-countdown-ui-fixture.json'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','inspect']);args=parser.parse_args()
assert BASE.is_file()
baseline=json.loads(BASE.read_text())
os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()


def hashes():
    result={}
    for dt in sorted(set(baseline['tables'])|{'Version'}):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        result[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    return result


try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler
    frappe.set_user('Administrator')
    if args.action=='prepare':
        assert not FIXTURE.exists(),'Conserve el fixture original'
        before=hashes();assert all(before[dt]==value for dt,value in baseline['tables'].items())
        from hospitality_suite import api
        prop=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'M101'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(hours=3)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        result=api.execute(prop.name,'walk_in',uuid.uuid4().hex,values)
        frappe.db.commit()
        fixture=dict(stay=result['stay'],folio=result['folio'],room=room.name,room_number=room.room_number,
                     property=prop.name,hashes=hashes())
        FIXTURE.write_text(json.dumps(fixture,sort_keys=True));FIXTURE.chmod(0o600)
        print('Fixture API explícito: estancia Por tiempo M101, tres horas. No se presenta como registro desde Page.')
    else:
        fixture=json.loads(FIXTURE.read_text());current=hashes()
        assert current==fixture['hashes'],'La consulta de reloj debe conservar las 72 tablas del fixture'
        stay=frappe.get_doc('HS Stay',fixture['stay'])
        assert stay.status=='Active' and stay.room==fixture['room']
        charges=frappe.get_all('HS Charge',filters={'stay':stay.name},fields=['name','amount','status'])
        assert len(charges)==1 and charges[0].status=='Pending'
        assert not any(frappe.db.count(dt) for dt in ('HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry','HS Daily Close'))
        proof=dict(site=SITE,synthetic=True,fixture_source='Explicit API walk_in before Page inspection',
                   stay=stay.name,room_number=fixture['room_number'],starts_at=str(stay.starts_at),ends_at=str(stay.ends_at),
                   server_time=str(now_datetime()),system_timezone=frappe.utils.get_system_timezone(),currency=stay.currency,
                   amount=str(charges[0].amount),stay_status=stay.status,charge_status=charges[0].status,
                   all_fixture_tables_unchanged=True,tables_compared=len(current),charges=1,payments=0,invoices=0)
        (ROOT/'docs/evidence/countdown-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback();frappe.destroy()
