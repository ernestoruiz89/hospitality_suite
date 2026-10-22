# Bloqueos operativos de habitación

La Page **Bloqueos de habitaciones** retira una habitación física de venta durante un intervalo para uso interno, VIP, propietario, mantenimiento u otro motivo. Es independiente de una reserva retenida y de una orden de mantenimiento. Para registrar trabajo, responsable, repuestos y reapertura supervisada, utilice **Mantenimiento**.

Recepción o Gerencia selecciona una habitación activa, el motivo, inicio, fin y una nota opcional. Para «Otro», la nota es obligatoria. El fin es **exclusivo**; desde ese instante la habitación vuelve a estar disponible automáticamente. Los establecimientos de tipo «Por tiempo» y «Mixto» pueden usar horas y minutos, además de días completos.

La operación se rechaza si coincide con una reserva, estancia u otro bloqueo, o si al reducir el cupo de la categoría incumple una reserva aún sin habitación asignada. Un bloqueo válido crea un documento **HS Room Block** y una asignación **HS Allocation**; el mismo cálculo de disponibilidad protege reservas, entradas y cotizaciones. El bloqueo aparece en Recepción, la ficha y agenda de la habitación, el calendario, los indicadores y el historial.

La acción **Liberar** exige un motivo. Conserva el bloqueo, usuario, fecha y explicación; libera la asignación y recorta el período histórico a la hora efectiva. Las órdenes de mantenimiento conservan su propio flujo de finalización. Las acciones de bloqueo y liberación usan las claves de idempotencia y el bloqueo transaccional por establecimiento de la Suite.

Para desplegar en un sitio existente, sincronice el esquema con `python tools/generate_schema.py`, ejecute `bench --site <sitio> migrate` y `bench build --app hospitality_suite`. Ningún bloqueo histórico se convierte automáticamente.
