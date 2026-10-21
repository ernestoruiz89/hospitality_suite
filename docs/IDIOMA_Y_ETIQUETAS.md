# Idioma y etiquetas operativas

Fase 0.8.1. Revisión de S01-04: interfaz en español y preparación para traducciones. S01-04 pasa de I a V tras las pruebas, lectura en navegador y conservación de los sitios. La matriz queda en 189 V, siete I y 22 R: 29 entradas sin cierre.

## Cambios

Los 35 DocTypes usan etiquetas explícitas en español. Se sustituyen 310 etiquetas generadas desde nombres técnicos; el catálogo cubre los 239 nombres de campo únicos del esquema. La comparación con affdbf1 excluye únicamente `label`: tipos, nombres de campo, opciones persistidas, valores predeterminados, permisos, series y demás metadatos permanecen iguales.

Los estados conservan sus códigos. Las 129 traducciones contextuales incluyen las opciones HS y el uso operativo de Stock Entry. Por ejemplo, `Active` se presenta como «Alojado» en Estancias y «Activa» en Asignaciones, sin alterar el contexto de Account. Los cinco enlaces de alojamiento en los once documentos nativos enlazados tienen etiquetas comprensibles y conservan sus destinos.

El artículo demostrativo original de hora adicional se presenta como «Hora adicional por tiempo» en el catálogo operativo. Su código y nombre maestro permanecen intactos. El alias solo se aplica a la combinación exacta del artículo generado y su nombre original; otro artículo con esas palabras o un nombre modificado por el usuario permanece literal. La búsqueda encuentra también el alias visible y mantiene los filtros de uso y permisos.

Las etiquetas secundarias de diálogos, listas de revisión, devoluciones, valores faltantes, títulos del portal y orden de mantenimiento usan llamadas de traducción reconocibles por Frappe. Se conservan la identidad del usuario, nombres comerciales, nombres introducidos por el usuario, referencias y textos históricos. El PDF de cuenta mantiene su resumen breve.

## Contraste de fuentes

| Superficie | Criterio revisado |
| --- | --- |
| 27 módulos Desk y un módulo de portal | Etiquetas, acciones, valores faltantes y prefijos visibles; separación de códigos/API, estados, CSS, rutas, tipos de controles, marcas y datos del usuario. |
| Nueve plantillas de impresión y dos de portal | Textos estáticos mediante `_`, estados mediante presentadores; parseo de todas las plantillas y extracción nativa. |
| 35 DocTypes y once puentes nativos | Etiquetas españolas y opciones contextuales; comparación estructural y lectura de metadatos instalados. |
| Mensajes Python | Revisión de `throw`/`msgprint`; el argumento dinámico restante de disponibilidad se construye desde un mensaje traducido. Los errores internos de contexto se capturan y muestran el mensaje operativo traducido. |
| Reportes y cierre | «Auditoría», «Disponibilidad», «Conciliación» y el tipo de pendiente se mantienen como identificadores. Se traducen los títulos visibles, sin enviar títulos traducidos a los métodos de consulta. |

El inventario de fuentes conserva las huellas de la versión revisada. La comprobación estructural de 28 fuentes JavaScript preserva sus literales previos de protocolo; no sustituye las pruebas de comportamiento. Las pruebas con traducciones distintas del español verifican selección de filtros, apertura del detalle de auditoría y ruta de conciliación, además de etiquetas y datos maestros.

## Diagnósticos conservados

La primera batería general encontró dos expectativas antiguas de proyección del catálogo. Se incorpora `display_name` a la lista permitida; los campos económicos siguen excluidos. La segunda, ejecutada después de medianoche, encontró dos dependencias horarias de las pruebas existentes: diez minutos de anticipación añadían una tercera fecha a dos noches y el corte de las 06:00 incluía una salida de mañana a las 00:xx. Las pruebas hacen explícita la duración de dos noches y el corte de calendario del escenario contable. No se modifica el reloj ni la fecha operativa de los establecimientos.

El contraste de sintaxis detectó y corrigió una sangría en el mensaje traducido de un parche antiguo. La comprobación de protocolo detectó tres comparaciones y una llamada de reporte envueltas por error; se restituyeron sus valores y se añadieron regresiones con traducción no idéntica. Los diagnósticos originales permanecen en `.local/language-review/`.

## Alcance

Preparar traducciones significa que las etiquetas pasan por el mecanismo nativo y que cambiar una traducción conserva los valores de negocio. No se entrega un paquete completo de francés u otro idioma. Los registros nativos Translation utilizados en pruebas se revierten. La validación general de todos los formularios, teclado y tareas secundarias continúa en S04-16/S04-17/S04-20. La sincronización OTA sigue aplazada.

## Conservación y trazabilidad de la migración

Actualizar las etiquetas de Custom Field genera 55 registros Version nativos en cada sitio. No se eliminan para hacer coincidir el recuento anterior: el verificador acredita que cada registro añadido contiene exclusivamente el cambio de la etiqueta esperada y que todas las Version anteriores conservan su huella. Las tablas de negocio, documentos contables e inventario conservan sus filas previas. El total que incluye Version pasa de 1191 a 1246 en principal y de 195 a 250 en aceptación; las 71 tablas de negocio de aceptación permanecen en 185 filas.

A las 00:00 del 21/10, el trabajo nativo `cache_companies_monthly_sales_history` actualizó únicamente `Company.modified` respecto al respaldo de esta fase. Los dos historiales calculados conservan sus valores. La evidencia contrasta el respaldo original de la fase, la fila actual, el trabajo completado y las funciones nativas de lectura. La comparación con el origen histórico de contabilidad usa la atestación anterior conservada y su huella, porque no se encontró un SQL disponible cuya fila coincidiera con aquel origen; no se afirma haber reconstruido nuevamente esa fila. No se modifica ningún libro mayor ni la huella histórica.

La restauración de aceptación vuelve al respaldo inicial con archivos y se ejecuta la migración actual para recuperar las etiquetas, en lugar de dejar metadatos antiguos bajo código nuevo. El verificador acepta únicamente las 55 entradas nuevas de metadatos demostradas y la actualización de caché descrita, manteniendo el contraste estricto del resto.

## Evidencias finales

- [379 pruebas nativas](evidence/language-review-native-tests.xml): 365 de integración y catorce puras; seis nuevas. Incluyen metadatos, contextos y traducciones nativas revertidas.
- [142 pruebas JS](evidence/language-review-js-tests.log): 140 Desk y dos del portal; seis nuevas. Incluyen alias, escape de nombres y rutas/filtros con traducciones no idénticas.
- [Metadatos comparados con affdbf1](evidence/language-review-metadata.json), [446 campos y 55 enlaces verificados en ambos sitios](evidence/language-review-installed.json), [extracción nativa](evidence/language-review-extraction.json), [protocolo conservado en 28 fuentes JS](evidence/language-review-wire-invariants.json).
- [Lectura real de Gerencia](evidence/language-review-items-ui.json): búsqueda, consulta de precio y dos secciones de mantenimiento. Capturas [catálogo](evidence/243-catalogo-nombre-por-tiempo.jpg), [orden](evidence/244-mantenimiento-etiquetas-espanol.jpg) y [plazos móvil](evidence/245-mantenimiento-plazos-movil.jpg). Se cerraron los formularios sin guardar. Vista móvil 390×844, botón 342×44 y ancho de página de 390.
- [Respaldo y comparación](evidence/language-review-upgrade.json), [aceptación restaurada](evidence/language-review-ux-restored.json), [caché de Company](evidence/language-review-company-cache.json) y [estado final](evidence/language-review-final-state.json). Se migró después de restaurar y se volvieron a comprobar las etiquetas actuales en ambos sitios.

Los núcleos permanecen limpios; el inventario conserva 35 DocTypes, once Pages, nueve roles, 25 DocTypes nativos utilizados y dos assets. La fecha principal sigue en 19/10/2026 y sus dos archivos privados conservan su huella. El PDF breve mantiene el SHA-256 `e1accf8743960381bd560aa4d1af99574599e2daf39d72adc04139252836e15a` en ambos sitios. El servidor temporal está apagado y la sesión de navegador terminó.
