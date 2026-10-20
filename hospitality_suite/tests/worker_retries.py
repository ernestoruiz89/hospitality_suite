"""Explicit real-worker fault probe, restricted to the disposable acceptance site.

No production hook imports this module. Redis records attempts outside the SQL
transaction so a rollback cannot erase the evidence. The expiry itself is real.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import time
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime
from frappe.utils.background_jobs import get_redis_conn
from rq import get_current_job

BENCH=Path('/home/frappe/benches/hospitality-bench')
BASE=BENCH/'.hospitality-background-jobs-upgrade.json'
BACKUP=BENCH/'.hospitality-background-jobs-ux-baseline.json'
PREFIX='hs-background-jobs-probe-'


def guard():
    assert frappe.local.site=='hospitality-acceptance.localhost'
    assert frappe.conf.db_name=='hospitality_acceptance'
    assert frappe.conf.allow_tests and frappe.conf.hospitality_integration_test_site and frappe.conf.pause_scheduler
    assert frappe.session.user=='Administrator' and BASE.is_file() and BACKUP.is_file()


def state(fixture):
    booking,portal=fixture['booking'],fixture['portal']
    return dict(booking=frappe.db.get_value('HS Booking',booking,'status'),
                portal=frappe.db.get_value('HS Portal Request',portal,'status'),
                active=frappe.db.count('HS Allocation',{'booking':booking,'status':'Active'})+
                       frappe.db.count('HS Allocation',{'portal_request':portal,'status':'Active'}),
                events=frappe.db.count('HS Audit Event',{'action':['in',['Hold expired','Portal hold expired']],
                                                       'source_name':['in',[booking,portal]]}))


def expire_with_fault(property_name, token, failures, kind):
    guard()
    assert token.startswith(PREFIX) and kind in ('transient','deadlock','raw-deadlock','timeout','sql-fatal','fatal')
    connection=get_redis_conn()
    raw=connection.get(token+'-permit')
    assert raw,'An explicit disposable fixture is required'
    fixture=json.loads(raw)
    assert fixture['property']==property_name
    job=get_current_job()
    assert job and job.kwargs['site']==frappe.local.site
    from hospitality_suite import jobs
    original=jobs._expire_once
    def attempt(name):
        before=state(fixture)
        assert before==dict(booking='Hold',portal='Hold',active=2,events=0),before
        count=connection.rpush(token,json.dumps(dict(job=job.id,before=before,user=frappe.session.user)))
        connection.expire(token,600)
        assert original(name)==2
        assert state(fixture)==dict(booking='Cancelled',portal='Expired',active=0,events=2)
        if count<=failures:
            if kind=='transient':
                raise frappe.RetryBackgroundJobError('HS synthetic transient after expiry; rollback is required')
            if kind=='deadlock':
                raise frappe.QueryDeadlockError('HS synthetic deadlock after expiry')
            if kind=='timeout':
                raise frappe.QueryTimeoutError('HS synthetic timeout after expiry')
            if kind=='raw-deadlock':
                raise frappe.db.OperationalError(1213,'HS synthetic raw driver deadlock after expiry')
            if kind=='sql-fatal':
                raise frappe.db.InternalError(1064,'HS synthetic non-transient SQL failure after expiry')
            raise RuntimeError('HS synthetic fatal after expiry; operator recovery is required')
        return 2
    with patch.object(jobs,'_expire_once',side_effect=attempt):
        assert jobs.expire_property(property_name)==2
    return dict(expired=2,attempts=connection.llen(token))


def fixture(prop, index):
    from hospitality_suite import api,portal
    from hospitality_suite.service import operation
    room=frappe.get_all('HS Room',filters={'property':prop.name},fields=['name','category'],order_by='room_number')[0]
    guest=frappe.get_doc('HS Guest',{'property':prop.name})
    start=now_datetime().replace(hour=14,minute=0,second=0,microsecond=0)+timedelta(days=61+index*3)
    values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,hold=1,
                rooms=[dict(room=room.name,category=room.category,people=1)])
    values['acceptance']=api.preview(prop.name,values)['acceptance']
    booking=api.execute(prop.name,'reserve',uuid.uuid4().hex,values)['booking']
    public=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),category=room.category,quantity=1,people=1,
                full_name='Solicitante sintético de caducidad',email='expiry@example.invalid')
    key=uuid.uuid4().hex
    frappe.set_user('Guest')
    try:
        public['acceptance']=portal.quote(prop.name,public)['acceptance']
        portal.request(prop.name,public,key)
    finally:
        frappe.set_user('Administrator')
    request=frappe.db.get_value('HS Portal Request',{'request_key':hashlib.sha256((prop.name+'|'+key).encode()).hexdigest()},'name')
    assert request
    with operation():
        for dt,name in [('HS Booking',booking),('HS Portal Request',request)]:
            doc=frappe.get_doc(dt,name)
            doc.hold_until=now_datetime()-timedelta(minutes=1)
            doc.save()
    frappe.db.commit()
    return dict(property=prop.name,booking=booking,portal=request)


def wait(job, token=None, duplicate=None):
    deadline=time.monotonic()+55
    deduplicated=False
    while time.monotonic()<deadline:
        status=job.get_status(refresh=True).value
        if duplicate and not deduplicated and status=='started' and get_redis_conn().llen(token):
            # The same running RQ id must not create another invocation/job.
            assert frappe.enqueue(**duplicate) is None
            deduplicated=True
        if status in ('finished','failed'):
            frappe.db.rollback()
            return status,deduplicated
        time.sleep(.2)
    raise AssertionError('El trabajo no terminó en 55 segundos; observe el mismo id: '+job.id)


def hashes():
    expected=json.loads(BASE.read_text())['hospitality-acceptance.localhost']['tables']
    result={}
    for dt,original in expected.items():
        columns=original['columns']
        rows=frappe.db.sql('SELECT '+','.join('`'+column+'`' for column in columns)+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
        raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        result[dt]=dict(columns=columns,rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
    return expected,result


def verify():
    guard()
    assert not any(frappe.db.count(dt) for dt in ('HS Booking','HS Portal Request','HS Stay','HS Charge','HS Payment'))
    from hospitality_suite import jobs
    from hospitality_suite.service import operation
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    with operation():
        prop.portal_enabled=1
        prop.save()
    frappe.db.commit()
    cases=[]
    connection=get_redis_conn()
    for index,(label,failures,kind,attempts,expected_status) in enumerate([
        ('transient-recovered',2,'transient',3,'finished'),
        ('deadlock-recovered',1,'deadlock',2,'finished'),
        ('raw-deadlock-recovered',1,'raw-deadlock',2,'finished'),
        ('timeout-exhausted',99,'timeout',3,'failed'),
        ('sql-fatal',99,'sql-fatal',1,'failed'),
        ('fatal',99,'fatal',1,'failed'),
    ]):
        current=fixture(prop,index)
        token=PREFIX+uuid.uuid4().hex
        assert connection.set(token+'-permit',json.dumps(current),nx=True,ex=600)
        args=dict(method='hospitality_suite.tests.worker_retries.expire_with_fault',property_name=prop.name,
                  token=token,failures=failures,kind=kind,queue='short',job_id=token,deduplicate=True)
        job=frappe.enqueue(**args)
        status,deduplicated=wait(job,token,args if label=='transient-recovered' else None)
        assert status==expected_status,(label,status)
        recorded=[json.loads(value) for value in connection.lrange(token,0,-1)]
        assert len(recorded)==attempts,(label,len(recorded))
        assert {attempt['job'] for attempt in recorded}=={job.id}
        assert all(attempt['before']==dict(booking='Hold',portal='Hold',active=2,events=0) and attempt['user']=='Administrator' for attempt in recorded)
        case=dict(scenario=label,job=job.id,status=status,attempts=attempts,same_rq_job=True,
                  every_retry_started_from_rolled_back_state=True,running_job_deduplicated=deduplicated,
                  app_max_attempts=jobs.EXPIRY_ATTEMPTS,booking=current['booking'],portal=current['portal'])
        if status=='failed':
            assert state(current)==dict(booking='Hold',portal='Hold',active=2,events=0)
            job.refresh()
            assert 'HS synthetic' in job.exc_info
            assert 'AttributeError: job' not in job.exc_info
            if kind in ('timeout','sql-fatal'):
                assert 'ExpiryExecutionError' in job.exc_info
            errors=frappe.get_all('Error Log',filters={'method':args['method']},fields=['name','metadata'])
            logs=[error for error in errors if json.loads(error.metadata or '{}').get('job_id')==job.id]
            assert logs,'El fallo debe conservarse en Error Log, además de RQ'
            case.update(failure_traceback_in_rq=True,persistent_native_error_log=True)
            recovered=frappe.enqueue('hospitality_suite.jobs.expire_property',property_name=prop.name,queue='short',job_id=token+'-recovery',deduplicate=True)
            assert wait(recovered)[0]=='finished'
            case.update(recovery_job=recovered.id,recovery_expired=2)
        assert state(current)==dict(booking='Cancelled',portal='Expired',active=0,events=2)
        assert jobs.expire_property(prop.name)==0
        frappe.db.commit()
        assert state(current)['events']==2
        case.update(final_booking_status='Cancelled',final_portal_status='Expired',final_active_allocations=0,
                    expiry_audits=2,repeated_expiry_created_no_additional_audits=True)
        cases.append(case)
        connection.delete(token,token+'-permit')
    expected,after=hashes()
    changed={dt for dt in after if after[dt]!=expected[dt]}
    allowed={'HS Property','HS Booking','HS Booking Room','HS Portal Request','HS Allocation','HS Request','HS Audit Event','Version'}
    assert changed<=allowed,changed-allowed
    proof=dict(site=frappe.local.site,synthetic=True,source='Explicit API/worker fixture; no browser actions',
               app_bounded_retry_with_native_failure_logging=True,frappe_version=frappe.__version__,cases=cases,
               compared_tables=len(after),unchanged_tables=len(after)-len(changed),changed_tables=sorted(changed),
               financial_stock_and_existing_guest_tables_unchanged=True)
    target=Path(__file__).resolve().parents[2]/'docs/evidence/background-jobs-worker.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return proof
