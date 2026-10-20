# Cargos periódicos de alojamiento, versión 0.6.0

Configuración → Políticas y contabilidad → Cargos de alojamiento permite elegir **Al ingresar** o **Por noche, en la auditoría del día**. La primera opción conserva el comportamiento anterior y es el valor de la actualización. La segunda se aplica a nuevas estancias hoteleras; la estancia conserva su política aunque después cambie el establecimiento. Un motel mantiene sus cargos por bloque y horas adicionales. En un establecimiento mixto se respeta la modalidad aceptada de cada estancia.

## Programación y generación

Cada noche conserva el importe individual de la cotización aceptada, incluido su tarifario, moneda, artículo y fecha. Una estancia de tres noches distintas no se convierte en tres promedios. Las extensiones añaden exclusivamente sus nuevas noches y conservan la política de la estancia.

HS Charge distingue el estado **Scheduled / Programado** del cargo **Pending / Pendiente** ya generado. Una programación es una obligación operativa aceptada; no crea factura, Payment Entry, GL Entry ni otro libro contable. La cuenta muestra el importe programado y el saldo total por separado. Los cargos programados se excluyen de la producción ordinaria, mientras la ocupación continúa usando las noches aceptadas. Se pueden consultar expresamente mediante su estado.

**Preparar cierre del día** genera las noches de la fecha operativa y las vencidas; las futuras permanecen programadas. Solo los usuarios autorizados para finanzas generan cargos. Se mantienen la revisión de pendientes, la autorización final y el avance explícito de fecha. La acción POST `generate_lodging` permite ejecutar el mismo proceso desde el contrato autenticado. El disparador operativo de esta política es la preparación de la auditoría de cada fecha; no se añade un trabajo automático del reloj ni se avanza la fecha desde un worker.

La referencia interna `period_key` identifica estancia, origen de entrada/extensión y noche. Es única en la base y se conserva al facturar, mover de cuenta y revertir. La transacción toma el bloqueo del establecimiento y cambia solo las programaciones pendientes. Repetir con la misma clave devuelve la respuesta anterior; una nueva petición de la misma fecha procesa cero cargos adicionales. Se registra una bitácora por lote efectivamente generado.

## Liquidación y ERPNext

Facturar o registrar salida liquida también las noches programadas de esa cuenta, conservando el total aceptado. Esto permite facturación/pago anticipados. La operación es atómica: si falla la factura, sus noches vuelven al estado anterior y no queda cobro ni factura parcial. Después de facturar, repetir la auditoría no vuelve a generar esas noches. Una cancelación nativa devuelve sus cargos a pendientes de facturar, conservando la identidad de origen.

La factura creada directamente en ERPNext puede usar los cargos programados como fuentes explícitas. Se impide introducir otra línea del mismo artículo sin su origen cuando hay cargos pendientes o programados. Se conservan las validaciones de cuenta/pagador, moneda, cantidad, ajustes completos y cargo utilizado una sola vez. El efecto contable sigue perteneciendo a los controladores estándar de ERPNext, con su fecha de contabilización y tratamiento tributario configurado.

**Pendiente de interfaz verificado:** el servidor tiene la acción `invoice`, pero las Pages solo alcanzan la facturación mediante cobro o salida. Falta una acción explícita para emitir la factura de una cuenta activa sin cobrar ni registrar salida. Es necesaria también para el caso de una cuenta de importe cero, que no admite un cobro ficticio. No se declara completo el requisito general de tareas habituales desde Pages; S00-02/F22 quedan P. La captura 103 y `periodic-page-invoice-gap.json` conservan la evidencia de esa ruta ausente. Este es el siguiente cambio de interfaz, manteniendo revisión de importes y permisos financieros.

Un cargo programado puede trasladarse a otra cuenta de la estancia/grupo junto con sus ajustes. Los descuentos/cortesías conservan su autorización y saldo máximo; un ajuste de una noche programada hereda su fecha y estado. Los cambios manuales de habitación conservan su cotización y cargos diferenciales autorizados. No se recalcula la cotización original al ejecutar la auditoría.

## Interfaz y comprobación real

La política tiene una pestaña propia y explicación breve. El cierre usa secciones desplegables: abre las que contienen importes y conserva accesibles los detalles de las secciones en cero. El encabezado y el botón permanecen visibles mientras se desplaza el contenido. La cuenta y el PDF separan alojamiento programado, cargos pendientes y saldo total.

El recorrido en `hospitality-acceptance.localhost` usa gerente y huéspedes ficticios. Se guarda/reabre la política en móvil 390×844. Desde Recepción se acepta H101 del 19/10 a las 14:00 al 22/10 a las 12:00, tres noches por 4500. Es una llegada tardía sintética respecto del reloj del 20/10; la fecha operativa permanece en 19/10.

Antes de preparar el cierre, la cuenta muestra tres noches programadas por 4500. Se prepara dos veces la misma fecha desde Gerencia: queda exactamente una noche generada por 1500 y dos programadas por 3000, saldo 4500, una sola bitácora de generación y cero facturas/pagos. No se confirma ese cierre. Se consulta el resumen conservado, se expande una sección en cero y se termina la sesión hasta Login. El servidor temporal no tiene Socket.IO propio; este recorrido no acredita tiempo real ni una nueva prueba de todos los roles.

Capturas 102–104 y `periodic-items-ui.json` acreditan esa operación. La cuenta nativa se genera en PDF de una página, se extraen texto/importes y se renderiza con Poppler para inspección visual; captura 105 y `periodic-pdf.json`. El primer intento PDF no resolvía el hostname del sitio desde WSL; se usa la URL loopback del mismo servidor solo en la configuración de memoria de la herramienta, sin cambiar la configuración guardada.

## Evidencia automatizada y conservación

`test_periodic.py` cubre noches/precios individuales e índice único real, vencidas/futuras, reintentos con nuevas claves, cierre revisado/confirmado/reabierto, factura anticipada y cancelación, extensión también a precio cero, fallo parcial y recuperación, traslado con ajuste, permisos, producción sin programados, motel por bloque y facturación nativa con/sin origen. Los resultados finales están en `periodic-native-tests.log/xml`. `periodic-js-tests.log` incluye la regresión de secciones desplegables además de las regresiones previas. Los recuentos vigentes están en REQUISITOS.md.

Antes de actualizar se respaldan ambos sitios con archivos. `periodic-upgrade.json` compara todas las columnas anteriores de 72 tablas con Version: 1191 filas principales y dos archivos privados, 195 filas de aceptación. También comprueba la política inicial Al ingresar y la ausencia de cargos programados o identidades periódicas retroactivas. Las columnas nuevas no se confunden con modificaciones de los datos anteriores.

El sitio de aceptación se respalda antes del recorrido y se restaura después con Bench y archivos. `periodic-ux-restored.json` compara sus 71 tablas/185 filas, incluidas todas las columnas nuevas. `periodic-final-state.json` conserva las guardias, servicios y estado final. El sitio principal mantiene su fecha operativa y sus operaciones; los núcleos Frappe/ERPNext no se modifican.

La reversión de una instalación que ya use esta política requiere un respaldo compatible con su código y esquema. No se deben interpretar estados nuevos con una revisión anterior que los desconozca. El ensayo final de recuperación de la revisión que se entregue sigue pendiente en F26. Continúan el contraste de requisitos aún R, otras verificaciones I, traducciones y aceptación completa. La sincronización externa permanece pendiente por instrucción del usuario.
