# Notas POS con recibos adicionales, versión 0.4.5

La revisión distingue el dinero que devuelve la nota ahora del crédito que queda por devolver mediante otros recibos. Muestra concepto, fecha, importe disponible y documento ERPNext; las claves internas de HS Payment no se usan como descripción. El resultado conserva la explicación del crédito pendiente y dirige a Cobrar → Devolución con el recibo original y la nota recién creada. Un crédito pendiente no se presenta como dinero ya entregado.

## Documentos, valoración y límites

La nota sigue siendo una Sales Invoice de devolución estándar con inventario y saldo propios. El Journal Entry devuelve únicamente la aportación neta del recibo POS, compensa la deuda correspondiente y revierte el ajuste original. El crédito respaldado por otros recibos queda pendiente. Si todo se cobró por otro recibo, se crea la nota sin un asiento vacío.

Los otros fondos se identifican mediante referencias nativas de Payment Entry o Journal Entry a la factura, y su HS Payment vigente del mismo establecimiento y cliente. Se admiten cobros, anticipos y garantías aplicadas, conservando las comprobaciones de origen, compañía, cuenta y moneda. El crédito restante no puede exceder los fondos identificados. Se mantiene el rechazo de valoración POS incoherente y de diferencias sin origen, sin convertirlas en ganancias de cambio.

Cobrar → Devolución permite devolver ese recibo contra la nota, también cuando el cobro nativo original no pertenece a una estancia o reserva. Esta excepción exige un origen de devolución real; no habilita nuevos cobros sin visita. El Payment Entry de salida conserva la valoración histórica del cliente, el cambio actual del dinero, el crédito disponible y los límites globales y por factura del recibo. No cambia el importe ni las asignaciones del original.

Si un recibo en otra moneda se distribuyó entre varias facturas, el equivalente monetario redondeado del límite exacto liquida ese límite contable. La última devolución absorbe el residuo del recibo. Por ejemplo, USD10/NIO366.24 aplicado como 100 y 266.24 se devuelve como USD2.73 y USD7.27 y liquida ambas notas sin centavos pendientes.

Al calcular lo ya devuelto del POS, se excluyen los pagos de devolución que tienen un origen HS Payment explícito. Esos pagos consumen su recibo adicional. Esta separación permite dos notas parciales sucesivas y evita descontar dos veces un mismo importe. Caja, arqueo, conciliación y cierre conservan la exclusión de documentos ya representados por HS Payment.

## Pruebas y recorrido

La batería completa aprueba **187 casos (173 integración y catorce puros)**, cuatro más que 0.4.4; los JS aprueban **29 (veintisiete Desk y dos portal)**. El caso anterior que rechazaba el circuito compuesto ahora comprueba su liquidación por origen, reintento y originales conservados. Los nuevos casos cubren parciales sucesivas con devolución intermedia, POS financiado solo por otro recibo, un recibo USD compartido entre facturas y garantía aplicada al POS sin reabrir su pasivo. Se conservan los casos de stock, permisos, valoración incoherente, redondeo, revisión obsoleta y reversión de las fases anteriores.

La preparación sintética usa los controladores ERPNext: venta de dos aguas por C$60, cobro POS de C$30 y otro Payment Entry de C$30. API cierra el turno original con 160 y abre otro con fondo 160. La preparación de venta, recibo y turnos no se atribuye a acciones de interfaz.

Gerencia realiza desde Caja la nota completa: revisión de C$60, devolución inmediata de C$30 y crédito pendiente de C$30, capturas 87–88. Desde Cobrar devuelve el segundo recibo contra la nota, captura 89. Arquea y cierra el nuevo turno con esperado/contado 100 y diferencia cero, mientras el original conserva 160, capturas 90–91. La inspección nativa acredita crédito final cero, stock neto cero, documentos/asignaciones originales conservados y diferencia de cambio cero. El cierre financiero muestra POS +30/-30; el segundo recibo y su devolución se cuentan por HS Payment, sin repetirse como POS. La conciliación no encuentra efectivo sin origen.

La sesión llega a Login, se cierra su pestaña y se detiene 8089. Bench restaura el respaldo con archivos; la verificación posterior acredita **70 tablas/185 filas idénticas**. Se intentó verificar antes de que el proceso de restauración terminara y aún no existía su recibo; tras esperar su finalización con código cero, la comparación completa pasó. Ambos sitios están migrados, los assets compilados y web/worker actualizados. Tras reiniciarse WSL se restablecieron los servicios y se comprobaron HTTP 200 y puertos. Las **36 tablas nativas principales permanecen intactas** y la lectura financiera de ambas propiedades funciona sin modificaciones. Los núcleos Frappe/ERPNext siguen limpios.

La evidencia está en mixed-native-tests.xml/log, mixed-js-tests.log, mixed-items-ui.json, mixed-ux-restored.json, mixed-final-state.json y mixed-main-financial-read.json. El PDF de arqueo ya acreditado en 0.4.4 conserva su formato; esta fase verifica la separación adicional en datos y pantalla, sin atribuirle una nueva exportación PDF.

S09-08 pasa a V. La matriz conserva texto, huella y 218 entradas: **50 V, una I y 167 R**. La traducción completa, el contraste individual de los demás capítulos y la recuperación final con archivo privado y reversión de código siguen pendientes. El objetivo general permanece activo.
