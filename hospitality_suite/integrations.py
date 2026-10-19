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


def sanitized(value):
    forbidden={"card_number","pan","cvv","cvc","password","secret","access_token","refresh_token"}
    if isinstance(value,dict):
        return {k:("[redacted]" if k.lower() in forbidden else sanitized(v)) for k,v in value.items()}
    if isinstance(value,list):
        return [sanitized(v) for v in value]
    return value


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
    values=json.loads(raw)
    if not values.get("id") or len(str(values["id"]))>200:
        frappe.throw(frappe._("El proveedor debe enviar un identificador estable"))
    prop=frappe.get_doc("HS Property",config["property"])
    frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(prop.name,))
    identity=hashlib.sha256((provider+"|"+str(values["id"])).encode()).hexdigest()
    with operation():
        existing=current_all("HS Integration Event",filters={"event_id":identity},fields=["name","status"])
        if existing:
            return existing[0]
        record=frappe.get_doc(dict(doctype="HS Integration Event",property=prop.name,company=prop.company,
                                   provider=provider,event_id=identity,status="Received",attempts=0,payload=canonical(sanitized(values))))
        record.insert(ignore_permissions=True)  # verified provider, fixed event schema; no accounting side effects
        audit(prop,"Verified integration event",record)
    return dict(name=record.name,status=record.status)
