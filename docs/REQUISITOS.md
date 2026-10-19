# Matriz de alcance obligatorio

Actualizada el 2026-10-19. **El objetivo sigue activo.** V = prueba ejecutada de la parte indicada; I = implementado, verificación pendiente; P = trabajo pendiente. Las pruebas de backend no acreditan por sí solas un recorrido completo de interfaz.

| ID | Requisito | Implementación | Evidencia y trabajo pendiente | Estado |
|---|---|---|---|---|
| F01 | Inspección y versión objetivo | ARQUITECTURA.md | Frappe 16.52.0, ERPNext 16.51.1, WSL/MariaDB inspeccionados | V |
| F02 | App nativa y migraciones | schema.py, hooks.py, install.py, patches/ | Dos sitios nuevos y migraciones repetidas de 0.1 a 0.2 conservando reserva previa | V |
| F03a | Configuración financiera por establecimiento | api.save_setup, controllers.py | Validación de cuentas, moneda, compañía, horarios y penalizaciones probada | V |
| F03b | Usuarios, series y formatos desde Page | setup.py, hospitality_workflows.js | Implementado; falta probar asistente y denegación de rol no autorizado | I |
| F04 | Ocupación, limpieza y bloqueos separados | HS Room, HS Allocation | test_operations, lifecycle y role_flow | V |
| F05 | Intervalos, grupos y cupo por categoría | availability.py, service.current_all | Dos conexiones reales: exactamente una confirmación en habitación y último cupo | V |
| F06a | Hotel/motel y snapshots históricos | pricing.py, operations.py | Límites, gracia, medianoche/año, DST, extensión y cambio de categoría | V |
| F06b | Camas extra, temporadas y paquetes | pricing.py, schema.py, Pages | Cama extra y tarifa histórica probadas; falta recorrido de configuración | I |
| F07 | Reservas, modificación, cancelación y retenciones | operations.py, portal.py, jobs.py | lifecycle y portal aprobados; falta scheduler real | I |
| F08a | Entrada, extensión, cambio y salida | operations.py, timing.py | operations, lifecycle, timing_metrics; entrada M101 confirmada también en Page | V |
| F08b | Acompañantes, Contact y Address estándar | operations.companions, api.create_guest | Capacidad, acompañantes y Contact/Address estándar probados; diálogo pendiente | I |
| F09 | Folios separados y factura grupal única | accounting.py | Reparto de pagadores, factura consolidada con anticipo, saldo compartido y ambas salidas | V |
| F10 | Facturación y conciliación estándar | accounting.py | Anticipo antes/después de factura, turno histórico cerrado, sin duplicar efectivo | V |
| F11 | Garantía separada, devolución y aplicación | accounting.py | Pasivo, aplicación antes/después de factura y retorno USD con variación de cambio aprobados | V |
| F12a | Caja, parciales, monedas y diferencias | accounting.py, cashier.py | NIO/USD, doble envío, diferencia, devolución, retiro probado | V |
| F12b | Denominaciones y vuelto | cashier.py, workflows JS | Vuelto C$70 y arqueo/cierre de C$630 desde Page; conteo fraccionario rechazado | V |
| F13 | Limpieza, asignación e inspección | housekeeping.py, Page | Checklist incompleto rechazado y circuito de roles probado; móvil pendiente | I |
| F14 | Mantenimiento, ropa y objetos | housekeeping.py, linen.py | Bloqueos/conflictos probados; costos, repuestos/evidencias y recorridos pendientes | I |
| F15a | Servicios y existencias únicas | inventory.py | Entrega repetida de minibar: una salida y reversión estándar | V |
| F15b | Venta directa y devolución | direct_sales.py | Factura/pago/salida únicos, reintento, devolución y rollback por falta de stock | V |
| F15c | Compras, traslados, mínimos y mermas | hooks estándar, inventory_status, linen.py | Mínimos visibles; faltan circuitos completos por establecimiento | I |
| F16 | Cierre diario y reapertura | closing.py | Cierre repetido, bloqueo por diferencia y snapshot probados; reapertura pendiente | I |
| F17a | KPI con noches y horas separadas | reports.summary | Cortesía, denominador cero, impuesto incluido, horas reales y bloqueo de mantenimiento probados | V |
| F17b | Reportes, conciliación y exportaciones | reports.py, reconciliation.py, api.export_report | Conciliación hasta origen; PDF y XLSX numérico inspeccionados; auditor no exporta | V |
| F18 | Portal opcional seguro | www/, portal.py | Desactivación, firma, caducidad, retención y conversión probadas; Page pública pendiente | I |
| F19 | Contratos de integración | integrations.py | HMAC/caducidad, redacción y simulación que nunca marca pagado probados | V |
| F20a | Permisos API, documentos, archivos y roles | security.py, hooks.py | security_recovery y role_flow; falta segunda compañía/maestros y navegador por rol | I |
| F20b | Notificaciones estándar por usuario | ScopedERPNotifications | Implementado sin list_update global; Socket.IO pendiente de prueba | I |
| F21 | Idempotencia y recuperación | service.py, jobs.py, JS | Reintento de cobro/cierre, rollback de factura/stock, versión obsoleta; red/worker pendientes | I |
| F22 | Once Pages, teclado y móvil | public/js, bundles, sidebar v16 | Circuito motel completo en Pages con cuatro roles; faltan móvil y recorridos adicionales | I |
| F23 | Impresiones | templates/print, generador | Nueve formatos y exportador: diez PDF generados, texto/render revisados, campos técnicos ocultos | V |
| F24 | Demo explícita de 2 × 10 habitaciones y roles | demo.seed | Carga y repetición ejecutadas; credenciales en archivo privado del sitio sintético | V |
| F25 | Manuales, contabilidad y operación | docs/ | README, manual por rol, contabilidad y operación escritos; falta probar restauración/reversión | I |
| F26 | Instalación/migración final sin pérdida | bootstrap WSL, patches | Reserva anterior conservada; instalación adicional y restauración pendientes | I |

## Criterios de aceptación de la especificación

| Criterio | Prueba ejecutada | Page / ampliación pendiente |
|---|---|---|
| 1 Hotel, anticipo, consumo y salida | test_operations.test_01_hotel_advance_consumption_checkout_cleaning | Circuito hotel completo pendiente; motel completo acreditado |
| 2 Motel, gracia y medianoche | pricing, timing_metrics, lifecycle | Reserva/entrada, consumo, extensión, cobro y salida M101 acreditados |
| 3 Grupo y separación de factura | group_split_folios y group_single_invoice_single_balance_and_checkout | Circuito de Page |
| 4 Habitación simultánea | concurrency.verify, REPEATABLE-READ | No aplica a un navegador único |
| 5 Último cupo y asignación física | concurrency.verify_category y category_last_unit_roomless_then_assign | Circuito de Page |
| 6 Extensión conflictiva y cambio | extension_rejects_next_booking y cambios con segmentos/cotización | Circuito de Page |
| 7 Expiración, penalización y devolución parcial | lifecycle, finance, portal | Scheduler y Page |
| 8 Doble cobro y cierre repetido | finance y lifecycle | Reintento visible |
| 9 Anticipo y garantía sin doble ingreso | finance, incluido turno histórico y garantía no efectiva | Circuito de Page |
| 10 Monedas, vuelto y arqueo | finance y cash_change_and_fractional_count | Arqueo y vuelto acreditados en Page |
| 11 Compañía/establecimiento/API/archivo | security_recovery y referencias cruzadas | Segunda compañía y Page |
| 12 Salida, limpieza e inspección | role_flow con cuatro roles operativos | Escritorio acreditado por cuatro roles; móvil pendiente |
| 13 Minibar y reversión | operations, direct_sales | Circuito de Page |
| 14 Operaciones externas ERPNext | finance y sync_document | Factura/pago externos y sus cancelaciones probados; transporte entre sesiones pendiente |
| 15 Fallos y recuperación | rollback de factura/stock e idempotencia | Corte de red y trabajo programado |
| 16 Instalar y migrar sin pérdida | Instalación inicial y dos patches ejecutados | Segundo sitio limpio acreditado; restauración pendiente |

## Evidencia acumulada

Batería conjunta anterior a las últimas ampliaciones: **50 aprobadas** (39 de integración y 11 puras). Ampliación de horarios, acompañantes y KPI: **4 aprobadas** por separado. La cortesía detectó una incompatibilidad con tarifas negativas; se corrigió con descuento en la línea estándar y referencias a sus cargos de origen. Última batería conjunta en hospitality-clean.localhost: **65 aprobadas** (54 integración + 11 puras). También pasaron impuesto incluido, camas extra, Contact/Address, retiro de caja, variación de cambio y exportación numérica.

La matriz no sustituye los registros finales ni las capturas. Integraciones reales de canales, mensajería, pasarelas y cerraduras esperan proveedor/credenciales; HRMS es opcional. No se migró producción ni ningún sitio ajeno.
