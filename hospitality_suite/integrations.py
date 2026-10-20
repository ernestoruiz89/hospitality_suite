"""Provider-neutral contracts. No external provider is activated or simulated in production."""
from abc import ABC, abstractmethod
import hashlib
import hmac
import json
import time

import frappe
from frappe.rate_limiter import rate_limit

from hospitality_suite.service import operation, current_all, audit, canonical


class PaymentGateway(ABC):
    @abstractmethod
    def create_intent(self, *, origin, amount, currency, idempotency_key):
        """Return a recoverable provider intent; never equate intent with settled payment."""

    @abstractmethod
    def verify_event(self, raw_body, headers):
        """Return a verified event with stable provider ID and actual settlement status."""


class ChannelGateway(ABC):
    @abstractmethod
    def publish_availability(self, *, property_name, category, intervals, idempotency_key):
        pass

    @abstractmethod
    def normalize_reservation(self, event):
        """Normalized requests must still pass the PMS's inventory transaction."""


class MessagingGateway(ABC):
    @abstractmethod
    def send_confirmation(self, *, recipient, signed_url, idempotency_key):
        pass


class LockGateway(ABC):
    @abstractmethod
    def grant_access(self, *, stay, room, starts_at, ends_at, idempotency_key):
        pass

    @abstractmethod
    def revoke_access(self, *, grant_id, idempotency_key):
        pass


def validate_signature(secret, raw_body, timestamp, signature, now=None):
    if abs((now or time.time())-int(timestamp))>300:
        return False
    expected=hmac.new(secret.encode(),str(timestamp).encode()+b"."+raw_body,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)


def receipt_metadata(raw_body, *, source="webhook"):
    """Persist a receipt fingerprint, never an arbitrary provider body.

    Future adapters must normalize the verified body in memory, then submit
    explicit business commands. Provider status alone cannot post a payment.
    """
    if source not in ("webhook", "legacy_payload"):
        raise ValueError("Unknown integration receipt source")
    return dict(schema="receipt-v1", source=source, body_bytes=len(raw_body),
                body_sha256=hashlib.sha256(raw_body).hexdigest())


def is_receipt_metadata(value):
    """Strict allowlist also makes the legacy-payload migration repeatable."""
    return (isinstance(value, dict) and set(value)=={"schema","source","body_bytes","body_sha256"}
            and value["schema"]=="receipt-v1" and value["source"] in ("webhook","legacy_payload")
            and type(value["body_bytes"]) is int and value["body_bytes"]>=0
            and isinstance(value["body_sha256"],str) and len(value["body_sha256"])==64
            and all(c in "0123456789abcdef" for c in value["body_sha256"]))


@frappe.whitelist(allow_guest=True,methods=["POST"])
@rate_limit(limit=30,seconds=60)
def webhook(provider):
    config=(frappe.conf.get("hospitality_integrations") or {}).get(provider) or {}
    if not config.get("enabled") or not config.get("secret") or not config.get("property"):
        frappe.throw(frappe._("Integración no configurada"),frappe.PermissionError)
    raw=frappe.request.get_data()
    if len(raw)>65536:
        frappe.throw(frappe._("Evento demasiado grande"))
    try:
        valid=validate_signature(config["secret"],raw,frappe.request.headers.get("X-Hospitality-Timestamp"),frappe.request.headers.get("X-Hospitality-Signature") or "")
    except (ValueError,TypeError):
        valid=False
    if not valid:
        frappe.throw(frappe._("Firma inválida o evento vencido"),frappe.PermissionError)
    try:
        values=json.loads(raw)
    except (ValueError,UnicodeError):
        frappe.throw(frappe._("El evento debe ser un objeto JSON válido"))
    identity_value=values.get("id") if isinstance(values,dict) else None
    if (type(identity_value) not in (str,int) or not str(identity_value).strip()
            or len(str(identity_value))>200):
        frappe.throw(frappe._("El proveedor debe enviar un identificador estable"))
    identity=hashlib.sha256((provider+"|"+str(identity_value)).encode()).hexdigest()
    receipt=canonical(receipt_metadata(raw))
    del raw,values,identity_value
    prop=frappe.get_doc("HS Property",config["property"])
    frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(prop.name,))
    with operation():
        existing=current_all("HS Integration Event",filters={"event_id":identity},fields=["name","status"])
        if existing:
            return existing[0]
        record=frappe.get_doc(dict(doctype="HS Integration Event",property=prop.name,company=prop.company,
                                   provider=provider,event_id=identity,status="Received",attempts=0,payload=receipt))
        record.insert(ignore_permissions=True)  # verified provider, fixed event schema; no accounting side effects
        audit(prop,"Verified integration event",record)
    return dict(name=record.name,status=record.status)
