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
parser.add_argument('--phase',choices=['service','pos','refund','guarantee','credits','mixed','accounting','forms','periodic','billing','board','availability','drafts','tariffs','account-summary','guest-profiles','background-jobs','countdown','finance-audit','housekeeping-audit','permissions-audit','audit-history','inventory-audit','closing-checks','navigation','room-states','room-history','role-acceptance','language-review','keyboard-review','secondary-forms','action-context','page-activity','friendly-links','print-delivery','realtime-origins','provider-contracts','numeric-review'],default='service')
parser.add_argument('--stage',choices=['partial','confirmed','discarded'],default='discarded')
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
        if args.phase in ('forms','periodic','billing','board','availability','drafts','tariffs','account-summary','guest-profiles','background-jobs','countdown','finance-audit','housekeeping-audit','permissions-audit','audit-history','inventory-audit','closing-checks','navigation','room-states','room-history','role-acceptance','language-review','keyboard-review','secondary-forms','action-context','page-activity','friendly-links','print-delivery','realtime-origins','provider-contracts','numeric-review'):assert not BASE.exists(),'Conserve el respaldo previo al recorrido de interfaz'
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
        print('Respaldo previo al recorrido UX,',len(tables),'tablas sin operaciones')
    elif args.action=='prepare' and args.phase=='availability':
        from hospitality_suite import api
        from hospitality_suite.time import now_local
        from datetime import datetime,time,timedelta
        import uuid
        assert BASE.is_file() and tables==json.loads(BASE.read_text())['tables']
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        category=frappe.db.get_value('HS Category',{'property':prop.name})
        room_count=frappe.db.count('HS Room',{'property':prop.name,'category':category,'active':1})
        assert room_count>1
        day=now_local(prop).date()+timedelta(days=2)
        values=dict(starts_at=str(datetime.combine(day,time(14))),ends_at=str(datetime.combine(day+timedelta(days=1),time(12))),
                    guest=guest.name,customer=guest.customer,instructions='UX-AVAILABILITY-001 consulta por cantidad',
                    rooms=[dict(category=category,people=1) for _ in range(room_count-1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        api.execute(prop.name,'reserve',uuid.uuid4().hex,values)
        frappe.db.commit()
        fixture_path=BENCH/'.hospitality-availability-ui-fixture.json'
        assert not fixture_path.exists(),'Conserve la huella del fixture original'
        fixture={}
        for dt in [*tables,'Version']:
            rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            fixture[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        fixture_path.write_text(json.dumps(fixture,sort_keys=True))
        fixture_path.chmod(0o600)
        print('Fixture API:',room_count-1,'habitaciones de categoría en una reserva grupal, un cupo restante; sin asignación física, estancia ni cobro.')
    elif args.action=='prepare' and args.phase=='board':
        from hospitality_suite import api
        from datetime import datetime,time,timedelta
        import uuid
        assert BASE.is_file() and tables==json.loads(BASE.read_text())['tables']
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        from hospitality_suite.time import now_local
        day=now_local(prop).date()
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        for number,start,end,action in [('H101',datetime.combine(day-timedelta(days=1),time(14)),datetime.combine(day,time(12)),'walk_in'),
                                       ('H102',datetime.combine(day+timedelta(days=1),time(14)),datetime.combine(day+timedelta(days=2),time(12)),'reserve'),
                                       ('H103',datetime.combine(day,time(14)),datetime.combine(day+timedelta(days=1),time(12)),'reserve')]:
            room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':number})
            values=dict(starts_at=str(start),ends_at=str(end),guest=guest.name,customer=guest.customer,rooms=[dict(category=room.category,room=room.name,people=1)])
            values['acceptance']=api.preview(prop.name,values)['acceptance']
            api.execute(prop.name,action,uuid.uuid4().hex,values)
        assert api.stay_board(prop.name)['counts']==dict(hosted=1,arrivals=1,departures=1,accounts=1)
        frappe.db.commit()
        print('Fixture API de tablero: H101 alojado/salida hoy, H102 llegada mañana, H103 llegada hoy; sin facturas ni pagos.')
    elif args.action=='prepare' and args.phase=='billing':
        from hospitality_suite import api
        from frappe.utils import now_datetime
        from datetime import timedelta
        import uuid
        assert BASE.is_file()
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        assert prop.lodging_charge_policy=='Nightly'
        assert frappe.db.count('HS Stay')==frappe.db.count('Sales Invoice')==1
        assert frappe.get_all('Sales Invoice',pluck='grand_total')==[0]
        assert frappe.db.count('HS Payment')==frappe.db.count('HS Shift')==0
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H102'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        api.save_setup(prop.name,'rate',dict(title='Tarifa positiva UX Facturación',category=room.category,mode='Hotel',currency='NIO',amount=1250,priority=30,active=1),uuid.uuid4().hex)
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        entered=api.execute(prop.name,'walk_in',uuid.uuid4().hex,values)
        assert frappe.db.get_value('HS Stay',entered['stay'],'amount')==1250
        frappe.db.commit()
        print('Fixture positivo por API: H102, una noche/1250, sin factura ni cobro.')
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
    elif args.action=='inspect' and args.phase=='drafts':
        # This phase has no API fixture: the reception Page creates each record.
        assert BASE.is_file()
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        path=ROOT/'docs/evidence/drafts-items-ui.json'
        proof=json.loads(path.read_text()) if path.exists() else dict(site=SITE,synthetic=True,source='Reception Page',stages={})
        bookings=frappe.get_all('HS Booking',fields=['name','status','customer','guest','starts_at','ends_at','instructions','draft_data','quote_snapshot','amount','modified'])
        main=[b for b in bookings if b.instructions=='UX-DRAFT-001 solicitud parcial']
        assert len(main)==1
        booking=main[0]
        empty={dt:frappe.db.count(dt) for dt in ('HS Stay','HS Folio','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry','GL Entry','Stock Ledger Entry')}
        baseline=json.loads(BASE.read_text())['tables']
        assert all(tables[dt]==baseline[dt] for dt in empty),empty
        stage=dict(booking=booking.name,status=booking.status,amount=str(booking.amount),
                   allocation_count=frappe.db.count('HS Allocation',{'booking':booking.name,'status':'Active'}),unchanged_financial_and_stay_tables=empty)
        if args.stage=='partial':
            assert len(bookings)==1 and booking.status=='Draft' and not booking.amount
            assert not booking.customer and not booking.starts_at and not booking.ends_at and not booking.quote_snapshot
            assert booking.draft_data and stage['allocation_count']==0
            proof['original_booking']=booking.name
            stage.update(customer_missing=True,dates_missing=True,accepted_quote=False)
        else:
            assert booking.name==proof['original_booking'] and booking.status=='Confirmed' and booking.amount==1500
            assert booking.customer and booking.starts_at and booking.ends_at and booking.quote_snapshot and not booking.draft_data
            assert stage['allocation_count']==1
            stage['same_record_confirmed']=True
            if args.stage=='discarded':
                discarded=[b for b in bookings if b.instructions=='UX-DRAFT-002 descartar']
                assert len(bookings)==2 and len(discarded)==1 and discarded[0].status=='Cancelled' and discarded[0].draft_data
                discarded=frappe.get_doc('HS Booking',discarded[0].name)
                assert discarded.reason=='Solicitud de prueba no continuada' and not discarded.amount and not discarded.quote_snapshot
                assert not frappe.db.count('HS Allocation',{'booking':discarded.name})
                assert frappe.db.exists('HS Audit Event',{'source_name':discarded.name,'action':'Discard booking draft'})
                from hospitality_suite import api
                assert not api.report(prop.name,'Cancelaciones y no presentaciones')
                stage.update(discarded_booking=discarded.name,discard_reason=discarded.reason,cancellation_report_rows=0)
        stage['native_versions']=frappe.db.count('Version',{'ref_doctype':'HS Booking'})
        proof['stages'][args.stage]=stage
        path.write_text(json.dumps(proof,default=str,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(dict(stage=args.stage,booking_status=booking.status,allocations=stage['allocation_count'],financial_and_stay_tables_unchanged=True)))
    elif args.action=='inspect' and args.phase=='availability':
        from hospitality_suite import api
        from hospitality_suite.time import local
        booking=frappe.get_doc('HS Booking',{'instructions':'UX-AVAILABILITY-001 consulta por cantidad'})
        prop=frappe.get_doc('HS Property',booking.property)
        values=dict(property_name=prop.name,starts_at=local(booking.starts_at,prop).isoformat(),ends_at=local(booking.ends_at,prop).isoformat(),category=booking.rooms[0].category,people=1)
        two=api.availability_search(**values,quantity=2)
        one=api.availability_search(**values,quantity=1)
        room_count=frappe.db.count('HS Room',{'property':prop.name,'category':booking.rooms[0].category,'active':1})
        assert two['available']==one['available']==1 and not two['enough'] and one['enough']
        assert two['physical_available']==room_count and not two['needs_assignment_review']
        assert len(booking.rooms)==room_count-1 and frappe.db.count('HS Booking')==1 and frappe.db.count('HS Allocation')==room_count-1
        assert all(frappe.db.count(dt)==0 for dt in ('HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry','HS Daily Close'))
        current={}
        for dt in tables:
            rows=frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            current[dt]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        assert tables==current
        fixture=json.loads((BENCH/'.hospitality-availability-ui-fixture.json').read_text())
        assert current=={dt:value for dt,value in fixture.items() if dt!='Version'}
        versions=frappe.db.sql('SELECT * FROM `tabVersion` ORDER BY name',as_dict=True)
        raw=json.dumps(versions,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        assert fixture['Version']==dict(rows=len(versions),sha256=hashlib.sha256(raw).hexdigest())
        proof=dict(site=SITE,synthetic=True,fixture_source='API',booking=booking.name,roomless_allocations=room_count-1,
                   query_two=two,query_one=one,query_business_mutations=False,tables_equal_after_query=len(tables),tables_equal_after_ui_with_version=len(fixture),
                   stays=0,charges=0,payments=0,invoices=0,business_date=str(prop.business_date))
        (ROOT/'docs/evidence/availability-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print('Consulta de una/dos habitaciones: cupo 1 y',room_count,'opciones físicas; 71 tablas sin cambios por consulta y sin operaciones financieras.')
    elif args.action=='inspect' and args.phase=='board':
        from hospitality_suite import api
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        stays=frappe.get_all('HS Stay',filters={'property':prop.name},fields=['room','status','owner'])
        assert len(stays)==2 and {row.status for row in stays}=={'Active'}
        assert sorted(row.owner for row in stays)==['Administrator','receptionist@hospitality.example.invalid']
        assert all(frappe.db.count(dt)==0 for dt in ('Sales Invoice','HS Payment','HS Shift','Payment Entry','Journal Entry','HS Daily Close','HS Cleaning Task'))
        board=api.stay_board(prop.name)
        assert board['counts']==dict(hosted=2,arrivals=0,departures=1,accounts=2)
        assert frappe.db.count('HS Charge')==2 and frappe.db.count('HS Charge',{'status':'Pending'})==2
        proof=dict(site=SITE,synthetic=True,fixture_origin='API: three bookings and one initial stay',
                   second_entry_from_page=True,entry_actor='HS Receptionist',counts=board['counts'],
                   active_rooms=sorted(frappe.db.get_value('HS Room',row.room,'room_number') for row in stays),
                   future_arrival_room='H102',invoices=0,payments=0,shifts=0,business_date=str(prop.business_date))
        (ROOT/'docs/evidence/board-items-ui.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
    elif args.action=='inspect' and args.phase=='billing':
        from hospitality_suite.accounting import folio_balance
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        stays=frappe.get_all('HS Stay',filters={'property':prop.name},fields=['name','room','status','amount','owner'])
        assert len(stays)==2 and {row.status for row in stays}=={'Active'}
        invoices=frappe.get_all('Sales Invoice',filters={'hs_property':prop.name},fields=['name','grand_total','outstanding_amount','docstatus','owner','hs_stay','hs_folio'])
        assert len(invoices)==2 and sorted(row.grand_total for row in invoices)==[0,1250]
        assert sorted(row.outstanding_amount for row in invoices)==[0,1250]
        assert all(row.docstatus==1 and row.owner=='manager@hospitality.example.invalid' for row in invoices)
        assert all(folio_balance(row.hs_folio)['scheduled']=='0.00' for row in invoices)
        assert frappe.db.count('HS Charge')==3 and frappe.db.count('HS Charge',{'status':'Invoiced'})==3
        assert all(frappe.db.count(dt)==0 for dt in ('HS Shift','HS Payment','Payment Entry','Journal Entry','HS Cleaning Task','HS Daily Close'))
        zero=next(row for row in stays if row.amount==0)
        positive=next(row for row in stays if row.amount==1250)
        assert zero.owner=='manager@hospitality.example.invalid' and positive.owner=='Administrator'
        proof=dict(site=SITE,synthetic=True,zero_stay_entered_from_page=True,positive_stay_origin='API fixture',
                   both_invoices_emitted_from_page=True,invoice_totals=['0.00','1250.00'],outstanding_totals=['0.00','1250.00'],
                   active_stays=2,invoiced_charges=3,shifts=0,payments=0,payment_entries=0,cleaning_tasks=0,
                   business_date=str(prop.business_date))
        (ROOT/'docs/evidence/billing-items-ui.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
    elif args.action=='inspect' and args.phase=='periodic':
        from hospitality_suite.accounting import folio_balance
        from hospitality_suite.pricing import decimal
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        assert prop.lodging_charge_policy=='Nightly' and str(prop.business_date)=='2026-10-19'
        assert frappe.db.count('HS Stay')==frappe.db.count('HS Booking')==1
        stay=frappe.get_doc('HS Stay',{'property':prop.name})
        assert stay.lodging_charge_policy=='Nightly' and stay.amount==4500
        charges=frappe.get_all('HS Charge',filters={'stay':stay.name},fields=['name','status','amount','period_key','service_date','business_date'],order_by='service_date asc')
        assert len(charges)==3 and len({row.period_key for row in charges})==3
        assert [row.status for row in charges]==['Pending','Scheduled','Scheduled']
        assert [str(row.service_date) for row in charges]==['2026-10-19','2026-10-20','2026-10-21']
        assert all(row.amount==1500 and row.service_date==row.business_date for row in charges)
        folio=frappe.get_doc('HS Folio',{'stay':stay.name})
        balance=folio_balance(folio.name)
        assert balance['pending']=='1500.00' and balance['scheduled']=='3000.00' and balance['outstanding']=='4500.00'
        assert frappe.db.count('Sales Invoice')==frappe.db.count('Payment Entry')==frappe.db.count('HS Payment')==0
        assert frappe.db.count('HS Audit Event',{'property':prop.name,'action':'Generate nightly charges'})==1
        close=frappe.get_doc('HS Daily Close',{'property':prop.name})
        assert close.status=='Review'
        proof=dict(site=SITE,synthetic=True,ui_only_entry=True,policy_saved_and_reopened=True,stay_amount='4500.00',
                   nights=3,generated=1,scheduled=2,pending_amount=balance['pending'],scheduled_amount=balance['scheduled'],
                   outstanding=balance['outstanding'],generation_batches=1,review_repeated_from_page=True,invoices=0,payments=0,
                   business_date=str(prop.business_date),close_status=close.status)
        (ROOT/'docs/evidence/periodic-items-ui.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof))
    elif args.action=='inspect' and args.phase=='forms':
        from hospitality_suite.accounting import folio_balance
        from hospitality_suite.cashier import expected
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        assert prop.brand_name=='Hotel UX Formularios'
        rate=frappe.get_doc('HS Rate',{'property':prop.name,'title':'Tarifa UX Formularios'})
        assert rate.amount==1234 and rate.included_people==3 and rate.priority==1 and rate.mode=='Hotel'
        guests=frappe.get_all('HS Guest',filters={'property':prop.name,'full_name':'Visitante UX Formularios'},fields=['name','email','customer'])
        assert len(guests)==1 and guests[0].email=='formularios@example.invalid'
        assert frappe.db.count('HS Stay')==frappe.db.count('HS Booking')==frappe.db.count('HS Folio')==1
        stay=frappe.get_doc('HS Stay',{'property':prop.name})
        assert stay.guest==guests[0].name and stay.customer==guests[0].customer and stay.amount==1500
        assert frappe.db.get_value('HS Room',stay.room,'room_number')=='H101'
        assert frappe.db.count('HS Payment')==frappe.db.count('Payment Entry')==frappe.db.count('Sales Invoice')==1
        payment=frappe.get_doc('HS Payment',{'stay':stay.name})
        assert payment.kind=='Payment' and payment.status=='Posted' and payment.amount==1500 and payment.tendered==1600 and payment.change_amount==100
        assert frappe.db.get_value('Payment Entry',payment.payment_entry,'docstatus')==1
        assert folio_balance(payment.folio)['outstanding']=='0.00'
        shift=frappe.get_doc('HS Shift',payment.shift)
        assert shift.status=='Closed' and shift.expected_amount==shift.counted_amount==1500 and shift.difference==0
        assert expected(shift)=={'NIO':'1500.00'}
        assert frappe.db.count('Journal Entry')==0
        proof=dict(site=SITE,synthetic=True,ui_only_entry=True,property_saved_from_last_tab=True,
                   rate=dict(amount=str(rate.amount),included_people=rate.included_people,priority=rate.priority),
                   guest=dict(name_preserved=True,email_preserved=True),room='H101',stay_amount='1500.00',
                   invoices=1,payments=1,payment_entries=1,received='1600.00',change='100.00',outstanding='0.00',
                   shift_closed=True,expected='1500.00',counted='1500.00',difference='0.00')
        (ROOT/'docs/evidence/forms-items-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(proof,ensure_ascii=False))
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
