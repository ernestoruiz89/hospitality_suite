"""Native HTTP permission probe on a backed-up, disposable acceptance fixture only."""
import argparse
from datetime import timedelta
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
SITE='hospitality-acceptance.localhost'
STATE=BENCH/'.hospitality-permissions-audit-http-v2.json'
PORT=8089
URL=f'http://localhost:{PORT}'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','start','probe','inspect','stop','cleanup']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-permissions-audit-ux-baseline.json').is_file()


def snapshot():
    import frappe
    names=json.loads((BENCH/'.hospitality-permissions-audit-upgrade.json').read_text())[SITE]['tables']
    return {dt:dict(rows=frappe.db.count(dt),sha256=hashlib.sha256(json.dumps(
        frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True),default=str,sort_keys=True,
        ensure_ascii=False,separators=(',',':')).encode()).hexdigest()) for dt in names}


class Session:
    def __init__(self):
        self.cookies=http.cookiejar.CookieJar();self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies));self.csrf=None

    def request(self,path,values=None,method='GET',csrf=True):
        headers={'Accept':'application/json'};body=None
        if values is not None:
            encoded=urllib.parse.urlencode({key:json.dumps(value) if isinstance(value,(dict,list)) else value for key,value in values.items()})
            if method=='GET': path+='?'+encoded
            else:body=encoded.encode();headers['Content-Type']='application/x-www-form-urlencoded'
        if csrf and self.csrf: headers['X-Frappe-CSRF-Token']=self.csrf
        req=urllib.request.Request(URL+path,data=body,headers=headers,method=method)
        try:
            with self.client.open(req,timeout=30) as response:code=response.status;raw=response.read()
        except urllib.error.HTTPError as response:code=response.code;raw=response.read()
        try:value=json.loads(raw)
        except ValueError:value={}
        return code,value,raw

    def rpc(self,name,values=None,method='GET',csrf=True):
        return self.request('/api/method/'+name,values,method,csrf)

    def login(self,user,password):
        code,_,_=self.rpc('login',dict(usr=user,pwd=password),'POST');assert code==200,'Native login failed'
        code,_,raw=self.request('/app');assert code==200
        match=re.search(rb'frappe\.csrf_token\s*=\s*"([^"]+)"',raw);assert match,'Native CSRF token missing'
        self.csrf=match[1].decode()


if args.action in ('start','stop'):
    pidfile=BENCH/'.hospitality-run/permissions-http-web.pid';log=pidfile.with_suffix('.log')
    if args.action=='start':
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',PORT))!=0,'8089 must be free'
        with log.open('ab') as stream:
            log.chmod(0o600)
            process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port',str(PORT),'--noreload'],
                cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
        pidfile.write_text(str(process.pid));print('Native acceptance HTTP server started on 8089')
    elif pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert 'serve' in command and SITE in command and str(PORT) in command
            assert (process/'cwd').resolve() in (BENCH,BENCH/'sites')
            os.kill(int(process.name),signal.SIGTERM)
        print('Temporary HTTP server stopped; main server untouched')
elif args.action=='probe':
    fixture=json.loads(STATE.read_text());sessions=[];checks=[]
    def check(label,result,exception=None,status=None):
        code,value,_=result
        assert (value.get('exc_type')==exception if exception else code==status),f"{label}: status={code}, exception={value.get('exc_type')}"
        checks.append(dict(check=label,status=code,exception=value.get('exc_type')))
    try:
        guest=Session()
        check('Guest authenticated bootstrap denied',guest.rpc('hospitality_suite.api.bootstrap'),exception='PermissionError')
        check('Guest native resource denied',guest.request('/api/resource/HS%20Guest/'+urllib.parse.quote(fixture['guest'])),exception='PermissionError')
        result=guest.rpc('hospitality_suite.portal.catalog');check('Disabled portal exposes no catalog',result,status=200);assert result[1]['message']==[]
        check('Disabled public quote denied',guest.rpc('hospitality_suite.portal.quote',dict(property_name=fixture['other'],data={})),exception='PermissionError')
        check('Disabled webhook denied',guest.rpc('hospitality_suite.integrations.webhook',dict(provider='unconfigured'),'POST'),exception='PermissionError')
        statuses=[guest.rpc('hospitality_suite.portal.catalog')[0] for _ in range(30)]
        assert statuses[-1]==429 and all(code==200 for code in statuses[:-1]);checks.append(dict(check='Native per-IP catalog limit',allowed=30,status=429))
        credentials=json.loads((BENCH/'sites'/SITE/'private/hospitality-demo-users.json').read_text())
        def demo(role):
            user=role+'@hospitality.example.invalid';value=credentials[user]
            client=Session();client.login(user,value if isinstance(value,str) else value['password']);sessions.append(client);return client
        reception=demo('receptionist')
        execute=dict(property_name=fixture['property'],action='booking_status',request_key=uuid.uuid4().hex,
            data=dict(booking=fixture['booking'],modified=fixture['modified'],status='Cancelled',reason='HTTP negative probe'))
        check('Cross-context command denied for multi-property reception',reception.rpc('hospitality_suite.api.execute',execute,'POST'),exception='PermissionError')
        check('Cross-context quote denied',reception.rpc('hospitality_suite.api.preview',dict(property_name=fixture['property'],action='booking_status',data=dict(booking=fixture['booking'],status='Cancelled'))),exception='PermissionError')
        check('Mutation using GET denied',reception.rpc('hospitality_suite.api.execute',execute),exception='PermissionError')
        check('Missing CSRF token denied',reception.rpc('hospitality_suite.api.execute',execute,'POST',csrf=False),exception='CSRFTokenError')
        check('Malformed JSON handled',reception.rpc('hospitality_suite.api.execute',{**execute,'data':'{'},'POST'),exception='ValidationError')
        check('Non-object payload handled',reception.rpc('hospitality_suite.api.execute',{**execute,'data':[]},'POST'),exception='ValidationError')
        check('Unknown action handled',reception.rpc('hospitality_suite.api.execute',{**execute,'action':"unknown' OR 1=1 --"},'POST'),exception='ValidationError')
        only=Session();only.login(fixture['user'],fixture['password']);sessions.append(only)
        check('Foreign guest document denied with combined native role',only.request('/api/resource/HS%20Guest/'+urllib.parse.quote(fixture['guest'])),exception='PermissionError')
        code,value,_=only.request('/api/resource/HS%20Room',dict(fields=['name','property'],limit_page_length=100));assert code==200
        assert len(value['data'])==10 and all(row['property']==fixture['property'] for row in value['data']);checks.append(dict(check='Native room list restricted to one property',rows=10,status=200))
        result=only.rpc('frappe.desk.search.search_link',dict(doctype='HS Guest',txt=fixture['guest']),'POST');assert result[0]==200 and result[1]['message']==[]
        checks.append(dict(check='Native link search excludes foreign guest',rows=0,status=200))
        cleaner=demo('housekeeping')
        check('Identity file denied to housekeeping',cleaner.request(fixture['file_url']),status=403)
        result=cleaner.rpc('hospitality_suite.api.bootstrap',dict(property_name=fixture['other']));assert result[0]==200
        assert not set(result[1]['message']).intersection({'guests','customers','payments','folios','stays','bookings'});checks.append(dict(check='Housekeeping projection excludes personal and financial documents',status=200))
        auditor=demo('auditor')
        check('Read-only auditor cannot open cash shift',auditor.rpc('hospitality_suite.api.execute',dict(property_name=fixture['property'],action='open_shift',request_key=uuid.uuid4().hex,data=dict(opening_amount=0)),'POST'),exception='PermissionError')
    finally:
        for client in sessions:
            result=client.rpc('logout',{},'POST');assert result[0]==200
            result=client.rpc('frappe.auth.get_logged_user');assert result[0]==403
            client.csrf=None;client.cookies.clear()
    proof=dict(site=SITE,base_url=URL,real_http=True,checks=checks,authenticated_sessions_logged_out=len(sessions),
        ui_navigation_executed=False,external_providers_enabled=False,business_mutations_from_http=0)
    (ROOT/'docs/evidence/permissions-audit-http.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(http_checks=len(checks),sessions_logged_out=len(sessions),rate_limit=429)))
else:
    import frappe
    from frappe.utils import now_datetime
    from hospitality_suite import api
    from hospitality_suite.service import operation
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        if args.action=='cleanup':
            assert not frappe.db.count('HS Booking') and not frappe.db.count('HS Stay')
            receipt=json.loads((BENCH/'.hospitality-permissions-audit-ux-restored-receipt.json').read_text())
            assert receipt['baseline_sha256']==hashlib.sha256((BENCH/'.hospitality-permissions-audit-ux-baseline.json').read_bytes()).hexdigest()
            with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',PORT))!=0
            folder=(BENCH/'sites'/SITE/'private/files').resolve();removed=0
            for state_path in (BENCH/'.hospitality-permissions-audit-http.json',STATE):
                if not state_path.exists():continue
                value=json.loads(state_path.read_text());url=value['file_url']
                assert re.fullmatch(r'/private/files/permissions-synthetic-[0-9a-f]+\.txt',url)
                assert not frappe.db.exists('File',{'file_url':url})
                target=(folder/Path(url).name).resolve();assert target.parent==folder
                if target.exists():
                    assert hashlib.sha256(target.read_bytes()).hexdigest()==value['file_sha256']
                    target.unlink();removed+=1
            proof=dict(acceptance_only=True,after_confirmed_restore=True,checked_fixture_generations=2,removed_synthetic_orphan_files=removed,sha256_checked_before_removal=True)
            (ROOT/'docs/evidence/permissions-audit-fixture-cleanup.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
        elif args.action=='prepare':
            assert not STATE.exists() and not frappe.db.count('HS Booking')
            before=snapshot();prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'});other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
            guest=frappe.get_doc('HS Guest',{'property':other.name});room=frappe.get_doc('HS Room',{'property':other.name});start=now_datetime().replace(microsecond=0)
            values=dict(guest=guest.name,customer=guest.customer,starts_at=str(start),ends_at=str(start+timedelta(hours=3)),rooms=[dict(category=room.category,room=room.name,people=1)])
            values['acceptance']=api.preview(other.name,values)['acceptance'];name=api.execute(other.name,'reserve',uuid.uuid4().hex,values)['booking']
            file=frappe.get_doc(dict(doctype='File',file_name='permissions-synthetic-'+uuid.uuid4().hex+'.txt',content='Synthetic permission evidence; no real identification.',
                is_private=1,attached_to_doctype='HS Guest',attached_to_name=guest.name)).insert()
            user='scope-http-'+uuid.uuid4().hex[:8]+'@example.invalid';password=secrets.token_urlsafe(32)
            previous_test=frappe.in_test
            try:
                # Native User.on_update creates Contact immediately in test mode.
                # Include it in preparation instead of racing the live worker.
                frappe.in_test=True
                frappe.get_doc(dict(doctype='User',email=user,first_name='HTTP scope test',send_welcome_email=0,user_type='System User',new_password=password,
                    roles=[dict(role='HS Receptionist'),dict(role='Accounts User')])).insert()
            finally:frappe.in_test=previous_test
            with operation():frappe.get_doc(dict(doctype='HS Access',company=prop.company,property=prop.name,user=user)).insert()
            frappe.db.commit()
            state=dict(property=prop.name,other=other.name,guest=guest.name,booking=name,modified=str(frappe.db.get_value('HS Booking',name,'modified')),
                file_url=file.file_url,file_sha256=hashlib.sha256(Path(file.get_full_path()).read_bytes()).hexdigest(),user=user,password=password,before=before,fixture=snapshot())
            STATE.write_text(json.dumps(state));STATE.chmod(0o600);print('Synthetic booking, private file and single-property combined-role user prepared')
        else:
            state=json.loads(STATE.read_text());actual=snapshot()
            assert actual==state['fixture'],['HTTP changed '+dt for dt in actual if actual[dt]!=state['fixture'][dt]]
            file=frappe.get_doc('File',{'file_url':state['file_url']});assert hashlib.sha256(Path(file.get_full_path()).read_bytes()).hexdigest()==state['file_sha256']
            proof=dict(site=SITE,synthetic_api_fixture=True,unchanged_tables=len(state['fixture']),rows=sum(v['rows'] for v in state['fixture'].values()),
                private_file_preserved=True,booking_status=frappe.db.get_value('HS Booking',state['booking'],'status'),http_business_writes=0)
            assert proof['booking_status']=='Confirmed'
            (ROOT/'docs/evidence/permissions-audit-http-preservation.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(proof))
    finally:frappe.db.rollback();frappe.destroy()
