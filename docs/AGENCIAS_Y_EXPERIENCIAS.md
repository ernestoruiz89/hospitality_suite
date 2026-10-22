# Agencias de viajes y experiencias

## Agencias de viajes

En **Agencias de viajes**, Gerencia registra una agencia por establecimiento, su tipo, contacto, porcentaje y, para liquidarla, un Supplier de ERPNext que ya esté registrado como proveedor de la sede. La agencia que origina una reserva es independiente del canal y del cliente que paga. Una OTA puede ser agente sin ser el pagador de la factura al huésped.

La reserva guarda el agente, el porcentaje pactado y una comisión **estimada** sobre el precio aceptado del alojamiento, sin impuestos ni experiencias. Editar el porcentaje del catálogo no cambia reservas existentes. Una modificación de la reserva conserva el porcentaje pactado y recalcula la estimación sobre el nuevo precio aceptado.

Una vez completada la reserva y facturados los cargos de alojamiento, Gerencia o Contabilidad revisa la base real y usa **Liquidar**. El cálculo suma los cargos de alojamiento facturados y sus ajustes asociados, antes de impuestos. Una nota de crédito sobre esas facturas bloquea la liquidación automática para revisión en ERPNext. Cada liquidación crea una Purchase Invoice estándar, con un artículo de comisión comprable y sin inventario y la cuenta de gasto configurada en el establecimiento. El proveedor y artículo deben estar configurados antes de liquidar. La factura queda enlazada a la reserva; el pago se hace por el flujo existente de proveedores o desde ERPNext. Una cancelación contable autorizada de esa factura libera el enlace para poder corregirla.

## Experiencias

En **Experiencias**, Gerencia configura nombre, categoría, duración, descripción y un Item de venta **sin inventario**. El precio vigente se toma de Item Price en la lista del establecimiento; no se mantiene una segunda tarifa. La experiencia puede publicarse en el portal. Solo se admite una imagen pública existente en `/files/`.

Recepción puede agregar experiencias al crear una reserva, guardar un borrador o añadirlas después a una reserva confirmada. El portal muestra únicamente las experiencias activas publicadas y valida nuevamente precio, cantidad y establecimiento en el servidor. La cotización muestra alojamiento y experiencias por separado; la reserva conserva el precio unitario e importe aceptados en cada orden.

Una orden pasa de **Reservada** a **Confirmada** con fecha y participantes, y luego a **Entregada**. Al entregar se selecciona estancia y cuenta; se crea una sola vez un HS Charge de servicio que la facturación normal incorpora a Sales Invoice. Antes de entregar se puede cancelar con motivo. La última salida de la reserva exige entregar o cancelar las órdenes pendientes. Una experiencia ya facturada se corrige mediante la nota de crédito estándar del folio, no editando su precio histórico. La venta de experiencias a clientes sin estancia usa la venta directa existente del Item.

## Despliegue

Ejecute `python tools/generate_schema.py`, `bench --site <sitio> migrate` y `bench build --app hospitality_suite`. Los establecimientos existentes empiezan con catálogos vacíos y ninguna comisión retroactiva. Configure el artículo y cuenta de comisión desde **Agencias de viajes → Configurar comisión**, y registre al agente como proveedor antes de la primera liquidación. Los impuestos y retenciones del proveedor que requieran tratamiento especial se revisan en ERPNext.
