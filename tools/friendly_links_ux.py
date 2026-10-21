"""Native isolated UX server and read-only draft/confirmation inspection."""
import argparse,json,os,re,signal,socket,subprocess
from pathlib import Path

BENCH=Path('/home/frappe/benches/hospitality-bench');SITE='hospitality-acceptance.localhost';ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','inspect']);parser.add_argument('--stage',choices=['observed-draft','draft','confirmed'],default='draft');args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('hospitality_integration_test_site') and config.get('allow_tests')
assert (BENCH/'.hospitality-friendly-links-ux-baseline.json').is_file()
pidfile=BENCH/'.hospitality-run/friendly-links-web.pid';log=pidfile.with_suffix('.log')
if args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Temporary friendly-Link server started on 8089')
elif args.action=='stop':
    if pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert SITE in command and 'serve' in command and '8089' in command and (process/'cwd').resolve() in (BENCH,BENCH/'sites')
            os.kill(int(process.name),signal.SIGTERM)
    print('Temporary friendly-Link server stopped')
else:
    import frappe
    from hospitality_suite.time import local
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator');prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        counts={dt:frappe.db.count(dt) for dt in ('HS Booking','HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry','HS Allocation')}
        assert counts=={'HS Booking':1,'HS Stay':0,'HS Charge':0,'HS Payment':0,'HS Shift':0,'Sales Invoice':0,'Payment Entry':0,'Journal Entry':0,'HS Allocation':int(args.stage=='confirmed')}
        booking=frappe.get_doc('HS Booking',frappe.db.get_value('HS Booking',{'property':prop.name}))
        assert booking.owner=='receptionist@hospitality.example.invalid'
        assert local(booking.starts_at,prop).isoformat()=='2026-10-26T14:00:00-06:00' and local(booking.ends_at,prop).isoformat()=='2026-10-27T12:00:00-06:00'
        assert str(prop.business_date)=='2026-10-19'
        if args.stage!='confirmed':
            assert booking.status=='Draft' and booking.amount==0
            rows=frappe.parse_json(booking.draft_data)['rooms'];assert len(rows)==1
            values=rows[0]
        else:
            assert booking.status=='Confirmed' and booking.amount==1500 and len(booking.rooms)==1 and not booking.draft_data
            values=booking.rooms[0].as_dict()
        category=frappe.get_doc('HS Category',values['category']);room=frappe.get_doc('HS Room',values['room']);rate=frappe.get_doc('HS Rate',values['rate'])
        assert category.property==room.property==rate.property==prop.name and room.category==category.name and rate.category==category.name
        assert room.room_number=='H101' and values['extra_beds']==0 and rate.amount==1500
        if args.stage!='observed-draft':assert values['people']==2
        ids={key:values[key] for key in ['category','room','rate']}
        if args.stage=='confirmed':
            previous=json.loads((ROOT/'docs/evidence/friendly-links-draft-ui.json').read_text())
            assert previous['ids']==ids and previous['booking']==booking.name
            allocation=frappe.get_doc('HS Allocation',frappe.db.get_value('HS Allocation',{'booking':booking.name}))
            assert allocation.status=='Active' and allocation.kind=='Reservation' and allocation.room==room.name
        http=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',log.read_text());assert not re.findall(r'HTTP/1.1" 500 ',http)
        commands=re.findall(r'"POST /api/method/hospitality_suite.api.execute HTTP/1.1" (\d+)',http)
        assert commands==['200']*{'observed-draft':1,'draft':2,'confirmed':3}[args.stage]
        proof=dict(site=SITE,stage=args.stage,fixture_origin='Pages UI only',mutations_by_inspector=False,operation_counts=counts,booking=booking.name,status=booking.status,amount=booking.amount,
            ids=ids,labels=dict(category=category.category_name,room=room.room_number,rate=rate.title),people=values['people'],extra_beds=0,keys_preserved_from_draft=args.stage=='confirmed',execute_http_statuses=commands,http_500=0,business_date='2026-10-19')
        (ROOT/f'docs/evidence/friendly-links-{args.stage}-ui.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof,ensure_ascii=False))
    finally:frappe.db.rollback();frappe.destroy()
