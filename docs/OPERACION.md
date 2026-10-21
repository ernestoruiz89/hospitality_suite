# Operación técnica

## Procesos y salud

En el sitio de pruebas de esta tarea, `tools/run_dev.py` arranca web 8086, Socket.IO 9001, worker para short/default/long y scheduler, con Redis propios 13001/11001. Comprueba procesos/puertos para no duplicarlos y no interrumpe un puerto ya activo. Los registros están en `/home/frappe/benches/hospitality-bench/.hospitality-run`.

El arranque directo de web incluye `DEV_SERVER=true`, como normalmente hace `bench start`. Sin esa variable, Desk intenta Socket.IO sobre el puerto web esperando un proxy productivo y sus consultas fallan. Se comprobó `window.dev_server=1`, puerto 9001 y conexión autenticada en Page. Después de cambiar Python use `--restart-web`: el proceso de pruebas utiliza `--noreload`. No se alteran archivos del núcleo para resolverlo.

Para los nombres `hospitality.localhost` y `hospitality-acceptance.localhost`, configure también su resolución a `127.0.0.1` dentro de WSL con el comando de `configure_local_hosts.py` del README. El reconocimiento automático de estos nombres por el navegador no basta: el middleware nativo autentica mediante una petición HTTP desde Node al origen del navegador. El helper conserva las líneas existentes, rechaza conflictos y solo añade estos dos alias. WSL puede regenerar hosts al reiniciar; el arranque comprueba esta condición sin cambiar la configuración general de WSL ni el núcleo de Frappe.

Se corrigió y verificó el fallo `ENOTFOUND` con ambos orígenes, cinco conexiones autenticadas, aislamiento y transacciones reales. Las Pages reciben automáticamente los cambios mientras están conectadas. Después de un corte largo que agote los tres reintentos nativos, muestran «Sin tiempo real · pulse Actualizar»: esa acción reconecta y recupera los cambios mediante bootstrap. [Alcance, recorrido y evidencia](TIEMPO_REAL_SITIOS_LOCALES.md). Esta recuperación explícita no se presenta como reconexión automática indefinida.

Es un servidor de desarrollo local. Para un despliegue definitivo use la administración de procesos, proxy, HTTPS y configuración de Bench correspondiente al sistema de destino; no copie este arranque como servicio público de producción.

## Motor PDF del bench de pruebas

Los PDF requieren wkhtmltopdf con Qt parcheado. El paquete del sistema WSL era 0.12.6 sin esas funciones: una exportación extensa podía partir filas y omitir encabezados. Se extrajo el [paquete oficial 0.12.6.1-3 de Jammy amd64](https://github.com/wkhtmltopdf/packaging/releases/tag/0.12.6.1-3), comprobado en este Ubuntu 24.04, únicamente en `.runtime/wkhtmltox` del bench. No sustituye `/usr/bin/wkhtmltopdf` ni cambia otro bench. El instalador verifica SHA-256 fijado, dependencias y la salida with patched qt, y limpia solo la caché de detección de estos sitios sintéticos.

```sh
/home/frappe/benches/hospitality-bench/env/bin/python /mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/tools/bootstrap_pdf_runtime.py
/home/frappe/benches/hospitality-bench/env/bin/python /mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/tools/run_dev.py --restart-web --restart-worker
```

run_dev y el servidor temporal de restauración anteponen ese directorio a PATH de sus procesos. Los helpers de impresión también lo seleccionan. Para otros comandos CLI de impresión, anteponga `/home/frappe/benches/hospitality-bench/.runtime/wkhtmltox/usr/local/bin` al PATH de esa sesión. Una instalación externa debe proporcionar su propio runtime compatible. La API de exportación rechaza un motor incompatible y conserva el escape de valores y las restricciones nativas de JavaScript/archivos locales.

Se verificaron los 142 registros de un PDF de 18 páginas por función y HTTP, con encabezado y pie por página; se revisaron las 18 páginas y diez comprobantes regenerados. La tabla de exportación tiene columnas de ancho contenido y ajuste de palabras para evitar desbordamiento con smart shrinking desactivado. Los respaldos SQL/archivos no incluyen este binario del sistema: preserve también la configuración y las versiones/dependencias del despliegue.

Compruebe:

```sh
bench --site hospitality.localhost list-apps
bench --site hospitality.localhost doctor
bench --site hospitality.localhost show-pending-jobs
```

Verifique la respuesta de recepción, una consulta de disponibilidad, estado de worker/scheduler y conectividad Socket.IO. Una interfaz que solo carga no acredita salud de pagos ni de tareas programadas.

## Retenciones y trabajos

El scheduler despacha por establecimiento cada cinco minutos. Cada job bloquea el establecimiento y libera retenciones vencidas de reservas y portal con auditoría. Su ejecución es repetible; no factura ni liquida dinero. Hay deduplicación por establecimiento. Desde 0.6.8, la aplicación limita el mismo trabajo a tres intentos para errores transitorios, con rollback completo y esperas de uno/dos segundos; los errores no transitorios fallan inmediatamente. TRABAJOS_Y_REINTENTOS.md documenta la diferencia detectada en el reintento nativo de Frappe 16.52 y las pruebas con el worker real.

Ante un fallo, revise RQ Job / Failed Jobs y Error Log con su metadata de trabajo/establecimiento. Conserve el traceback antes de reencolar o de un nuevo despacho periódico, que puede reemplazar la entrada RQ de la misma clave; Error Log SQL conserva el fallo según la retención estándar. Corrija la causa y reencole el job mediante los controles estándar. Un nuevo despacho cada cinco minutos tiene un presupuesto propio; no prolonga los reintentos del anterior. Compruebe finalización y cupo liberado. No marque manualmente como pagado ni cambie Allocation para eludir un bloqueo. Una ejecución posterior vuelve a examinar el estado real y no duplica la liberación.

Se verificaron seis escenarios del worker real: recuperaciones transitorias, agotamiento, fallos no transitorios, rollback, logs y recuperación, con reserva y portal. Las clases de bloqueo se inyectaron después de caducar datos reales; no se presenta como una nueva carrera de dos conexiones. La propagación entre sesiones, aislamiento y reconexión bajo corte conservan su evidencia anterior.

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

El responsable del despliegue debe identificar bench, sitio y base antes de ejecutar estos ejemplos. Sustituya `hotel.localhost` por ese destino confirmado. Registre también qué procesos lo sirven y si el scheduler estaba habilitado; una sede de recuperación puede requerir que siga pausado.

1. Conserve los commits de Frappe, ERPNext y Hospitality, versiones de Python/Node y dependencias, configuración del administrador de procesos, runtime PDF y estado inicial de salud. `list-apps` muestra la versión registrada por la última migración; contrástela con el código y commit que se va a ejecutar. Preserve cambios locales antes de sustituir código.
2. Ensaye primero el commit exacto sobre una copia restaurada: instalación de sus dependencias, migración, construcción, pruebas y un recorrido autorizado por roles. Compare datos, documentos nativos y archivos privados con el respaldo. Este ensayo no utiliza la sede operativa como batería de integración.
3. Durante la ventana, ponga el sitio en mantenimiento, evite nuevos despachos del scheduler y deje terminar los trabajos en curso. `disable-scheduler` no detiene un job ya iniciado. Examine colas, trabajos en ejecución/fallidos y logs; coordine después la parada de workers con el administrador de procesos de ese bench.

```sh
bench --site hotel.localhost set-maintenance-mode on
bench --site hotel.localhost disable-scheduler
bench --site hotel.localhost show-pending-jobs
bench --site hotel.localhost backup --with-files
```

4. Verifique y copie fuera del equipo el SQL, archivos públicos/privados, configuración y clave de cifrado del mismo punto. Registre sus hashes y los commits anteriores. Despliegue el código/dependencias ensayados; migre y construya antes de reiniciar web, workers y Socket.IO con su administrador de procesos configurado. No cambie de versión del núcleo de forma implícita al actualizar solo esta app.

```sh
bench --site hotel.localhost migrate
bench build --app hospitality_suite
bench --site hotel.localhost clear-cache
```

5. Compruebe versiones registradas/código, `doctor`, colas, HTTP, Socket.IO, permisos por sede, archivos privados, conciliación de facturas/pagos/stock y las tareas acordadas. Habilite el scheduler solamente si estaba habilitado antes y retire mantenimiento cuando la revisión permita reabrir la operación.

```sh
bench --site hotel.localhost enable-scheduler
bench --site hotel.localhost set-maintenance-mode off
```

6. Si el despliegue falla, mantenga el destino cerrado y conserve estado/logs de la falla. Antes de restaurar compruebe si hubo reservas, facturas, pagos, stock o trabajos nuevos. Si no hubo actividad nueva, restaure en el destino controlado el SQL y archivos del mismo respaldo, su clave y el conjunto compatible de código/dependencias anteriores; utilice el comando de restauración descrito arriba. Verifique identidad/conexión del destino, migre con ese código, reconstruya y reinicie sus procesos. Repita las comparaciones y el recorrido antes de reabrir. Volver solo al commit anterior no revierte la base ni sus archivos.
7. Si hubo actividad nueva, preserve un respaldo del estado posterior y concilie sus documentos antes de decidir la recuperación. Puede ser necesaria una corrección hacia delante o una recuperación asistida; una restauración antigua descartaría movimientos válidos. El responsable debe resolver ese alcance antes de reabrir y conservar la evidencia de ambos puntos.

Los patches de la app reconstruyen referencias de líneas y snapshots de asignaciones anteriores, sin reescribir importes contabilizados. Conserve sus registros de ejecución y repita migrate para verificar idempotencia.

Esta sección entrega el procedimiento. Las restauraciones históricas y las restauraciones del sitio sintético durante desarrollo no sustituyen el ensayo final de despliegue/reversión de la versión a entregar; F26/S19-07 conservan esa verificación pendiente.

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

## Ensayo histórico de catálogo extenso

El ensayo anterior de `tools/catalog_preview.py` creó 606 Item ficticios en hospitality-clean.localhost, sin stock ni movimientos financieros. Ese sitio está ahora en cuarentena y conserva respaldo de diagnóstico: esta descripción es evidencia histórica, no una instrucción para volver a prepararlo o arrancarlo. Las revisiones actuales usan hospitality-acceptance.localhost, su respaldo inicial y los helpers acotados de la fase documentada. 8089 es temporal y se detiene antes de restaurar; 8086 pertenece a la demostración principal.

El caso histórico seleccionó Servicio especial del catálogo / HS-CATALOG-QA-0605 sin enviar un consumo; el precio/entrega con un catálogo grande se comprobó en integración con rollback. Las credenciales de pruebas permanecen privadas. La vista temporal no configura un segundo Socket.IO; ese transporte conserva su prueba independiente en el sitio principal.
