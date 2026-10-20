# Formularios por tarea, versión 0.5.2

La petición del usuario prioriza formularios cortos, acciones claras y una experiencia usable en escritorio y móvil. Esta fase reorganiza los controles nativos de Frappe; conserva los comandos, validaciones, permisos, claves de solicitud y documentos estándar de ERPNext.

| Formulario | Secciones | Acción principal |
|---|---|---|
| Políticas y contabilidad | Operación; Cuentas y almacenes; Artículos e impuestos | Guardar configuración |
| Tarifa | Precio; Tiempo y personas; Vigencia; Servicios incluidos | Guardar tarifa |
| Medio de pago | Medio y cuenta; Comisión y liquidación; Devoluciones | Guardar medio de pago |
| Horarios y penalizaciones | Horarios; Cargos por horario; Cancelaciones | Guardar horarios y políticas |
| Reserva y entrada | Huésped y fechas; Habitaciones; Opciones | Revisar precio; después confirmar reserva o entrada |
| Cobros y fondos | Cuenta y concepto; Importe; Devolución cuando corresponde | Revisar cobro, anticipo, garantía o devolución; después confirmar ese concepto |
| Huésped | Datos principales; Datos adicionales | Guardar huésped |
| Nuevo establecimiento | Establecimiento; Fecha y horario | Crear establecimiento |

En hotel se indica precio por noche; en motel, precio por bloque. Los ajustes de bloques, exceso y ventana nocturna se muestran para motel. En caja, los datos de devolución aparecen para esa acción, el efectivo recibido/entregado aparece con un medio de efectivo y la referencia bancaria depende del medio y de su política. Estas condiciones orientan la captura; el servidor continúa validando la operación.

El encabezado y la acción permanecen fuera del área que se desplaza. Las pestañas se ajustan al ancho; las columnas se apilan en móvil. El botón principal y el cierre tienen al menos 44 px en móvil. Cada pestaña expone su selección accesible. Si falta un valor obligatorio, la validación nativa informa los campos y se abre la sección del primero. Al revisar una cotización, el formulario anterior se oculta y queda inerte; al cancelar la revisión, vuelve con sus valores intactos.

## Evidencia ejecutada

La batería JavaScript aprueba **37 casos**, siete nuevos para disposición y conservación de controles, dependencias hotel/motel y medios, recuperación de errores entre pestañas, intención de cobro/devolución, estado accesible y borrador al cancelar una revisión. No equivale a 37 recorridos de navegador. La batería de backend vigente sigue siendo la de 0.5.1: **196 aprobadas** (182 de integración y catorce puras); esta fase no cambia sus reglas ni presenta otra ejecución completa de backend.

El recorrido real usa `hospitality-acceptance.localhost:8089`, gerente ficticio, 1280×720 y 390×844. No usa clientes ni dinero reales:

1. Configuración: editar el nombre comercial en Operación, recorrer Cuentas y Artículos y guardar desde la última pestaña. Recarga conserva el cambio.
2. Tarifa: intentar guardar desde Servicios incluidos con los campos principales vacíos; se bloquea y vuelve a Precio, con `aria-selected=true`. Completar nombre, categoría, importe 1234 y prioridad 1; cambiar personas incluidas de 2 a 3 en otra pestaña; guardar desde Servicios incluidos. La lectura nativa confirma todos esos valores.
3. Huésped: capturar nombre/correo en Datos principales y guardar desde Datos adicionales. Una sola ficha conserva ambos valores.
4. Entrada inmediata: seleccionar ese huésped y pagador, H101 y una persona; cotizar desde Opciones y confirmar C$1500 conforme a la tarifa demo de mayor prioridad. Se conserva una reserva, estancia y cuenta.
5. Caja: abrir turno en cero; recorrer Devolución sin registrarla y volver a Cobro. Elegir cuenta/medio de efectivo, importe 1500 y recibido 1600. La revisión muestra vuelto 100 y una única confirmación. Cerrar la revisión conserva importes y medio; reabrir y confirmar genera exactamente una factura, un Payment Entry y un HS Payment. Saldo cero.
6. Arqueo desde Page: contado/esperado 1500, diferencia cero y turno cerrado. Se termina la sesión hasta observar Login.

La inspección es de lectura y revierte sus bloqueos. `forms-items-ui.json` acredita los valores y documentos. No se efectuó una devolución en este recorrido ni se acredita aquí una nueva sesión contable, todos los roles o tiempo real: el servidor temporal no tiene Socket.IO propio.

Capturas: 96 configuración, 97 precio de tarifa, 98 huésped móvil, 99 validación móvil, 100 confirmación única del cobro y 101 caja cerrada. Las capturas 97/98 muestran borradores de presentación; no representan nuevas altas adicionales. En móvil se midieron 44 px de alto y 342 px de ancho para Guardar huésped, dentro de un viewport de 390×844; el formulario de políticas también conserva su pie dentro del viewport.

La primera construcción de pestañas detectó la necesidad nativa de `hidden: 0` en la apertura; el código objetivo se consultó y se corrigió. La revisión real detectó el botón `es-button btn-modal-primary` de Frappe 16: el CSS final usa esas clases. La primera inspección de saldo comparaba texto con número; se corrigió a la representación monetaria del contrato. Esas comprobaciones iniciales no se presentan como aprobadas.

## Conservación y alcance pendiente

Antes del recorrido se conserva el respaldo nativo con archivos. Al terminar se detiene 8089 y se restaura aceptación: 71 tablas/185 filas coinciden. La comparación adicional incluye Version: 72 tablas/195 filas de aceptación y 72 tablas/1191 filas principales con dos archivos privados idénticos. Las diferencias históricas de caché de Company conservan su acreditación específica. La fecha operativa principal sigue en 19/10 y no se confirma su cierre.

Los núcleos Frappe/ERPNext siguen limpios. La matriz canónica mantiene **80 V, ocho I, dos P y 128 R de 218**: esta mejora no acredita por sí sola todos los flujos obligatorios. F22 conserva su alcance general I y se añade F22a para esta verificación concreta. Continúan cargos periódicos e idempotencia, contraste restante, traducciones, aceptación completa y recuperación de la revisión final. La sincronización con plataformas de reservas permanece pendiente por indicación del usuario.

## Ampliaciones posteriores

FACTURACION_DESDE_PAGES.md acredita la revisión compacta y emisión sin cobro/salida en 0.6.1. ESTANCIAS_Y_LLEGADAS.md acredita en 0.6.2 las cuatro vistas, próxima llegada en tarjetas, cabecera móvil compacta y ficha de cuenta de 352 px sin desborde/con acción de 44 px. El selector de fecha aparece solo en las tareas donde cambia los resultados. Continúan el contraste general y formularios secundarios; gestionar reservas aún puede reducir el área de motivo y mostrar campos según acción. Los recuentos del cuerpo de este documento corresponden a la fase histórica 0.5.2; REQUISITOS.md conserva el estado vigente.
