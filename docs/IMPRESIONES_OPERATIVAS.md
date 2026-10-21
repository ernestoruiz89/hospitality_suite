# Impresiones y artefactos nativos - 0.8.7

La revisión de S18-02 contrasta los artefactos entregados y su instalación; S18-03 contrasta las impresiones solicitadas. No acredita la terminación de las otras tareas, formularios o fases del producto.

## Documentos accesibles desde las Pages

| Documento | Acceso operativo comprobado | Formato de la app | Render real revisado |
|---|---|---|---|
| Confirmación de reserva | Recepción: Ver reserva, Imprimir confirmación | HS Confirmación de reserva | [Confirmación](evidence/320-confirmacion-reserva-pdf.png) |
| Registro de huésped | Cuenta de estancia, Imprimir registro de huésped; permiso de gestión de huéspedes | HS Registro de huésped | [Registro](evidence/321-registro-huesped-pdf.png) |
| Cuenta de estancia | Calendario o estancia, Imprimir cuenta | HS Cuenta de estancia | [Cuenta concisa](evidence/322-cuenta-concisa-pdf.png) |
| Factura / nota de crédito | Caja: estancia, enlace de factura en la cuenta; formato elegido en Configuración | HS Factura por defecto | [Factura](evidence/323-factura-pdf.png) |
| Recibo | Caja: Ver recibo en Movimientos recientes y tras registrar el movimiento; formato elegido en Configuración | HS Recibo por defecto | [Recibo](evidence/324-recibo-pdf.png) |
| Arqueo y cierre de turno | Caja: Imprimir en la fila del turno cerrado | HS Arqueo | [Arqueo](evidence/325-arqueo-pdf.png) |
| Orden de limpieza | Imprimir orden en la tarjeta de la tarea | HS Orden de limpieza | [Limpieza](evidence/326-limpieza-pdf.png) |
| Orden de mantenimiento | Imprimir orden en la fila del trabajo | HS Orden de mantenimiento | [Mantenimiento](evidence/327-mantenimiento-pdf.png) |
| Cierre diario conservado | Gerencia: historial de cierres, Imprimir cierre | HS Cierre diario | [Página 1](evidence/328-cierre-diario-pagina-1.png), [página 2](evidence/329-cierre-diario-pagina-2.png) |

Se añaden los accesos al registro y a la orden de limpieza, y el recibo permanece recuperable después de recargar Caja. La impresión no registra otro cobro ni cambia el estado de la tarea. Los nombres de pagadores y responsables usan sus nombres descriptivos; los números de documento se conservan para la trazabilidad. El texto codificado de campos Data se decodifica una vez y se vuelve a escapar, sin insertar HTML arbitrario ni traducir nombres de maestros.

La cuenta sigue concisa: cargos, cuentas/saldos y documentos existentes, sin el cálculo histórico detallado. El registro separa al huésped principal de sus acompañantes y explica una lista vacía. El recibo ordinario ya no incluye la explicación propia de una liquidación bancaria. El arqueo distingue aprobación pendiente y no requerida. La factura identifica compañía y establecimiento, conserva la moneda de la cuenta del cliente para el saldo, y muestra el total exigible y su redondeo con los mismos campos nativos usados por ERPNext/PMS. El formato fiscal y las condiciones reales siguen configurándose por instalación.

## Evidencia ejecutada y alcance

**386 pruebas nativas aprobadas: 372 de integración y catorce puras**, incluidas seis nuevas de impresión. [JUnit normalizado](evidence/print-delivery-native-tests.xml) y [salida realmente ejecutada](evidence/print-delivery-native-tests.log). Las seis comprueban los nueve formatos con sus roles, nombres/escape, ausencia de escrituras de negocio, denegaciones, selección de formatos, acompañantes y proyección de total/redondeo/POS/moneda en copias transitorias. El caso nativo anterior de POS con 60.15/60 también forma parte de la batería; no se presenta la copia transitoria de impresión como otra transacción contabilizada.

La primera pasada detectó dos expectativas incorrectas de presentación y un nombre nativo con entidades: se identifica el establecimiento de la factura y se normalizan los nombres con escape. La regresión completa detectó después que un nombre de usuario histórico sin maestro perdía su literal al sustituirse por un guion; se conserva de nuevo el fallback. La batería definitiva incluye esa comprobación de localización sin debilitarla.

**210 pruebas JavaScript aprobadas: 207 Desk y tres portal**, siete nuevas. [Resultado](evidence/print-delivery-js-tests.log), [compilación definitiva](evidence/print-delivery-build.log) y [valores de protocolo conservados](evidence/print-delivery-wire-invariants.json).

Los nueve PDF reales se generan mediante Frappe/wkhtmltopdf, en un escenario API sintético que se revierte sin confirmar sus documentos. Son diez páginas: ocho documentos de una página y el cierre de dos. [Manifiesto](evidence/print-delivery-pdfs.json), [estructura](evidence/print-delivery-pdf-structure.json) y los diez renders anteriores conservan evidencia. El proceso usa loopback para cargar los assets del servidor temporal; no cambia el host persistido del sitio. Los PDF de QA se encuentran en `output/pdf/print-delivery` y pueden regenerarse con el helper documentado en el repositorio.

Para repetir esta revisión en el entorno WSL instalado, con aceptación sin operaciones y la app migrada, el servidor y el generador exigen la línea de base de `tools/service_ux.py before --phase print-delivery`. Esa línea se crea una sola vez y se conserva. Con ella disponible, desde el bench y como usuario `frappe`:

```bash
repo=/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel
env/bin/python "$repo/tools/print_delivery_server.py" start
env/bin/python "$repo/tools/print_delivery_qa.py"
env/bin/python "$repo/tools/print_delivery_server.py" stop
```

El helper del servidor comprueba sitio/base/puerto; el generador comprueba que no hay operaciones, crea su escenario mediante API, imprime con cada rol y verifica la igualdad tras rollback. La revisión estructural de los archivos se repite con `python tools/qa_pdf.py output/pdf/print-delivery --expected-files 9` desde el repositorio, usando un Python con `pypdf`; el render se verifica visualmente con Poppler. El escenario persistido de navegador usa el helper separado `print_delivery_fixture.py` y requiere la restauración nativa con archivos posterior; no se necesita para regenerar estos nueve PDF transitorios.

La prueba de navegador usa otro escenario desechable creado por las APIs nativas. **No se atribuye a la UI la creación de esos documentos**: las Pages comprueban el acceso a impresión. Veintidós eventos cubren Recepción, Caja, Limpieza, Mantenimiento y Gerencia. [Traza](evidence/print-delivery-browser.json) e [inspección final](evidence/print-delivery-ui-data.json). Limpieza abre su orden desde la [vista móvil efectiva de 390 px](evidence/337-imprimir-limpieza-movil-390.jpg), sin desbordamiento del documento. La [captura 336](evidence/336-imprimir-limpieza-escritorio.jpg) es escritorio de 1280 px; el primer intento de tamaño no se había aplicado a la pestaña temporal y no se cuenta como aceptación móvil. Se restablece el viewport y se cierran las sesiones y pestañas de QA.

## Corrección encontrada al revisar las acciones

L7TWF4HE abre la reserva, pero deja deshabilitado «Ver estancia y cuenta» después de finalizar la preparación. [Captura 331](evidence/331-boton-cuenta-deshabilitado-defecto.jpg). Los modales están fuera de la raíz de la Page. VBL4AU4J amplía la liberación por propietario, pero Frappe vuelve a insertar el HTML con la marca antigua; la [captura 332](evidence/332-boton-recreado-defecto.jpg) conserva ese segundo defecto.

La compilación definitiva **TFVL2SJI** identifica el propietario de las acciones y aplica su estado actual al insertar nuevos botones. Usa un solo observador, comprueba conexión/actividad y conserva separados los botones nativos y los de otras Pages. Las tres regresiones nuevas de transporte cubren finalización, aislamiento/recuperación y reinserción tardía. En navegador se repite el paso reserva a cuenta, se abre también desde el calendario y se imprimen registro y cuenta. [Acciones corregidas](evidence/333-impresiones-recepcion-desde-cuenta.jpg), [recibo de Caja](evidence/334-recibo-desde-caja.jpg) y [factura desde la estancia](evidence/335-factura-desde-estancia-caja.jpg). Las nueve familias se consultan tras la corrección; se conserva además la confirmación inicial anterior a ella.

Esto corrige la deshabilitación persistente encontrada en este recorrido. No declara resueltos todos los clics durante el cierre visual nativo ni todas las reglas/estados de las vistas secundarias de S04-16.

## Inventario y conservación

[Inventario instalado](evidence/print-delivery-native-artifacts.json): 35 DocTypes con controladores propios, 11 Pages, 28 APIs públicas revisadas, permisos/campos contra el origen, nueve formatos, seis patches registrados y el método programado de expiración. Se comprueban ambos sitios, los hooks y métodos referenciados. Los artefactos nativos JSON se complementan con altas idempotentes de roles/campos/permisos en instalación/migración y fixtures explícitos de demostración/pruebas; no se siembran operaciones demostrativas durante una instalación normal. No se declara que exista un directorio de fixtures exportados distinto de esa estrategia.

El escenario de impresión conserva una reserva, estancia, cargo, cobro, turno, tarea, orden, cierre, factura y Payment Entry; cero Journal Entry. La lectura posterior acredita que las impresiones no los alteraron. Tras la restauración y migración, aceptación vuelve a 71 tablas/185 filas de negocio y 72/250 con Version; principal conserva 72/1246, dos archivos privados y fecha 19/10. [Verificación de fase](evidence/print-delivery-verification.json) enlaza las comprobaciones, fuentes y resultados.

S18-02 y S18-03 quedan acreditados con su alcance individual. La matriz conserva **200 V, seis I, cero P y doce R: dieciocho entradas abiertas**. Continúan las tareas/estados por rol y las revisiones generales/fases, incluidos F26 e instalación/reversión de la versión final. Airbnb/Booking y la sincronización externa siguen aplazados por instrucción del usuario.
