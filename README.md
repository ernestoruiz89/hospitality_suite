# Hospitality Suite 0.8.9

Aplicación de alojamiento para **Hotel, Por tiempo y operación Mixta** sobre Frappe/ERPNext. Incluye once Pages para recepción, reservas, estancias, caja, limpieza, mantenimiento, servicios/inventario, huéspedes, gerencia y configuración; nueve roles y 35 DocTypes HS. Los documentos estándar de ERPNext son la autoridad contable y de inventario.

El alcance obligatorio del adjunto está contrastado en las **218 entradas** de la [matriz](docs/AUDITORIA_ESPECIFICACION.md), con [cotejo individual](docs/COTEJO_FINAL.md). La sincronización real con Airbnb/Booking sigue aplazada por instrucción del usuario. Las demás integraciones externas son contratos/adaptadores de referencia con pruebas simuladas, sin proveedores activos.

## Probar el sitio ya instalado en WSL

Desde PowerShell en este repositorio:

```powershell
.\tools\start_local_hotel.ps1
```

Abra [Reservas](http://hospitality.localhost:8086/desk/hospitality-suite/hospitality-reservations). El lanzador restablece solo los alias locales nombrados, reutiliza procesos gestionados y comprueba HTTP 200/pong dentro de WSL. No instala ni reinicia la demostración. Las cuentas por rol permanecen en `sites/hospitality.localhost/private/hospitality-demo-users.json` del bench, fuera de Git/paquetes. [Entrega y artefactos](docs/ENTREGA_FINAL.md).

## Entorno acreditado

Frappe **16.52.0**, ERPNext **16.51.1**, Python **3.14.6**, Node **24.18.0**, MariaDB **10.11.14**, Ubuntu 24.04/WSL2; commits y rutas en [la evidencia de entorno](docs/evidence/f26-candidate-environment.json). Otras versiones no están acreditadas. HRMS es opcional y no estaba instalado. PDF requiere `wkhtmltopdf` con Qt parcheado; un renderer incompatible se rechaza con un error claro.

La app declara sus dependencias Bench en `pyproject.toml`, usa JS/CSS y controles nativos de Frappe, y no modifica el núcleo. [Arquitectura y decisiones](docs/ARQUITECTURA.md).

## Instalación con Bench

Use un bench de desarrollo/pruebas con las versiones anteriores de Frappe y ERPNext instaladas. Obtenga un clon del repositorio Git local de este proyecto; el archivo de repositorio tar.gz es un archivo fuente sin historial Git.

```sh
bench get-app hospitality_suite /ruta/al/repositorio-git
bench new-site hotel.localhost --install-app erpnext
bench --site hotel.localhost install-app hospitality_suite
bench --site hotel.localhost migrate
bench build --app hospitality_suite
```

Si el sitio ya existe con ERPNext, omita `new-site`. Inicie los procesos de desarrollo con `bench start` y abra la Page `hospitality-home`. La instalación no crea compañía, habitaciones ni operaciones ficticias: complete primero el asistente nativo de ERPNext y cree el primer establecimiento desde Inicio. Configure modalidad/zona/moneda/fecha/corte, habitaciones/categorías/tarifas, impuestos, cuentas/centros de costo/almacenes, medios de pago, políticas, series/formatos y usuarios antes de habilitar operaciones financieras.

Recepción y Caja tienen permisos separados; una misma persona puede reservar y cobrar con ambos roles explícitamente asignados a su sede. Limpieza no recibe inspección o permisos financieros por defecto. La marca comercial y las políticas se configuran por establecimiento.

## Demostración explícita

Solo en un sitio de pruebas designado:

```sh
bench --site hotel.localhost set-config allow_tests true
bench --site hotel.localhost set-config hospitality_allow_demo true
bench --site hotel.localhost execute hospitality_suite.demo.seed
bench --site hotel.localhost execute hospitality_suite.demo_scenario.build
```

Se crean dos establecimientos ficticios de diez habitaciones, tarifas, huéspedes, stock y usuarios por rol. El escenario añade reservas, estancias y consumos mediante documentos estándar, sin cobros. Repetir conserva las referencias y el trabajo posterior; rechaza datos ajenos al primer escenario. Las contraseñas quedan en el archivo privado del sitio, modo 600. [Alcance y aceptación](docs/ACEPTACION_Y_DEMOSTRACION.md). No reutilice la demostración ocupada como sitio vacío de integración.

## Construcción, migración y pruebas

Los JSON nativos están versionados. Si cambia `schema.py` o una plantilla de impresión, genere los metadatos con `python3 tools/generate_schema.py`, ejecute `bench --site hotel.localhost migrate` y `bench build --app hospitality_suite`. Para actualizar/restaurar una instalación, siga [OPERACION.md](docs/OPERACION.md); volver solo al código anterior no restaura base ni archivos.

La batería nativa exige un sitio desechable sin operaciones, Redis disponible y designación explícita. Instale la dependencia de pruebas y pause el scheduler antes de preparar ese sitio:

```sh
bench pip install -e "apps/hospitality_suite[test]"
bench --site hotel-test.localhost set-config allow_tests true
bench --site hotel-test.localhost set-config hospitality_integration_test_site true
bench --site hotel-test.localhost set-config pause_scheduler true
bench --site hotel-test.localhost run-tests --app hospitality_suite --junit-xml-output /ruta/pruebas.xml
```

`before_tests` valida la protección y carga explícitamente el fixture. Frappe 16 produce dos documentos XML, integración y unitarias; consérvelos y normalice con `python3 tools/normalize_junit.py /ruta/pruebas.xml /ruta/pruebas-normalizadas.xml` desde el repositorio. Revise casos/fallos/errores/omisiones además del código de salida.

Las pruebas JS sin servidor se ejecutan desde el repositorio con:

```sh
HOSPITALITY_FRAPPE_ROOT=/ruta/al/bench/apps/frappe node tools/run_ui_tests.cjs
```

Última batería: **410 nativas (378 integración/32 unitarias) y 232 JS (229 Desk/tres portal)**, sin fallos ni omisiones, desde el Python/clon del bench independiente sobre 0.8.9. [JUnit](docs/evidence/final-recovery-native-tests.xml), [recibo](docs/evidence/final-recovery-native-run.json), [JS](docs/evidence/f26-js-run.json). El transporte, las carreras reales, el worker y los recorridos GUI están documentados por separado; no se presentan los 232 casos JS como pruebas de navegador.

Los helpers de concurrencia requieren sitio de integración designado, scheduler pausado y respaldo. Usan conexiones/commits reales y dejan anulaciones auditadas; no se ejecutan sobre un cliente con operaciones. [Ensayo de instalación y recuperación](docs/ACTUALIZACION_Y_RECUPERACION_FINAL.md).

## Guías, alcance e integraciones

- [Entrega y artefactos](docs/ENTREGA_FINAL.md).
- [Manual por rol](docs/MANUAL.md), [contabilidad/conciliación](docs/CONTABILIDAD.md) y [operación/respaldos](docs/OPERACION.md).
- [Modelo, estados y flujos](docs/MODELO_ESTADOS_Y_FLUJOS.md) y [API](docs/API.md).
- [Funciones completadas, límites e integraciones externas](docs/ESTADO_Y_EVIDENCIAS_ENTREGA.md).
- [Historial de fases](docs/AVANCE.md); sus recuentos/versiones son antecedentes, no el estado vigente.

Los proveedores de pagos, correo/WhatsApp y cerraduras requieren selección, documentación, credenciales y aceptación específica antes de operar. Ninguna simulación contabiliza pagos ni confirma entregas/aperturas físicas. [Contratos](docs/CONTRATOS_PROVEEDORES.md). No se habilita sincronización real de canales. La entrega se verifica en desarrollo/pruebas y no certifica configuraciones o proveedores distintos del entorno acreditado.
