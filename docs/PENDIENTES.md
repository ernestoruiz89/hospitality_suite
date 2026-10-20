# Siguiente fase del objetivo activo

Actualizado el 20/10/2026. El alcance obligatorio sigue abierto: **83 V, siete I, una P y 127 R**, de las mismas 218 entradas y huella. R significa contraste individual pendiente y no función ausente. Los recuentos no son un porcentaje de programación ni una fecha de terminación.

## Diferencia material ya confirmada

1. **Facturación explícita desde Pages — S00-02 / F22.** Añadir revisión y emisión de factura de cuenta sin cobrar ni registrar salida, incluido importe cero. El contrato autenticado invoice funciona, pero la interfaz solo lo alcanza de forma implícita al cobrar o salir. No registrar un cobro ficticio ni dar salida a una estancia activa para facturar. La ausencia de la ruta se contrasta en periodic-page-invoice-gap.json y la captura 103; este es el próximo cambio de Pages.

S12-03/S16-06/S17-08 pasan a V en 0.6.0. La política por noche conserva importes/orígenes, genera una vez por fecha y liquida anticipadamente al facturar; repetición, recuperación, extensión cero y facturación nativa están probadas. CARGOS_PERIODICOS.md delimita reglas y evidencia. S14-08 quedó resuelto en 0.5.1 con recibos mínimos; no activa canales.

## Contraste y verificaciones pendientes

1. **Auditoría y UX completa.** Continuar las 127 R de Pages, habitaciones, reservas, tarifas, estancias, contabilidad, limpieza/mantenimiento, inventario, cierre, seguridad y entregables. Relacionar cada obligación con código/aserciones/evidencia. Ya se agrupan formularios, se conserva el borrador entre pestañas y se diferencian revisar/confirmar; UX_FORMULARIOS.md acredita 0.5.2 y CARGOS_PERIODICOS.md amplía la política y las secciones del cierre. Completar la aceptación de cada flujo, sin inferirla de una batería verde.
2. **Límites y trabajos.** Probar extremos exactos de [inicio, fin) y colchón de limpieza, incluido el instante anterior y el extremo permitido (S16-03). Contrastar reintentos limitados del job de expiración, separándolos de nuevos despachos periódicos y recuperación manual (S16-10). Ya existen pruebas de carreras reales, fallo/rollback y recuperación RQ.
3. **Contratos externos.** Acreditar las otras familias de contratos/simulaciones, además del doble de pago y receptor sintético (S14-05/07). El usuario pidió dejar pendiente la sincronización con Airbnb, Booking y otros canales: no implementarla ni activarla. Los proveedores reales son opcionales; INTEGRACIONES.md conserva alcance y fuentes. No presentar simulaciones como operativas.
4. **Aceptación y demo.** Crear un escenario explícito reproducible que deje reservas/consumos identificados, separado de instalación y tests revertidos (S17-17). Acreditar un usuario autorizado de recepción+caja en un recorrido Pages completo y una sesión contable rastreando documentos/reportes (S17-18). Los recorridos previos alternan recepción/cajero/gerencia; conservar permisos por función.
5. **Traducciones — S01-04.** Contrastar textos dinámicos/secundarios antes de pasar a V. Pages, errores, explicaciones y comprobantes tienen extracción/diccionario nativo y claves conservadas probados.
6. **Recuperación final — F26.** Repetir respaldo con archivo privado, restauración, migrate, reversión de código y redespliegue de la revisión final. El ensayo histórico conserva 70 tablas/866 filas/archivo privado; las actualizaciones y restauraciones actuales no sustituyen ese ensayo final.

## Evidencia y entorno conservados

0.6.0 aprueba **211 pruebas** (197 integración y catorce puras) y **38 regresiones JavaScript** (36 Desk y dos portal). Quince casos nativos nuevos cubren programación, precios distintos/cero, idempotencia, interrupción, cierre/reapertura y facturación estándar; una regresión JS cubre grupos desplegables. El recorrido real guarda/reabre la política móvil y prepara dos veces tres noches por 4500: una generada/1500, dos programadas/3000, sin factura/pago. PDF nativo de una página renderizado/revisado. Capturas 102–105; no equivalen a 38 recorridos de navegador.

Respaldos con archivos, migración y comparación de todas las columnas anteriores de **72 tablas con Version**, 1191 filas y dos archivos privados principales/195 filas de aceptación conservados. Columnas nuevas con valores iniciales, sin programaciones retroactivas. La restauración de aceptación conserva también todas las columnas nuevas de **71 tablas/185 filas**; queda sin operaciones después del recorrido y de la batería final. 8089 cerrado; demostración en 8086/Socket.IO 9001, web/worker actualizados y núcleos limpios.

La fecha operativa principal sigue en 19/10 y no se confirmó su cierre. El corte respeta [corte de D, corte de D+1) en la zona local, incluidos días de 23/25 horas. Company conserva su acreditación de diferencia histórica limitada a dos cachés/modified; las otras 35 tablas mantienen la huella histórica y las 36 coinciden con el respaldo previo. periodic-upgrade.json acredita por separado la conservación de esta actualización. No se sustituyen huellas para ocultar cambios.

hospitality-clean.localhost continúa con respaldo de diagnóstico y scheduler pausado tras la interrupción de WSL. No usarlo para aceptación ni reparar sus libros manualmente. hospitality-acceptance.localhost es el sitio designado de pruebas; before_tests rechaza fixtures en la demostración principal. El servidor de restauración 8088 permanece detenido. No se desplegó en producción ni se modificó un sitio ajeno. El objetivo permanece activo.
