# Panel de estancia y estados compartidos

Revisión sobre 0.8.8, después de `fbb4ce7`. Las acciones del panel de estancia pasaban directamente a sus manejadores y omitían el coordinador de la Page. Ahora usan el mismo bloqueo de preparación y tratamiento de errores. El panel conserva su contenido si está desconectado; su cierre sin animación evita dejar la capa anterior sobre el formulario siguiente. No cambian comandos, permisos, claves ni reglas de negocio.

Tres regresiones fallan con la ruta anterior: dos eventos encolados preparan dos formularios, un error de consulta escapa del manejador y el panel no conserva el comportamiento de desconexión/cierre previsto. Son pruebas del callback registrado, **no evidencia de una doble factura realizada en el navegador**. [Resultado previo](evidence/stay-panel-red-js-tests.log).

La primera corrección pasó 228 JS. El recorrido real confirmó bloqueo, recuperación, revisión/cancelación y validación local, pero la captura 375 mostró que el aviso de preparación quedaba oculto al cerrar el panel. Se añadió un aviso temporal fuera de esa ventana, visible dentro del área de pantalla y con `role=status`. Desaparece al terminar o fallar; no toma el foco ni recibe clics. La nueva regresión cubre ambos desenlaces. **229 JS aprobadas: 226 Desk y tres portal**, sin omisiones. [Batería final](evidence/stay-panel-js-tests.log), [compilación](evidence/stay-panel-build.log).

## Recorrido real y límites de la evidencia

Se usa Gerencia en escritorio, en el sitio de aceptación nativo. Una estancia H101 y su cargo de C$ 1,500.00 se preparan mediante la API nativa: no se atribuye su creación a las Pages. Un envoltorio privado demora ocho segundos una lectura de estancia y provoca un 503 en otra, una vez por escenario; no altera HTML, respuestas de comandos ni archivos de Frappe/ERPNext.

- Preparación: la Page bloquea sus acciones, abre un solo formulario y recupera los controles. En la repetición final, el aviso permanece visible al cerrarse el panel. [Captura 379](evidence/379-estancia-preparacion-visible.jpg).
- Error y reintento: aparece un solo aviso de acción no completada. Cerrarlo permite reabrir el panel y preparar de nuevo la factura; el aviso temporal se retira también ante el error.
- Revisión: se muestra la cuenta, el pagador, la fecha contable y C$ 1,500.00. Se cancela sin pulsar Emitir factura y se conserva la cuenta seleccionada. [Captura 376 del primer escenario](evidence/376-estancia-revisar-sin-emitir.jpg).
- Extensión: abrirla inmediatamente desde el panel no deja una capa anterior; enviar campos vacíos señala Nueva salida y Cuenta, conserva el formulario y enfoca el primer campo. Cancelar deja la Page accesible, sin ventana ni fondo residual. [Captura 377 del primer escenario](evidence/377-estancia-validacion-local.jpg).

El primer escenario y la repetición final se distinguen en [stay-panel-browser.json](evidence/stay-panel-browser.json) y [stay-panel-final-browser.json](evidence/stay-panel-final-browser.json). La repetición cubre preparación visible, error, reintento, revisión/cancelación y validación; no se presenta la primera compilación como si fuese la final. La captura 375 solo muestra controles bloqueados; no acredita un aviso visible. La captura 378 documenta el panel anterior a la mejora del aviso. No hay una nueva revisión móvil en esta fase.

Las inspecciones de cada escenario acreditan **72 tablas protegidas idénticas al fixture, 741 archivos idénticos y cero comandos financieros desde la UI**. La traza acumulada final contiene las dos demoras y los dos 503 deliberados, ningún 500. Ambos escenarios terminan con salida de sesión y restauración nativa de base/archivos; se conserva el primer recibo antes de la segunda restauración. Principal conserva 72 tablas/1,246 filas, dos archivos privados y fecha operativa 19/10. La prueba nativa de **407 casos de fbb4ce7** se reutiliza como antecedente con todas las fuentes Python idénticas; no se afirma otra ejecución nativa completa. [Verificación](evidence/stay-panel-verification.json).

## Cierre de S04-16

Se contrasta el texto completo «Estado vacío, carga, error, éxito, validación junto al campo y prevención de doble envío» con el contrato compartido y su evidencia acumulada:

| Estado | Evidencia revisada |
|---|---|
| Vacío | [Selectores/reserva manual](SELECTORES_Y_RESERVA_MANUAL.md): distingue borradores de reservas confirmadas. [Tesorería/compras](TESORERIA_Y_COMPRAS_DESDE_PAGES.md): liquidaciones, compras por facturar y proveedores sin saldo; no se abre un formulario inutilizable. |
| Carga | [Actividad/recuperación](ACTIVIDAD_Y_RECUPERACION_PAGES.md): carga, guardado y preparación, controles, respuestas antiguas y aviso móvil. Esta fase completa la preparación desde el panel con aviso visible. |
| Error | Actividad/recuperación: reintento de actualización. Tesorería/compras: límite rechazado y corrección conservada. Esta fase: error de preparación y reintento deliberado. |
| Éxito | [Aceptación por roles](ACEPTACION_Y_DEMOSTRACION.md) y tesorería/compras: resultado confirmado por servidor, documentos y saldos reales. Esta fase no genera operaciones financieras. |
| Validación junto al campo | [Formularios](VALIDACION_FORMULARIOS.md), [validación numérica](VALIDACION_NUMERICA.md) y [tareas por rol](TAREAS_Y_ESTADOS_POR_ROL.md): campos/filas, fechas, tipos, cero, borradores, valor original y foco. Esta fase repite la obligación local en extensión. |
| Prevención de doble envío | Contrato de formularios, idempotencia nativa y coordinador de Page. Se añade la ruta antes omitida del panel y cuatro regresiones; [ventanas/evidencias](VENTANAS_Y_EVIDENCIAS_PRIVADAS.md) acredita la causa y corrección de la transición anterior. |

S04-16 pasa a V. Esto acredita los estados compartidos y los casos delimitados, no 84 recorridos gráficos ni todas las ramas de negocio. **213 V y cinco I**, de las mismas 218 entradas. S04-20 conserva ropa de cama, políticas/otros adjuntos, retención/reintento y conversión del portal. S00-01/S01-12/S19-07/S19-08 dependen de terminar esos recorridos, F26, el paquete actualizado y la entrega. OTA permanece aplazada por instrucción del usuario.
