# Valores numéricos sin conversiones silenciosas

Revisión del 21/10/2026 sobre 0.8.8, después de `3069b8a`. Se mantiene la versión y el backend; cambia la validación de las Pages. El defecto se reproduce en aceptación: una categoría nueva con capacidad escrita **1.5** termina guardada con **1**, sin aviso. La corrección revisa el borrador original antes del parseo nativo, aunque el campo no declare un mínimo. Los enteros rechazan fracciones y los campos numéricos rechazan valores no finitos o no interpretables mediante el evaluador nativo. Se conservan los signos, cero, decimales en campos decimales, expresiones y formato numérico nativo; no se añade una regla general de importes positivos.

Las tablas comprueban también las columnas opcionales y el borrador del editor expandido. Un error conserva el valor escrito como dato local, identifica fila/campo y enfoca el aviso o el control visible. Al reabrir una fila se recupera el valor original. Los borradores incompletos siguen admitidos: omiten las obligaciones y límites de dominio de la confirmación, pero no convierten una fracción en una persona entera.

## Pruebas ejecutadas

**215 pruebas JS aprobadas, sin omisiones**, cinco nuevas: [salida completa](evidence/numeric-review-js-tests.log). Cubren tipos sin límites explícitos, columnas opcionales, editor expandido/colapsado, independencia entre tablas y guardado parcial; se conserva la prueba de signos, cero y evaluador nativo. Las tres primeras regresiones fallaron antes de la corrección: [resultado previo](evidence/numeric-review-red-tests.log). Los nombres de campos/RPC/acciones existentes se conservan en treinta fuentes: [contraste](evidence/numeric-review-wire-invariants.json).

La [lectura real del navegador](evidence/numeric-review-browser.json) delimita los casos de Gerencia y Recepción en aceptación:

- Capacidad 1.5 queda visible, con «Indique un número entero» y foco en el campo. Corregir a 2 permite guardar: [captura](evidence/352-capacidad-entera-validacion.png), [lectura de base](evidence/numeric-review-scalar-database.json).
- Personas 1.5, tras volver a la tabla, bloquea Guardar borrador y Revisar precio; el aviso identifica la fila/campo. Reabrir recupera 1.5. Camas adicionales 2abc también se rechaza y recupera al reabrir: [aviso](evidence/353-fila-personas-validacion.png), [cero reservas tras los intentos](evidence/numeric-review-grid-blocked-database.json).
- Con dos personas y cero camas se guarda un único borrador y se retoma con dos personas: [captura](evidence/354-borrador-cantidades-corregidas.png), [lectura del borrador](evidence/numeric-review-grid-saved-database.json). El cero opcional se muestra vacío mediante el control nativo, pero queda guardado como 0. El borrador conserva sus filas en `draft_data`, sin hijos de reserva/asignaciones; el primer chequeo de evidencia asumió hijos y se corrigió tras revisar esa estructura.

El editor expandido nativo cubre los botones del pie. Los primeros intentos de activarlos con ese editor abierto no enviaron la acción: no se cuentan como prueba de validación. La prueba efectiva acepta la categoría con el teclado, vuelve a la tabla y activa los botones. No se atribuye a esta fase aceptación completa por rol, Caja, móvil, impresión ni todas las reglas de dominio.

La consulta principal de solo lectura vuelve a comprobar el ajuste solicitado: nueve tarjetas verdes con «Disponible», H105 roja con «No disponible / Ocupada», sin repetir «en el intervalo». Las fechas aparecen una vez en el resumen: [captura actual](evidence/355-disponibilidad-sin-repeticion.png), [estados y colores](evidence/numeric-review-availability.json). Se devuelve el filtro de establecimiento anterior y se cierra la pestaña auxiliar. Compilación comprobada `OTTQHYJ4`; no se guarda una reserva en el principal.

## Conservación y alcance pendiente

Aceptación se respalda antes, se detiene 8089, se restaura y se migra: [migración](evidence/numeric-review-acceptance-restored.json), [restauración estricta](evidence/numeric-review-ux-restored.json). Ambos sitios conservan sus datos/archivos anteriores: [comparación](evidence/numeric-review-upgrade.json), [servicios y estado final](evidence/numeric-review-final-state.json). La [verificación de la fase](evidence/numeric-review-verification.json) contrasta las fuentes, pruebas y observaciones; las 404 nativas de `fb8c022` siguen siendo evidencia histórica del backend sin cambios, sin afirmar otra ejecución nativa completa.

La matriz mantiene **208 V y diez I**, las mismas 218 entradas y su huella. Se añade evidencia a S04-16 sin dar por revisadas todas las tareas/estados. Continúan la aceptación transversal, paquete/instalación y recuperación final F26. La sincronización OTA sigue aplazada; el objetivo permanece activo.
