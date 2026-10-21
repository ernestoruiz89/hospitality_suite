# Disponibilidad visual y límites de consulta — 0.8.4

Las opciones de habitación muestran fondo verde, marca y texto «Disponible». El detalle por fechas usa verde para `Available` y rojo para `Reserved`, `Occupied`, `Blocked`, `Buffer`, `Inactive` y `Category Full`, con «No disponible» y el motivo. Un estado desconocido queda gris y «Por revisar». Las clases se eligen de una lista fija; no se construyen con datos arbitrarios. El color depende del intervalo consultado; la limpieza actual se conserva como información independiente.

Las tarjetas disponibles siguen abriendo Nueva reserva con habitación, fechas y personas preseleccionadas. Una consulta que no cubra toda la cantidad solicitada conserva las opciones como información, sin acción de reserva. No cambian permisos, asignaciones, contratos ni valores almacenados.

Cantidad de habitaciones y Personas por habitación rechazan cero, negativos, fracciones y texto antes de que el control Int nativo trunque el dato o se envíe la consulta. El mensaje aparece junto al campo y recibe foco. Se conserva el texto escrito, incluido `1.5`, y se permite corregir. Los límites son explícitos por campo; no se prohíbe cero en importes o conteos que lo admiten. La evaluación de números, separadores y expresiones válidas sigue siendo la nativa de Frappe.

## Comprobaciones ejecutadas

**191 JavaScript aprobadas: 188 Desk y tres portal**, ocho más que 0.8.3. Cinco cubren límites y su integración anterior al parseo; tres cubren los siete estados, limpieza independiente, estado desconocido/escape y acciones conservadas en tarjetas verdes. Los casos anteriores de respuesta antigua, permiso y contexto de reserva siguen pasando. [Resultado](evidence/action-context-js-tests.log) y [compilación](evidence/action-context-build.log).

El recorrido de Pages usa Caja y Recepción con sesiones separadas en aceptación:

1. Dos turnos se abren/cierran con cero y diferencia cero. La confirmación de salida aparece, Enter en No conserva sesión y Enter en Sí la termina. El primer turno se observó con instrumentación temporal ya retirada; el segundo y su salida usan DALLPPL6.
2. Cantidad `0`, `1.5` y `abc`, y personas `-1`, reciben error local y conservan el texto. El [checkpoint anterior a la corrección](evidence/action-context-invalid-checkpoint.json) comprueba **cero peticiones HTTP de disponibilidad**. Corregir con `1+1` permite una consulta de dos habitaciones. Capturas [cero](evidence/284-cantidad-cero-validacion.jpg), [decimal conservado](evidence/285-cantidad-decimal-validacion.jpg), [móvil](evidence/286-personas-validacion-movil.jpg) y [corrección](evidence/287-disponibilidad-cantidades-corregidas.jpg).
3. Después de la petición de colores se compila DB4YLAYT / CSS 7ABEJ5NU. En las fechas 24/10/2026 14:00 a 25/10/2026 12:00, pulsar H101 abre la reserva con habitación, fechas y dos personas. Se confirma una sola reserva ficticia por C$ 1,500.00, sin ingreso, estancia, cargo ni factura/pago. La consulta repetida muestra H101 roja y nueve habitaciones verdes. [Opciones](evidence/288-opciones-disponibles-verdes.jpg), [preselección](evidence/289-tarjeta-reserva-preseleccionada.jpg), [escritorio](evidence/291-disponibilidad-verde-rojo-amplio.jpg) y [móvil](evidence/292-disponibilidad-verde-rojo-movil.jpg).
4. El DOM visible acredita fondos `rgb(252,236,238)` / `rgb(234,246,237)` con texto rojo/verde. Móvil de 390 × 844 sin desbordamiento del documento ni modal. La lectura inicial que incluyó diálogos ocultos se conserva identificada y se sustituye como evidencia de conteo por la lectura filtrada a tarjetas visibles. La ventana vuelve a su tamaño original y Recepción cierra sesión.

[action-context-browser.json](evidence/action-context-browser.json) conserva 27 eventos, con alcance incremental por bundle. [action-context-items-ui.json](evidence/action-context-items-ui.json) contrasta documentos y estados con lectura nativa: dos turnos cerrados, una reserva/asignación y cero movimientos financieros; tres consultas HTTP y dos salidas, todas 200, sin HTTP 500. Los datos no son generados por el inspector.

Tras restaurar aceptación y actualizar ambos sitios, se deja abierta Reservas en la demostración principal con una consulta de solo lectura. H105 ocupada aparece roja, las otras nueve verdes; H102/H103/H104 conservan «Limpieza actual: Sucia» sin confundirla con la disponibilidad del intervalo. [Vista entregada](evidence/293-disponibilidad-colores-demostracion.jpg) y [estado observado](evidence/action-context-main-handoff.json). No se crea otra reserva en principal.

## Conservación y alcance pendiente

Aceptación se restaura desde su respaldo con archivos y se migra a 0.8.4. La comparación estricta conserva 71 tablas/185 filas de negocio y 72/250 con Version; principal conserva 72/1246, dos archivos privados y fecha 19/10. [Verificación de fase](evidence/action-context-verification.json) vincula fuentes, capturas, versiones, compilación, servicios, idioma y protocolos. Frappe/ERPNext permanecen limpios. Los 380 casos nativos de beac44d son antecedente, **no una nueva ejecución de esta fase de interfaz**.

S04-16 continúa I: estos dos campos quedan comprobados; faltan reglas específicas y vistas secundarias del conjunto. Se conserva la revisión del contexto de acciones: un clic inmediato mientras se refresca tras confirmar reserva no abrió la consulta; posteriormente funciona. También una confirmación nativa visible dejó de resolver por nombre accesible tras varios diálogos, aunque la salida terminó usando el único diálogo visible. No se presenta como resuelta la incidencia previa de salida tras arqueo solo porque los dos turnos actuales completaron su salida.

La matriz mantiene **196 V, 6 I, 0 P y 16 R: 22 entradas abiertas**. Siguen las tareas secundarias por rol, contratos abstractos, otros entregables y ensayo final F26. OTA Airbnb/Booking permanece aplazada. Esta restauración del escenario no acredita reversión de una entrega final.
