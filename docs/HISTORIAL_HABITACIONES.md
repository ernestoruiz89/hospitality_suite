# Historial de habitaciones — 0.7.8

Contraste individual de S05-04 sobre Frappe 16.52.0 / ERPNext 16.51.1. Recepción dispone de **Historial** en cada tarjeta, también si la habitación está bloqueada o inactiva. La consulta pide Desde, Hasta (sin incluir) y vista. No modifica ocupación ni sustituye los registros de origen.

## Información y fechas

Actividad reúne operaciones y períodos; Cambios de datos muestra versiones nativas y registros de creación; Estancias y bloqueos permite consultar períodos; Todo el historial combina las fuentes. Se presentan descripciones, usuario y momento. Antes/después permanece plegado y las claves internas no se imprimen en las tarjetas. Los resultados se paginan de 25 en 25; consultar otra fecha o vista invalida los resultados anteriores.

Los momentos puntuales cumplen `[desde, hasta)`; los períodos se incluyen cuando cruzan ese rango y muestran sus extremos originales. Una reserva liberada conserva sus fechas y explica que no representa ocupación actual. Un cambio de habitación conserva sus segmentos anteriores. Una estancia sin salida registrada queda abierta y explica la salida prevista; solo su último segmento utiliza la salida real, incluso si ocurrió después de la prevista. Un bloqueo hasta reapertura permanece sin extremo artificial. Al finalizarlo, el extremo histórico procede del evento de finalización, aunque después se edite la orden.

El filtro se interpreta en la zona del establecimiento mediante el conversor existente, que rechaza horas locales ambiguas o inexistentes sin desplazamiento explícito. El navegador valida fechas vacías/invertidas antes de consultar y muestra el error en la misma ventana; el servidor vuelve a validar rango, habitación, vista y página.

## Fuentes, límites y permisos

`room_history.py` reúne HS Allocation, HS Audit Event y Version para habitación, reserva, estancia, limpieza y mantenimiento. Se leen todos los lotes necesarios de 500; no se conserva el antiguo límite de 500 resultados. El usuario consulta páginas de hasta 200 por API y de 25 desde Page.

Los cambios de habitación guardados normalmente conservan una instantánea operativa antes/después, incluso cuando se omite Version. Las nuevas instantáneas de reservas conservan habitaciones con sus referencias originales y números registrados. No se amplían los permisos generales de Recepción sobre Version o Auditoría. La proyección privilegiada de esas dos fuentes solo se realiza después de autorizar el establecimiento, el rol operador y la habitación; únicamente devuelve campos operativos permitidos. Identidad, adjuntos, importes, costos y cargas arbitrarias no salen en este historial.

Frappe 16 puede guardar títulos de Links y fechas formateadas en Version. Se conservan como tales; no se interpretan títulos como identificadores arbitrarios ni fechas formateadas como ISO. Los alias de números anteriores se resuelven solo si son únicos en el establecimiento. Cuando un registro relacionado no permite reconstruir la habitación, se declara la incertidumbre; no se inventa un valor anterior. JSON antiguo mal formado recibe una explicación recuperable. Una frontera de establecimiento/compañía impide mostrar valores anteriores de la otra sede, incluso si ese traslado omitió Version; se registra la incorporación al nuevo establecimiento.

Esto acredita el historial disponible en las fuentes conservadas. No reconstruye valores que nunca fueron registrados o que se eliminaron fuera del flujo autorizado. Las modificaciones directas de base de datos no equivalen a acciones del producto.

## Pruebas y navegador

La ejecución final aprueba **365 pruebas nativas: 351 de integración y catorce puras**, con trece casos nuevos de historial. Incluyen reserva modificada/cancelada en la habitación correcta, cambio real de habitación, todas las transiciones de limpieza, renombrado sin Version, bloqueo abierto/finalizado y modificación posterior, salida tardía del último segmento, límites exactos, permisos/lectura sin escrituras, filtros inválidos, dos fronteras de establecimiento y cargas antiguas mal formadas. Una revisión posterior al navegador contrasta dos cambios reales cuando un número visible coincide con otra clave interna; el título nativo ambiguo no atribuye movimientos a la habitación equivocada y las instantáneas originales mantienen su relación. Se ejecutan otra vez los trece casos dirigidos y la batería completa tras esa corrección. La prueba de 610 Version usa inserción masiva explícita de datos históricos sintéticos para verificar ausencia de tope y duplicados; no se presenta como 610 operaciones ejecutadas por usuario. Frappe omite Version por defecto durante pruebas: los comandos de este módulo activan su comportamiento normal y las pruebas de omisión lo indican expresamente.

Pasan **136 regresiones JS: 134 de Desk y dos del portal**, diez nuevas. Comprueban escape, campos y zona, roles, carga/error/reintento, envío doble, cierre/reapertura, propiedad, edición de filtros, respuestas antiguas, contexto de respuesta, paginación con regreso a cero y validación de fechas anterior al servidor. No equivalen a recorridos completos de todos los roles.

`tools/room_history_ux.py` crea un fixture reversible mediante comandos nativos: reserva H101→H102 cancelada, estancia H103→H104, limpieza completada, bloqueo finalizado H105, abierto H106 y cambios reales de número/piso en H109A. El navegador utiliza Recepción y solo consulta. La ventana explícita del preparador cuenta 58 registros para H109A; el rango semanal de Page incluye además la creación anterior y muestra **59**, recorridos 1–25→26–50→51–59→26–50→1–25. No son el mismo intervalo.

Capturas 217–227 y `room-history-browser.json` conservan limpieza con antes/después, cancelación, validación inline/recuperación a vacío, ambos bloqueos, paginación, segundo establecimiento y cambio H103→H104. En móvil 390×844: documento de 390 px, diálogo de 374 px, controles/resumen/acción de 44 px y botón principal dentro de pantalla. Tab desde la vista alcanza el resumen; Enter abre sus valores y Escape cierra el diálogo. La tabla abierta conserva sus 304 px sin desbordar el documento. El viewport se restablece y la sesión termina en Login; la pestaña temporal se cierra.

Se corrigieron durante la revisión el error contextual «Cleaning» como consumo, la supresión predeterminada de versiones en pruebas, el rango invertido que abría otra alerta y los controles de 28 px. Los timeouts de algunos localizadores del navegador se resolvieron observando el estado y usando los controles nativos; no se alteró el producto para eludirlos. El servidor temporal muestra fallback sin tiempo real: no se acredita transporte Socket.IO.

## Conservación y alcance

`room-history-items-ui.json` comprueba que las consultas conservan idénticas las **72 tablas del fixture**, las tablas nativas y la fecha operativa. La preparación se distingue de las acciones hechas desde Page. La restauración del respaldo original con archivos, comparación de ambos sitios y comprobaciones finales se registran en `room-history-ux-restored.json`, `room-history-upgrade.json` y `room-history-final-state.json`.

La restauración conserva aceptación **71 tablas/185 filas y 72/195 con Version**, sin operaciones. Principal conserva **72 tablas/1191 filas, dos archivos privados y fecha operativa 19/10**. Se mantiene la excepción histórica limitada a cachés Company; las huellas originales no se sustituyen. Web/worker quedan actualizados, servicios/HTTP activos y 8089 apagado; núcleos limpios y PDF resumido con su huella anterior, sin nueva descarga/render.

S05-04 es la única entrada que pasa de I a V: **185 V, 10 I, 0 P y 23 R; 33 entradas sin cierre**, mismas 218 entradas y huella original. Las revisiones integrales de formularios/roles, contratos simulados restantes, demo, entregables/fases y recuperación final F26 continúan abiertas. Airbnb, Booking y demás sincronización externa permanecen aplazados.
