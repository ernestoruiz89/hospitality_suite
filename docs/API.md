# API y contratos de integración

Contrato verificado contra Frappe 16.52.0 / ERPNext 16.51.1. Las Pages usan estos mismos servicios. Las respuestas RPC estándar envuelven el resultado en `message`; un error no confirma una operación.

## Acceso y consultas

Use sesión Frappe con CSRF o credenciales API estándar del usuario mediante `Authorization: token <api_key>:<api_secret>`, siempre por HTTPS fuera del desarrollo local. No coloque claves en URLs ni en el repositorio. El usuario necesita el rol de la acción y HS Access para compañía/establecimiento. El servidor aplica el alcance aunque se conozca el identificador de un documento.

Base RPC: `/api/method/hospitality_suite.api.`.

| Método | Parámetros principales | Resultado / permiso |
|---|---|---|
| `bootstrap` | `property_name` opcional | Establecimientos, navegación y proyección limitada al rol |
| `availability_search` | establecimiento, inicio, fin, categoría, personas | Disponibilidad compartida con recepción |
| `calendar` | establecimiento, inicio, fin | Asignaciones del establecimiento |
| `booking_detail`, `stay_detail` | `name` | Documento autorizado y cuentas relacionadas |
| `room_balances` | establecimiento | Saldos únicamente para roles financieros/recepción autorizados |
| `inventory_status` | establecimiento, almacén opcional | Existencias de almacenes autorizados |
| `report`, `export_report` | establecimiento, nombre, filtros; exportación `file_format` | Datos o descarga XLSX/PDF según rol |
| `report_page` | los mismos filtros, `offset`, `page_length` (1–200) | `rows`, `columns`, `total`, `has_more`; sin truncar la exportación |
| `report_options` | `property_name`, `report_name`, `company` opcional | Dimensiones aplicables, tipos de fecha y opciones dentro de los establecimientos autorizados |
| `guest_history` | `name`, `offset`, `page_length` | Visitas como principal o acompañante, limitadas al documento/establecimiento autorizado |
| `catalog_search` | `property_name`, `txt`, `purpose` (`any`, `sale`, `stock`, `purchase`) | Hasta 50 coincidencias y `has_more`; solo nombres/uso del Item compartido, sin precio/costo/saldo |
| `configuration`, `setup_options` | establecimiento | Configuración y opciones; requiere permiso de configuración |

En la tabla, establecimiento es el argumento `property_name`; inicio/fin son `starts_at`/`ends_at`, categoría es `category` y personas es `people`. Filtros se envía como objeto JSON en `filters`, con `from_date`, `to_date` y dimensiones admitidas por el reporte. Nombres e identificadores se obtienen de las consultas, no se construyen a partir del número visible de habitación.

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

## Portal opcional

Rutas públicas `/hospitality` y `/hospitality-confirmation?token=…`. RPC base `hospitality_suite.portal.`: `catalog()`, `quote(property_name,data)` y **POST** `request(property_name,data,request_key)`. La solicitud añade categoría, cantidad de habitaciones, personas, nombre/correo y aceptación. Devuelve retención y enlace firmado, nunca pago aprobado. Recepción convierte mediante `convert_portal` después de revisar huésped/pagador y nueva cotización. Los enlaces tienen caducidad y no devuelven nombre, correo, identificación ni datos financieros ajenos. Configuración → Portal de reservas lo habilita explícitamente por establecimiento; inicialmente está desactivado.

## Proveedores externos

`integrations.py` define los contratos `PaymentGateway`, `ChannelGateway`, `MessagingGateway` y `LockGateway`. No hay proveedores activos. El adaptador concreto debe implementar autenticación, mapeo, identificadores, reintentos y conciliación del proveedor; una intención o un webhook recibido no equivale a liquidación. Nunca envíe números completos de tarjeta/CVV al PMS.

El receptor preparado es **POST** `/api/method/hospitality_suite.integrations.webhook?provider=<id configurado>`. Configuración privada del sitio: `hospitality_integrations[provider]` con `enabled`, `property` y `secret`. La firma es HMAC-SHA256 sobre `timestamp + "." + cuerpo crudo`, con encabezados `X-Hospitality-Timestamp` y `X-Hospitality-Signature`; la tolerancia es 300 segundos. El cuerpo JSON requiere `id` estable, máximo 200 caracteres y 64 KiB de cuerpo. El identificador se deduplica bajo bloqueo del establecimiento; secretos/campos de tarjeta conocidos se redactan. El receptor registra `Received` y auditoría, **sin crear pagos, reservas ni accesos a cerraduras automáticamente**. Las pruebas y simulaciones están identificadas como tales.

Para activar un proveedor real se necesitan su documentación, acceso y credenciales, y pruebas de sus estados/cancelaciones. Los endpoints públicos tienen limitación de solicitudes. Mantenga las credenciales y la clave de cifrado del sitio en almacenamiento protegido.
