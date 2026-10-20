# Contraste de Pages, UX y habitaciones

Revisión del 20/10/2026 sobre aplicación 0.6.1, commit `3563ef0`. Se contrastan las **27 entradas de las secciones 4 y 5** del documento original contra código, aserciones y evidencia ya conservada. No se ejecuta otra batería ni se realizan nuevos recorridos de navegador en esta revisión documental. Las pruebas vigentes siguen siendo 220 de backend y 41 regresiones JavaScript.

En este bloque, **16 entradas pasan a V, nueve a I y dos a P**. El inventario original conserva texto, líneas, huella y sus 218 entradas: **99 V, diecisiete I, dos P y 100 R**. Estos recuentos representan aceptación documentada, no porcentaje de programación. `evidence/pages-rooms-audit.json` identifica casos aprobados del JUnit actual, referencias, huellas del código y las dos reproducciones estáticas.

## Pages acreditadas y sus límites

Recepción ofrece tablero, panel lateral de estancia y cuenta; Reservas añade calendario por habitación y búsqueda de disponibilidad con el mismo motor de cupos. La prueba de calendario conserva 610 asignaciones y la de disponibilidad respeta demanda sin habitación. Los recorridos grupales y de hotel acreditan operación desde Pages. El calendario ordinario no constituye por sí solo un historial completo de todos los cambios.

Caja conserva evidencia de cobro, devolución, turno, arqueo y cierre. Limpieza tiene inicio, checklist, prioridades, responsables y aprobación separada por supervisión, incluido móvil. Mantenimiento registra incidencias, equipo, bloqueos, repuestos y evidencia privada; completar una orden libera su bloqueo. Consumos entrega una vez y utiliza inventario estándar para reposición, traslado y reversión. Clientes y huéspedes consulta historial de principal/acompañante y rechaza otra propiedad. Gerencia y Configuración disponen de reportes, autorizaciones y asistente con validación del servidor. La matriz individual enlaza cada obligación con sus implementaciones y comprobantes.

El diseño adaptable conserva evidencia de escritorio, tableta 1024×768 y móvil 390×844, con limpieza móvil y los formularios por pestañas de 0.5.2. Las acciones expresan verbos operativos y los estados tienen texto además de color. Se acredita el transporte entre tres sesiones autorizadas/aisladas, publicación tras commit, reconexión y recuperación del cambio perdido. El bloqueo sin conexión, las confirmaciones dependientes de respuesta y la clave de reintento se contrastan con los ensayos de respuesta perdida y rollback. Nada de esto acredita automáticamente accesibilidad completa ni todos los flujos de todos los roles.

## Dos diferencias confirmadas

**S04-04: Estancias necesita llegadas, salidas y cuentas abiertas diferenciadas.** `render_stays` presenta una tabla general de habitación, huésped, salida prevista, estado y enlace a la cuenta. No existe otra extensión que sustituya ese renderizador. El usuario puede consultar reservas y reportes en otras Pages, pero eso no completa la tarea pedida en Estancias. Deben ofrecerse vistas breves con conteos, fecha clara, estado vacío y acción adecuada a cada caso; no una tabla larga que mezcle todo el historial.

**S05-01: falta entrada prevista o próxima llegada en las tarjetas de Recepción.** El código muestra salida prevista, tiempo restante/excedido, estado de ocupación/limpieza/bloqueo y saldo autorizado. No representa una llegada futura en la tarjeta. La corrección debe conservar las dimensiones separadas: una reserva futura no significa habitación ocupada. Mostrar fecha y contexto resulta más claro que añadir otro código de estado.

Las reproducciones estáticas comprueban el renderizador único de Estancias y la ausencia del campo de llegada en las tarjetas en esta revisión; no escriben bases ni simulan un recorrido. Estas diferencias son los siguientes cambios de interfaz. Las capturas 106–110 siguen acreditando el flujo de facturación resuelto y no se reinterpretan como prueba de estas vistas ausentes.

## Verificaciones parciales que siguen abiertas

- **S04-01:** Inicio muestra indicadores, conteos de limpieza/mantenimiento y accesos; completar revisión y aceptación de alertas accionables de llegadas/salidas. No se da por completo el requisito solo por los indicadores agregados.
- **S04-14/20:** ampliar la aceptación de tareas habituales por rol. Los recorridos existentes alternan roles; siguen abiertos el usuario combinado de recepción/caja y la sesión contable de S17-18.
- **S04-15:** ejecutar combinación/persistencia de búsqueda, piso, categoría y limpieza al recargar/cambiar de propiedad. El código guarda filtros por propiedad; una captura no prueba esa interacción.
- **S04-16:** completar validación junto al campo y estados asíncronos secundarios, incluido cambio rápido de fecha del calendario. Hay prueba de doble envío y recuperación de pestaña, pero no de todas las vistas secundarias.
- **S04-17:** completar recorrido solo con teclado y foco al abrir/cerrar paneles y revisiones. Controles nativos, ARIA, texto de estados y foco CSS son evidencia de implementación, no aceptación completa de accesibilidad.
- **S05-03:** revisar reservada para intervalo consultado y llegada/salida próxima con la corrección de tarjetas. Los nombres sugeridos de estados no se convierten en un único campo que mezcle ocupación, limpieza y mantenimiento.
- **S05-04:** probar explícitamente todo el historial por habitación/rango, con limpieza y reserva cancelada. Las 610 asignaciones, los segmentos de estancia y el bloqueo finalizado acreditan parte del alcance.
- **S05-07/S16-03:** probar el instante anterior y el extremo permitido del intervalo, con y sin colchón de limpieza. La implementación amplía extremos; no sustituye esa prueba exacta.

La salida que deja habitación sucia, el checklist obligatorio, la inspección por otro rol y la liberación final quedan V, así como el rechazo de habitaciones sucias, bloqueadas o deshabilitadas para entrada y la exclusión de ocupación simultánea. El motor y el esquema conservan por separado asignación/estancia, limpieza y mantenimiento. Las carreras reales siguen siendo la evidencia de concurrencia; no se repiten ni se atribuyen a un solo navegador.

## Continuidad

Corregir las dos diferencias de interfaz, completar las verificaciones específicas y continuar las 100 R de las demás secciones. El objetivo sigue activo; faltan también traducciones, reintentos de expiración, demo operativa, otras familias de contratos y recuperación de la revisión final. La sincronización con Airbnb, Booking y otros canales permanece pendiente por indicación del usuario. Esta revisión no modifica código de aplicación, bases, configuración ni servicios.
