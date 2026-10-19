# Operación técnica

## Procesos y salud

En el sitio de pruebas de esta tarea, `tools/run_dev.py` arranca web 8086, Socket.IO 9001, worker para short/default/long y scheduler, con Redis propios 13001/11001. Comprueba procesos/puertos para no duplicarlos y no interrumpe un puerto ya activo. Los registros están en `/home/frappe/benches/hospitality-bench/.hospitality-run`.

Es un servidor de desarrollo local. Para un despliegue definitivo use la administración de procesos, proxy, HTTPS y configuración de Bench correspondiente al sistema de destino; no copie este arranque como servicio público de producción.

Compruebe:

```sh
bench --site hospitality.localhost list-apps
bench --site hospitality.localhost doctor
bench --site hospitality.localhost show-pending-jobs
```

Verifique la respuesta de recepción, una consulta de disponibilidad, estado de worker/scheduler y conectividad Socket.IO. Una interfaz que solo carga no acredita salud de pagos ni de tareas programadas.

## Retenciones y trabajos

El scheduler despacha por establecimiento cada cinco minutos. Cada job bloquea el establecimiento y libera retenciones vencidas de reservas y portal con auditoría. Su ejecución es repetible; no factura ni liquida dinero. Hay deduplicación del job por establecimiento. Los reintentos transitorios limitados de Frappe no sustituyen la revisión de fallos de negocio.

Ante un fallo, conserve Failed Job Log y el traceback, corrija la causa y vuelva a ejecutar la operación o su job por los mecanismos estándar. No marque manualmente como pagado ni cambie Allocation para eludir un bloqueo. Una ejecución posterior vuelve a examinar el estado real y no debe duplicar la liberación.

Se verificó ejecución real de expire_property por el worker. El ensayo explícito de fallo/reintento y la reconexión entre sesiones siguen pendientes en la matriz.

## Respaldo

Desde el bench y con los permisos del sitio:

```sh
bench --site hotel.localhost backup --with-files
```

Conserve el SQL comprimido, archivos públicos/privados y configuración necesaria del sitio, incluida su clave de cifrado, en almacenamiento protegido fuera del mismo equipo. Las copias contienen datos personales, contables y credenciales técnicas; no deben incluirse en Git ni distribuirse como demostración.

Registre fecha, sitio, versiones de apps y commit de hospitality_suite. Verifique tamaño/hash y pruebe una restauración en un destino separado. Un archivo de respaldo existente no prueba que se pueda restaurar.

## Restauración en un destino separado

Prepare un sitio de pruebas con versiones compatibles y aplicaciones instaladas, y use la restauración estándar de Bench:

```sh
bench --site destino-de-pruebas.localhost restore /ruta/database.sql.gz \
  --with-public-files /ruta/public-files.tar \
  --with-private-files /ruta/private-files.tar
bench --site destino-de-pruebas.localhost migrate
bench build --app hospitality_suite
```

La restauración reemplaza datos del destino: confirme su identidad y respaldo antes de ejecutarla. Proporcione las credenciales de base por el mecanismo de administración del entorno; no las escriba en una guía, historial compartido o repositorio. Preserve la clave de cifrado del origen sin sustituir la identidad/conexión del destino por accidente.

Valide cantidades de establecimientos/habitaciones/reservas, snapshots de tarifas, vínculos de facturas y pagos, archivos privados, cuentas por cobrar y saldos de stock. Ejecute pruebas de lectura y un recorrido ficticio en el destino. El ensayo de restauración final aún debe quedar acreditado en la matriz.

## Actualización y reversión de despliegue

1. Registre las versiones y haga respaldo completo.
2. Ensaye el commit nuevo sobre una copia restaurada; ejecute migrate, build y pruebas apropiadas.
3. Planifique la ventana, controle trabajos en curso y despliegue mediante el administrador de procesos del entorno.
4. Migre el sitio, compile assets y verifique salud, roles, conciliación y un recorrido autorizado.
5. Si falla antes de operar con datos nuevos, restaure respaldo y código compatible en el destino controlado. Volver solo a un commit anterior no revierte una migración de base.
6. Si ya hubo operaciones, preserve el estado nuevo y los registros antes de decidir una restauración; una reversión de código puede necesitar una migración correctiva. No descarte facturas/cobros nuevos mediante un rollback de base sin conciliarlos.

Los patches de la app reconstruyen referencias de líneas y snapshots de asignaciones anteriores, sin reescribir importes contabilizados. Conserve sus registros de ejecución y repita migrate para verificar idempotencia.

## Seguridad y monitoreo

- Conceda roles HS más HS Access por compañía/establecimiento. Los roles ERPNext adicionales deben asignarse explícitamente; compruebe su alcance antes de usarlos.
- Los archivos personales deben ser privados y vinculados a documentos autorizados. Configure la política de datos personales de la implementación; no existe una purga automática acreditada por el solo campo retention_days.
- Revise diferencias de caja, conciliación, documentos anulados, autorizaciones, bloqueos y jobs fallidos. No use ajustes automáticos para ocultar una diferencia.
- Las notificaciones de la app invalidan solo el establecimiento y se envían por usuario autorizado. Los documentos estándar evitan difusión global de sus nombres; la prueba del transporte entre sesiones continúa en la matriz.
- Proteja site_config, claves de cifrado y secretos de proveedores fuera del repositorio. El portal está desactivado por defecto; los adaptadores no reciben credenciales reales durante la demostración.
