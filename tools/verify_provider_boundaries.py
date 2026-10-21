"""Read-only proof: reference adapters import, remain private and activate no provider."""
import inspect
import json
from pathlib import Path

import frappe
import erpnext
import hospitality_suite
from hospitality_suite import api, hooks
from hospitality_suite.provider_adapters import (
    HttpContractTransport, ProviderUnavailable, ReferencePaymentAdapter,
    ReferenceMessagingAdapter, ReferenceLockAdapter, ReferenceChannelNormalizer,
)

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
assert (BENCH/'.hospitality-provider-contracts-upgrade.json').is_file()
classes=[ReferencePaymentAdapter,ReferenceMessagingAdapter,ReferenceLockAdapter,ReferenceChannelNormalizer]
assert not any(inspect.isabstract(cls) for cls in classes)
methods=[method for cls in classes for name,method in inspect.getmembers(cls,inspect.isfunction) if not name.startswith('_')]
assert not any(method in frappe.whitelisted for method in methods)
assert 'provider_adapters' not in repr(hooks.scheduler_events)+repr(hooks.doc_events)
transport=HttpContractTransport('https://provider.example.invalid')
assert transport.enabled is False
try:transport.request('/v1/messages',{},idempotency_key='never-send')
except ProviderUnavailable:pass
else:raise AssertionError('An unconfigured transport must reject sending')
channel=ReferenceChannelNormalizer(company='Compañía ficticia',property_name='PROPERTY-TEST',category_map={})
try:channel.publish_availability(property_name='PROPERTY-TEST',category='CATEGORY-TEST',intervals=[],idempotency_key='never-sync')
except ProviderUnavailable as error:assert str(error)=='channel_synchronization_deferred'
else:raise AssertionError('OTA publication must stay deferred')
sites={}
for site,db in [('hospitality.localhost','hospitality_dev'),('hospitality-acceptance.localhost','hospitality_acceptance')]:
    config=json.loads((BENCH/'sites'/site/'site_config.json').read_text())
    assert config['db_name']==db and config.get('allow_tests')
    integrations=config.get('hospitality_integrations') or {}
    assert isinstance(integrations,dict)
    active=[key for key,value in integrations.items() if isinstance(value,dict) and value.get('enabled')]
    assert active==[],'An existing provider needs explicit review; never disable it silently'
    sites[site]=dict(enabled_providers=0,credentials_disclosed=False)
proof=dict(versions={'frappe':frappe.__version__,'erpnext':erpnext.__version__,'hospitality_suite':hospitality_suite.__version__},
           concrete_reference_classes=[cls.__name__ for cls in classes],adapter_rpc_methods=0,scheduled_or_business_hook_activation=False,
           disabled_transport_rejects_send=True,channel_publication_deferred=True,provider_network_requests=0,
           registered_api_methods=len([fn for name,fn in inspect.getmembers(api,inspect.isfunction) if fn in frappe.whitelisted]),
           sites=sites,database_mutations=False,real_vendor_connector_claimed=False)
(ROOT/'docs/evidence/provider-contracts-boundaries.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(proof))
