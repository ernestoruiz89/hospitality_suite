# Configuración contable y conciliación

## Fuentes de verdad

ERPNext es el único libro mayor y el único inventario. HS Charge, HS Payment y HS Service Request mantienen origen y flujo operativo; no sustituyen GL Entry, Payment Ledger Entry o Stock Ledger Entry. La app no escribe directamente esos libros.

HS Property debe apuntar a Company, Cost Center, Warehouse, artículos y cuentas existentes. La cuenta por cobrar debe ser Receivable; garantías debe ser un pasivo. Ambas usan la moneda del establecimiento. Los medios de pago enlazan Mode of Payment y una cuenta de la misma compañía/moneda. No se crean cuentas ni tasas fiscales silenciosamente en la instalación normal.

Configure la plantilla tributaria, incluidos o añadidos, y confirme su revisión antes de habilitar finanzas. El formato HS Factura es configurable y usa valores del Sales Invoice estándar; la implementación debe validar sus datos fiscales y formato aplicable. Ninguna tasa del conjunto de pruebas constituye configuración fiscal de un cliente.

## Momento de reconocimiento

Se conserva como cargo operativo el importe aceptado de alojamiento/consumos. Se convierte en contabilidad al presentar Sales Invoice. No se implementa otro devengo diario ni un asiento paralelo de alojamiento. Repetir el cierre no reconoce nuevamente lo facturado.

La factura de folio toma cargos pendientes, conserva su origen y los marca facturados después de presentar el documento estándar. La cuenta compartida puede reunir varias estancias de una reserva y un único pagador. Los descuentos/cortesías de cargos pendientes se incluyen en la línea estándar con sus referencias; no necesitan habilitar tarifas negativas en Selling Settings. Si el origen ya está contabilizado, la corrección financiera requiere documentos de reversión.

## Anticipos

Un anticipo es un Payment Entry del cliente y queda sin asignar hasta su aplicación. No genera automáticamente ingreso por alojamiento. Al facturar, ERPNext aplica los anticipos de esa reserva/estancia y pagador, respetando compañía, moneda y cuenta.

También se concilian anticipos recibidos después de existir una factura. La app utiliza Payment Reconciliation de ERPNext. Actualizar referencias de un anticipo histórico puede ser válido con el turno original cerrado; no cambia el importe, moneda, cuenta o caja originales. No puede usarse esa excepción para cambiar dinero de un turno cerrado.

Para devolver un anticipo no aplicado, se utiliza un Journal Entry del cliente/efectivo y conciliación estándar con el Payment Entry original, que es el mecanismo verificado en ERPNext 16.51.1. Un cobro facturado se devuelve contra nota de crédito real.

## Garantías reembolsables

La recepción de garantía genera Journal Entry: débito al medio de pago y crédito al pasivo configurado. El retorno invierte esa obligación por el importe disponible. La aplicación autorizada debita el pasivo y acredita la cuenta del cliente, con referencia a factura o como anticipo estándar conciliable.

Una aplicación no vuelve a aumentar el efectivo esperado. Se conserva el documento y la valuación de la obligación original; las diferencias de cambio se equilibran mediante la cuenta estándar de ganancia/pérdida de cambio configurada. Se probó una garantía de USD10 devuelta con un cambio distinto: la obligación original queda en cero y la diferencia de C$3.76 se registra en la cuenta de cambio. Otras combinaciones de moneda/precisión necesitan la ampliación indicada en la matriz.

## Monedas, caja y correcciones

Cada movimiento conserva moneda del medio, importe, tipo de cambio y equivalente base. La conversión a la moneda de la cuenta del cliente se almacena en Payment Entry. ERPNext obtiene los cambios desde Currency Exchange/configuración estándar; el navegador no impone una tasa.

El arqueo separa monedas. Fondo más cobros/anticipos/garantías en efectivo, menos devoluciones, retiros, egresos y pagos a proveedores en efectivo, produce el esperado. La aplicación de garantía y la liquidación bancaria se excluyen del efectivo porque no son movimientos de caja. Los medios no efectivos no aumentan el efectivo físico.

Configure el medio no efectivo con cuenta de compensación, banco de liquidación en la moneda del medio, gasto de comisión y activo separado para retenciones en moneda base. El cobro conserva el bruto y un snapshot de porcentajes/comisión fija. Registrar liquidación exige revisar una cotización y una referencia del extracto: Journal Entry debita banco neto, comisión y retención y acredita compensación. No genera otra factura ni otro cobro.

Las liquidaciones parciales prorratean el costo fijo/porcentajes del bruto original; la última absorbe el residuo de redondeo. Cambiar la política afecta a cobros nuevos. La compensación se cancela por su valor histórico; banco/gastos usan el cambio actual y la cuenta estándar de diferencia de cambio. Se verificó USD con saldo de compensación cero y ganancia de C$3.76. La conciliación comprueba bruto, neto, comisión, retención y valoración histórica.

Las devoluciones tienen su política configurable de comisión y liquidación de salida: el banco se acredita por bruto devuelto más comisión. La retención original no se recupera automáticamente; una devolución tributaria depende de la liquidación/documentación real del proveedor. Para anular un cobro con liquidaciones vigentes, primero revierta esas liquidaciones con autorización y motivo. No hay pasarela activa que liquide importes por su cuenta.

## Compras y egresos

Registrar egreso usa una categoría con cuenta Expense de la compañía en moneda base y límite por operación (cero = sin límite). Solo efectivo disponible del propio turno; otro responsable exige autorización gerencial. El Journal Entry registra gasto y salida de caja, sin ajustar una factura de cliente.

Orden de compra conserva precio/impuestos aceptados. Purchase Receipt incorpora la recepción completa o parcial; Purchase Invoice se crea desde lo recibido con update_stock=0. No duplica inventario. El pago se convierte a la moneda de la cuenta del proveedor, aplica la factura estándar y crea un único movimiento del turno. Pagos nativos de proveedor sobre los medios configurados también se sincronizan; una devolución de proveedor se gestiona con el flujo estándar de devolución de compra y su conciliación, no con un cobro de huésped.

Los mínimos se almacenan en Item Reorder por almacén. HS Stock Policy solo clasifica uso operativo; Bin/SLE siguen siendo la verdad de cantidades/valoración. Traslados y reposición de ropa usan Material Transfer; limpieza/merma usan Material Issue con gasto/centro de costo; el conteo autorizado usa Stock Reconciliation con valoración existente y rechazo si cambió la existencia cotizada. Los activos fijos conservan el módulo Asset estándar. Movimientos de inventario proyecta SLE y origen, cantidades, variación de valor, uso y centro de costo, sin otro libro de inventario.

Cancelar o devolver exige autorización y motivo. Una corrección posterior al cierre conserva el arqueo original; Conciliación compara el esperado actual con ese snapshot y muestra la diferencia para revisión. No se eliminan registros para ocultarla.

## Conciliación e indicadores

Conciliación compara cargos/ajustes con líneas de facturas presentadas, movimientos HS con sus documentos vigentes y efectivo actual con arqueos conservados. Las diferencias tienen origen y documento explícitos y bloquean el cierre diario. Los reportes interactivos/exportados limitan a 1 000 filas por consulta; el control interno de cierre examina todas las filas.

Los documentos creados, presentados o cancelados desde ERPNext también pasan por los hooks de validación y sincronización. Para una operación externa de estancia deben indicarse establecimiento, estancia o reserva, cuenta y turno cuando corresponda. Una línea no puede facturar de nuevo un cargo existente.

Hotel: noches únicas comercializadas por habitación y fecha, ADR = alojamiento neto facturado / noches; RevPAR = alojamiento neto / noches comercializables. Motel: horas reales unidas por habitación desde la entrada real, horas comercializables menos bloqueos, rotaciones por entradas y duración real de las visitas. El ticket mostrado se refiere a alojamiento neto. Las cortesías ocupan con ingreso cero; impuestos, anticipos, garantías y otros servicios se excluyen de ADR/RevPAR. Denominador cero devuelve cero. No se suman noches y horas ni reserva y estancia como dos ocupaciones.

La producción operativa se informa separada del ingreso neto facturado y del efectivo cobrado. El neto de alojamiento se distribuye al período de servicio a partir del snapshot aceptado y de líneas presentadas, incluidas notas de crédito; no representa un nuevo devengo contable.
