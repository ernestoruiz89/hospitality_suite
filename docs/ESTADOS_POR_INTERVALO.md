# Estados actuales y por intervalo — 0.7.7

S05-03 se contrasta individualmente sobre Frappe 16.52.0 / ERPNext 16.51.1. Los estados son información calculada para la tarea; no se sustituyen las asignaciones ni se guarda un único estado que mezcle limpieza y reserva.

## Qué ve Recepción

Buscar disponibilidad conserva sus cinco campos y el resumen de cupo. Una sección plegada adicional, **Estado de las habitaciones en estas fechas**, permite contrastar todas las habitaciones de la categoría. Presenta número y descripción, sin hashes, huésped, reserva, saldo ni JSON técnico. El intervalo se muestra en el resumen; la limpieza se identifica como **actual**, pendiente de comprobar antes de registrar entrada.

| Estado requerido | Criterio y evidencia |
|---|---|
| Disponible | Sin conflicto físico después de considerar el colchón de limpieza y con cupo por categoría. No promete limpieza futura ni entrada inmediata. Las opciones físicas son alternativas dentro del cupo; una categoría llena por reservas sin asignación se expresa como Sin cupo por categoría. |
| Reservada para el intervalo | Una asignación de reserva activa cruza las fechas solicitadas. Otro intervalo puede resultar libre; al cancelar la reserva deja de bloquear. |
| Ocupada | La estancia cruza el intervalo; una estancia vencida y aún activa sigue bloqueando conforme al motor de disponibilidad. La tarjeta actual conserva Alojado y las horas de entrada/salida. |
| Salida próxima | Hasta una hora antes de la salida, con referencia del servidor y avance monotónico. Se muestra texto, además de cualquier color. |
| Tiempo excedido | Contador posterior a la salida prevista; no registra salida ni altera cargos por mostrarlo. |
| Sucia / En limpieza / Pendiente de inspección | Estados de limpieza actuales independientes del intervalo futuro. La pantalla y el resultado de consulta los conservan explícitos. |
| Fuera de servicio | Bloqueo de mantenimiento durante el intervalo, incluido sin vencimiento hasta reapertura autorizada. La tarjeta actual indica reapertura pendiente cuando corresponde. |

También se distinguen habitación inactiva y colchón de limpieza, sin presentarlos como una reserva que no cruza las fechas. Las llegadas diferencian próxima, próxima dentro de una hora sin entrada registrada y hora prevista superada. Las etiquetas de llegada/salida se actualizan con el reloj del servidor, también tras cambios del reloj del equipo.

`availability_search.interval_states` usa las asignaciones y candidatos del mismo motor de capacidad; conserva permisos de la consulta y no libera asignaciones ni genera documentos. `hospitality_availability.js` presenta el contraste plegado. `hospitality.js` y `hospitality_board.js` presentan los tiempos con texto. No cambia esquema, facturación, precio, series documentales ni formato PDF.

## Calendario

La consulta muestra carga, invalida la respuesta anterior al cambiar fecha/propiedad y conserva la lista de habitaciones del contexto solicitado. Una fecha vacía identifica el campo y ofrece corregirlo; fallo o datos inesperados muestran reintento, sin convertirse en un calendario disponible. Las fechas se envían con la zona explícita del establecimiento. Una celda vacía dice **Sin asignación**, porque no acredita por sí sola cupo ni limpieza. El contraste para reservar se realiza en Buscar disponibilidad.

Los días de semana respetan el idioma del usuario, con español por defecto y recuperación ante un código de idioma inválido; no dependen del idioma global de Moment. Las capturas 214–215 son anteriores a este ajuste de idioma; 216 acredita la presentación final. Esto no acredita todos los literales dinámicos ni todos los estados/validaciones de formularios secundarios: S01-04 y S04-16 continúan I. El historial completo por rango, incluidos cambios de limpieza y reservas canceladas, sigue pendiente en S05-04.

## Pruebas y recorrido

Pasaron **352 pruebas nativas: 338 de integración y catorce puras**, siete nuevas de disponibilidad. Después de convertir las etiquetas a literales extraíbles se repitieron las **catorce dirigidas de disponibilidad**, aprobadas, sobre el código final de esa proyección. La batería completa no se vuelve a presentar como una ejecución posterior a ese ajuste de extracción. Pasaron **126 JS: 124 Desk y dos portal**, nueve nuevas, incluido el ajuste final de idioma. Los JUnit y logs distinguen ambos alcances.

Las nuevas nativas comprueban reserva/estancia/bloqueo reales e inactiva, otra fecha y cancelación nativa, cupo lleno sin habitación asignada, colchón y extremo exclusivo, bloqueo sin vencimiento/reapertura, limpieza actual separada de disponibilidad futura y proyección sin identidad/finanzas ni otra propiedad. Las JS comprueban escape y referencias ocultas, cero cupo, límite de una hora y tiempo excedido, reloj/llegada próxima o atrasada, carga/error/fecha inválida y respuestas antiguas de calendario, propiedad, idioma y recuperación. Se conservan las regresiones anteriores de permisos, límites, horarios, estancias y contabilidad.

El fixture de `tools/room_states_ux.py` se prepara únicamente en aceptación, con respaldo. Usa H101 próxima a salir, H102 reservada, H103 bloqueada hasta reapertura, H104 inactiva, H105 sucia, H106 en limpieza, H107 para inspección, H108/H109 libres y H110 vencida aún alojada. La creación es por API/configuración. H110 recibe marcas horarias sintéticas anteriores para comprobar la representación de vencimiento; no se presenta como una salida o modificación hecha desde Page.

Recepción consulta y observa cinco opciones físicas para las primeras fechas; la lista adicional contrasta las diez habitaciones. Para el 25–26, H101/H102 quedan disponibles y el cupo sube a siete; H103 conserva bloqueo y H110 sigue ocupada. Editar los campos retira el resultado anterior. Las capturas 206–208 acreditan tiempos y llegada atrasada, 209–211 resumen/contraste/otro intervalo y 212–213 móvil. En 390×844, documento de 390 px y diálogo de 374 sin desborde; tarjetas de 147 px, resumen de 66 px y acción principal de 44 px dentro de la pantalla. El detalle permanece plegado hasta pedirlo.

El calendario rechaza una fecha vacía, recupera la última de dos fechas consecutivas y cambia al establecimiento Por tiempo con solo M101–M110 y su vista horaria; al regresar recupera habitaciones del hotel. El retraso/respuesta fuera de orden se controla de forma determinista en JS; la navegación real no simula un retardo de red controlado. Después de restaurar se comprueba el idioma final mediante otra sesión de lectura sin operaciones. Ambas sesiones terminan en Login, viewport restablecido y pestañas/8089 cerrados. El servidor temporal conserva fallback de Socket.IO: no se acredita transporte en tiempo real.

## Conservación y alcance

La lectura de interfaz conserva las mismas **72 tablas del fixture** y todas las nativas; no crea cobros, facturas ni movimientos de inventario. Se restauró el respaldo original con archivos y se volvió a comparar tras la lectura final de idioma: aceptación **71 tablas/185 filas y 72/195 con Version**, sin operaciones. Principal conserva **72 tablas/1191 filas, dos archivos privados y fecha operativa 19/10**. Se mantiene la excepción histórica documentada de cachés Company; no se reemplazan huellas. Núcleos limpios, assets/servicios/HTTP activos y PDF conciso instalado con la misma huella, sin otra descarga/render de PDF.

`room-states-items-ui.json`, `room-states-browser.json`, los JUnit/logs y los comprobantes upgrade/ux-restored/final-state delimitan la evidencia. La primera reconstrucción final se lanzó fuera del bench, sin ejecutarse; se corrigió el directorio y los assets se construyeron correctamente. Un intento de navegar antes de terminar Login fue abortado por la redirección; se esperó Desktop y se continuó con éxito. No se alteró el producto para eludir esos errores de herramientas.

S05-03 I→V: **184 V, 11 I, 0 P y 23 R; 34 entradas sin cierre**, mismas 218 entradas y huella originales. Continúan historial completo, aceptación integral por roles/UX, contratos simulados restantes, demo, entregables/fases y recuperación final F26. El objetivo sigue activo. Airbnb/Booking y demás sincronización externa siguen aplazados.
