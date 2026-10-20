# Receptor de integraciones: datos mínimos

Versión 0.5.1, 20/10/2026. S14-08 pasa de P a V por la corrección del receptor existente, sin implementar sincronización con canales. El usuario pidió dejar Airbnb, Booking.com y otras plataformas pendientes. Esa decisión se conserva en [INTEGRACIONES.md](INTEGRACIONES.md).

El receptor ya no conserva cuerpos filtrados por una lista de nombres. Después de validar firma, caducidad, tamaño y forma del identificador, calcula una huella y retira el cuerpo/identificador de las variables locales antes de escribir documentos. Guarda únicamente `schema`, `source`, `body_bytes` y `body_sha256`; `event_id` también es una huella por proveedor. `Received` conserva su significado técnico y no acredita reserva, cobro ni acceso a cerradura.

Los reenvíos conservan el recibo original incluso si cambia el cuerpo, y otros proveedores tienen otra identidad. Los JSON inválidos, identificadores no admitidos, cuerpos demasiado grandes y proveedores no configurados dejan los documentos operativos y financieros intactos. Las pruebas usan marcadores ficticios de tarjeta/secretos, incluidos campos anidados con nombres no conocidos por el sanitizador anterior.

La migración nativa convierte payloads históricos a huellas marcadas como `legacy_payload`. También retira los campos de payload/error de Version, conserva los otros cambios y sus metadatos, y agrega auditoría sin los contenidos retirados. Repetirla no vuelve a cambiar registros ni duplicar auditoría. No altera facturas, pagos ni libros de contabilidad/stock. Los respaldos históricos no se reescriben; su retención corresponde a la política de almacenamiento.

## Evidencia revisada

- [integration-native-tests.xml](evidence/integration-native-tests.xml): **196 aprobadas**, 182 integración y catorce puras; tres casos nativos adicionales y reemplazo de la prueba pura de filtrado por conservación mínima. Los cuatro métodos de TestWebhook prueban firma/reenvío, forma/ausencia de efectos, identidad por proveedor y migración real con Version/auditoría. TestIntegrationContracts prueba firma/caducidad y el resumen sin contenidos del proveedor.
- [integration-js-tests.log](evidence/integration-js-tests.log): **30 aprobadas**, veintiocho Desk y dos portal. No son recorridos nuevos de navegador ni cambios de interfaz.
- [integration-upgrade.json](evidence/integration-upgrade.json): respaldos nativos con archivos de ambos sitios; las 72 tablas comparadas, incluida Version, mantienen todas sus columnas/1191 filas en demostración y 195 en aceptación. Dos archivos privados de demostración mantienen sus bytes. Ambos sitios tenían cero recibos de proveedores; los registros antiguos se ejercitaron en transacciones de pruebas revertidas.
- [integration-main-migrate.log](evidence/integration-main-migrate.log) e [integration-acceptance-migrate.log](evidence/integration-acceptance-migrate.log): patch nativo y sincronización instalados en ambos destinos.
- [integration-final-state.json](evidence/integration-final-state.json): aceptación sin operaciones, guardia de fixtures, HTTP/servicios y puertos; 35 tablas nativas conservan su huella histórica y Company conserva la caché nativa acreditada en accounting-company-cache.json. Además, la comparación fresca de las 72 tablas comprueba la conservación durante esta fase.

Las primeras comprobaciones encontraron dos errores de los tests: un paréntesis y la comparación de fechas en memoria como texto contra fechas recargadas como datetime. Se corrigió el fixture sin relajar la comprobación de metadatos; la batería completa final pasa. La detención gradual del worker excedió la espera del helper: se verificó la terminación real del proceso antes de iniciarlo de nuevo, sin forzar otro por un timeout.

La matriz conserva sus 218 entradas: **80 V, ocho I, dos P y 128 R**. Las dos P restantes corresponden a cargos periódicos y su idempotencia. Contratos/simulaciones de otras familias, traducciones, aceptación completa y recuperación final siguen abiertos. Las mejoras de claridad y longitud de formularios solicitadas por el usuario son la siguiente prioridad de UX/UI. No se declara terminado el objetivo.
