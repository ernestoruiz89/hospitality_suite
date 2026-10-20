# Precio histórico, reservas y nombres legibles — 0.6.5

«Ver cálculo del precio», en cada cargo de la cuenta, despliega la tarifa que fue aceptada. Para Hotel muestra noches, regla de temporada, base, personas y camas adicionales. Para Por tiempo muestra bloque, tolerancia, fracción y tiempo adicional facturable. La Page y el PDF usan la misma proyección de `quote_snapshot`; no consultan el tarifario actual ni recalculan el cargo.

Una extensión o cambio de habitación distingue el cargo de diferencia de la cotización completa que sirve de referencia. Descuento, cortesía y recargo conservan signo y motivo; el desglose de origen no representa otro cobro. Los cargos por noche explican solamente su noche. Folios compartidos conservan el alcance por estancia. Un registro antiguo sin información suficiente lo indica y mantiene visible su importe registrado. Programados y revertidos explican su tratamiento.

El cálculo previo a confirmar continúa en la cotización. Al revisar la cuenta, el detalle queda plegado para facilitar la lectura; puede abrirse con teclado. El PDF imprime el cálculo completo y resume las referencias de los ajustes para evitar duplicarlo. Las dos cuentas sintéticas revisadas caben en una página cada una: Hotel C$3,800 menos descuento C$100, y Por tiempo C$600 más C$150. Se cambiaron tarifas actuales después de aceptar; los desgloses conservaron las reglas originales.

La terminología visible usa «Hotel», «Por tiempo» y «Hotel y por tiempo». Los valores persistidos `Hotel`, `Motel`, `Mixed`, claves de reportes y fórmulas permanecen compatibles. «Motel Luna Demo» es un nombre comercial y no se reescribe. El diccionario de estas etiquetas no acredita por sí solo toda la traducción de la aplicación.

## Consultar y seleccionar una habitación

En Buscar disponibilidad, consulte categoría, cantidad, personas e intervalo. Si alcanza el cupo y hay habitaciones físicas disponibles, cada número es un botón accesible. Al pulsarlo abre Nueva reserva con las fechas aceptadas por el servidor, categoría, personas y habitación elegida. El formulario mantiene los segundos y el desplazamiento de zona horaria al revisar un intervalo sin editarlo.

Si se solicitaron varias habitaciones, se conserva esa cantidad: la elegida ocupa la primera solicitud y las otras quedan por asignar en la misma categoría. Un resultado obsoleto, filtros editados, consulta pendiente, cambio de establecimiento o permiso insuficiente impiden reutilizarlo. Abrir el formulario no guarda, retiene ni confirma: el operador elige pagador y revisa precio/disponibilidad antes de aceptar. Los enlaces nativos de categoría y habitación muestran títulos desde el bootstrap autorizado y conservan sus valores internos.

## Ver una reserva

El resumen conserva huésped, pagador, fechas, modalidad, canal, importe reservado y habitaciones/personas/camas. Cada estancia asociada muestra su habitación actual, estado y acceso a su cuenta según permiso. Funciona tras registrar entrada aunque ya no haya asignaciones pendientes; una reserva grupal parcialmente ingresada conserva sus acciones pendientes. El modo discreto muestra «Huésped registrado». Los estados se presentan en español; no se usa el hash como resumen.

El importe reservado se distingue expresamente del saldo de la cuenta, que incorpora consumos, ajustes, impuestos y pagos. Las notas se escapan y conservan saltos de línea. Confirmadas y retenidas muestran el mismo resumen antes de las acciones; las que no tienen acciones muestran Cerrar e impresión. Los nuevos números RES se incluyen como referencia legible. [Series documentales](SERIES_DOCUMENTALES.md) explica la compatibilidad con identificadores anteriores.

## Evidencia y límites

Los casos nativos cubren noches estacionales, suplementos, cambios de maestros posteriores, bloque/fracciones, segunda extensión, artículo histórico compartido, cambio de habitación, ajustes, folio grupal, impresión escapada, permisos y precisión monetaria. También cubren resumen tras entrada, grupos sin asignar, discreción y series. Las pruebas JS cubren detalle plegado, datos escapados, preselección completa, respuestas obsoletas, permisos, apertura única y estados de reserva.

Capturas 128–130: cálculo en escritorio/móvil y modalidad. 131–132: resumen de reserva en escritorio y 390×844, ancho de contenido 344 px sin desborde. 133–135: botones de habitaciones, fechas exactas 24/10/2026 10:27:35 → 25/10/2026 13:27:35, M103, Estándar y dos personas. 136–137: ambas páginas PDF renderizadas y revisadas. `tariffs-browser.json`, `booking-details-browser.json` y `tariffs-items-ui.json` delimitan el recorrido: fixture API sintético y consultas desde Page sin guardar nuevas operaciones. La aceptación general de todos los flujos y roles sigue abierta.

Los PDF se exportaron con el motor nativo de Frappe/wkhtmltopdf. La ejecución CLI utilizó `http://127.0.0.1:8089` solamente en ese proceso para cargar assets, sin persistir host ni cambiar DNS. Este recorrido no acredita la descarga de PDF desde el navegador. Los documentos de prueba no contienen datos reales.
