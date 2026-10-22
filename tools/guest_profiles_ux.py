"""Policy-only fixture; all new guest registrations/corrections come from Pages."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import frappe
from hospitality_suite import api
from hospitality_suite.service import operation

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
BASE=BENCH/'.hospitality-guest-profiles-ux-baseline.json'
FIXTURE=BENCH/'.hospitality-guest-profiles-ui-fixture.json'
PROOF=ROOT/'docs/evidence/guest-profiles-items-ui.json'
ACTOR='receptionist@hospitality.example.invalid'
NAMES=dict(optional='Persona UX-GUEST-OPTIONAL-001',optional_updated='Persona UX-GUEST-OPTIONAL-CORREGIDA',
           required='Persona UX-GUEST-REQUIRED-001')
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','checkpoint','inspect'])
parser.add_argument('--stage',choices=['optional-created','optional-updated','required-rejected','required-created','final'],default='final')
args=parser.parse_args()
assert BASE.is_file(),'Conserve el respaldo inicial con archivos'
baseline=json.loads(BASE.read_text())
os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()


def hashes():
    result={}
    for dt in sorted(set(baseline['tables'])|{'Version'}):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        result[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    return result


def write_fixture(fixture):
    if FIXTURE.exists():
        original=json.loads(FIXTURE.read_text())
        assert original['hashes']==fixture['hashes'] and original['properties']==fixture['properties']
    FIXTURE.write_text(json.dumps(fixture,ensure_ascii=False,sort_keys=True,default=str));FIXTURE.chmod(0o600)


try:
    assert frappe.conf.db_name=='hospitality_acceptance' and frappe.conf.allow_tests and frappe.conf.pause_scheduler
    frappe.set_user('Administrator')
    if args.action=='prepare':
        assert not FIXTURE.exists(),'No sustituya el fixture original'
        before=hashes();assert all(before[dt]==value for dt,value in baseline['tables'].items())
        properties={}
        with operation():
            for key,title,required in [('optional','Luna Demo · Por tiempo',0),('required','Hotel Jardín Demo',1)]:
                prop=frappe.get_doc('HS Property',{'property_name':title})
                if prop.guest_id_required!=required:prop.guest_id_required=required;prop.save()
                properties[key]=prop.name
        frappe.db.commit()
        write_fixture(dict(hashes=hashes(),properties=properties,checkpoints={}))
        print('Solo se configuró identificación: Hotel obligatoria, Por tiempo opcional. Registros de personas exclusivamente desde Page.')
    else:
        fixture=json.loads(FIXTURE.read_text());current=hashes()
        allowed={'HS Guest','Customer','Contact','Contact Email','Contact Phone','Dynamic Link','HS Request','HS Audit Event','Version'}
        assert all(value==fixture['hashes'][dt] for dt,value in current.items() if dt not in allowed)
        optional=frappe.db.get_value('HS Guest',{'full_name':NAMES['optional_updated' if args.stage!='optional-created' else 'optional']},'name')
        assert optional,'Registre primero la persona opcional desde Page'
        guest=frappe.get_doc('HS Guest',optional)
        assert guest.property==fixture['properties']['optional'] and guest.owner==guest.modified_by==ACTOR
        assert not guest.identity_number and not guest.identity_type and not guest.nationality and not guest.address
        assert guest.contact
        assert current['Address']==fixture['hashes']['Address']
        if args.stage=='optional-created':
            assert guest.phone=='00000000' and not guest.email
            assert 'optional-created' not in fixture['checkpoints']
            fixture['checkpoints']['optional-created']=dict(guest=guest.name,customer=guest.customer,contact=guest.contact,counts={dt:current[dt]['rows'] for dt in allowed if dt in current})
        else:
            original=fixture['checkpoints']['optional-created']
            assert (guest.name,guest.customer,guest.contact)==(original['guest'],original['customer'],original['contact'])
            assert guest.phone=='11111111' and guest.email=='guest-ux@example.invalid'
            contact=frappe.get_doc('Contact',guest.contact)
            assert contact.phone==guest.phone and contact.email_id==guest.email and contact.full_name==guest.full_name
        required=frappe.db.get_value('HS Guest',{'full_name':NAMES['required']},'name')
        extra=2 if args.stage in ('required-created','final') else 1
        assert current['HS Guest']['rows']==fixture['hashes']['HS Guest']['rows']+extra
        assert current['Customer']['rows']==fixture['hashes']['Customer']['rows']+extra
        assert current['Contact']['rows']==fixture['hashes']['Contact']['rows']+1
        if args.stage in ('required-created','final'):
            person=frappe.get_doc('HS Guest',required)
            assert person.property==fixture['properties']['required'] and person.owner==person.modified_by==ACTOR
            assert not person.phone and not person.email and not person.identity_type and not person.nationality and not person.contact and not person.address
            assert person.identity_number==('FICTICIA-UX-GUEST-REQUIRED-001' if args.stage=='required-created' else 'FICTICIA-UX-GUEST-CORREGIDA')
            if args.stage=='required-created':
                assert 'required-created' not in fixture['checkpoints']
                fixture['checkpoints']['required-created']=dict(guest=person.name,customer=person.customer)
            else:
                assert fixture['checkpoints']['required-created']==dict(guest=person.name,customer=person.customer)
        if args.stage=='required-rejected':assert not required
        unchanged=sum(current[dt]==fixture['hashes'][dt] for dt in current)
        proof=dict(site=SITE,synthetic=True,fixture_source='Policy configuration only',all_guest_creations_and_corrections_from_page=True,
                   stage=args.stage,actor=ACTOR,optional_guest=guest.name,required_guest=required,existing_identity_preserved=True,
                   unrequested_identification_and_addresses_absent=True,guests_added=extra,customers_added=extra,contacts_added=1,
                   no_new_people_on_correction=True,tables_compared=len(current),tables_unchanged=unchanged,
                   protected_operational_and_financial_tables_unchanged=True)
        if args.stage=='final':
            events=frappe.get_all('HS Audit Event',filters={'action':'Update guest','source_name':['in',[guest.name,required]]},fields=['reason','details','actor'])
            assert len(events)==2 and all(event.reason and event.actor==ACTOR for event in events)
            assert all('FICTICIA-' not in event.details for event in events)
            assert frappe.db.exists('Version',{'ref_doctype':'HS Guest','docname':required})
            proof.update(corrections_with_reason=2,native_guest_versions_present=True,audit_details_contain_field_names_only=True)
        write_fixture(fixture)
        PROOF.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback();frappe.destroy()
