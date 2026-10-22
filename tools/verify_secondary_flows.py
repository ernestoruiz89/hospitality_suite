"""Verify bounded linen/policy GUI acceptance, native regressions and restoration."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.request
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence'
BENCH=Path('/home/frappe/benches/hospitality-bench')
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
run=read('secondary-flows-native-run.json')
assert (run['tests'],run['integration'],run['unit'])==(409,377,32)
assert not any(run[key] for key in ['errors','failures','skipped','exit_code'])
xml=ET.parse(E/'secondary-flows-native-tests.xml').getroot()
cases=xml.findall('.//testcase')
assert len(cases)==409 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
for name in ['test_penalty_settings_reject_invalid_values_without_request_or_property_changes',
    'test_penalty_settings_accept_percent_endpoints_fractional_rates_and_fixed_amounts']:
    assert any(row.get('name')==name for row in cases)
js=(E/'secondary-flows-js-tests.log').read_text()
assert all(re.search(rf'^# {key} {value}$',js,re.M) for key,value in
    [('tests',230),('pass',230),('fail',0),('cancelled',0),('skipped',0),('todo',0)])
assert '# fail 1' in (E/'secondary-flows-policy-red-js-tests.log').read_text()
browser=read('secondary-flows-browser.json')
assert set(browser['roles'])=={'HS Manager','HS Housekeeping','HS Cashier'}
assert browser['desktop_only'] and not browser['full_secondary_acceptance']
events={row['label']:row for row in browser['events']}
assert len(events)==26 and browser['label_correction']['to'] in events
for label,text in [
    ('manager-policy-125-inline-final','El porcentaje debe estar entre 0 y 100.'),
    ('manager-no-show-negative-inline','Indique un importe de 0 o más.'),
    ('housekeeping-setup-denied','No permitido'),
    ('housekeeping-linen-zero-server-message','Artículo, cantidad o movimiento de ropa inválido'),
    ('housekeeping-loss-reason-required','Indique el motivo de la pérdida')]:
    assert text in events[label]['text'],label
assert any(row.get('name')=='cancellation_fee_value' and row['invalid']=='true' and row['value']=='125.00'
    for row in events['manager-policy-125-inline-final']['inputs'])
assert any(row.get('name')=='no_show_fee_value' and row['invalid']=='true' and row['value']=='-1.00'
    for row in events['manager-no-show-negative-inline']['inputs'])
choice=next(row for row in events['cashier-policies-effect']['policyChoices'] if row['label']=='Concepto')['options']
assert not any(row['value']=='Advance' for row in choice)
assert next(row for row in choice if row['value']=='Guarantee')['disabled']
assert all(not row['disabled'] for row in choice if row['value'] in ['Refund','Guarantee Refund'])
assert 'Reponer' in events['manager-replenishment-alert-nine']['text']
assert 'Reponer' not in events['manager-stock-final-ten-no-alert']['text']
assert events['cashier-logged-out']['url'].split('/')[3].startswith('login')
before=read('secondary-flows-fixture.json')
zero=read('secondary-flows-linen-zero-rejected.json')
assert before['stock']==zero['stock'] and before['stock_entries']==zero['stock_entries']
received=read('secondary-flows-linen-received.json')
rejected=read('secondary-flows-linen-loss-rejected.json')
assert received['stock']==rejected['stock'] and received['stock_entries']==rejected['stock_entries']
stocks=lambda name:{r['warehouse']:r['actual_qty'] for r in read(name)['stock']}
laundry='Lavandería de aceptación operativa - HSD';reserve='Reserva de ropa de aceptación - HSD';operational='Stores - HSD'
assert stocks('secondary-flows-linen-sent.json')=={laundry:4,reserve:5,operational:6}
assert stocks('secondary-flows-linen-received.json')=={laundry:1,reserve:5,operational:9}
assert stocks('secondary-flows-linen-loss-completed.json')=={laundry:0,reserve:5,operational:9}
assert stocks('secondary-flows-completed-ui.json')=={laundry:0,reserve:4,operational:10}
done=read('secondary-flows-completed-ui.json')
assert all(value==0 for value in done['finance_counts'].values())
assert sorted(row['quantity'] for row in done['linen_incidents'])==[1,3,4]
assert all(row['owner']=='housekeeping@hospitality.example.invalid' and row['status']=='Resolved' for row in done['linen_incidents'])
entries=[row for row in done['stock_entries'] if row['hs_stock_purpose']]
assert len(entries)==4 and all(row['docstatus']==1 for row in entries)
for row in entries:
    assert row['owner']==row['modified_by']==('manager@hospitality.example.invalid' if row['hs_stock_purpose']=='Linen Replacement' else 'housekeeping@hospitality.example.invalid')
loss=next(row for row in entries if row['hs_stock_purpose']=='Waste')
assert loss['stock_entry_type']=='Material Issue' and loss['total_outgoing_value']==25
assert len(done['stock_ledger'])==9 and sum(row['actual_qty'] for row in done['stock_ledger'])==14
balances=defaultdict(float)
for row in done['gl']:balances[(row['voucher_type'],row['voucher_no'])]+=row['debit']-row['credit']
assert all(abs(value)<1e-6 for value in balances.values())
assert read('secondary-flows-policy-after-percent.json')['property']['cancellation_fee_value']==125
fixed=read('secondary-flows-fixed-125-accepted.json')['property']
assert fixed['cancellation_fee_mode']=='Fixed' and fixed['cancellation_fee_value']==125
prop=done['property']
assert (prop['cancellation_fee_mode'],prop['cancellation_fee_value'],prop['no_show_fee_mode'],prop['no_show_fee_value'])==('Percent',25.5,'Fixed',50)
assert (prop['advance_policy'],prop['guarantee_policy'])==('Disabled','Approval')
assert prop['laundry_warehouse']==laundry and prop['portal_enabled']==0 and str(prop['business_date'])=='2026-10-19'
assert len(done['stock_policies'])==1 and done['stock_policies'][0]['purpose']=='Linen'
assert done['reorder']==[dict(warehouse=operational,warehouse_reorder_level=10,warehouse_reorder_qty=5)]
inventory=read('secondary-flows-actions.json')
assert inventory['handler_count']==84 and len(inventory['buttons'])==97 and len(inventory['sources_sha256'])==30
assert not inventory['unbound_literal_actions'] and not inventory['unresolved_dynamic_buttons']
assert all(sha(ROOT/name)==digest for name,digest in inventory['sources_sha256'].items())
for name in ['secondary-flows-first-ux-restored.json','secondary-flows-ux-restored.json']:
    restored=read(name)
    assert restored['restored'] and restored['tables']==71 and restored['rows']==185
files=read('secondary-flows-files-restored.json')
assert files['original_physical_files']==741 and files['all_original_bytes_preserved'] and files['native_artifacts_preserved_outside_site']==11
upgrade=read('secondary-flows-upgrade.json')
assert upgrade['previous_columns_preserved'] and upgrade['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
ports={}
for port in [8086,8089,8091,9001,9003,11001,13001,11003,13003]:
    with socket.socket() as connection:
        connection.settimeout(.3);ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert {p for p,on in ports.items() if on}=={'8086','9001','11001','13001'}
restart=json.loads((BENCH/'.hospitality-secondary-flows-main-restarted.json').read_text())
assert restart['controller_sha256']==sha(ROOT/'hospitality_suite/controllers.py')
for name in ['web','worker']:assert (BENCH/'.hospitality-run'/f'{name}.pid').read_text().strip()==restart['after'][name]
assets=json.loads((BENCH/'sites/assets/assets.json').read_text());bundle=assets['hospitality.bundle.js']
with urllib.request.urlopen('http://hospitality.localhost:8086'+bundle,timeout=10) as response:
    assert response.status==200;served=hashlib.sha256(response.read()).hexdigest()
assert served==sha((BENCH/'sites'/bundle.lstrip('/')).resolve())
assert any(bundle in url for url in events['manager-policy-125-inline-final']['bundle'])
for app in ['frappe','erpnext']:assert not subprocess.check_output(['git','status','--porcelain'],cwd=BENCH/'apps'/app)
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'));counts=Counter(row['status'] for row in audit['items'])
assert len(audit['items'])==218 and counts=={'V':213,'I':5}
assert {row['id'] for row in audit['items'] if row['status']!='V'}=={'S00-01','S01-12','S04-20','S19-07','S19-08'}
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),statuses=dict(counts),newly_closed_requirements=[],
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),
    native=dict(tests=409,integration=377,unit=32,failures=0,errors=0,skipped=0),javascript=dict(tests=230,desk=227,portal=3),
    browser=dict(roles=browser['roles'],events=26,desktop_only=True),reviewed_task_variants=['T14 linen Send/Receive/Loss/replacement','T18 laundry/classification/penalties/payment policies'],
    acceptance_restored=True,main_business_mutations=False,original_physical_files=741,native_artifacts_quarantined=11,
    current_python_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'hospitality_suite').rglob('*.py')},
    bundle=bundle,served_bundle_sha256=served,ports=ports,full_secondary_acceptance=False,final_F26_complete=False,current_package_contains_this_phase=False,
    remaining=['retention-retry','other-private-attachments','portal-conversion','F26-package-delivery'],ota_sync_deferred_by_user=True,
    references_sha256={p.name:sha(p) for p in E.glob('secondary-flows-*') if p.name!='secondary-flows-verification.json'},
    screenshots_sha256={p.name:sha(p) for n in range(380,383) for p in E.glob(str(n)+'-*')})
(E/'secondary-flows-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(native=409,javascript=230,roles=3,browser_events=26,verified=213,open=5,acceptance_restored=True)))
