# Contraste de flujos, transacciones y aceptación

Revisión del 20/10/2026 sobre el código de aplicación 0.5.0 (`b52eefb`). Se revisaron en bloque 38 entradas: S12-03, sección 14, sección 16 y sección 17. Se contrastaron implementaciones, aserciones de las pruebas y evidencia conservada; esta revisión no representa una nueva ejecución de la batería ni un recorrido adicional de navegador.

De esas entradas, 28 pasan a V, siete a I y tres a P. El inventario completo conserva sus **218 entradas y la huella del documento original: 79 V, ocho I, tres P y 128 R**. R sigue significando contraste pendiente, sin afirmar ausencia de implementación. Estos números miden aceptación documentada y no permiten calcular un porcentaje de programación restante.

La [matriz individual](AUDITORIA_ESPECIFICACION.md) identifica código, caso y evidencia por requisito. [flow-audit.json](evidence/flow-audit.json) conserva los casos JUnit contrastados y las comprobaciones estáticas/puras de esta revisión. La batería vigente permanece en **193 aprobadas** (179 de integración y catorce puras), con **30 regresiones JavaScript**. Estas últimas no representan treinta recorridos de navegador.

## Flujos ya acreditados

La prueba de hotel reserva dos noches, recibe 500 de anticipo, entrega dos aguas, presenta una Sales Invoice de 3060, aplica el anticipo mediante ERPNext, cobra 2560 y registra salida/limpieza/inspección. Las capturas 08–12 acreditan el recorrido de Pages y adaptación móvil. Para motel, las pruebas puras comprueban medianoche/cambio de año y el límite exacto de tolerancia; la prueba nativa prepara una liquidación de tiempo una sola vez. El recorrido 01–06 incluye extensión, cobro, vuelto y liberación de habitación.

Las pruebas grupales verifican habitaciones y estancias diferentes, traslado de cargos sin duplicación y factura consolidada de 6000 con dos líneas. El recorrido 24–30 añade empresa/huésped, cuenta personal de 30, pagos y arqueo de 6030. El cambio de habitación conserva segmentos y deja sucia la anterior; el cambio de categoría aplica la diferencia aceptada. La extensión conflictiva se rechaza tanto en integración como en la Page.

Cancelación, no presentación y expiración usan las acciones reales del servicio. La prueba de reportes crea las decisiones Cancelled/No Show con cargos de 100/80 y sus facturas, créditos y anulaciones nativas; la de devolución parcial conserva 400 de un anticipo original de 500. El fallo y recuperación reales del worker conservan el cupo hasta confirmar y después lo liberan sin duplicarlo.

Las pruebas financieras contrastadas comprueban anticipos antes/después de facturar, garantías como pasivo, aplicación sin segundo ingreso, devoluciones, combinación NIO/USD, cambio conservado, redondeo nativo 0/3 y arqueo con diferencia. Facturas y pagos presentados/anulados directamente con los controladores ERPNext se reflejan en los cargos y saldos de estancia. Los casos de seguridad incluyen una segunda Company real, alcance por establecimiento, roles combinados, API, listados, archivos privados y documentos financieros.

## Exclusión, atomicidad y recuperación

El servicio bloquea la fila persistente de HS Property antes de consultar asignaciones o peticiones. Así protege también una habitación sin reservas previas. `current_all` hace lecturas actuales bajo el bloqueo para evitar un snapshot anterior de REPEATABLE READ. Las dos pruebas con conexiones independientes acreditan exactamente una confirmación para habitación vacía y último cupo de categoría; las referencias JSON conservan el resultado de cada conexión.

Las restricciones únicas de acceso, número de habitación, fecha de cierre, pagadores y otras claves de identidad se instalan por separado. La exclusión de intervalos no se delega a un índice único: bloquea el recurso/cupo e inspecciona los solapamientos dentro de la transacción. El motor cuenta una reserva una sola vez al convertir la asignación de categoría en estancia física.

Los comandos operativos y los documentos nativos pertenecen a la transacción de la petición Frappe, con savepoint local y sin commits intermedios en los módulos de ejecución. Los commits explícitos localizados pertenecen a herramientas de pruebas con conexiones/trabajos independientes; se excluyeron de la comprobación de ejecución. La notificación en tiempo real se publica tras el commit y no después de rollback.

El fallo inyectado al facturar deja cero HS Payment y cero facturas presentadas y conserva el cargo pendiente; la misma clave puede reintentarse. El proxy real de pérdida de respuesta conserva la intención y confirma una sola factura, un solo pago y una sola salida de stock; su devolución estándar restaura existencias. Los tres transportes autenticados prueban aislamiento, reconexión y recuperación de un cambio perdido. Los proveedores externos siguen sin activarse; no hay una supuesta transacción distribuida de pagos.

Falta una prueba específica de extremos exactos del intervalo y del colchón de limpieza (S16-03). Las pruebas de tolerancia de tarifa no acreditan ese límite de inventario. También debe cerrarse el contraste de la política limitada de reintentos del job de expiración, distinguiendo un reintento de un despacho periódico nuevo y de la recuperación manual (S16-10).

## Diferencias materiales confirmadas

**Cargos periódicos de alojamiento: S12-03 y parte de S16-06.** La entrada registra el importe completo aceptado; extensión y preparación de salida agregan diferencias. `daily_close` captura el resumen, detecta pendientes y avanza la fecha. El scheduler instalado expira retenciones. No existe una política/proceso que genere cargos por períodos de alojamiento. Repetir un cierre sin duplicar su fecha no prueba generación periódica. Hace falta una política configurable, un origen/período único y pruebas de reintento con la misma y con distinta clave de petición. El saldo total, los anticipos y los importes ya aceptados deberán conservarse. Esta diferencia operativa no exige crear otro libro ni cambiar el reconocimiento contable nativo al presentar Sales Invoice.

**Datos conservados de webhooks: parte de S14-08.** Firma HMAC, caducidad y deduplicación están probadas. Sin embargo, el receptor guarda el cuerpo después de filtrar nombres conocidos de campos. La evaluación pura del sanitizador actual comprueba que elimina `cvv`, pero conserva `nested.card.number` cuando el campo se llama `number`. Se usaron únicamente marcadores ficticios, sin petición HTTP ni escritura de datos. Hace falta restringir lo que se persiste a campos permitidos del contrato y probar otras estructuras; una lista de nombres prohibidos no acredita ausencia de números completos de tarjeta o secretos en cuerpos arbitrarios.

Las tres P representan estas dos diferencias, porque la generación periódica afecta a dos requisitos. No son el inventario completo de posibles diferencias: quedan 128 entradas R por contrastar.

## Verificaciones aún abiertas en este bloque

- **S14-05/S14-07:** los cuatro contratos abstractos y la API están documentados. La simulación de pago y el webhook sintético están probados e identificados; falta acreditar adaptadores/simulaciones de las otras familias. La activación real de canales, mensajería y cerraduras continúa siendo opcional y dependiente de proveedor.
- **S16-03/S16-10:** límites de disponibilidad y política de reintentos descritos arriba.
- **S17-08:** completar el escenario nocturno repetido cuando exista la generación periódica; cobro repetido y cierre/avance de fecha ya tienen evidencia.
- **S17-17:** seed explícito prepara hotel/motel de diez habitaciones, tarifas y usuarios por rol. Los tests crean reservas y consumos dentro de transacciones revertidas. Contrastar y entregar el escenario demostrativo completo y repetible que deje esas operaciones identificadas, separado de instalación y batería.
- **S17-18:** completar un recorrido Pages con usuario autorizado de recepción+caja y sesión contable de rastreo de documentos. Los recorridos actuales alternan recepción y cajero; no se considera acreditado todo el texto por esa equivalencia ni se amplía automáticamente el permiso de recepción.

La instalación limpia y la migración previa sin pérdida de datos quedan contrastadas para S17-16: aceptación tiene aplicación instalada y la actualización de 0.5.0 compara las 70 tablas/911 filas previas, incluidos sus campos anteriores. La aceptación restaurada conserva 71 tablas/185 filas. Esa evidencia no sustituye el ensayo final de restauración con archivo privado y reversión/redespliegue de la revisión que se entregue, que continúa abierto en F26.

## Trabajo siguiente

Continuar el contraste en bloque de Pages/UX, habitaciones, reservas, tarifas, estancia, contabilidad, limpieza/mantenimiento, inventario, cierre, seguridad y entregables. Corregir las diferencias confirmadas, completar las verificaciones abiertas, revisar los textos dinámicos de traducción y repetir la recuperación final después del último cambio. La existencia de 193 pruebas aprobadas no declara completo el alcance ni aptitud para producción; todavía no hay una estimación de terminación respaldada por el inventario completo.
