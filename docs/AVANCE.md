# Registro de implementación

Actualización: 2026-10-19. Objetivo activo; el alcance obligatorio aún tiene verificaciones y componentes pendientes en REQUISITOS.md. No se declara aptitud para producción.

## Entorno aislado

- Repositorio inicialmente vacío, rama codex/hospitality-suite. Primer commit fd352d2.
- Bench: /home/frappe/benches/hospitality-bench. App enlazada al repositorio Windows. No se modifica el núcleo ni se migran sitios ajenos.
- Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, MariaDB 10.11.14, Node 24.18.0.
- hospitality.localhost en http://localhost:8086/app/hospitality-reception; sitio adicional hospitality-clean.localhost instalado desde cero con la versión ampliada.
- Redis separados 13001/11001; Socket.IO 9001; worker y scheduler activos. Se verificaron trabajos expire_property terminados por el worker.
- tools/run_dev.py arranca los procesos del bench de pruebas de forma repetible y guarda PID/registros en .hospitality-run. El servidor web quedó independiente de la sesión de herramientas; --restart-web se verificó y /login responde HTTP 200. Tras editar Python debe reiniciarse ese servidor (--noreload). tools/bootstrap_wsl.py admite otro sitio hospitality-*.localhost sin reutilizar bases existentes.
- Claves Administrator en .hospitality-setup.json y .hospitality-clean-setup.json, dentro del bench, con modo 600. Usuarios ficticios y sus claves solo en private/hospitality-demo-users.json del sitio. No copiar secretos a Git.

## Implementación alcanzada

26 DocTypes nativos HS, once Pages, sidebar propia y assets esbuild. Reservas, grupos, retenciones, modificaciones cotizadas, entrada, segmentos, extensiones, cambios tarifarios, folios compartidos o separados, salida, limpieza, inspección, mantenimiento, consumos y stock estándar.

Contabilidad mediante Sales Invoice, Payment Entry y Journal Entry: anticipos reales, conciliación antes/después de facturar, garantías separadas, devoluciones, notas de crédito, turno y arqueo, vuelto y multimoneda. Venta directa con factura, cobro y una salida de stock; devolución completa estándar. No se escribe GL Entry, Payment Ledger Entry ni Stock Ledger Entry directamente.

Configuración por establecimiento, pagadores/crédito, políticas, temporadas, tarifas negociadas, camas extra, usuarios/roles, selección de series y formatos. Customer/Contact/Address estándar para registro de huésped y tabla de acompañantes validada.

Cierre diario, reportes operativos/KPI, conciliación hasta documentos, exportadores XLSX/PDF, nueve formatos de impresión. Portal opcional desactivado con cupo compartido, retención/caducidad y firma. Proveedores externos siguen sin configurar; las simulaciones nunca liquidan pagos.

## Pruebas ejecutadas

- Batería en instalación adicional limpia: 65 aprobadas (54 integración + 11 puras), con before_tests y demo explícita reproducible. La instalación limpia detectó opcionales numéricos None y se corrigió su validación/default.
- Ampliación financiera: 17 pruebas financieras aprobadas, incluidas factura y pago creados directamente con controladores ERPNext, sus cancelaciones y notificaciones por usuario.
- La batería conjunta incluye horas reales de motel, bloqueo de mantenimiento, retorno USD con diferencia de cambio, retiro idempotente, pagos combinados NIO/USD y rechazo de anticipo tras salida.
- Concurrencia real bajo REPEATABLE-READ: exactamente una confirmación para habitación vacía y para último cupo de categoría. La primera ejecución descubrió snapshot obsoleto; se corrigió con lecturas actuales FOR UPDATE después de bloquear establecimiento e idempotencia.
- Migaciones versionadas conservaron la reserva previa y reconstruyeron sus líneas/snapshots sin alterar importes contables.
- Cortesías y descuentos se representan en líneas estándar, conservando referencias a cargos/ajustes. No se activa silenciosamente permitir tarifas negativas en Selling Settings. Cortesía ocupa con ingreso cero; prueba de impuesto incluido confirma neto para ADR.

## Evidencia de Pages

Reserva kh48obir08, estancia agp2lri219, habitación M101, todos ficticios:

1. Reserva y entrada desde Page, alojamiento C$450.
2. Agua entregada desde Consumos: inventario 100 → 99, cargo C$30.
3. Extensión cotizada por una hora: adicional C$150; saldo C$630.
4. Usuario cashier registra C$630, recibido C$700, vuelto C$70. Payment Entry ACC-PAY-2026-00001 y factura ACC-SINV-2026-00001.
5. Arqueo 63 unidades de C$10, cierre sin diferencia.
6. Usuario receptionist registra salida con saldo cero; M101 queda sucia y se genera tarea.
7. Usuario housekeeping inicia, completa cuatro puntos y solicita inspección.
8. Usuario supervisor inspecciona y libera; cero pendientes.

Capturas 01 a 06 en docs/evidence. Se eliminaron las dos barras de navegación simultáneas usando hide_sidebar de Page en Frappe 16. La captura 06 acredita M101 nuevamente limpia. Se detectaron detalles de presentación (símbolo de moneda en denominaciones, botón de inspección visible a limpieza, etiquetas técnicas) y se corrigieron en los assets actuales.

## Ampliación: operación, recuperación y móvil

La última batería conjunta tiene **79 aprobadas** (68 integración + 11 puras). Hay 28 DocTypes y once Pages. Se probaron facturas externas con todos los ajustes, rechazo de cargos revertidos, conciliación inversa, medio histórico inmutable y precisión monetaria 0/3.

Mantenimiento incluye responsable validado, repuestos con Stock Entry, costo derivado, devolución autorizada, evidencias privadas y resolución de novedades/objetos. Pasaron cuatro pruebas; limpieza no recibe los costos de impresión. Se probaron envío, recepción y pérdida de ropa con stock real. La Page registró un repuesto para M102, costo C$10. La impresión actual se generó y revisó en una página. Faltan equipo y reposición.

Servicios incluidos conservan cantidades aceptadas, reservan cupo desde solicitud, entregan sin otro cargo y con stock único. Cancelación/devolución restituyen cupo; extensión añade beneficios por noche y cambio de habitación no duplica. Pasaron tres pruebas; la configuración/entrega incluida en navegador queda pendiente.

Se creó otra compañía en la prueba y se combinaron HS Receptionist, Stock User, Accounts User y Sales User. Se rechazaron compañía/establecimiento ajenos, Bin/almacenes no asignados, Stock Entry cruzado y RPC de stock/saldo global. Los usuarios ajenos a HS mantienen controles estándar.

worker_recovery ejecutó un job RQ que expiró una retención y falló: rollback conservó retención/asignación. El job productivo siguiente terminó y liberó cupo. La reapertura del último día exige autorización/motivo y conserva el cierre anterior.

Circuito hotel en Pages: reserva s9tit5ss4j, estancia sa48191j91, H101; dos noches C$3,000, agua C$60; anticipo C$500 y pago C$2,560, factura ACC-SINV-2026-00002, pagos ACC-PAY-2026-00002/00003. Salida con saldo cero, arqueo C$3,060 cerrado y limpieza/inspección móvil terminadas. Se corrigió una captura anterior al cambio de fila sincronizando controles numéricos antes de leer/enviar el diálogo; el cierre se repitió con el conteo recién escrito y sin diferencia.

Panel lateral verificado 1024×768 y 390×844. Tablas como fichas y conexión visible en móvil. El contador bajó 47 h 59 min → 47 h 58 min sin cambiar referencia del servidor ni recargar (countdown.json). Capturas 07 a 12.

Respaldo Bench con archivos restaurado en **hospitality-restore.localhost**, DB hospitality_restore, conservando conexión/identidad del destino y clave de cifrado del origen. Antes/después de migrate: **52 tablas, 295 filas idénticas**, SHA-256 3126e6dacf105ff2ec0b3982e4f852f9affd5e5070f8e8d5e1a7d0425bdebe50. Scheduler del destino pausado. El respaldo contiene el hotel aún activo antes de la salida posterior del sitio principal. Referencia completa privada en el bench; resultados sin credenciales en evidence. Pendientes actuales en PENDIENTES.md.

## Ampliación: tesorería y abastecimiento

31 DocTypes y once Pages. Batería conjunta: **91 aprobadas** (80 integración + 11 puras). Egresos documentados y pagos a proveedores reducen el efectivo esperado; cuentas y documentos son nativos. Liquidación de tarjeta conserva el bruto, snapshot, parciales, comisión, retención, neto e histórico de cambio; admite liquidación de devolución de salida. Se verificaron redondeo final, cancelaciones, prohibición de anular origen con dependientes y USD sin residuo en compensación.

Compras usan Purchase Order → Purchase Receipt parcial → Purchase Invoice sin update_stock → Payment Entry. Almacenes/proveedores asignados, clasificación de artículos, mínimos Item Reorder, traslados/reposición, limpieza/merma y Stock Reconciliation con conteo vigente. Reporte de movimientos proyecta Stock Ledger Entry con cantidad, valor, centro de costo y documento de origen. No hay libro paralelo. Los roles HS combinados con Accounts User no permiten a limpieza ver Customer/Contact/Address ni sus archivos; las notificaciones de esos maestros también se limitan por usuario.

En Page, supervisor abrió C$500, egresó C$20 (ACC-JV-2026-00001), compró dos sábanas × C$50 (PUR-ORD-2026-00001, MAT-PRE-2026-00001, ACC-PINV-2026-00001) y pagó C$100 (ACC-PAY-2026-00004). Venta directa de agua C$30 por tarjeta (ACC-PAY-2026-00005), stock 96→95; liquidación ACC-JV-2026-00002: gasto C$2.90, retención C$0.30, banco C$26.80, compensación cero. Turno 3ri45vs2lc cerrado con C$380 y diferencia cero. Evidencia 13/14 y finance-stock.json; todo es sintético/local.

Se corrigió el diálogo genérico de Frappe 16: sincroniza controles numéricos y valida una sola vez antes de enviar. El doble get_values refrescaba un requerido cuyo modelo todavía estaba vacío y perdía el valor recién escrito. Se verificó guardado inmediato y arqueo recién editado. El objetivo sigue activo con pendientes explícitos, sin afirmar aptitud para producción.

## Ampliación: equipos, evidencia y conexión

32 DocTypes y once Pages; última batería **95 aprobadas** (84 integración + 11 puras). HS Equipment conserva ubicación e identificación operativa, con Asset estándar opcional asignado a la misma compañía/establecimiento. Su vínculo es único y no se cambia tras registrar mantenimiento. Las órdenes por equipo no se solapan; una orden sin habitación no crea Allocation. El bloqueo de una habitación sigue rechazando reservas conflictivas y no las cancela. Se probaron Asset nativo, duplicados, alcance, cambio de ubicación con órdenes pendientes y proyección mínima del técnico.

Circuito de Page: equipo hfj7aq41pd (BOMBA-UI-001), orden hr3a78j3od sin habitación, responsable maintenance, evidencia privada 4166ba4f19 y finalización autorizada por supervisor. Objeto jpjjmvvhon resuelto con constancia. El archivo privado se abrió en la sesión de supervisión; verificación backend permite supervisor/mantenimiento y deniega limpieza. Impresión de equipo revisada en una página y vista 390×844 guardada, capturas 15/16 y equipment.json.

Los archivos conservan el control nativo de propietario/documento, más restricciones por rol/establecimiento también en listados. Se probó permitir a los roles correctos y denegar archivos financieros al propietario con limpieza + Accounts User, además de Payment Entry/GL y maestros personales. La primera implementación devolvía None al no denegar: Frappe 16 lo interpreta como denegación; se corrigió a True y se añadieron casos positivos y listados. La evidencia de mantenimiento usa nivel de permiso separado del acceso operativo de limpieza.

Se detectó que el arranque directo omitía DEV_SERVER, por lo que Desk consultaba Socket.IO sobre web 8086 esperando un proxy. run_dev.py ahora establece esa variable para web. Page comprobada con `window.dev_server=1`, Socket.IO 9001, indicador conectado y sin errores de consola tras recarga. El indicador deriva del socket real; Actualizar también reintenta conexión. Falta todavía el ensayo entre sesiones, corte y respuesta perdida. El objetivo permanece activo.
