# Contratos y adaptadores de referencia — 0.8.8

`hospitality_suite/provider_adapters.py` implementa **Hospitality Provider Contract v1**, un protocolo propio de referencia para preparar integraciones. No implementa la API comercial de una pasarela, Meta/WhatsApp, un fabricante de cerraduras, Airbnb ni Booking. No hay cuentas, credenciales reales, proveedores activos ni conexiones externas en esta fase. Los dobles de pruebas están en `tests/test_provider_adapters.py`, identificados como simulados, y prohíben conexiones de red.

| Familia | Contrato y adaptación entregados | Estado operativo |
| --- | --- | --- |
| Pagos | `PaymentGateway` → `ReferencePaymentAdapter`: intención recuperable y normalización de evento con firma | Referencia probada; no contabiliza pagos |
| Correo | `MessagingGateway` → `ReferenceMessagingAdapter(medium="email")`: destinatario, plantilla y enlace de confirmación | Referencia probada; sin envío real |
| WhatsApp | Mismo contrato, `medium="whatsapp"`, número internacional con `+` | Referencia probada; sin cuenta, plantilla comercial ni envío real |
| Cerraduras | `LockGateway` → `ReferenceLockAdapter`: solicitar vigencia y revocar identificador de acceso | Referencia probada; ningún hardware conectado |
| Canales | `ChannelGateway` → `ReferenceChannelNormalizer`: mapeo de una solicitud entrante, sin ejecutarla | **Sincronización aplazada por el usuario**; publicar disponibilidad devuelve `ProviderUnavailable` |

Los adaptadores son una biblioteca privada para un integrador. **No son nuevos RPC, acciones de Page, tareas programadas ni hooks de entradas, salidas o cobros.** El receptor público existente sigue registrando únicamente un recibo mínimo `Received`, sin invocar estos adaptadores. No se amplía la superficie pública ni se permite que un estado externo cree dinero, reservas o accesos automáticamente.

## Uso y autorización

El integrador debe comprobar en el servidor rol, acceso a compañía/establecimiento y origen real mediante las APIs nativas del PMS; una operación pendiente de commit no autoriza un envío. El SDK recibe ese contexto autorizado y lo incluye en cada petición. Rechaza respuestas de otro contexto o versión de contrato. Para cerraduras, debe comprobar además estancia activa, segmento de habitación y vigencia autorizada antes de despachar; para mensajes, debe usar destinatario autorizado y el enlace firmado generado por el PMS. El SDK no sustituye estas reglas operativas ni confirma que el hardware haya funcionado.

Construcción desactivada, sin solicitud de red:

```python
from hospitality_suite.provider_adapters import HttpContractTransport, ReferencePaymentAdapter

transport = HttpContractTransport("https://provider.example.invalid", enabled=False)
gateway = ReferencePaymentAdapter(
    transport, company="Compañía ficticia", property_name="PROPERTY-TEST"
)
# create_intent ahora rechaza provider_disabled_or_missing_credentials.
```

La dirección `.invalid` es ficticia, no un servicio para conectar. Una integración real necesita implementar o traducir este protocolo al del proveedor elegido, cargar sus secretos desde configuración privada y habilitar expresamente su transporte. `hospitality_integrations` continúa siendo la configuración privada del receptor: no habilita por sí sola ningún envío saliente. No copie los valores `FICTIONAL-*` de las pruebas a una configuración operativa.

## Transporte común

`HttpContractTransport(base_url, token=None, enabled=False, timeout=5, opener=None)` usa HTTPS verificado. La base debe ser un origen sin credenciales, ruta, query ni fragmento; el timeout debe ser mayor que cero y como máximo treinta segundos. `opener` permite inyectar el doble de pruebas; no desactiva la validación del adaptador. No se siguen redirecciones, para evitar trasladar la autorización a otro destino. Las respuestas HTTP fallidas se cierran y el error expuesto no incluye cuerpo, token ni datos del proveedor.

Cada POST incluye `Authorization: Bearer <secreto privado>`, `Content-Type: application/json`, `Accept: application/json`, `Idempotency-Key` y `X-Hospitality-Payload-SHA256`. La clave admite 1–128 caracteres ASCII alfanuméricos o `_.:-`, sin espacios ni saltos de línea. El JSON es canónico para su huella. Petición y respuesta tienen límite de 64 KiB. La respuesta exige `application/json` y un objeto válido, sin claves duplicadas ni números no finitos.

El proveedor que implemente este contrato debe conservar de forma duradera `(credencial/ámbito, ruta, clave)` y su huella: repetir la misma carga devuelve la misma identidad; reutilizar la clave con otra carga devuelve conflicto 409. El SDK no finge una deduplicación duradera en memoria. Hace **un intento por llamada**. `ProviderFailure.retryable` es verdadero ante 429, 5xx o error de transporte/timeout, y falso para los demás HTTP fallidos. Un timeout puede ocultar una solicitud ya aceptada: el llamador conserva carga y clave y limita sus reintentos. No se crea una cola saliente ni un segundo sistema de jobs.

Todas las peticiones y respuestas llevan:

```json
{
  "contract": "hospitality-provider-v1",
  "scope": {"company": "Compañía ficticia", "property": "PROPERTY-TEST"}
}
```

Las respuestas añaden `id` estable y `status` de la familia indicada. Un estado no reconocido o un ámbito distinto se rechaza. Los campos adicionales del proveedor se descartan de los resultados normalizados; no se almacenan datos completos de tarjeta, códigos de acceso ni secretos. El SDK no registra cuerpos ni respuestas crudas. El integrador debe conservar también esa política en su código, logs y configuración.

## Pasarela

`create_intent(origin, amount, currency, idempotency_key)` envía POST `/v1/payment-intents`. El cuerpo añade origen interno, importe decimal positivo y moneda de tres letras mayúsculas. Se aceptan `str`, `int` o `Decimal`, sin `bool`/`float`, con hasta 18 dígitos enteros y nueve decimales como límites técnicos; no se fija una precisión fiscal ni tasa tributaria. Las representaciones equivalentes se normalizan sin ceros finales. La respuesta debe repetir origen, importe y moneda; solo admite `pending` o `requires_action`. Devuelve siempre `payment_recorded=False`.

`verify_event(raw_body, headers)` no hace solicitudes. Usa el mismo formato HMAC-SHA256 de `integrations.validate_signature`: timestamp, punto y bytes originales; encabezados `X-Hospitality-Timestamp` / `X-Hospitality-Signature`, tolerancia de 300 segundos. Exige además contexto, `id`, `intent_id`, origen, importe y moneda. Estados admitidos: `pending`, `settled`, `failed`, `cancelled`, `refunded`. Incluso un evento firmado `settled` devuelve **`payment_recorded=False`**: el integrador debe contrastar el estado real, identidad, importe y origen y usar el flujo contable autorizado del PMS; este SDK nunca presenta Payment Entry ni marca la reserva como pagada.

El receptor público y su minimización, deduplicación y migración conservan su contrato en [API.md](API.md). Su recibo `Received` tampoco equivale a liquidación.

## Correo y WhatsApp

`ReferenceMessagingAdapter(..., medium, confirmation_origin, template_id)` exige medio `email` o `whatsapp`, origen HTTPS del PMS y plantilla configurada. `send_confirmation(recipient, signed_url, idempotency_key)` hace POST `/v1/messages`, añadiendo esos cuatro campos. El correo debe tener estructura de dirección y no contener saltos de línea; el teléfono usa `+`, primer dígito no cero y entre 8 y 15 dígitos.

El enlace debe corresponder al origen configurado, ruta `/hospitality-confirmation`, un único `token` no vacío y sin fragmento. La autenticidad/caducidad de ese token sigue siendo responsabilidad del portal nativo al consultarlo; el SDK no lo inventa ni lo renueva. Respuestas admitidas: `queued` o `accepted`. Devuelve `delivery_confirmed=False`; una aceptación no se presenta como entrega al huésped.

## Cerraduras

`grant_access(stay, room, starts_at, ends_at, idempotency_key)` hace POST `/v1/access-grants`. Requiere identificadores y dos instantes ISO con zona u offset explícitos, fin posterior a inicio y aún no vencido. Normaliza la ventana a UTC. La respuesta `scheduled` o `active` debe repetir estancia, habitación y la misma ventana; el resultado no devuelve PINs, tarjetas ni códigos del proveedor. El estado describe su respuesta de protocolo, no una comprobación física.

`revoke_access(grant_id, idempotency_key)` hace POST `/v1/access-grants/{id}/revoke`. El identificador solo admite caracteres alfanuméricos ASCII o `_.:-`, máximo 200, excluyendo `.` y `..`; no se puede introducir otra ruta o query. Solo acepta `revoked` para la misma identidad. La vigencia no se toma del reloj del navegador ni de una duración sin zona horaria.

## Canales: solo contrato entrante

`ReferenceChannelNormalizer(company, property_name, category_map)` valida un objeto de este contrato con `id` externo, categoría externa mapeada explícitamente, `quantity`, `people`, `starts_at` y `ends_at`. Cantidad/personas deben ser enteros de 1–100 como límites de entrada, no como autorización de cupo/capacidad. Devuelve la categoría interna, intervalo UTC y **`requires_pms_validation=True`, `provider_confirmation=False`**. Descarta precios, nombres y campos arbitrarios externos.

No confirma reservas, crea huéspedes, bloquea inventario ni modifica tarifas. Para llegar a una reserva operativa harían falta revisión, mapeo autorizado de personas/pagador, cotización aceptada y el mismo comando transaccional de reservas que usa Recepción. `publish_availability(property_name, category, intervals, idempotency_key)` **siempre rechaza `channel_synchronization_deferred`**, sin disponer de transporte. No se implementa ni se ejecuta sincronización Airbnb/Booking, iCal ni channel manager.

## Pruebas y límites comprobados

[Dieciocho casos dirigidos](evidence/provider-contracts-focused-tests.log) prueban las familias con un servicio ficticio en memoria y un bloqueo de red. Incluyen respuesta perdida después de aceptación y reintento desde otra instancia sin duplicar; conflicto de carga/clave; ámbito/origen/importe/moneda incorrectos; firmas alteradas/vencidas; límites JSON, contenido inválido y cierre de respuestas fallidas; rechazo de redirección/rutas; destinatarios/enlaces; vigencias con zona y revocación; canal sin publicación; y ausencia de RPC/jobs/hooks que activen los adaptadores.

[Regresión nativa completa](evidence/provider-contracts-native-tests.xml), [log](evidence/provider-contracts-native-tests.log) y [ejecución/normalización de los dos documentos JUnit nativos](evidence/provider-contracts-native-run.json) conservan todos los casos, incluidos webhooks y conciliación existentes. [Regresión de interfaz](evidence/provider-contracts-js-tests.log) comprueba las Pages existentes; no se modifica frontend ni se atribuye un recorrido visual nuevo a esta fase. El primer pase dirigido aprobó los casos pero advirtió respuestas HTTPError sin cerrar: se corrigió la liberación de recursos y se repitió antes de la batería completa.

La evidencia acredita preparación de contratos/adaptadores y simulaciones claramente delimitadas, **no disponibilidad comercial de proveedores reales**. Las integraciones externas opcionales requieren elección, documentación, acceso, credenciales y aceptación específica del proveedor. La sincronización de reservas continúa aplazada por instrucción del usuario.

## Estado de la fase

La regresión completa aprueba **404 casos nativos (372 integración y 32 unitarios) y 210 JS**. [Límites de activación](evidence/provider-contracts-boundaries.json) confirma cuatro clases concretas, cero nuevos RPC, ningún hook/job que las active y cero proveedores habilitados en ambos sitios. [Inventario instalado](evidence/provider-contracts-native-artifacts.json): se mantienen 35 DocTypes, once Pages, nueve formatos, seis patches y 28 APIs, con campos/permisos contrastados en 0.8.8.

Aceptación se restaura y migra a 0.8.8: [71 tablas/185 filas](evidence/provider-contracts-ux-restored.json), [72/250 con Version y conservación de principal 72/1246/dos archivos](evidence/provider-contracts-upgrade.json). Ambos [migrate](evidence/provider-contracts-acceptance-migrate.json) [terminan correctamente](evidence/provider-contracts-main-migrate.json); [servicios/guardas](evidence/provider-contracts-final-state.json) conserva fecha 19/10, HTTP 200, servicios aislados activos y 8089 detenido. La restauración de fixtures no sustituye el ensayo final de despliegue/reversión F26.

S14-05/S14-07 pasan I→V por preparación/simulación, bajo el aplazamiento explícito de sincronización y el carácter opcional de los proveedores comerciales. La matriz conserva los 218 textos/huella: **202 V, cuatro I y doce R: dieciséis sin cierre**. El objetivo general sigue activo. [Verificación acotada de esta fase](evidence/provider-contracts-verification.json).
