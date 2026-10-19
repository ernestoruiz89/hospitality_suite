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
23. `23-tiempo-real-recuperado.png`: servidor reiniciado y Actualizar reconecta/refresca. `transport-sessions.json` prueba además tres sesiones autenticadas, aislamiento, commit/rollback y recuperación de cambio perdido. `desk-transport-tests.log`: tres pruebas JavaScript aprobadas.
