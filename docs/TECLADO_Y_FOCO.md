# Teclado, foco y etiquetas — 0.8.2

S04-17 queda acreditado con la revisión de las Pages operativas, sus diálogos y el portal. Pasaron **380 pruebas nativas y 174 JavaScript**; el recorrido real registra los nueve roles con usuarios separados, escritorio y móvil de 390 × 844. El objetivo completo sigue activo: las verificaciones generales de tareas secundarias, estados/validación de todos los formularios, contratos externos y recuperación final mantienen sus propias entradas abiertas.

## Comportamiento comprobado

- Los diálogos tienen nombre accesible, foco inicial y ciclo de Tab/Mayús+Tab. Una revisión sin campos empieza en su título. Las pestañas usan flechas, Inicio y Fin, con estado seleccionado y paneles comunicados mediante ARIA.
- Escape devuelve el foco al control de origen o a su reemplazo después de actualizar la Page. Cuando un reporte abre resultados y después cierra sus filtros, el resultado conserva el origen de la página. La construcción nativa que desenfoca sobre body utiliza el último control del contexto, sin restaurar foco en otra ruta.
- Enter activa el botón enfocado una vez. En una confirmación nativa, Enter sobre No conserva la sesión y sobre Sí registra una sola salida. La comprobación HTTP de este caso no añadió errores 500.
- La tabla vacía se recorre sin crear filas. Añadir fila crea una línea explícitamente; Enter/Espacio abre sus editores. Tab conserva las filas existentes y las flechas de un Select eligen la opción sin saltar de fila. Link conserva su autocompletado nativo. Las celdas/selecciones de fila tienen etiquetas y las opciones muestran Una vez por estancia y Por noche (hotel), conservando Stay/Night en datos.
- Una lectura nativa de dependencias conserva el precio que se acaba de escribir antes de blur, también cero. Se preservan cambios nativos que ocultan, deshabilitan o reemplazan un campo. No se cambia el modelo ni se elude su validación.
- Un checklist obligatorio sin marcar se rechaza antes de enviar y enumera los puntos pendientes. Al cerrar el aviso, el foco vuelve al primero. Cero sigue siendo válido para importes. Los nombres internos de campo usados como ayuda de desarrollo no se anuncian como etiquetas.
- Las tablas anchas tienen una región de desplazamiento accesible por teclado. Se comprobó desplazamiento horizontal con flecha; el foco visible tiene contorno propio. En móvil, el menú nativo del contenedor operativo tiene nombre y área de 44 × 44; no se cambian menús de otras Pages.
- Auditoría permite recorrer Operación, Valores registrados y los datos plegados sin escribir. Mantenimiento usa Trabajo requerido, Inicio del trabajo y Fin previsto; no confunde esos campos con una tarifa o reserva. Los estados se muestran escritos, además del color.
- El portal público tiene etiquetas asociadas, menú en español y foco visible. La fecha obligatoria incompleta recibe foco nativo. Tras consultar, precio o falta de cupo reciben foco si la persona no está editando otro campo; Tab permite alcanzar la siguiente acción. El mensaje de negocio queda en línea sin popup duplicado. No se inserta HTML arbitrario de mensajes del servidor.

La implementación utiliza métodos propios, eventos públicos de Frappe y listeners del diálogo concreto; no reemplaza prototipos del núcleo. Se contrastaron ui/dialog.js, ui/keyboard.js, ui/field_group.js, form/layout.js, form/grid_row.js y website/js/website.js de Frappe 16.52.0. Website usa error_msg para sus mensajes, mientras Desk admite silent: el portal entrega a Website un destino jQuery vacío y muestra su texto mediante textContent.

## Recorrido real y evidencia

[keyboard-review-roles-ui.json](evidence/keyboard-review-roles-ui.json) conserva 180 eventos. La identidad acreditada procede del actor observado en el DOM, con 43 observaciones y los nueve usuarios HS. Las etiquetas de rol de los helpers pueden quedar retrasadas entre closures del REPL; se conservan solo como diagnóstico. Los eventos que contienen únicamente teclas no inventan un actor. Las capturas y la inspección de documentos respaldan el flujo:

| Rol | Acción comprobada |
|---|---|
| Administración | Categoría conservada y tarifa de 900 con dos servicios guardada; repetición móvil cancelada sin guardar. Pestañas, precio, validación y tabla. |
| Recepción | Huésped Visita teclado, reserva de H101, entrada, consumo de un agua, entrega y salida después del cobro por Caja. |
| Caja | Fondo inicial cero, cobro de 1530, recibido 1600/vuelto 70, conteo sintético por denominación y turno cerrado sin diferencia. |
| Limpieza | Inicio, rechazo de checklist vacío, cuatro casillas con Espacio/Tab y solicitud de inspección. No se autoaprueba. |
| Supervisión | Inspección independiente y liberación de H101; finalización y reapertura de mantenimiento H102. |
| Mantenimiento | Orden Revisión por teclado, fecha escrita por segmentos y bloqueo hasta reapertura; solo Abierta/En curso para el técnico. |
| Contabilidad | Tres filas de conciliación en OK, tabla desplazable y factura presentada por 1530 con saldo cero. |
| Gerencia | Producción de alojamiento 1500 y agua 30, revisiones, cancelación/cierre de sesión y retorno de foco. |
| Auditoría | Consulta y detalle de reapertura, pestañas y datos plegados; repetición móvil sin modificar la operación. |

El recorrido avanzó sobre compilaciones sucesivas; cada defecto se corrigió y se repitió su regresión concreta. El bundle final de Desk es TSVX6BYI; Administración y Auditoría se repitieron en móvil con esa compilación. El portal se sirve desde sus archivos www y se recargó después de cada cambio. No se presenta todo el recorrido anterior como una segunda ejecución completa sobre el último bundle.

[keyboard-review-items-ui.json](evidence/keyboard-review-items-ui.json) es la inspección de solo lectura posterior: RES-2026-00001, EST-2026-00001, factura ACC-SINV-2026-00001 y pago ACC-PAY-2026-00001. Comprueba propietarios/roles, 1530 facturados y pagados, diferencia de turno cero, entrega con una salida de stock, limpieza inspeccionada y reapertura autorizada. La tarifa móvil no se guardó y no se envió una solicitud del portal. Las operaciones del escenario se realizaron desde Pages, sin fixtures operativos creados por API.

Capturas representativas: [reserva](evidence/250-reserva-resumen-teclado.jpg), [revisión de cobro](evidence/252-revision-cobro-teclado.jpg), [checklist](evidence/256-checklist-teclado.jpg), [conciliación](evidence/261-conciliacion-teclado.jpg), [tarifa móvil](evidence/268-tarifa-movil-precio-conservado.jpg) y [portal final sin cupo](evidence/272-portal-error-final-movil.jpg). Las imágenes 247 y 271 son estados anteriores/intermedios de defectos encontrados, no aceptación final.

## Pruebas y conservación

- [keyboard-review-native-tests.xml](evidence/keyboard-review-native-tests.xml): 380 casos sin errores/fallos/omisiones, 366 de integración y 14 puros. La [salida](evidence/keyboard-review-native-tests.log) corresponde a la ejecución final, después de restaurar y migrar aceptación. Incluye una regresión nueva de las etiquetas de mantenimiento y conservación de sus valores.
- [keyboard-review-js-tests.log](evidence/keyboard-review-js-tests.log): 174 aprobadas, 171 de Desk y tres del portal. Son 32 más que 0.8.1; el modelo de DOM prueba fronteras del código y se complementa con el navegador real.
- [keyboard-review-build.log](evidence/keyboard-review-build.log), [wire-invariants](evidence/keyboard-review-wire-invariants.json), [fuentes/etiquetas instaladas](evidence/keyboard-review-language-installed.json) y [permisos](evidence/keyboard-review-permissions-source.json) conservan compilación, 28 fuentes existentes y un módulo nuevo, 158 fuentes Python y la superficie sin nuevas APIs públicas. El inventario estructural no sustituye el recorrido.
- [keyboard-review-logout.json](evidence/keyboard-review-logout.json): Enter en No envía cero solicitudes y Enter en Sí envía una, sin nuevo 500. Antes de corregir se observaron dos peticiones y una carga transitoria de login con TypeError nativo; se conservó ese resultado en la traza.
- [keyboard-review-ux-restored.json](evidence/keyboard-review-ux-restored.json) conserva las 71 tablas y 185 filas iniciales de negocio. [keyboard-review-upgrade.json](evidence/keyboard-review-upgrade.json) compara además Version y archivos: principal 72/1246 y dos archivos privados; aceptación 72/250. Todas las huellas coinciden con el respaldo original de esta fase. La fecha operativa sigue 19/10/2026.
- [keyboard-review-final-state.json](evidence/keyboard-review-final-state.json): 8089 detenido, 8086/Socket.IO/Redis activos y HTTP 200; la demostración rechaza la batería de integración. El formato breve de cuenta instalado conserva su hash y sigue sin bloques de cálculo histórico. Núcleos Frappe/ERPNext limpios.

Las salidas publicadas normalizan finales de línea y espacios terminales; los originales permanecen en .local/keyboard-review. Durante la verificación final se encontró una interrupción de servicios: puertos ausentes y Redis Queue rechazando conexión. Se arrancaron con el helper acotado y se repitieron salud y comparación estricta de datos. No se sustituyó una prueba fallida por una afirmación de éxito.

La restauración del sitio sintético y esta aceptación no son el ensayo final de despliegue/reversión F26. La sincronización con plataformas de reservas continúa aplazada por indicación del usuario.
