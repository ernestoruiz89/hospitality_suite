import hashlib
import hmac
import unittest

from hospitality_suite.integrations import validate_signature, sanitized, PaymentGateway


class SimulatedPaymentGateway(PaymentGateway):
    """TEST DOUBLE ONLY. Does not call or represent an operational payment provider."""
    def create_intent(self,**kwargs):
        return dict(id="simulated-intent",status="pending",**kwargs)

    def verify_event(self,raw_body,headers):
        return dict(id="simulated-event",status="pending")


class TestIntegrationContracts(unittest.TestCase):
    def test_signature_and_expiration(self):
        raw=b'{"id":"event-1"}'
        signature=hmac.new(b"test-secret",b"1000."+raw,hashlib.sha256).hexdigest()
        self.assertTrue(validate_signature("test-secret",raw,1000,signature,now=1001))
        self.assertFalse(validate_signature("test-secret",raw,1000,signature,now=1400))
        self.assertFalse(validate_signature("wrong",raw,1000,signature,now=1001))

    def test_sensitive_fields_redacted(self):
        self.assertEqual(sanitized(dict(nested=dict(cvv="123",card_number="1234"))),dict(nested=dict(cvv="[redacted]",card_number="[redacted]")))

    def test_simulated_intent_is_never_paid(self):
        response=SimulatedPaymentGateway().create_intent(origin="test",amount="10",currency="NIO",idempotency_key="one")
        self.assertEqual(response["status"],"pending")
