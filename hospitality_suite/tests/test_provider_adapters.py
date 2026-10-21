"""SIMULATED contract provider only. No network, money, messages or hardware."""
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from hospitality_suite.provider_adapters import (
    CONTRACT, LIMIT, ContractError, ProviderFailure, ProviderUnavailable,
    HttpContractTransport, ReferencePaymentAdapter, ReferenceMessagingAdapter,
    ReferenceLockAdapter, ReferenceChannelNormalizer,
)

SCOPE=dict(company='Compañía ficticia',property='PROPERTY-TEST')
SECRET='FICTIONAL-WEBHOOK-SECRET'
NOW=datetime(2026,10,21,18,tzinfo=timezone.utc)
START='2026-10-21T12:00:00-06:00'
END='2026-10-22T12:00:00-06:00'


class SimulatedResponse:
    def __init__(self,raw,status=200,content_type='application/json'):
        self.raw=raw;self.status=status;self.headers={'Content-Type':content_type}
    def getcode(self):return self.status
    def read(self,size):return self.raw[:size]
    def __enter__(self):return self
    def __exit__(self,*args):return False


class SimulatedProvider:
    """Fictional in-memory remote service, persists across adapter instances."""
    def __init__(self):
        self.calls=[];self.accepted={};self.lose_next_response=False;self.transform=lambda value:value
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        path=urlsplit(request.full_url).path;data=json.loads(request.data)
        key=(path,request.get_header('Idempotency-key'))
        digest=hashlib.sha256(request.data).hexdigest()
        assert request.get_header('X-hospitality-payload-sha256')==digest
        if key in self.accepted:
            old_digest,value=self.accepted[key]
            if digest!=old_digest:
                raise HTTPError(request.full_url,409,'FICTIONAL-PRIVATE-BODY',{},io.BytesIO())
        else:
            status={'/v1/payment-intents':'pending','/v1/messages':'queued','/v1/access-grants':'scheduled'}.get(path,'revoked')
            identity=path.split('/')[-2] if path.endswith('/revoke') else 'contract-id-'+str(len(self.accepted)+1)
            value=dict(data,id=identity,status=status,provider_token='FICTIONAL-PRIVATE-TOKEN',pan='FICTIONAL-PAN',access_code='FICTIONAL-PIN')
            self.accepted[key]=(digest,value)
        if self.lose_next_response:
            self.lose_next_response=False
            raise TimeoutError('FICTIONAL-PRIVATE-DETAIL: accepted before lost reply')
        return SimulatedResponse(json.dumps(self.transform(dict(value))).encode())


class TestProviderAdapters(unittest.TestCase):
    def setUp(self):
        self.no_network=patch('socket.create_connection',side_effect=AssertionError('External network forbidden in contract tests'))
        self.no_network.start();self.addCleanup(self.no_network.stop)
        self.remote=SimulatedProvider()
        self.transport=self.new_transport()

    def new_transport(self,**kwargs):
        return HttpContractTransport('https://provider.example.invalid','FICTIONAL-API-TOKEN',enabled=True,opener=self.remote,**kwargs)

    def payment(self,transport=None):
        return ReferencePaymentAdapter(transport or self.transport,company=SCOPE['company'],property_name=SCOPE['property'],webhook_secret=SECRET,clock=lambda:NOW.timestamp())

    def message(self,medium='email',transport=None):
        return ReferenceMessagingAdapter(transport or self.transport,company=SCOPE['company'],property_name=SCOPE['property'],medium=medium,
                                         confirmation_origin='https://hotel.example.invalid',template_id='confirmed-booking-v1')

    def lock(self):
        return ReferenceLockAdapter(self.transport,company=SCOPE['company'],property_name=SCOPE['property'],clock=lambda:NOW)

    def intent(self,adapter=None,**overrides):
        values=dict(origin='CTA-TEST',amount='10.50',currency='NIO',idempotency_key='intent-1');values.update(overrides)
        return (adapter or self.payment()).create_intent(**values)

    def event(self,**overrides):
        value=dict(contract=CONTRACT,scope=dict(SCOPE),id='event-1',intent_id='contract-id-1',origin='CTA-TEST',amount='10.50',currency='NIO',status='settled',pan='FICTIONAL-PAN',cvv='FICTIONAL-CVV')
        value.update(overrides);return json.dumps(value).encode()

    def sign(self,raw,timestamp=None):
        stamp=str(int(NOW.timestamp()) if timestamp is None else timestamp)
        return {'x-hospitality-timestamp':stamp,'x-hospitality-signature':hmac.new(SECRET.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()}

    def test_disabled_transport_and_missing_credentials_never_call_provider(self):
        for kwargs in ({},{'enabled':'true'},{'enabled':False},{'enabled':True,'token':None}):
            token=kwargs.pop('token','FICTIONAL-TOKEN')
            transport=HttpContractTransport('https://provider.example.invalid',token,opener=self.remote,**kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ProviderUnavailable):self.intent(self.payment(transport))
        self.assertEqual(self.remote.calls,[])

    def test_https_base_url_timeout_and_auth_header_validation(self):
        for url in ['http://provider.example.invalid','https://user:secret@provider.example.invalid','https://provider.example.invalid/path','https://provider.example.invalid?token=x','https://bad domain.invalid']:
            with self.subTest(url=url),self.assertRaises(ContractError):HttpContractTransport(url,opener=self.remote)
        for timeout in [0,-1,31,float('inf'),float('nan'),True]:
            with self.subTest(timeout=timeout),self.assertRaises(ContractError):self.new_transport(timeout=timeout)
        transport=HttpContractTransport('https://provider.example.invalid','private\r\nInjected: value',enabled=True,opener=self.remote)
        with self.assertRaises(ContractError):self.intent(self.payment(transport))
        self.assertEqual(self.remote.calls,[])

    def test_http_rejects_arbitrary_paths_and_header_injection_without_a_request(self):
        for path in ['https://other.example.invalid','/v1/../admin','/v1/access-grants/../../secret/revoke','/v1/access-grants/../revoke','/v1/messages?secret=x']:
            with self.subTest(path=path),self.assertRaises(ContractError):self.transport.request(path,{},idempotency_key='key-1')
        for key in ['','a\r\nAuthorization: other','a b','x'*129,None]:
            with self.subTest(key=key),self.assertRaises(ContractError):self.intent(idempotency_key=key)
        self.assertEqual(self.remote.calls,[])

    def test_ambiguous_response_retries_same_intent_across_instances_without_double_acceptance(self):
        self.remote.lose_next_response=True
        with self.assertRaises(ProviderFailure) as raised:self.intent()
        self.assertTrue(raised.exception.retryable);self.assertEqual(str(raised.exception),'provider_request_failed')
        self.assertEqual(len(self.remote.calls),1) # No automatic resubmission.
        retry=self.intent(self.payment(self.new_transport()))
        repeated=self.intent(amount='10.500')
        self.assertEqual(retry,repeated);self.assertEqual(len(self.remote.accepted),1)
        with self.assertRaises(ProviderFailure) as raised:self.intent(amount='11')
        self.assertFalse(raised.exception.retryable);self.assertEqual(len(self.remote.accepted),1)

    def test_payment_intent_is_pending_not_a_payment_and_excludes_unknown_secrets(self):
        result=self.intent()
        self.assertEqual(result,dict(id='contract-id-1',status='pending',origin='CTA-TEST',amount='10.5',currency='NIO',payment_recorded=False))
        request,timeout=self.remote.calls[0]
        self.assertEqual(request.get_method(),'POST');self.assertEqual(timeout,5)
        self.assertEqual(request.get_header('Authorization'),'Bearer FICTIONAL-API-TOKEN')
        self.assertEqual(json.loads(request.data)['scope'],SCOPE)
        self.assertNotIn('FICTIONAL',json.dumps(result))

    def test_amount_currency_and_response_status_validation(self):
        for amount in [0,-1,True,1.5,'NaN','Infinity','1e999999999','1e-999999999','1000000000000000000',None]:
            with self.subTest(amount=amount),self.assertRaises(ContractError):self.intent(amount=amount)
        for currency in ['nio','NIO\n','NI','USDD',None]:
            with self.subTest(currency=currency),self.assertRaises(ContractError):self.intent(currency=currency)
        self.assertEqual(self.remote.calls,[])
        for status in ['settled','paid',[],{},None]:
            self.remote.transform=lambda data,status=status:dict(data,status=status)
            with self.subTest(status=status),self.assertRaises(ContractError):self.intent()

    def test_payment_refuses_mismatched_scope_origin_amount_or_currency(self):
        for changes in [dict(scope=dict(SCOPE,property='OTHER')),dict(contract='future'),dict(origin='OTHER'),dict(amount='11'),dict(currency='USD'),dict(id='')]:
            self.remote.transform=lambda data,changes=changes:dict(data,**changes)
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.intent()

    def test_verified_payment_event_is_a_normalized_receipt_without_accounting(self):
        raw=self.event();result=self.payment().verify_event(raw,self.sign(raw))
        self.assertEqual(result['status'],'settled');self.assertTrue(result['verified']);self.assertFalse(result['payment_recorded'])
        self.assertNotIn('FICTIONAL',json.dumps(result));self.assertEqual(self.remote.calls,[])

    def test_payment_event_rejects_bad_signature_expiration_scope_and_body(self):
        raw=self.event()
        for body,headers in [(raw,{}),(raw,dict(self.sign(raw),**{'x-hospitality-signature':'bad'})),(raw,self.sign(raw,int(NOW.timestamp())-301)),(raw+b' ',self.sign(raw))]:
            with self.subTest(body=body),self.assertRaises(ContractError):self.payment().verify_event(body,headers)
        for raw in [self.event(scope=dict(SCOPE,company='OTHER')),b'[]',b'{"id":1,"id":2}',b'{"id":NaN}',b'x'*(LIMIT+1)]:
            with self.subTest(raw=raw[:30]),self.assertRaises(ContractError):self.payment().verify_event(raw,self.sign(raw))
        adapter=ReferencePaymentAdapter(self.transport,company=SCOPE['company'],property_name=SCOPE['property'])
        with self.assertRaises(ProviderUnavailable):adapter.verify_event(self.event(),{})

    def test_email_and_whatsapp_submit_template_and_signed_link_without_delivery_claim(self):
        for medium,recipient in [('email','guest@example.invalid'),('whatsapp','+50588880000')]:
            result=self.message(medium).send_confirmation(recipient=recipient,signed_url='https://hotel.example.invalid/hospitality-confirmation?token=fictional-signed-token',idempotency_key='message-'+medium)
            self.assertEqual(result['status'],'queued');self.assertFalse(result['delivery_confirmed']);self.assertNotIn('FICTIONAL',json.dumps(result))
            data=json.loads(self.remote.calls[-1][0].data)
            self.assertEqual(data['medium'],medium);self.assertEqual(data['recipient'],recipient);self.assertEqual(data['template_id'],'confirmed-booking-v1')
        self.assertEqual(len(self.remote.accepted),2)

    def test_messaging_rejects_invalid_recipient_foreign_link_and_unconfirmed_delivery(self):
        good='https://hotel.example.invalid/hospitality-confirmation?token=fictional-token'
        for medium,recipient in [('email','missing-at'),('email','x@example.invalid\nBCC: y@example.invalid'),('whatsapp','88880000'),('whatsapp','+000000000')]:
            with self.subTest(medium=medium),self.assertRaises(ContractError):self.message(medium).send_confirmation(recipient=recipient,signed_url=good,idempotency_key='msg')
        for link in [good.replace('https:','http:'),good.replace('hotel.','other.'),good.replace('hospitality-confirmation','admin'),good.replace('fictional-token',''),good+'&token=second',good+'#fragment']:
            with self.subTest(link=link),self.assertRaises(ContractError):self.message().send_confirmation(recipient='guest@example.invalid',signed_url=link,idempotency_key='msg')
        self.assertEqual(self.remote.calls,[])
        self.remote.transform=lambda data:dict(data,status='delivered')
        with self.assertRaises(ContractError):self.message().send_confirmation(recipient='guest@example.invalid',signed_url=good,idempotency_key='msg')

    def test_lock_grant_uses_aware_utc_window_and_revoke_returns_no_access_code(self):
        grant=self.lock().grant_access(stay='EST-TEST',room='H101',starts_at=START,ends_at=END,idempotency_key='grant')
        self.assertEqual(grant['starts_at'],'2026-10-21T18:00:00+00:00');self.assertEqual(grant['ends_at'],'2026-10-22T18:00:00+00:00')
        self.assertNotIn('FICTIONAL',json.dumps(grant))
        revoked=self.lock().revoke_access(grant_id=grant['id'],idempotency_key='revoke')
        self.assertEqual(revoked,dict(id=grant['id'],status='revoked'));self.assertNotIn('FICTIONAL',json.dumps(revoked))

    def test_lock_rejects_naive_reversed_expired_and_mismatched_grants(self):
        for start,end in [('2026-10-21 18:00:00',END),(END,START),(START,START),('2026-10-19T18:00:00Z','2026-10-20T18:00:00Z')]:
            with self.subTest(start=start),self.assertRaises(ContractError):self.lock().grant_access(stay='EST-TEST',room='H101',starts_at=start,ends_at=end,idempotency_key='grant')
        for grant_id in ['../../other','..','.','',None,'a?token=private']:
            with self.subTest(grant_id=grant_id),self.assertRaises(ContractError):self.lock().revoke_access(grant_id=grant_id,idempotency_key='revoke')
        self.assertEqual(self.remote.calls,[])
        for changes in [dict(stay='OTHER'),dict(room='OTHER'),dict(scope=dict(SCOPE,property='OTHER')),dict(ends_at='2026-10-23T18:00:00Z')]:
            self.remote.transform=lambda data,changes=changes:dict(data,**changes)
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.lock().grant_access(stay='EST-TEST',room='H101',starts_at=START,ends_at=END,idempotency_key='grant')
        self.remote.transform=lambda data:dict(data,id='OTHER')
        with self.assertRaises(ContractError):self.lock().revoke_access(grant_id='contract-id-1',idempotency_key='revoke')

    def test_http_status_failures_are_sanitized_and_retry_budget_is_caller_owned(self):
        class FailingOpener:
            def __init__(self,code):self.code=code;self.calls=0
            def open(self,request,timeout):
                self.calls+=1
                self.error=HTTPError(request.full_url,self.code,'FICTIONAL-PRIVATE-TOKEN',{},io.BytesIO(b'FICTIONAL-PAN'))
                raise self.error
        for status in [302,400,401,409,429,500,503]:
            opener=FailingOpener(status)
            transport=HttpContractTransport('https://provider.example.invalid','FICTIONAL-API-TOKEN',enabled=True,opener=opener)
            with self.subTest(status=status),self.assertRaises(ProviderFailure) as raised:self.intent(self.payment(transport))
            self.assertEqual(raised.exception.retryable,status==429 or status>=500);self.assertEqual(str(raised.exception),'provider_request_failed');self.assertEqual(opener.calls,1)
            self.assertTrue(opener.error.fp.closed)
        from hospitality_suite.provider_adapters import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'',{},'https://other.example.invalid'))

    def test_http_response_and_request_limits_reject_malformed_json(self):
        class InvalidOpener:
            def __init__(self,raw,content_type='application/json'):self.raw=raw;self.content_type=content_type
            def open(self,request,timeout):return SimulatedResponse(self.raw,content_type=self.content_type)
        for raw in [b'[]',b'{"id":1,"id":2}',b'{"number":NaN}',b'not-json',b'\xff',b'x'*(LIMIT+1)]:
            transport=HttpContractTransport('https://provider.example.invalid','FICTIONAL-TOKEN',enabled=True,opener=InvalidOpener(raw))
            with self.subTest(raw=raw[:20]),self.assertRaises(ContractError):self.intent(self.payment(transport))
        transport=HttpContractTransport('https://provider.example.invalid','FICTIONAL-TOKEN',enabled=True,opener=InvalidOpener(b'{}','text/html'))
        with self.assertRaises(ContractError):self.intent(self.payment(transport))
        for payload in [dict(value=float('nan')),dict(value='x'*(LIMIT+1))]:
            with self.assertRaises(ContractError):self.transport.request('/v1/messages',payload,idempotency_key='msg')
        self.assertEqual(self.remote.calls,[])

    def test_channel_mapping_is_read_only_and_outbound_synchronization_stays_deferred(self):
        normalizer=ReferenceChannelNormalizer(company=SCOPE['company'],property_name=SCOPE['property'],category_map={'double':'CAT-TEST'})
        event=dict(contract=CONTRACT,scope=dict(SCOPE),id='external-request',category='double',quantity=2,people=2,starts_at=START,ends_at=END,amount='UNTRUSTED-PRICE',guest='FICTIONAL-GUEST-SECRET')
        result=normalizer.normalize_reservation(event)
        self.assertEqual(result,dict(external_id='external-request',category='CAT-TEST',quantity=2,people=2,starts_at='2026-10-21T18:00:00+00:00',ends_at='2026-10-22T18:00:00+00:00',requires_pms_validation=True,provider_confirmation=False))
        with self.assertRaises(ProviderUnavailable):normalizer.publish_availability(property_name=SCOPE['property'],category='CAT-TEST',intervals=[],idempotency_key='never-publish')
        self.assertEqual(self.remote.calls,[])

    def test_channel_rejects_unknown_mapping_foreign_scope_and_invalid_counts(self):
        normalizer=ReferenceChannelNormalizer(company=SCOPE['company'],property_name=SCOPE['property'],category_map={'double':'CAT-TEST'})
        event=dict(contract=CONTRACT,scope=dict(SCOPE),id='external-request',category='double',quantity=2,people=2,starts_at=START,ends_at=END)
        for changes in [dict(scope=dict(SCOPE,company='OTHER')),dict(category='foreign'),dict(category=[]),dict(quantity=0),dict(quantity=101),dict(quantity=True),dict(people=1.5),dict(ends_at=START)]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):normalizer.normalize_reservation(dict(event,**changes))
        self.assertEqual(self.remote.calls,[])

    def test_adapters_are_not_whitelisted_or_attached_to_jobs_and_business_hooks(self):
        import frappe
        from hospitality_suite import hooks
        methods=[ReferencePaymentAdapter.create_intent,ReferencePaymentAdapter.verify_event,ReferenceMessagingAdapter.send_confirmation,
                 ReferenceLockAdapter.grant_access,ReferenceLockAdapter.revoke_access,ReferenceChannelNormalizer.normalize_reservation]
        self.assertTrue(all(method not in frappe.whitelisted for method in methods))
        self.assertNotIn('provider_adapters',repr(hooks.scheduler_events)+repr(hooks.doc_events))


if __name__=='__main__':unittest.main(verbosity=2)
