# Paquete e instalación limpia en WSL

Revisión del 21/10/2026, app 0.8.8. Se construye y verifica el paquete y se instala en un bench independiente del que contiene la demostración. Este ensayo acredita S18-01 y completa la instalación que faltaba en S19-02; la aceptación transversal de tareas/estados y la recuperación final F26 continúan pendientes.

## Código, dependencias y artefactos

Se añade el archivo MIT correspondiente a la licencia que ya declaraba la app, su declaración en `pyproject.toml` y la inclusión de documentación/herramientas en la distribución fuente. `tools/build_release.py` trabaja desde un commit inmutable, conserva intentos previos, genera repositorio archivado, sdist y wheel, y compara los bytes de los **332 archivos de la aplicación** en ambas distribuciones. Comprueba traducciones, datos nativos, fuentes de assets, README, licencia, herramientas y dependencias Bench; excluye entornos, sitios, credenciales y archivos ignorados.

Paquete revisado: código `3a8d0bf`, [manifiesto y hashes](evidence/release-install-package-final.json). Artefactos locales en `output/releases/3a8d0bfd2ae2/`:

- `hospitality-suite-repository.tar.gz`: repositorio archivado, sin `.git`.
- `hospitality_suite-0.8.8.tar.gz`: distribución fuente, con documentación y herramientas.
- `hospitality_suite-0.8.8-py3-none-any.whl`: paquete Python/datos. La instalación operativa se realiza con Bench y ERPNext.
- `manifest.json`: tamaños, versiones de construcción y SHA-256 de los archivos anteriores.

Los paquetes iniciales de `eb0a452` y `93b4e07` se conservan con [su primer manifiesto](evidence/release-install-package.json) y [el intermedio](evidence/release-install-package-current.json). El código de negocio, metadatos y frontend no cambian desde la instalación inicial `eb0a452`: las cuatro diferencias dentro de la app son exclusivamente preparación y protección de pruebas. La [comparación de entorno y archivos](evidence/release-install-environment.json) vincula el paquete final con la app que ejecutó las pruebas. Los registros de revisión añadidos después del corte del paquete permanecen en el repositorio actual.

Se usa un entorno de construcción separado: build 1.6.1 y flit_core 3.12.0. La licencia se valida mediante `License-File` y sus bytes, conforme a los metadatos emitidos por Flit; el primer chequeo esperaba el texto dentro de METADATA y se corrigió sin sustituir sus artefactos.

## Instalación realmente ejecutada

Bench: `/home/frappe/.hospitality-release-install/benches/hospitality-release-bench`. Sitio/base: `hospitality-release.localhost` / `hospitality_release`. Python, clones de Frappe/ERPNext/PMS, assets, Redis 11003/13003 y base son propios de ese bench. Comparten el sistema WSL, el servicio MariaDB y el binario PDF del host, como dependencia declarada. No se reutiliza el Python ni el código editable del bench principal.

Versiones comprobadas: Frappe 16.52.0 (`4515014`), ERPNext 16.51.1 (`5af6561`), Python 3.14.6, Node 24.18.0 y MariaDB 10.11.14. Dependencias Python instaladas y rutas reales se registran en [entorno](evidence/release-install-environment.json); HRMS está ausente. Los contratos de proveedores permanecen sin activar y OTA sigue aplazada.

Se ejecutan init/get-app, instalación ERPNext en sitio nuevo, instalación del PMS, migrate y construcción completa de assets. La [comprobación inicial](evidence/release-install-clean.json) verifica **35 DocTypes, once Pages, nueve roles, nueve formatos, seis patches y 28 métodos API**, controladores, campos y permisos contra sus fuentes. Todas las tablas de negocio revisadas están vacías, incluidas Company, Item, movimientos y todos los documentos HS. Bootstrap ofrece las once páginas y la creación del primer establecimiento. Instalar no carga demostración.

El primer init falló porque Bench comparaba puertos de tipos distintos en benches vecinos. Se conservó ese directorio sin sitios ni apps en `failed-init-bench` y se creó el bench en un padre privado; no se modificaron los vecinos. [Intento](evidence/release-install-init.json), [init corregido](evidence/release-install-init-isolated-parent.json), [ERPNext](evidence/release-install-get-erpnext.json), [sitio](evidence/release-install-create-site.json), [app](evidence/release-install-install-app.json), [migración](evidence/release-install-migrate.json), [construcción](evidence/release-install-build.json).

## Primer arranque desde la interfaz

ERPNext abre primero su asistente nativo: [captura](evidence/356-instalacion-primer-arranque.png), [lectura](evidence/release-install-first-boot.json). Se completa explícitamente con español, Nicaragua, America/Managua, NIO, una cuenta ficticia y la compañía «Instalación PMS», sin activar demostración. Las credenciales se conservan privadas.

Después, Inicio del PMS muestra «Prepare su primer establecimiento» y «Crear establecimiento»: [captura](evidence/357-instalacion-pms-vacio.png). Ese diálogo permite crear «Hotel de instalación» con la compañía anterior, modalidad Hotel, NIO y fecha local; se abre el tablero sin habitaciones ni operaciones. [Captura](evidence/358-instalacion-primer-hotel.png), [traza](evidence/release-install-setup-browser.json), [estado SQL](evidence/release-install-state-setup.json). Se observa tiempo real conectado. Compilación del bench independiente: `DWFPEU45`, contrastada con su manifiesto local de assets. Este recorrido corresponde a Administrator y primer establecimiento; no se presenta como aceptación completa por rol, móvil o de todas las acciones.

Un respaldo con archivos, tomado antes del asistente, permite volver al estado vacío antes de la batería: [respaldo](evidence/release-install-backup-clean.json), [restauración](evidence/release-install-restore-clean-sites.json), [migrate posterior](evidence/release-install-migrate-restored.json), [cero documentos de negocio](evidence/release-install-state-restored.json). El primer comando del helper usó un directorio de trabajo incorrecto y falló antes de conectar a la base; [se conserva](evidence/release-install-restore-clean.json). Las configuraciones y contraseñas no salen del directorio privado.

## Regresión y concurrencia

**404 nativas aprobadas: 372 de integración y 32 puras, sin fallos, errores ni omisiones.** Se ejecutan desde el Python y la app clonados del bench nuevo: [JUnit completo](evidence/release-install-native-tests.xml), [salida](evidence/release-install-native-tests.log), [recibo de ejecución](evidence/release-install-native-run.json). El código ejecutado es `be67c92`; todos sus archivos de app coinciden con el paquete `3a8d0bf`. También pasan **215 JS**, ejecutadas desde el clon en `93b4e07`: [salida](evidence/release-install-js-tests.log). Las modificaciones posteriores afectan solo pruebas Python, README y herramientas; no se atribuye otra ejecución JS después de ellas.

El primer pase nativo tuvo **siete fallos**, conservados en [JUnit](evidence/release-install-native-first-attempt.xml) y [salida](evidence/release-install-native-first-attempt.log). Seis escenarios de impresión fijaban el nombre del sitio de aceptación y otro suponía que la demostración conservaba un artículo compartido antiguo. Se usa ahora la misma protección de sitio explícito en los helpers y el caso antiguo prepara ese artículo antes de comprobarlo. Las verificaciones originales se mantienen; no se omiten casos ni se cambia el negocio para acomodar las pruebas.

El helper de concurrencia también apuntaba al sitio principal. Ahora requiere un sitio de integración designado, `.localhost` o de pruebas, scheduler pausado y ausencia de operaciones/reservas ajenas al ensayo. [Rechazo final del principal](evidence/release-install-concurrency-guard-final.json); el [rechazo intermedio](evidence/release-install-concurrency-guard.json) conserva el guard anterior.

Se ejecutan aparte dos carreras reales, cada una con dos sesiones DB y barrera de inicio: [misma habitación](evidence/release-install-concurrency-room.json), [último cupo de categoría](evidence/release-install-concurrency-category.json). En cada caso se confirma una solicitud y se rechaza otra. Las reservas se cancelan por la API con auditoría y commit, sin asignaciones activas restantes. El [estado final de esa base](evidence/release-install-state-after-concurrency.json) contiene dos establecimientos, veinte habitaciones, tres reservas sintéticas canceladas y ningún movimiento de estancia, cargo, cobro, turno o factura. Una apertura de stock y sus dos apuntes GL pertenecen a la carga explícita del generador, que utiliza una compañía para ambas propiedades; no se atribuyen a la instalación. Los primeros chequeos de estado se corrigieron para reconocer esa preparación real.

## Conservación y siguiente trabajo

WSL se reinició durante el ensayo. Se revalidó el estado, se restablecieron solo los procesos gestionados y los alias necesarios, y se mantuvieron los registros previos. La demostración volvió a cargar autenticada como Recepción con tiempo real conectado: [lectura](evidence/release-install-main-browser.json). La comparación estricta mantiene el principal en **72 tablas/1246 filas/dos archivos privados** y aceptación en **72/250**, sin cambios en sus datos: [comparación](evidence/release-install-upgrade.json). Los servicios temporales del bench nuevo se detienen al terminar; el sitio y sus respaldos se conservan para el ensayo final. [Estado de servicios](evidence/release-install-final-state.json).

S18-01 y S19-02 pasan a V con [verificación de alcance](evidence/release-install-verification.json). La matriz conserva las **218 entradas y su huella: 210 V y ocho I**. Permanecen S00-01/S00-02/S01-12/S04-14/S04-16/S04-20/S19-07/S19-08: aceptación de tareas/estados y cierre integral, con recuperación coordinada de código, base y archivos F26. Restaurar el estado vacío y actualizar helpers de pruebas no sustituye ese ensayo final. El objetivo sigue activo; OTA permanece aplazada y no se declara aptitud para producción.
