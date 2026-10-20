# Devolución de garantías aplicadas

La versión 0.4.3 completa el circuito de devolución de fondos que ya salieron del pasivo de garantías. Un movimiento Guarantee Applied mantiene su Journal Entry de crédito del cliente; no vuelve a ser una garantía retenida ni otro ingreso de efectivo. Su devolución usa ese origen, separado de la devolución de la parte aún retenida.

## Fuente y documentos

refunds.original_funds lee las líneas nativas del cliente del Journal Entry presentado, exige garantía original vigente del mismo establecimiento/cliente/moneda y una cuenta/valoración inequívocas. Las referencias Sales Invoice indican lo aplicado a cada factura; las líneas sin referencia indican fondos aún disponibles. No se infiere disponibilidad desde el importe del pasivo ni desde el estado de la pantalla.

Si ya se facturó, la devolución utiliza Payment Entry contra una nota de crédito válida de esa factura y hasta la aportación restante del origen. Si aún hay crédito sin asignar a facturas, crea un Journal Entry del cliente/efectivo y reconcilia sus líneas mediante reconcile_against_document. Este controlador actualiza las referencias del Journal Entry original, incluso con su turno cerrado; conserva los importes/cuentas/tipo de cambio originales. Se mantienen los límites globales, por factura, crédito, moneda y revisión de 0.4.2.

La aplicación sigue consumiendo la garantía retenida aunque luego se devuelva como crédito del cliente. Una segunda Guarantee Refund no puede gastar esa parte de nuevo. La devolución del crédito no vuelve a debitar el pasivo ni crea otra entrada de caja. Las diferencias cambiarias se registran en los documentos estándar; el caso USD10 liquida NIO366.24 y contabiliza NIO3.76 al devolver con cambio 37.

close_financials incluye los fondos de aplicaciones todavía sin factura entre los créditos de cliente por aplicar, con su Journal Entry como fuente. Antes se contaban los Payment Entry disponibles pero ese crédito podía quedar fuera del saldo mostrado. Cuando se factura o devuelve, las referencias estándar reducen ese importe. No se suman de nuevo a garantías retenidas ni dinero recibido.

## Interfaz y aislamiento de asistentes

El selector distingue Garantía de Garantía aplicada por fecha, importe y documento estándar. La aplicación muestra Garantía aplicada (sin nuevo ingreso). La revisión de devolución diferencia aplicada a factura de aplicada aún sin facturar y explica qué concepto elegir. Aplicar garantía reutiliza la descripción legible del recibo.

El filtro de fuentes de devolución de 0.4.2 también se aplicaba a otros diálogos con source_payment y podía quitar una devolución de tarjeta de su liquidación. Ahora exige que el formulario tenga el concepto Refund; los demás asistentes conservan sus opciones. Una prueba JS reproduce esa selección de liquidación para evitar que se vuelva a filtrar.

Cuatro casos nativos nuevos comprueban aplicación antes/después de factura, devolución parcial sin asignar y facturación de lo restante, pasivo separado/prevención de doble devolución, USD con cambio, aprobación y turno original cerrado con reintento único. Conservan documentos y saldos nativos. Dos JS adicionales cubren la fuente de garantía aplicada y el aislamiento de asistentes; los demás casos previos siguen formando parte de la batería completa.

El contraste del POS desde las Pages continúa por separado. No se declara completo el capítulo de todas las correcciones financieras ni la aplicación entera con este circuito.

## Verificación final de 0.4.3

La batería posterior a la restauración aprueba **169 pruebas (155 integración y catorce puras)** y **26 JS (veinticuatro Desk y dos portal)**; cuatro casos nativos y dos JS nuevos respecto de 165/24. Assets compilados y ambos sitios migrados. La aplicación desde Page descubrió que faltaba seleccionar turno cuando gerencia no tenía uno propio: se añadió el selector abierto y se repitió el recorrido.

En aceptación se prepararon estancia H101 y recibo de garantía C$1500 por API. Gerencia aplicó los C$1500 desde Caja; el esperado siguió en C$1500 y se verificó crédito sin asignar por ese importe, separado del pasivo ya cero. Después se prepararon factura y nota mediante controladores nativos. Gerencia seleccionó el origen legible, revisó y confirmó la devolución desde Page. El Payment Entry de salida deja crédito y esperado en cero; el Journal Entry original mantiene su asignación de C$1500 a la factura. Capturas 79–81 y guarantee-items-ui.json. No se presenta la preparación de factura/nota como acciones de Page.

La sesión terminó en Login y se cerró el servidor temporal 8089. La restauración Bench con archivos coincide en **70 tablas/185 filas** antes y después de la batería. guarantee-final-state.json acredita aceptación vacía, HTTP principal 200, servicios activos y **36 tablas nativas principales sin cambios**. guarantee-main-financial-read.json acredita lectura del resumen financiero de ambas propiedades, incluyendo crédito convertido, sin modificaciones. architecture-current.json conserva ambos núcleos limpios. No se sustituyen con esta restauración las pruebas finales de reversión de código/archivo privado.

La matriz conserva texto/huella y 218 entradas: **49 V, dos I y 167 R**. S08-10 queda contrastado con garantía retenida, aplicación autorizada, devolución original y del crédito convertido; S09-08 sigue parcial por las notas POS desde las Pages. El objetivo continúa activo.
