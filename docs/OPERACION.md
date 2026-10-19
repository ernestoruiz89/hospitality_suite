# Operación técnica

## Procesos y salud

En el sitio de pruebas de esta tarea, `tools/run_dev.py` arranca web 8086, Socket.IO 9001, worker para short/default/long y scheduler, con Redis propios 13001/11001. Comprueba procesos/puertos para no duplicarlos y no interrumpe un puerto ya activo. Los registros están en `/home/frappe/benches/hospitality-bench/.hospitality-run`.

El arranque directo de web incluye `DEV_SERVER=true`, como normalmente hace `bench start`. Sin esa variable, Desk intenta Socket.IO sobre el puerto web esperando un proxy productivo y sus consultas fallan. Se comprobó `window.dev_server=1`, puerto 9001 y conexión autenticada en Page. Después de cambiar Python use `--restart-web`: el proceso de pruebas utiliza `--noreload`. No se alteran archivos del núcleo para resolverlo.

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

Se verificaron ejecución real de expire_property, fallo con rollback y reintento posterior por el worker. La propagación entre sesiones, aislamiento y reconexión bajo corte ya se comprobaron con tráfico real.

## Retención revisada de datos sensibles

Configurar retention_days no elimina datos automáticamente. El gerente o administrador HS revisa candidatos y alcance en Gerencia, indica motivo y confirma. El límite se calcula a medianoche local del establecimiento. Se conservan huéspedes con reservas no terminadas o actividad reciente, incluidos acompañantes; mantenimiento debe estar completado y las novedades resueltas. Un adjunto nuevo o modificado recientemente impide retirar el documento.

La política actual retira identity_type, identity_number e identity_file de HS Guest y evidence de mantenimiento/novedades cerrados, junto con sus adjuntos privados locales, cambios de esos campos en Version y comentarios automáticos de adjuntos. Conserva nombres, contactos, importes, documentos contables, descripciones y comentarios libres, bitácora y respaldos. No es anonimización integral. Los respaldos deben caducar mediante la política separada de almacenamiento; restaurarlos puede recuperar información retirada y exige volver a revisar retención.

HS Retention Run conserva aprobación y conteos. El retiro de campos/metadatos y el outbox se confirman juntos; un rollback mantiene el archivo físico. El job privado se encola después del commit como Administrator, conservando la identidad del aprobador en la ejecución. Nunca lo exponga como RPC. Comprueba referencias compartidas antes de eliminar y limpia rutas/hash al terminar. Los archivos compartidos se conservan para el otro documento. Si falla, mantiene el outbox privado y hace como máximo tres intentos automáticos; Gerencia permite reintento autorizado con motivo después de corregir permisos/almacenamiento. No borre ni edite el outbox manualmente.

Tras cambiar hooks o código del worker en este bench de pruebas, use `tools/run_dev.py --restart-worker`. El script valida PID, comando y directorio antes de detener el proceso aislado. La prueba real retiró dos referencias File y sus bytes en un intento, después del commit, sin cambiar GL/Payment/Stock Ledger. `tools/verify_privacy.py` solo admite el sitio sintético y un fixture explícito desechable; la prueba de navegador revisó el alcance y el resultado, mientras la aprobación del fixture se ejecutó por el helper de desarrollo.

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

Valide cantidades de establecimientos/habitaciones/reservas, snapshots de tarifas, vínculos de facturas y pagos, archivos privados, cuentas por cobrar y saldos de stock. Ejecute pruebas de lectura y un recorrido ficticio en el destino.

Ensayo ejecutado: respaldo nativo con archivos de hospitality.localhost y restauración en hospitality-restore.localhost, base hospitality_restore. Se conservaron exactamente 52 tablas y 295 filas operativas/nativas, incluidos GL Entry, Payment Ledger Entry y Stock Ledger Entry; SHA-256 idéntico antes y después de migrate. La configuración del destino mantuvo su base y credenciales y recibió la clave de cifrado del respaldo. El scheduler del destino está pausado. `tools/restore_wsl.py` solo admite este tercer sitio aislado; reemplaza sus datos y no es un restaurador para producción. La referencia completa permanece privada en el bench; los hashes y resultados están en docs/evidence.

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
- Los archivos personales deben ser privados y vinculados a documentos autorizados. Configure y revise la política descrita arriba; el valor retention_days por sí solo no elimina datos.
- Revise diferencias de caja, conciliación, documentos anulados, autorizaciones, bloqueos y jobs fallidos. No use ajustes automáticos para ocultar una diferencia.
- Las notificaciones de la app invalidan solo el establecimiento y se envían por usuario autorizado. Los documentos estándar evitan difusión global de sus nombres; el transporte entre sesiones y la exclusión de otra propiedad están probados.
- Proteja site_config, claves de cifrado y secretos de proveedores fuera del repositorio. El portal está desactivado por defecto; los adaptadores no reciben credenciales reales durante la demostración.

## Ensayos de transporte local

`transport_probe.py prepare` crea dos usuarios ficticios con una sola propiedad cada uno; sus contraseñas quedan en un archivo privado del bench. `verify_transport.cjs` usa socket.io-client de Frappe: dos conexiones de hotel, una de motel, commit/rollback reales y desconexión de transporte. Los eventos solo invalidan property; al reconectar se consulta bootstrap porque Socket.IO no reproduce todos los eventos perdidos.

`drop_response_proxy.py` escucha únicamente 127.0.0.1:8087 y reenvía al servidor real 8086. Solo puede descartar una respuesta exitosa de direct_sale con referencia sintética UX-NET-001. No cambia controladores, importes ni el resultado del backend. Su estado privado compara hash de clave/carga y el resultado del reintento. `verify_network_sale.py` consulta factura, pago y stock nativos. No se arma dos veces automáticamente; no es middleware de despliegue. El proxy se detuvo al terminar el ensayo y el turno quedó cerrado en cero.

`cut_test_socket.py` verifica PID/comando/directorio del servicio aislado antes de detener Socket.IO. Restablezca inmediatamente con run_dev.py. Se observaron Sin tiempo real y Tiempo real conectado tras Actualizar; web/worker/scheduler siguieron activos. Las peticiones necesitan respuesta del servidor aun cuando Socket.IO está conectado. Una respuesta perdida mantiene la ventana y su referencia: reintente los mismos datos. Una recarga completa pierde la referencia en memoria; consulte documentos/saldos antes de iniciar otra operación.
