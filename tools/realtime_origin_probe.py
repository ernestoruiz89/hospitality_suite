"""Scoped native transactions for the two named-origin realtime checks."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import uuid

import frappe
from frappe.utils import now_datetime
from hospitality_suite.security import allowed_properties, realtime
from hospitality_suite.service import operation
from hospitality_suite.time import local

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['metadata','broadcast','guest','walk-in','inspect'])
parser.add_argument('--site',choices=['hospitality.localhost','hospitality-acceptance.localhost'],default='hospitality.localhost')
parser.add_argument('--token')
parser.add_argument('--defer',action='store_true')
parser.add_argument('--room',choices=['H101','H102'],default='H101')
parser.add_argument('--stage',choices=['first','final'],default='final')
args=parser.parse_args()
os.chdir(BENCH/'sites')
frappe.init(site=args.site,sites_path=str(BENCH/'sites'));frappe.connect()
try:
    expected='hospitality_dev' if args.site=='hospitality.localhost' else 'hospitality_acceptance'
    assert frappe.conf.db_name==expected and frappe.conf.allow_tests
    assert (BENCH/'.hospitality-realtime-origins-upgrade.json').is_file()
    if args.site=='hospitality-acceptance.localhost':
        assert frappe.conf.pause_scheduler and frappe.conf.hospitality_integration_test_site
        assert (BENCH/'.hospitality-realtime-origins-ux-baseline.json').is_file()
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    if args.action=='metadata':
        if args.site=='hospitality.localhost':
            scoped=json.loads((BENCH/'.hospitality-transport-users.json').read_text())
            for account in scoped.values():
                assert allowed_properties(account['user'])==[account['property']]
        print(json.dumps(dict(site=args.site,property=prop.name)))
    elif args.action in ('broadcast','guest'):
        if args.action=='guest':
            from hospitality_suite import api
            assert args.site=='hospitality-acceptance.localhost' and args.token and args.token.startswith('realtime-origins-') and len(args.token)<100
            frappe.set_user('receptionist@hospitality.example.invalid')
            result=api.create_guest(prop.name,dict(full_name='Prueba temporal '+args.token),uuid.uuid4().hex)
        else:
            assert args.site=='hospitality.localhost'
            realtime(prop.name)
            result=dict(property=prop.name,business_mutation=False)
        if args.defer:
            print(json.dumps(dict(ready=True)),flush=True)
            decision=sys.stdin.readline().strip()
            assert decision in ('commit','rollback')
        else:decision='commit'
        getattr(frappe.db,decision)()
        print(json.dumps(dict(decision=decision,**result)),flush=True)
    elif args.action=='walk-in':
        from hospitality_suite import api
        assert args.site=='hospitality-acceptance.localhost'
        assert not frappe.db.exists('HS Stay',{'room':frappe.db.get_value('HS Room',{'property':prop.name,'room_number':args.room}),'status':'Active'})
        now=now_datetime().replace(microsecond=0)
        with operation():
            prop.business_date=local(now,prop).date();prop.save()
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':args.room})
        guest=frappe.get_doc('HS Guest',{'property':prop.name,'full_name':['not like','Prueba temporal realtime-origins-%']})
        frappe.set_user('manager@hospitality.example.invalid')
        if args.room=='H101':
            assert not frappe.db.count('HS Shift')
            shift=api.execute(prop.name,'open_shift',uuid.uuid4().hex,dict(opening_amount=0))['shift']
        else:
            shift=frappe.get_doc('HS Shift',{'property':prop.name,'status':'Open'})
            api.execute(prop.name,'close_shift',uuid.uuid4().hex,dict(shift=shift.name,modified=str(shift.modified),denominations={'NIO':[dict(value=100,count=0)]}))
        values=dict(starts_at=str(now),ends_at=str(now+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        result=api.execute(prop.name,'walk_in',uuid.uuid4().hex,values)
        frappe.db.commit()
        print(json.dumps(dict(result,room_number=args.room,fixture_origin='Native API, not a UI-created check-in'),default=str))
    else:
        assert args.site=='hospitality-acceptance.localhost'
        counts={dt:frappe.db.count(dt) for dt in ['HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry']}
        stays=1 if args.stage=='first' else 2
        assert counts=={'HS Stay':stays,'HS Booking':stays,'HS Charge':stays,'HS Payment':0,'HS Shift':1,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0},counts
        assert frappe.db.get_value('HS Shift',{'property':prop.name},'status')==('Open' if args.stage=='first' else 'Closed')
        guests=frappe.get_all('HS Guest',filters={'full_name':['like','Prueba temporal realtime-origins-%']},pluck='name')
        assert len(guests)==3
        proof=dict(site=args.site,stage=args.stage,counts=counts,committed_transport_guests=len(guests),api_fixture_stays=stays,ui_created_operations=False,
                   external_providers_contacted=False,main_business_mutation=False)
        suffix='-first' if args.stage=='first' else ''
        (ROOT/f'docs/evidence/realtime-origins-ui{suffix}-data.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
finally:
    frappe.db.rollback();frappe.destroy()
