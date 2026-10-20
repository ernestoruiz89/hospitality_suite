# Estancias y próximas llegadas, versión 0.6.2

Estancias sustituye la tabla general por cuatro vistas: **Alojados, Llegadas, Salidas y Cuentas abiertas**. Cada una muestra su conteo, una explicación breve, hasta 25 filas por página y la acción correspondiente. Las selecciones de vista/fecha se conservan en la instancia de la Page y separadas por establecimiento; no se acredita aquí persistencia después de cerrar sesión o recargar.

| Vista | Contenido y acción |
|---|---|
| Alojados | Estancias activas ahora, con huésped, habitación, entrada/salida prevista y Ver estancia |
| Llegadas | Una fila por habitación aún pendiente de entrada; Gestionar llegada abre la reserva y sus solicitudes numeradas |
| Salidas | Estancias activas con salida prevista hasta el día elegido; Ver estancia abre sus acciones y cuenta |
| Cuentas abiertas | Una fila por cuenta Open, también con saldo cero; pagador, habitación/grupo, saldo y Ver cuenta |

**Consultar pendientes hasta** usa la fecha calendario en la zona del establecimiento, con límite excluido en la medianoche del día siguiente. Incluye pendientes anteriores, de modo que una llegada o salida atrasada no desaparece al cambiar de día. La fecha operativa de cierre permanece independiente. Alojados y Cuentas abiertas muestran el estado actual, por lo que ocultan el campo de fecha y conservan una referencia breve al período de los conteos de llegadas/salidas.

Una llegada grupal parcialmente ingresada conserva solo las asignaciones pendientes. La fila sin habitación física muestra Por asignar y su categoría. La gestión de una reserva con varias solicitudes permite elegir cuál registrar; no se convierte todo el grupo en una sola estancia. Las cuentas compartidas se muestran una vez con sus habitaciones, sin sumar varias veces el mismo saldo. Cada importe conserva su moneda; no se ofrece un total que mezcle monedas.

## Tarjetas y uso móvil

Recepción muestra entrada y salida previstas de la estancia activa, tiempo restante/excedido y saldo autorizado. Una habitación con reserva pendiente muestra su fecha y **Ver reserva**; conserva Sin ocupación hasta que se registre la entrada. Las retenciones vencidas se omiten de próximas llegadas sin cancelarlas ni liberar recursos desde una consulta. El control de disponibilidad y su recuperación siguen en los comandos y trabajos existentes.

La cabecera móvil se compacta conservando establecimiento, fecha operativa, actualización, estado de conexión y cierre de sesión. Se retira la repetición del título de sección. Las cuatro vistas se disponen en dos columnas. Entre 360 y 600 px, las fichas del tablero presentan sus datos en dos columnas y su acción a todo el ancho; en pantallas más estrechas conservan la disposición de una columna. Se mantiene el HTML de tabla y sus encabezados/etiquetas.

En 390×844, la ficha de cuenta con nombre, pagador, habitación, saldo y Ver cuenta cabe en la primera pantalla. La lectura DOM midió **352 px de ancho y scrollWidth 352**, sin desborde horizontal de la ficha, y botón de **44 px**. La primera revisión visual detectó exceso de cabecera; se redujo. También se corrigió la prioridad CSS frente a la regla general de tablas móviles antes de guardar la captura final 112. No se presenta esa iteración inicial como resultado final.

## Contrato de lectura y permisos

`stay_board(property_name, date=None, view="hosted", offset=0, page_length=25)` requiere un rol operativo de lectura y acceso al establecimiento. Permite recepción, caja, contabilidad, supervisión/gerencia y auditor de lectura; limpieza, Guest o un recepcionista sin acceso no pueden consultar otra propiedad. No concede permisos de escritura o finanzas. Las acciones de cada fila conservan sus permisos existentes.

La lectura reutiliza la paginación autorizada y el saldo de folio estándar. Calcula el saldo únicamente para las cuentas de la página solicitada. Devuelve filas, conteos por vista, fecha, establecimiento y hora del servidor. El modo discreto sustituye los nombres de presentación. El cliente escapa las etiquetas y conserva las identidades originales para las acciones.

La proyección de próxima llegada en bootstrap contiene solo habitación, reserva, fechas y estado, sin nombres ni precios, para los roles autorizados de operación/finanzas. La ocupación sigue leyendo exclusivamente estancias Active. Consultar el tablero no registra documentos, cargos ni conciliaciones. Si falla una consulta, muestra error y Actualizar; las respuestas de una fecha, vista o propiedad anterior no pueden reemplazar la selección nueva ni quitarle su estado de carga.

## Pruebas ejecutadas

La batería conjunta aprueba **229 casos: 215 de integración y catorce puros**, en el sitio de aceptación designado. Los nueve nuevos casos de `test_desk_board.py` cubren reserva futura sin ocupación, proyección mínima, grupo parcialmente ingresado, demanda por asignar, retención vencida sin escritura, día local de 25 horas/límite excluido, cuentas compartidas/cero, paginación/valores inválidos, roles/propiedad/modo discreto y salidas atrasadas. Una ejecución parcial inicial usó incorrectamente status en vez de hold en el fixture de retención; se corrigió y los nueve casos pasaron antes de la batería completa.

Aprueban **45 regresiones JavaScript: 43 Desk y dos portal**. Las cuatro nuevas cubren presentación de llegada futura sin ocupación, nombres escapados/identidades estables, respuestas obsoletas y paginación/contexto inválido. No representan 45 recorridos de navegador. Los últimos ajustes posteriores a la batería nativa fueron de presentación JavaScript/CSS; las 45 regresiones y la construcción se repitieron con esos archivos finales.

El recorrido real en `hospitality-acceptance.localhost:8089` usa **HS Receptionist**, datos ficticios y 1280×720/390×844:

1. Un fixture API deja H101 alojado con salida hoy, H103 pendiente de entrada hoy y H102 con llegada mañana. Ninguna de esas reservas iniciales se atribuye a captura desde Pages.
2. Se consultan las cuatro vistas. Llegadas muestra una habitación hoy y dos al elegir mañana, incluyendo la pendiente anterior. Salidas conserva la de H101. Cuentas muestra el saldo 1500, con su acción visible en móvil.
3. Recepción distingue H101 alojado de H102/H103 sin ocupación, cada una con su llegada pendiente. Ver reserva abre la solicitud H102; se cierra sin registrar su entrada.
4. Desde Llegadas se gestiona H103 y se confirma la entrada. El servidor confirma la operación: Alojados pasa de uno a dos, Llegadas de uno a cero y Cuentas abiertas de una a dos. Se comprueba el estado vacío y las dos estancias activas.
5. `board-items-ui.json` verifica H101/H103 Active, actor de la segunda entrada recepcionista, dos cargos Pending y cero facturas, pagos, turnos, Payment Entry, Journal Entry, limpieza o cierre diario. La reserva futura de H102 continúa sin entrada. Se termina sesión hasta Login y se cierra la pestaña temporal.

Capturas **111–117** conservan llegadas, cuenta móvil, tarjetas, entrada confirmada, salidas, consulta hasta mañana y llegada completada. El servidor temporal no tiene Socket.IO propio; este recorrido no acredita tiempo real ni todos los roles. La cobertura de grupos/roles/permisos del nuevo tablero se acredita con los casos nativos, no con una supuesta operación grupal de este recorrido individual.

## Conservación y matriz

Respaldos nativos con archivos, migraciones y bundle completados. `board-upgrade.json` compara las mismas columnas de 72 tablas: 1191 filas/dos archivos privados principales y 195 filas de aceptación. Tras el recorrido se restaura aceptación con Bench y archivos: `board-ux-restored.json` compara las 71 tablas/185 filas y acredita cero operaciones. `board-final-state.json` verifica servicios/guardias, fecha principal 19/10, HTTP 200 y 8089 cerrado. Web/worker se reinician con esta revisión; Frappe/ERPNext permanecen limpios.

S04-04 y S05-01 pasan P→V con este alcance. La matriz conserva las 218 entradas y huella originales: **101 V, diecisiete I, cero P y 100 R**. El contraste histórico en `AUDITORIA_PAGES_HABITACIONES.md` y `pages-rooms-audit.json` corresponde a 3563ef0; no se vuelve a ejecutar su reproducción de ausencias contra el código nuevo.

Siguen pendientes la revisión de las 100 R y verificaciones I, incluidas alertas de Inicio, filtros/persistencia, teclado/foco, estados secundarios del calendario, historial completo, extremos del colchón, formularios secundarios y aceptación por rol. La gestión de reservas aún puede simplificar campos según acción y acortar el área de motivo; no se declara resuelta toda la UX por estas vistas. Continúan demo operativa, traducciones, reintentos y recuperación de la revisión final. La sincronización externa sigue pendiente por indicación del usuario. El objetivo continúa activo.
