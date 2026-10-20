# Configuración contable y conciliación

## Cuentas y centros de costo por servicio

Configuración → 18. Contabilidad por servicio permite elegir ingreso, gasto y centro de costo de la sede y excepciones por Item. Un campo vacío hereda de la sede y después de ERPNext. Las cuentas deben pertenecer a la compañía, estar habilitadas, no ser grupos y tener naturaleza/moneda base adecuadas. No se cambian los valores compartidos de los artículos. Los registros nuevos usan esa clasificación; las notas de crédito y cancelaciones conservan la del original. No se reclasifica historia al guardar la configuración.

El costo de una entrega de venta se registra en Stock Entry y el ingreso en Sales Invoice. Una compra sin inventario usa su gasto configurado; con inventario, ERPNext conserva sus cuentas de existencias/recepción. Los egresos y mermas con categoría explícita usan la cuenta de esa categoría. Véase [auditoría de contabilidad por servicio](AUDITORIA_CONTABILIDAD_SERVICIOS.md).

## Fuentes de verdad

ERPNext es el único libro mayor y el único inventario. HS Charge, HS Payment y HS Service Request mantienen origen y flujo operativo; no sustituyen GL Entry, Payment Ledger Entry o Stock Ledger Entry. La app no escribe directamente esos libros.

HS Property debe apuntar a Company, Cost Center, Warehouse, artículos y cuentas existentes. La cuenta por cobrar debe ser Receivable; garantías debe ser un pasivo. Ambas usan la moneda del establecimiento. Los medios de pago enlazan Mode of Payment y una cuenta de la misma compañía/moneda. No se crean cuentas ni tasas fiscales silenciosamente en la instalación normal.

Configure la plantilla tributaria, incluidos o añadidos, y confirme su revisión antes de habilitar finanzas. El formato HS Factura es configurable y usa valores del Sales Invoice estándar; la implementación debe validar sus datos fiscales y formato aplicable. Ninguna tasa del conjunto de pruebas constituye configuración fiscal de un cliente.

## Momento de reconocimiento

Los artículos de alojamiento/tiempo se seleccionan por establecimiento y se conservan en las cotizaciones nuevas. Las horas adicionales de motel se registran por separado con su importe/horas aceptados, manteniendo clasificación de alojamiento para indicadores. La extensión y el exceso de salida cobran solo el incremento. La migración conserva el artículo anterior en propiedades existentes y no recategoriza documentos. Alimentación, minibar, lavandería de huésped y otros consumos usan Item Price vigente por lista/moneda/unidad/pagador; la entrega de stock sigue en Stock Entry y la factura no repite la salida.

Se conserva el importe aceptado de alojamiento/consumos y se convierte en contabilidad al presentar Sales Invoice. La política Al ingresar genera el cargo completo al entrar. Por noche conserva cada noche como Programada y Preparar cierre del día genera las de la fecha operativa y las vencidas una sola vez. Los importes futuros se muestran aparte y no integran la producción ordinaria; el saldo incluye la obligación aceptada completa. Facturar o salir liquida también las noches programadas. No se implementa otro devengo diario ni un asiento paralelo de alojamiento. Repetir el cierre no reconoce nuevamente lo facturado. Véase CARGOS_PERIODICOS.md para identidad de origen, extensiones, recuperación y límites de interfaz.

Facturar cuenta desde Pages revisa valores nativos, impuestos, anticipos y saldo antes de emitir; admite cero sin cobro ni salida. La cotización no guarda factura ni aplica conciliaciones y la confirmación rechaza valores que hayan cambiado. Véase FACTURACION_DESDE_PAGES.md.

La factura de folio toma cargos pendientes y programados, conserva su origen y los marca facturados después de presentar el documento estándar. La cuenta compartida puede reunir varias estancias de una reserva y un único pagador. Los descuentos/cortesías de cargos pendientes se incluyen en la línea estándar con sus referencias; no necesitan habilitar tarifas negativas en Selling Settings. Si el origen ya está contabilizado, la corrección financiera requiere documentos de reversión.

## Anticipos

Cada establecimiento configura anticipos y garantías como manuales, con autorización de gerencia o deshabilitados para nuevos ingresos. La cotización y la contabilización aplican la política; la autorización conserva actor y regla en auditoría. También se valida la presentación nativa de Payment Entry sin referencias y Journal Entry que ingresa al pasivo de garantías. Separe el cobro de una factura del anticipo sin aplicar en documentos distintos. Deshabilitar ingresos conserva la devolución/aplicación autorizada de fondos existentes.

Un anticipo es un Payment Entry del cliente y queda sin asignar hasta su aplicación. No genera automáticamente ingreso por alojamiento. Al facturar, ERPNext aplica los anticipos de esa reserva/estancia y pagador, respetando compañía, moneda y cuenta.

También se concilian anticipos recibidos después de existir una factura. La app utiliza Payment Reconciliation de ERPNext. Actualizar referencias de un anticipo histórico puede ser válido con el turno original cerrado; no cambia el importe, moneda, cuenta o caja originales. No puede usarse esa excepción para cambiar dinero de un turno cerrado.

Para devolver un anticipo no aplicado, se utiliza un Journal Entry del cliente/efectivo y conciliación estándar con el Payment Entry original, que es el mecanismo verificado en ERPNext 16.51.1. Un anticipo aplicado o cobro facturado se devuelve mediante Payment Entry de salida contra una nota de crédito real de la factura de origen. Se comprueba el límite aplicado por ese movimiento a cada factura, el crédito pendiente y los fondos originales menos devoluciones vigentes. No se deshace la asignación histórica.

La devolución liquida el valor original en la cuenta del cliente y entrega el dinero al cambio actual, con diferencia cambiaria estándar. La última devolución absorbe el residuo de redondeo. Una revisión obsoleta se rechaza aunque el tipo de cambio sea el mismo. Caja presenta el origen por fecha, importe y recibo estándar, y separa el valor liquidado de la conversión actual. Véase AUDITORIA_DEVOLUCIONES.md.

## Garantías reembolsables

La recepción de garantía genera Journal Entry: débito al medio de pago y crédito al pasivo configurado. El retorno invierte esa obligación por el importe disponible. La aplicación autorizada debita el pasivo y acredita la cuenta del cliente, con referencia a factura o como anticipo estándar conciliable.

Una aplicación no vuelve a aumentar el efectivo esperado. Se conserva el documento y la valuación de la obligación original; las diferencias de cambio se equilibran mediante la cuenta estándar de ganancia/pérdida de cambio configurada. Se probó una garantía de USD10 devuelta con un cambio distinto: la obligación original queda en cero y la diferencia de C$3.76 se registra en la cuenta de cambio. Otras combinaciones de moneda/precisión necesitan la ampliación indicada en la matriz.

## Monedas, caja y correcciones

El cierre conserva producción, facturación, cobros y saldos diferenciados por moneda. Facturación usa fecha contable; cobros usan fecha operativa registrada/auditada. Los cobros POS nativos se leen de sus cuentas de pago estándar, netos de vuelto. Los saldos de facturas y anticipos nativos usan moneda de la cuenta del cliente; créditos a favor y facturas pendientes se muestran separados hasta conciliarlos. Los movimientos históricos sin fecha acreditada se advierten sin inventarla. Ver resumen e imprimir utilizan el JSON conservado; no vuelven a sumar saldos actuales. Véase AUDITORIA_CIERRE_POLITICAS.md.

Cada movimiento conserva moneda del medio, importe, tipo de cambio y equivalente base. La conversión a la moneda de la cuenta del cliente se almacena en Payment Entry. ERPNext obtiene los cambios desde Currency Exchange/configuración estándar; el navegador no impone una tasa.

El arqueo separa monedas. Fondo más cobros/anticipos/garantías en efectivo, menos devoluciones, retiros, egresos y pagos a proveedores en efectivo, produce el esperado. La aplicación de garantía y la liquidación bancaria se excluyen del efectivo porque no son movimientos de caja. Los medios no efectivos no aumentan el efectivo físico.

Las facturas estándar Sales Invoice con is_pos aportan directamente el neto real de sus cuentas de pago/vuelto desde GL Entry, asignado a su turno. No generan otro HS Payment ni Payment Entry. Caja, arqueo impreso y cierre diario comparten esa lectura por moneda. Se exige turno abierto, medio inequívoco y referencia según política; una factura histórica sin turno queda en conciliación. Una corrección después del cierre conserva el conteo y muestra la diferencia. El Supervisor puede aprobar diferencias de arqueo mediante cash_approve; esa autorización no concede otras aprobaciones financieras. Véase AUDITORIA_CAJA_POS.md.

Configure el medio no efectivo con cuenta de compensación, banco de liquidación en la moneda del medio, gasto de comisión y activo separado para retenciones en moneda base. El cobro conserva el bruto y un snapshot de porcentajes/comisión fija. Registrar liquidación exige revisar una cotización y una referencia del extracto: Journal Entry debita banco neto, comisión y retención y acredita compensación. No genera otra factura ni otro cobro.

Las liquidaciones parciales prorratean el costo fijo/porcentajes del bruto original; la última absorbe el residuo de redondeo. Cambiar la política afecta a cobros nuevos. La compensación se cancela por su valor histórico; banco/gastos usan el cambio actual y la cuenta estándar de diferencia de cambio. Se verificó USD con saldo de compensación cero y ganancia de C$3.76. La conciliación comprueba bruto, neto, comisión, retención y valoración histórica.

Las devoluciones tienen su política configurable de comisión y liquidación de salida: el banco se acredita por bruto devuelto más comisión. La retención original no se recupera automáticamente; una devolución tributaria depende de la liquidación/documentación real del proveedor. Para anular un cobro con liquidaciones vigentes, primero revierta esas liquidaciones con autorización y motivo. No hay pasarela activa que liquide importes por su cuenta.

## Compras y egresos

Registrar egreso usa una categoría con cuenta Expense de la compañía en moneda base y límite por operación (cero = sin límite). Solo efectivo disponible del propio turno; otro responsable exige autorización gerencial. El Journal Entry registra gasto y salida de caja, sin ajustar una factura de cliente.

Orden de compra conserva precio/impuestos aceptados. Purchase Receipt incorpora la recepción completa o parcial; Purchase Invoice se crea desde lo recibido con update_stock=0. No duplica inventario. El pago se convierte a la moneda de la cuenta del proveedor, aplica la factura estándar y crea un único movimiento del turno. Pagos nativos de proveedor sobre los medios configurados también se sincronizan; una devolución de proveedor se gestiona con el flujo estándar de devolución de compra y su conciliación, no con un cobro de huésped.

Los mínimos se almacenan en Item Reorder por almacén. HS Stock Policy solo clasifica uso operativo; Bin/SLE siguen siendo la verdad de cantidades/valoración. Traslados y reposición de ropa usan Material Transfer; limpieza/merma usan Material Issue con gasto/centro de costo; el conteo autorizado usa Stock Reconciliation con valoración existente y rechazo si cambió la existencia cotizada. Los activos fijos conservan el módulo Asset estándar. Movimientos de inventario proyecta SLE y origen, cantidades, variación de valor, uso y centro de costo, sin otro libro de inventario.

Cancelar o devolver exige autorización y motivo. Una corrección posterior al cierre conserva el arqueo original; Conciliación compara el esperado actual con ese snapshot y muestra la diferencia para revisión. No se eliminan registros para ocultarla.

## Conciliación e indicadores

Conciliación compara cargos/ajustes con líneas de facturas presentadas, movimientos HS con sus documentos vigentes y efectivo actual con arqueos conservados. Las diferencias tienen origen y documento explícitos y bloquean el cierre diario. La Page pagina 50 filas; las consultas autorizadas y las exportaciones examinan el conjunto completo, sin el antiguo límite de 1 000.

Los documentos creados, presentados o cancelados desde ERPNext también pasan por los hooks de validación y sincronización. Para una operación externa de estancia deben indicarse establecimiento, estancia o reserva, cuenta y turno cuando corresponda. Una línea no puede facturar de nuevo un cargo existente.

Hotel: noches únicas comercializadas por habitación y fecha, ADR = alojamiento neto facturado / noches; RevPAR = alojamiento neto / noches comercializables. Motel: horas reales unidas por habitación desde la entrada real, horas comercializables menos bloqueos y duración real de las visitas. Entradas es el total; rotaciones por habitación = entradas / habitaciones habilitadas con alguna hora comercializable en el período. El ticket mostrado se refiere a alojamiento neto. Las cortesías ocupan con ingreso cero; impuestos, anticipos, garantías y otros servicios se excluyen de ADR/RevPAR. Denominador cero devuelve cero. No se suman noches y horas ni reserva y estancia como dos ocupaciones.

La producción operativa se informa separada del ingreso neto facturado y del efectivo cobrado. El neto de alojamiento se distribuye al período de servicio a partir del snapshot aceptado y de líneas presentadas, incluidas notas de crédito; no representa un nuevo devengo contable.

Producción incluye penalizaciones de cancelación/no presentación y líneas de facturas ERPNext sin estancia que todavía no estén representadas por cargos o ventas directas. Solo suma documentos presentados, incluyendo notas de crédito con signo negativo; no duplica líneas ya enlazadas. El importe de línea y su neto sin impuestos son conceptos distintos. La fecha operativa procede del evento inmutable de presentación; para una factura histórica sin ese evento se usa su fecha contable como referencia disponible. Los totales se conservan separados por moneda; `production` resume exclusivamente la moneda del establecimiento y `production_by_currency` conserva todas.

Una nota de crédito de factura POS nativa conserva su `update_stock`; ERPNext registra la devolución física de esa misma factura. Las entregas operativas mediante Stock Entry mantienen `update_stock=0` en factura y nota de crédito, y devuelven existencias por su flujo de consumo autorizado.

Arqueos por moneda lee esperado y denominaciones del snapshot de cierre, sin convertir ni sumar monedas. Un turno abierto muestra esperado actual y deja conteo/diferencia pendientes. Una diferencia no crea un asiento compensatorio. Productividad de limpieza agrupa por responsable: total, pendientes, finalizadas, finalizadas con duración positiva, minutos acumulados/media y tareas por hora registrada. Solo las tareas finalizadas con inicio/fin válidos aportan duración; esta incluye esperas de inspección y no representa horas de jornada laboral.

La garantía ya aplicada es crédito del cliente respaldado por su Journal Entry. Su devolución usa el concepto Refund con ese origen: Payment Entry contra nota de la factura a la que contribuyó, o Journal Entry y conciliación estándar entre asientos para lo no asignado. El pasivo ya consumido por la aplicación no se reabre; la garantía aún retenida conserva Guarantee Refund. El cierre incluye el crédito aplicado aún sin facturar entre fondos disponibles del cliente, con su Journal Entry como fuente, sin duplicar efectivo. Véase AUDITORIA_GARANTIAS_APLICADAS.md.

Las notas de originales Sales Invoice POS creadas desde Caja son devoluciones estándar con saldo propio y update_stock del original. Un Journal Entry enlazado liquida la nota, compensa la deuda correspondiente del original y devuelve el neto real de sus medios. Conserva cuenta/valoración del cliente, aplica cambio actual al dinero y registra diferencia/redondeo estándar; la reversión del write-off original permanece separada. No crea HS Payment ni otro Payment Entry ni modifica el recibo original. Los asientos enlazados se incluyen una vez en caja, arqueo, cierre y conciliación desde sus GL vigentes; los ya representados por HS Payment quedan excluidos de esa proyección. Véase AUDITORIA_NOTAS_POS.md.
