"""Back up and restore only the empty acceptance site around a synthetic UX run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess

import frappe
from hospitality_suite.schema import SCHEMA

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
TARGET=BENCH/'sites'/SITE
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['before','prepare','inspect','restore','verify'])
parser.add_argument('--phase',choices=['service','pos','refund','guarantee','credits'],default='service')
args=parser.parse_args()
BASE=BENCH/f'.hospitality-{args.phase}-ux-baseline.json'
RECEIPT=BENCH/f'.hospitality-{args.phase}-ux-restored-receipt.json'
assert TARGET.resolve()==Path('/home/frappe/benches/hospitality-bench/sites/hospitality-acceptance.localhost')
config=json.loads((TARGET/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('allow_tests') and config.get('pause_scheduler')

if args.action=='restore':
    assert os.geteuid()==0,'La restauración nativa requiere el administrador local de MariaDB'
    assert ':8089 ' not in subprocess.check_output(['ss','-ltnp'],text=True),'Detenga primero el servidor temporal de UX'
    baseline=json.loads(BASE.read_text())
    backups=TARGET/'private/backups'
    for name,digest in baseline['backup_files'].items():
        path=(backups/name).resolve()
        assert path.parent==backups.resolve() and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    assert all(baseline[field] in baseline['backup_files'] for field in ('database','public_files','private_files'))
    config['db_socket']='/run/mysqld/mysqld.sock'
    (TARGET/'site_config.json').write_text(json.dumps(config,indent=1))
    (TARGET/'site_config.json').chmod(0o600)
    command=[str(BENCH/'env/bin/python'),'-m','frappe.utils.bench_helper','frappe','--site',SITE,'restore',str(backups/baseline['database']),
             '--db-root-username','root','--db-root-password','local-unix-socket-auth',
             '--with-public-files',str(backups/baseline['public_files']),'--with-private-files',str(backups/baseline['private_files'])]
    log=BENCH/f'.hospitality-{args.phase}-ux-restore.log'
    with log.open('w') as output:
        result=subprocess.run(command,cwd=BENCH/'sites',stdout=output,stderr=subprocess.STDOUT)
    if result.returncode==0:
        restored=json.loads((TARGET/'site_config.json').read_text())
        if baseline.get('original_host_name'):
            restored['host_name']=baseline['original_host_name']
        else:
            restored.pop('host_name',None)
        (TARGET/'site_config.json').write_text(json.dumps(restored,indent=1))
    log.chmod(0o600)
    owner=pwd.getpwnam('frappe')
    os.chown(log,owner.pw_uid,owner.pw_gid)
    for path in [TARGET]+list(TARGET.rglob('*')):
        assert path.resolve().is_relative_to(TARGET.resolve())
        os.chown(path,owner.pw_uid,owner.pw_gid)
    if result.returncode==0:
        RECEIPT.write_text(json.dumps(dict(site=SITE,baseline_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest())))
        RECEIPT.chmod(0o600)
        os.chown(RECEIPT,owner.pw_uid,owner.pw_gid)
    print('Restauración del sitio de aceptación:',result.returncode)
    raise SystemExit(result.returncode)

os.chdir(BENCH/'sites')
frappe.init(site=SITE,sites_path=str(BENCH/'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    native=['Company','Account','Cost Center','Warehouse','Customer','Supplier','Contact','Address','Dynamic Link','Item','Item Price','Item Reorder','Asset','File',
            'Sales Invoice','Sales Invoice Item','Sales Taxes and Charges','Payment Entry','Payment Entry Reference','Payment Entry Deduction',
            'Journal Entry','Journal Entry Account','Stock Entry','Stock Entry Detail','Stock Reconciliation','Stock Reconciliation Item','Bin',
            'GL Entry','Payment Ledger Entry','Stock Ledger Entry','Purchase Order','Purchase Order Item','Purchase Receipt','Purchase Receipt Item','Purchase Invoice','Purchase Invoice Item']
    tables={}
    for dt in sorted(set(SCHEMA)|set(native)):
        rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        tables[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    if args.action=='before':
        assert all(tables[dt]['rows']==0 for dt in ('HS Stay','HS Booking','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry'))
        frappe.db.rollback()
        with (BENCH/f'.hospitality-{args.phase}-ux-backup.log').open('w') as output:
            subprocess.run(['/home/frappe/.local/bin/bench','--site',SITE,'backup','--with-files'],cwd=BENCH,stdout=output,stderr=subprocess.STDOUT,check=True)
        backups=TARGET/'private/backups'
        database=max(backups.glob('*-database.sql.gz'),key=lambda p:p.stat().st_mtime)
        prefix=database.name.removesuffix('-database.sql.gz')
        public=next(p for p in backups.glob(prefix+'-files.*') if p.suffix in ('.tar','.tgz'))
        private=next(p for p in backups.glob(prefix+'-private-files.*') if p.suffix in ('.tar','.tgz'))
        files=[database,public,private,backups/(prefix+'-site_config_backup.json')]
        for path in files:path.chmod(0o600)
        baseline=dict(tables=tables,database=database.name,public_files=public.name,private_files=private.name,original_host_name=config.get('host_name'),
                      backup_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
        BASE.write_text(json.dumps(baseline,sort_keys=True))
        BASE.chmod(0o600)
        print('Respaldo previo al recorrido UX, 70 tablas sin operaciones')
    elif args.action=='prepare':
        assert args.phase=='pos' and BASE.is_file() and tables==json.loads(BASE.read_text())['tables']
        from hospitality_suite import api
        import uuid
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        assert not prop.tax_template
        method=frappe.get_doc('HS Payment Method',{'property':prop.name,'is_cash':1,'currency':'NIO'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        shift=api.execute(prop.name,'open_shift',uuid.uuid4().hex,dict(opening_amount=100))['shift']
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=prop.company,hs_property=prop.name,hs_shift=shift,customer=guest.customer,
                    currency='NIO',debit_to=prop.receivable_account,cost_center=prop.cost_center,is_pos=1,update_stock=1,account_for_change_amount=method.account))
        invoice.append('items',dict(item_code='HS-DEMO-WATER',qty=2,rate=30,cost_center=prop.cost_center,warehouse=prop.warehouse))
        invoice.append('payments',dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=100))
        invoice.set_missing_values()
        invoice.insert().submit()
        fixture=BENCH/'.hospitality-pos-ux-fixture.json'
        fixture.write_text(json.dumps(dict(property=prop.name,shift=shift,invoice=invoice.name)))
        fixture.chmod(0o600)
        frappe.db.commit()
        print('Fixture POS sintético: fondo 100, venta 60, recibido 100, vuelto 40; sin HS Payment ni Payment Entry')
    elif args.action=='inspect' and args.phase=='pos':
        fixture=json.loads((BENCH/'.hospitality-pos-ux-fixture.json').read_text())
        shift=frappe.get_doc('HS Shift',fixture['shift'])
        from hospitality_suite.cashier import expected
        from hospitality_suite.native_pos import movements
        assert shift.status=='Closed' and shift.expected_amount==shift.counted_amount==160 and shift.difference==0
        assert expected(shift)=={'NIO':'160.00'}
        assert frappe.db.count('HS Payment')==frappe.db.count('Payment Entry')==0
        native=movements(fixture['property'])
        assert len(native)==1 and native[0]['amount']==60 and native[0]['shift']==shift.name
        os.environ['PATH']=str(BENCH/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
        frappe.local.lang='es'
        pdf=frappe.get_print('HS Shift',shift.name,print_format='HS Arqueo',as_pdf=True)
        output=ROOT/'output/native-pos'
        output.mkdir(parents=True,exist_ok=True)
        (output/'shift.pdf').write_bytes(pdf)
        import io
        from pypdf import PdfReader
        pages=PdfReader(io.BytesIO(pdf)).pages
        text=''.join(page.extract_text() or '' for page in pages)
        assert 'Movimientos POS vigentes' in text and all(value in text for value in ('60.00','160.00'))
        proof=dict(site=SITE,synthetic=True,fixture_origin='ERPNext Sales Invoice controller',closed_from_page=True,
                   opening='100.00',receipt='60.00',tendered='100.00',change='40.00',expected='160.00',counted='160.00',difference='0.00',
                   operational_payments=0,payment_entries=0,invoice=fixture['invoice'],shift=shift.name,pdf_pages=len(pages),pdf_sha256=hashlib.sha256(pdf).hexdigest())
        (ROOT/'docs/evidence/pos-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
    elif args.action=='inspect':
        from hospitality_suite.pricing import decimal
        prop=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        assert prop.extra_hour_item=='HS-DEMO-EXTRA-HOUR'
        rows=frappe.get_all('HS Stay',filters={'property':prop.name},fields=['name','amount','room','quote_snapshot'])
        assert len(rows)==1 and decimal(rows[0].amount)==600
        stay=rows[0]
        charges=frappe.get_all('HS Charge',filters={'stay':stay.name},fields=['description','item','quantity','amount','status'])
        assert len(charges)==2 and {r.status for r in charges}=={'Pending'}
        assert sum(decimal(r.amount) for r in charges if r.item==prop.lodging_item)==450
        assert sum(decimal(r.amount) for r in charges if r.item==prop.extra_hour_item)==150
        for row in charges:row['item_name']=frappe.db.get_value('Item',row.item,'item_name')
        proof=dict(site=SITE,synthetic=True,stay=stay.name,room=frappe.db.get_value('HS Room',stay.room,'room_number'),
                   amount=str(stay.amount),charges=charges,accepted_item=frappe.parse_json(stay.quote_snapshot)['charge_items']['extra_hour_item'],
                   invoices=frappe.db.count('Sales Invoice'),payments=frappe.db.count('HS Payment'),ui_only_entry=True)
        assert proof['invoices']==proof['payments']==0
        os.environ['PATH']=str(BENCH/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')
        frappe.local.lang='es'
        pdf=frappe.get_print('HS Stay',stay.name,print_format='HS Cuenta de estancia',as_pdf=True)
        output=ROOT/'output/service-items'
        output.mkdir(parents=True,exist_ok=True)
        (output/'account.pdf').write_bytes(pdf)
        import io
        from pypdf import PdfReader
        pages=PdfReader(io.BytesIO(pdf)).pages
        text=''.join(page.extract_text() or '' for page in pages)
        assert 'Horas adicionales de motel' in text and all(value in text for value in ('150.00','450.00','600.00'))
        proof.update(pdf_pages=len(pages),pdf_sha256=hashlib.sha256(pdf).hexdigest(),pdf='output/service-items/account.pdf')
        (ROOT/'docs/evidence/service-items-ui.json').write_text(json.dumps(proof,default=str,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,default=str,ensure_ascii=False))
    else:
        receipt=json.loads(RECEIPT.read_text())
        assert receipt['site']==SITE and receipt['baseline_sha256']==hashlib.sha256(BASE.read_bytes()).hexdigest()
        expected=json.loads(BASE.read_text())['tables']
        assert tables==expected,[dt for dt in tables if tables[dt]!=expected.get(dt)]
        proof=dict(site=SITE,restored=True,tables=len(tables),rows=sum(r['rows'] for r in tables.values()),
                   aggregate_sha256=hashlib.sha256(json.dumps(tables,sort_keys=True).encode()).hexdigest(),
                   stay_records=frappe.db.count('HS Stay'),invoices=frappe.db.count('Sales Invoice'),payments=frappe.db.count('HS Payment'))
        (ROOT/f'docs/evidence/{args.phase}-ux-restored.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
finally:
    frappe.db.rollback()
    frappe.destroy()
