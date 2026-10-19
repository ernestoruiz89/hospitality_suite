"""Read-only inventory of the installed model, roles, indexes and native runtime."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import frappe
import erpnext

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
os.chdir(BENCH/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_dev'
    frappe.set_user('Administrator')
    from hospitality_suite.schema import SCHEMA,PAGES,ROLES,STANDARD_SCOPED
    from hospitality_suite.security import ACTIONS
    core={}
    for app in ('frappe','erpnext'):
        folder=BENCH/'apps'/app
        def git(*args):
            return subprocess.check_output(['git','-C',str(folder),*args],text=True).strip()
        dirty=git('status','--porcelain')
        assert not dirty,app+' core has changes'
        core[app]=dict(version=frappe.__version__ if app=='frappe' else erpnext.__version__,commit=git('rev-parse','HEAD'),clean=True)
    model=[]
    for name,spec in SCHEMA.items():
        meta=frappe.get_meta(name)
        assert bool(meta.istable)==bool(spec.get('child')),name
        for expected in spec['fields']:
            actual=meta.get_field(expected['fieldname'])
            assert actual and actual.fieldtype==expected['fieldtype'],(name,expected['fieldname'])
            for key in ('options','reqd','unique'):
                if key in expected:
                    assert (actual.get(key) or '')==(expected[key] or ''),(name,expected['fieldname'],key)
        if not spec.get('child'):
            assert set(spec.get('roles',[])).issubset({r.role for r in meta.permissions}),name
        # Names are static SCHEMA identifiers, never request input.
        indexes=frappe.db.sql('SHOW INDEX FROM `tab'+name+'`',as_dict=True)
        grouped={}
        for row in sorted(indexes,key=lambda r:(r.Key_name,r.Seq_in_index)):
            index=grouped.setdefault(row.Key_name,dict(unique=not bool(row.Non_unique),columns=[]))
            index['columns'].append(row.Column_name)
        model.append(dict(doctype=name,child=bool(meta.istable),fields=len(spec['fields']),indexes=grouped))
    pages=[]
    for route,(title,roles) in PAGES.items():
        doc=frappe.get_doc('Page',route)
        assert doc.title==title and set(roles).issubset({r.role for r in doc.roles}),route
        pages.append(dict(route=route,title=doc.title,roles=sorted(r.role for r in doc.roles)))
    required=set(STANDARD_SCOPED)|{'Customer','Contact','Address','Item','Item Group','UOM','Price List','Company','Cost Center','Warehouse','Mode of Payment','GL Entry','Payment Ledger Entry','Stock Ledger Entry'}
    assert all(frappe.db.exists('DocType',dt) for dt in required)
    assert all(frappe.db.exists('Role',role) for role in ROLES)
    from frappe.utils.jinja_globals import bundled_asset
    assets=[]
    for name in ('hospitality.bundle.js','hospitality.bundle.css'):
        asset=BENCH/'sites'/bundled_asset(name).lstrip('/')
        assert asset.is_file(),str(asset)
        assets.append(dict(name=name,bytes=asset.stat().st_size,sha256=hashlib.sha256(asset.read_bytes()).hexdigest()))
    proof=dict(site=frappe.local.site,mutations=False,core=core,python=platform.python_version(),
               database=frappe.db.sql('SELECT VERSION()')[0][0],installed_apps=frappe.get_installed_apps(),
               roles=ROLES,actions=ACTIONS,model=model,pages=pages,native_doctypes=sorted(required),assets=assets)
    (ROOT/'docs/evidence/architecture-current.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(core=core,doctypes=len(model),pages=len(pages),roles=len(ROLES),native_doctypes=len(required),assets=len(assets)),ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
