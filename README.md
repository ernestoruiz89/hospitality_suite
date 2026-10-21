# Hospitality Suite

PMS nativo para modalidades Hotel, Por tiempo y Hotel y por tiempo. Recepción, caja, limpieza y gerencia trabajan desde once Pages de Desk en español; la contabilidad y el inventario permanecen en ERPNext.

Versión objetivo probada: **Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, MariaDB 10.11.14 y Node 24.18.0**, Ubuntu 24.04 / WSL2. App 0.8.2 en validación; última fase cerrada 0.8.1. Otras versiones no están acreditadas.

El desarrollo continúa: [matriz de requisitos](docs/REQUISITOS.md), [auditoría punto por punto](docs/AUDITORIA_ESPECIFICACION.md), [registro de avance](docs/AVANCE.md) y [arquitectura](docs/ARQUITECTURA.md). No se declara listo para producción mientras existan pendientes obligatorios.

[Caja y contabilidad](docs/AUDITORIA_CAJA_CONTABILIDAD.md): conciliación por estancia/turno, cuentas grupales completas y filtros más compactos. 294 pruebas nativas y 80 JS aprobadas. Resultados de esa fase en su auditoría. El PDF habitual de cuenta mantiene la [presentación resumida](docs/CUENTA_RESUMIDA.md).

[Limpieza y mantenimiento](docs/AUDITORIA_LIMPIEZA_MANTENIMIENTO.md): bloqueo hasta reapertura, inspección y correcciones explícitas. 307 nativas y 85 JS aprobadas. Matriz: 157 V, 14 I y 47 R; 61 entradas sin cierre.

[Permisos y aislamiento](docs/AUDITORIA_SEGURIDAD.md): contexto validado en servidor, JSON acotado y 19 comprobaciones HTTP. 319 nativas aprobadas. Estado de esa fase: **166 V, 15 I y 37 R; 52 entradas sin cierre**.

[Bitácora y cierres](docs/BITACORA_Y_CIERRES.md): cambios legibles, valores históricos y resumen por ejecución. **329 nativas y 95 JS aprobadas**. Estado de esa fase: **170 V, 14 I y 34 R; 48 entradas sin cierre**.

[Inventario y servicios](docs/AUDITORIA_INVENTARIO_SERVICIOS.md): entregas/devoluciones conciliadas, consultas por ubicación y acciones claras por estado. **337 nativas y 101 JS aprobadas**. Estado de esa fase: **179 V, 14 I y 25 R; 39 entradas sin cierre**.

[Aceptación y demostración](docs/ACEPTACION_Y_DEMOSTRACION.md): un usuario con roles explícitos de recepción/caja reserva, ingresa, entrega un consumo, extiende, cobra y registra salida desde Pages. Limpieza/Supervisión liberan; Contabilidad rastrea factura/pago y Gerencia contrasta C$ 3,030.00. Generador operativo repetible, con reservas y consumos ficticios en dos establecimientos. **373 nativas y 136 JS aprobadas** en esa fase. Estado de esa fase: **188 V, 8 I y 22 R; 30 entradas sin cierre**.

[Idioma y etiquetas](docs/IDIOMA_Y_ETIQUETAS.md): campos y enlaces en español, estados por contexto y catálogo con nombres claros. **379 nativas y 142 JS aprobadas** en 0.8.1. Estado al cerrar esa fase: **189 V, 7 I y 22 R; 29 entradas sin cierre**. Datos originales conservados, con Version de metadatos y caché nativa documentadas.

[Teclado y foco](docs/TECLADO_Y_FOCO.md) conserva la revisión en curso: **379 nativas y 162 JS aprobadas**, con aceptación visual actual pendiente. La [revisión de entregables](docs/ENTREGABLES_Y_REVISION.md) acredita los [diagramas completos](docs/MODELO_ESTADOS_Y_FLUJOS.md) y la matriz original: **191 V, 7 I y 20 R; 27 entradas sin cierre**. S04-17 permanece I.

[Historial de habitaciones](docs/HISTORIAL_HABITACIONES.md) conserva la fase 0.7.8: operaciones, cambios de datos y períodos por rango; valores plegados, paginación y permisos por establecimiento. **365 nativas y 136 JS aprobadas** en esa fase. Recepción comprueba cancelación, limpieza, cambio de habitación, bloqueos, tres páginas y móvil.

[Estados por intervalo](docs/ESTADOS_POR_INTERVALO.md) conserva la fase 0.7.7: contraste plegado de habitaciones para sus fechas, limpieza actual y llegadas/salidas con texto; calendario con contexto, validación e idioma. **352 nativas y 126 JS aprobadas** en esa fase, con catorce nativas dirigidas finales.

[Inicio y filtros de Recepción](docs/INICIO_Y_FILTROS.md) conserva la fase 0.7.6: llegadas/salidas accionables y preferencias por usuario/establecimiento, con 117 JS y nueve nativas dirigidas de esa fase.

[Fecha y pendientes del cierre](docs/FECHA_Y_PENDIENTES_CIERRE.md) conserva la fase 0.7.5: corte explícito, pendientes y acciones para resolver el cierre; su batería completa de 345 nativas se mantiene como evidencia anterior.

## Instalación en Bench

ERPNext debe estar instalado antes. La instalación normal no crea compañías, cuentas, impuestos, habitaciones ni datos de demostración. HRMS es opcional.

```sh
cd /ruta/al/bench
bench get-app hospitality_suite /ruta/al/repositorio/Hotel
bench --site hotel.localhost install-app hospitality_suite
bench --site hotel.localhost migrate
bench build --app hospitality_suite
bench --site hotel.localhost clear-cache
```

Se requieren Redis, MariaDB, worker, scheduler y Socket.IO de Frappe. Los PDF usan el motor wkhtmltopdf del entorno. No se modifica el núcleo.

## Sitio de WSL creado para esta tarea

Bench separado: `/home/frappe/benches/hospitality-bench`. Sitio operativo de demostración: [Recepción local](http://localhost:8086/app/hospitality-reception). Segundo sitio de instalación limpia: `hospitality-clean.localhost`.

Desde PowerShell:

```powershell
wsl -d Ubuntu-24.04 -u frappe -- python3 /mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/tools/run_dev.py
```

El script solo arranca el bench aislado, reutiliza puertos activos y deja PID/registros en `.hospitality-run`. Tras cambiar Python, ejecute el mismo comando con `--restart-web` y, si cambian hooks/jobs, `--restart-worker`; el servidor administrado usa `--noreload`. No es un despliegue de producción. Las credenciales se conservan únicamente en los archivos privados del bench/sitio descritos en `docs/AVANCE.md`; no están en Git.

PDF requiere wkhtmltopdf con Qt parcheado. En este bench, `tools/bootstrap_pdf_runtime.py` se ejecuta con `env/bin/python` de Frappe y extrae el paquete oficial dentro de `.runtime`, sin reemplazar el binario del sistema. Después reinicie web/worker mediante run_dev. Versión probada: 0.12.6.1; detalles y comandos en OPERACION.md.

`tools/bootstrap_wsl.py` documenta la creación inicial de la base y el sitio, rechaza bases existentes y permite otra base `hospitality_*` para un sitio `hospitality-*.localhost`. No reutilizarlo sobre sitios ajenos.

## Configuración y operación

Abra Configuración con un administrador de sistema o rol autorizado. Seleccione compañía, moneda y zona; cree categorías, habitaciones, tarifas, medios de pago y políticas. El asistente valida cuentas, almacenes y centro de costo antes de habilitar finanzas. Revise expresamente impuestos, identificación, crédito y formatos de factura para la instalación.

[Estancias](docs/ESTANCIAS_Y_LLEGADAS.md) separa alojados, llegadas, salidas y cuentas abiertas, con conteos y paginación. Recepción muestra la próxima llegada pendiente y abre la reserva existente; una reserva futura conserva su diferencia con la ocupación actual. La cabecera móvil y las fichas del tablero se compactan para mostrar antes datos y acciones.

Los formularios extensos se dividen en pestañas por tarea, con acción visible y adaptación móvil. Reserva/entrada revisa el precio antes de confirmar; caja distingue revisar/confirmar cobro, anticipo, garantía o devolución. [UX y evidencia de formularios](docs/UX_FORMULARIOS.md).

La política de [cargos por noche](docs/CARGOS_PERIODICOS.md) conserva importes aceptados, separa programados/generados y evita duplicados al repetir la auditoría. La actualización mantiene Al ingresar para datos existentes. [Facturar cuenta](docs/FACTURACION_DESDE_PAGES.md) permite revisar y emitir una factura, incluido importe cero, conservando la estancia activa y sin registrar un cobro.

El usuario necesita roles HS y un registro HS Access por establecimiento/compañía. El asistente concede únicamente roles HS; la administración de cuentas de acceso y los roles ERPNext adicionales siguen los mecanismos estándar de Frappe. Un recepcionista que también cobra puede combinar HS Receptionist y HS Cashier.

[Reservas y precio histórico](docs/EXPLICACION_TARIFA_HISTORICA.md): la cuenta explica la tarifa aceptada, Ver reserva muestra un resumen completo y las habitaciones disponibles abren la reserva con datos preseleccionados. Los nuevos documentos usan [series legibles](docs/SERIES_DOCUMENTALES.md), conservando los identificadores anteriores.

La [gestión de huéspedes](docs/GESTION_HUESPEDES.md) permite corregir la misma ficha con motivo, prioriza la identificación según la política y conserva los documentos estándar y referencias existentes.

El [contador de recepción](docs/CONTADOR_Y_RELOJ.md) conserva el vencimiento al recargar y al cambiar el reloj del equipo; es orientativo y no modifica los cargos.

La [caducidad de retenciones](docs/TRABAJOS_Y_REINTENTOS.md) limita los reintentos transitorios del worker, conserva el rollback y registra los fallos con recuperación estándar.

El [PDF de cuenta resumido](docs/CUENTA_RESUMIDA.md) presenta cargos, movimientos y saldo, omitiendo fórmulas y secciones vacías; el cálculo histórico se consulta en pantalla.

Consulte el [manual por rol](docs/MANUAL.md), [tratamiento contable](docs/CONTABILIDAD.md) y [operación técnica](docs/OPERACION.md) y [contratos API](docs/API.md).

## Demostración explícita

Solo en un sitio de pruebas, habilite `hospitality_allow_demo` y ejecute:

```sh
bench --site hotel.localhost set-config allow_tests true
bench --site hotel.localhost set-config hospitality_allow_demo true
bench --site hotel.localhost execute hospitality_suite.demo.seed
bench --site hotel.localhost execute hospitality_suite.demo_scenario.build
```

Crea datos ficticios: Hotel y Por tiempo con diez habitaciones cada uno, huéspedes, precios, existencias de muestra y usuarios por rol. El escenario operativo deja una reserva futura, una estancia y un consumo entregado por establecimiento; usa movimientos nativos de stock y no hace cobros. Repetir conserva las referencias y el trabajo posterior. Requiere los establecimientos ficticios originales y rechaza reservas, estancias, cargos, caja o consumos ajenos al primer recorrido. Las contraseñas aleatorias quedan en `sites/<sitio>/private/hospitality-demo-users.json`, modo 600. Ambas cargas son explícitas y están separadas de la instalación normal. Use un sitio distinto y vacío para la batería; vea [aceptación y límites](docs/ACEPTACION_Y_DEMOSTRACION.md).

## Construcción, migración y pruebas

Los JSON nativos están versionados. Si se cambia `schema.py` o una plantilla de impresión:

```sh
python3 tools/generate_schema.py
cd /ruta/al/bench
bench --site hotel.localhost migrate
bench build --app hospitality_suite
```

La batería requiere un sitio desechable identificado como pruebas y `allow_tests`. Para generar JUnit, instale la dependencia opcional con `bench pip install -e "apps/hospitality_suite[test]"`:

```sh
bench --site hospitality-acceptance.localhost set-config allow_tests true
bench --site hospitality-acceptance.localhost set-config hospitality_integration_test_site true
bench --site hospitality-acceptance.localhost run-tests --app hospitality_suite
```

`before_tests` exige Redis disponible y un sitio designado sin operaciones; después carga solo la base de prueba. Cada caso revierte sus movimientos. El ejemplo usa el sitio de aceptación instalado en WSL; en otro entorno cree e instale primero un sitio desechable equivalente. Conserve un respaldo inicial para recuperar una ejecución interrumpida. Última batería conjunta: **379 aprobadas** en hospitality-acceptance.localhost, 365 de integración y 14 puras, sobre 0.8.2. Las seis de idioma cubren alias, metadatos, contextos y extracción; IDIOMA_Y_ETIQUETAS.md delimita aquella revisión. TECLADO_Y_FOCO.md conserva el orden de ejecución de esta fase y su aceptación pendiente. Las ocho de 0.8.0 y ACEPTACION_Y_DEMOSTRACION.md conservan la aceptación operativa de Pages. Se conservan los seis escenarios adicionales con el worker real de TRABAJOS_Y_REINTENTOS.md como evidencia de esa fase.

La fase histórica 0.7.1 acredita **307 pruebas nativas y 85 JS**, con trece casos nuevos de limpieza, bloqueos y contexto de establecimiento. La matriz registra 157 V, 14 I, 0 P y 47 R; cada entrada conserva su evidencia y límites. Las auditorías anteriores mantienen los recorridos históricos. El sitio limpio anterior conserva respaldo de diagnóstico, y la demostración principal conserva operaciones UX: ninguno sustituye el sitio de aceptación. Los dos casos de concurrencia usan conexiones y commits reales; se ejecutan aparte sobre aceptación con respaldo y restauración posterior:

```sh
bench --site hospitality-acceptance.localhost execute hospitality_suite.tests.concurrency.verify
bench --site hospitality-acceptance.localhost execute hospitality_suite.tests.concurrency.verify_category
```

Las pruebas JS sin servidor cubren transporte, edición numérica, catálogo, traducción/presentación, políticas, cierre, servicios, POS, devoluciones, notas de crédito, formularios, foco/teclado, historial y portal: **160 de Desk y dos del portal**. Ejecute las 162 con:

```sh
node tools/run_ui_tests.cjs
```

Los ensayos reales de sesiones, corte y respuesta perdida se describen en docs/OPERACION.md. Los recorridos de navegador se documentan por separado en la matriz y la evidencia.

Los helpers de concurrencia están limitados al sitio sintético y conservan anulaciones auditadas. No son pruebas que deban ejecutarse contra clientes reales.

`tools/qa_exports.py` genera las impresiones y exportaciones reales del recorrido ficticio. `qa_pdf.py` y `qa_workbook.mjs` las inspeccionan sin modificar su contenido; requieren las dependencias de QA. La evidencia está en `docs/evidence/` y los archivos de revisión locales en `output/`.

## Alcance y límites actuales

El núcleo incluye disponibilidad serializada, snapshots tarifarios, grupos, folios, facturación, anticipos/garantías reales, caja, servicios/stock y limpieza. Las Pages permiten órdenes/recepciones/facturas de compra, pago a proveedor, egresos documentados, clasificación/mínimos, traslados/consumos/conteos y liquidación bancaria con comisiones/retenciones. Se verificaron circuitos de motel y hotel, y compra/pago/liquidación desde las Pages con datos ficticios.

La retención de identificaciones y evidencias requiere revisión de gerencia y una política por establecimiento; los archivos se eliminan mediante outbox después del commit. Su alcance y recuperación están en docs/OPERACION.md.

La matriz distingue lo implementado de lo probado y lo pendiente. Mantenimiento, planes incluidos, portal Guest, grupos, consumos y existencias móviles ya tienen recorridos de navegador. Continúan la aceptación integral por roles y formularios secundarios, el contraste restante y la recuperación final de despliegue. Pasarelas, canales, mensajería y cerraduras solo tienen contratos; no hay proveedor real configurado ni pagos simulados como liquidados.
