"""Synthetic provider only: no payment provider, network or real credentials."""
import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.wrappers import Request

from hospitality_suite import integrations


class TestWebhook(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        original_request=getattr(frappe.local,'request',None)
        original_ip=getattr(frappe.local,'request_ip',None)
        original_user=frappe.session.user
        self.addCleanup(setattr,frappe.local,'request',original_request)
        self.addCleanup(setattr,frappe.local,'request_ip',original_ip)
        self.addCleanup(frappe.set_user,original_user)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.provider='synthetic-webhook-'+uuid.uuid4().hex[:8]
        frappe.local.request_ip='192.0.2.'+str(uuid.uuid4().int%254+1)

    def signed_call(self,body,provider=None,configured=True):
        provider=provider or self.provider
        secret='synthetic-test-secret-no-provider'
        stamp=str(int(time.time()))
        signature=hmac.new(secret.encode(),stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        config={provider:dict(enabled=True,property=self.prop.name,secret=secret)} if configured else {}
        with patch.dict(frappe.conf,{'hospitality_integrations':config}):
            frappe.local.request=Request.from_values(method='POST',data=body,headers={
                'X-Hospitality-Timestamp':stamp,'X-Hospitality-Signature':signature})
            return integrations.webhook(provider)

    def test_unconfigured_or_malformed_signed_events_leave_no_operational_effects(self):
        tracked=('HS Integration Event','HS Booking','HS Allocation','Sales Invoice','Payment Entry','HS Payment','Stock Entry','GL Entry')
        before={dt:frappe.db.count(dt) for dt in tracked}
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):
            self.signed_call(b'{"id":"fictional"}',configured=False)
        for body in (b'[]',b'null',b'false',b'{broken',b'{"id":[]}',b'{"id":true}',b'{"id":1.5}',
                     b'{"id":" "}',b'{"id":"'+b'x'*201+b'"}',b'{"id":"fictional","x":"'+b'x'*65536+b'"}'):
            with self.subTest(body_size=len(body)),self.assertRaises(frappe.ValidationError):
                self.signed_call(body)
        self.assertEqual({dt:frappe.db.count(dt) for dt in tracked},before)

    def test_event_identity_is_scoped_and_duplicate_keeps_original_receipt(self):
        external='fictional-external-event-'+uuid.uuid4().hex
        raw=json.dumps(dict(id=external,status='paid',card=dict(number='FICTIONAL-PAN'))).encode()
        frappe.set_user('Guest')
        first=self.signed_call(raw)
        replay=self.signed_call(json.dumps(dict(id=external,status='changed',token='FICTIONAL-SECRET')).encode())
        self.assertEqual(first['name'],replay['name'])
        event=frappe.get_doc('HS Integration Event',first['name'])
        self.assertEqual(frappe.parse_json(event.payload)['body_sha256'],hashlib.sha256(raw).hexdigest())
        other=self.signed_call(raw,provider=self.provider+'-other')
        self.assertNotEqual(first['name'],other['name'])
        self.assertEqual(event.status,'Received')
        self.assertEqual(frappe.db.count('HS Integration Event',{'property':self.prop.name}),2)

    def test_legacy_payload_migration_preserves_metadata_and_cleans_versions_once(self):
        from hospitality_suite.service import operation,canonical
        from hospitality_suite.patches.v0_5.minimal_integration_receipts import execute
        tracked=('Sales Invoice','Payment Entry','HS Payment','Stock Entry','GL Entry','Payment Ledger Entry','Stock Ledger Entry')
        before={dt:frappe.db.count(dt) for dt in tracked}
        raw=canonical(dict(id='legacy-fictional',card=dict(number='FICTIONAL-PAN'),text='FICTIONAL-SECRET'))
        with operation():
            event=frappe.get_doc(dict(doctype='HS Integration Event',property=self.prop.name,company=self.prop.company,
                                     provider=self.provider,event_id=uuid.uuid4().hex,status='Failed',attempts=2,
                                     payload=raw,last_error='FICTIONAL-SECRET')).insert(ignore_permissions=True)
            current=frappe.get_doc(dict(doctype='HS Integration Event',property=self.prop.name,company=self.prop.company,
                                       provider=self.provider,event_id=uuid.uuid4().hex,status='Received',attempts=0,
                                       payload=canonical(integrations.receipt_metadata(b'fictional-body')))).insert(ignore_permissions=True)
        event.reload()
        metadata={key:value for key,value in event.as_dict().items() if key not in ('payload','last_error')}
        history=[]
        for source in (event,current):
            version=frappe.get_doc(dict(doctype='Version',ref_doctype='HS Integration Event',docname=source.name,
                                       data=canonical(dict(changed=[['payload',raw,raw],['last_error','',raw],['status','Received','Failed']])))).insert(ignore_permissions=True)
            history.append((version.name,str(version.modified)))
        unrelated=frappe.get_doc(dict(doctype='Version',ref_doctype='HS Property',docname=self.prop.name,
                                     data=canonical(dict(changed=[['brand_name','Antes','Después']])))).insert(ignore_permissions=True)
        unrelated_data=unrelated.data
        audits=frappe.db.count('HS Audit Event')
        self.assertEqual(execute(),dict(events=2,versions=2,errors=1))
        event.reload()
        self.assertEqual({key:value for key,value in event.as_dict().items() if key not in ('payload','last_error')},metadata)
        receipt=frappe.parse_json(event.payload)
        self.assertTrue(integrations.is_receipt_metadata(receipt))
        self.assertEqual(receipt['source'],'legacy_payload')
        self.assertEqual(receipt['body_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(event.last_error,'LEGACY_ERROR_OMITTED')
        for name,modified in history:
            version=frappe.get_doc('Version',name)
            self.assertNotIn('FICTIONAL',version.data)
            self.assertEqual(frappe.parse_json(version.data)['changed'],[['status','Received','Failed']])
            self.assertEqual(str(version.modified),modified)
        unrelated.reload()
        self.assertEqual(unrelated.data,unrelated_data)
        self.assertEqual(frappe.db.count('HS Audit Event'),audits+2)
        self.assertEqual(execute(),dict(events=0,versions=0,errors=0))
        self.assertEqual(frappe.db.count('HS Audit Event'),audits+2)
        self.assertEqual({dt:frappe.db.count(dt) for dt in tracked},before)

    def test_signed_duplicate_is_recorded_once_without_financial_effects(self):
        self.addCleanup(frappe.db.rollback)
        original_request=getattr(frappe.local,'request',None)
        original_ip=getattr(frappe.local,'request_ip',None)
        original_user=frappe.session.user
        prop=frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'},'name')
        provider='synthetic-webhook-test'
        secret='synthetic-test-secret-no-provider'
        external_id=uuid.uuid4().hex
        raw=json.dumps(dict(id=external_id,status='paid',nested=dict(cvv='synthetic-value',card=dict(number='FICTIONAL-PAN')),
                            arbitrary=[dict(token='FICTIONAL-SECRET'),'FICTIONAL-FREETEXT'])).encode()
        stamp=str(int(time.time()))
        signature=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        config={provider:dict(enabled=True,property=prop,secret=secret)}
        before={dt:frappe.db.count(dt) for dt in ('Sales Invoice','Payment Entry','HS Payment')}
        try:
            frappe.set_user('Guest')
            frappe.local.request_ip='192.0.2.'+str(uuid.uuid4().int%254+1)
            with patch.dict(frappe.conf,{'hospitality_integrations':config}):
                frappe.local.request=Request.from_values(method='POST',data=raw,headers={
                    'X-Hospitality-Timestamp':stamp,'X-Hospitality-Signature':'invalid'})
                with self.assertRaises(frappe.PermissionError):
                    integrations.webhook(provider)
                frappe.local.request=Request.from_values(method='POST',data=raw,headers={
                    'X-Hospitality-Timestamp':stamp,'X-Hospitality-Signature':signature})
                first=integrations.webhook(provider)
                second=integrations.webhook(provider)
                self.assertEqual(first['name'],second['name'])
                self.assertEqual(second['status'],'Received')
                self.assertEqual(frappe.db.count('HS Integration Event',{'provider':provider}),1)
                event=frappe.get_doc('HS Integration Event',first['name'])
                self.assertNotIn('synthetic-value',event.payload)
                receipt=frappe.parse_json(event.payload)
                self.assertTrue(integrations.is_receipt_metadata(receipt))
                self.assertEqual(receipt['body_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(receipt['body_bytes'],len(raw))
                for marker in (external_id,'FICTIONAL-PAN','FICTIONAL-SECRET','FICTIONAL-FREETEXT','paid'):
                    self.assertNotIn(marker,event.payload)
                self.assertEqual(event.event_id,hashlib.sha256((provider+'|'+external_id).encode()).hexdigest())
                self.assertEqual({dt:frappe.db.count(dt) for dt in before},before)
        finally:
            frappe.set_user(original_user)
            frappe.local.request=original_request
            frappe.local.request_ip=original_ip
