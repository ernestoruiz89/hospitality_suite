# Revisión de teclado y foco — en curso, 0.8.2

S04-17 conserva el estado I. Esta fase añade comportamiento de teclado a las Pages y sus diálogos nativos; falta terminar el recorrido real por roles, incluidos tablas, revisiones anidadas y móvil. La revisión independiente de entregables acredita S18-04/S18-05: la matriz queda en 191 V, 7 I y 20 R. Este cambio de recuento no acredita la aceptación pendiente de teclado.

## Cambios implementados

- Los diálogos reciben nombre accesible, foco inicial y un ciclo de Tab/Mayús+Tab dentro de la ventana visible. Las revisiones de solo lectura empiezan en su título.
- Las pestañas usan un único punto de Tab, flechas, Inicio y Fin; el estado seleccionado y la visibilidad de los paneles se comunican con ARIA.
- Al cerrar, el foco vuelve al control de origen o a su reemplazo después de actualizar la Page. Un cambio de ruta impide restaurarlo en una página distinta. Los filtros conservan el cursor cuando la Page se vuelve a dibujar.
- Un error obligatorio abre la pestaña correspondiente y devuelve el foco al campo después de cerrar el aviso nativo. Una casilla obligatoria sin marcar se trata como incompleta; un importe numérico cero sigue siendo válido.
- Las celdas editables y selectores de filas tienen etiquetas. Enter/Espacio activa la edición nativa. El encabezado de tabla que Frappe utiliza para abrir o crear una fila sale del orden de Tab.
- En las tablas de estos diálogos, Tab conserva el desplazamiento nativo del navegador y la validación al salir del campo; se detiene el manejador de Frappe que añade otra fila al llegar al último editor. Añadir fila y los atajos explícitos conservan sus acciones.
- Las opciones de tabla con código/etiqueta muestran el texto visible también fuera del editor: Una vez por estancia y Por noche (hotel), conservando Stay/Night en los datos. Se utiliza texto, no HTML.
- Las tablas de resultados con desbordamiento horizontal reciben una región nombrada y accesible mediante teclado. Las acciones de edición agregadas se retiran si un campo o tabla pasa a solo lectura.
- El foco visible tiene un contorno propio dentro de la aplicación y sus diálogos.

La implementación utiliza el evento público `frappe.ui.Dialog:shown`, listeners del diálogo concreto y métodos propios de Desk. No reemplaza prototipos de Frappe. Las fuentes contrastadas son `ui/dialog.js`, `form/layout.js`, `form/grid_row.js` y `form/formatters.js` de Frappe 16.52.0 instalado.

La preparación de tablas comprueba que el diálogo esté registrado en el ámbito operativo. Una regresión específica verifica que enfocar una tabla de un diálogo nativo fuera de estas Pages no altere sus controles ni su navegación.

## Evidencia actual y límites

- [keyboard-review-before-ui.json](evidence/keyboard-review-before-ui.json): observaciones de la compilación anterior 282ce6b, sin acciones de negocio enviadas. Identifica las fallas de flechas, ciclo de foco y retorno al cerrar; no es la aceptación de la corrección.
- [keyboard-review-js-tests.log](evidence/keyboard-review-js-tests.log): 162 casos aprobados, incluidos 19 de teclado y uno adicional de formulario. El modelo de DOM de estas pruebas verifica las fronteras del código; no ejecuta un navegador real.
- [keyboard-review-native-tests.xml](evidence/keyboard-review-native-tests.xml) y su [salida de ejecución](evidence/keyboard-review-native-tests.log): 379 casos, 365 de integración y 14 puros, sin errores. Se ejecutaron antes del recorrido de categoría y antes de los últimos ajustes exclusivamente JavaScript de tablas.
- [keyboard-review-build.log](evidence/keyboard-review-build.log): compilación de los assets con los últimos cambios.
- [keyboard-review-wire-invariants.json](evidence/keyboard-review-wire-invariants.json): las 28 fuentes existentes conservan sus literales de protocolo respecto de 282ce6b; el módulo de teclado es una fuente nueva, sin comparación anterior.
- [keyboard-review-upgrade.json](evidence/keyboard-review-upgrade.json): comprobación anterior al recorrido, con 72 tablas/1246 filas en demostración y 72/250 en aceptación. No es una comprobación posterior a restauración.
- [keyboard-review-checkpoint.json](evidence/keyboard-review-checkpoint.json): lectura al retomar el trabajo, con principal 72/1246 y dos archivos privados intactos. Aceptación tiene 72/253, con una categoría, su solicitud idempotente y su auditoría como únicos cambios. No hay reservas, estancias, turnos ni documentos financieros nuevos. Las 36 tablas nativas de negocio y Version conservan su huella. Se reproduce con `tools/keyboard_review_ux.py checkpoint` antes de iniciar el recorrido financiero completo.

Los logs publicados normalizan finales de línea y espacios al final; las salidas originales permanecen en `.local/keyboard-review/`. No se modifican los resultados de los casos.

El recorrido preliminar guardó una categoría desde Configuración por un administrador HS y comprobó pestañas, recuperación del primer campo obligatorio y retorno de foco. En tarifas reveló filas añadidas por la navegación nativa. Ese recorrido utilizaba una compilación anterior a la corrección actual; la captura 246 es preliminar y no acredita su validación final. La traza de la sesión de navegador se perdió al reiniciarse el entorno y debe repetirse y exportarse.

Al continuar el 21/10/2026, WSL ya no tenía los servidores activos. Se levantaron mediante `run_dev.py` y el helper de esta fase. El navegador conservaba pestañas con página de error. Al intentar adquirir una de ellas, su política de seguridad rechazó el protocolo de la página de error. Se solicitó abrir la URL HTTP de aceptación desde el navegador integrado; no se intentaron otras superficies ni controles alternativos para acceder a la pestaña bloqueada.

## Pendiente de aceptación

1. Retomar con una página HTTP accesible y repetir el recorrido con la compilación actual, exportando foco, teclas y rol sin credenciales.
2. Completar las operaciones desde Pages con administración, recepción y caja separadas, limpieza, supervisión y mantenimiento; revisar también contabilidad, gerencia y auditoría. Verificar la navegación de las tablas sin insertar filas implícitas.
3. Contrastar etiquetas, estados con texto y navegación del portal y las vistas secundarias; revisar escritorio y móvil. Una muestra de diálogos no acredita todos los formularios.
4. Comparar los documentos nativos y la conciliación con las acciones realmente realizadas. El inspector preparado no debe acreditarse antes de completar su escenario.
5. Cerrar las sesiones, restaurar aceptación desde el respaldo de esta fase y verificar datos/archivos, servicios y fecha operativa antes de declarar terminada la fase. El servidor temporal 8089 está activo mientras se retoma la aceptación.

La sincronización con plataformas de reservas continúa aplazada por indicación del usuario.
