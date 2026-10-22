# Tareas operativas y estados por rol

Complemento posterior: [TESORERIA_Y_COMPRAS_DESDE_PAGES.md](TESORERIA_Y_COMPRAS_DESDE_PAGES.md) aporta el recorrido T11/T19 con tres roles, 407 nativas/225 JS y corrección del conteo de Gerencia. 212 V/seis I; la evidencia siguiente conserva su alcance histórico.

Complemento posterior: [VENTANAS_Y_EVIDENCIAS_PRIVADAS.md](VENTANAS_Y_EVIDENCIAS_PRIVADAS.md) resuelve la observación de clic inmediato que se registra abajo y revisa adjuntos privados con técnico/Supervisión. 405 nativas y 222 JS actuales; 212 V/seis I, sin cierre general de aceptación secundaria. El texto siguiente documenta la fase anterior y sus 404 nativas históricas.

Revisión del 21/10/2026 sobre 0.8.8, después de `ad1f701`. Se acreditan **S00-02 y S04-14**: las tareas habituales de recepción, caja, limpieza, mantenimiento y gerencia disponen de Pages y acciones propias, sin exigir formularios técnicos de ERPNext. **212 V y seis I**, conservando las 218 entradas y su fuente. La aceptación visual de todas las variantes secundarias, los estados restantes y F26 continúan abiertos; esta revisión no declara completa la aplicación.

## Colección finita de tareas

[task-state-crosswalk.json](evidence/task-state-crosswalk.json) agrupa los **84 manejadores en 22 familias**, una sola vez cada uno, y relaciona roles, implementación y evidencia. [El inventario actual](evidence/task-state-actions.json) conserva treinta fuentes, once Pages, nueve roles, 97 apariciones de botones y dos grupos de acciones calculadas resueltos. Son comprobaciones de estructura; **84 manejadores no equivalen a 84 recorridos de navegador**.

| Tareas | Evidencia y alcance |
|---|---|
| Recepción: huésped, disponibilidad, reserva, entrada, consumos, extensión, cuenta y salida | [Aceptación operativa](ACEPTACION_Y_DEMOSTRACION.md), [teclado y nueve roles](TECLADO_Y_FOCO.md), [selectores y reserva](SELECTORES_Y_RESERVA_MANUAL.md), [historial](HISTORIAL_HABITACIONES.md). Los documentos distinguen operaciones de Page y fixtures API. |
| Caja: apertura, cobro, vuelto, denominaciones y arqueo | Aceptación y teclado; facturación y devoluciones en sus [auditorías](AUDITORIA_DEVOLUCIONES.md) y [emisión desde Pages](FACTURACION_DESDE_PAGES.md). |
| Limpieza y Supervisión: iniciar, checklist, solicitar inspección, devolver y liberar | [Auditoría de limpieza/mantenimiento](AUDITORIA_LIMPIEZA_MANTENIMIENTO.md) y teclado; incluye usuarios separados y móvil histórico. |
| Mantenimiento: orden, inicio, repuestos, devolución autorizada y reapertura | Nuevo recorrido real descrito abajo, con tres usuarios separados e inspecciones de base de solo lectura. |
| Gerencia, Contabilidad y Auditoría: producción, conciliación, cierre e historial | Aceptación, teclado, [bitácora y cierres](BITACORA_Y_CIERRES.md) y [pendientes del cierre](FECHA_Y_PENDIENTES_CIERRE.md). |
| Configuración y acciones secundarias | El contraste relaciona cada acción con su diálogo/panel y sus pruebas. Primer establecimiento, categoría y tarifa se guardaron desde Pages; los formularios extensos tienen grupos/pestañas por tarea. Las variantes secundarias aún pendientes de recorrido visual quedan expresas abajo. |
| Impresiones | [Nueve formatos desde Pages y cinco roles](IMPRESIONES_OPERATIVAS.md); sus documentos fueron fixtures API. No se atribuye al navegador su creación. |

La lectura de las fuentes operativas no encuentra navegación obligatoria a un formulario nativo ni creación con `frappe.new_doc`. El único `frappe.set_route` va a la Page de estancias; la navegación lateral y de pendientes enlaza Pages, y las impresiones/exportaciones abren sus entregables. Las referencias a documentos estándar permiten rastrear contabilidad. La batería nativa y las pruebas de interfaz se usan junto con los recorridos reales para acreditar el camino operativo; no se usa la presencia de un botón como prueba de una operación terminada.

## Nuevo recorrido real

[task-state-browser.json](evidence/task-state-browser.json) conserva las lecturas de DOM y sus límites. El sitio aislado se respaldó antes. Un fixture explícito creó **solo un artículo de prueba y una entrada inicial estándar de diez unidades a C$20**; las acciones de categoría, orden, salida/devolución de repuestos, novedad/resolución y reapertura se realizaron desde Pages.

1. **Gerencia** intentó capacidad `1e2` y `0x10`: ambas conservan el texto, muestran un aviso junto al campo y lo enfocan. Corregir a `1+1` guarda una única categoría con capacidad 2: [aviso](evidence/359-capacidad-sin-conversion.png), [base](evidence/task-state-scalar-database.json).
2. **Mantenimiento** encuentra un estado vacío claro. Un envío sin trabajo requerido muestra el error local. Crea H101 bloqueada hasta reapertura, se asigna, inicia el trabajo y no recibe la opción de completar/liberar. Su acceso directo a Configuración es rechazado por los permisos nativos.
3. La búsqueda de repuestos sin coincidencias muestra su vacío y admite otra búsqueda. La cantidad `0x10` se rechaza junto al campo; corregir a 2 registra una sola salida estándar. Existencias **10 → 8**, costo **C$40**: [base](evidence/task-state-issued-database.json).
4. La tabla aún mostraba el código del artículo: [estado anterior](evidence/360-mantenimiento-codigo-anterior.png). Se corrigió para reutilizar el nombre/alias del catálogo, escapado y conservando la referencia original: [resultado final](evidence/361-mantenimiento-repuesto-legible.png). El técnico no recibe la opción de devolución.
5. **Gerencia** abre Devolver desde Repuestos, recibe error local si omite el motivo y autoriza la devolución de las dos unidades. Existencias **8 → 10**, costo **C$0** y salida estándar anulada, con el bloqueo todavía activo: [base](evidence/task-state-returned-database.json).
6. El técnico registra un objeto encontrado; Gerencia documenta su entrega y lo resuelve. **Supervisión**, en otra sesión, completa la orden y libera el bloqueo: [resultado](evidence/362-mantenimiento-reapertura-autorizada.png). El [checkpoint final](evidence/task-state-completed-database.json) comprueba orden, asignación, inventario, documento anulado y actores de auditoría; H101 vuelve a ofrecer Reservar en la Page de Recepción. No se crea una reserva para comprobarlo.

Se cerraron las sesiones. Este recorrido es de escritorio y no incluye nuevas cargas de archivos ni impresiones. Los primeros pasos numéricos y la salida corrieron en `46PQW7RZ`; nombre legible, devolución, resolución y reapertura en `5IE6WQ4O`. No se presenta el primer tramo como repetido entero sobre el segundo bundle. El cambio entre ambos es únicamente la etiqueta del repuesto.

## Corrección numérica y pruebas

El evaluador de JavaScript y el control nativo no siempre coinciden: `Number('1e2')` da 100, pero el entero nativo de Frappe guarda 1. `Number` también admite literales de base distinta, como `0x10`, que los controles nativos no interpretan igual. La validación ahora comprueba la sintaxis decimal y, en enteros, que el parseo nativo conserve el valor aceptado. No bloquea expresiones ni formatos que el control sí interpreta correctamente.

- [Cinco pruebas con código nativo de Frappe](../tools/test_native_numeric_ui.cjs) leen evaluador, formato y controles de la instalación: fórmulas, signos, cero, separadores locales, decimales y redondeo válidos permanecen admitidos. `HOSPITALITY_FRAPPE_ROOT` permite indicar otra instalación para ejecutarlas. No son un navegador ni sustituyen la comprobación real anterior.
- [221 JS aprobadas](evidence/task-state-js-tests.log), sin omisiones, frente a 215 anteriores: cinco de compatibilidad nativa y una del nombre de repuesto escapado/referencia intacta. [Tres regresiones numéricas previas](evidence/task-state-native-numeric-red.log) y [la regresión del rótulo](evidence/task-state-part-label-red.log) fallaron antes de sus correcciones.
- [Un diagnóstico intermedio](evidence/task-state-js-fixture-diagnostic.log) conserva 219/220: una prueba suponía que un literal decimal muy grande sufría la misma truncación que la expresión `10**21`. El código nativo conserva ese literal; se corrigió el supuesto, manteniendo las aserciones de la expresión y exponentes que sí reproducen la diferencia.
- [Compilación final](evidence/task-state-build.log) aprobada. Las **404 nativas de `be67c92`** son evidencia histórica de la instalación independiente, sin nueva ejecución nativa completa: el contraste verifica que las fuentes Python actuales son idénticas. Solo cambian validación y presentación en dos archivos JavaScript.

## Conservación y pendientes concretos

[Restauración UX](evidence/task-state-review-ux-restored.json) y [comparación de ambos sitios](evidence/task-state-review-upgrade.json) deben coincidir exactamente con sus respaldos: aceptación **71 tablas/185 filas de negocio, 72/250 con Version**; principal **72/1246 y dos archivos privados**, sin alterar la fecha operativa 19/10. El [estado final](evidence/task-state-final-state.json) y la [verificación de la fase](evidence/task-state-verification.json) conservan salud, fuentes y límites.

Los seis requisitos abiertos son **S00-01, S01-12, S04-16, S04-20, S19-07 y S19-08**. El trabajo siguiente queda delimitado por la colección de tareas:

- S04-16: reglas específicas restantes, estados de vistas/búsquedas secundarias y secuencias rápidas de cierre/apertura. Se observó que Cerrar repuestos seguido inmediatamente de Registrar novedad no abrió la siguiente ventana; no había bloqueo ni botón deshabilitado al inspeccionar después. Un clic posterior la abrió. No se asigna una causa ni se presenta como resuelto; las salidas de sesión del recorrido sí funcionaron sin recarga.
- S04-20: completar variantes visuales secundarias de tesorería/egresos, compras y movimientos, ropa de cama, retención/reintento, conversión del portal y políticas/adjuntos no recorridos visualmente. El contraste de fuentes/pruebas de esas familias acredita sus acciones propias, pero no inventa una ejecución GUI de todas sus variantes.
- S19-07/S19-08: F26, con actualización y recuperación coordinadas de **código, base y archivos**, paquete final y revisión de entrega. El paquete e instalación de `3a8d0bf` son antecedentes; aún no incluyen estos dos cambios de interfaz.

S00-01/S01-12 permanecen abiertos hasta cerrar lo anterior. La sincronización OTA continúa aplazada por instrucción del usuario; no se conecta un proveedor real.
