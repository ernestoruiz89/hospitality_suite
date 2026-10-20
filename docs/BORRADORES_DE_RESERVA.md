# Borradores de reserva — 0.6.4

Una solicitud incompleta puede guardarse desde Reservas, sin cliente, fechas ni categoría definidos. «Guardar borrador» no reserva cupo, fija precio, inicia retención ni produce cargos. La lista separa «Borradores por completar» de las reservas vigentes y muestra «Por definir» y «Sin cotizar», conservando los identificadores internos para las operaciones.

El editor organiza Fechas y pagador, Habitaciones y Opciones en tres pestañas. El huésped principal puede seleccionarse más tarde; para confirmar se necesita pagador, intervalo válido y al menos una solicitud con categoría y personas. Habitación física y tarifa preferida son opcionales. El calendario aparece después de las acciones y las listas. «Gestionar reserva» muestra datos de ingreso solamente para registrar entrada y exige motivo al cancelar o marcar no presentada.

Al retomar, se conservan los datos parciales y la versión del registro. «Revisar precio» vuelve a consultar disponibilidad y tarifario. La aceptación confirma el mismo registro o inicia su retención temporal. Una tarifa modificada, conflicto de cupo o versión obsoleta impide confirmar con una revisión anterior. Las fechas con desplazamiento explícito conservan la elección de hora ambigua mientras el usuario no cambie la hora mostrada.

Un fallo de red conserva la clave y el contenido de la solicitud de guardado. El siguiente intento resuelve primero esa solicitud; si se editaron los campos, guarda después esos cambios sobre el ID recuperado. Un rechazo de negocio permite corregir los datos. No se hace una segunda reserva con un nuevo identificador al recuperar una respuesta perdida.

Descartar exige un motivo y conserva el registro y su auditoría. Un borrador descartado no genera factura ni penalización y no se cuenta como cancelación de una reserva aceptada. No se permite usar un borrador como origen de documentos financieros, registrar su entrada, modificarlo por el flujo de reservas confirmadas ni saltar directamente de estado.

El campo JSON oculto contiene solamente modalidad, opción de retención y solicitudes parciales; referencias personales, notas y fechas usan sus campos nativos. La auditoría de guardado enumera campos cambiados; el historial nativo conserva las modificaciones de datos. Se mantienen los controles por establecimiento, rol, versión y transacción.

La batería completa aprueba **255 casos nativos** (241 de integración y 14 puros) y **56 JS** (54 Desk y dos portal). Los doce casos nuevos de servidor cubren parcialidad, idempotencia, versiones/historial, revisión sin escritura, tarifa modificada, conflicto de disponibilidad, retención, rechazo de atajos de estado, descarte, veto financiero, permisos y horas DST. Los siete nuevos de JS cubren reintento perdido con ediciones, corrección tras rechazo, fechas ambiguas, formularios y tarjetas.

Recepción guardó desde Page una solicitud sin pagador/fechas, cerró, recargó, retomó, completó y aceptó C$ 1,500.00. La inspección nativa verificó cero asignaciones antes y una después, sobre el mismo registro. Se descartó otra solicitud parcial con motivo desde móvil. Las tablas de estancias y finanzas conservaron sus filas/huellas, incluidos los dos GL Entry y un Stock Ledger Entry preexistentes. El recorrido no usó fixture API. Capturas JPEG nativos 122–127 y drafts-browser.json/items-ui.json conservan la evidencia.

En viewport 390×844, el primer paso cabe con ambas acciones visibles: modal de 374 px, cuerpo de 372 sin desborde horizontal, botón principal de 342×44. Guardar borrador mide 133×40. El recorrido confirma el formulario y el descarte móvil; la confirmación completa se ejecutó en escritorio. La aceptación general de todos los flujos/roles sigue abierta.

Después del recorrido se cerraron sesión/pestaña, se restableció el viewport y se detuvo 8089. El respaldo con archivos se restauró y migró a 0.6.4: 71 tablas/185 filas idénticas incluidas las columnas nuevas, 72/195 con Version. Principal: 72/1191 y dos archivos privados sin cambios, fecha operativa 19/10; el campo nuevo no contiene datos retroactivos. Núcleos limpios y servicios principales activos. No sustituye la recuperación final de F26.

S06-03 pasa P→V: matriz **131 V, 18 I, 1 P y 68 R**, mismas 218 entradas y huella del TXT. Continúa S07-09 (explicación histórica al revisar la cuenta). La integración con canales externos sigue aplazada por indicación del usuario.
