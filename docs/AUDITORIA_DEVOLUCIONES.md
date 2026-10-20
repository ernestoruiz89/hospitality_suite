# Devolución de anticipos aplicados

La versión 0.4.2 permite devolver desde Caja un anticipo que ya se aplicó a una factura, contra su nota de crédito estándar. Corrige la ruta que antes rechazaba siempre un origen Advance, incluso cuando se seleccionaba una nota válida. La parte no aplicada sigue utilizando Journal Entry y conciliación estándar; lo aplicado utiliza Payment Entry de salida contra Sales Invoice de devolución.

## Fondos, documentos y revisión

refunds.plan comprueba el Payment Entry original presentado, cliente, compañía, establecimiento, moneda y cuenta del cliente. El medio de devolución utiliza la moneda original. Controla el importe total recibido menos devoluciones vigentes. Si se elige nota de crédito, exige documento presentado de ese cliente/cuenta/establecimiento, referencia a una factura del movimiento original, importe aplicado por ese movimiento a esa factura menos devoluciones previas y saldo negativo disponible de la nota. La disponibilidad de otra factura o la parte todavía sin aplicar no amplía ese límite.

El Payment Entry original conserva sus importes, asignaciones y turno. No se deshace la aplicación para devolver el dinero ni se cambia un importe contabilizado. La nueva salida conserva source_payment, nota de crédito y auditoría. Repetir la misma solicitud devuelve el mismo resultado; el servidor vuelve a comprobar fondos y documento. La revisión conserva las versiones/saldos originales dentro de su aceptación: un segundo reembolso vuelve obsoleta una revisión anterior aunque el tipo de cambio no haya variado. Una cancelación autorizada del Payment Entry de devolución cancela su registro operativo y vuelve a liberar la disponibilidad comprobada por los controladores nativos.

## Monedas y fracciones

La parte que se liquida en la cuenta del cliente procede proporcionalmente del valor contable original. El efectivo de salida usa el cambio actual. ERPNext calcula la diferencia y registra su cuenta configurada; se admite la cuenta de cambio del establecimiento o la predeterminada de Company. Un Journal Entry de anticipo disponible también conserva esa valoración y equilibra el cambio mediante sus líneas estándar. No se escribe directamente en GL Entry ni Payment Ledger Entry.

La última devolución absorbe el residuo de redondeo de la moneda del cliente. El caso de USD0.03, valorado en NIO1.10, devuelve tres veces USD0.01 y liquida NIO0.37/0.37/0.36. No quedan centavos contables sin origen ni se supera el importe recibido. Las devoluciones parciales de cantidades de artículos siguen respetando las unidades nativas: el fixture de cantidad 0.25 utiliza Hour, en lugar de una unidad que exige enteros.

## Presentación y alcance

Caja identifica el origen por concepto, fecha, importe/moneda y recibo estándar, conservando su clave interna al enviar. Elimina las devoluciones y otros conceptos incompatibles del selector. La revisión distingue anticipo disponible, anticipo aplicado y cobro facturado; muestra nota de crédito, valor liquidado en la cuenta del cliente y diferencia de cambio. Los textos y valores se escapan antes de insertarlos. El recibo que devuelve la operación se presenta mediante su documento ERPNext, sin mostrar la clave aleatoria de HS Payment.

Las pruebas nativas cubren parcial/reintento/revisión obsoleta/turno anterior cerrado, asignación de un anticipo a dos facturas con límites independientes, crédito parcial y remanente sin aplicar, USD con cambio distinto antes/después de aplicar, permiso de aprobación y residuo de moneda. Las dos nuevas pruebas JS comprueban etiquetas/valores del selector y separación/escape de importes de la revisión. Los resultados finales, recorrido real y restauración se conservan en las evidencias refund-*.

Este contraste no declara completas todas las correcciones financieras posibles. Continúan la revisión de fondos de garantías ya aplicadas, las notas de crédito POS desde las Pages, los restantes capítulos y la recuperación final del conjunto de demostración. Las pruebas y la restauración del sitio de aceptación no sustituyen esa auditoría.

Resultado final: **165 pruebas aprobadas (151 integración y catorce puras)**, seis nuevas sobre la base de 159; **24 JS (veintidós Desk y dos portal)**, dos nuevas sobre 22. El primer fixture de crédito fraccionario usó Nos y fue rechazado por su validación de enteros; se cambió a la unidad Hour antes de emitir la factura. Las pruebas finales incluyen cancelar una devolución y volver a usar solo los fondos liberados.

En el sitio de aceptación se prepararon estancia H101, anticipo C$1500, factura y nota de crédito mediante API/controladores. Gerencia seleccionó el origen por recibo, revisó y confirmó la devolución desde la Page: capturas 76–78 y refund-items-ui.json. El Payment Entry original mantiene su asignación de 1500, la nota queda con saldo cero y el esperado de caja vuelve a cero. También se retiraron claves de reserva/grupo de los selectores, respetando la descripción y modo discreto existentes. La revisión dice Entregado para la devolución.

La sesión salió hasta Login y el servidor temporal 8089 se detuvo. Bench restauró el respaldo previo y sus **70 tablas/185 filas** coinciden antes y después de la batería final. refund-final-state.json confirma las **36 tablas nativas principales sin cambios**, servicios/HTTP y sitio de aceptación vacío. No hay segundo Socket.IO en esa copia. La matriz conserva las 218 entradas/texto/huella: **48 V, dos I y 168 R**; S09-08 pasa a contraste parcial y mantiene explícito lo pendiente. El objetivo sigue activo.
