# Ropa de cama y políticas desde las Pages

Recorrido posterior a `d54bc45`, sobre 0.8.8, con Gerencia, Limpieza y Caja en sesiones separadas. Aporta aceptación secundaria de T14/T18 a S04-20 y corrige una política que podía guardarse aunque después impidiera cancelar reservas. No completa la aceptación secundaria ni F26: **213 V y cinco I** de las mismas 218 entradas.

## Defecto de penalización y corrección

Antes de la corrección, Gerencia guardó **125 %** como penalización de cancelación desde Horarios y penalizaciones. La [inspección nativa](evidence/secondary-flows-policy-after-percent.json) confirma el valor persistido; el motor de cancelación ya exigía entre 0 y 100. El servidor ahora aplica esa misma regla al guardar el establecimiento, para cancelación y no presentación. También rechaza importes negativos o no finitos. No modifica facturas, reservas ni sus cotizaciones históricas.

El formulario indica el error junto al importe, conserva 125 y enfoca ese campo. Cambiar el tipo a **importe fijo** permite guardar C$125: la regla de porcentaje no limita un importe monetario válido. Una penalización fija de no presentación de −1 se rechaza junto a su propio campo; corregirla permite guardar. La configuración final del escenario es cancelación **25.5 %** y no presentación **C$50**, con las horas originales 14:00/12:00 conservadas. [Captura 380](evidence/380-penalizacion-validacion-local.jpg).

La [regresión JS previa](evidence/secondary-flows-policy-red-js-tests.log) falla con el validador anterior. Pasan **230 JS**: 227 Desk y tres portal, sin omisiones. La nueva regresión diferencia porcentaje, importe fijo, fracción, extremos y borrador parcial. Dos pruebas nativas nuevas recorren ambas políticas: rechazos sin modificar establecimiento/versión/solicitud; cero, 25.5, 100 y cantidades fijas válidas. La batería completa ejecuta **409 pruebas nativas: 377 de integración y 32 unitarias**, sin errores ni omisiones. [Resultado nativo](evidence/secondary-flows-native-tests.xml), [resultado JS](evidence/secondary-flows-js-tests.log).

## Ropa de cama

El fixture API crea solamente un artículo sintético, una ubicación de reserva y una entrada estándar: diez sábanas en el almacén operativo y cinco en reserva, a C$25 por unidad. No crea lavandería, clasificación, movimientos de ropa ni políticas. El primer inspector confundió campos de reorden del artículo estándar con campos de HS Stock Policy; se corrigió la consulta y se leyó el mismo fixture ya creado, sin repetir su creación.

**Gerencia** crea Lavandería de aceptación operativa desde Consumos e inventario, la selecciona en Políticas y contabilidad y clasifica el artículo como Ropa de cama, mínimo diez/reposición cinco. ERPNext presenta su aviso de reordenamiento automático desactivado; se cierra el aviso sin activar esa automatización. La alerta de reposición de la Page sí funciona con estos mínimos manuales.

**Limpieza** tiene acceso a Ropa de cama y el acceso directo a Configuración es rechazado. Selecciona H101 y el nombre legible de la sábana. El intento con cantidad cero devuelve el aviso del servidor y conserva el formulario; existencias y documentos no cambian. Corregir a cuatro registra el envío. Recibe tres unidades. Una pérdida sin motivo se rechaza sin movimiento; documentar el motivo permite registrar la pérdida de una unidad. La Page conserva los tres registros de ropa con sus descripciones y estado resuelto.

| Paso desde las Pages | Operativo | Lavandería | Reserva |
|---|---:|---:|---:|
| Prerrequisito API | 10 | 0 | 5 |
| Enviar 4 — Limpieza | 6 | 4 | 5 |
| Recibir 3 — Limpieza | 9 | 1 | 5 |
| Pérdida documentada de 1 — Limpieza | 9 | 0 | 5 |
| Reponer 1 desde reserva — Gerencia | 10 | 0 | 4 |

La Page de inventario muestra la clasificación, mínimo y alerta cuando quedan nueve; después de reponer muestra diez y retira la alerta. Los movimientos usan Stock Entry y Stock Ledger Entry estándar: salidas/entradas de 4/3/1 y costo de pérdida **C$25**. Las tres operaciones de lavandería conservan Limpieza como propietario y actor; la reposición conserva Gerencia. Los asientos quedan balanceados. No se crean turnos, facturas ni pagos. [Checkpoint final](evidence/secondary-flows-completed-ui.json).

## Efecto de políticas en Caja

Gerencia desactiva nuevos anticipos y exige autorización para nuevas garantías desde Anticipos y garantías. En otra sesión, el formulario de Caja omite Anticipo, muestra Garantía · requiere gerencia deshabilitada y mantiene disponibles Devolución y Devolución de garantía. Se cierra el formulario sin turno ni movimiento de dinero. La evidencia complementa las pruebas nativas de autorización; no atribuye a este recorrido un cobro rechazado por el servidor.

## Alcance, evidencias y conservación

[secondary-flows-browser.json](evidence/secondary-flows-browser.json) distingue 26 observaciones de escritorio y sus compilaciones. El nombre inicial de una observación anticipaba un rechazo del 125 %; la inspección demostró que se había guardado, y el rótulo se corrigió dejando constancia de ello. Las lecturas de base son de solo consulta. Las capturas 381/382 conservan vistas parciales de las Pages; los números anteriores se acreditan mediante el DOM registrado y los checkpoints, no mediante una tabla completa visible en esas capturas. La captura 380 sí acredita el error junto al campo y su foco. No hay nueva prueba móvil ni carga de archivos en este tramo. Los intentos de edición del control horario por la herramienta no cambiaron las horas y no se presentan como una edición horaria comprobada.

El escenario se restaura antes de las pruebas nativas y se conserva ese primer recibo. Tras la batería, se restaura de nuevo la base y los archivos. Los archivos nuevos de las pruebas se conservan fuera del sitio; los **741 archivos originales** quedan idénticos, incluidos los huérfanos anteriores. Aceptación vuelve a 71 tablas/185 filas de negocio, 72/250 con Version; principal conserva 72/1,246, dos archivos privados y fecha operativa 19/10. No cambian esquemas ni núcleos Frappe/ERPNext. Web y worker se reinician para cargar la validación Python. [Verificación de fase](evidence/secondary-flows-verification.json).

S04-16 conserva V con la validación adicional acreditada. S04-20 conserva pendientes retención/reintento, otros adjuntos privados y conversión del portal; las otras acciones y roles conservan su evidencia anterior, sin atribuirles una nueva ejecución en este tramo. Después corresponden F26, paquete actualizado y entrega S19-07/S19-08, junto con los cierres generales S00-01/S01-12. La sincronización OTA sigue aplazada por el usuario.
