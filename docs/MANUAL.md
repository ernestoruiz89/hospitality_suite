# Manual diario por rol

Aplicación 0.2.0, Frappe 16.52 / ERPNext 16.51. Los recorridos acreditados y las verificaciones pendientes están en REQUISITOS.md.

## Recepción

1. Seleccione el establecimiento. El reloj y las fechas de operación usan su zona horaria; la fecha operativa puede diferir del calendario.
2. Registre al huésped en Clientes y huéspedes, o elija uno existente. Huésped, acompañante y cliente pagador son entidades diferentes. Contact y Address se crean como documentos estándar cuando se proporcionan datos de contacto/dirección.
3. En Reservas o Recepción, pulse Reservar. Indique intervalo, categoría, cantidad/personas y habitación si ya la conoce. Una reserva por categoría consume cupo aunque aún no tenga habitación asignada.
4. Revise la explicación y acepte la cotización del servidor. La retención es temporal; una confirmación requiere respuesta válida. Una reserva futura no significa habitación ocupada ahora.
5. Desde Ver reserva, registre entrada y asigne habitación limpia y disponible. El grupo conserva una asignación por habitación y permite entradas separadas. Entrada inmediata realiza reserva y entrada en una sola transacción.
6. En Ver estancia, agregue consumos, solicite extensión o cambio. Cada extensión/cambio que modifica el importe requiere nueva cotización; el tarifario posterior no altera el precio histórico aceptado.
7. Acompañantes permite vincular huéspedes registrados dentro de la ocupación aceptada. Para cambiar la ocupación o capacidad, revise primero la reserva/tarifa; no agregue personas para eludir el precio.
8. Separar cuenta crea otro pagador para la estancia o una cuenta compartida del grupo. Cambiar cuenta traslada cargos pendientes y sus ajustes sin duplicarlos.
9. Antes de salir, complete los servicios solicitados, liquide todas las cuentas, devuelva/aplique garantías y solicite inspección si la política la exige. Los excesos de tiempo se preparan primero y se cobran antes de confirmar salida.
10. Registrar salida deja la habitación sucia y crea limpieza. La liberación depende del flujo de limpieza/inspección.

El rol HS Receptionist registra la operación. Para cobrar con ese mismo usuario, administración puede añadir HS Cashier. Una salida a crédito requiere autorización de usuario y pagador, límite vigente y motivo; el saldo continúa como cuenta por cobrar.

## Caja

- Abra su turno con moneda y fondo inicial. Un movimiento pertenece a un único turno abierto; las operaciones ordinarias se bloquean cuando está cerrado o en revisión.
- En Cobrar, elija estancia/reserva, cuenta, medio e importe en la moneda de ese medio. Anticipo, cobro y garantía tienen efectos diferentes. La referencia bancaria es obligatoria si así se configuró.
- Revise importe, conversión, recibido y vuelto. El vuelto se expresa en la moneda del efectivo recibido. Confirme y conserve el recibo/documento ERPNext que devuelve el servidor.
- Los pagos parciales y combinados se registran como movimientos separados contra el mismo saldo. Un cobro ordinario no puede superar el saldo; use Anticipo cuando corresponda y exista una visita vigente.
- Retirar / entregar efectivo registra un Journal Entry hacia la cuenta de traslado configurada. No se elimina un cobro para representar la entrega.
- Las devoluciones requieren origen y motivo. Un pago facturado necesita nota de crédito; un anticipo disponible puede devolverse parcialmente mediante documentos y conciliación estándar. Una garantía conserva su circuito separado.
- Cuente por denominaciones y moneda. Una diferencia queda visible y exige motivo; el supervisor autorizado debe aprobarla. No se crea un ajuste automático para ocultarla.
- Imprima arqueo y recibos. La aplicación de un anticipo o garantía no representa una segunda entrada de efectivo.

## Limpieza y supervisión

- Abra Limpieza, revise prioridad y responsable, e inicie la tarea. El sistema registra inicio/fin y evita sobrescribir una tarea modificada por otro usuario.
- Complete baño, cama/ropa, minibar y superficies/equipo, y deje observaciones. Un checklist parcial no permite liberar.
- Si se exige inspección, solicítela. Supervisión revisa y libera la habitación; limpieza no se autoaprueba la inspección.
- Supervisión puede programar limpieza de estancia o profunda y asignar responsable con acceso al establecimiento.
- Registre daños/objetos y movimientos de ropa de cama. Las entregas, recepciones y pérdidas de artículos inventariables usan Stock Entry; una pérdida exige motivo.
- La vista de limpieza no muestra nombres de huéspedes, cuentas ni saldos financieros.

## Mantenimiento y servicios

Los bloqueos de mantenimiento se reservan por intervalo con el mismo motor de disponibilidad. Un conflicto con reserva/estancia se rechaza. Asigne una persona con rol y acceso al establecimiento. Desde Repuestos se registra una salida estándar; el costo procede de su valoración de inventario. Gerencia puede devolver repuestos sin usar con motivo. Supervisión autoriza completar la orden y liberar el bloqueo. Evidencia carga archivos privados vinculados a la orden; la impresión incluye repuestos y costos solo para roles autorizados. Los daños y objetos encontrados se resuelven con constancia y usuario responsable.

En Consumos, la solicitud no descuenta stock. Entregado genera un cargo y una única salida de inventario. Reintentar la entrega no repite la salida. Si el consumo ya se facturó, cree la nota de crédito antes de devolverlo. Venta directa crea factura, cobro y salida estándar sin estancia; su devolución completa se hace desde ese servicio con autorización.

En una tarifa puede configurar artículos incluidos una vez por estancia o por noche de hotel. La cotización conserva las cantidades aceptadas. Al solicitar marque Consumir del plan incluido: el sistema reserva su cupo, no agrega otro cargo y descuenta stock al entregar. Cancelar o devolver libera ese cupo. El beneficio por estancia se concede una sola vez; si cambian las tarifas entre noches, se usa el mayor beneficio por estancia de esas noches. Cambiar habitación conserva los beneficios aceptados sin duplicarlos; extender hotel añade solo las cantidades por noche de la extensión. Editar una tarifa no modifica estancias existentes.

## Gerencia y contabilidad

Consulte producción, facturas, cobros, anticipos, garantías y pendientes por separado. Conciliación lleva cada diferencia al documento de origen. Exporte solo con rol autorizado. Los importes del XLSX son numéricos y mantienen su moneda; no sume monedas diferentes sin conversión explícita.

Los medios utilizados conservan cuenta, moneda y clasificación para que los arqueos históricos no cambien. Cree otro medio si necesita cambiarlas. Una factura externa debe incluir el cargo y todos sus ajustes una vez; no admite cargos revertidos. Un movimiento nativo de caja sin registro operativo aparece en conciliación y bloquea el cierre del turno. Los usuarios con roles HS usan los saldos de sus cuentas de estancia y reportes; una consulta global de cuenta contable podría agregar otros establecimientos y se restringe.

Revise el cierre diario antes de confirmar: llegadas pendientes, estancias vencidas, cargos, turnos y diferencias contables. Confirmar avanza la fecha operativa una sola vez por solicitud. Reabrir el último día requiere motivo y autorización. El formato de cierre imprime el snapshot conservado.

## Si ocurre un error

- Sin conexión, no se cobran movimientos desconectados. Espere respuesta del servidor; vuelva a consultar la cuenta antes de repetir.
- La misma solicitud conserva su clave de idempotencia al reintentar. Si se perdió toda la ventana, consulte primero el comprobante y el saldo; no introduzca otro pago sin verificar.
- Si otro usuario modificó el documento, actualice y revise el estado nuevo. No vuelva a enviar datos antiguos para sobrescribirlo.
- Si falla facturación o stock, el comando revierte su operación local completa. El error no equivale a una reserva, cobro o salida confirmada.
- Para corregir documentos presentados, use nota de crédito, devolución o cancelación autorizada con motivo. Conserve documentos y auditoría.
