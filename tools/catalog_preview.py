"""Prepare or serve the fixed clean test site; never touch the main demo site."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-clean.localhost'
PORT=8089


def prepare():
    import frappe
    from frappe.utils import now_datetime
    os.chdir(BENCH/'sites')
    frappe.init(site=SITE,sites_path=str(BENCH/'sites'))
    frappe.connect()
    try:
        assert frappe.conf.allow_tests and frappe.conf.db_name=='hospitality_clean'
        frappe.set_user('Administrator')
        template=frappe.get_doc('Item','HS-DEMO-WATER')
        prefix='HS-CATALOG-QA-'
        existing=set(frappe.get_all('Item',filters={'name':['like',prefix+'%']},pluck='name'))
        stamp=now_datetime()
        fields=['name','item_code','item_name','item_group','stock_uom','is_stock_item','is_sales_item','is_purchase_item','disabled','is_fixed_asset','owner','creation','modified']
        values=[(prefix+f'{i:04}',prefix+f'{i:04}',f'Catálogo de prueba {i:04}',template.item_group,template.stock_uom,0,1,1,0,0,'Administrator',stamp,stamp) for i in range(605) if prefix+f'{i:04}' not in existing]
        if values:
            frappe.db.bulk_insert('Item',fields=fields,values=values)
        target=prefix+'0605'
        if target not in existing:
            frappe.get_doc(dict(doctype='Item',item_code=target,item_name='Servicio especial del catálogo',item_group=template.item_group,stock_uom=template.stock_uom,is_stock_item=0,is_sales_item=1,is_purchase_item=1)).insert()
        frappe.db.commit()
        proof=dict(site=SITE,synthetic=True,financial_operations=False,fixture_items=frappe.db.count('Item',{'name':['like',prefix+'%']}),
                   target=target,target_label=frappe.db.get_value('Item',target,'item_name'))
        print(json.dumps(proof,ensure_ascii=False))
    finally:
        frappe.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','start','stop'])
    args=parser.parse_args()
    config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
    assert config['db_name']=='hospitality_clean' and config.get('allow_tests')
    if args.action=='prepare':
        prepare()
        return
    state=BENCH/'.hospitality-run'
    pidfile=state/'catalog-web.pid'
    if args.action=='stop':
        if pidfile.exists():
            process=Path('/proc')/pidfile.read_text().strip()
            if process.exists():
                command=(process/'cmdline').read_bytes().decode(errors='replace')
                assert 'serve' in command and str(PORT) in command and SITE in command
                assert (process/'cwd').resolve() in (BENCH,BENCH/'sites')
                os.kill(int(process.name),signal.SIGTERM)
        print('Preview de catálogo detenido; sitio principal intacto')
        return
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1',PORT))!=0,'Puerto ocupado; no se reutiliza'
    with (state/'catalog-web.log').open('ab') as log:
        environment={**os.environ,'DEV_SERVER':'true'}
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port',str(PORT),'--noreload'],cwd=BENCH,env=environment,
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    pidfile.write_text(str(process.pid))
    print(f'Preview de pruebas: http://{SITE}:{PORT}/desk/hospitality-suite/hospitality-services')


if __name__=='__main__':
    main()
