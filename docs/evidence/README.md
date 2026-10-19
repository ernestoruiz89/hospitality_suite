# Evidencia de pruebas

Sitios ficticios locales: hospitality.localhost y hospitality-clean.localhost, bench separado en WSL Ubuntu 24.04. Frappe 16.52.0, ERPNext 16.51.1 y app 0.2.0. No hay datos ni operaciones de producción.

## Automatizadas

- `tests-clean.log`: última batería conjunta, **65 aprobadas**: 54 integración y 11 puras.
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

Las capturas prueban escritorio. No acreditan vista móvil, fallo de red, portal ni todos los recorridos de grupo/hotel; siguen en la matriz.

## Impresiones y exportación

`exports-manifest.json` conserva origen, formato, tamaño y SHA-256 de los archivos locales generados por los controladores instalados. `pdf-qa.json` acredita diez PDF legibles de una página cada uno. Se inspeccionaron visualmente sus PNG: reserva, registro, cuenta, recibo, arqueo, limpieza, mantenimiento, cierre diario, factura y conciliación.

La cuenta muestra cargos, facturas/impuestos, cobros/garantías y saldo; el arqueo incluye denominaciones. La factura HS Factura usa valores estándar y oculta referencias técnicas. No se acredita cumplimiento fiscal particular por el solo formato de demostración.

`workbook-qa.log` contiene la importación de solo lectura y los valores de la conciliación XLSX: importes numéricos, moneda NIO y diferencias cero. También se revisó su imagen sin texto cortado. Los archivos PDF/XLSX e imágenes de revisión están en `output/`, excluido de Git; los scripts QA permiten reproducirlos después de completar un recorrido ficticio.

El núcleo de Frappe/ERPNext se comprobó sin cambios. Los pendientes obligatorios continúan en `../PENDIENTES.md`; esta evidencia no declara aptitud para producción.
