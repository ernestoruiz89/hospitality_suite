# Integraciones y sincronización externa

## Decisión de alcance

El 20/10/2026 el usuario indicó que aún no tiene anuncios y pidió **dejar pendiente la sincronización con Airbnb, Booking.com y otros canales**. No se conecta ninguna cuenta ni se implementa o activa esa sincronización en esta fase. Continúa el alcance operativo de la aplicación. Los contratos preparados y el receptor existente no equivalen a canales conectados.

## Componentes existentes

`integrations.py` define contratos abstractos de pago, canales, mensajería y cerraduras. Falta acreditar el conjunto de adaptadores/simulaciones de las otras familias, registrado en S14-05/S14-07. El proveedor concreto necesitará documentación, autorización y credenciales propias cuando se retome ese trabajo.

El receptor genérico valida firma HMAC, caducidad, tamaño, forma del identificador y deduplicación por proveedor. Su resultado `Received` significa recepción técnica. No importa reservas ni modifica cupos, no presenta pagos y no concede accesos a cerraduras.

Desde 0.5.1 el cuerpo arbitrario no se guarda. `HS Integration Event.payload` contiene únicamente `schema="receipt-v1"`, `source`, `body_bytes` y `body_sha256`. El identificador externo se usa en memoria para calcular `event_id`, una huella por proveedor; tampoco se conserva en texto. Un reenvío con el mismo identificador devuelve el recibo original sin reemplazar su huella. Para corregir o cambiar un evento, el adaptador futuro tendrá que usar el contrato de identificadores del proveedor y un flujo explícito, sin interpretar una respuesta recibida como negocio confirmado.

La migración reemplaza contenidos anteriores por una huella marcada `source="legacy_payload"`, que corresponde al texto histórico guardado y no al cuerpo HTTP original desconocido. Retira contenidos de `payload` y `last_error` de Version, conserva los otros cambios y metadatos, y audita la minimización sin copiar los valores retirados. No modifica documentos contables ni inventario. Los respaldos anteriores conservan su contenido y siguen la política de almacenamiento/retención documentada en OPERACION.md.

## Opciones para cuando se retome

Consulta de fuentes oficiales realizada el 20/10/2026; las condiciones pueden cambiar.

| Vía | Qué permite | Acceso y límites actuales |
|---|---|---|
| Gestor de canales autorizado | Centralizar conexiones y sincronizar las funciones que ofrezca su API: disponibilidad, tarifas, reservas y cambios | Requiere elegir proveedor, acceso a su API y asociar alojamientos/categorías/tarifas. No se ha elegido ni contratado uno. |
| Booking.com Connectivity | Gestionar disponibilidad, tarifas y reservas de alojamientos conectados | El portal indica pausa de integraciones con nuevos proveedores y remite a alojamientos individuales a un gestor de canales. Tener un anuncio no concede por sí solo acceso a la API. |
| Software conectado a Airbnb | Conectar anuncios y sincronizar datos según programa, permisos y modo contratado | Requiere software admitido y autorización de la cuenta. La aplicación actual no está conectada ni aprobada como proveedor. |
| Calendarios iCal | Compartir fechas bloqueadas mediante enlaces .ics | Airbnb indica actualización automática cada tres horas. No acredita una sincronización completa de reservas/tarifas ni inmediatez. Su implementación también queda pendiente. |

Fuentes: [portal oficial Booking.com](https://connect.booking.com/?lang=en), [Connectivity APIs](https://developers.booking.com/connectivity/docs), [gestores de canales de Airbnb](https://www.airbnb.com/help/article/3304), [conexión de anuncios mediante software](https://www.airbnb.com/help/article/2346), [modalidades de sincronización de Airbnb](https://www.airbnb.com/help/article/2348) y [sincronización de calendarios](https://www.airbnb.com/help/article/99).

## Requisitos para la futura conexión

Antes de activarla habrá que asociar establecimiento, anuncio, categoría/habitación y plan tarifario; conservar origen e identificadores sin duplicar reservas; tratar altas, modificaciones y cancelaciones; y enviar disponibilidad desde el mismo motor que usa recepción. Los conflictos deberán quedar visibles y recuperables. Una reserva confirmada externamente que choque con el cupo local necesita resolución explícita; nunca se debe borrar otra reserva para encajarla ni prometer atomicidad entre servicios independientes.

Los precios aceptados y las monedas deben conservarse según el contrato elegido, con reglas de impuestos y comisiones explícitas. La importación de una reserva no prueba que el canal haya cobrado o liquidado dinero. Reintentos, vencimiento/revocación de credenciales, trabajos fallidos y conciliación necesitan pruebas del proveedor antes de mostrar una conexión como operativa.

Esta lista prepara el trabajo futuro y no declara esas funciones implementadas. No se necesitan cuentas ni credenciales externas para usar y probar la operación local del hotel.
