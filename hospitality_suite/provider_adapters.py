"""Hospitality Provider Contract v1 reference adapters, not vendor connectors.

No registry, RPC, job or business hook activates these adapters. An integration
must authorize and validate its committed PMS operation before dispatching it.
Responses alone never post money, create a reservation or change a room.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hospitality_suite.integrations import PaymentGateway, MessagingGateway, LockGateway, ChannelGateway, validate_signature

CONTRACT='hospitality-provider-v1'
LIMIT=65536


class ContractError(ValueError):
    """Safe protocol error code, without the provider's body or credentials."""


class ProviderUnavailable(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    def __init__(self, *, retryable):
        super().__init__('provider_request_failed')
        self.retryable=retryable


def _text(value, maximum=200):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or not value.isprintable():
        raise ContractError('invalid_text')
    return value


def _key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',value):
        raise ContractError('invalid_idempotency_key')
    return value


def _amount(value):
    try:
        if isinstance(value,(bool,float)) or not isinstance(value,(str,int,Decimal)) or len(str(value))>40:
            raise ValueError()
        number=Decimal(value)
        if not number.is_finite() or number<=0 or number.adjusted()>17 or number.as_tuple().exponent < -9:
            raise ValueError()
        result=format(number,'f')
        return result.rstrip('0').rstrip('.') if '.' in result else result
    except (InvalidOperation,ValueError):
        raise ContractError('invalid_amount') from None


def _currency(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z]{3}',value):
        raise ContractError('invalid_currency')
    return value


def _grant_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value) or value in ('.','..'):
        raise ContractError('invalid_grant_id')
    return value


def _instant(value):
    try:
        result=datetime.fromisoformat(value) if isinstance(value,str) else None
        if result is None or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError,OverflowError):
        raise ContractError('invalid_aware_datetime') from None


def _interval(start,end):
    starts,ends=_instant(start),_instant(end)
    if ends<=starts:
        raise ContractError('invalid_interval')
    return starts.isoformat(),ends.isoformat()


def _origin(value):
    try:
        parts=urlsplit(_text(value,8192))
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
            raise ValueError()
        port=parts.port or 443
        return ('https',parts.hostname.casefold(),port)
    except ValueError:
        raise ContractError('invalid_https_origin') from None


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ContractError('duplicate_json_key')
        result[key]=value
    return result


def _constant(value):
    raise ContractError('non_finite_json')


def _json(raw):
    if not isinstance(raw,bytes) or len(raw)>LIMIT:
        raise ContractError('invalid_response_size')
    try:
        value=json.loads(raw,object_pairs_hook=_unique,parse_constant=_constant)
    except (ValueError,UnicodeError):
        raise ContractError('invalid_provider_json') from None
    if not isinstance(value,dict):
        raise ContractError('invalid_provider_object')
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        return None


class HttpContractTransport:
    """One authenticated HTTPS request. Disabled until enabled=True explicitly.

    No implicit retries: an ambiguous timeout may already have been accepted.
    Reuse the same key and payload; the provider must deduplicate durably.
    """
    def __init__(self,base_url,token=None,*,enabled=False,timeout=5,opener=None):
        _origin(base_url)
        parts=urlsplit(base_url)
        if parts.path not in ('','/') or parts.query or parts.fragment:
            raise ContractError('invalid_provider_base_url')
        if type(timeout) not in (int,float) or not 0<timeout<=30:
            raise ContractError('invalid_timeout')
        self.base_url=base_url.rstrip('/')
        self._token=token
        self.enabled=enabled is True
        self.timeout=timeout
        self._opener=opener or build_opener(_NoRedirect())

    def request(self,path,payload,*,idempotency_key):
        if not self.enabled or not self._token:
            raise ProviderUnavailable('provider_disabled_or_missing_credentials')
        _text(self._token,4096)
        key=_key(idempotency_key)
        if not isinstance(path,str) or not re.fullmatch(r'/v1/(?:payment-intents|messages|access-grants(?:/[A-Za-z0-9_.:-]{1,200}/revoke)?)',path):
            raise ContractError('invalid_provider_path')
        if path.endswith('/revoke'):
            _grant_id(path.split('/')[3])
        try:
            raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        except (TypeError,ValueError):
            raise ContractError('invalid_request_json') from None
        if len(raw)>LIMIT:
            raise ContractError('request_too_large')
        request=Request(self.base_url+path,data=raw,method='POST',headers={
            'Authorization':'Bearer '+self._token,'Content-Type':'application/json','Accept':'application/json',
            'Idempotency-Key':key,'X-Hospitality-Payload-SHA256':hashlib.sha256(raw).hexdigest()})
        try:
            with self._opener.open(request,timeout=self.timeout) as response:
                status=response.getcode()
                if not 200<=status<300:
                    raise ProviderFailure(retryable=status==429 or status>=500)
                if response.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                    raise ContractError('invalid_response_content_type')
                return _json(response.read(LIMIT+1))
        except HTTPError as error:
            retryable=error.code==429 or error.code>=500
            try:
                error.close()
            finally:
                raise ProviderFailure(retryable=retryable) from None
        except (URLError,TimeoutError,OSError):
            raise ProviderFailure(retryable=True) from None


class _ReferenceAdapter:
    def __init__(self,transport,*,company,property_name):
        self.transport=transport
        self.scope=dict(company=_text(company),property=_text(property_name))

    def _reply(self,value,statuses):
        if not isinstance(value,dict) or value.get('contract')!=CONTRACT or value.get('scope')!=self.scope:
            raise ContractError('provider_scope_or_contract_mismatch')
        if not isinstance(value.get('status'),str) or value['status'] not in statuses:
            raise ContractError('unexpected_provider_status')
        return dict(id=_text(value.get('id')),status=value['status'])

    def _send(self,path,data,key):
        _key(key)
        value=self.transport.request(path,dict(contract=CONTRACT,scope=dict(self.scope),**data),idempotency_key=key)
        return value


class ReferencePaymentAdapter(_ReferenceAdapter,PaymentGateway):
    def __init__(self,*args,webhook_secret=None,clock=time.time,**kwargs):
        super().__init__(*args,**kwargs)
        self._webhook_secret=_text(webhook_secret,4096) if webhook_secret is not None else None
        self._clock=clock

    def create_intent(self,*,origin,amount,currency,idempotency_key):
        data=dict(origin=_text(origin),amount=_amount(amount),currency=_currency(currency))
        value=self._send('/v1/payment-intents',data,idempotency_key)
        result=self._reply(value,{'pending','requires_action'})
        if value.get('origin')!=data['origin'] or _amount(value.get('amount'))!=data['amount'] or value.get('currency')!=data['currency']:
            raise ContractError('provider_intent_mismatch')
        return dict(result,**data,payment_recorded=False)

    def verify_event(self,raw_body,headers):
        if not self._webhook_secret:
            raise ProviderUnavailable('missing_webhook_secret')
        if not isinstance(raw_body,bytes) or len(raw_body)>LIMIT or not isinstance(headers,dict):
            raise ContractError('invalid_webhook_input')
        lowered={key.casefold():value for key,value in headers.items() if isinstance(key,str)}
        try:
            valid=validate_signature(self._webhook_secret,raw_body,lowered.get('x-hospitality-timestamp'),lowered.get('x-hospitality-signature') or '',now=self._clock())
        except (ValueError,TypeError):
            valid=False
        if not valid:
            raise ContractError('invalid_or_expired_signature')
        value=_json(raw_body)
        result=self._reply(value,{'pending','settled','failed','cancelled','refunded'})
        return dict(result,intent_id=_text(value.get('intent_id')),origin=_text(value.get('origin')),
                    amount=_amount(value.get('amount')),currency=_currency(value.get('currency')),verified=True,payment_recorded=False)


class ReferenceMessagingAdapter(_ReferenceAdapter,MessagingGateway):
    def __init__(self,*args,medium,confirmation_origin,template_id,**kwargs):
        super().__init__(*args,**kwargs)
        if medium not in ('email','whatsapp'):
            raise ContractError('invalid_message_medium')
        self.medium=medium
        self.confirmation_origin=_origin(confirmation_origin)
        parts=urlsplit(confirmation_origin)
        if parts.path not in ('','/') or parts.query or parts.fragment:
            raise ContractError('invalid_confirmation_origin')
        self.template_id=_text(template_id)

    def send_confirmation(self,*,recipient,signed_url,idempotency_key):
        recipient=_text(recipient,254)
        pattern=r'[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+' if self.medium=='email' else r'\+[1-9][0-9]{7,14}'
        if not re.fullmatch(pattern,recipient):
            raise ContractError('invalid_recipient')
        if _origin(signed_url)!=self.confirmation_origin:
            raise ContractError('confirmation_origin_mismatch')
        parts=urlsplit(signed_url);query=parse_qs(parts.query)
        if parts.path!='/hospitality-confirmation' or parts.fragment or set(query)!={'token'} or len(query['token'])!=1 or not query['token'][0]:
            raise ContractError('invalid_confirmation_link')
        value=self._send('/v1/messages',dict(medium=self.medium,recipient=recipient,signed_url=signed_url,template_id=self.template_id),idempotency_key)
        return dict(self._reply(value,{'queued','accepted'}),delivery_confirmed=False)


class ReferenceLockAdapter(_ReferenceAdapter,LockGateway):
    def __init__(self,*args,clock=lambda:datetime.now(timezone.utc),**kwargs):
        super().__init__(*args,**kwargs)
        self._clock=clock

    def grant_access(self,*,stay,room,starts_at,ends_at,idempotency_key):
        start,end=_interval(starts_at,ends_at)
        if _instant(end)<=self._clock():
            raise ContractError('access_interval_expired')
        data=dict(stay=_text(stay),room=_text(room),starts_at=start,ends_at=end)
        value=self._send('/v1/access-grants',data,idempotency_key)
        result=self._reply(value,{'scheduled','active'})
        if value.get('stay')!=stay or value.get('room')!=room or _interval(value.get('starts_at'),value.get('ends_at'))!=(start,end):
            raise ContractError('provider_access_mismatch')
        return dict(result,**data)

    def revoke_access(self,*,grant_id,idempotency_key):
        _grant_id(grant_id)
        value=self._send('/v1/access-grants/'+grant_id+'/revoke',{},idempotency_key)
        result=self._reply(value,{'revoked'})
        if result['id']!=grant_id:
            raise ContractError('provider_grant_mismatch')
        return result


class ReferenceChannelNormalizer(ChannelGateway):
    """Read-only inbound contract mapping. Publishing stays explicitly deferred."""
    def __init__(self,*,company,property_name,category_map):
        self.scope=dict(company=_text(company),property=_text(property_name))
        if not isinstance(category_map,dict):
            raise ContractError('invalid_category_map')
        self.category_map={_text(key):_text(value) for key,value in category_map.items()}

    def publish_availability(self,*,property_name,category,intervals,idempotency_key):
        raise ProviderUnavailable('channel_synchronization_deferred')

    def normalize_reservation(self,event):
        if not isinstance(event,dict) or event.get('contract')!=CONTRACT or event.get('scope')!=self.scope:
            raise ContractError('channel_scope_or_contract_mismatch')
        category=self.category_map.get(_text(event.get('category')))
        if not category:
            raise ContractError('unmapped_category')
        for key in ['quantity','people']:
            if type(event.get(key)) is not int or not 1<=event[key]<=100:
                raise ContractError('invalid_channel_quantity_or_people')
        start,end=_interval(event.get('starts_at'),event.get('ends_at'))
        return dict(external_id=_text(event.get('id')),category=_text(category),quantity=event['quantity'],people=event['people'],
                    starts_at=start,ends_at=end,requires_pms_validation=True,provider_confirmation=False)
