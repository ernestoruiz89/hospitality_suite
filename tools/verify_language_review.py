"""Read-only language metadata/extraction proof on the two isolated installed sites."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path

import frappe
from hospitality_suite.schema import SCHEMA,STANDARD_SCOPED
from hospitality_suite.schema_labels import FIELD_LABELS

BENCH=Path('/home/frappe/benches/hospitality-bench');ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--output',default='docs/evidence/language-review-installed.json');args=parser.parse_args()
sources={}
for path in sorted((ROOT/'hospitality_suite').rglob('*.py')):
    if 'tests' in path.parts:continue
    raw=path.read_bytes();ast.parse(raw,filename=str(path));sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest()
surfaces=[*sorted((ROOT/'hospitality_suite/public/js').glob('*.js')),ROOT/'hospitality_suite/www/hospitality.js',
          *sorted((ROOT/'hospitality_suite/templates/print').glob('*.html')),*sorted((ROOT/'hospitality_suite/www').glob('*.html'))]
proof=dict(python_sources=len(sources),source_sha256={**sources,**{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in surfaces}},
           desk_modules=len(list((ROOT/'hospitality_suite/public/js').glob('*.js'))),portal_modules=1,templates=11,field_names=len(FIELD_LABELS),sites={},
           review='Manual classification of secondary captions versus stored/API values; source inventory complements tests, it does not prove every UI flow.',
           full_other_language_pack=False)
assert len(surfaces)==proof['desk_modules']+proof['portal_modules']+proof['templates']
expected={'hs_property':'Establecimiento de alojamiento','hs_stay':'Estancia de alojamiento','hs_shift':'Turno de caja',
          'hs_folio':'Cuenta de estancia','hs_booking':'Reserva de alojamiento'}
targets={'hs_property':'HS Property','hs_stay':'HS Stay','hs_shift':'HS Shift','hs_folio':'HS Folio','hs_booking':'HS Booking'}
os.chdir(BENCH/'sites')
for site,database in [('hospitality.localhost','hospitality_dev'),('hospitality-acceptance.localhost','hospitality_acceptance')]:
    frappe.init(site=site,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        assert frappe.conf.db_name==database and frappe.conf.allow_tests
        fields=0
        for dt,spec in SCHEMA.items():
            meta=frappe.get_meta(dt)
            for df in spec['fields']:
                actual=meta.get_field(df['fieldname']);assert actual.label==df['label'],(site,dt,df['fieldname'])
                if df['fieldtype']=='Select':assert actual.options==df['options']
                fields+=1
        links=0
        for dt in STANDARD_SCOPED:
            meta=frappe.get_meta(dt)
            for field,label in expected.items():
                actual=meta.get_field(field)
                assert actual.label==label and actual.options==targets[field] and actual.fieldtype=='Link',(site,dt,field)
                assert actual.no_copy and actual.print_hide,(site,dt,field)
                links+=1
        frappe.local.lang='es'
        assert frappe._('Active',context='HS Stay')=='Alojado'
        assert frappe._('Active',context='HS Allocation')=='Activa'
        assert frappe._('Laundry',context='Stock Entry')=='Lavandería'
        raw_name=frappe.db.get_value('Item','HS-DEMO-EXTRA-HOUR','item_name')
        if site=='hospitality-acceptance.localhost':assert raw_name=='Hora adicional de motel'
        proof['sites'][site]=dict(doctypes=len(SCHEMA),fields_checked=fields,bridge_doctypes=len(STANDARD_SCOPED),bridge_labels_checked=links,
                                 stored_select_options_preserved=True,demo_alias_fixture_present=raw_name is not None,
                                 raw_item_preservation_evidence='language-review-upgrade.json',mutations=False)
    finally:frappe.db.rollback();frappe.destroy()
(ROOT/args.output).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:v for k,v in proof.items() if k!='source_sha256'},ensure_ascii=False))
