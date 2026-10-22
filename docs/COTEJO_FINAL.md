# Cotejo final del alcance obligatorio — 0.8.9

Se revisó el adjunto original, sus **218 entradas con ID/línea/texto y SHA-256 conservados**, los archivos actuales de implementación y las evidencias específicas de cada entrada. [El registro individual](evidence/completion-preflight-review.json) enlaza cada cláusula con sus fuentes actuales, pruebas nativas aprobadas y evidencia anterior; no sustituye una prueba funcional por la existencia de un archivo.

El código de la app coincide en sus **332 archivos** con la candidata instalada y probada en el bench independiente. Desde la aceptación final de Pages de `bcfcf09`, la única diferencia dentro de la app es `__version__`, de 0.8.8 a 0.8.9. Los treinta archivos de interfaz conservan los hashes de su aceptación. Esto permite mantener los recorridos anteriores con sus límites, sin presentarlos como otra ejecución completa de navegador.

## Contraste por sección

| Sección | Entradas | Conclusión y evidencia examinada |
|---|---:|---|
| Objetivo | 2 | Código instalable y once Pages; recorrido completo de operación y seguimiento contable, más tareas secundarias. [Aceptación](ACEPTACION_Y_DEMOSTRACION.md), [colección de tareas](evidence/privacy-portal-task-acceptance.json). |
| 1. Trabajo y producto | 13 | Marca/configuración, tres modalidades, idioma y valores editables; versiones realmente instaladas, núcleos limpios y trabajo en sitios de prueba. [Arquitectura](ARQUITECTURA.md), [entorno](evidence/f26-candidate-environment.json). |
| 2. Arquitectura/modelo | 11 | DocTypes HS, hijos, segmentos y folios; controles/Pages nativos, compañía/sede y fechas explícitas; documentos ERPNext como autoridad contable/stock. [Modelo](MODELO_ESTADOS_Y_FLUJOS.md), [instalación](evidence/f26-clean-install.json). |
| 3. Configuración | 8 | Asistente, habitaciones/tarifas/políticas, usuarios/series/formatos y mapeos; rechazo de configuración financiera inválida sin crear cuentas/impuestos arbitrarios. TestInitialSetup, TestSetupReporting, TestPaymentPolicies y TestServiceAccounting. |
| 4. Pages/UX | 20 | Once Pages, 22 familias, filtros/estados/teclado/móvil, acciones revisadas, reconexión y respuesta válida antes de confirmar. [Tareas](TAREAS_Y_ESTADOS_POR_ROL.md), [teclado](TECLADO_Y_FOCO.md), [últimas variantes](RETENCION_Y_PORTAL_DESDE_PAGES.md). |
| 5. Habitaciones | 7 | Dimensiones separadas, disponibilidad por intervalo, buffer/limpieza, bloqueo e historial completo. TestAvailabilitySearch, TestDeskBoard, TestRoomHistory y TestHousekeepingAudit. |
| 6. Reservas | 10 | Física/categoría/grupos, borrador/hold, cupo único, canales, cotización y modificaciones; caducidad y conflictos. TestBookingDrafts, TestLifecycle, TestOperations y dos carreras reales. |
| 7. Tarifas | 11 | Reglas con prioridad, noche/bloques/fracciones/ventanas, extras/incluidos/impuestos, snapshots y explicación; medianoche/años/DST y reloj servidor. TestBookingRateAudit, TestPricing y TestTariffExplanations. |
| 8. Estancias | 12 | Entrada reservada/inmediata, datos mínimos, folios/cambios/extensión, salida/crédito/garantía/limpieza y corrección posterior autorizada. TestRoleAcceptance, TestLifecycle, TestGuestProfiles y pruebas financieras. |
| 9. Caja/contabilidad | 17 | Turnos/arqueos, pagos/FX/vuelto, anticipo/garantía, factura/PE/JE, devoluciones y liquidaciones; conciliación incluida la edición desde ERPNext. [Auditoría](AUDITORIA_CAJA_CONTABILIDAD.md), [fuentes actuales](evidence/completion-accounting-source.json). |
| 10. Limpieza/mantenimiento | 7 | Checklist, inspección, novedades, ropa e inventario, equipos, bloqueos/recursos/costos/evidencia y reapertura. [Limpieza](AUDITORIA_LIMPIEZA_MANTENIMIENTO.md), [ropa](ROPA_Y_POLITICAS_DESDE_PAGES.md). |
| 11. Servicios/inventario | 10 | Familias/estados/entregas, POS/room charge, compras/traslados/conteos, clasificación/activos y devolución sin doble stock; HRMS ausente. [Inventario](AUDITORIA_INVENTARIO_SERVICIOS.md), [compras](TESORERIA_Y_COMPRAS_DESDE_PAGES.md). |
| 12. Cierre | 7 | Fecha/corte, pendientes/diferencias, cargos idempotentes, excepciones, resumen congelado y recuperación autorizada. TestClosingChecks, TestPeriodic, TestCloseFinancials y TestAuditHistory. |
| 13. Reportes/KPI | 15 | Filtros/paginación/XLSX/PDF/permisos, origen nativo y definiciones; noches/horas, ADR/RevPAR netos, rotaciones, unión de intervalos y cero. TestReportDimensions, TestReportingHistory y TestTimingMetrics. |
| 14. Portal/integraciones | 8 | Portal opcional y token seguro, motor/hold comunes y confirmación manual. Contratos/adaptadores y simulaciones identificadas; proveedores reales separados y OTA aplazada. [Contratos](CONTRATOS_PROVEEDORES.md), [portal](RETENCION_Y_PORTAL_DESDE_PAGES.md). |
| 15. Seguridad/privacidad | 10 | Nueve roles, compañía/sede en API/documentos/archivos/exportaciones/eventos, mínimos de datos, retención y bitácora, reversión, modo discreto y límites de entrada. TestPermissionsAudit, TestSecurityRecovery, TestPrivacy y TestAuditHistory. |
| 16. Integridad | 10 | Bloqueo incluso sin reservas, intervalos y lecturas actuales, idempotencia/versión, atomicidad y reintentos. Sin commits explícitos en Python de producto. [Transacciones](ARQUITECTURA.md), [worker real](TRABAJOS_Y_REINTENTOS.md). |
| 17. Aceptación | 19 | Los dieciséis casos se contrastan individualmente abajo; fixture separado, Pages por roles y resultados/limitaciones explícitos. |
| 18. Entregables | 12 | Repositorio/paquetes/metadatos, nueve impresiones, modelo/estados/flujos, matriz, README/manual/contabilidad/operación, generador y evidencias/lista de límites. [Revisión documental](ENTREGABLES_Y_REVISION.md), [entrega](ENTREGA_FINAL.md). |
| 19. Fases | 9 | Hitos de las siete fases, verificaciones reales y pendientes resueltos sin reducir el alcance; instalación/actualización/recuperación final. [Fases](REVISION_FASES_Y_ACCIONES.md), [F26](ACTUALIZACION_Y_RECUPERACION_FINAL.md). |

El registro individual conserva la asociación original requisito → implementación → evidencia. Las clases de pruebas indicadas son conjuntos complementarios; no se afirma que cada caso cubra cada cláusula de su sección.

## Dieciséis criterios mínimos

1. Hotel con anticipo, consumo, saldo/salida: `TestOperations.test_01_hotel_advance_consumption_checkout_cleaning` y recorrido real de H101.
2. Por tiempo, bloque/tolerancia/extensión/medianoche: TestTimingMetrics y TestBookingRateAudit.
3. Grupo y separación/consolidación por pagador: TestLifecycle, con cargos y factura nativos sin duplicación.
4. Misma habitación simultánea: [dos conexiones con barrera y un ganador](evidence/release-install-concurrency-room.json); el helper y el motor de disponibilidad/bloqueo conservan su código.
5. Último cupo y asignación física: [carrera de categoría](evidence/release-install-concurrency-category.json) y `test_category_last_unit_roomless_then_assign`.
6. Extensión en conflicto y cambio trazable: TestOperations y TestLifecycle.
7. Caducidad/cancelación/no presentación y devolución parcial: TestLifecycle, TestPaymentPolicies, TestFinance y worker real.
8. Doble cobro/cierre repetido: `test_double_payment_is_one_posting`, `test_repeated_daily_close_advances_business_date_once` y protección de envío/reintento en interfaz.
9. Anticipo/garantía y pasivo correcto: TestFinance, TestAppliedRefunds y TestGuaranteeRefunds.
10. Pagos/monedas/redondeo/arqueo: TestFinance, TestFinancialAudit, TestPosCreditNotes y TestTreasury.
11. Aislamiento de sede/compañía/API/archivos: TestSecurityRecovery, TestPermissionsAudit y TestPrivacy.
12. Salida/limpieza/inspección/disponible: TestRoleFlow y recorrido real con sesiones de Limpieza/Supervisión separadas.
13. Minibar, stock único y reversión: TestOperations, TestInventoryAudit e incluidos.
14. Factura/pago desde ERPNext y cancelación: `test_invoice_and_payment_created_outside_pms_sync_and_reverse` y pruebas de conciliación.
15. Corte/error de facturación/job: pruebas de transporte real y recuperación, rollback financiero y [seis escenarios del worker](evidence/background-jobs-worker.json). El PDF/DOM y los fallos inyectados conservan su alcance; no se confunden con fallos reales de red.
16. Instalación limpia/migración previa sin pérdida: [instalación actual](evidence/f26-clean-install.json) y [ensayo coordinado F26](evidence/f26-verification.json), con estado fallido y recuperación de código/base/archivos.

## Ajustes pedidos durante el desarrollo

Se mantienen nombres legibles en informes/selectores y series nuevas sin renombrar referencias antiguas; modalidad visible Hotel/Por tiempo/Mixto; formularios agrupados con acciones revisables; tarjeta que abre reserva con habitación/fechas; detalle de reserva comprensible; PDF de cuenta conciso; disponibilidad verde/rojo con texto y sin repetir «en el intervalo». Las regresiones actuales de documentación/nombres/tarifas/impresión y los 232 casos JS conservan esos cambios. La sincronización real con Airbnb/Booking continúa aplazada por instrucción expresa.

## Alcance de la conclusión

La revisión reúne **410 pruebas nativas actuales, 378 integración/32 unitarias, y 232 JS**, instalación/meta/paquetes y recorridos de navegador de las fases indicadas. No ejecuta otra ronda de 84 acciones ni transforma contratos simulados en proveedores operativos. Los kernels y versiones soportados se limitan al entorno probado; cada despliegue debe configurar sus políticas e impuestos. Las evidencias históricas mantienen fallos previos, fixtures y límites, sin sustituirlos por resultados nuevos.

Los cuatro cierres generales S00-01/S01-12/S19-07/S19-08 se sustentan en este contraste, el paquete de código verificado y la documentación/artefactos de entrega. La comprobación de cierre posterior al paquete definitivo queda en [completion-final-review.json](evidence/completion-final-review.json).
