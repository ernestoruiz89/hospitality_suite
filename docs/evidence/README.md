# Evidencia de pruebas

Índice acumulado de evidencia histórica y actual. Versión de aplicación vigente: 0.6.2; Frappe 16.52.0 y ERPNext 16.51.1, en un bench separado de WSL Ubuntu 24.04. Sitios ficticios: hospitality.localhost, hospitality-clean.localhost, hospitality-restore.localhost y hospitality-acceptance.localhost. No hay datos ni operaciones de producción.

La batería vigente está en board-native-tests.log/xml: **229 aprobadas** (215 integración y catorce puras), y board-js-tests.log: **45 regresiones JavaScript** (43 Desk y dos portal). ESTANCIAS_Y_LLEGADAS.md delimita el nuevo recorrido con recepcionista y sus fixtures. Los resultados menores que siguen pertenecen a fases anteriores; no representan otra ejecución ni recorridos adicionales.

## Automatizadas

- `tests-clean.log`: batería histórica de 0.2.0, **103 aprobadas**: 92 integración y 11 puras.
- `tests-clean.xml`: JUnit normalizado para CI, sin fallos ni errores. `tests-clean.raw.txt` conserva la salida original; Frappe 16 concatena un documento XML por cohorte. `tools/normalize_junit.py` los combina sin alterar casos/resultados.
- `concurrency.log` y `category-race.log`: dos conexiones reales por caso, exactamente una confirmación y un rechazo, bajo REPEATABLE-READ; anulaciones de limpieza auditadas.
- Los escenarios, fuentes y limitaciones están descritos en `../REQUISITOS.md` y `../AVANCE.md`.

## Circuito de Pages

1. `01-recepcion-entrada.png`: reserva y entrada de M101.
2. `02-caja-cobro-vuelto.png`: cajero confirma C$630, recibido C$700 y vuelto C$70, con comprobante.
3. `03-caja-turno-cerrado.png`: arqueo C$630 y turno cerrado.
4. `04-recepcion-salida-sucia.png`: recepcionista registra salida; M101 queda sucia.
5. `05-limpieza-inspeccion.png`: responsable de limpieza completa checklist y solicita inspección. Captura anterior a ocultar el botón de inspección al rol de limpieza; el servidor ya rechazaba la autoaprobación.
6. `06-recepcion-limpia.png`: supervisor libera y M101 vuelve a quedar limpia.

La reserva es kh48obir08 y la estancia agp2lri219, ambas sintéticas. El consumo de agua redujo existencias de 100 a 99; la extensión agregó C$150 al alojamiento C$450 y consumo C$30. Factura ACC-SINV-2026-00001 y Payment Entry ACC-PAY-2026-00001.

Las capturas 01 a 06 prueban escritorio. La ampliación 07 a 12 prueba mantenimiento móvil, panel de hotel en tableta/móvil, cuenta saldada, arqueo cerrado y limpieza/inspección móvil. No acredita fallo de red, portal ni grupo.

7. `07-maintenance-mobile.png`: orden con responsable y repuesto, vista adaptada.
8. `08-hotel-tablet-panel.png`: panel lateral 1024×768.
9. `09-hotel-mobile-panel.png`: panel lateral 390×844, acciones y cuenta legibles.
10. `10-hotel-settled.png`: alojamiento C$3,000 + consumo C$60, factura y saldo cero.
11. `11-hotel-cashier-closed.png`: turno C$3,060 cerrado; anticipo C$500 y pago C$2,560.
12. `12-hotel-housekeeping-mobile.png`: limpieza/inspección terminadas, cero pendientes.
13. `13-caja-egresos-liquidacion.png`: egreso C$20, proveedor C$100, cobro de tarjeta C$30 y liquidación separada C$2.90 comisión/C$0.30 retención/C$26.80 banco; esperado C$380.
14. `14-caja-compra-cerrada.png`: turno cerrado con C$380 contados y sin diferencia. `finance-stock.json` verifica los documentos nativos, dos sábanas recibidas, factura sin segundo stock y saldada, compensación cero y conciliación sin diferencias.
15. `15-equipo-evidencia-resolucion.png`: equipo sin habitación, orden completada por supervisión, evidencia privada y objeto resuelto con constancia; conexión real visible.
16. `16-equipo-mobile.png`: vista de mantenimiento a 390×844 con fichas y estado de tiempo real. `equipment.json` acredita cero asignaciones de habitación, archivo/hash, roles permitidos/denegado y resolución. Su PDF se generó y revisó visualmente en una página (472 caracteres).

`countdown.json` acredita descenso con la misma referencia del servidor. `worker-recovery.json` conserva fallo/rollback y recuperación. `restore-baseline-summary.json`, `restore-verify.json` y `restore-after-migrate.json` conservan cantidades/hash; no contienen credenciales ni volcado. Referencia y respaldos completos permanecen privados en WSL.

## Impresiones y exportación

`exports-manifest.json` conserva origen, formato, tamaño y SHA-256 de los archivos locales generados por los controladores instalados. `pdf-qa.json` acredita diez PDF legibles de una página cada uno. Se inspeccionaron visualmente sus PNG: reserva, registro, cuenta, recibo, arqueo, limpieza, mantenimiento, cierre diario, factura y conciliación.

La cuenta muestra cargos, facturas/impuestos, cobros/garantías y saldo; el arqueo incluye denominaciones. La factura HS Factura usa valores estándar y oculta referencias técnicas. No se acredita cumplimiento fiscal particular por el solo formato de demostración.

`workbook-qa.log` contiene la importación de solo lectura y los valores de la conciliación XLSX: importes numéricos, moneda NIO y diferencias cero. También se revisó su imagen sin texto cortado. Los archivos PDF/XLSX e imágenes de revisión están en `output/`, excluido de Git; los scripts QA permiten reproducirlos después de completar un recorrido ficticio.

`finance-stock-pdf-qa.json` acredita seis PDF adicionales legibles: liquidación, egreso, arqueo y reportes de liquidaciones/egresos/movimientos nativos. Se revisaron sus renderizados; `qa_finance_workbook.mjs` verificó C$30/C$2.90/C$0.30/C$26.80 como celdas numéricas y renderizó su vista sin modificar el XLSX. Los movimientos antiguos sin clasificación explícita se muestran como tales; no se infiere que fueron traslados.

El núcleo de Frappe/ERPNext se comprobó sin cambios. Los pendientes obligatorios continúan en `../PENDIENTES.md`; esta evidencia no declara aptitud para producción.

17. `17-retencion-revision.png`: alcance revisado, tres campos de identificación, dos referencias privadas, motivo previo y confirmación explícita sin valores sensibles. No se pulsó el borrado final desde el navegador.
18. `18-retencion-completada.png`: ejecución completada, dos referencias eliminadas y cero pendientes/fallidos. `privacy-worker.json` acredita aprobación del fixture desechable mediante helper, job RQ real terminado, bytes presentes antes del commit y ausentes después, outbox limpio y ledgers sin cambios.

19. `19-respuesta-perdida.png`: aviso de resultado incierto; confirmación y referencia UX-NET-001 conservadas.
20. `20-reintento-confirmado.png`: mismo resultado, factura ACC-SINV-2026-00004 después del reintento. network-sale-sale.json prueba factura/pago/stock únicos y cantidades nativas.
21. `21-venta-devuelta.png`: venta devuelta y stock restituido, nota/pago estándar en network-sale-returned.json; turno cerrado en cero. El aviso informativo estándar de ERPNext se cerró después de verificar los documentos.
22. `22-tiempo-real-interrumpido.png`: servidor Socket.IO aislado detenido realmente; indicador Sin tiempo real.
23. `23-tiempo-real-recuperado.png`: servidor reiniciado y Actualizar reconecta/refresca. `transport-sessions.json` prueba además tres sesiones autenticadas, aislamiento, commit/rollback y recuperación de cambio perdido. `desk-transport-tests.log`: cinco pruebas JavaScript aprobadas (tres de transporte y dos de tablas/grupos).

24. `24-grupo-modificacion.png`: dos solicitudes por asignar, ocupantes 2/1 y nueva cotización C$6000.
25. `25-grupo-asignacion.png`: segunda solicitud identificada, H2/H103 y única acción de entrada pendiente.
26. `26-grupo-acompanante.png`: acompañante H3 persistido y reabierto, dentro de dos plazas aceptadas.
27. `27-grupo-cuenta-compartida.png`: alojamiento consolidado C$6000 en empresa, cuenta personal separada.
28. `28-grupo-caja-cerrada.png`: turno del grupo cerrado C$6030.
29. `29-grupo-saldos-cero.png`: cuentas empresarial y personal saldadas y facturas de origen.
30. `30-grupo-salidas-escritorio.png`: ambas salidas registradas a 1280×900; se restauró el viewport habitual.

`group-reserved/modified/stays/companions/billed/checked-out.json` son puntos de control de solo lectura del mismo recorrido. Acreditan asignaciones sin habitación, conservación 2/1, dos entradas, acompañante, una factura Company de dos alojamientos C$6000, factura personal C$30, pagos estándar y stock único. El último incluye cierre contado/esperado C$6030, diferencia cero, reserva Completed, ambas salidas y dos tareas de limpieza pendientes. No declara que esas tareas nuevas ya estén inspeccionadas.

31. `31-configuracion-documentos.png`: series y formatos guardados/reabiertos.
32. `32-plan-incluido-configuracion.png`: tarifa por fecha/prioridad con agua incluida.
33. `33-plan-cotizacion.png`: C$1600 y una unidad por estancia.
34. `34-plan-cupo-rechazado.png`: segunda unidad rechazada, sin reintento de red sugerido.
35. `35-extension-conflictiva-rechazada.png`: conflicto con reserva posterior.
36. `36-plan-cambio-extension.png`: H105, salida 21/10 09:30 y C$3100. plan-*.json acredita segmentos contiguos, dos cargos y stock/beneficio únicos; fixture sigue abierto sin cobrar.
37. `37-portal-solicitud-visitante.png`: confirmación firmada con vencimiento; la solicitud se creó como Guest antes del nuevo inicio de sesión de gerencia.
38. `38-portal-convertido.png`: conversión manual. portal-converted.json acredita owner Guest, reserva Web, una asignación activa y ningún pago.
39. `39-configuracion-acceso-denegado.png`: recepción no puede abrir la Page de configuración.
40. `40-configuracion-roles.png`: formulario administrativo con nueve roles en español; no se concedieron nuevos accesos desde el navegador.

portal-ui-tests.log contiene dos pruebas aprobadas; desk-transport-tests.log contiene seis. La prueba nativa del portal ahora renderiza la ruta real de confirmación y valida vencimiento y ausencia del correo del visitante.

41. `41-inventario-revision-conteo.png`: conteo 1 frente a existencia 2 y valoración C$10 revisados antes de confirmar.
42. `42-inventario-conteo-confirmado.png`: ubicación de lavandería con una unidad de agua después del ajuste.
43. `43-lavanderia-mobile.png`: formulario completo a 390×844, con etiquetas y Guardar accesible.
44. `44-lavanderia-resultados-mobile.png`: resultado de pérdida/recepción sin información de huéspedes o importes. Los movimientos se enviaron con rol limpieza en la vista habitual y se revisaron junto con el formulario a 390×844.

inventory-ui.json acredita traslado MAT-STE-2026-00010, conteo MAT-RECO-2026-00001 con dos GL Entry y tres movimientos de ropa: 00011/00012/00013. Agua 91 en origen/1 en lavandería; sábana 1 en origen/0 en lavandería, envío 2/recepción 1/pérdida 1. No se escribió directamente en los libros.

La batería final registra 107 aprobadas, 94 integración y 13 puras. Incluye corte operativo configurable que recorta horas de motel, snapshot del cierre, límites inválidos rechazados, DST de 23/25 horas y webhook sintético firmado/repetido una vez, con campos redactados y ningún efecto financiero. Desk tiene siete pruebas aprobadas; portal conserva dos. concurrency-final.json acredita una confirmación y un rechazo en ambas carreras reales.

45. `45-restauracion-recepcion.png`: recepción de la copia con estado de habitaciones conservado; se abrió H105 y se comprobaron C$1600 + C$1500 y saldo C$3100.
46. `46-restauracion-gerencia-corte.png`: período 19/10 06:00→20/10 06:00 y KPI conservados.

recovery-final-baseline/restored/migrated/reversed/redeployed/ui/source.json conservan el mismo hash agregado, 70 tablas, 866 filas y un archivo privado. recovery-code-previous/current.json registra las revisiones y migraciones de la copia. recovery-backup-manifest.json guarda tamaños/hash de cuatro componentes, sin archivos ni secretos. El servidor temporal 8088 se detuvo; solo se acreditan lectura/API en esa copia, mientras Socket.IO se probó en el servicio principal. El objetivo conserva pendientes de dimensiones e historial documentados.

47. `47-auditoria-segunda-pagina.png`: 51–100 de 142 registros, foco/posición regresan al encabezado al avanzar.
48. `48-historial-acompanante.png`: H3 como principal de H105 y acompañante de H102, con dos visitas recuperadas desde el servidor.

history-ui.json conserva páginas sin duplicados, 142 filas en XLSX y los 142 identificadores extraídos del PDF. El PDF tiene diez páginas: se revisaron primera y última, y se detectó corte de fila/ausencia de encabezado repetido que continúa pendiente en PENDIENTES.md. No se declara esa revisión visual aprobada. La batería actual suma 111 aprobadas; las cuatro nuevas prueban 1105 eventos, 610 asignaciones, acompañantes/alcance y mantenimiento histórico.

49. `49-pdf-encabezados-paginacion.png`: PDF corregido con Qt parcheado, tabla contenida y pie 1/18.
50. `50-pdf-ultima-pagina.png`: encabezado repetido, última fila completa y pie 18/18.

La revisión anterior de diez páginas fue sustituida por un PDF de 18 páginas, todas renderizadas y revisadas. history-pdf-qa.json fija su hash y revisión; history-ui.json verifica 142 registros y encabezados de todas las páginas por función/HTTP 200. pdf-runtime.json fija versión/paquete/binario aislado. patched-native-exports-manifest.json conserva la nueva generación de diez comprobantes, todos revisados. Batería actual: 112 aprobadas; queda dimensión/fechas de informes, sin declarar completo el objetivo.

51. `51-produccion-por-habitacion.png`: producción agrupada por habitación y moneda, sin duplicar venta/devuelta.
52. `52-filtros-disponibilidad-movil.png`: filtros de intervalo y habitación en móvil.
53. `53-disponibilidad-movil.png`: H104 no disponible en el intervalo reservado, cupo simultáneo 8 y limpieza actual por separado, a 390×844.
54. `54-produccion-legible.png`: Page con nombres de servicios, habitación, cantidad, moneda, estado e ingreso neto; diez registros en la vista operativa.
55. `55-produccion-pdf-legible.png`: PDF operativo con los diez registros en una página, sin hashes ni códigos de catálogo HS-DEMO.
56. `56-reservas-nombres-fechas.png`: listado de reservas con huésped y fecha; los comandos conservan las claves originales.

`report-dimensions.json` acredita filtros locales, atribución de alojamiento H104 C$1600/extensión H105 C$1500, venta/devuelta una vez, disponibilidad compartida con el motor de reservas, llegadas por canal Web y cuentas con saldo positivo. Cinco exportaciones PDF/XLSX verificadas por HTTP 200. La versión técnica conserva todas las referencias en cada sección; la operativa las oculta. Las diez páginas de esos cinco PDF se renderizaron y revisaron; `readability-pdf-qa.json` fija los hashes y páginas. Los archivos se conservan en `output/report-dimensions/` y las capturas 54/55 permiten revisar el resultado sin abrir el sitio.

`readability-native-tests.log/xml`: 122 aprobadas, 109 integración + 13 puras, cero fallos/errores. `readability-js-tests.log`: nueve pruebas Desk y dos portal. `readability-race-room/category.json`: una confirmación y un rechazo en cada carrera real bajo REPEATABLE READ, después de compartir el motor con disponibilidad. Las reservas de carrera se cancelaron con auditoría. El checkpoint de recuperación anterior sigue siendo evidencia histórica; deberá repetirse con la revisión final. Continúan la auditoría de todos los puntos de la especificación y los orígenes contables de los reportes mínimos.

57. `57-productividad-limpieza.png`: dos grupos por responsable, pendientes/finalizadas y duración/tareas por hora registrada; todos los datos son ficticios y los tiempos de demostración no representan productividad laboral real.
58. `58-arqueos-por-moneda.png`: cuatro arqueos históricos con responsable legible, fechas, moneda, esperado/contado y diferencia, conservando el cierre.
59. `59-cancelaciones-fecha-real.png`: H101, retención vencida el 19/10 frente a llegada prevista 08/12, motivo y ausencia de penalización explícitos.

`minimum-reports-native-tests.log/xml`: 125 aprobadas, 112 integración + 13 puras, cero fallos/errores. Tres nuevas cubren cancelación/no presentación con factura, retorno, anulación y fecha inmutable; factura POS nativa con retorno parcial/stock único y monedas separadas; productividad y arqueo de dos monedas con diferencia sin asiento oculto. Se amplió expiración de retención y métricas hotel/motel positivas. Los fixtures se revierten por prueba. `minimum-reports-js-tests.log` conserva nueve de Desk y dos del portal; `minimum-reports-build.log` acredita assets.

`minimum-reports-http.json` registra 24 consultas en cada establecimiento autorizado y cuatro PDF/XLSX completos por HTTP 200: productividad, arqueos, cancelaciones y producción. Los ocho folios renderizados se revisaron; hashes y alcance en `minimum-reports-pdf-qa.json`, archivos en `output/minimum-reports/`. Estas consultas son de solo lectura. Los datos con penalización/retorno y diferencia USD se acreditan en integración; las capturas del sitio principal no simulan esos casos adicionales.

60. `60-catalogo-completo-busqueda.png`: búsqueda por nombre y selección de Servicio especial del catálogo en la Page, sitio limpio con 606 artículos de prueba; no se envió el formulario.

`catalog-preview-fixture.json` fija sitio, tamaño y artículo objetivo; `catalog-ui-selection.json` conserva su etiqueta visible y código estable HS-CATALOG-QA-0605. `catalog-preview-health.json` confirma 8089 cerrado y 8086 activo al terminar. El sitio temporal no tenía segundo transporte Socket.IO configurado: se acredita catálogo/Page, sin afirmar tiempo real en esa copia.

`catalog-native-tests.log/xml`: 127 aprobadas, 114 integración y 13 puras; dos nuevas prueban acceso completo, consumo con precio nativo/nombre histórico y seguridad de la proyección. `catalog-js-tests.log`: once de Desk (dos de catálogo) y dos de portal, con descartes por versión/cierre, fallo que bloquea envío, selección conservada y códigos originales. `catalog-build.log` acredita compilación. Los 606 artículos de UX se crearon explícitamente solo en hospitality-clean.localhost; las operaciones financieras de la batería se revierten y no forman parte de esa preparación.

61. `61-produccion-nombres-verificada.png`: comprobación en Gerencia de diez registros con nombres de artículos, habitaciones, cantidades, moneda y estado; consulta sin movimientos.

`localization-native-tests.log/xml`: batería completa en hospitality-clean.localhost, 129 aprobadas (116 integración y 13 puras). `localization-targeted-tests.log/xml`: dos aprobadas después de ampliar el caso del checklist. Los Translation de prueba usan francés y se revierten; no representan un paquete completo instalado. `localization-js-tests.log`: 15 aprobadas, incluidas dos nuevas de etiquetas/valores/nombres como texto. `localization-wire-invariants.json` compara literales de protocolo con 32d4020; `localization-extraction.json` acredita extracción nativa representativa y sintaxis de once plantillas, sin afirmar cobertura total. La ejecución inicial sobre la demostración no pasó y se documenta en AVANCE.md; los archivos de aceptación corresponden al sitio limpio.

`localization-exports.json`: nueve formatos instalados idénticos a su fuente, nueve PDF existentes y exportación operativa de Producción PDF/XLSX, sin mutaciones de negocio. Ocho comprobantes coinciden con los PDF ya revisados por SHA-256; mantenimiento y Producción se renderizaron y revisaron de nuevo. Los diez registros de Producción caben en una página y XLSX conserva números; archivos en output/localization/. `localization-build.log` y ambos registros migrate acreditan instalación/compilación. S01-04 conserva verificación parcial y el objetivo sigue activo.

62. `62-alta-fecha-corte.png`: alta administrativa de un establecimiento mixto con compañía existente, NIO, Managua, 05:30 y 18/10; formulario completado antes de guardar.
63. `63-alta-conservada.png`: nuevo establecimiento seleccionado después de guardar y recargar, misma fecha inicial y cero habitaciones/categorías/tarifas.

`initial-setup-native-tests.log/xml`: 133 aprobadas (120 integración + trece puras). Cuatro nuevas cubren fecha/corte, default local/año, reintento sin maestros financieros, permisos/entradas, fecha directa rechazada y ambas modalidades con cupo compartido. La primera ejecución tuvo un error en el propio test al consultar mode de la reserva; la batería final consulta el snapshot y pasa. `initial-setup-js-tests.log`: quince aprobadas; incluye corte sin propiedad y fecha inicial ISO. `initial-setup-build.log`: compilación. No cambia el esquema instalado.

`initial-setup-ui.json`: lectura del fixture administrativo creado desde Page en hospitality-clean.localhost, petición/auditoría únicas y cero documentos operativos o financieros, con finanzas deshabilitadas. Queda como fixture explícito en el sitio limpio y se creó después de la batería. La copia temporal no acredita Socket.IO. `architecture-current.json`: inspección instalada de solo lectura y núcleos limpios; sus bundles corresponden a la compilación de esta fase. AUDITORIA_ARQUITECTURA.md detalla la evidencia de cada obligación revisada y las diferencias aún pendientes.

`initial-setup-health.json` confirma sesión temporal cerrada, servidor 8089 detenido mediante el helper y 8086 activo con HTTP 200. La escucha se comprobó dentro de WSL: el reenvío TCP de Windows puede sobrevivir brevemente al proceso, por lo que un connect TCP desde Windows no se usó como prueba suficiente del cierre.

64. `64-close-financial-review.png`: revisión financiera del cierre en Gerencia, fechas y conceptos separados.
65. `65-close-financial-balances.png`: saldos y dos cargos pendientes; Confirmar cierre deshabilitado.
66. `66-close-saved-summary.png`: Ver resumen consulta la captura conservada, sin confirmar ni recalcularla.
67. `67-payment-policies-reloaded.png`: Approval/Disabled guardados y recargados en el establecimiento administrativo vacío del sitio limpio.

`financial-native-tests.log/xml`: 145 aprobadas (132 integración + trece puras) en hospitality-acceptance.localhost; doce nuevas sobre políticas, crédito/descuento, fechas, impuestos/devoluciones/POS/monedas y cierre estable. La venta directa se ejecuta además como cajero con turno propio. `financial-js-tests.log`: diecinueve aprobadas, diecisiete Desk y dos portal. `financial-build.log`, `financial-main-migrate.log` y `financial-acceptance-install.log` conservan instalación/compilación. El núcleo continúa limpio.

`financial-upgrade-before/after.json`: mismas 70 tablas/908 filas y archivo privado durante la migración, excluyendo solo las cuatro columnas nuevas. `financial-final-state.json`: sitio de aceptación sin operaciones remanentes, respaldo inicial, scheduler pausado, guardia de fixtures rechaza la demostración, 36 tablas nativas de esa demostración sin cambios, HTTP 200 y puertos comprobados desde WSL. No sustituye la recuperación de la revisión final.

`financial-close-ui-export.json`: revisión real guardada, fuentes/importes/pendientes y exportación sin mutaciones; PDF nativo en output/financial-close/daily-close.pdf, dos páginas renderizadas/revisadas. `payment-policy-ui.json` confirma política del fixture vacío, finanzas deshabilitadas y cero operaciones/documentos propios. La sesión administrativa temporal se cerró; 8089 se detuvo y no acredita otro Socket.IO.

La interrupción de WSL y las ejecuciones fallidas se describen en AVANCE.md y AUDITORIA_CIERRE_POLITICAS.md. El antiguo sitio limpio conserva respaldo de diagnóstico y scheduler pausado; la aceptación final usa un sitio nuevo independiente. Los resultados anteriores no se presentan como la aceptación de esta revisión. La matriz conserva 218 entradas: 46 V, dos I y 170 R; objetivo activo.

68. `68-service-items-configured.png`: nombres/asignaciones del asistente guardados y recargados; artículo propio de horas adicionales de motel.
69. `69-service-current-price.png`: agua por C$30, lista guardada y entrega con inventario; los nombres se muestran como texto.
70. `70-motel-extra-hours-quote.png`: revisión de cuatro horas por C$600 antes de confirmar.
71. `71-motel-separated-charges.png`: entrada real de prueba y cuenta con alojamiento C$450/horas adicionales C$150, sin factura ni cobro.

`service-native-tests.log/xml`: 153 aprobadas (139 integración + catorce puras). Siete casos nuevos de servicios/configuración/precios/contratos anteriores/crédito entre cargos y una prueba pura de componentes/fracciones a precisión 0/2/3. La factura usa fracciones de Hour; el artículo anterior conserva una unidad de cargo y se rechaza un artículo distinto con unidad entera. `service-js-tests.log`: 21 aprobadas; las dos nuevas prueban nombres escapados/guardado restringido y respuestas atrasadas/cierre. `service-build.log` y ambos service-*-migrate.log acreditan sincronización/compilación.

`service-upgrade-before/after.json`: mismas 70 tablas/911 filas y un archivo privado; solo se excluye la nueva columna extra_hour_item. `service-items-ui.json`: entrada confirmada desde Recepción, artículos/importes/cuenta y PDF de una página renderizada/revisada, en output/service-items/account.pdf. `service-ux-restored.json`: restauración nativa del respaldo previo al recorrido, 70 tablas/185 filas idénticas y cero estancias/facturas/cobros. No acredita recuperación del archivo privado de la demostración ni reversión final de código.

`service-final-state.json`: sitio de aceptación designado sin operaciones, scheduler pausado y respaldo, demostración rechazada por la guardia de fixtures con 36 tablas nativas sin cambios, HTTP 200 y 8089 cerrado desde WSL. La sesión temporal llegó a Login y se cerró. La copia no tiene segundo Socket.IO. AUDITORIA_SERVICIOS.md explica el alcance y los pendientes; matriz actual 47 V, una I y 170 R de 218 entradas.

72. `72-native-pos-cashier.png`: fondo 100 y cobro POS neto 60 en Caja; esperado 160, sin pago duplicado.
73. `73-native-pos-count.png`: arqueo con 16×10 y aprobación específica de supervisión visible.
74. `74-native-pos-shift-closed.png`: respuesta válida de servidor y turno cerrado por 160 desde la Page.
75. `75-native-pos-shift-pdf.png`: PDF nativo actualizado, una página revisada con conteo y origen POS, sin clave aleatoria del turno.

`pos-native-tests.log/xml`: 159 aprobadas (145 integración + catorce puras); seis nativas nuevas. `pos-js-tests.log`: 22 aprobadas, una nueva de POS. `pos-build.log` y ambos pos-*-migrate.log conservan compilación y migraciones; el de aceptación posterior al respaldo ejecuta la actualización de formatos por contenido. `pos-items-ui.json`: fixture del controlador nativo y cierre desde Page, 100+60=160, recibido/vuelto 100/40, sin HS Payment ni Payment Entry, PDF y huella. `pos-ux-restored.json`: 70 tablas/185 filas coinciden después de restaurar y repetir la batería; no sustituye la recuperación final de demostración. `pos-final-state.json`: 36 tablas nativas principales sin cambios, servicios/HTTP, copia vacía, 8089 cerrado y guardia de fixtures. Objetivo activo: 48 V, una I y 169 R de 218 entradas; véase AUDITORIA_CAJA_POS.md.

76. `76-refund-readable-source.png`: selector por concepto/fecha/importe/recibo; conserva la referencia interna al enviar y reservas con nombre/fecha.
77. `77-refund-applied-review.png`: revisión del servidor de anticipo aplicado, nota estándar, valor liquidado, cambio y entregado.
78. `78-refund-confirmed-cashier.png`: devolución confirmada C$1500 con documento ERPNext y esperado de caja cero.

`refund-native-tests.log/xml`: 165 aprobadas (151 integración y catorce puras), seis nuevas. `refund-js-tests.log`: 24 aprobadas, dos nuevas. `refund-build.log` y ambos refund-*-migrate.log: compilación/migración. `refund-items-ui.json`: preparación por API/controladores y devolución desde Page, anticipo/asignación originales conservados, crédito/esperado cero. `refund-ux-restored.json`: restauración nativa y 70 tablas/185 filas coinciden también después de repetir la batería. `refund-final-state.json`: 36 tablas nativas principales sin cambios, aceptación vacía, servicios/HTTP y 8089 cerrado; núcleo limpio en architecture-current.json. Sin segundo Socket.IO; no sustituye recuperación final con archivo privado/reversión. AUDITORIA_DEVOLUCIONES.md: límites y pendientes. Matriz activa: 48 V, dos I y 168 R de 218 entradas; S09-08 parcial.

79. `79-guarantee-application-no-cash.png`: garantía aplicada desde Page; esperado C$1500 sin otro ingreso y concepto legible.
80. `80-guarantee-refund-review.png`: revisión de garantía aplicada contra nota de crédito estándar; valor liquidado y entregado C$1500.
81. `81-guarantee-refund-confirmed.png`: Caja después de confirmar, con aplicación, recibo y devolución diferenciados y esperado cero.

`guarantee-native-tests.log/xml`: 169 aprobadas (155 integración y catorce puras), cuatro nuevas. `guarantee-js-tests.log`: 26 aprobadas, dos nuevas. `guarantee-build.log` y ambos guarantee-*-migrate.log: compilación/migración. `guarantee-items-ui.json`: aplicación y devolución desde Page; preparación por API/controladores, original conservado y pasivo/crédito/esperado cero. `guarantee-ux-restored.json`: restauración con archivos y 70 tablas/185 filas coincidentes después de repetir la batería. `guarantee-final-state.json`: aceptación sin operaciones, 36 tablas nativas principales sin cambios, HTTP/servicios y 8089 cerrado. `guarantee-main-financial-read.json`: resumen financiero de ambas propiedades sin modificaciones. Núcleos limpios en architecture-current.json. No sustituye recuperación final con archivo privado/reversión. AUDITORIA_GARANTIAS_APLICADAS.md delimita alcance: 49 V, dos I y 167 R de 218; objetivo activo.

82. `82-pos-credit-partial-quantity.png`: devolución por nombre, cantidad de una unidad y clave original oculta.
83. `83-pos-credit-net-review.png`: revisión de una unidad/C$30 y efectos de inventario/dinero antes de confirmar.
84. `84-pos-credit-confirmed.png`: confirmación simplificada con nota y asiento estándar, sin avisos de configuración manual.
85. `85-pos-credit-closed-cashier.png`: turno de devolución cerrado en 100, original cerrado en 160 y cobro 60/devoluciones -30/-30 en una vista.
86. `86-pos-credit-shift-pdf.png`: arqueo real de una página, fondo 160, esperado/contado 100, diferencia cero y ambos asientos.

`credits-native-tests.log/xml`: 183 aprobadas (169 integración y catorce puras), catorce nuevas. `credits-js-tests.log`: 28 aprobadas, dos nuevas; ejecución portable con tools/run_ui_tests.cjs. `credits-build.log` y ambos credits-*-migrate.log: compilación/migración. `credits-items-ui.json`: venta/turnos preparados por controlador/API, notas parcial/resto y cierre desde Page; original/stock conservados, créditos liquidados y sin pagos operativos adicionales. `credits-pdf-check.json`: hash/contenido de una página renderizada. `credits-ux-restored.json`: restauración con archivos y 70 tablas/185 filas coincidentes también después de la batería. `credits-final-state.json`: aceptación vacía, 36 tablas nativas principales sin cambios, HTTP/servicios y 8089 cerrado. `credits-main-financial-read.json`: lectura principal sin modificaciones; núcleos limpios en architecture-current.json. No sustituye recuperación final con archivo privado/reversión. AUDITORIA_NOTAS_POS.md: alcance. Matriz: 49 V, dos I y 167 R de 218; objetivo activo.

87. `87-mixed-credit-readable-review.png`: nota de 60, devolución inmediata de 30 y crédito pendiente de 30; recibo adicional por concepto/fecha/importe/documento.
88. `88-mixed-credit-pending-confirmed.png`: confirmación con instrucciones para devolver el recibo pendiente.
89. `89-mixed-additional-refund-review.png`: revisión de devolución adicional de 30 contra la nota, sin diferencia de cambio.
90. `90-mixed-closed-cashier.png`: turno nuevo cerrado en 100 y original cerrado en 160.
91. `91-mixed-native-operational-receipts.png`: cobro/devolución adicionales en HS Payment y +30/-30 propios del POS, sin repetir el recibo adicional.

`mixed-native-tests.xml/log`: 187 aprobadas (173 integración y catorce puras), cuatro casos adicionales y un caso previo ampliado. `mixed-js-tests.log`: 29 aprobadas, una nueva. `mixed-build.log` y ambos mixed-*-migrate.log: compilación/migración. `mixed-items-ui.json`: nota/devolución/cierre desde Page, originales/asignación conservados, crédito/stock cero y resumen sin duplicar. `mixed-ux-restored.json`: restauración con archivos y 70 tablas/185 filas idénticas. `mixed-final-state.json`: aceptación vacía, 36 tablas nativas principales intactas, servicios/HTTP y 8089 detenido. `mixed-main-financial-read.json`: lectura financiera principal sin modificaciones; núcleos limpios en architecture-current.json. AUDITORIA_RECIBOS_POS.md delimita la evidencia y la verificación inicialmente prematura de la restauración. No sustituye recuperación final con archivo privado y reversión de código. S09-08 V; matriz 50 V, una I y 167 R de las mismas 218 entradas, objetivo activo.

92. `92-service-accounting-configured.png`: configuración guardada/reabierta, nombre del servicio, cuentas/centro del minibar y valores de la sede.
93. `93-service-accounting-sale-review.png`: venta directa de Agua minibar por C$30 antes de confirmar.
94. `94-service-accounting-sale-confirmed.png`: factura confirmada, entrega y stock 99.
95. `95-service-accounting-closed-cashier.png`: turno cerrado en 130, fondo 100 y cobro 30.

`accounting-native-tests.xml/log`: 193 aprobadas (179 integración y catorce puras), seis nuevas; `accounting-js-tests.log`: 30 aprobadas, una nueva. `accounting-build.log` y ambos accounting-*-migrate.log: compilación/migración. `accounting-items-ui.json`: configuración/venta/cierre desde Page, ingreso 30/costo 10/centro nativos, Item Default intacto. `accounting-upgrade.json`: 70 tablas/911 filas previas conservadas y nuevos campos vacíos. `accounting-ux-restored.json`: respaldo con archivos restaurado, 71 tablas/185 filas idénticas también después de la batería final. `accounting-final-state.json`: aceptación vacía, HTTP/servicios y 8089 cerrado; 35 tablas nativas con huella histórica y 36 coincidentes con el respaldo previo a 0.5.0. `accounting-company-cache.json`: diferencia histórica de Company limitada a dos cachés/modified, acreditada por fila de respaldo, mantenimiento nativo completado y funciones de lectura. `accounting-main-financial-read.json`: lectura principal sin modificaciones; architecture-current.json acredita 35 DocTypes/once Pages y núcleos limpios. AUDITORIA_CONTABILIDAD_SERVICIOS.md documenta alcance y corrección de fixtures de fecha/compañía. No sustituye recuperación final actual con archivo privado/reversión. S09-09 V; matriz 51 V, una I y 166 R de 218, objetivo activo.

## Contraste de flujos, transacciones y aceptación, 20/10/2026

`flow-audit.json` relaciona 38 entradas con casos aprobados del JUnit vigente y conserva su huella. Comprueba ambas carreras reales y ausencia de llamadas commit en los módulos de ejecución. Su evaluación pura del sanitizador, con marcadores ficticios, demuestra que `nested.card.number` permanece; no ingresa una petición ni escribe una base. Junto con la revisión de cierre/hooks, confirma dos diferencias: cargos periódicos aún ausentes y datos arbitrarios conservados por el webhook. Las tres entradas P representan esas dos diferencias.

No se ejecutó una batería ni un recorrido nuevo y no se cambió código de aplicación. El inventario actual queda en **79 V, ocho I, tres P y 128 R**; 28 V, siete I y tres P provienen de este contraste. Véase ../AUDITORIA_FLUJOS_TRANSACCIONES.md. Continúan traducciones, verificaciones y recuperación final; objetivo activo.

## Recibos mínimos del receptor, 0.5.1

integration-native-tests.log/xml acredita 196 aprobadas (182 integración y catorce puras); integration-js-tests.log conserva treinta regresiones. integration-upgrade.json compara 72 tablas con Version/1191 filas y dos archivos privados en demostración, 195 filas en aceptación, después de respaldos con archivos y migrate. Los recibos legacy y su Version se ejercitan en tests revertidos: esos sitios tenían cero eventos de proveedor. integration-final-state.json confirma guardia de fixtures, aceptación sin operaciones, HTTP/puertos y núcleo nativo preservado con la caché Company acreditada. AUDITORIA_RECEPTOR.md delimita resultados.

No se implementa ni activa sincronización con Airbnb/Booking/otros canales, pendiente por indicación del usuario. S14-08 pasa a V: 80 V, ocho I, dos P y 128 R. La prioridad siguiente incluye claridad y longitud de formularios en escritorio/móvil, junto con el alcance operativo pendiente.

## Formularios por tarea, 0.5.2

96. `96-formulario-operacion.png`: políticas divididas en Operación, Cuentas y almacenes, Artículos e impuestos; acción de guardar visible.
97. `97-tarifa-precio-claro.png`: borrador de tarifa con precio por noche y cuatro secciones.
98. `98-huesped-movil-breve.png`: borrador de huésped a 390×844, datos esenciales y botón de 44 px a todo el ancho.
99. `99-tarifa-validacion-movil.png`: intento de guardar desde otra pestaña vuelve a Precio; ningún alta incompleta.
100. `100-cobro-confirmacion-unica.png`: revisión de cobro 1500, recibido 1600, vuelto 100; formulario anterior oculto/inactivo.
101. `101-formularios-cobro-cierre.png`: un cobro contabilizado y turno cerrado en 1500 sin diferencia.

`forms-js-tests.log`: 37 aprobadas, siete nuevas; no son recorridos de navegador. El backend vigente conserva 196 aprobadas de 0.5.1, sin nueva ejecución conjunta en esta fase. `forms-build.log` y `forms-*-migrate.log`: compilación/migración. `forms-items-ui.json`: valores guardados desde otras pestañas, reserva/estancia/cuenta únicas, una factura y Payment Entry, saldo cero y cierre. Toda la captura/confirmación del escenario se hizo desde Pages con datos ficticios; inspect solo lee y revierte sus bloqueos. Se prueba cancelar/reabrir revisión sin perder datos, y se inspecciona la sección Devolución sin registrarla.

`forms-ux-restored.json`: restauración nativa con archivos, 71 tablas/185 filas idénticas. `forms-upgrade.json`: comparación adicional de todas las columnas de 72 tablas con Version, 1191 filas y dos archivos privados principales/195 filas de aceptación conservados. `forms-final-state.json`: aceptación sin operaciones, fecha principal conservada, HTTP/servicios y 8089 detenido. `architecture-current.json`: núcleos limpios, assets, 35 DocTypes y once Pages. UX_FORMULARIOS.md delimita evidencia, correcciones detectadas y alcance pendiente. F22a V para este cambio; F22 general I y matriz canónica sin cambios: 80 V, ocho I, dos P y 128 R de 218. No sustituye la recuperación final de la revisión que se entregue.


## Cargos por noche, 0.6.0

102. `102-politica-cargos-nocturnos.png`: política guardada/reabierta en pestaña propia a 390×844; explicación y acción siempre visibles.
103. `103-cuenta-noches-programadas.png`: tres noches aceptadas por 4500, programado y saldo total separados, sin fuentes internas en la tabla.
104. `104-cierre-cargos-generados-programados.png`: resumen conservado tras preparar dos veces la fecha; 1500 pendiente y 3000 programado, grupos desplegables y pendientes claros.
105. `105-cuenta-periodica-pdf.png`: render Poppler de la cuenta nativa de una página, una noche pendiente y dos programadas; sin factura ni pago.

`periodic-native-tests.log/xml`: 211 aprobadas (197 integración y catorce puras), quince nuevas. Incluye reintentos con distinta clave, cierre/avance/reapertura, rollback y recuperación, precios distintos/cero, extensión y factura estándar con/sin origen. `periodic-js-tests.log`: 38 aprobadas, una nueva para apertura de secciones con importes y acceso a detalles en cero. Los informes locales previos de 208/210 no sustituyen el final. `periodic-build.log` y `periodic-*-migrate.log` conservan compilación/migración; los originales de consola permanecen en output/periodic, las copias de evidencia normalizan espacio y progreso de terminal.

`periodic-items-ui.json`: configuración/entrada/preparación repetida desde Pages con datos ficticios, tres orígenes únicos, una bitácora y sin facturas/pagos. No se confirma el cierre. `periodic-pdf.json`: una página, huella y texto/importes verificados; render completo revisado. `periodic-ux-restored.json`: restauración nativa con archivos, 71 tablas/185 filas idénticas después del recorrido y de la batería. `periodic-upgrade.json`: columnas anteriores de 72 tablas/1191 filas y dos archivos privados principales/195 filas de aceptación conservados; política inicial y sin programación retroactiva. `periodic-final-state.json`: aceptación sin operaciones, fecha principal, HTTP/puertos y 8089 cerrado. architecture-current.json acredita núcleos limpios y metadatos/assets.

`periodic-page-invoice-gap.json` contrasta de forma estática la acción invoice presente en servidor y ausente en Pages; captura 103 muestra las acciones disponibles. S00-02/F22 P: hace falta emitir factura explícita sin cobrar/salir. S12-03/S16-06/S17-08 V; matriz actual 83 V, siete I, una P y 127 R de las mismas 218 entradas. CARGOS_PERIODICOS.md delimita reglas y verificación. La recuperación final actual y el resto del alcance siguen abiertos; sincronización externa pendiente por indicación del usuario.

## Facturación explícita desde Pages, 0.6.1

- `billing-native-tests.log/xml`: batería conjunta, 220 aprobadas; nueve casos nuevos en test_invoice_page.py. `billing-js-tests.log`: 41 aprobadas, tres nuevas para revisión/confirmación, cero y reintento.
- `billing-build.log`, `billing-main-migrate.log` y `billing-acceptance-migrate.log`: construcción y migraciones nativas de ambos sitios.
- `106-cuenta-accion-facturar.png`: acción explícita desde estancia. `107-factura-cero-revision-movil.png`: revisión compacta 390×844. `108-factura-cero-emitida.png`: dos cargos cero facturados y estancia activa. `109-factura-revision-sin-cobro.png`: revisión C$1250. `110-factura-emitida-estancia-activa.png`: confirmación con total, saldo y enlace estándar.
- `billing-items-ui.json`: dos emisiones desde Pages por gerencia; entrada cero por Page y entrada positiva como fixture API, ambas identificadas. Sin pagos, turnos, asientos de garantía ni limpiezas. No acredita tiempo real ni todos los roles.
- `billing-ui-upgrade.json`: todas las columnas de 72 tablas conservadas, 1191 filas/dos archivos privados principales y 195 filas de aceptación. `billing-ux-restored.json`: 71 tablas/185 filas tras restauración nativa. `billing-final-state.json`: aceptación vacía, principal conservado, 8089 apagado/8086 operativo y guardias. `architecture-current.json`: núcleos limpios, 35 DocTypes/once Pages/nueve roles.
- `periodic-page-invoice-gap.json` sigue siendo evidencia histórica de f424e2d; su diferencia quedó resuelta en esta revisión. No ejecutar su reproducción como comprobación del código actual.

La matriz canónica conserva 218 entradas: 83 V, ocho I, cero P y 127 R. F22b acredita este flujo; S00-02/F22 requieren aceptación completa por rol. La recuperación final de F26 continúa pendiente. No se implementó sincronización de canales.

## Contraste de Pages y habitaciones sobre 3563ef0

`pages-rooms-audit.json` y `../AUDITORIA_PAGES_HABITACIONES.md` revisan las 27 entradas de las secciones 4 y 5 con código/aserciones/evidencia existentes: 16 V, nueve I y dos P. Verifica nombres de casos aprobados en billing-native-tests.xml y conserva huellas del código. No es otra ejecución ni un recorrido adicional. Las dos P son vistas de llegadas/salidas/cuentas en Estancias y llegada prevista en tarjetas. La auditoría canónica vigente queda en **99 V, diecisiete I, dos P y 100 R**, las mismas 218 entradas/huella. Los recuentos de las fases anteriores de este índice son históricos.

## Estancias y próximas llegadas, 0.6.2

- `board-native-tests.log/xml`: 229 aprobadas, nueve nuevas en test_desk_board.py. `board-js-tests.log`: 45 aprobadas, cuatro nuevas para presentación/escapado, respuestas obsoletas y contexto/paginación. `board-build.log` y `board-*-migrate.log`: construcción y migraciones de ambos sitios.
- `111-estancias-llegadas.png`: llegada pendiente de hoy. `112-estancias-cuentas-movil.png`: cuenta, saldo y Ver cuenta visibles en 390×844, ficha de 352 px/scrollWidth 352 y botón 44 px. `113-recepcion-proxima-llegada.png`: estancia actual y próxima reserva separadas, con Ver reserva. `114-estancias-entrada-confirmada.png`: dos alojados tras registrar H103. `115-estancias-salidas.png`: salida pendiente. `116-estancias-fecha-llegadas.png`: consulta hasta mañana, dos llegadas. `117-estancias-llegada-completada.png`: entrada confirmada y estado vacío de llegadas de hoy.
- `board-items-ui.json`: fixture API de tres reservas/primera estancia y segunda entrada desde Pages por recepcionista. Dos Active, dos Pending y cero facturas/pagos/turnos/limpieza/cierre. No acredita operación grupal desde navegador, todos los roles ni tiempo real.
- `board-upgrade.json`: 72 tablas/1191 filas/dos archivos privados principales y 195 filas de aceptación conservados, sin cambios de negocio. `board-ux-restored.json`: 71 tablas/185 filas idénticas tras restauración Bench con archivos. `board-final-state.json`: aceptación sin operaciones, principal conservado, guardias, HTTP 200/8086 y 8089 cerrado. `architecture-current.json`: núcleos limpios y metadatos/assets vigentes.

Las dos P históricas de pages-rooms-audit.json quedan resueltas y acreditadas: matriz al cerrar esa fase **101 V, diecisiete I, cero P y 100 R**, las mismas 218 entradas/huella. Continúan verificaciones I, contraste restante y recuperación final; sincronización externa pendiente por instrucción del usuario.

## Contraste de reservas, tarifas y estancias sobre 43ce506

- `reservations-native-tests.log/xml`: batería conjunta nueva, **236 aprobadas** (222 integración/catorce puras), sin fallos/errores/omisiones. Siete casos nuevos en test_booking_rate_audit.py; código de aplicación 0.6.2 sin modificaciones. No repite los 45 JS ni los recorridos de navegador anteriores.
- `reservations-audit.json` y `../AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md`: 32 R contrastadas con archivos/aserciones/evidencia por entrada, 26 V/tres I/tres P. Huellas de código/especificación, hallazgos estáticos acotados y ejemplo financiero nativo. Las ausencias son históricas de la revisión indicada y deben contrastarse después de implementarlas.
- `reservations-conservation.json`: comprobación posterior contra la línea de base privada anterior, sin reemplazar huellas. Las mismas 72 tablas/1191 filas/dos archivos privados principales y 72 tablas/195 filas de aceptación; rollback de la batería final secuencial después de restaurar el respaldo original. `reservations-recovery.json` acredita respaldo de diagnóstico y restauración tras dos ejecuciones solapadas por error, descartadas como aceptación; una produjo seis errores de bloqueo y la adicional se canceló. No se sustituyeron huellas iniciales. Aceptación vacía, fecha principal 19/10, guardia de fixtures, excepción Company acreditada, HTTP 200/8086, Socket.IO/Redis activos y 8089 apagado.

Matriz vigente: **127 V, veinte I, tres P y 68 R**, 218 entradas/huella originales. Quedan diferencias en consulta por cantidad, borrador persistente y explicación tarifaria en la cuenta; aceptación de identificación/corrección del huésped, contador tras recarga y fiabilidad de retenciones, más las verificaciones anteriores. La cuenta imprimible sí contiene los componentes financieros, comprobados con HTML nativo; no se generó/revisó PDF nuevo. La sincronización de canales sigue pendiente por instrucción del usuario; objetivo activo.

## Consulta por cantidad — 0.6.3

- `availability-native-tests.log/xml`: **243 aprobadas** (229 integración/catorce puras), siete casos nuevos de TestAvailabilitySearch. `availability-js-tests.log`: **49 aprobadas** (47 Desk/dos portal), cuatro nuevas para consulta/errores/contexto. La batería nativa precede las mejoras finales de texto/espacio; Python funcional no cambió después y la UI final se verificó con JS/navegador.
- `118-disponibilidad-cantidad-escritorio.jpg`: pide dos frente a cupo uno. `119-disponibilidad-cantidad-movil.jpg`: pide una, resultado positivo y botón completo de 44 px. `120-disponibilidad-filtros-editados.jpg`: resultado anterior retirado al editar. `121-disponibilidad-opciones.jpg`: diez opciones y explicación del cupo. Son JPEG nativos; el móvil usa viewport 390×844 y captura 390×787.
- `availability-browser.json`: recorrido de recepción, respuestas/fechas/edición/desplegable y geometría sin desborde. `availability-items-ui.json`: fixture API de reserva grupal de nueve unidades y consultas Page/API; 72 tablas con Version idénticas al fixture tras el recorrido, cero operaciones de estancia/finanzas. No presenta esa preparación como realizada desde Page.
- `availability-main-migrate.log`, `availability-acceptance-migrate.log`, `availability-restore-migrate.log`, `availability-build.log`: actualización/construcción. `availability-upgrade.json`: columnas/archivos de 72 tablas/1191 filas/dos archivos privados principales y 72/195 de aceptación conservados. `availability-ux-restored.json`: respaldo original con archivos restaurado, 71/185. `availability-final-state.json`: aceptación vacía, guardia, fecha 19/10, Company acreditada, HTTP 200/8086, Socket.IO/Redis activos y 8089 apagado. `architecture-current.json`: núcleos limpios/metadatos/assets.
- `availability-feature.json` y `../DISPONIBILIDAD_POR_CANTIDAD.md`: fuentes/casos/capturas/contrato y límites exactos con/sin margen, enlazados a S06-01/S05-07/S16-03. Las tres promociones dejan **130 V, dieciocho I, dos P y 68 R** de 218. La sincronización externa permanece pendiente y la recuperación final del objetivo no queda sustituida por esta restauración.

## Precio histórico, resumen y series — 0.6.5

- `tariffs-native-tests.log/xml`: 271 aprobadas (257 integración y 14 puras), sin fallos/errores/omisiones. Dieciséis nuevos casos frente a 0.6.4: catorce de cálculo/etiquetas/resumen y dos de 24 series nativas, creación e idempotencia con enlaces anteriores. `tariffs-js-tests.log`: 66 aprobadas, diez más que 0.6.4.
- `128–130` son JPEG nativos del cálculo de Hotel, modalidad Por tiempo y cálculo móvil. `131–132` muestran Ver reserva legible en escritorio/móvil; `133–135`, números clickeables y preselección de fechas, M103, Estándar y dos personas. `tariffs-browser.json` y `booking-details-browser.json` distinguen fixture API y Page de solo lectura, incluyen geometría y cierre de sesión/viewport. No se guardó otra reserva en este recorrido.
- `136–137` son renders PNG de los dos PDF nativos de una página. `tariffs-items-ui.json` conserva importes históricos, SHA de PDF y comparación idéntica de 72 tablas con Version después de Page/impresión. Los tarifarios se cambiaron después de aceptar. La configuración de assets para CLI fue local al proceso; no se presenta como descarga de navegador.
- `tariffs-main-migrate.log`, `tariffs-acceptance-migrate.log`, `tariffs-restored-migrate.log`, `tariffs-build.log`: actualización final y construcción. `tariffs-upgrade.json`: principal 72 tablas/1191 filas/dos archivos privados y aceptación 72/195 conservados. `tariffs-ux-restored.json`: 71/185 restauradas con archivos. `tariffs-final-state.json`: aceptación sin operaciones, guardia principal, fecha 19/10, caché Company histórica, HTTP 200/servicios y 8089 apagado. `architecture-current.json`: núcleos limpios y autoname de cada DocType instalado.
- `../EXPLICACION_TARIFA_HISTORICA.md` acredita S07-09; `../SERIES_DOCUMENTALES.md` documenta la ampliación del usuario. Matriz 132 V, 18 I, 0 P, 68 R de las mismas 218 entradas. Las 86 sin cierre, aceptación integral por rol, traducciones y recuperación final continúan pendientes. OTA permanece aplazada.

## Cuenta resumida — 0.6.6

- `account-summary-native-tests.log/xml`: 272 aprobadas, 258 integración y 14 puras, cero errores/fallos/omisiones. `account-summary-js-tests.log`: 66 aprobadas. Contrato de impresión actualizado: descripciones escapadas, desglose histórico disponible en API/Page y ausente en PDF; caso nuevo con descuento, factura 1400, cobro 500 y saldo 900. Las pruebas completas se repitieron tras corregir una aserción anterior del contexto de impresión.
- `138-cuenta-resumida-hotel.png`, `139-cuenta-resumida-por-tiempo.png`: las dos páginas nativas completas revisadas. `account-summary-items-ui.json` registra fixture API, importes, SHA de PDF y las mismas 72 tablas con Version después de consultas/impresión. Los maestros cambiaron después de aceptar el precio. No se presenta el fixture como operación Page.
- `140-cuenta-resumida-impresion-nativa.jpg`, `account-summary-browser.json`: recepción abre formato nativo y descarga Obtener PDF en localhost:8089. El PDF descargado se extrae/renderiza: una página, mismo texto que CLI, sin bloques históricos y cifras conservadas. La descarga HTTP no usa el host configurado solo para CLI. Guest rechazado; sesión/pestaña cerradas y sin mutaciones de negocio.
- `account-summary-upgrade.json`, `account-summary-ux-restored.json`, `account-summary-final-state.json`: columnas/archivos conservados, restauración original con archivos, aceptación vacía 71/185 y 72/195, principal 72/1191/dos archivos privados/fecha 19/10, servicios activos/HTTP 200 y 8089 apagado. Formato actualizado por reload-doc, sin campos nuevos; arquitectura actual acredita núcleos limpios. `../CUENTA_RESUMIDA.md` explica la petición del usuario y conserva el alcance. Matriz permanece 132 V, 18 I, 0 P, 68 R; objetivo activo.
- `account-summary-installed.json`: HTML instalado idéntico a la metadata del repositorio en ambos sitios, sin bloques históricos; versión/SHA y comprobaciones de solo lectura. Se reproduce con `tools/verify_account_summary.py`.

## Registro y corrección de huéspedes — 0.6.7

- `guest-profiles-native-tests.log/xml`: 284 aprobadas (270 integración/14 puras), doce casos nuevos de TestGuestProfiles; cero errores/fallos/omisiones. `guest-profiles-js-tests.log`: 71 aprobadas, cinco nuevas. `guest-profiles-build.log`: assets construidos; el código funcional no cambió tras esas baterías.
- `141–147` son JPEG nativos de registro mínimo, corrección/motivo, identificación obligatoria y persistencia en escritorio/móvil. `guest-profiles-browser-ui.json`: rol recepción, flujo Page, 1280×720 y 390×844 sin desborde; Guardar cambios de 44 px visible. Se cerró sesión/pestaña y se restableció el viewport.
- `guest-profiles-items-ui.json`: fixture de política solamente; los dos registros/correcciones se realizaron desde Page. Dos Guest/dos Customer/un Contact, sin duplicados, sin Address/identificación innecesaria; Version/motivos/actor y comparación de 72 tablas (65 idénticas; operación/finanzas intactas). La evidencia previa `group-companions.json` acredita vinculación desde Page; el nuevo caso nativo conserva las referencias de principal y acompañante al corregirlos.
- `guest-profiles-upgrade.json`, `guest-profiles-ux-restored.json`, `guest-profiles-final-state.json`: restauración con archivos y conservación de 71/185 y 72/195 aceptación; principal 72/1191/dos archivos/fecha 19/10. La primera comprobación encontró servicios detenidos; tras run_dev, HTTP 200/8086/9001/Redis activos y 8089 apagado. Núcleos limpios, 35 DocTypes/11 Pages y assets acreditados en `architecture-current.json`. `account-summary-installed.json` mantiene comprobación de formato conciso bajo 0.6.7.
- `../GESTION_HUESPEDES.md`: contrato, correcciones de fixtures/diagnóstico, conservación y límites. S08-02 I→V, **133 V, 17 I, 0 P y 68 R** de 218; no acredita UX integral ni recuperación final. OTA aplazada.
