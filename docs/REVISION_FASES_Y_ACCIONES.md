# Contraste de fases y acciones — 0.8.8

Esta revisión contrasta los doce requisitos generales/de fases que aún tenían «Contraste individual pendiente». No cambia código de negocio, no vuelve a ejecutar la batería completa y no realiza operaciones por navegador. La aplicación coincide byte por byte con `fb8c022`, versión en que se ejecutaron [404 casos nativos](evidence/provider-contracts-native-tests.xml) y [210 JS](evidence/provider-contracts-js-tests.log). Los recorridos visuales anteriores se identifican como históricos; no se presentan como una repetición visual de esta revisión.

## Estado comprobado ahora

[Inventario del entorno/modelo](evidence/phase-review-architecture.json): Frappe 16.52.0, ERPNext 16.51.1, app 0.8.8, Python 3.14.6, Node 24.18.0 y MariaDB del bench; núcleos limpios, 35 DocTypes, once Pages, nueve roles e índices inspeccionados. [Metadatos de ambos sitios](evidence/phase-review-native-artifacts.json) contrastan campos/permisos/controladores, nueve formatos, seis patches y los 28 métodos del módulo API operativo. Portal/webhook conservan sus endpoints separados documentados en API.md; «28» no se usa como censo de todos los endpoints públicos de Frappe.

[Inventario de acciones](evidence/phase-review-actions.json) sigue las 29 importaciones del bundle en su orden real, incluidas las sustituciones de métodos: 84 manejadores y 97 apariciones de botones con nombre literal. Las dos construcciones dinámicas se resuelven al conjunto cerrado de acciones de estancia y reserva/calendario. No hay acciones declaradas sin manejador; los nombres RPC literales corresponden al API operativo y las mutaciones literales al registro COMMANDS. Esto acredita conexiones de código, **no que toda interacción, regla o combinación de rol se haya aceptado visualmente**.

La [comparación actual de datos/archivos](evidence/phase-review-preservation.json) es estricta contra las columnas y bytes protegidos de 0.8.8: principal 72 tablas/1246 filas/dos archivos, fecha operativa 19/10; aceptación 72/250 incluyendo Version y sin operaciones. HTTP 200, servicios aislados activos y 8089 detenido. Esta revisión no necesita otra preparación, respaldo ni restauración porque no modifica datos.

## Veredicto por fase

| Entrada | Contraste concreto | Estado y límite |
| --- | --- | --- |
| S19-01 | Entorno actual, elección de Page API nativa, modelo/estados, roles/índices, decisiones y matriz original de 218 entradas. Inventarios actuales más pruebas de permisos/configuración y auditoría de arquitectura | V |
| S19-02 | Instalación existente y metadatos actuales, asistente, habitaciones/tarifas y exclusión de disponibilidad: implementados y probados. Migrate de un sitio existente no prueba una instalación limpia final | I: pendiente ese ensayo y el paquete/dependencias |
| S19-03 | Pages de recepción/reservas/estancias y acciones cargadas; pruebas actuales de ciclo de vida, reservas, tarifas, huéspedes y cambio/extensión/salida. Se revisan el recorrido real de H101 desde reserva hasta salida/limpieza y los grupos/cambios anteriores | V para el flujo enumerado. Conserva las I globales de tareas y estados secundarios |
| S19-04 | Folios, consumos, factura, anticipos/garantías, cobros/devoluciones, turnos y conciliación nativa: fuentes y casos actuales, complementados por cobro real desde Page, saldo cero, arqueo cerrado y rastreo de documentos | V para los flujos enumerados; no equivale a aceptar todas las variantes visuales |
| S19-05 | Limpieza/inspección y bloqueo/reapertura, servicios/inventario/compras nativos, periódicos y cierre. Recorridos anteriores de limpieza/supervisión, En proceso→Entregado→Devuelto, stock 98→96→98 y cierre 19→20, más regresión actual | V |
| S19-06 | Reportes con fuentes/fórmulas/cortes, portal opcional con token y conversión sin pago supuesto, contratos/adaptadores de referencia y simulaciones sin proveedores reales | V. Publicación/sincronización de canales sigue aplazada |
| S19-07 | Batería actual, correcciones y documentación existen. Faltan aceptación global de tareas/estados, instalación limpia y ensayo coordinado de actualización/reversión | I: F26 no queda resuelto por restaurar fixtures |
| S19-08 | Hay registro de avance y contraste por fase, se conserva el alcance original y las acciones tienen manejador. Eso no prueba todos sus resultados ni la fase 7 aún abierta | I hasta cerrar esas comprobaciones |
| S19-09 | Errores de entorno, recuperación y límites de simulaciones se documentan; pendientes siguen explícitos y se continúa en componentes independientes. No se atribuyen operaciones a pruebas que solo prepararon fixtures ni se ofrecen proveedores ficticios como reales | V del procedimiento de trabajo, no de completitud del producto |

[El contraste estructurado](evidence/phase-review-crosswalk.json) conserva por cada fila su fundamento, fuentes, requisitos componentes, módulos/casos presentes en el JUnit y evidencia histórica específica. Los estados V no se infieren de un recuento ni únicamente del estado de sus componentes: el inventario de código y los resultados/recorridos relacionados se revisan con el límite indicado arriba. Los recorridos principales por Pages no sustituyen la aceptación transversal S00-02/S04-14/S04-16/S04-20.

## Requisitos generales todavía abiertos

S00-01 y S01-12 pasan R→I: se localizan la implementación completa por áreas y sus pruebas, pero no se declara concluido el alcance hasta terminar las comprobaciones globales pendientes y la entrega final. S18-01 pasa R→I: hay estructura nativa, dependencias en `pyproject.toml`, bundles de Bench y código versionado; falta comprobar el paquete distribuible y la instalación final. La app no necesita un package.json propio para estos módulos JavaScript sin dependencias adicionales; se construyen con el bundler del Frappe probado. Esto no acredita todavía el contenido de un wheel/sdist ni otro entorno no probado.

Seis entradas pasan R→V: S19-01/S19-03/S19-04/S19-05/S19-06/S19-09. Las otras seis R pasan a I con verificaciones concretas. La matriz conserva texto, líneas y huella de las 218 originales: **208 V, diez I, cero P y cero R: diez entradas sin cierre**. El objetivo permanece activo.

Las diez I quedan identificadas:

- **S00-02/S04-14/S04-20:** terminar la colección transversal de tareas habituales y secundarias por rol/Page. Vincular cada acción relevante con resultado autorizado y datos posteriores; distinguir operaciones de UI y fixtures preparados por API. Los 84 manejadores son inventario de partida, no 84 aceptaciones realizadas.
- **S04-16:** contrastar las reglas por campo y los estados de vistas/búsquedas secundarias, con vacío/carga/error/éxito y doble envío. Revisar especialmente campos numéricos sin `_hsBounds` y el orden respecto al parseo nativo; no se afirma aquí que se haya reproducido o corregido un fallo en ellos. Repetir las secuencias rápidas de cierre/acción de diálogos y concretar su observación histórica.
- **S18-01/S19-02:** paquete y dependencias, instalación limpia de la versión final y primer arranque con metadatos/permisos correctos. No crear silenciosamente configuración financiera ni demo como parte de la instalación.
- **S19-07/S19-08:** cierre de aceptación y ensayo final F26 de despliegue, actualización y reversión coherente de código/base/archivos en un destino aislado; conservar los respaldos, no descartar actividad nueva y comprobar recuperación antes de reabrir.
- **S00-01/S01-12:** cerrar el objetivo completo solo después de lo anterior, sin reducir el alcance a los puntos ya aprobados.

No hay un bloqueo de credenciales que impida estas comprobaciones del núcleo. Las integraciones comerciales y la sincronización de reservas siguen siendo externas opcionales; Airbnb/Booking continúa aplazado por el usuario. [Verificación de la revisión](evidence/phase-review-verification.json).
