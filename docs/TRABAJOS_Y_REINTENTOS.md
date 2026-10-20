# Caducidad y reintentos limitados — 0.6.8

El scheduler despacha la caducidad de retenciones cada cinco minutos, con un trabajo deduplicado por establecimiento. Dentro de ese trabajo, la aplicación hace **como máximo tres intentos**: el inicial y dos reintentos, con esperas de uno y dos segundos. Se reintentan RetryBackgroundJobError y bloqueos/esperas SQL transitorios, tanto los errores de consulta de Frappe como los códigos equivalentes del controlador de MariaDB. Un error de validación, programación o SQL no transitorio falla inmediatamente.

Cada intento bloquea y vuelve a leer el establecimiento, las reservas y las solicitudes del portal. Antes de reintentar se revierte la transacción completa, incluidos sus callbacks de notificación. La caducidad cancela la retención de reserva o expira la solicitud del portal y libera sus asignaciones una sola vez; no crea facturas ni cobros. Al agotar intentos se emite ExpiryExecutionError para que Frappe revierta y registre el fallo en Error Log y RQ, sin volver a entrar en su reintento recursivo. El usuario y el contexto del trabajo se conservan.

El límite corresponde a una ejecución. Un nuevo despacho periódico, después de finalizar o fallar la anterior, examina las retenciones todavía vencidas con un nuevo presupuesto. No equivale a prolongar los reintentos del trabajo anterior. La clave estable evita duplicados mientras está en cola o ejecutándose; el bloqueo y la lectura actual mantienen la idempotencia aunque se solicite otra ejecución.

## Diferencia encontrada en la versión disponible

El código de Frappe 16.52.0 declara hasta cinco reintentos internos, pero el primer ensayo real terminó con `AttributeError: job` en el finally recursivo: las tres invocaciones habían terminado cancelando la reserva y expirando el portal, mientras RQ marcó el trabajo fallido. `background-jobs-native-retry-diagnostic.json` conserva el diagnóstico histórico, descartado como aceptación. Además, database.sql transforma deadlock/timeout a excepciones QueryDeadlockError/QueryTimeoutError que no cubre ese except nativo. La aplicación intercepta esos casos antes de que el ejecutor reinicialice su contexto; los núcleos no se modificaron.

## Verificación con el worker real

`hospitality_suite.tests.worker_retries.verify` está limitado a hospitality-acceptance.localhost, su base designada, scheduler pausado, Administrator y un respaldo previo de esta fase. No está expuesto como RPC ni está enlazado al scheduler. Crea fixtures explícitos por API; no presenta esas operaciones como navegación. Inyecta errores después de ejecutar la caducidad real y programar su notificación, antes de confirmar la transacción. Las clases/códigos de bloqueo son errores sintéticos inyectados, no una prueba nueva de contención entre dos conexiones.

| Escenario | Intentos del mismo trabajo | Resultado |
|---|---:|---|
| RetryBackgroundJobError dos veces | 3 | Termina correctamente; una solicitud duplicada mientras corre no encola otro trabajo |
| QueryDeadlockError una vez | 2 | Termina correctamente |
| Error 1213 del controlador una vez | 2 | Termina correctamente |
| QueryTimeoutError persistente | 3 | Fallo acotado, retenciones y asignaciones intactas, Error Log y traceback RQ |
| Error SQL no transitorio | 1 | Fallo sin reintentos, registros nativos conservados |
| RuntimeError no transitorio | 1 | Fallo sin reintentos, registros nativos conservados |

En cada invocación, reserva y portal comienzan retenidos, con dos asignaciones activas y cero eventos de caducidad; actor Administrator e id RQ se mantienen. Los tres casos fallidos se recuperan después mediante otro trabajo real sin el fallo inyectado. Cada recuperación libera dos asignaciones y crea exactamente dos eventos. Repetir la caducidad devuelve cero y no añade eventos. `background-jobs-worker.json` compara 72 tablas: 64 idénticas y ocho tablas de fixture modificadas; finanzas, stock y huéspedes previos no cambian. La deduplicación concurrente se comprobó en el primer escenario; el campo false de los demás significa que no se solicitó ese chequeo allí.

El primer pase de la corrección superó los reintentos y encontró un error en el verificador: el id del trabajo está en Error Log.metadata, no necesariamente en el texto error. Se corrigió esa búsqueda, se restauró el respaldo original y el recorrido final de seis escenarios aprobó. Los diagnósticos no sustituyen ese pase final.

Dos casos adicionales de la batería nativa comprueban la liberación aislada por establecimiento y los extremos de caducidad: un segundo antes, el instante exacto y un segundo después. La batería conjunta aprobó **286 casos (272 integración y 14 puros), cero errores/fallos/omisiones**; background-jobs-native-tests.log/xml conserva el pase. Tras restaurar el respaldo con archivos y ejecutar esa batería, aceptación conserva 71 tablas/185 filas y 72/195 con Version; principal conserva 72/1191, dos archivos privados y fecha operativa 19/10. HTTP 200, servicios 8086/9001/Redis activos, 8089 apagado y núcleos limpios. Los archivos background-jobs-upgrade/ux-restored/final-state.json conservan los controles posteriores; el formato conciso coincide en ambos sitios bajo 0.6.8. La interfaz JavaScript es idéntica a 0.6.7; sus 71 pruebas y las capturas 141–147 se conservan como evidencia de esa revisión, sin declararlas un recorrido nuevo de 0.6.8.

## Recuperación operativa

Administración técnica revisa RQ Job / Failed Jobs y Error Log, con el id del trabajo y el establecimiento de su metadata. Conserve el traceback antes de reencolar o de un nuevo despacho: Frappe puede reemplazar el registro RQ de una clave terminada; el Error Log SQL conserva el fallo según la retención estándar del sitio. Corrija primero la causa (bloqueo, permisos o servicio) y reencole el trabajo por los controles estándar. El scheduler también vuelve a examinar retenciones vencidas en su siguiente despacho. Compruebe que el trabajo termina y que el cupo/asignaciones quedan liberados; no cambie estados de Allocation ni documentos financieros manualmente.

La eliminación de archivos de retención mantiene su política propia de tres intentos por HS Retention Run, ya acreditada en test_privacy. Gerencia puede recuperar una ejecución Failed con motivo tras corregir la causa. Si el worker falló por base de datos antes de guardar Failed y el outbox conserva Pending, administración técnica reencola el job fallido estándar; no edita intentos ni rutas directamente. OPERACION.md conserva los límites de archivos, aprobaciones y almacenamiento.

Esta fase no cambia esquema, assets de interfaz ni formatos. La restauración de aceptación, reinicio de procesos y comparación de tablas/archivos son comprobaciones de conservación de la fase; no sustituyen la recuperación final de F26. S06-08/S16-10 pasan de I a V: **135 V, 15 I, 0 P y 68 R** de las mismas 218 entradas/huella. Las 83 sin cierre continúan pendientes. La sincronización externa sigue aplazada y el objetivo completo sigue activo.
