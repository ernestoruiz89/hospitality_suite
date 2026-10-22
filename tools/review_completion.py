"""Bind the unchanged 218 clauses to current code, real tests and scoped evidence.

This records the final review; it never promotes requirement states. Class-level
test references complement each clause's existing individual implementation and
evidence, and do not claim that every case exercises every clause in its section.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,re,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence'
parser=argparse.ArgumentParser()
parser.add_argument('--stage',choices=['preflight','final'],required=True)
args=parser.parse_args()
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
audit=json.loads((ROOT/'docs/specification-audit.json').read_text(encoding='utf-8'))
assert len(audit['items'])==218 and audit['sha256']=='876632e08057a1ea0386bd9e01fde6f477c62380a9414bed23e2a852765fb651'
native=read('final-recovery-native-run.json');assert (native['tests'],native['integration'],native['unit'])==(410,378,32)
assert not any(native[k] for k in ['errors','failures','skipped','exit_code'])
xml=ET.parse(E/'final-recovery-native-tests.xml').getroot();cases=xml.findall('.//testcase')
assert len(cases)==410 and not any(xml.findall('.//'+tag) for tag in ['failure','error','skipped'])
environment=read('f26-candidate-environment.json');package=read('completion-code-package.json')
assert package['app_version']=='0.8.9' and package['application_bytes_identical'] and package['application_files']==332
for name,digest in environment['application_file_sha256'].items():
    assert sha(ROOT/name)==digest,name
    original=subprocess.check_output(['git','show',package['revision']+':'+name],cwd=ROOT)
    assert hashlib.sha256(original).hexdigest()==digest
assert subprocess.check_output(['git','diff','--name-only','bcfcf09',package['revision'],'--','hospitality_suite'],cwd=ROOT,text=True).splitlines()==['hospitality_suite/__init__.py']
assert read('f26-verification.json')['F26_coordinated_recovery_verified']
assert read('f26-js-run.json')['tests']==232 and not read('f26-js-run.json')['exit_code']
ui=read('privacy-portal-actions.json')
assert ui['handler_count']==84 and not ui['unbound_literal_actions'] and not ui['unresolved_dynamic_buttons']
assert all(sha(ROOT/name)==digest for name,digest in ui['sources_sha256'].items())
tasks=read('privacy-portal-task-acceptance.json');assert len(tasks['task_families'])==22

# Review judgments are feature-specific. The original per-clause source/evidence
# list remains attached below, rather than being replaced with a green count.
SECTIONS={
0:('TestRoleAcceptance TestRoleFlow TestInitialSetup',
   'Aplicación instalable y operación por Pages: el recorrido real incluye reserva/entrada/consumo/extensión/cobro/salida, limpieza e inspección, rastreo contable y reportes; los cierres generales requieren el paquete de entrega.',
   'ACEPTACION_Y_DEMOSTRACION.md RETENCION_Y_PORTAL_DESDE_PAGES.md ACTUALIZACION_Y_RECUPERACION_FINAL.md'),
1:('TestInitialSetup TestLocalization TestLanguageReview TestGuestProfiles TestSetupReporting',
   'Se contrastan marca editable, compañías/sedes, tres modalidades, idioma, moneda/zona, identificación e impuestos configurables. El entorno/versiones y núcleos limpios son evidencia de infraestructura, no inferencias de pruebas unitarias.',
   'ARQUITECTURA.md IDIOMA_Y_ETIQUETAS.md ACTUALIZACION_Y_RECUPERACION_FINAL.md'),
2:('TestInitialSetup TestLifecycle TestRoleAcceptance TestServiceAccounting TestSecurityRecovery',
   'DocTypes HS y tablas hijas nativos; huésped/acompañante/pagador separados; segmentos y folios; moneda/tiempo explícitos. Los cargos operativos enlazan documentos estándar y no son un segundo libro mayor o stock.',
   'MODELO_ESTADOS_Y_FLUJOS.md ARQUITECTURA.md CONTABILIDAD.md'),
3:('TestInitialSetup TestSetupReporting TestDocumentNaming TestPrintDelivery TestPaymentPolicies TestServiceAccounting',
   'El asistente expone los campos de sede/habitación/tarifa, políticas, usuarios/series/formatos y mapeos nativos. La habilitación financiera valida cuentas e impuestos sin crear maestros arbitrarios.',
   'AUDITORIA_CONTABILIDAD_SERVICIOS.md UX_FORMULARIOS.md ROPA_Y_POLITICAS_DESDE_PAGES.md'),
4:('TestDeskBoard TestRoleAcceptance TestPermissionsAudit TestAvailabilitySearch TestGuestProfiles TestPrintDelivery',
   'Once Pages y 22 familias de tareas con controles/paneles propios; recorridos de teclado/nueve roles y móvil; estados/validaciones, filtros y reconexión. Los 84 bindings no se cuentan como 84 nuevos recorridos GUI.',
   'TAREAS_Y_ESTADOS_POR_ROL.md TECLADO_Y_FOCO.md PANEL_ESTANCIA_Y_ESTADOS.md TIEMPO_REAL_SITIOS_LOCALES.md RETENCION_Y_PORTAL_DESDE_PAGES.md'),
5:('TestDeskBoard TestAvailabilitySearch TestRoomHistory TestHousekeepingAudit TestTimingMetrics',
   'Se separan ocupación/limpieza/mantenimiento, intervalos consultados y reloj real; nombres/tiempos/saldos según rol, bloqueos y buffer. El historial conserva valores anteriores, límites, paginación y finalización inmutable.',
   'ESTADOS_POR_INTERVALO.md HISTORIAL_HABITACIONES.md DISPONIBILIDAD_VISUAL_Y_LIMITES.md'),
6:('TestAvailabilitySearch TestBookingDrafts TestLifecycle TestOperations TestHoldExpiry TestPortal',
   'Cantidad/capacidad/fechas, reservas físicas o sin asignar y grupos; estados, instrucciones, confirmación, modificación y penalizaciones; expiración e inventario únicos. Las carreras reales tienen una confirmada y una rechazada.',
   'DISPONIBILIDAD_POR_CANTIDAD.md BORRADORES_DE_RESERVA.md AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md'),
7:('TestBookingRateAudit TestPricing TestTimingMetrics TestIncludedServices TestTariffExplanations TestSetupReporting',
   'Una regla ganadora por noche/bloque, temporada/día/pagador/plan, extras/incluidos, cortesías e impuestos; precisión nativa, tolerancia/fracción, modo mixto, snapshots y explicación; meses/años/DST y tiempo del servidor.',
   'AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md EXPLICACION_TARIFA_HISTORICA.md CONTADOR_Y_RELOJ.md'),
8:('TestLifecycle TestOperations TestRoleAcceptance TestGuestProfiles TestFinance TestPaymentPolicies TestAppliedRefunds',
   'Entrada reservada/inmediata, datos mínimos, habitación/tarifa/pagador, cuentas, cambios/extensiones con cotización y disponibilidad; salida, crédito autorizado, garantía separada, limpieza y reversión posterior trazable.',
   'ACEPTACION_Y_DEMOSTRACION.md AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md AUDITORIA_CAJA_CONTABILIDAD.md'),
9:('TestFinance TestFinancialAudit TestInvoicePage TestAppliedRefunds TestGuaranteeRefunds TestTreasury TestServiceAccounting TestPosCreditNotes',
   'Turnos, fondos/retiros/arqueo y diferencias autorizadas; pagos parciales/mixtos/FX/vuelto; anticipo, garantía, invoice/PE/JE nativos y conciliación externa, comisiones/liquidaciones y centros de costo. Sin escritura directa de los tres libros.',
   'AUDITORIA_CAJA_CONTABILIDAD.md AUDITORIA_DEVOLUCIONES.md TESORERIA_Y_COMPRAS_DESDE_PAGES.md CONTABILIDAD.md'),
10:('TestHousekeepingAudit TestMaintenanceLinen TestEquipment TestRoleFlow',
   'Tres tipos de limpieza, checklist y supervisión, objetos/daños, ropa Send/Receive/Loss/reposición con stock; mantenimiento por equipo/habitación, repuestos/evidencia/costos, bloqueos y reapertura sin cancelar reservas.',
   'AUDITORIA_LIMPIEZA_MANTENIMIENTO.md VENTANAS_Y_EVIDENCIAS_PRIVADAS.md ROPA_Y_POLITICAS_DESDE_PAGES.md'),
11:('TestInventoryAudit TestProcurement TestServiceItems TestServiceAccounting TestNativePos TestDirectSales TestIncludedServices',
   'Siete familias de servicios y estados, consumo/venta/room charge, mínimos/almacenes, compras/movimientos/conteos, clasificación/activos. Entrega descuenta stock una vez; cancelación/devolución/POS reutilizan ERPNext; HRMS ausente.',
   'AUDITORIA_INVENTARIO_SERVICIOS.md TESORERIA_Y_COMPRAS_DESDE_PAGES.md AUDITORIA_CONTABILIDAD_SERVICIOS.md'),
12:('TestBusinessWindow TestClosingChecks TestPeriodic TestCloseFinancials TestLifecycle TestAuditHistory',
   'Fecha operativa/corte y ventanas locales, pendientes y diferencias, lotes periódicos idempotentes, revisión de excepciones, resúmenes congelados y recuperación del cierre con autorización/motivo.',
   'FECHA_Y_PENDIENTES_CIERRE.md BITACORA_Y_CIERRES.md AUDITORIA_CAJA_CONTABILIDAD.md'),
13:('TestReportDimensions TestReportingHistory TestTimingMetrics TestFinancialAudit TestClosingChecks TestSetupReporting',
   'Reportes filtrables y paginados/exportados con permisos, producción/cobro/pendientes separados y trazabilidad nativa; hotel noches ADR/RevPAR netos, tiempo por horas/rotaciones, bloqueos/cortesías/unión de intervalos y denominadores cero.',
   'CONTABILIDAD.md AUDITORIA_CAJA_CONTABILIDAD.md'),
14:('TestPortal TestIntegrationContracts TestProviderAdapters TestWebhook',
   'Portal desactivado, mismo motor y retenciones, token firmado/caducidad, confirmación manual sin falso pago. Proveedores son contratos/adaptadores de referencia y pruebas simuladas sin red; OTA real aplazada, no operativa.',
   'CONTRATOS_PROVEEDORES.md RETENCION_Y_PORTAL_DESDE_PAGES.md API.md'),
15:('TestPermissionsAudit TestSecurityRecovery TestPrivacy TestGuestProfiles TestAuditHistory TestDeskBoard',
   'Nueve roles con autorización del servidor y aislamiento de compañía/sede en documentos/links/archivos/exportaciones/eventos; mínimos de datos, retención revisada, bitácora y reversión. Modo discreto, límites de entrada y endpoints acotados.',
   'AUDITORIA_SEGURIDAD.md BITACORA_Y_CIERRES.md RETENCION_Y_PORTAL_DESDE_PAGES.md'),
16:('TestOperations TestSecurityRecovery TestFinance TestPeriodic TestWebhook TestHoldExpiry TestPrivacy',
   'Bloqueo de establecimiento incluso sin asignaciones, lectura vigente y [inicio,fin) con buffer; idempotencia/versión y transacción sin commits intermedios; fallos recuperables y reintentos limitados, con pruebas reales de worker/conexiones.',
   'ARQUITECTURA.md TRABAJOS_Y_REINTENTOS.md TESORERIA_Y_COMPRAS_DESDE_PAGES.md'),
17:('TestOperations TestLifecycle TestFinance TestRoleAcceptance TestRoleFlow TestDemoScenario TestTimingMetrics TestSecurityRecovery',
   'Los dieciséis escenarios mínimos se enlazan individualmente abajo; fixture reproducible separado de install, aceptación por Pages y límites/errores de las pruebas conservados. No se declara certificación productiva ni proveedores activos.',
   'ACEPTACION_Y_DEMOSTRACION.md ACTUALIZACION_Y_RECUPERACION_FINAL.md'),
18:('TestPrintDelivery TestDocumentNaming TestDemoScenario',
   'Artefactos/repositorio/dependencias, metadatos/formatos nativos, diagramas/matriz y guías en español por rol/contabilidad/operación; generador y resultados/capturas reales y lista diferenciada de límites/proveedores.',
   'ENTREGABLES_Y_REVISION.md IMPRESIONES_OPERATIVAS.md MANUAL.md CONTABILIDAD.md OPERACION.md'),
19:('TestInitialSetup TestOperations TestLifecycle TestFinance TestHousekeepingAudit TestPortal TestRoleAcceptance',
   'Fases 1–7 acreditadas por sus hitos, código y recorridos, incluida instalación/actualización/recuperación actuales. La entrega general se cierra solamente con los artefactos y documentación finales, sin reducir alcance.',
   'REVISION_FASES_Y_ACCIONES.md AVANCE.md ACTUALIZACION_Y_RECUPERACION_FINAL.md')}

MINIMUM={
1:['test_01_hotel_advance_consumption_checkout_cleaning'],
2:['test_motel_midnight_grace_overtime_and_prepare_retry','test_motel_blocks_fraction_boundaries_and_night_window'],
3:['test_group_split_folios_has_no_duplicate_charges','test_group_single_invoice_single_balance_and_checkout'],
4:['test_conflicting_room_is_rejected'],
5:['test_category_last_unit_roomless_then_assign'],
6:['test_extension_rejects_next_booking','test_room_change_retains_segments_and_price'],
7:['test_hold_expiry_is_idempotent','test_cancellation_penalty_uses_invoice_and_advance','test_partial_advance_refund_then_invoice'],
8:['test_double_payment_is_one_posting','test_repeated_daily_close_advances_business_date_once'],
9:['test_guarantee_application_is_standard_advance','test_guarantee_is_liability_then_refund'],
10:['test_multicurrency_advance_preserves_exchange','test_cash_change_and_fractional_count','test_close_difference_needs_supervisor_and_blocks_new_payment'],
11:['test_scoped_lists_links_api_and_private_files','test_second_company_and_standard_roles_cannot_bypass_property_stock_scope'],
12:['test_reception_cashier_cleaning_supervisor_end_to_end'],
13:['test_stock_delivery_only_once_and_reversal'],
14:['test_invoice_and_payment_created_outside_pms_sync_and_reverse'],
15:['test_failure_rolls_back_invoice_payment_and_retries_safely'],
16:[]}

native_by_class={}
source_tests={}
for row in cases:
    full=row.get('classname');name=row.get('name');module,_,cls=full.rpartition('.')
    file=ROOT/(module.replace('.','/')+'.py');tree=ast.parse(file.read_text(encoding='utf-8'))
    klass=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name==cls)
    method=next(node for node in klass.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name)
    entry=dict(name=name,classname=full,source=file.relative_to(ROOT).as_posix(),line=method.lineno,
        source_sha256=sha(file),passed=True)
    native_by_class.setdefault(cls,[]).append(entry);source_tests.setdefault(name,[]).append(entry)

reviews=[]
for item in audit['items']:
    classes,note,docs=SECTIONS[item['section']]
    selected=[test for cls in classes.split() for test in native_by_class[cls]]
    if item['section']==17 and int(item['id'].split('-')[1])<=16:
        index=int(item['id'].split('-')[1]);selected=[case for name in MINIMUM[index] for case in source_tests[name]]
    sources={}
    for reference in item['implementation']:
        path=reference.partition('::')[0];assert (ROOT/path).is_file(),path;sources[path]=sha(ROOT/path)
    references=list(dict.fromkeys(item['evidence']+['docs/'+name for name in docs.split()]))
    # Retain canonical evidence before adding new final-review links.
    references=[name for name in references if name not in ['docs/COTEJO_FINAL.md','docs/evidence/completion-preflight-review.json','docs/evidence/completion-final-review.json']]
    for reference in references:assert (ROOT/reference.partition('::')[0]).is_file(),reference
    special=[]
    if item['id'] in ['S16-01','S16-02','S16-04','S16-05','S17-04','S17-05']:
        special+=['release-install-concurrency-room.json','release-install-concurrency-category.json']
    if item['id'] in ['S04-18','S17-15']:special+=['realtime-origins-verification.json','background-jobs-worker.json']
    if item['id'] in ['S04-20','S17-18','S00-02']:special+=['privacy-portal-task-acceptance.json','privacy-portal-browser.json']
    if item['id'] in ['S17-16','S18-01','S19-07','S00-01']:special+=['f26-verification.json','f26-clean-install.json','completion-code-package.json']
    if item['id']=='S09-17':special+=['completion-accounting-source.json']
    for name in special:assert (E/name).is_file(),name
    reviews.append(dict(id=item['id'],source_line=item['line'],requirement=item['requirement'],
        current_status=item['status'],review_basis=note,current_implementation_sha256=sources,
        existing_and_feature_evidence=references,current_passed_native_tests=selected,
        direct_additional_evidence_sha256={name:sha(E/name) for name in special},
        judgment='implemented-and-verified' if item['status']=='V' else 'implementation-and-tests-reviewed; final-delivery-gate-required'))
for name in ['room','category']:
    race=read('release-install-concurrency-'+name+'.json')
    assert race['passed'] and sorted(row['result'] for row in race['sessions'])==['confirmed','rejected']
    assert sha(ROOT/'hospitality_suite/tests/concurrency.py')==race['source_sha256']
accounting=read('completion-accounting-source.json')
assert all(sha(ROOT/row['path'])==row['sha256'] for row in accounting['files'])
assert not any(isinstance(node,ast.Call) and ast.unparse(node.func)=='frappe.db.commit'
    for path in (ROOT/'hospitality_suite').rglob('*.py') if 'tests' not in path.parts
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))))
statuses=Counter(row['status'] for row in audit['items'])
if args.stage=='preflight':assert statuses=={'V':214,'I':4}
else:
    assert statuses=={'V':218}
    assert read('delivery-package-final.json')['application_bytes_identical']
    assert (ROOT/'docs/ENTREGA_FINAL.md').is_file()
proof=dict(at_utc=datetime.now(timezone.utc).isoformat(),stage=args.stage,requirements=218,statuses=dict(statuses),
    original_source_sha256=audit['sha256'],native=dict(tests=410,integration=378,unit=32),javascript=232,
    application_sources_match_tested_candidate=True,all_30_UI_sources_match_accepted_GUI=True,
    read_scope='Original 218 clauses, current implementation, class/case source and recorded pass, individual historical evidence, installed artifact checks and real GUI/worker/race/recovery evidence. No new GUI replay.',
    external_OTA_sync_deferred_by_user=True,providers_are_reference_contracts_and_simulations=True,
    reviewed_requirements=reviews)
path=E/('completion-'+args.stage+'-review.json')
assert not path.exists(),'Preserve the preceding audit observation'
path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(stage=args.stage,requirements=218,statuses=dict(statuses),native=410,javascript=232)))
