import hashlib
import hmac
import unittest

from hospitality_suite.integrations import validate_signature, receipt_metadata, is_receipt_metadata, PaymentGateway


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

    def test_receipt_drops_all_provider_content_including_unknown_fields(self):
        import json
        value=dict(id="fictional-event",status="paid",nested=dict(card=dict(number="FICTIONAL-PAN"),cvv="FICTIONAL-CVV"),
                   arbitrary=[dict(token="FICTIONAL-SECRET"),"FICTIONAL-FREETEXT"])
        raw=json.dumps(value).encode()
        receipt=receipt_metadata(raw)
        self.assertTrue(is_receipt_metadata(receipt))
        self.assertEqual(receipt['body_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['body_bytes'],len(raw))
        self.assertFalse(any(marker in json.dumps(receipt) for marker in ('FICTIONAL','fictional-event','paid')))
        self.assertFalse(is_receipt_metadata(dict(receipt,number='FICTIONAL-PAN')))
        self.assertFalse(is_receipt_metadata(dict(receipt,body_sha256='g'*64)))
        self.assertFalse(is_receipt_metadata(dict(receipt,body_bytes=True)))
        self.assertEqual(receipt_metadata(raw,source='legacy_payload')['source'],'legacy_payload')

    def test_simulated_intent_is_never_paid(self):
        response=SimulatedPaymentGateway().create_intent(origin="test",amount="10",currency="NIO",idempotency_key="one")
        self.assertEqual(response["status"],"pending")
