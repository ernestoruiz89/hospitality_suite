# Siguiente fase del objetivo activo

Actualizado el 20/10/2026. El alcance obligatorio sigue abierto: **80 V, ocho I, dos P y 128 R**, de las mismas 218 entradas. R significa contraste individual pendiente y no función ausente. No hay una estimación fiable de terminación hasta clasificar el inventario restante. Véase [contraste en bloque](AUDITORIA_FLUJOS_TRANSACCIONES.md).

## Diferencias materiales ya confirmadas

1. **Cargos periódicos de alojamiento — S12-03 y S16-06.** La entrada registra el importe aceptado y las extensiones agregan diferencias; el cierre captura/avanza fecha. Falta una política configurable que genere cargos por origen/período una sola vez, mantenga el total aceptado y no duplique efectos al repetir con otra clave HTTP. Completar su escenario nocturno en S17-08. No crear otro libro mayor ni confundir cargo operativo con devengo contable paralelo.
S14-08 quedó resuelto en 0.5.1: recibo mínimo sin cuerpo/identificador externo en texto, migración de Version y auditoría, 196 pruebas nativas/puras y treinta JavaScript. Véase AUDITORIA_RECEPTOR.md. No activa canales.

Las dos entradas P corresponden a cargos periódicos y su idempotencia. No representan todas las diferencias posibles: continúa el contraste de las 128 R.

## Contraste y verificaciones pendientes

1. **UX/UI y auditoría.** 0.5.2 agrupa los formularios por tarea, conserva datos entre pestañas y diferencia revisar/confirmar. Se acreditan configuración/tarifa/huésped, validación móvil, entrada y cobro/cierre desde Pages; siete regresiones nuevas y capturas 96–101, con aceptación restaurada. Véase UX_FORMULARIOS.md. Continúa la aceptación de todos los flujos y la auditoría en bloque. El primer bloque revisó 38 entradas de portal/integraciones, transacciones y escenarios, más S12-03: 28 V, siete I y tres P. Continuar Pages/UX, habitaciones, reservas, tarifas, estancias, contabilidad, limpieza/mantenimiento, inventario, cierre, seguridad y entregables. Relacionar código y aserciones/evidencia por cada obligación; una batería verde no acredita todas.
2. **Límites y trabajos.** Probar extremos exactos de [inicio, fin) y del colchón de limpieza, incluyendo el instante anterior y el extremo permitido (S16-03). Contrastar/documentar reintentos limitados del job de expiración, separándolos de nuevos despachos periódicos y recuperación manual (S16-10). Ya existen pruebas reales de ambas carreras, fallo/rollback y recuperación RQ.
3. **Contratos externos.** Acreditar adaptadores/simulaciones de canales, correo/WhatsApp y cerraduras además del doble de pago y receptor sintético ya probados (S14-05/07). El usuario pidió dejar pendiente la sincronización con Airbnb, Booking y otros canales; no implementarla ni activarla por ahora. Los proveedores reales son opcionales y esperan acceso/documentación/credenciales cuando se retome ese alcance. Véase INTEGRACIONES.md; nunca presentar simulaciones como operativas.
4. **Aceptación y demo.** Completar un escenario explícito reproducible que deje reservas/consumos identificados, separado de instalación y de tests revertidos (S17-17). Acreditar un usuario autorizado de recepción+caja en un mismo recorrido Pages y una sesión contable rastreando los documentos/reportes (S17-18); los recorridos actuales alternan recepción y cajero. Conservar permisos por función.
5. **Traducciones — S01-04.** Pages, errores, explicaciones y comprobantes tienen extracción/diccionario nativo y claves conservadas probados. Falta contrastar todos los textos dinámicos/secundarios antes de pasar a V.
6. **Recuperación final — F26.** Repetir respaldo con archivo privado, restauración, migrate, reversión de código y redespliegue de la revisión final. El ensayo histórico conserva 70 tablas/866 filas/archivo privado; 0.5.0 ya acredita actualización sin pérdida de 70 tablas/911 filas y restauración de aceptación con 71 tablas/185 filas. Esas pruebas no sustituyen la recuperación de la revisión que se entregue.

## Evidencia y entorno conservados

La batería de backend vigente es la de 0.5.1: **196 pruebas** (182 integración y catorce puras) en hospitality-acceptance.localhost. 0.5.2 aprueba **37 regresiones JavaScript** (35 Desk y dos portal) y un nuevo recorrido real de formularios, sin modificar reglas de backend. La migración/restauración conserva 72 tablas con Version (1191 filas principales/195 de aceptación) y los dos archivos privados principales; aceptación vuelve a cero operaciones. Las regresiones JavaScript no equivalen a 37 recorridos de interfaz.

Los reportes mínimos de la sección 13 ya están contrastados, con nombres legibles, referencias técnicas opcionales, dimensiones, monedas separadas y PDF/XLSX. Las políticas, artículos/cuentas por servicio, arqueo POS, anticipos/garantías y devoluciones compuestas tienen auditorías específicas y recorridos conservados. Capturas 01–95 y su alcance están en evidence/README.md.

La demostración principal conserva su fecha operativa 19/10 y no se confirmó su cierre durante la revisión. El corte operativo respeta [corte de D, corte de D+1) en la zona local, incluidos días de 23/25 horas. La diferencia histórica de Company está atribuida exclusivamente a dos cachés y modified del mantenimiento nativo; las otras 35 tablas conservan su huella histórica y las 36 coinciden con el respaldo anterior a 0.5.0. Véase accounting-company-cache.json. No se sustituyó una tabla cambiada por una huella nueva sin explicación.

hospitality-clean.localhost conserva respaldo de diagnóstico y scheduler pausado tras la interrupción de WSL que dejó datos parciales. No usarlo para aceptación ni reparar sus libros manualmente. hospitality-acceptance.localhost está designado para pruebas, con respaldo y sin operaciones remanentes después de restaurar. before_tests rechaza fixtures en la demostración. El servidor temporal 8089 y el de restauración 8088 quedaron detenidos; la demostración usa 8086/Socket.IO 9001.

No se desplegó en producción ni se modificó un sitio ajeno. El objetivo sigue activo hasta resolver las diferencias y acreditar todo el alcance obligatorio.
