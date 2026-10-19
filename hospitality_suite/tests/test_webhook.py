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
    def test_signed_duplicate_is_recorded_once_without_financial_effects(self):
        self.addCleanup(frappe.db.rollback)
        original_request=getattr(frappe.local,'request',None)
        original_ip=getattr(frappe.local,'request_ip',None)
        original_user=frappe.session.user
        prop=frappe.db.get_value('HS Property',{'property_name':'Hotel Jardín Demo'},'name')
        provider='synthetic-webhook-test'
        secret='synthetic-test-secret-no-provider'
        raw=json.dumps(dict(id=uuid.uuid4().hex,status='paid',nested=dict(cvv='synthetic-value'))).encode()
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
                self.assertEqual(frappe.parse_json(event.payload)['nested']['cvv'],'[redacted]')
                self.assertEqual({dt:frappe.db.count(dt) for dt in before},before)
        finally:
            frappe.set_user(original_user)
            frappe.local.request=original_request
            frappe.local.request_ip=original_ip
