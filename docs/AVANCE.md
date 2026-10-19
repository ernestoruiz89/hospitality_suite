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

## Próximo cierre de trabajo

- Terminar mantenimiento con repuestos/costos/evidencias y servicios incluidos; ampliar seguridad de segunda compañía/maestros.
- Verificar Socket.IO entre sesiones, corte/reconexión y fallo/recuperación de trabajo programado; comprobar expiración real.
- Impresiones y exportaciones ya revisadas: diez PDF de una página, incluido cierre/factura/cuenta detallada, y XLSX numérico sin recortes. Falta ampliar casos de volumen/grupo/multimoneda.
- Probar asistente, portal, gerencia, venta directa y flujos hotel/grupo en navegador, además de vista móvil si el control disponible lo permite.
- Manuales, contabilidad y operación escritos. Faltan ensayos de respaldo/restauración/reversión y repetición final de concurrencia.
- Actualizar matriz con estados granulares; no confundir implementación o prueba de backend con Page verificada.
