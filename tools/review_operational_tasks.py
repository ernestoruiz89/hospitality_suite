"""Bounded task/role crosswalk. Source bindings are not UI replay evidence."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'docs/evidence'
read = lambda name: json.loads((E / name).read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
inventory = read('task-state-actions.json')
assert inventory['handler_count'] == 84 and not inventory['unbound_literal_actions']
assert inventory['unresolved_dynamic_buttons'] == 0
assert all(sha(ROOT / name) == digest for name, digest in inventory['sources_sha256'].items())
native = ET.parse(E / 'release-install-native-tests.xml').getroot()
cases = native.findall('.//testcase')
assert len(cases) == 404 and not any(native.findall('.//' + key) for key in ['failure', 'error', 'skipped'])
counts = Counter(case.attrib['classname'].split('.')[-1] for case in cases)

# Each action belongs to exactly one task family. Evidence descriptions state
# what was actually observed; native cases and bindings do not claim a GUI run.
groups = [
    ('Navegación y recuperación', 'Todos', 'owner reload logout clear_room_filters home_queue home_pending',
     ['TestDeskBoard', 'TestPermissionsAudit'], ['INICIO_Y_FILTROS.md', 'ACTIVIDAD_Y_RECUPERACION_PAGES.md', 'TIEMPO_REAL_SITIOS_LOCALES.md'],
     'Inicio, filtros, accesos por rol y recuperación de la Page; no hay formulario técnico obligatorio.'),
    ('Huéspedes y acompañantes', 'Recepción / Gerencia', 'guest guest_edit guest_history companions',
     ['TestGuestProfiles'], ['GESTION_HUESPEDES.md', 'TECLADO_Y_FOCO.md'],
     'Registro y edición de huésped, acompañantes e historial mediante diálogos y resultados legibles.'),
    ('Disponibilidad', 'Recepción', 'availability',
     ['TestAvailabilitySearch'], ['DISPONIBILIDAD_VISIBLE.md', 'SELECTORES_Y_RESERVA_MANUAL.md'],
     'Consulta por cantidad y fechas; tarjeta pasa habitación y fechas a la reserva, sin guardar por consultar.'),
    ('Reservas', 'Recepción', 'reserve booking booking_edit',
     ['TestBookingDrafts', 'TestBookingRateAudit', 'TestHoldExpiry'], ['BORRADORES_DE_RESERVA.md', 'AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md', 'TECLADO_Y_FOCO.md'],
     'Cotización, borrador, confirmación y acciones desde el detalle de reserva.'),
    ('Entrada, estancia y salida', 'Recepción', 'walk_in detail extend change_room checkout inspect_departure',
     ['TestLifecycle', 'TestOperations', 'TestRoleAcceptance'], ['ACEPTACION_Y_DEMOSTRACION.md', 'ESTANCIAS_Y_LLEGADAS.md', 'TECLADO_Y_FOCO.md'],
     'Recorrido completo de entrada, consumo, extensión, liquidación y salida desde Pages; cambio/inspección tienen diálogos propios.'),
    ('Historial de habitación', 'Recepción / Gerencia', 'room_history',
     ['TestRoomHistory'], ['HISTORIAL_HABITACIONES.md'],
     'Rango, paginación y detalle de operaciones sin acceder al formulario interno.'),
    ('Cuentas y ajustes', 'Recepción / Caja / Gerencia', 'folio move_charge billing_party adjustment',
     ['TestFinance', 'TestFinancialAudit'], ['CUENTA_RESUMIDA.md', 'AUDITORIA_CAJA_CONTABILIDAD.md', 'EXPLICACION_TARIFA_HISTORICA.md'],
     'Cuenta, responsables y cargos se revisan desde paneles/diálogos; los movimientos se ejecutan en servidor.'),
    ('Facturación y notas de crédito', 'Caja / Contabilidad / Gerencia', 'invoice credit',
     ['TestInvoicePage', 'TestPosCreditNotes'], ['FACTURACION_DESDE_PAGES.md', 'AUDITORIA_NOTAS_POS.md'],
     'Emitir factura y nota de crédito usa revisión propia y documentos estándar creados por API, sin formulario técnico obligatorio.'),
    ('Turnos', 'Caja', 'open_shift close_shift',
     ['TestFinance', 'TestRoleFlow'], ['ACEPTACION_Y_DEMOSTRACION.md', 'TECLADO_Y_FOCO.md', 'VALIDACION_FORMULARIOS.md'],
     'Apertura, cobro, arqueo por denominación y cierre de turno comprobados con Caja.'),
    ('Cobros, anticipos y garantías', 'Caja / Gerencia', 'payment guarantee',
     ['TestFinance', 'TestAppliedRefunds', 'TestGuaranteeRefunds'], ['AUDITORIA_DEVOLUCIONES.md', 'AUDITORIA_GARANTIAS_APLICADAS.md', 'TECLADO_Y_FOCO.md'],
     'Cobro y devolución con revisión; aplicación de garantía autorizada conserva el documento estándar.'),
    ('Tesorería y egresos', 'Caja / Contabilidad / Gerencia', 'withdrawal cash_expense settlement supplier_payment',
     ['TestTreasury', 'TestProcurement'], ['AUDITORIA_CAJA_CONTABILIDAD.md', 'CONTABILIDAD.md'],
     'Diálogos y cotizaciones propios; sus variantes secundarias aún requieren aceptación visual adicional en S04-20.'),
    ('Venta directa', 'Caja / Gerencia', 'direct_sale return_direct_sale',
     ['TestDirectSales', 'TestNativePos', 'TestPosCreditNotes'], ['AUDITORIA_CAJA_POS.md', 'AUDITORIA_NOTAS_POS.md', 'AUDITORIA_RECIBOS_POS.md'],
     'Venta directa y devolución autorizada reutilizan documentos de ERPNext mediante acciones de la Page.'),
    ('Consumos', 'Recepción / Caja / Gerencia', 'service service_status',
     ['TestInventoryAudit', 'TestServiceItems'], ['AUDITORIA_INVENTARIO_SERVICIOS.md', 'AUDITORIA_SERVICIOS.md', 'ACEPTACION_Y_DEMOSTRACION.md'],
     'Solicitud, preparación, entrega y devolución; una entrega genera un cargo y una salida estándar.'),
    ('Limpieza y ropa', 'Limpieza / Supervisión', 'cleaning schedule_cleaning rework_cleaning linen',
     ['TestHousekeepingAudit', 'TestMaintenanceLinen'], ['AUDITORIA_LIMPIEZA_MANTENIMIENTO.md', 'TECLADO_Y_FOCO.md'],
     'Limpieza y supervisión recorren checklist/inspección/liberación; ropa tiene diálogo propio y pruebas nativas, sin afirmar nuevo recorrido GUI de sus tres variantes.'),
    ('Mantenimiento', 'Mantenimiento / Gerencia / Supervisión', 'maintenance maintenance_parts return_parts maintenance_evidence',
     ['TestMaintenanceLinen', 'TestEquipment', 'TestHousekeepingAudit'], ['AUDITORIA_LIMPIEZA_MANTENIMIENTO.md', 'TECLADO_Y_FOCO.md', 'TAREAS_Y_ESTADOS_POR_ROL.md'],
     'Nuevo recorrido: técnico crea/inicia y entrega repuestos; Gerencia devuelve; Supervisión completa/reabre. Adjuntos conservan evidencia nativa histórica, sin nueva carga GUI.'),
    ('Novedades', 'Limpieza / Mantenimiento / Gerencia', 'incident incident_evidence resolve_incident',
     ['TestMaintenanceLinen', 'TestHousekeepingAudit'], ['AUDITORIA_LIMPIEZA_MANTENIMIENTO.md', 'TAREAS_Y_ESTADOS_POR_ROL.md'],
     'Nuevo recorrido: técnico registra objeto y Gerencia documenta entrega/resolución; no se atribuye al navegador una nueva carga de archivo.'),
    ('Reportes, auditoría y cierre', 'Gerencia / Contabilidad / Auditoría', 'report daily_close view_close view_audit',
     ['TestReportDimensions', 'TestAuditHistory', 'TestClosingChecks'], ['BITACORA_Y_CIERRES.md', 'FECHA_Y_PENDIENTES_CIERRE.md', 'TECLADO_Y_FOCO.md'],
     'Consultas, exportación, detalle de auditoría y preparación/cierre desde Pages, con trazabilidad de documentos estándar.'),
    ('Configuración', 'Administración / Gerencia', 'setup new_property policies denominations portal_settings document_settings assign_user equipment expense_category stock_policy retention_policy payment_policies service_items service_accounting',
     ['TestInitialSetup', 'TestSetupReporting', 'TestPaymentPolicies', 'TestServiceAccounting', 'TestPrivacy'], ['INSTALACION_LIMPIA.md', 'UX_FORMULARIOS.md', 'TECLADO_Y_FOCO.md', 'AUDITORIA_CONTABILIDAD_SERVICIOS.md'],
     'Establecimiento, categoría y tarifa guardados por Pages; los formularios extensos se agrupan por tarea. No se afirma nueva aceptación GUI de todas las políticas.'),
    ('Compras y movimientos de inventario', 'Gerencia / Contabilidad', 'register_supplier create_warehouse purchase_order receive_purchase purchase_invoice move_stock adjust_stock',
     ['TestProcurement', 'TestInventoryAudit'], ['AUDITORIA_INVENTARIO_SERVICIOS.md', 'CONTABILIDAD.md'],
     'Maestros, pedido, recepción, factura y movimientos tienen acciones propias. Pruebas nativas y de interfaz; queda el recorrido visual integral secundario en S04-20.'),
    ('Retención de datos', 'Gerencia autorizada', 'retention retry_retention',
     ['TestPrivacy', 'TestSecurityRecovery'], ['OPERACION.md', 'AUDITORIA_SEGURIDAD.md'],
     'Vista previa/confirmación y reintento explícitos; conservar pendiente la aceptación visual de la ejecución secundaria.'),
    ('Solicitudes del portal', 'Recepción', 'portal_convert',
     ['TestPortal'], ['MANUAL.md', 'API.md'],
     'Conversión por comando validado desde la Page; integración OTA real aplazada por el usuario.'),
    ('Impresiones', 'Según permiso de la operación', 'print_shift print_stay print_registration print_cleaning print_close print_maintenance',
     ['TestPrintDelivery'], ['IMPRESIONES_OPERATIVAS.md'],
     'Accesos desde Pages a nueve formatos con cinco roles; los documentos de ese ensayo fueron fixture API, no creación GUI.'),
]
seen = Counter(action for row in groups for action in row[2].split())
assert set(seen) == set(inventory['effective_handlers']), sorted(set(inventory['effective_handlers']) - set(seen))
assert all(number == 1 for number in seen.values())
rows = []
for number, (title, roles, actions, classes, documents, scope) in enumerate(groups, 1):
    assert all(name in counts for name in classes)
    assert all((ROOT / 'docs' / name).is_file() for name in documents)
    rows.append(dict(id=f'T{number:02}', task=title, roles=roles, actions=actions.split(),
        bindings={action: inventory['effective_handlers'][action] for action in actions.split()},
        historical_native_classes={name: counts[name] for name in classes},
        evidence=[f'docs/{name}' for name in documents], acceptance_scope=scope))

pages = [json.loads(path.read_text()) for path in (ROOT / 'hospitality_suite/hospitality_suite/page').rglob('*.json')]
assert len(pages) == 11
roles = {role['role'] for page in pages for role in page['roles'] if role['role'].startswith('HS ')}
assert len(roles) == 9
# This narrowly checks whether operational sources force navigation to a native
# form. Optional standard document links in reports remain legitimate tracing.
routes = []
for name in inventory['sources_sha256']:
    source = (ROOT / name).read_text()
    for match in re.finditer(r'frappe\.set_route\s*\(([^)]*)\)|frappe\.new_doc\s*\(', source):
        snippet = match.group(0)
        assert snippet == 'frappe.set_route("hospitality-stays")', (name, snippet)
        routes.append(dict(file=name, line=source.count('\n', 0, match.start()) + 1, source=snippet))
assert len(routes) == 1
changed = subprocess.check_output(['git', 'diff', '--name-only', 'ad1f701', '--', 'hospitality_suite'], cwd=ROOT, text=True).splitlines()
assert set(changed) == {'hospitality_suite/public/js/hospitality_forms.js', 'hospitality_suite/public/js/hospitality_workflows.js'}
proof = dict(reviewed_at_utc=datetime.now(timezone.utc).isoformat(), task_families=rows, handlers=84,
    source_inventory_sha256=sha(E / 'task-state-actions.json'), sources_sha256=inventory['sources_sha256'],
    pages={page['name']: [row['role'] for row in page['roles']] for page in sorted(pages, key=lambda p: p['name'])},
    hs_roles=sorted(roles), native_regression=dict(tests=404, rerun=False, execution_revision='be67c92',
        unchanged_current_python=True, junit_sha256=sha(E / 'release-install-native-tests.xml')),
    current_application_changes=changed, native_form_navigation_required=False, explicit_page_navigation=routes,
    distinction='Finite task/role/source crosswalk with historical and new GUI evidence. Binding counts do not mean 84 GUI flows executed.',
    claims=['S00-02: routine work through custom Pages', 'S04-14: frequent actions through own panels/dialogs'],
    still_open=['S04-16: remaining field rules, search/view states and rapid close/open sequences',
        'S04-20: full visual acceptance of remaining secondary tasks', 'S19-07/S19-08: final F26 and delivery'],
    all_requirements_completed=False, ota_sync_deferred_by_user=True)
archive = subprocess.check_output(['git', 'archive', 'be67c92', 'hospitality_suite'], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as sources:
    python_sources = {entry.name: sha(ROOT / entry.name) for entry in sources if entry.isfile() and entry.name.endswith('.py')}
    for name in python_sources:
        assert (ROOT / name).read_bytes() == sources.extractfile(name).read(), name
assert python_sources and not subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', 'hospitality_suite'], cwd=ROOT)
proof['unchanged_python_sources_sha256'] = python_sources
(E / 'task-state-crosswalk.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(task_families=len(rows), handlers=len(seen), pages=len(pages), roles=len(roles), historical_native=404,
    all_handlers_grouped_once=True, native_form_navigation_required=False, all_requirements_completed=False)))
