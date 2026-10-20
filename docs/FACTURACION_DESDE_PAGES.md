# Facturar una cuenta desde Pages, versión 0.6.1

Desde **Recepción → Ver estancia → Facturar cuenta**, un usuario autorizado para finanzas elige la cuenta, pulsa **Revisar factura** y confirma **Emitir factura**. La revisión destaca el total exigible y presenta neto, impuestos, anticipos y saldo de la nueva factura. Si existe redondeo, distingue el total anterior al redondeo. Incluye las noches programadas y los cargos pendientes de esa cuenta.

La estancia permanece activa. Emitir una factura no registra una salida, un cobro, un turno ni una limpieza. Una cuenta de importe cero también puede facturarse; el servidor distingue explícitamente una cotización válida de una cuenta sin cargos nuevos. Si no hay cargos nuevos, la interfaz muestra un aviso y no emite otra factura.

La revisión es breve y utiliza el comportamiento común de los formularios: cabecera y acción visibles, contenido acotado y botón de ancho completo en móvil. El borrador queda suspendido mientras se revisa; cerrar la revisión permite volver a él. La confirmación muestra total facturado, saldo pendiente y enlace a la factura estándar. Los códigos legales de factura se conservan como enlaces de comprobación; las cuentas y los clientes se seleccionan por su nombre.

## Cotización y registro estándar

`preview(action="invoice")` requiere permiso financiero y calcula una Sales Invoice transitoria con los controladores de ERPNext. No la guarda, consume serie, genera cargos programados ni aplica conciliaciones. Se determina expresamente la moneda de la cuenta del cliente; la moneda del saldo puede diferir de la moneda de factura. Los anticipos y garantías disponibles se asignan hasta el total exigible, respetando su origen, pagador, compañía y cuenta.

La revisión devuelve una huella de cuenta, cargos, valores calculados, líneas, impuestos y anticipos. La confirmación vuelve a calcularla antes de liquidar programaciones. Si cambió un cargo, un anticipo, una configuración tributaria o el resultado, se rechaza esa revisión. La Page conserva la misma clave de petición al reintentar una respuesta perdida. El contrato anterior sin huella sigue disponible para sus consumidores autorizados; esta Page siempre la envía.

La emisión presenta una única Sales Invoice estándar y enlaza cada cargo con su línea. Los efectos contables pertenecen a ERPNext. Consultar una cuenta ya facturada no aplica automáticamente nuevos anticipos ni modifica conciliaciones históricas; esa operación tiene su flujo financiero separado.

## Pruebas ejecutadas

La batería conjunta de esta revisión aprueba **220 casos: 206 de integración y catorce puros**, en `hospitality-acceptance.localhost`. Los nueve casos de `test_invoice_page.py` verifican cotización repetible sin escrituras, factura sin cobro/salida, importe cero, revisión obsoleta por cargo o maestro tributario, anticipo de 500 y saldo de 2500, permisos/contexto, impuesto incluido y consulta sin cargos nuevos. La primera ejecución parcial detectó una importación ausente de `canonical`; se corrigió y se repitieron los casos antes de ejecutar la batería conjunta aprobada.

Aprueban **41 regresiones JavaScript: 39 Desk y dos portal**. Las tres nuevas prueban cero válido, contenido escapado, cuenta/huella/clave de confirmación, reintento tras respuesta perdida y guardias de rol/cuenta sin cargos. Estas pruebas no representan 41 recorridos de navegador.

En el navegador real, con gerente y datos ficticios:

- Se registra desde Pages una estancia de dos noches a precio cero, se revisa en 390×844 y se emite su factura. La estancia sigue activa y sus dos cargos quedan facturados.
- Se prepara por API una segunda estancia de una noche por C$1250; su revisión y emisión se realizan desde Pages. La confirmación muestra total y saldo de C$1250, conservando la estancia activa.
- Se vuelve a revisar la primera cuenta y aparece el aviso de que no hay cargos nuevos, sin otra emisión.

`billing-items-ui.json` verifica dos estancias activas, dos facturas presentadas con totales/saldos 0 y 1250, tres cargos facturados y cero turnos, pagos operativos, Payment Entry, Journal Entry, limpiezas o cierres diarios. La entrada positiva por API es un fixture identificado, no una entrada acreditada desde Pages. El servidor temporal carece de Socket.IO propio y este recorrido no acredita tiempo real ni la aceptación completa por todos los roles.

Capturas: **106** acción Facturar cuenta; **107** revisión cero en móvil; **108** cuenta cero facturada con estancia activa; **109** revisión de C$1250 sin cobro; **110** confirmación con total, saldo y estancia activa.

## Conservación y alcance

Se respaldaron ambos sitios con archivos, se migraron y se construyó el bundle. `billing-ui-upgrade.json` compara todas las columnas de 72 tablas con Version: 1191 filas y dos archivos privados principales, 195 filas de aceptación, sin cambios de negocio. Después del recorrido se cerró sesión, se detuvo 8089 y se restauró el respaldo mediante Bench. `billing-ux-restored.json` compara las 71 tablas/185 filas de aceptación y acredita cero estancias, facturas y pagos. `billing-final-state.json` conserva las guardias y servicios; web y worker se reiniciaron con esta revisión.

La diferencia de interfaz detectada en 0.6.0 está resuelta. S00-02 y F22 pasan a **I**, pues el texto completo exige aceptación de todas las tareas habituales por rol; F22b acredita únicamente este flujo. La auditoría conserva las mismas 218 entradas: 83 V, ocho I, cero P y 127 R. Continúan el contraste restante, límites/reintentos, traducciones, demo operativa, recorrido combinado de recepción/caja, sesión contable y recuperación de la revisión final. La sincronización con plataformas de reservas permanece pendiente por instrucción del usuario. El objetivo continúa activo.
