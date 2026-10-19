# Evidencia de pruebas

Sitios ficticios locales: hospitality.localhost, hospitality-clean.localhost y hospitality-restore.localhost, bench separado en WSL Ubuntu 24.04. Frappe 16.52.0, ERPNext 16.51.1 y app 0.2.0. No hay datos ni operaciones de producción.

## Automatizadas

- `tests-clean.log`: última batería conjunta, **103 aprobadas**: 92 integración y 11 puras.
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
