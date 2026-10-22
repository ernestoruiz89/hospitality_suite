# API y contratos de integración

Desde 0.7.8, `room_history(property_name, room, starts_at, ends_at, view="activity", offset=0, page_length=25)` consulta una habitación autorizada. Exige rol operador y acceso al establecimiento/documento. Fechas en zona del establecimiento, inicio inclusivo y final exclusivo; el servidor devuelve extremos ISO con desplazamiento y `time_zone`. Los períodos se incluyen por intersección. Vistas: `activity`, `operations`, `changes`, `periods`, `all`; página de 1–200, desplazamiento entero no negativo. Devuelve metadatos de contexto, `rows`, `total`, `has_more` y conteos por tipo. Cada fila contiene tipo, título, usuario, momento/período, nota, relación exacta o incierta y campos operativos antes/después. Los IDs solo sirven para correlación interna. No devuelve JSON de origen, identidad, adjuntos ni valores financieros. No concede acceso general a Version o Auditoría. Las fuentes antiguas no recuperables se explican. Véase HISTORIAL_HABITACIONES.md.

service_accounting_configuration(property_name) exige setup y devuelve modified, company, defaults y services con nombres legibles. execute(action=service_accounting) exige esa versión en data.modified, defaults con income_account/expense_account/cost_center y services como lista de item y esos tres campos. Los nombres descriptivos son proyección de lectura; no se envían como campos de escritura. El comando conserva la petición idempotente y audita el cambio completo. Un campo vacío hereda de la sede y después de ERPNext; no cambia Item Default. Una versión obsoleta, cuenta incompatible o duplicado revierte la configuración completa. Las devoluciones conservan las cuentas del original.

Contrato verificado contra Frappe 16.52.0 / ERPNext 16.51.1. Las Pages usan estos mismos servicios. Las respuestas RPC estándar envuelven el resultado en `message`; un error no confirma una operación.

Desde 0.6.4, `execute(action="save_booking_draft")` permite `data.values` parcial: modalidad, huésped, pagador, fechas, canal, instrucciones y solicitudes de habitación con categoría/habitación/tarifa/personas/camas adicionales. Para editar exige `data.booking` y `data.modified` devueltos por el servidor. Conserva un `HS Booking` en `Draft`, sin precio aceptado, asignaciones, retención ni documentos financieros. Las referencias presentes siguen validándose por establecimiento y permisos; no se omiten validaciones mediante escritura directa.

`booking_detail(name).draft` reconstruye los datos parciales. `preview(action="confirm_booking_draft", data={booking, modified, values?})` exige datos completos y cotiza con disponibilidad y tarifas vigentes; devuelve `draft_acceptance`. `execute(action="confirm_booking_draft")` exige ese token, la misma versión y los mismos valores, y cambia **el mismo registro** a `Confirmed` o `Hold`, creando asignaciones solo entonces. `discard_booking_draft` exige booking/modified/reason, conserva el registro cancelado sin penalización y excluye ese borrador del informe de cancelaciones operativas. Las tres órdenes requieren permiso `reserve` y clave idempotente. Huésped principal puede completarse al registrar entrada; pagador/fechas/habitaciones sí son obligatorios al confirmar. El cliente conserva el desplazamiento explícito de fechas DST mientras no cambie la hora mostrada.

Desde 0.6.3, `availability_search` devuelve un objeto de consulta por cantidad en lugar de la lista anterior de candidatos. Sus consumidores deben leer `rooms`; la Page incluida se actualiza en la misma versión. `quantity` es el número de habitaciones de una categoría y `people` las personas **por habitación**: ambos enteros positivos, sin truncar fracciones. El servidor valida capacidad, establecimiento y fechas en la zona configurada.

La respuesta contiene `property`, `category`, `category_label`, `starts_at`/`ends_at` en la zona del sitio, `time_zone` del establecimiento, `quantity`, `people`, `available`, `enough`, `physical_available`, `needs_assignment_review` y `rooms` con nombre interno/número/limpieza. `available` es el cupo simultáneo de categoría y `enough` indica si alcanza para `quantity`; las habitaciones de `rooms` son alternativas físicas libres todo el intervalo, no unidades que se sumen al cupo. Por ejemplo, una reserva grupal sin habitación física puede dejar cupo 1 y diez alternativas: solicitar 2 devuelve `enough=false`. La fragmentación puede dejar cupo suficiente y pocas opciones continuas; entonces `needs_assignment_review=true`. Cero cupo es una respuesta válida; errores de conexión o de validación no significan cero. La consulta no escribe documentos ni conserva cupo: la confirmación sigue validando el mismo motor de intervalos/colchón bajo bloqueo.

preview(action=payment, kind=Refund) devuelve refund con modalidad, documento original, nota/factura, valor y moneda de la cuenta del cliente, valoración histórica y diferencia de cambio actual. Su acceptance incluye fondos, asignación y saldo del crédito. execute(payment) vuelve a validarlos y conserva la nota en HS Payment.sales_invoice y el origen en source_payment. Un anticipo ya aplicado admite devolución solo contra crédito válido de una de sus facturas y hasta su aportación restante; sin nota solo se devuelve lo no aplicado.

## Acceso y consultas

Use sesión Frappe con CSRF o credenciales API estándar del usuario mediante `Authorization: token <api_key>:<api_secret>`, siempre por HTTPS fuera del desarrollo local. No coloque claves en URLs ni en el repositorio. El usuario necesita el rol de la acción y HS Access para compañía/establecimiento. El servidor aplica el alcance aunque se conozca el identificador de un documento.

Base RPC: `/api/method/hospitality_suite.api.`.

bootstrap devuelve native_pos solo a roles de finanzas/reportes del establecimiento: proyección de facturas Sales Invoice con is_pos y sus movimientos reales de GL, turno, moneda, importe y clasificación. No crea HS Payment ni Payment Entry. close_shift usa cash_approve para aprobar diferencias o cerrar el turno de otro cajero: Administrador HS, Gerente y Supervisor. Las demás autorizaciones gerenciales conservan approve.

| Método | Parámetros principales | Resultado / permiso |
|---|---|---|
| `bootstrap` | `property_name` opcional | Establecimientos, navegación y proyección limitada al rol |
| `availability_search` | `property_name`, `starts_at`, `ends_at`, `category`, `people=1`, `quantity=1` | Consulta de cupo por cantidad; requiere acción reserve y acceso al establecimiento |
| `calendar` | establecimiento, inicio, fin | Asignaciones del establecimiento |
| `booking_detail`, `stay_detail` | `name` | Documento autorizado y cuentas relacionadas |
| `room_balances` | establecimiento | Saldos únicamente para roles financieros/recepción autorizados |
| `inventory_status` | establecimiento, almacén opcional | Existencias de almacenes autorizados |
| `report`, `export_report` | establecimiento, nombre, filtros; exportación `file_format` | Datos o descarga XLSX/PDF según rol |
| `report_page` | los mismos filtros, `offset`, `page_length` (1–200) | `rows`, `columns`, `total`, `has_more`; sin truncar la exportación |
| `report_options` | `property_name`, `report_name`, `company` opcional | Dimensiones aplicables, tipos de fecha y opciones dentro de los establecimientos autorizados |
| `guest_detail` | `name` | Perfil autorizado, política, pagador legible y versiones de Guest/Contact/Address; requiere guest |
| `guest_history` | `name`, `offset`, `page_length` | Visitas como principal o acompañante, limitadas al documento/establecimiento autorizado |
| `catalog_search` | `property_name`, `txt`, `purpose` (`any`, `sale`, `stock`, `purchase`) | Hasta 50 coincidencias y `has_more`; solo nombres/uso del Item compartido, sin precio/costo/saldo |
| `configuration`, `setup_options` | establecimiento | Configuración y opciones; requiere permiso de configuración |

En la tabla, establecimiento es el argumento `property_name`; inicio/fin son `starts_at`/`ends_at`, categoría es `category` y personas es `people`. Filtros se envía como objeto JSON en `filters`, con `from_date`, `to_date` y dimensiones admitidas por el reporte. Nombres e identificadores se obtienen de las consultas, no se construyen a partir del número visible de habitación.

### Registro y corrección de huéspedes

`bootstrap.properties` proyecta `guest_id_required`. `create_guest(property_name, data, request_key)` admite nombre, correo/teléfono, identificación/nacionalidad y dirección (`address_line1`, `city`, `country`); `customer` opcional debe estar registrado en ese establecimiento. Requiere `guest`. Devuelve `guest`, `customer`, `modified` y `related_versions` para contacto/dirección, sin cambiar las claves anteriores.

`guest_detail(name)` devuelve esos identificadores/versiones, `property`, `values`, `guest_id_required`, `customer_label`, `shared_contact` y `shared_address`. `update_guest(property_name, name, modified, data, reason, request_key, related_versions)` es POST: campos omitidos conservan su valor; cadenas vacías limpian el valor del perfil. No admite cambiar propiedad, pagador ni enlaces CRM directamente. La identificación sigue la política actual; una dirección requiere ciudad/país. `related_versions` debe contener la versión de cada registro existente que se vaya a modificar; el formulario reenvía ambas. Un conflicto revierte toda la orden y exige consultar de nuevo. El pagador y las referencias de visitas se conservan; los registros CRM compartidos se copian, los exclusivos se corrigen. Véase GESTION_HUESPEDES.md para reintentos y límites.

### Catálogo de artículos

`bootstrap.items` incluye las primeras 50 opciones y los nombres referenciados por consumos, compras o repuestos visibles, incluso si el artículo histórico está deshabilitado. No es el catálogo completo ni limita la selección: `catalog_search` busca en el Item estándar completo, por código o nombre, con texto literal de hasta 140 caracteres. Los artículos deshabilitados quedan fuera de la búsqueda. Requiere establecimiento autorizado y rol de servicio, limpieza, mantenimiento, inventario, configuración o reporte; Guest no accede. Item es un maestro compartido de ERPNext; precios y costos se resuelven en sus operaciones autorizadas por establecimiento/lista/moneda.

La Page conserva el código en el valor de la opción y muestra su nombre. Si dos resultados tienen el mismo nombre, añade el código para distinguirlos. Una búsqueda fallida o pendiente no autoriza la acción; las respuestas anteriores se descartan y la selección existente se conserva explícitamente al cambiar la búsqueda. `_hs_item_search` es un control de pantalla y se retira antes de ejecutar el comando.

### Reportes y presentación

`report_options` es la autoridad sobre filtros y `date_field`. Llegadas permite llegada/salida prevista o registro; estancias añade entrada/salida reales. Los períodos de fecha cubren días locales completos, con extremo final exclusivo en el día siguiente. Se admite un solo extremo y se rechazan fechas inválidas, períodos invertidos y dimensiones que no correspondan. Disponibilidad utiliza `starts_at`/`ends_at` y el mismo cálculo de cupo que reserva; las candidatas físicas son alternativas, mientras las reservas sin asignar consumen cupo de categoría.

Para agregar una compañía envíe `property_name=""` y `filters.company` con su nombre. Solo se combinan establecimientos autorizados de esa compañía; la selección de una propiedad incompatible se rechaza. Las filas conservan establecimiento, zona y moneda. Producción admite `group_by` con `room`, `category`, `item`, `channel` o `property`, con totales separados por moneda. Los documentos compartidos se seleccionan completos; un filtro no prorratea su saldo.

`report` conserva las claves originales. `report_page` y `export_report` usan por defecto una vista operativa con nombres y columnas relevantes. Las etiquetas están en `_display`; no reemplazan el valor original de `name`, `stay`, `folio`, `item` u otros enlaces. `filters.detail_level="technical"` incluye las referencias de documentos para trazabilidad. La Page debe renderizar únicamente `columns` y escapar las etiquetas. El historial de huésped sigue el mismo criterio y conserva sus claves en la respuesta.

Las exportaciones incluyen todos los resultados. XLSX mantiene números y precisión monetaria nativa; `base_currency` identifica el importe en moneda base. El PDF operativo de producción omite identificadores aleatorios. Los informes anchos se distribuyen en secciones con claves de relación repetidas; fechas y filtros figuran en el encabezado. El generador exige el runtime con Qt parcheado descrito en OPERACION.md.

Cancelaciones/no presentaciones usa `date_field="status_changed_at"` de forma predeterminada; procede de eventos Cancelled/No Show/Hold expired y no de `modified`. También admite llegada/salida prevista y creación. Incluye `penalty_amount` aceptado sin impuestos, `fee_invoice`, `fee_status` y motivo. Una factura anulada no aporta producción. Producción incluye líneas nativas sin cargo/venta directa representados, penalizaciones y sus notas de crédito; no altera la contabilidad ni suma dos veces sus orígenes.

`Productividad de limpieza` conserva filtros de Limpieza y agrupa por `assigned_to`: tareas, pendientes, finalizadas, finalizadas con duración positiva, minutos totales/media y tareas por hora registrada. `Arqueos por moneda` conserva filtros de Turnos y devuelve una fila por turno/moneda con el snapshot de cierre; en turno abierto, `counted_amount` y `difference` son null. `summary` mantiene `rotations` como entradas y añade `commercial_rooms`, `rotations_per_room` y `production_by_currency`; `production` corresponde solo a la moneda del establecimiento.

## Cotizar y confirmar

`preview(property_name, data, action)` consulta la cotización. `data` admite objeto o JSON. Fechas de entrada se interpretan en la zona del establecimiento; para una hora ambigua de DST debe proporcionarse un desplazamiento explícito. No use importes ni reloj del navegador como autoridad.

Ejemplo de `data` para `action="reserve"`:

```json
{
  "starts_at": "2026-12-10T14:00:00",
  "ends_at": "2026-12-12T12:00:00",
  "guest": "<huésped autorizado>",
  "customer": "<cliente pagador>",
  "rooms": [{"category": "<categoría>", "people": 2}],
  "channel": "Recepción"
}
```

Omitir `room` conserva cupo por categoría. Después de revisar la explicación y el importe, añada el `acceptance` devuelto y envíe **POST** `execute` con `property_name`, `action="reserve"`, una `request_key` nueva y los mismos datos. El registro resultante entrega el identificador de reserva. Entrada, extensión, cambio, pago, compra, liquidación, conteo y retención tienen sus cotizaciones particulares; sus campos se definen en `api.COMMANDS` y los servicios correspondientes, usados por los diálogos de la app.

Conserve una clave por intención de escritura. Reintente con **la misma clave, acción, usuario y carga** si se perdió la respuesta; cambiar la carga con una clave usada se rechaza. Una nueva cotización aceptada es otra intención. La transacción comprende documentos operativos y controladores ERPNext; no hay commits intermedios. No utilice REST genérico para cambiar asignaciones, caja o estados protegidos.

Las acciones sobre documentos existentes exigen su `modified` actual cuando corresponda. `save_setup` requiere `expected_modified`; los campos permitidos dependen de `section`. `create_guest` y `create_property` son POST con clave propia; crear establecimiento y conceder usuarios están restringidos. Si cambia la versión o cotización, vuelva a consultar y revisar, sin sobrescribir el estado ajeno.

`create_property(data, request_key)` requiere administración del sistema. Admite `property_name`, `company`, `mode`, `currency`, `time_zone`, `close_time` y `business_date` inicial opcional en formato AAAA-MM-DD. La compañía ya debe existir. Sin fecha inicial, usa el día de la zona elegida y el corte local (antes del corte corresponde D−1). Registra auditoría y resultado en HS Request, serializando el alta en Company; mismo usuario/compañía/clave/carga devuelve el mismo `property`, otra carga con esa clave se rechaza. No habilita finanzas ni crea cuentas/tributos. `bootstrap.can_create_property` informa si la interfaz puede presentar esa acción; el servidor vuelve a comprobar el permiso.

## Artículos y precios de servicios

`service_configuration(property_name,item=None)` requiere configuración. Devuelve `modified`, asignaciones/nombres y lista/moneda; al indicar un artículo de venta habilitado añade su precio general vigente y estado `Priced`, `Missing` o `Ambiguous`. No concede lectura de costos/saldos del catálogo. `save_setup(section="property")` admite `extra_hour_item` junto con los artículos/lista ya existentes y exige `expected_modified`.

Los consumos y ventas consultan la misma selección de Item Price por lista/moneda, vigencia, unidad y pagador. Se rechaza la ausencia o superposición aplicable. Las cotizaciones nuevas conservan `charge_items`; el cálculo por tiempo conserva `lodging_amount`, `extra_hours_amount` y `extra_hours_quantity`. Las cotizaciones/estancias antiguas pueden carecer de esas claves y mantienen su cargo aceptado. Los importes no se recalculan a partir de nombres ni descripciones traducidas.

## Políticas y cierre diario

`save_setup(section="property")` admite `advance_policy` y `guarantee_policy`: `Manual`, `Approval` o `Disabled`. Cambiarlas requiere aprobación además de configuración y `expected_modified`. `bootstrap.payment_policies` sirve para presentar las opciones de caja; el servidor vuelve a autorizarlas en cotización/contabilización y en documentos nativos nuevos. El cambio no invalida la devolución/aplicación autorizada de fondos anteriores.

`execute(action="daily_close",data={"confirm":false})` conserva revisión y devuelve `period`, `blockers` y `review_acceptance`. La Page envía esa huella al confirmar; si cambian los importes, fuentes o pendientes se rechaza antes de avanzar la fecha. `period.financial` diferencia facturación contable, movimientos operativos y saldos capturados de todas las fechas, por moneda, con fuentes. `bootstrap.closes[].summary` conserva el JSON que utiliza Ver resumen; consultarlo no recalcula saldos. Los cierres antiguos pueden carecer de `financial` y deben indicarlo. Las fechas históricas de cobros sin auditoría permanecen desconocidas, sin atribución inventada.

## Caja Chica y financiación

`bootstrap(property_name)` devuelve `petty_cash`, `petty_expenses`, `petty_renditions`, `petty_handovers`, `treasury_concepts` y `treasury_movements` según permisos. `save_setup(section="property")` acepta `petty_cash_account`, `petty_cash_responsible`, `petty_cash_overage_account` y `petty_cash_shortage_account`; `save_setup(section="treasury_concept")` crea un concepto con `label`, `nature` (`Other Income`, `Loan`, `Capital`), `account` y `active`.

Las siguientes acciones usan `execute(property_name, action, request_key, data)` y, por tanto, bloqueo por establecimiento, transacción e idempotencia: `petty_fund` (`kind=Initial Fund|Replenishment`, `shift`, `method`, `amount`, `rendition` para reposición), `petty_expense` (`category`, `beneficiary`, `concept`, `receipt_reference`, `amount`), `petty_correct` (solo campos descriptivos), `petty_rendition` (`counted_cash`, `explanation`, `rendition` al reenviar), `petty_review` (`rendition`, `approve`, `note`), `petty_handover`, `petty_accept`, `finance_request`, `finance_approve`, `finance_post` y `finance_reverse` (`doctype`, `name`, `reason`). Una rendición aprobada requiere usuario distinto al presentador; financiación aprobada requiere usuario distinto al solicitante.

`finance_request` recibe `kind` de préstamo o capital, `amount` y `concept` para entradas o `source_movement` para devoluciones. `finance_post` recibe el `movement` aprobado o `kind=Other Income` con `concept`; `channel=Cash` exige `shift` y `method`, mientras `channel=Bank` exige `bank_account` y `reference`. `preview(action="finance_post")` devuelve las cuentas de débito/crédito y el importe para revisión previa. La solicitud aprobada conserva la contrapartida aunque luego cambie el concepto. El cierre diario incluye `financial.version=2` con `sources.treasury_movements`, `sources.petty_expenses` y `sources.petty_variances` y métricas separadas en moneda base.

## Portal opcional

Rutas públicas `/hospitality` y `/hospitality-confirmation?token=…`. RPC base `hospitality_suite.portal.`: `catalog()`, `quote(property_name,data)` y **POST** `request(property_name,data,request_key)`. La solicitud añade categoría, cantidad de habitaciones, personas, nombre/correo y aceptación. Devuelve retención y enlace firmado, nunca pago aprobado. Recepción convierte mediante `convert_portal` después de revisar huésped/pagador y nueva cotización. Los enlaces tienen caducidad y no devuelven nombre, correo, identificación ni datos financieros ajenos. Configuración → Portal de reservas lo habilita explícitamente por establecimiento; inicialmente está desactivado.

## Proveedores externos

`integrations.py` define los contratos `PaymentGateway`, `ChannelGateway`, `MessagingGateway` y `LockGateway`. No hay proveedores activos. El adaptador concreto debe implementar autenticación, mapeo, identificadores, reintentos y conciliación del proveedor; una intención o un webhook recibido no equivale a liquidación. Nunca envíe números completos de tarjeta/CVV al PMS.

`provider_adapters.py` añade adaptadores ejecutables para **Hospitality Provider Contract v1**, protocolo de referencia propio: `ReferencePaymentAdapter`, `ReferenceMessagingAdapter` para correo/WhatsApp y `ReferenceLockAdapter`. `HttpContractTransport` permanece desactivado por defecto y no sigue redirecciones; ninguna Page, RPC, tarea o hook lo activa. `ReferenceChannelNormalizer` solo valida/mapea una solicitud entrante sin ejecutarla; publicar disponibilidad siempre rechaza la sincronización aplazada. Son contratos probados con dobles sin red, no conectores comerciales de proveedores existentes. [Métodos, cuerpos, respuestas, autorización previa y límites](CONTRATOS_PROVEEDORES.md).

El receptor preparado es **POST** `/api/method/hospitality_suite.integrations.webhook?provider=<id configurado>`. Configuración privada del sitio: `hospitality_integrations[provider]` con `enabled`, `property` y `secret`. La firma es HMAC-SHA256 sobre `timestamp + "." + cuerpo crudo`, con encabezados `X-Hospitality-Timestamp` y `X-Hospitality-Signature`; la tolerancia es 300 segundos. El cuerpo JSON requiere `id` estable, máximo 200 caracteres y 64 KiB de cuerpo. El identificador se valida y se deduplica por huella bajo bloqueo del establecimiento. El cuerpo y el identificador externo en texto no se guardan: payload contiene solo schema=receipt-v1, source, body_bytes y body_sha256. Un reenvío conserva el recibo original; la migración minimiza payloads/Version antiguos sin modificar documentos financieros. El receptor registra `Received` y auditoría, **sin crear pagos, reservas ni accesos a cerraduras automáticamente**. Las pruebas y simulaciones están identificadas como tales.

Para activar un proveedor real se necesitan su documentación, acceso y credenciales, y pruebas de sus estados/cancelaciones. Los endpoints públicos tienen limitación de solicitudes. Mantenga las credenciales y la clave de cifrado del sitio en almacenamiento protegido.

## Fondos de garantías aplicadas

Refund admite source_payment de tipo Guarantee Applied. refund.original_doctype identifica Journal Entry; original_funds obtiene cuenta, valoración, referencias Sales Invoice y líneas disponibles del cliente desde ese documento presentado. credit_note es obligatorio para fondos asignados y debe pertenecer a la factura original; sin nota solo se devuelve crédito no asignado. La aceptación conserva versión/saldos y execute reconcilia mediante controladores ERPNext. No se convierte otra vez en Guarantee Refund ni se libera para devolver el pasivo ya aplicado.

apply_guarantee admite shift abierto explícito, comprobado por el servidor; la Page lo solicita junto con origen, cuenta, importe y motivo. period.financial.sources.unallocated_advances puede incluir doctype=Journal Entry para crédito de garantía aplicada aún sin facturar. Los snapshots de cierres anteriores permanecen conservados.

## Notas de crédito y devolución POS

preview(action="credit_note") requiere approve, invoice y reason; para un original POS también shift abierto del establecimiento. items opcional contiene invoice_item y quantity por línea, sin duplicados; omitirlo devuelve lo pendiente. reference es obligatorio según los medios bancarios originales. La respuesta incluye items por nombre, total/currency, rounding_adjustment, update_stock y acceptance. El importe liquidado respeta el total exigible en la moneda de la cuenta del cliente según el controlador ERPNext, incluido su redondeo. is_pos describe el origen, no el indicador de la nota resultante.

pos conserva fondos nativos, documentos enlazados, payments con amount/currency/exchange_rate por cuenta, party_amount/party_currency/party_rate, offset del original, write_off_base y exchange_difference. Un amount negativo significa recuperar dinero del vuelto. La aceptación cubre versiones, devoluciones, saldos y tipos de cambio. execute(credit_note) exige la aceptación para POS y vuelve a calcularla; su resultado incluye credit_note y refund_journal, ambos documentos estándar. La nota POS resultante tiene is_pos=0, saldo propio y stock del original; su Journal Entry liquida la devolución en la misma transacción. Una revisión cambiada se rechaza y el mismo request_key reintenta una sola intención.

bootstrap.native_pos puede incluir doctype Journal Entry o Payment Entry de devoluciones enlazadas a notas de un original POS, además de Sales Invoice. name identifica su documento real; la Page elige el enlace según doctype. Los comprobantes ya representados por HS Payment se excluyen para evitar duplicados. Las lecturas usan sus GL; ninguna API acepta líneas arbitrarias de GL ni cuentas de devolución ajenas al origen.

La revisión POS rechaza diferencias que no corresponden a valoración histórica/cambio actual y redondeos acotados. Los cobros adicionales se devuelven contra su origen y se concilian con el crédito pendiente, sin usar la cuenta de cambio para compensar fondos distintos; véase AUDITORIA_RECIBOS_POS.md. La valoración de los GL de un POS se valida también al presentarlo; una incoherencia entre moneda del medio y base impide confirmar la transacción.

## Facturación explícita de cuenta, 0.6.1

`preview(property_name, action="invoice", data={folio})` requiere finance y contexto compatible de establecimiento/compañía. Calcula una Sales Invoice transitoria sin guardarla ni consumir serie, sin generar programaciones ni conciliar. Devuelve `ready`, cuenta/cliente/fecha, `net_total`, `taxes`, `total`, `payable` (incluido redondeo), `advance`, `outstanding`, monedas, alojamiento `scheduled`, número de líneas y `acceptance`. `ready=true` es válido con importe cero. Sin cargos nuevos devuelve `ready=false` sin modificar conciliaciones.

`execute(action="invoice", data={folio, invoice_acceptance}, request_key)` comprueba la revisión antes de liquidar programaciones y presentar la factura estándar. La Page siempre envía la huella y conserva la clave en los reintentos. El parámetro de revisión es opcional para compatibilidad del contrato previo; la autorización y validación contable siguen siendo obligatorias. La emisión conserva activa la estancia y no registra dinero ni salida. FACTURACION_DESDE_PAGES.md describe pruebas y límites.

## Tablero de estancias, 0.6.2

`stay_board(property_name,date=None,view="hosted",offset=0,page_length=25)` es de solo lectura y requiere rol operativo/contable/auditor de lectura y acceso al establecimiento. view admite hosted/arrivals/departures/accounts; fecha ISO estricta, página válida de 1–200 filas y offset no negativo. La Page utiliza 25. Devuelve rows, counts por vista, total/offset/page_length/has_more, property/date/view y server_time.

La fecha predeterminada es hoy en la zona del establecimiento. Llegadas y salidas incluyen pendientes anteriores y usan como límite excluido la medianoche local siguiente, también en días de cambio horario; no filtran por fecha operativa ni la avanzan. Hosted conserva solo Active y accounts solo Open, también con cero. El grupo parcialmente ingresado conserva asignaciones Reservation Active pendientes y la cuenta compartida aparece una vez. Las retenciones vencidas se excluyen sin cancelarlas desde la lectura. Saldo reutiliza folio_balance por cuenta/página y conserva moneda; nombres de presentación respetan modo discreto. ESTANCIAS_Y_LLEGADAS.md delimita pruebas y permisos.

bootstrap añade starts_at a la proyección mínima occupied y, para los roles que ya reciben estancias/reservas, room_arrivals con la primera llegada pendiente asignada por habitación, sin nombres/precios. No es otro estado de ocupación ni concede escritura. El cliente conserva secuencia/propiedad/fecha/vista antes de presentar una respuesta y descarta respuestas antiguas.
