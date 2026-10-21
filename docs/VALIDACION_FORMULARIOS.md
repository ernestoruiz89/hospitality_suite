# Validación junto al campo — 0.8.3

Esta fase mejora el formulario compartido de las Pages. **S04-16 continúa I**: se acreditan los errores locales y las regresiones descritas aquí; no se declara revisado todo el conjunto de reglas de negocio, vistas y acciones secundarias. La matriz conserva **196 V, 6 I, 0 P y 16 R: 22 entradas sin cierre**.

## Comportamiento

Los campos obligatorios muestran una explicación junto al control, sin abrir otro diálogo. Las casillas obligatorias deben estar marcadas; los importes y conteos cero siguen siendo valores válidos cuando la regla de negocio los permite. No se exige completar controles ocultos por dependencia o de solo lectura. Los errores nativos del control y las fechas incompletas del navegador impiden continuar.

Las tablas indican fila y columna faltante bajo su propio control. La primera incidencia abre su pestaña y recibe foco; en una tabla sin editor abierto, el foco llega al mensaje. Los mensajes usan texto, conservan las ayudas y los atributos ARIA nativos y se retiran al corregir, sin desplazar el foco mientras se escribe. El estado de procesamiento pide esperar y el bloqueo de envío conserva una solicitud en curso. Guardar un borrador parcial mantiene su vía sin validación obligatoria.

La salida debe ser posterior al inicio; los rangos de reporte y vigencia pueden incluir el mismo día. Son comprobaciones locales previas: permisos, cupo, saldos y demás reglas siguen comprobándose en el servidor. No se interpretan cadenas arbitrarias del servidor como asociaciones entre campos.

La prueba móvil detectó que un cambio rápido de campo o pestaña podía borrar un nombre recién escrito antes del debounce de Frappe. El envoltorio del diálogo conserva también esos controles obligatorios con modelo todavía vacío, además del editor enfocado. No escribe el modelo ni reemplaza prototipos. Si el núcleo oculta, deshabilita, sustituye o asigna un valor nuevo al control, se conserva ese cambio nativo.

## Evidencia ejecutada

**183 pruebas JavaScript aprobadas**, 180 de Desk y tres del portal, nueve más que 0.8.2. Los casos nuevos comprueban campos/filas, cero, dependencias, formato nativo, intervalos, ayudas accesibles, corrección sin salto de foco, independencia de diálogos, envío concurrente/reintento/borrador y debounce del nombre. La batería nativa de **380 casos de 0.8.2** se conserva como antecedente; esta fase no cambia reglas Python ni presenta una segunda ejecución completa de esa batería.

El recorrido real usa dos sesiones separadas en aceptación:

1. Administración intenta guardar una categoría vacía: aparece «Complete Categoría», un solo diálogo y foco en Categoría. Corregir retira el mensaje. Un doble clic guarda una sola categoría Revisión de formularios, capacidad dos.
2. Desde Servicios incluidos de una tarifa, Guardar vuelve a Precio y muestra los tres campos faltantes. En móvil 390 × 844 se completa nombre, categoría y cero rápidamente; una fila sin artículo recibe su mensaje. Después de corregir el defecto de debounce se conservan el nombre y 0.00 al volver a Precio. Se cancela sin guardar la tarifa.
3. Disponibilidad rechaza localmente salida anterior a entrada y enfoca Salida prevista. Corregir permite consultar diez habitaciones, sin reservar. La cantidad cero sigue siendo rechazada por el servidor; esta observación no se presenta como validación local por campo.
4. Caja abre con fondo cero y cierra mediante una fila de denominación uno/cantidad cero. Turno cerrado, conteo y diferencia cero; no se registran cobros, facturas ni pagos.

La compilación inicial fue KP6BAQQX y la final TU7AFJT4. La categoría inicial se guardó con la primera; la regresión del nombre, fechas y caja se repitieron con la final. [secondary-forms-browser.json](evidence/secondary-forms-browser.json) conserva los estados realmente observados; [secondary-forms-items-ui.json](evidence/secondary-forms-items-ui.json) inspecciona los documentos sin escribir. Las imágenes 276 y 281 registran respectivamente el defecto anterior y una limitación abierta, no aceptación final de esos casos.

Capturas finales: [error de categoría](evidence/274-categoria-error-en-linea.jpg), [fila incompleta móvil](evidence/277-tarifa-fila-validacion-final-movil.jpg), [nombre y cero conservados](evidence/278-tarifa-cero-conservado-movil.jpg), [fechas](evidence/279-fechas-validacion-en-linea.jpg), [consulta corregida](evidence/280-disponibilidad-corregida.jpg) y [arqueo cero](evidence/282-arqueo-cero-conservado.jpg).

## Conservación y revisión restante

Se conservó un respaldo nuevo de fase antes de las acciones. El sitio sintético se restaura mediante Bench y se migra; la comparación comprueba sus 71 tablas/185 filas iniciales y, por separado, 72/250 incluyendo Version. La demostración conserva 72/1246, dos archivos privados y fecha 19/10. [secondary-forms-verification.json](evidence/secondary-forms-verification.json) vincula las comparaciones, compilación, fuentes y observaciones. Ambos sitios registran 0.8.3; principal responde HTTP 200 con web/Socket.IO/Redis activos y 8089 detenido. Núcleos limpios. La revisión histórica de las guías conserva sus documentos exactos en beac44d.

Queda revisar las reglas específicas por campo, incluidos límites numéricos, y las acciones/vistas secundarias del conjunto. Después de cerrar el arqueo, varios clics de salida no mostraron confirmación; recargar permitió cerrar sesión. La traza conserva esa incidencia para reproducir y resolver el contexto de acciones. No se presenta el turno correcto como prueba de que todos sus accesos posteriores funcionaron.

Continúan S00-02/S04-14/S04-20, las demás entradas abiertas y el ensayo final F26. La sincronización Airbnb/Booking permanece aplazada. La restauración de este escenario no es el ensayo de reversión de la versión final.
