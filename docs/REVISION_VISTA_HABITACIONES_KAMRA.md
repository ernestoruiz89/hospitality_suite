# Vista de habitaciones de Kamra: análisis para Hospitality Suite

Revisión del 22 de octubre de 2026. Fuente principal: Kamra PMS, commit [`bb4e36e`](https://github.com/Kamra-PMS/kamra-pms/tree/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a). El nombre del proyecto es **Kamra**, aunque en la conversación se escribió «Karma».

## Qué ofrece Kamra

La [pantalla Rooms](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/screens/Rooms.tsx) presenta tarjetas por piso. Cada tarjeta muestra número, tipo, estado de limpieza, ocupación, apellido del huésped alojado o previsto, marcas de llegada y salida, y bloqueo. La búsqueda admite número y huésped; hay filtros por piso, tipo y estados con conteos. La pantalla consulta de nuevo cada 30 segundos. El panel se abre sin abandonar el tablero y conserva la habitación en el parámetro `room` de la URL.

El [panel RoomDrawer](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomDrawer.tsx) separa siete áreas: estado, situación actual, solicitudes, folio, disponibilidad, historial y detalles (las solicitudes y el folio aparecen durante la estancia). Desde allí se inicia entrada/salida, cambio de habitación, limpieza, bloqueo, solicitudes, cargos y cobros mediante comandos existentes. La [documentación funcional](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/docs-site/rooms.md) precisa roles, reglas y definiciones. Las cinco consultas nuevas en [`rooms.py`](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/kamra/rooms.py) son de lectura: tablero, detalle, disponibilidad, historia e indicadores; las mutaciones conservan sus endpoints anteriores.

La pestaña [Insights](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomInsights.tsx) muestra noches ocupadas, ocupación sobre noches comercializables, ingreso de alojamiento contabilizado, noches fuera de servicio y duración de limpieza, por habitación y en conjunto. Tiene períodos de 30/90 días en la interfaz, restricción del dato monetario por rol y caché de diez minutos en el servidor.

### Matices del código que afectan la adaptación

1. El filtro `Ready to sell` de `Rooms.tsx` comprueba habitación desocupada, sin bloqueo y limpia, pero no excluye una llegada asignada para hoy. Representa preparación física actual, **no cupo vendible para cualquier intervalo**. En Hospitality Suite debe decir «Lista ahora» o «Lista para llegada» y remitir la decisión comercial a la búsqueda de disponibilidad.
2. `rooms_board` consulta llegadas con `check_in_date == today`; una llegada pendiente de ayer no entra en esa marca. Nuestra bandeja de llegadas ya incluye pendientes atrasadas. Debemos conservarla y señalar su prioridad en la tarjeta.
3. `room_availability` calcula noches con fechas y salida exclusiva. No sirve literalmente para estancias de horas, salida a medianoche, colchón de limpieza, reservas sin número asignado y bloqueos sin fecha final de nuestra app. Nuestro `HS Allocation` y el barrido por intervalos siguen siendo la autoridad.
4. La acción «fuera de servicio» de `RoomDrawer` crea el bloqueo y después intenta marcar `Out of Order`; la reapertura libera bloqueos y después marca `Dirty`. Son llamadas separadas. Nuestra vista debe usar un único comando transaccional para cada operación, con versión, rol, motivo y bitácora.
5. `room_insights` atribuye ingreso y noches al `Reservation.room` actual. Tras un traslado, esa referencia puede no representar la habitación histórica que produjo cada noche/cargo. Para indicadores por habitación nuestros, usar intervalos de asignación y una regla explícita de atribución de ingresos antes de presentar rankings monetarios.

## Comparación con Hospitality Suite

| Capacidad | Estado local | Brecha útil |
| --- | --- | --- |
| Tarjetas y filtros | Recepción tiene tarjetas con ocupación, limpieza, siguiente llegada, saldo autorizado y filtros por piso, categoría y estado; Inicio ya tiene dashboard operativo. | Falta una ficha persistente de la habitación y filtros directos de llegada atrasada, salida y trabajo abierto. |
| Estancia y cuenta | `action_detail`, `action_booking`, colas de Estancias y saldos distinguen cuenta compartida de grupo; cobro sigue el flujo ERPNext. | Reunir enlaces y resumen autorizado en el contexto de habitación; no crear un segundo folio. |
| Limpieza y mantenimiento | `HS Cleaning Task`, `HS Maintenance Order`, bloqueo `HS Allocation`, inspección, evidencia y reapertura ya existen. | Mostrar trabajo abierto por habitación y dar acceso contextual a sus acciones existentes. |
| Disponibilidad | Calendario de asignaciones de Recepción y `availability.py` validan intervalos, mantenimiento y demanda de categoría sin habitación. | Una tira temporal para una habitación concreta, con escala de noches o de horas según modo, y enlace a búsqueda validada. |
| Historial | `room_history.py` reconstruye operaciones, versiones y períodos con paginación y permisos; Recepción lo abre en diálogo. | Integrarlo como sección de la ficha sin perder rango, zona horaria ni distinción de relaciones ambiguas. |
| Indicadores | Gestión calcula ADR/RevPAR para hotel y utilización/rotación por horas para motel; Inicio muestra ocupación actual. | Indicadores **por habitación** de uso y tiempo de limpieza; ingresos por habitación quedan condicionados a atribución histórica verificable. |
| Información física | `HS Room` guarda categoría, piso, zona, camas y estacionamiento; `HS Category` contiene capacidad, descripción, comodidades e imagen pública. | Mostrar ficha descriptiva. Fotos de limpieza o notas de habitación serían un dato nuevo y requieren caso de uso y permisos propios. |

## Propuesta de producto

### Fase 1 — ficha operativa de habitación (prioridad alta)

Al seleccionar cualquier tarjeta en Recepción se abre una ficha con encabezado fijo: número, categoría, ocupación actual, limpieza, bloqueo y hora de actualización. Cuatro secciones bastan:

- **Ahora:** estancia activa y próxima llegada asignada, también atrasada; entrada/salida prevista; cuenta solo para roles autorizados, indicando si es compartida; enlaces a estancia y reserva existentes.
- **Trabajo:** tarea de limpieza, inspección pendiente y mantenimiento abierto, responsable y prioridad; botones de acción únicamente si el servidor autoriza.
- **Agenda:** asignaciones y bloqueos de esa habitación en el horizonte elegido; horas en motel, noches en hotel. Estado «sin asignación» nunca implica cupo garantizado.
- **Historial y datos:** acceso al historial paginado actual y a las características físicas; no copiar todo el histórico al bootstrap.

El tablero debe sumar filtros «Llega», «Sale» y «Trabajo pendiente» con conteos, y chips de texto además de color. Mantener la selección al refrescar y al volver desde una acción. En pantalla pequeña, ficha de ancho completo; en escritorio, panel lateral. El dashboard de Inicio puede abrir Recepción con el filtro correspondiente.

### Fase 2 — acciones de ciclo de vida (prioridad media)

Conectar la ficha a entrada, salida, cambio de habitación, limpieza e incidencia ya disponibles. Para «bloquear» y «reabrir» proponer comandos únicos que actualicen orden de mantenimiento/asignación y estado de preparación de forma atómica. La reapertura debe dejar la habitación pendiente de limpieza o inspección según la política vigente; no declararla vendible al cerrar una orden. El servidor debe recalcular disponibilidad bajo bloqueo y rechazar versiones obsoletas.

### Fase 3 — indicadores por habitación (prioridad condicionada)

Primero publicar ocupación por noches en hotel, horas utilizadas y rotaciones en motel, horas fuera de servicio, tareas completadas y duración válida de limpieza. Después, si podemos demostrar atribución correcta en cambios de habitación, grupos, anulaciones y ajustes, añadir ingresos y ranking. Cada indicador debe mostrar período, denominador, zona horaria y fecha de actualización. Un intervalo sin datos se muestra como «sin datos», no como cero medido.

## Contrato y controles propuestos

Crear proyecciones de solo lectura `room_board_snapshot(property)`, `room_snapshot(property, room)` y `room_schedule(property, room, starts_at, ends_at)` sobre las entidades existentes. El servidor verifica rol y propiedad para cada solicitud; la respuesta incluye solo campos visibles por ese rol y respeta modo discreto. La ocupación procede de `HS Stay`/`HS Allocation`; limpieza de `HS Room` y `HS Cleaning Task`; bloqueo de asignaciones de mantenimiento; nunca aceptar del cliente un estado de ocupación editable. Las acciones siguen `api.execute` y sus reglas actuales.

Para no duplicar lecturas costosas, el tablero trae un resumen acotado de todas las habitaciones y la ficha consulta el detalle solo al abrirse. Refresco periódico únicamente con la página visible, marca de última actualización, descarte de respuestas viejas al cambiar propiedad/habitación y actualización puntual tras cada comando. El campo de búsqueda de huésped se ofrece solo a roles que puedan ver su identidad; el tablero no envía nombres a roles de limpieza o mantenimiento cuando no les corresponda.

## Aceptación mínima

- Dos establecimientos y roles de recepción, limpieza, supervisión, mantenimiento, caja y auditoría: ninguna respuesta ni enlace cruza propiedad o divulga saldo/huésped sin permiso.
- Habitación limpia con llegada asignada, llegada atrasada, salida vencida, estancia activa con cuenta grupal, habitación sin asignar, bloqueo hasta reapertura y mantenimiento que no bloquea: cada tarjeta y ficha comunica el estado real.
- Hotel y motel, incluido intervalo corto que cruza medianoche: la agenda coincide con `HS Allocation` y la búsqueda de disponibilidad; una zona vacía no se presenta como promesa de venta.
- Cambio de propiedad o habitación durante una consulta y refresco automático mientras se edita: no aparecen datos obsoletos ni se pierde el trabajo del usuario.
- Bloqueo/reapertura y cambio de habitación concurrentes: validación servidor, versión, idempotencia y auditoría; una operación fallida no deja estados parciales.
- Navegación por teclado y lector de pantalla, con etiqueta textual de estado, foco recuperado al cerrar la ficha y acciones alcanzables en móvil.

La oportunidad inmediata es **unificar la operación de una habitación**, no migrar la app a React ni rehacer el dashboard ya entregado. El valor aparece al reducir saltos entre Recepción, Estancias, Limpieza, Mantenimiento e Historial conservando las reglas actuales de disponibilidad y contabilidad.

## Implementación local

La propuesta está implementada en `hospitality_suite/room_view.py` y `hospitality_suite/public/js/hospitality_room_view.js`. Recepción muestra filtros y conteos de llegadas, salidas y trabajo, abre una ficha lateral con Ahora, Trabajo, Agenda, Historial, Datos e Indicadores, y conserva la habitación al actualizar o cerrar una acción. Inicio enlaza a Recepción con el filtro elegido. La ficha consulta cada sección bajo demanda y limita huéspedes, saldos y enlaces según el rol y el modo discreto.

La agenda usa los intervalos reales de `HS Allocation`, incluidos bloqueos sin fin, estancias activas vencidas y los límites horarios que cruzan medianoche. Su ausencia de asignaciones no equivale a disponibilidad confirmada. Las acciones de reserva, estancia, limpieza y mantenimiento siguen los comandos existentes. Al completar mantenimiento con bloqueo, el mismo comando libera la asignación y crea una limpieza pendiente si no la había; la habitación queda sucia hasta completar el proceso. Siguen vigentes la comprobación de versión, permisos, idempotencia y auditoría de `api.execute`.

Los indicadores muestran noches al final del día local para hotel, horas usadas, rotaciones, horas bloqueadas y limpiezas. La utilización divide horas usadas por horas calendario menos bloqueos de mantenimiento; el denominador **no** reconstruye limpieza, inactividad histórica ni restricciones comerciales. La duración media se muestra «sin mediciones válidas» cuando no hay tareas con tiempos completos. No se publican ingresos por habitación hasta tener atribución verificable a cada estancia, traslado y cargo.

Verificación: 7 pruebas de integración de la ficha; batería nativa completa de 390 pruebas de integración y 32 unitarias; 244 pruebas Node de interfaz; compilación de assets y recorrido real en Recepción para la ficha, agenda, historial, indicadores, enlace filtrado desde Inicio, regreso desde una acción y pantalla móvil de 390 px. La batería nativa completa se ejecutó antes de agregar dos casos finales de la ficha, que se probaron por separado.

## Revisión adicional: qué implementar después de la ficha

Esta sección compara el mismo commit de Kamra con la ficha y el dashboard **ya implementados**. La selección se basa en el código de [Rooms](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/screens/Rooms.tsx), [RoomDrawer](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomDrawer.tsx), [RoomInsights](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomInsights.tsx) y [rooms.py](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/kamra/rooms.py). Son propuestas; no forman parte de la implementación descrita arriba.

### Prioridad de producto

| Prioridad | Oportunidad | Base que ya tenemos y trabajo adicional | Criterio de aceptación |
| --- | --- | --- | --- |
| 1 · alta | **Llegada en riesgo** en Recepción e Inicio: una llegada asignada próxima cuya habitación sigue sucia, en inspección, bloqueada o con trabajo crítico abierto. | `board_snapshot` ya cruza llegada, limpieza, bloqueo y trabajo. Agregar una regla con ventana configurable y hora local; mostrar motivo, tiempo restante y enlace a la ficha. No inferir una hora prevista distinta de la entrada reservada si no existe ETA. | El mismo cuarto con llegada inminente y limpieza pendiente aparece una vez, con causa verificable; al limpiar, cambiar la habitación o posponer la llegada desaparece. El tablero no promete disponibilidad. |
| 1 · alta | **Comparador de habitaciones** en el dashboard: tabla ordenable, mejores y menos usadas, fuera de servicio, rotaciones y tiempo de limpieza; seleccionar fila abre su ficha. | `room_insights` ya devuelve métricas de todas las habitaciones para 7/30/90 días, pero la interfaz solo muestra una. Crear una vista agregada por propiedad y modalidad; mantener los permisos de la consulta. Evitar calcular otra vez por cada tarjeta. | Los totales coinciden con la suma de las filas y con la ficha; se distinguen 0, sin medición válida y denominador 0. Señalar que la inactividad histórica aún no se conoce. Sin ranking monetario hasta definir atribución. |
| 2 · media | **Enlace directo y acciones contextuales**: abrir una habitación específica desde Inicio, mantenimiento, limpieza o un enlace compartido; desde «Ahora», entrar al flujo existente de salida, cambio, registro y llegada. | Kamra conserva `room` en la URL. Aquí se conserva la selección en memoria, pero no se puede abrir la ficha por enlace. Usar ruta/consulta validada contra propiedad y rol; enlazar `action_detail`, `action_checkout`, `action_change_room`, `action_print_registration` y la acción de llegada, sin duplicar comandos. | Recargar, retroceder o cambiar propiedad no abre una habitación de otra propiedad. El usuario regresa a la ficha tras cerrar la acción y solo ve botones que puede ejecutar. |
| 2 · media | **Búsqueda autorizada por huésped y tablero compacto por piso**. | Kamra busca nombre y agrupa tarjetas por piso. Nuestra búsqueda cubre número, categoría, piso y zona; el resumen del tablero ya puede contener nombres solo para roles autorizados. Combinar búsqueda local con esos campos ya proyectados, sin agregar datos personales al bootstrap general; la agrupación compacta debe ser una vista opcional. | Limpieza, mantenimiento y modo discreto no reciben ni pueden buscar nombres; el resultado mantiene conteos y navegación por teclado. |
| 2 · media | **Solicitudes del huésped visibles en la ficha**. Primero mostrar consumos/servicios abiertos de la estancia; después crear tickets generales con tipo, prioridad, equipo, responsable, estado, vencimiento y resolución. | Kamra usa `Service Ticket` para peticiones de toallas, concierge y quejas. Nuestro `HS Service Request` exige artículo/cantidad y puede generar cargo o movimiento de inventario; `HS Request` es el registro de idempotencia. Ninguno representa todas esas peticiones. Un ticket nuevo debe relacionarse con estancia y habitación histórica y admitir solicitudes sin cargo. | Un ticket abierto sigue visible tras reasignarlo o cambiar de habitación, se conserva en historial con autor y tiempos, y una queja o una petición de limpieza no crea un cargo accidental. |
| 2 · media | **Retenciones de inventario por motivo**: uso interno, propietario, VIP u otro, con fechas/horas y liberación. | Kamra tiene `Room Block` para esos motivos además de reparaciones. Aquí `HS Allocation` solo admite Reservation/Stay/Maintenance, y los bloqueos están ligados a órdenes de mantenimiento. Modelar retención no técnica por separado, con motivo, autorización, intervalo, bloqueo real del motor de disponibilidad e historial; distinguir uso interno efectivo de simple retención. | Un bloqueo no se solapa con estancia o reserva confirmada, considera colchón y zona horaria, se libera de forma transaccional e idempotente y no deja la habitación «limpia» por accidente. |
| 3 · selectiva | **Agenda visual por noches u horas** y **datos físicos específicos**. | Kamra presenta celdas de 14/30 noches, notas y fotos de limpieza. Nuestra agenda de intervalos ya es más fiel a motel/mixto. Una capa visual puede usar celdas nocturnas para hotel y franjas horarias para motel; notas/fotos requieren campos, permisos y retención diferenciando imagen pública de evidencia interna. | Una franja vacía se rotula «sin asignación» y la búsqueda de disponibilidad decide si se puede vender. Evidencia privada nunca sale al portal. |

### Límites detectados en Kamra que no debemos trasladar

- El indicador de [ocupación de `rooms.py`](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/kamra/rooms.py#L548-L576) usa la habitación **actual** de la reserva para todas las noches y cargos del período. Si hubo traslado, puede asignar uso e ingreso históricos a la habitación equivocada. Nuestra base de intervalos por `HS Allocation` es mejor para uso físico; ingresos requieren vínculo de cargo a habitación y tiempo de prestación.
- Su [denominador](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/kamra/rooms.py#L578-L637) resta noches de bloqueo sumadas, pero no reconstruye inactividad ni limpieza histórica; tampoco usa horas, por lo que no representa motel. Nuestro indicador actual declara que tampoco descuenta limpieza/inactividad histórica. Antes de llamar «ocupación comercial» a un ranking, guardar o reconstruir esos períodos y unir intervalos superpuestos. Mientras tanto, rotular el dato como **uso sobre horas calendario menos mantenimiento**.
- El [estado de limpieza](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomDrawer.tsx#L324-L365) se puede marcar directamente `Clean`, `Inspected` o `Ready`. Aquí la tarea y la inspección tienen su propio ciclo. Un ajuste excepcional de supervisor, si se necesita, debe pedir motivo y quedar auditado; no sustituye una limpieza real.
- Los [bloqueos y reaperturas](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/frontend/src/components/RoomDrawer.tsx#L292-L322) se resuelven con dos llamadas de escritura consecutivas. Conservar comandos atómicos en nuestra app. La [celda `Free`](https://github.com/Kamra-PMS/kamra-pms/blob/bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a/kamra/rooms.py#L252-L297) solo dice que no encontró asignación de esa habitación en esa noche; no valida demanda de categoría, colchón de limpieza ni un intervalo horario.

### Secuencia sugerida

1. Entregar alerta de llegada en riesgo y comparador de habitaciones como extensión del dashboard actual. Usar `room_insights` existente, documentar el denominador y medir el costo de la consulta antes de introducir caché. Mostrar el trabajo relevante de la habitación junto a la alerta.
2. Agregar enlace directo, acciones contextuales y búsqueda autorizada. Son mejoras de navegación sobre comandos y proyecciones existentes.
3. Diseñar tickets generales y retenciones de inventario como flujos propios. Antes de construir las pantallas, definir roles, plazos, vencimiento, concurrencia, historial y relación con estancia/reserva; no reutilizar `HS Request` ni fingir una orden de mantenimiento.
4. Evaluar agenda compacta, notas y evidencia solo donde la operación diaria demuestre necesidad. Posponer ingresos por habitación hasta que los cargos puedan atribuirse a una habitación histórica concreta.
