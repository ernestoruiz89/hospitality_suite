"""Evidence crosswalk for implementation phases; declarations are reviewed, not inferred from counts."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
executed_revision='fb8c022'
assert not subprocess.check_output(['git','diff',executed_revision,'--','hospitality_suite'],cwd=ROOT)
assert not subprocess.check_output(['git','ls-files','--others','--exclude-standard','--','hospitality_suite'],cwd=ROOT)
native=ET.parse(E/'provider-contracts-native-tests.xml').getroot()
cases=native.findall('.//testcase');assert len(cases)==404
assert not any(native.findall('.//'+name) for name in ['failure','error','skipped'])
modules=Counter(Path(row.get('file','')).stem for row in cases)
actions=read('phase-review-actions.json');architecture=read('phase-review-architecture.json')
artifacts=read('phase-review-native-artifacts.json');preservation=read('phase-review-preservation.json')
assert actions['handler_count']==84 and len(actions['buttons'])==97 and len(actions['load_order'])==29
assert not actions['unbound_literal_actions'] and not actions['unresolved_dynamic_buttons']
assert [row['resolved_actions'] for row in actions['dynamic_bindings']]==[
    ['service','inspect_departure','extend','change_room','folio','companions','adjustment','invoice','payment','checkout'],['detail','booking']]
api_tree=ast.parse((ROOT/'hospitality_suite/api.py').read_text(encoding='utf-8'))
commands=next(node.value for node in api_tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='COMMANDS' for target in node.targets))
command_names={key.value for key in commands.keys}
assert {row['name'] for row in actions['rpc']}.issubset(set(artifacts['api_methods']))
assert {row['name'] for row in actions['mutations']}.issubset(command_names)
assert architecture['app_version']==artifacts['version']=='0.8.8'
assert len(architecture['model'])==35 and len(architecture['pages'])==11 and len(architecture['roles'])==9
assert not architecture['mutations'] and all(value['clean'] for value in architecture['core'].values())
for name,digest in artifacts['source_sha256'].items():assert sha(ROOT/name)==digest,name
for name,digest in actions['sources_sha256'].items():assert sha(ROOT/name)==digest,name
assert preservation['sites']['hospitality.localhost']['rows']==1246 and preservation['sites']['hospitality-acceptance.localhost']['rows']==250
assert not preservation['database_mutations'] and not preservation['new_backup_or_restore']
role=read('role-acceptance-browser.json');role_db=read('role-acceptance-items-ui.json')
assert role['app_version']=='0.8.0' and role['all_sessions_closed']
assert role['sessions'][0]['role']=='HS Receptionist + HS Cashier'
assert 'H101' in role['entered_card'] and 'Alojado' in role['entered_card'] and 'C$ 0.00' in role['paid_card']
assert '3,030.00' in role['closed_shift'] and 'Cerrado' in role['closed_shift']
assert role['extended_end'].startswith('2026-10-22') and 'Sin ocupación' in role['clean_room']
assert role_db['outstanding']==0 and role_db['reconciliation_all_ok'] and role_db['receptionist_role_not_expanded']
housekeeping=read('housekeeping-audit-browser.json')
assert all(housekeeping[name] for name in ['cleaning_started_and_inspection_requested','housekeeper_cannot_release_from_page','supervisor_completed_h101','indefinite_order_created_from_page'])
assert 'Fuera de servicio' in housekeeping['blocked_card'] and 'Sin ocupación' in housekeeping['reopened_card']
stock=read('inventory-audit-browser.json')
assert stock['manager_page_states']==['En proceso','Entregado','Devuelto']
assert [stock['stock_observed'][key] for key in ['main_before','main_delivered','main_returned']]==[98,96,98]
closing=read('audit-history-browser.json')
assert closing['per_execution_snapshot_opened'] and closing['repeated_manager_prepare_confirm']['confirmed_from_page']
assert closing['manager_closed_day']['before']=='2026-10-19' and closing['manager_closed_day']['after']=='2026-10-20'
portal=read('portal-converted.json')
assert portal['status']=='Converted' and portal['booking_status']=='Confirmed' and portal['payments']==0 and portal['request_active_allocations']==0 and portal['booking_active_allocations']==1
providers=read('provider-contracts-boundaries.json')
assert providers['channel_publication_deferred'] and not providers['real_vendor_connector_claimed'] and providers['provider_network_requests']==0

def ids(sections=(),extra=()):
    return [row['id'] for row in audit['items'] if row['section'] in sections or row['id'] in extra]

def entry(status,basis,sources,test_modules,evidence,child_ids=(),remaining=''):
    assert status in ('V','I') and bool(remaining)==(status=='I')
    assert all((ROOT/name).is_file() for name in sources+evidence)
    assert all(modules[name]>0 for name in test_modules)
    assert all(next(row for row in audit['items'] if row['id']==name)['status']=='V' for name in child_ids)
    return dict(reviewed_status=status,basis=basis,implementation=sources,native_modules={name:modules[name] for name in test_modules},
                evidence=evidence,verified_component_requirements=list(child_ids),remaining=remaining)

phases={
 'S19-01':entry('V','Fresh installed environment/model/roles/index inventory, explicit architecture decisions and unchanged 218-entry specification.',
   ['docs/ARQUITECTURA.md','docs/MODELO_ESTADOS_Y_FLUJOS.md','hospitality_suite/schema.py','hospitality_suite/security.py','hospitality_suite/controllers.py'],
   ['test_permissions_audit','test_security_recovery','test_initial_setup'],['docs/evidence/phase-review-architecture.json','docs/evidence/phase-review-native-artifacts.json','docs/AUDITORIA_ARQUITECTURA.md'],
   ids([2,15],['S01-07','S01-08','S01-09','S01-10','S01-11','S18-04','S18-05'])),
 'S19-02':entry('I','Existing installation, setup, room/rate model and inventory exclusion are implemented and tested. Migrate is not evidence of a fresh final installation.',
   ['hospitality_suite/install.py','hospitality_suite/setup.py','hospitality_suite/pricing.py','hospitality_suite/availability.py','pyproject.toml'],
   ['test_initial_setup','test_setup_reporting','test_availability_search','test_security_recovery'],['docs/evidence/phase-review-native-artifacts.json','docs/AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md'],
   ids([3,5,16]),'Ejecutar instalación limpia de la versión final y comprobar su paquete, dependencias, metadatos, permisos y primer arranque. No sustituirla con migrate de los dos sitios existentes.'),
 'S19-03':entry('V','Reception/reservation/stay flows exist in loaded Pages; real earlier Page booking/check-in/extension/checkout and group changes complement the current native/client regression. Global secondary UX acceptance stays open.',
   ['hospitality_suite/operations.py','hospitality_suite/booking_drafts.py','hospitality_suite/public/js/hospitality_workflows.js','hospitality_suite/public/js/hospitality_drafts.js','hospitality_suite/public/js/hospitality_extras.js'],
   ['test_lifecycle','test_operations','test_booking_drafts','test_guest_profiles','test_timing_metrics','test_role_acceptance'],
   ['docs/ACEPTACION_Y_DEMOSTRACION.md','docs/AUDITORIA_FLUJOS_TRANSACCIONES.md','docs/evidence/role-acceptance-browser.json','docs/evidence/role-acceptance-items-ui.json','docs/evidence/24-grupo-modificacion.png','docs/evidence/36-plan-cambio-extension.png'],ids([6,7,8],['S04-02','S04-03','S04-04'])),
 'S19-04':entry('V','Native invoice/payment/guarantee/refund/shift reconciliation is implemented and exercised in the current regression; earlier authorized Page payments and zero-balance/closed-shift/native-ledger trace are preserved.',
   ['hospitality_suite/accounting.py','hospitality_suite/cashier.py','hospitality_suite/treasury.py','hospitality_suite/refunds.py','hospitality_suite/reconciliation.py','hospitality_suite/public/js/hospitality_finance_stock.js'],
   ['test_finance','test_financial_audit','test_applied_refunds','test_guarantee_refunds','test_native_pos','test_pos_credit_notes','test_invoice_page','test_treasury'],
   ['docs/AUDITORIA_CAJA_CONTABILIDAD.md','docs/AUDITORIA_DEVOLUCIONES.md','docs/evidence/role-acceptance-browser.json','docs/evidence/role-acceptance-items-ui.json'],ids([9])),
 'S19-05':entry('V','Cleaning/inspection, blocking/reopening, native stock/services and daily-close flows are implemented. Earlier role Page state transitions and stock/close readbacks complement current native cases.',
   ['hospitality_suite/housekeeping.py','hospitality_suite/inventory.py','hospitality_suite/procurement.py','hospitality_suite/periodic.py','hospitality_suite/closing.py','hospitality_suite/close_checks.py'],
   ['test_housekeeping_audit','test_maintenance_linen','test_inventory_audit','test_procurement','test_periodic','test_audit_history','test_closing_checks'],
   ['docs/AUDITORIA_LIMPIEZA_MANTENIMIENTO.md','docs/AUDITORIA_INVENTARIO_SERVICIOS.md','docs/BITACORA_Y_CIERRES.md','docs/evidence/housekeeping-audit-browser.json','docs/evidence/inventory-audit-browser.json','docs/evidence/audit-history-browser.json'],ids([10,11,12])),
 'S19-06':entry('V','Report definitions/native sources, optional token portal and private reference-provider infrastructure are implemented and tested. No operational vendor or outbound OTA synchronization is claimed.',
   ['hospitality_suite/reports.py','hospitality_suite/report_queries.py','hospitality_suite/portal.py','hospitality_suite/integrations.py','hospitality_suite/provider_adapters.py','hospitality_suite/public/js/hospitality_reporting.js'],
   ['test_report_dimensions','test_reporting_history','test_timing_metrics','test_portal','test_integrations','test_webhook','test_provider_adapters'],
   ['docs/API.md','docs/CONTRATOS_PROVEEDORES.md','docs/evidence/portal-converted.json','docs/evidence/finance-audit-browser.json','docs/evidence/provider-contracts-boundaries.json','docs/evidence/273-portal-escritorio-teclado.jpg'],ids([13,14])),
 'S19-07':entry('I','Current regression, corrections and documentation are delivered. Final broad role/state acceptance and the clean-install/deployment/code+database recovery rehearsal remain unproved.',
   ['README.md','docs/OPERACION.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md','tools/run_native_tests.py'],
   ['test_role_acceptance','test_security_recovery'],['docs/evidence/provider-contracts-native-tests.xml','docs/evidence/provider-contracts-js-tests.log'],
   remaining='Completar S00-02/S04-14/S04-16/S04-20, empaquetado/instalación limpia S18-01/S19-02 y ensayo final F26 de actualización y recuperación coordinada de código, base y archivos en un destino aislado.'),
 'S19-08':entry('I','Phase evidence and progress history are explicit; literal and resolved dynamic Page buttons bind to loaded handlers. Static binding does not prove every action result, and phase 7 remains open.',
   ['docs/AVANCE.md','docs/REQUISITOS.md','hospitality_suite/public/hospitality.bundle.js'],[],['docs/evidence/phase-review-actions.json'],
   remaining='Cerrar la aceptación global de tareas/estados y la fase 7/F26. Mantener el registro y comprobar resultados de las acciones; la presencia de manejador no acredita por sí sola una tarea completada.'),
 'S19-09':entry('V','Past runtime limitations and their fixes are documented; reference-only integrations are distinguished from real providers, and every current incomplete item has an explicit remaining check. Independent work continued without claiming a reduced MVP.',
   ['docs/PENDIENTES.md','docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md','docs/TIEMPO_REAL_SITIOS_LOCALES.md','docs/CONTRATOS_PROVEEDORES.md'],[],
   ['docs/evidence/realtime-origins-diagnostics.json','docs/evidence/provider-contracts-verification.json','docs/evidence/phase-review-preservation.json'])
}
sources=set(actions['sources_sha256'])|{'tools/review_implementation_phases.py','tools/audit_operational_actions.cjs','tools/verify_architecture.py','tools/verify_phase_preservation.py'}
for phase in phases.values():sources.update(phase['implementation']);sources.update(phase['evidence'])
sources.update(['docs/evidence/provider-contracts-native-tests.xml','docs/evidence/provider-contracts-js-tests.log','docs/evidence/phase-review-actions.json','docs/evidence/phase-review-preservation.json'])
proof=dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(),scope='Implementation phase evidence crosswalk; no new business implementation, full test execution or UI replay in this review.',
           application_version='0.8.8',application_matches_executed_revision=executed_revision,native_execution=dict(tests=404,source='provider-contracts-native-tests.xml'),
           client_execution=dict(tests=210,source='provider-contracts-js-tests.log'),loaded_handlers=84,literal_button_occurrences=97,resolved_dynamic_button_groups=2,
           rpc_literals_valid=True,mutation_literals_valid=True,phases=phases,source_and_evidence_sha256={name:sha(ROOT/name) for name in sorted(sources)},
           ui_replay=False,full_suite_rerun=False,new_backup_or_restore=False,external_providers_activated=False,ota_sync_deferred_by_user=True,all_requirements_completed=False)
(E/'phase-review-crosswalk.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(reviewed_phases=len(phases),verified=[key for key,value in phases.items() if value['reviewed_status']=='V'],pending=[key for key,value in phases.items() if value['reviewed_status']=='I'],handler_count=84,ui_replay=False,all_requirements_completed=False)))
