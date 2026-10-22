# Lavandería de huéspedes

La Page **Lavandería** administra pedidos de prendas de huéspedes alojados. Es independiente de **Limpieza → Ropa de cama**, que traslada inventario propio del hotel entre almacenes de ERPNext.

## Preparación

1. Gerencia crea un artículo de **venta sin inventario** en ERPNext para cada tratamiento contable que necesite (por ejemplo, lavandería normal o lavado en seco). Su cuenta de ingresos y tratamiento fiscal se configuran mediante los artículos y las reglas contables habituales de la Suite.
2. En **Lavandería → Tarifario por prenda**, Gerencia define prenda, servicio, artículo, tarifa normal y, si aplica, exprés. Cada establecimiento mantiene su tarifario. La tarifa exprés sin precio propio usa la normal; el campo opcional no aplica un multiplicador automático.
3. La estancia debe estar activa y disponer de una cuenta abierta en la moneda del establecimiento. Las tarifas se congelan en las líneas al recoger la bolsa; editar una tarifa no altera órdenes existentes.

## Operación

Recepción o Limpieza registra una solicitud de recogida para una estancia activa. Al recoger, cuenta prendas y selecciona sus tarifas; una cortesía requiere Gerencia. La bolsa avanza **Solicitada → Recogida → En proceso → Lista**. En Lista se registra el número de piezas devueltas por línea.

Recepción o Gerencia entrega la bolsa. Si faltan piezas, solo Gerencia puede confirmar con explicación. El cargo al folio se calcula **sobre las piezas efectivamente devueltas**; la cotización original queda visible en la orden. Una cortesía no crea cargo. La factura y los impuestos siguen el flujo ordinario del folio y ERPNext. La orden conserva los vínculos a los cargos generados y el comprobante imprimible. El tablero resume pedidos abiertos y cargos entregados durante los últimos 30 días.

La salida de la estancia se bloquea mientras tenga pedidos abiertos. Una solicitud sin prendas puede cancelarse con motivo; cancelar una bolsa ya recogida requiere Gerencia. Los comandos autenticados usan la clave de idempotencia de la Suite y bloquean el establecimiento durante la operación para impedir doble entrega o cobro.

## Despliegue

Ejecute `python tools/generate_schema.py`, `bench --site <sitio> migrate` y `bench build --app hospitality_suite`. Los establecimientos existentes no reciben tarifas ni pedidos de forma automática. Cree el tarifario cuando el establecimiento vaya a ofrecer lavandería de huéspedes.
