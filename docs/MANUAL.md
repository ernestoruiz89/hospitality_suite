# Manual diario por rol

Aplicación 0.5.2, Frappe 16.52 / ERPNext 16.51. Los recorridos acreditados y las verificaciones pendientes están en REQUISITOS.md.

Los formularios extensos están organizados en pestañas por tarea. Puede cambiar de sección sin perder lo escrito y guardar desde cualquiera. Los datos adicionales del huésped y las opciones de reserva tienen su propia sección. La acción de guardar o revisar permanece visible; si falta un dato obligatorio, el formulario abre su sección. Al cerrar una revisión de precio o cobro, vuelve al borrador sin registrarlo. Véase UX_FORMULARIOS.md.

## Recepción

1. Seleccione el establecimiento. El reloj y las fechas de operación usan su zona horaria; la fecha operativa puede diferir del calendario.
2. Registre al huésped en Clientes y huéspedes, o elija uno existente. Huésped, acompañante y cliente pagador son entidades diferentes. Contact y Address se crean como documentos estándar cuando se proporcionan datos de contacto/dirección.
3. En Reservas o Recepción, pulse Reservar. Indique intervalo, categoría, cantidad/personas y habitación si ya la conoce. Una reserva por categoría consume cupo aunque aún no tenga habitación asignada.
4. La tabla conserva los números escritos al cambiar de fila. En reservas, la vista inicial muestra las vigentes; Mostrar historial permite consultar las terminadas o canceladas. Revise la explicación y acepte la cotización del servidor. La retención es temporal; una confirmación requiere respuesta válida. Una reserva futura no significa habitación ocupada ahora.
5. Desde Ver reserva, registre entrada y asigne habitación limpia y disponible. El grupo conserva una asignación por habitación y permite entradas separadas. El selector distingue cada solicitud por número y ocupantes; tras la primera entrada solo ofrece registrar las pendientes. Entrada inmediata realiza reserva y entrada en una sola transacción.
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
- Registrar egreso exige categoría, comprobante y efectivo disponible; respeta su límite configurado. Pagar proveedor selecciona una factura pendiente, cotiza moneda/saldo y registra Payment Entry. Ambos reducen el esperado si se pagan en efectivo.
- Registrar liquidación selecciona un movimiento no efectivo pendiente, bruto y referencia de extracto. Revise comisión, retención y neto antes de registrar. El banco neto y el bruto cobrado son conceptos separados; la caja física no aumenta. Una devolución liquidada muestra débito bancario.
- Las devoluciones requieren origen y motivo. El selector muestra concepto, fecha, importe y recibo ERPNext. Un cobro facturado o anticipo ya aplicado necesita una nota de crédito de su factura de origen; un anticipo disponible se devuelve dejando la nota vacía. Revise el importe entregado, valor liquidado en la cuenta del cliente y diferencia de cambio. Si cambió el saldo o se hizo otra devolución mientras revisaba, vuelva a revisar. Para fondos ya convertidos elija Devolución y el origen Garantía aplicada: con nota si ya se asignaron a factura, sin nota para lo aún disponible. Devolución de garantía corresponde únicamente a la parte que permanece retenida.
- Cuente por denominaciones y moneda. Una diferencia queda visible y exige motivo; el supervisor autorizado debe aprobarla. No se crea un ajuste automático para ocultarla.
- Aplicar garantía exige autorización, recibo de garantía recibido, cuenta destino, turno abierto, importe y motivo. El recibo se muestra por fecha, importe y documento ERPNext. El resultado Garantía aplicada (sin nuevo ingreso) permite distinguirlo del dinero recibido.
- Imprima arqueo y recibos. La aplicación de un anticipo o garantía no representa una segunda entrada de efectivo.
- Cobros POS de ERPNext muestra facturas y documentos de devolución vinculados con su turno, medio e importe neto de vuelto/devolución. El efectivo ya forma parte del esperado; no registre otro cobro por esa venta. El arqueo impreso incluye ese origen. Una factura histórica sin turno o medio configurado exige revisión en Conciliación.

- Nota de crédito pide factura y motivo. Para un original POS elija también turno de devolución y referencia bancaria si corresponde. Use Seleccionar cantidades para devolver solo algunas unidades, por nombre del artículo/servicio. Revise el total, las existencias y el dinero de cada medio antes de confirmar.
- Una nota POS devuelve el dinero en esa misma operación; no registre otro cobro o devolución. El resultado entrega la nota y el asiento estándar. La devolución de una factura de estancia conserva el paso posterior de Cobrar con el origen correspondiente. Las ventas directas usan Devolver en Consumos e inventario, que incluye dinero y stock. Si la revisión indica Recibir, esa parte recupera efectivo que se entregó como vuelto de otro medio.
- Las correcciones conservan los originales. Para cancelar una nota POS con devolución vigente, revierta primero su asiento con autorización y motivo.

## Limpieza y supervisión

- Abra Limpieza, revise prioridad y responsable, e inicie la tarea. El sistema registra inicio/fin y evita sobrescribir una tarea modificada por otro usuario.
- Complete baño, cama/ropa, minibar y superficies/equipo, y deje observaciones. Un checklist parcial no permite liberar.
- Si se exige inspección, solicítela. Supervisión revisa y libera la habitación; limpieza no se autoaprueba la inspección.
- Supervisión puede programar limpieza de estancia o profunda y asignar responsable con acceso al establecimiento.
- Registre daños/objetos y movimientos de ropa de cama. Las entregas, recepciones y pérdidas de artículos inventariables usan Stock Entry; una pérdida exige motivo.
- La vista de limpieza no muestra nombres de huéspedes, cuentas ni saldos financieros.

## Mantenimiento y servicios

Los bloqueos de mantenimiento se reservan por intervalo con el mismo motor de disponibilidad. Un conflicto con reserva/estancia se rechaza. Asigne una persona con rol y acceso al establecimiento. Desde Repuestos se registra una salida estándar; el costo procede de su valoración de inventario. Gerencia puede devolver repuestos sin usar con motivo. Supervisión autoriza completar la orden y liberar el bloqueo. Evidencia carga archivos privados vinculados a la orden; la impresión incluye repuestos y costos solo para roles autorizados. Los daños y objetos encontrados se resuelven con constancia y usuario responsable.

Configuración → Equipos y activos registra etiqueta, nombre, ubicación e instrucciones. Puede enlazar un Asset que contabilidad haya asignado al establecimiento mediante su campo estándar de alojamiento; no se crean valores ni depreciaciones desde el PMS. Nueva orden admite equipo sin habitación, o equipo ubicado en habitación. La casilla Bloquear disponibilidad decide si se reserva ese intervalo; una revisión sin bloqueo no cancela reservas. Una orden de equipo no se solapa con otra del mismo equipo. Ver evidencia abre el archivo privado para mantenimiento/supervisión; limpieza no recibe ese enlace ni puede abrir/listar esos archivos.

En Consumos, la solicitud no descuenta stock. Entregado genera un cargo y una única salida de inventario. Reintentar la entrega no repite la salida. Si el consumo ya se facturó, cree la nota de crédito antes de devolverlo. Venta directa crea factura, cobro y salida estándar sin estancia; su devolución completa se hace desde ese servicio con autorización.

Para abastecimiento, registre proveedor/ubicación en Consumos e inventario. Nueva compra permite artículos, cantidades y precios acordados, con revisión del total. Recibir admite cantidades parciales hasta lo pendiente. Facturar recepción solicita número/fecha de factura; vuelve después a Caja para pagar al proveedor. Mover / consumir stock distingue traslado, reposición de ropa, limpieza y merma con motivo y categoría de gasto. Ajustar conteo está reservado a gerencia y requiere revisar la diferencia actual. Configuración → Clasificación y mínimos guarda los umbrales nativos de cada artículo/almacén. Gerencia → Movimientos de inventario muestra el movimiento nativo, costo y origen.

En una tarifa puede configurar artículos incluidos una vez por estancia o por noche de hotel. La cotización conserva las cantidades aceptadas. Al solicitar marque Consumir del plan incluido: el sistema reserva su cupo, no agrega otro cargo y descuenta stock al entregar. Cancelar o devolver libera ese cupo. El beneficio por estancia se concede una sola vez; si cambian las tarifas entre noches, se usa el mayor beneficio por estancia de esas noches. Cambiar habitación conserva los beneficios aceptados sin duplicarlos; extender hotel añade solo las cantidades por noche de la extensión. Editar una tarifa no modifica estancias existentes.

## Gerencia y contabilidad

Consulte producción, facturas, cobros, anticipos, garantías y pendientes por separado. Conciliación lleva cada diferencia al documento de origen. Exporte solo con rol autorizado. Los importes del XLSX son numéricos y mantienen su moneda; no sume monedas diferentes sin conversión explícita.

Los medios utilizados conservan cuenta, moneda y clasificación para que los arqueos históricos no cambien. Cree otro medio si necesita cambiarlas. Una factura externa debe incluir el cargo y todos sus ajustes una vez; no admite cargos revertidos. Un movimiento nativo de caja sin registro operativo aparece en conciliación y bloquea el cierre del turno. Los usuarios con roles HS usan los saldos de sus cuentas de estancia y reportes; una consulta global de cuenta contable podría agregar otros establecimientos y se restringe.

Revise el cierre diario antes de confirmar: llegadas pendientes, estancias vencidas, cargos, turnos y diferencias contables. Confirmar avanza la fecha operativa una sola vez por solicitud. Reabrir el último día requiere motivo y autorización. El formato de cierre imprime el snapshot conservado.

Configuración → Horarios y penalizaciones define la hora de corte. La fecha operativa D comprende desde ese corte de D hasta el corte de D+1 en la zona del establecimiento, con inicio incluido y fin excluido. Gerencia y el cierre muestran el período real; un día con cambio horario puede durar 23 o 25 horas. El reloj no avanza automáticamente la fecha operativa: el responsable confirma su cierre después de revisar los pendientes. Los informes con fechas explícitas conservan el período elegido.

Configuración → Series y formatos permite seleccionar los existentes en ERPNext. Usuarios y roles aparece solo a administración del sistema; el alta concede roles HS y acceso al establecimiento, sin conceder roles generales de ERPNext. Las aprobaciones financieras y de retención requieren gerente o administrador HS; el supervisor operativo inspecciona limpieza y mantenimiento.

Configuración → Portal de reservas habilita el establecimiento en `/hospitality`. El visitante consulta precio y solicita confirmación; el cupo se conserva hasta la hora mostrada. En Reservas → Solicitudes del portal, recepción revisa huésped/pagador y confirma la cotización para convertirla en reserva. El enlace firmado permite consultar su estado sin publicar datos personales. Sin pasarela real no hay pago aprobado ni envío automático por un proveedor de mensajería.

En Configuración → Retención de datos, administración define días de conservación; 0 desactiva la revisión. Gerencia → Revisar datos vencidos muestra documentos elegibles y pide motivo. Revise los campos y adjuntos del resumen antes de confirmar la eliminación irreversible. Solo administrador HS y gerente pueden aprobarla. Huéspedes con actividad vigente o reciente, evidencias de tareas abiertas y adjuntos recientes se conservan. Se retiran identificaciones y evidencias cerradas; nombres, contactos, contabilidad, comentarios libres y respaldos conservan su política propia. El historial distingue pendiente, completada y fallida; corregida la causa de una falla, un gerente puede encolar otro intento con motivo.

## Si ocurre un error

En los selectores de consumos, venta directa, ropa, repuestos, movimientos, conteos y filtros de artículos puede escribir parte del nombre o código. Se muestran hasta 50 coincidencias; afine el texto si hay más. Elija el resultado por su nombre. Cambiar la búsqueda conserva la selección anterior y lo indica; una búsqueda sin respuesta válida bloquea la confirmación hasta volver a consultar. Los precios se obtienen de ERPNext al cotizar o registrar el consumo.

- Sin conexión, no se cobran movimientos desconectados. Espere respuesta del servidor; vuelva a consultar la cuenta antes de repetir.
- Si aparece Sin confirmación del servidor, mantenga el diálogo y reintente los mismos datos. La misma solicitud conserva su clave de idempotencia al reintentar. Si se perdió toda la ventana, consulte primero el comprobante y el saldo; no introduzca otro pago sin verificar.
- Si otro usuario modificó el documento, actualice y revise el estado nuevo. No vuelva a enviar datos antiguos para sobrescribirlo.
- El indicador Tiempo real conectado refleja Socket.IO. Si muestra Sin tiempo real, pulse Actualizar para reconectar y consultar el estado del servidor. Los movimientos siguen requiriendo respuesta válida; una conexión de notificaciones no sustituye esa confirmación.
- Si falla facturación o stock, el comando revierte su operación local completa. El error no equivale a una reserva, cobro o salida confirmada.
- Para corregir documentos presentados, use nota de crédito, devolución o cancelación autorizada con motivo. Conserve documentos y auditoría.

## Reportes con información legible

En Gerencia, elija el reporte y confirme compañía, establecimiento y período. «Consultar por» distingue llegada, salida y registro. Los filtros de categoría, habitación, canal, usuario, responsable, turno, medio de pago o inventario aparecen cuando corresponden al reporte. Las fechas usan el calendario del navegador y la zona local del establecimiento.

La presentación inicial es «Vista operativa»: servicios por su nombre, habitaciones por su número, cuentas por su etiqueta y personas por su nombre autorizado. Producción muestra alojamiento, consumos y devoluciones con cantidades, importes y estado; «Agrupar producción» permite comparar habitación, categoría, servicio, canal o establecimiento. Los importes de monedas distintas permanecen separados.

Para revisar documentos de origen, seleccione «Documentos y referencias técnicas» en Presentación. Las claves internas siguen disponibles para contabilidad, sin ocupar la vista cotidiana. PDF y Excel respetan esa selección e incluyen el conjunto completo, aunque la pantalla muestre una página. Los valores numéricos se conservan en Excel.

El listado de reservas muestra huésped y fecha. En modo discreto sustituye el nombre por «Huésped registrado». Las acciones siguen apuntando al mismo documento; estas etiquetas no renumeran ni alteran reservas, facturas, cuentas o movimientos.

«Cancelaciones y no presentaciones» consulta inicialmente la fecha de la decisión o vencimiento, tomada de auditoría. Puede cambiarla a llegada prevista, salida o registro. Muestra motivo, penalización aceptada y factura/estado contable; una penalización anulada no sigue sumando producción. «Arqueos por moneda» separa esperado, contado y diferencia de cada moneda, conservando el snapshot de cierre. En un turno abierto, contado y diferencia permanecen pendientes.

«Productividad de limpieza» resume por responsable tareas pendientes/finalizadas y duración registrada. Tareas por hora usa únicamente finalizadas con duración positiva de inicio a finalización; incluye esperas de inspección y no es una medición de jornada laboral. Gerencia de motel distingue entradas totales de rotaciones por habitación con tiempo comercializable.

Las etiquetas y mensajes preparados usan las traducciones nativas de Frappe. Los nombres de huéspedes, artículos, establecimientos y cuentas permanecen como fueron registrados. Los selectores muestran los nombres como texto y conservan la referencia original al confirmar. Esta revisión amplía la preparación de idiomas; no incorpora un paquete completo de otro idioma.

## Alta de otro establecimiento

Administración del sistema dispone de «Crear establecimiento» en Configuración, también cuando ya existen otros. Seleccione una compañía existente de ERPNext, modalidad, moneda y zona horaria; indique la hora local del corte. La fecha operativa inicial es opcional: vacía, corresponde al día local y retrocede un día si aún no se alcanzó el corte. Puede indicar una fecha inicial válida con el calendario. Una vez creado, el panel selecciona el nuevo establecimiento.

El alta no crea cuentas ni impuestos y conserva finanzas deshabilitadas. Complete políticas/contabilidad, categorías, habitaciones, tarifas y medios antes de habilitarlas. La fecha posterior avanza mediante cierre diario; una corrección usa la reapertura autorizada. Un reintento con los mismos datos conserva la referencia del formulario y recupera el establecimiento ya creado.

## Artículos y servicios

En Configuración → Artículos y servicios, seleccione los artículos estándar de alojamiento, horas adicionales de motel y horarios de hotel, junto con la lista de precios de consumos. La tabla superior muestra sus nombres actuales. Los artículos automáticos de alojamiento/tiempo deben estar habilitados para venta y no manejar inventario.

Si elige un artículo distinto para horas adicionales, su unidad debe representar horas y admitir fracciones (por ejemplo, Hour). Las propiedades migradas que mantienen el mismo artículo de alojamiento conservan una unidad de cargo por registro, con el importe de la fracción aceptada.

Busque un servicio para consultar su precio general vigente y si requiere entrega con inventario. Alimentación, minibar, lavandería de huésped y otros servicios usan Item/Item Price de ERPNext; un precio específico del pagador puede prevalecer. Si cambia la lista, guarde y vuelva a abrir para consultar sus precios. Un precio vencido, futuro o superpuesto no autoriza un consumo.

Las horas adicionales de motel se muestran separadas del alojamiento en la cuenta. Las extensiones y la preparación de salida registran solo el incremento correspondiente. Una asignación nueva no modifica los cargos ya aceptados; las reservas antiguas conservan su tratamiento original.

## Políticas de anticipos y garantías

En Configuración → Anticipos y garantías, elija una política para cada tipo: manual según rol de caja, con autorización de gerencia o sin nuevos movimientos. Guardar el cambio requiere permiso de aprobación. La caja muestra las opciones que correspondan y avisa cuando requiere gerencia; el servidor comprueba nuevamente el permiso al registrar. Los fondos recibidos anteriormente conservan su devolución o aplicación autorizada.

## Revisar y consultar el cierre

Gerencia → Revisar cierre del día presenta ocupación, producción, facturación, dinero recibido y saldos separados por moneda. La fecha contable selecciona las facturas; la fecha operativa selecciona los movimientos. Los saldos corresponden al instante de la revisión e incluyen todas las fechas. Anticipos y garantías se distinguen del ingreso por alojamiento; un crédito a favor no elimina una factura sin conciliación.

Resuelva los pendientes antes de confirmar. Si cambia la información financiera mientras revisa, actualice la revisión. Historial de cierres → Ver resumen consulta lo conservado en esa ejecución, sin recalcularlo con pagos posteriores. Imprimir cierre utiliza ese mismo resumen. Los cierres antiguos que no conservan el desglose lo indican expresamente.

Si un POS tiene fondos de otros documentos o una valoración incoherente, la operación se rechaza antes de registrar una devolución. En esta versión, use Venta directa para nuevos cobros afectados por el vuelto en moneda extranjera. Los documentos históricos requieren revisión contable; no vuelva a pagar su importe bruto.
