"""Cross-check role Page observations, native ledgers, regressions and exact restoration."""
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
run=read('secondary-finance-native-run.json')
assert (run['tests'],run['integration'],run['unit'])==(407,375,32)
assert not any(run[k] for k in ['errors','failures','skipped'])
xml=ET.parse(E/'secondary-finance-native-tests.xml').getroot()
cases=xml.findall('.//testcase')
assert len(cases)==407 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
for name in ['test_manager_count_delegates_only_native_balance_calculation_and_preserves_actor',
    'test_failed_delegated_count_restores_request_and_accountant_cannot_approve']:
    assert any(row.get('name')==name for row in cases)
js=(E/'secondary-finance-complete-js-tests.log').read_text()
assert all(re.search(rf'^# {key} {value}$',js,re.M) for key,value in
    [('tests',225),('pass',225),('fail',0),('cancelled',0),('skipped',0),('todo',0)])
for name in ['receipt-red','receipt-completion-red','invoice-empty-red']:
    assert '# fail 1' in (E/f'secondary-finance-{name}.log').read_text()
trace=read('secondary-finance-browser.json')
assert set(trace['roles'])=={'HS Manager','HS Cashier','HS Accountant'}
assert trace['desktop_only'] and trace['last_session_logged_out'] and not trace['full_secondary_acceptance']
events={row['label']:row for row in trace['events']}
assert len(events)==48
for name,text in [
    ('cashier-setup-denied','No permitido'),
    ('cashier-expense-required-reason-inline','Complete Motivo y comprobante.'),
    ('cashier-expense-over-limit-preserves-form','El egreso supera el límite'),
    ('cashier-card-reference-required-inline','Complete Referencia bancaria.'),
    ('cashier-settlement-over-pending-rejected','La liquidación supera el importe bruto pendiente'),
    ('cashier-full-settlement-empty-confirmed','No hay movimientos pendientes'),
    ('accountant-new-location-empty','No hay existencias ni mínimos'),
    ('accountant-purchase-quantity-inline','Fila 1, Cantidad: Indique un número válido.'),
    ('accountant-invoice-empty-state-final','No hay recepciones de compra pendientes de facturar.'),
    ('accountant-supplier-pending-empty-after-payments','No hay facturas de compra con saldo pendiente.'),
    ('manager-count-native-permission-rejected','Sin permiso para Reconciliación de inventarios')]:
    assert text in events[name]['text'],name
assert any(row.get('name')=='quantity' and row['value']=='0x10' and row['invalid']=='true'
    for row in events['accountant-purchase-quantity-inline']['inputs'])
assert not any(button['text']=='Añadir fila' for button in events['accountant-receipt-fixed-existing-lines']['buttons'])
assert any(button['text']=='Recibir' for button in events['accountant-complete-receipt-action-still-offered']['buttons'])
assert not any(button['text']=='Recibir' for button in events['accountant-received-complete-no-receive-action-final']['buttons'])
assert not any(button['text']=='Ajustar conteo' for button in events['accountant-floor-stock-one-no-adjust-action']['buttons'])
assert any(row.get('name')=='amount' and row['value']=='40.00' for row in events['cashier-settlement-review-closed-values-retained']['inputs'])
assert events['manager-native-permission-dismissal-returned-desktop']['url'].endswith('/desk')
final=events['manager-count-posted-main-103']
assert '103' in final['text'] and 'manager@hospitality.example.invalid' in final['text']
assert any('VCUWKE54' in name for name in final['bundle'])
assert not any(row['visible'] for row in final['dialogs'])
before=read('secondary-finance-expense-rejected.json')
assert before['counts']['HS Payment']==1 and before['counts']['Journal Entry']==0
assert before['shifts'][0]['expected_now']['NIO']=='600.00'
cancel=read('secondary-finance-settlement-cancelled.json')
assert cancel['counts']['HS Payment']==4 and cancel['counts']['Journal Entry']==2
assert not any(row['kind']=='Settlement' for row in cancel['payments'])
partial=read('secondary-finance-partial-receipt.json')
assert partial['stock'][0]['actual_qty']==102 and partial['counts']['Purchase Receipt']==1
assert partial['counts']['Purchase Invoice']==0
received=read('secondary-finance-fully-received-unbilled.json')
assert received['counts']['Purchase Receipt']==2 and received['counts']['Purchase Invoice']==0
assert received['purchase_orders'][0]['per_received']==100 and received['stock'][0]['actual_qty']==106
done=read('secondary-finance-completed.json')
assert done['counts']=={'HS Booking':1,'HS Stay':1,'HS Charge':1,'HS Payment':8,'HS Shift':2,
    'HS Expense Category':1,'HS Supplier':1,'Sales Invoice':0,'Payment Entry':4,'Journal Entry':4,
    'Purchase Order':1,'Purchase Receipt':2,'Purchase Invoice':2,'Stock Entry':3,'Stock Reconciliation':1,
    'GL Entry':34,'Stock Ledger Entry':7,'File':2}
assert Counter(row['kind'] for row in done['payments'])==Counter(Advance=2,Expense=1,Withdrawal=1,Settlement=2,**{'Supplier Payment':2})
settlements=[row for row in done['payments'] if row['kind']=='Settlement']
assert [sum(row[key] for row in settlements) for key in ['amount','fee_amount','withholding_amount','net_amount']]==[100,5,1,94]
assert len({row['source_payment'] for row in settlements})==1
for shift in done['shifts']:
    expected={'cashier@hospitality.example.invalid':470,'accountant@hospitality.example.invalid':40}[shift['cashier']]
    assert shift['status']=='Closed' and shift['counted_amount']==expected and shift['difference']==0
    assert float(shift['expected_now']['NIO'])==expected
assert {row['warehouse']:row['actual_qty'] for row in done['stock']}=={'Stores - HSD':103,'Piso de aceptación financiera - HSD':1}
assert sorted(row['grand_total'] for row in done['purchase_invoices'])==[20,40]
assert all(row['docstatus']==1 and not row['update_stock'] and not row['outstanding_amount'] for row in done['purchase_invoices'])
assert not done['manager_has_general_count_write']
recon=done['stock_reconciliations'][0]
assert (recon['docstatus'],recon['owner'],recon['modified_by'],recon['difference_amount'])==(1,'manager@hospitality.example.invalid','manager@hospitality.example.invalid',-10)
assert done['count_audit'][0]['actor']==recon['owner'] and done['count_audit'][0]['source_name']==recon['name']
for rows in [done['gl'],done['stock_ledger']]:
    matching=[row for row in rows if row['voucher_type']=='Stock Reconciliation']
    assert matching and all(row['voucher_no']==recon['name'] and row['owner']==recon['owner'] for row in matching)
balances=defaultdict(float)
for row in done['gl']:balances[(row['voucher_type'],row['voucher_no'])]+=row['debit']-row['credit']
assert all(abs(value)<0.000001 for value in balances.values())
rejected=read('secondary-finance-stock-count-rejected.json')
assert rejected['counts']['Stock Reconciliation']==0 and rejected['counts']['GL Entry']==32
inventory=read('secondary-finance-actions.json')
assert inventory['handler_count']==84 and len(inventory['buttons'])==97 and len(inventory['sources_sha256'])==30
assert not inventory['unbound_literal_actions'] and not inventory['unresolved_dynamic_buttons']
assert all(sha(ROOT/name)==digest for name,digest in inventory['sources_sha256'].items())
restored=read('secondary-finance-ux-restored.json')
assert restored['restored'] and (restored['tables'],restored['rows'])==(71,185)
assert read('secondary-finance-upgrade.json')['sites']=={
    'hospitality.localhost':dict(tables=72,rows=1246,private_files=2),
    'hospitality-acceptance.localhost':dict(tables=72,rows=250,private_files=0)}
files=read('secondary-finance-files-restored.json')
assert files['original_physical_files']==741 and files['all_original_bytes_preserved']
assert files['native_artifacts_preserved_outside_site']==11
audit=json.loads((ROOT/'docs/specification-audit.json').read_text())
counts=Counter(row['status'] for row in audit['items'])
assert len(audit['items'])==218 and counts==Counter(V=212,I=6)
assert audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
panel=(ROOT/'hospitality_suite/public/js/hospitality.js').read_text()
assert 'd.hide();if(this[`action_${a}`])await this[`action_${a}`](id2)' in panel
ports={}
for port in [8086,8089,8091,9001,9003,11001,13001,11003,13003]:
    with socket.socket() as connection:
        connection.settimeout(.3);ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
assert {key for key,value in ports.items() if value}=={'8086','9001','11001','13001'}
restart=json.loads((BENCH/'.hospitality-secondary-finance-main-restarted.json').read_text())
for name in ['web','worker']:
    assert (BENCH/'.hospitality-run'/f'{name}.pid').read_text().strip()==restart['after'][name]
assert (BENCH/'.hospitality-secondary-finance-main-restarted.json').stat().st_mtime>(ROOT/'hospitality_suite/controllers.py').stat().st_mtime
bundle=json.loads((BENCH/'sites/assets/assets.json').read_text())['hospitality.bundle.js']
assert bundle.endswith('hospitality.bundle.VCUWKE54.js')
for url in ['http://hospitality.localhost:8086/login','http://hospitality.localhost:8086'+bundle]:
    with urllib.request.urlopen(url,timeout=10) as response:
        assert response.status==200
        if url.endswith('.js'):served=hashlib.sha256(response.read()).hexdigest()
assert served==sha((BENCH/'sites'/bundle.lstrip('/')).resolve())
for app in ['frappe','erpnext']:
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=BENCH/'apps'/app)
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),statuses=dict(counts),newly_closed_requirements=[],
    source_sha256=audit['sha256'],audit_sha256=sha(ROOT/'docs/specification-audit.json'),native=dict(tests=407,integration=375,unit=32,failures=0,errors=0,skipped=0),
    javascript=dict(tests=225,desk=222,portal=3),browser=dict(roles=trace['roles'],events=48,desktop_only=True),
    reviewed_task_families=['T11','T19'],native_count_general_write_granted=False,
    native_count_actor_preserved=True,acceptance_restored=True,main_business_mutations=False,
    original_physical_files_preserved=741,bundle=bundle,served_bundle_sha256=served,ports=ports,
    current_python_sha256={path.relative_to(ROOT).as_posix():sha(path) for path in (ROOT/'hospitality_suite').rglob('*.py')},
    full_secondary_acceptance=False,final_F26_complete=False,current_package_contains_this_phase=False,
    remaining_native_stay_panel_rapid_activation_review=True,ota_sync_deferred_by_user=True,
    references_sha256={path.name:sha(path) for path in E.glob('secondary-finance-*') if path.name!='secondary-finance-verification.json'},
    screenshots_sha256={path.name:sha(path) for number in range(366,375) for path in E.glob(str(number)+'-*')})
(E/'secondary-finance-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',newline='\n')
print(json.dumps(dict(native=407,javascript=225,roles=3,browser_events=48,reviewed_families=['T11','T19'],
    open_requirements=6,acceptance_restored=True,all_original_files_preserved=741)))
