# Hospitality Suite

PMS nativo para hoteles, moteles y operación mixta. Recepción, caja, limpieza y gerencia trabajan desde once Pages de Desk en español; la contabilidad y el inventario permanecen en ERPNext.

Versión objetivo probada: **Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, MariaDB 10.11.14 y Node 24.18.0**, Ubuntu 24.04 / WSL2. App 0.3.0. Otras versiones no están acreditadas.

El desarrollo continúa: [matriz de requisitos](docs/REQUISITOS.md), [auditoría punto por punto](docs/AUDITORIA_ESPECIFICACION.md), [registro de avance](docs/AVANCE.md) y [arquitectura](docs/ARQUITECTURA.md). No se declara listo para producción mientras existan pendientes obligatorios.

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

El usuario necesita roles HS y un registro HS Access por establecimiento/compañía. El asistente concede únicamente roles HS; la administración de cuentas de acceso y los roles ERPNext adicionales siguen los mecanismos estándar de Frappe. Un recepcionista que también cobra puede combinar HS Receptionist y HS Cashier.

Consulte el [manual por rol](docs/MANUAL.md), [tratamiento contable](docs/CONTABILIDAD.md) y [operación técnica](docs/OPERACION.md) y [contratos API](docs/API.md).

## Demostración explícita

Solo en un sitio de pruebas, habilite `hospitality_allow_demo` y ejecute:

```sh
bench --site hotel.localhost set-config hospitality_allow_demo true
bench --site hotel.localhost execute hospitality_suite.demo.seed
```

Crea datos ficticios: hotel y motel con diez habitaciones cada uno, huéspedes, precios, existencias de muestra y usuarios por rol. Las contraseñas aleatorias quedan en `sites/<sitio>/private/hospitality-demo-users.json`, modo 600. La carga es repetible y está separada de la instalación normal.

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
bench --site hotel.localhost set-config allow_tests true
bench --site hotel.localhost set-config hospitality_integration_test_site true
bench --site hotel.localhost run-tests --app hospitality_suite
```

`before_tests` exige Redis disponible y un sitio designado sin operaciones; después carga la demostración explícita para las pruebas. Cada caso revierte sus movimientos. Conserve un respaldo inicial para recuperar una ejecución interrumpida; no ejecutar en producción. Última batería conjunta: **145 aprobadas** en hospitality-acceptance.localhost, 132 de integración y 13 puras, además de diecisiete de Desk y dos del portal. El sitio limpio anterior conserva un respaldo de diagnóstico tras una interrupción de WSL; no es la línea de base actual. La demostración principal conserva operaciones UX y tampoco representa ese estado inicial. Los dos casos de concurrencia usan conexiones y commits reales y se ejecutan aparte:

```sh
bench --site hospitality.localhost execute hospitality_suite.tests.concurrency.verify
bench --site hospitality.localhost execute hospitality_suite.tests.concurrency.verify_category
```

Las nueve pruebas de orden de respuestas, recuperación, edición numérica, acciones de grupos, horas locales, reportes y etiquetas de Pages se ejecutan con `node tools/test_desk_transport.cjs`. Las dos del catálogo se ejecutan con `node tools/test_catalog_ui.cjs` y cubren respuestas atrasadas, fallo de búsqueda, selección conservada y valores originales. Las dos del portal se ejecutan con `node tools/test_portal_ui.cjs` y cubren cotizaciones obsoletas y reintentos con la misma referencia. Las dos de presentación/traducción verifican valores estables y nombres insertados como texto. Puede ejecutar las quince juntas con `node --test tools/test_desk_transport.cjs tools/test_catalog_ui.cjs tools/test_localization_ui.cjs tools/test_portal_ui.cjs`. Los ensayos reales de sesiones, corte y respuesta perdida se describen en docs/OPERACION.md.

Los helpers de concurrencia están limitados al sitio sintético y conservan anulaciones auditadas. No son pruebas que deban ejecutarse contra clientes reales.

`tools/qa_exports.py` genera las impresiones y exportaciones reales del recorrido ficticio. `qa_pdf.py` y `qa_workbook.mjs` las inspeccionan sin modificar su contenido; requieren las dependencias de QA. La evidencia está en `docs/evidence/` y los archivos de revisión locales en `output/`.

## Alcance y límites actuales

El núcleo incluye disponibilidad serializada, snapshots tarifarios, grupos, folios, facturación, anticipos/garantías reales, caja, servicios/stock y limpieza. Las Pages permiten órdenes/recepciones/facturas de compra, pago a proveedor, egresos documentados, clasificación/mínimos, traslados/consumos/conteos y liquidación bancaria con comisiones/retenciones. Se verificaron circuitos de motel y hotel, y compra/pago/liquidación desde las Pages con datos ficticios.

La retención de identificaciones y evidencias requiere revisión de gerencia y una política por establecimiento; los archivos se eliminan mediante outbox después del commit. Su alcance y recuperación están en docs/OPERACION.md.

La matriz distingue lo implementado de lo probado y lo pendiente. Mantenimiento, planes incluidos, portal Guest, grupos y fallos de transporte ya tienen recorridos de navegador; faltan ampliación de inventario móvil y auditoría/recuperación final de despliegue. Pasarelas, canales, mensajería y cerraduras solo tienen contratos; no hay proveedor real configurado ni pagos simulados como liquidados.
