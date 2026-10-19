# Registro de implementación

Actualización: 2026-10-19. Objetivo activo; el alcance obligatorio aún tiene verificaciones y componentes pendientes en REQUISITOS.md. No se declara aptitud para producción.

## Entorno aislado

- Repositorio inicialmente vacío, rama codex/hospitality-suite. Primer commit fd352d2.
- Bench: /home/frappe/benches/hospitality-bench. App enlazada al repositorio Windows. No se modifica el núcleo ni se migran sitios ajenos.
- Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, MariaDB 10.11.14, Node 24.18.0.
- hospitality.localhost en http://localhost:8086/app/hospitality-reception; sitio adicional hospitality-clean.localhost instalado desde cero con la versión ampliada.
- Redis separados 13001/11001; Socket.IO 9001; worker y scheduler activos. Se verificaron trabajos expire_property terminados por el worker.
- tools/run_dev.py arranca los procesos del bench de pruebas de forma repetible y guarda PID/registros en .hospitality-run. El servidor web quedó independiente de la sesión de herramientas; --restart-web se verificó y /login responde HTTP 200. Tras editar Python debe reiniciarse ese servidor (--noreload). tools/bootstrap_wsl.py admite otro sitio hospitality-*.localhost sin reutilizar bases existentes.
- Claves Administrator en .hospitality-setup.json y .hospitality-clean-setup.json, dentro del bench, con modo 600. Usuarios ficticios y sus claves solo en private/hospitality-demo-users.json del sitio. No copiar secretos a Git.

## Implementación alcanzada

26 DocTypes nativos HS, once Pages, sidebar propia y assets esbuild. Reservas, grupos, retenciones, modificaciones cotizadas, entrada, segmentos, extensiones, cambios tarifarios, folios compartidos o separados, salida, limpieza, inspección, mantenimiento, consumos y stock estándar.

Contabilidad mediante Sales Invoice, Payment Entry y Journal Entry: anticipos reales, conciliación antes/después de facturar, garantías separadas, devoluciones, notas de crédito, turno y arqueo, vuelto y multimoneda. Venta directa con factura, cobro y una salida de stock; devolución completa estándar. No se escribe GL Entry, Payment Ledger Entry ni Stock Ledger Entry directamente.

Configuración por establecimiento, pagadores/crédito, políticas, temporadas, tarifas negociadas, camas extra, usuarios/roles, selección de series y formatos. Customer/Contact/Address estándar para registro de huésped y tabla de acompañantes validada.

Cierre diario, reportes operativos/KPI, conciliación hasta documentos, exportadores XLSX/PDF, nueve formatos de impresión. Portal opcional desactivado con cupo compartido, retención/caducidad y firma. Proveedores externos siguen sin configurar; las simulaciones nunca liquidan pagos.

## Pruebas ejecutadas

- Batería en instalación adicional limpia: 65 aprobadas (54 integración + 11 puras), con before_tests y demo explícita reproducible. La instalación limpia detectó opcionales numéricos None y se corrigió su validación/default.
- Ampliación financiera: 17 pruebas financieras aprobadas, incluidas factura y pago creados directamente con controladores ERPNext, sus cancelaciones y notificaciones por usuario.
- La batería conjunta incluye horas reales de motel, bloqueo de mantenimiento, retorno USD con diferencia de cambio, retiro idempotente, pagos combinados NIO/USD y rechazo de anticipo tras salida.
- Concurrencia real bajo REPEATABLE-READ: exactamente una confirmación para habitación vacía y para último cupo de categoría. La primera ejecución descubrió snapshot obsoleto; se corrigió con lecturas actuales FOR UPDATE después de bloquear establecimiento e idempotencia.
- Migaciones versionadas conservaron la reserva previa y reconstruyeron sus líneas/snapshots sin alterar importes contables.
- Cortesías y descuentos se representan en líneas estándar, conservando referencias a cargos/ajustes. No se activa silenciosamente permitir tarifas negativas en Selling Settings. Cortesía ocupa con ingreso cero; prueba de impuesto incluido confirma neto para ADR.

## Evidencia de Pages

Reserva kh48obir08, estancia agp2lri219, habitación M101, todos ficticios:

1. Reserva y entrada desde Page, alojamiento C$450.
2. Agua entregada desde Consumos: inventario 100 → 99, cargo C$30.
3. Extensión cotizada por una hora: adicional C$150; saldo C$630.
4. Usuario cashier registra C$630, recibido C$700, vuelto C$70. Payment Entry ACC-PAY-2026-00001 y factura ACC-SINV-2026-00001.
5. Arqueo 63 unidades de C$10, cierre sin diferencia.
6. Usuario receptionist registra salida con saldo cero; M101 queda sucia y se genera tarea.
7. Usuario housekeeping inicia, completa cuatro puntos y solicita inspección.
8. Usuario supervisor inspecciona y libera; cero pendientes.

Capturas 01 a 06 en docs/evidence. Se eliminaron las dos barras de navegación simultáneas usando hide_sidebar de Page en Frappe 16. La captura 06 acredita M101 nuevamente limpia. Se detectaron detalles de presentación (símbolo de moneda en denominaciones, botón de inspección visible a limpieza, etiquetas técnicas) y se corrigieron en los assets actuales.

## Ampliación: operación, recuperación y móvil

La última batería conjunta tiene **79 aprobadas** (68 integración + 11 puras). Hay 28 DocTypes y once Pages. Se probaron facturas externas con todos los ajustes, rechazo de cargos revertidos, conciliación inversa, medio histórico inmutable y precisión monetaria 0/3.

Mantenimiento incluye responsable validado, repuestos con Stock Entry, costo derivado, devolución autorizada, evidencias privadas y resolución de novedades/objetos. Pasaron cuatro pruebas; limpieza no recibe los costos de impresión. Se probaron envío, recepción y pérdida de ropa con stock real. La Page registró un repuesto para M102, costo C$10. La impresión actual se generó y revisó en una página. Faltan equipo y reposición.

Servicios incluidos conservan cantidades aceptadas, reservan cupo desde solicitud, entregan sin otro cargo y con stock único. Cancelación/devolución restituyen cupo; extensión añade beneficios por noche y cambio de habitación no duplica. Pasaron tres pruebas; la configuración/entrega incluida en navegador queda pendiente.

Se creó otra compañía en la prueba y se combinaron HS Receptionist, Stock User, Accounts User y Sales User. Se rechazaron compañía/establecimiento ajenos, Bin/almacenes no asignados, Stock Entry cruzado y RPC de stock/saldo global. Los usuarios ajenos a HS mantienen controles estándar.

worker_recovery ejecutó un job RQ que expiró una retención y falló: rollback conservó retención/asignación. El job productivo siguiente terminó y liberó cupo. La reapertura del último día exige autorización/motivo y conserva el cierre anterior.

Circuito hotel en Pages: reserva s9tit5ss4j, estancia sa48191j91, H101; dos noches C$3,000, agua C$60; anticipo C$500 y pago C$2,560, factura ACC-SINV-2026-00002, pagos ACC-PAY-2026-00002/00003. Salida con saldo cero, arqueo C$3,060 cerrado y limpieza/inspección móvil terminadas. Se corrigió una captura anterior al cambio de fila sincronizando controles numéricos antes de leer/enviar el diálogo; el cierre se repitió con el conteo recién escrito y sin diferencia.

Panel lateral verificado 1024×768 y 390×844. Tablas como fichas y conexión visible en móvil. El contador bajó 47 h 59 min → 47 h 58 min sin cambiar referencia del servidor ni recargar (countdown.json). Capturas 07 a 12.

Respaldo Bench con archivos restaurado en **hospitality-restore.localhost**, DB hospitality_restore, conservando conexión/identidad del destino y clave de cifrado del origen. Antes/después de migrate: **52 tablas, 295 filas idénticas**, SHA-256 3126e6dacf105ff2ec0b3982e4f852f9affd5e5070f8e8d5e1a7d0425bdebe50. Scheduler del destino pausado. El respaldo contiene el hotel aún activo antes de la salida posterior del sitio principal. Referencia completa privada en el bench; resultados sin credenciales en evidence. Pendientes actuales en PENDIENTES.md.

## Ampliación: tesorería y abastecimiento

31 DocTypes y once Pages. Batería conjunta: **91 aprobadas** (80 integración + 11 puras). Egresos documentados y pagos a proveedores reducen el efectivo esperado; cuentas y documentos son nativos. Liquidación de tarjeta conserva el bruto, snapshot, parciales, comisión, retención, neto e histórico de cambio; admite liquidación de devolución de salida. Se verificaron redondeo final, cancelaciones, prohibición de anular origen con dependientes y USD sin residuo en compensación.

Compras usan Purchase Order → Purchase Receipt parcial → Purchase Invoice sin update_stock → Payment Entry. Almacenes/proveedores asignados, clasificación de artículos, mínimos Item Reorder, traslados/reposición, limpieza/merma y Stock Reconciliation con conteo vigente. Reporte de movimientos proyecta Stock Ledger Entry con cantidad, valor, centro de costo y documento de origen. No hay libro paralelo. Los roles HS combinados con Accounts User no permiten a limpieza ver Customer/Contact/Address ni sus archivos; las notificaciones de esos maestros también se limitan por usuario.

En Page, supervisor abrió C$500, egresó C$20 (ACC-JV-2026-00001), compró dos sábanas × C$50 (PUR-ORD-2026-00001, MAT-PRE-2026-00001, ACC-PINV-2026-00001) y pagó C$100 (ACC-PAY-2026-00004). Venta directa de agua C$30 por tarjeta (ACC-PAY-2026-00005), stock 96→95; liquidación ACC-JV-2026-00002: gasto C$2.90, retención C$0.30, banco C$26.80, compensación cero. Turno 3ri45vs2lc cerrado con C$380 y diferencia cero. Evidencia 13/14 y finance-stock.json; todo es sintético/local.

Se corrigió el diálogo genérico de Frappe 16: sincroniza controles numéricos y valida una sola vez antes de enviar. El doble get_values refrescaba un requerido cuyo modelo todavía estaba vacío y perdía el valor recién escrito. Se verificó guardado inmediato y arqueo recién editado. El objetivo sigue activo con pendientes explícitos, sin afirmar aptitud para producción.

## Ampliación: equipos, evidencia y conexión

32 DocTypes y once Pages; última batería **95 aprobadas** (84 integración + 11 puras). HS Equipment conserva ubicación e identificación operativa, con Asset estándar opcional asignado a la misma compañía/establecimiento. Su vínculo es único y no se cambia tras registrar mantenimiento. Las órdenes por equipo no se solapan; una orden sin habitación no crea Allocation. El bloqueo de una habitación sigue rechazando reservas conflictivas y no las cancela. Se probaron Asset nativo, duplicados, alcance, cambio de ubicación con órdenes pendientes y proyección mínima del técnico.

Circuito de Page: equipo hfj7aq41pd (BOMBA-UI-001), orden hr3a78j3od sin habitación, responsable maintenance, evidencia privada 4166ba4f19 y finalización autorizada por supervisor. Objeto jpjjmvvhon resuelto con constancia. El archivo privado se abrió en la sesión de supervisión; verificación backend permite supervisor/mantenimiento y deniega limpieza. Impresión de equipo revisada en una página y vista 390×844 guardada, capturas 15/16 y equipment.json.

Los archivos conservan el control nativo de propietario/documento, más restricciones por rol/establecimiento también en listados. Se probó permitir a los roles correctos y denegar archivos financieros al propietario con limpieza + Accounts User, además de Payment Entry/GL y maestros personales. La primera implementación devolvía None al no denegar: Frappe 16 lo interpreta como denegación; se corrigió a True y se añadieron casos positivos y listados. La evidencia de mantenimiento usa nivel de permiso separado del acceso operativo de limpieza.

Se detectó que el arranque directo omitía DEV_SERVER, por lo que Desk consultaba Socket.IO sobre web 8086 esperando un proxy. run_dev.py ahora establece esa variable para web. Page comprobada con `window.dev_server=1`, Socket.IO 9001, indicador conectado y sin errores de consola tras recarga. El indicador deriva del socket real; Actualizar también reintenta conexión. Falta todavía el ensayo entre sesiones, corte y respuesta perdida. El objetivo permanece activo.

## Ampliación: retención revisada y outbox de archivos

34 DocTypes y once Pages; batería conjunta **103 aprobadas** (92 integración + 11 puras). Ocho pruebas de retención cubren huésped principal/acompañante vigente, reserva futura, adjuntos recientes, rol y establecimiento, evidencias abiertas/cerradas, retiro de versiones, rollback posterior al retiro de metadatos, referencias compartidas, tres intentos y recuperación autorizada. Una prueba detectó dos referencias File nativas al guardar Attach: se corrigió el fixture para envejecer ambas, conservando el bloqueo correcto de archivos recientes.

Gerencia muestra candidatos, motivo, campos/adjuntos exactos y confirmación explícita; supervisor no recibe esa acción. Configuración permite 0 días para desactivar y hasta 36500. La revisión de navegador se detuvo antes del borrado final; el helper de desarrollo aprobó el fixture ficticio desechable UX-RET-001 mediante el mismo servicio autorizado. Ejecución 62e15kfojm aprobada por manager, worker RQ real Finished, un intento, dos referencias eliminadas y bytes ausentes solo después del commit. No cambió ningún ledger. Capturas 17/18 y privacy-worker.json. No hay errores de consola en esta revisión.

Se detectó que RQ captura el usuario que encola: el job privado de disposición se encola como servicio del sistema y restaura inmediatamente al gerente; la aprobación conserva manager. run_dev.py permite reiniciar el worker validando PID/comando/directorio. La política no elimina nombres, contactos, contabilidad, descripciones libres ni respaldos; no se presenta como anonimización integral. El objetivo sigue activo con pendientes de transporte, Pages y reversión documentados.

## Ampliación: transporte y reintento tras commit

Tres sesiones Socket.IO autenticadas y reales: dos con usuario exclusivo del hotel y otra exclusiva del motel. No hubo eventos antes del commit ni tras rollback; las dos autorizadas recibieron la invalidación property y la tercera recibió cero eventos. Se cerró un transporte, se confirmó otro cambio, se reconectó y bootstrap recuperó el cambio perdido; un evento posterior volvió a llegar. transport-sessions.json conserva resultados sin cookies/credenciales.

Tres pruebas JS verifican que una respuesta vieja no sustituye otra propiedad, un fallo viejo no borra la carga nueva y una invalidación durante una mutación fallida vuelve a consultarse. La Page ahora conserva actualizaciones pendientes, ignora respuestas obsoletas y desactiva el selector de propiedad durante la mutación. El diálogo captura el fallo de red, mantiene la misma referencia y permite reintentar.

Proxy local 8087 descartó la primera respuesta exitosa de la venta ficticia UX-NET-001 después de que Frappe confirmó su transacción. La Page mostró Sin confirmación del servidor. El segundo envío conservó clave y carga y devolvió exactamente el mismo resultado: factura ACC-SINV-2026-00004, pago ACC-PAY-2026-00006 y stock MAT-STE-2026-00007 únicos. Agua 95→94, C$30. Capturas 19/20 y network-sale-sale.json.

La devolución desde Page creó nota ACC-SINV-2026-00005 y pago de salida ACC-PAY-2026-00007, anuló el movimiento de stock y restituyó 95 unidades. El aviso estándar informativo de ERPNext sobre la nota se mostró y se cerró; documentos y saldos quedaron correctos. Turno a756ko5a9j arqueado/cerrado C$0 sin diferencia. Captura 21 y network-sale-returned.json. Se detuvo el proxy.

Se detuvo exclusivamente Socket.IO aislado verificando PID/comando/cwd: Page mostró Sin tiempo real. Se reinició mediante run_dev.py y Actualizar mostró conexión y una referencia de servidor nueva. Capturas 22/23. Esto no afirma persistencia de la clave tras recargar completamente el navegador. Backend conserva 103 pruebas aprobadas; las tres pruebas JS pasan por separado. El objetivo sigue activo con Pages/configuración/portal y reversión pendientes.

## Ampliación: recorrido grupal y edición nativa de tablas

Reserva ki589mj6qt, marcador UX-GRP-001: dos habitaciones sin asignar, ocupantes 2/1, una noche C$3000. Modificación en Page a dos noches C$6000 conservó ambas solicitudes y liberó las asignaciones anteriores. Entradas H102/H103 desde solicitudes numeradas y con principales H1/H2; H3 acompañante de H102 guardado y reabierto.

Cuenta empresarial compartida, cliente nativo Company ficticio creado mediante fixture explícito demo.group_payer. Ambos alojamientos pasaron a ese folio y el consumo de agua quedó en cuenta personal H102. Desde Caja se cobraron empresa C$6000 y huésped C$30: ACC-SINV-2026-00006 con dos líneas y ACC-SINV-2026-00007 con una, Payment Entries 00008/00009. Todos los saldos cero, una salida de inventario MAT-STE-2026-00008. Turno qnjrtadd6h cerrado C$6030, contado 603 × C$10 y diferencia cero. Ambas salidas desde Page dejaron reserva Completed, cero asignaciones activas y dos tareas de limpieza pendientes. Capturas 24–30 y group-*.json.

La prueba detectó que un editor numérico de una fila podía perder lo recién escrito al refrescar otra fila. El diálogo registra la entrada antes del refresco, mantiene el modelo de la fila y toma todos los valores antes de esperar validaciones; no vuelve a enviar controles ocultos sin editar. Se repitió la edición rápida 2 personas → Añadir fila y se verificó 2/1 en la base. Arqueo de dos valores editados y checkbox de acompañante también quedaron correctos. Cinco pruebas JS pasan: tres de transporte y dos de editores/acciones válidas del grupo. La batería Frappe sigue en 103 aprobadas; no se modificó lógica financiera durante este recorrido.

Reservas separa vigentes e historial. La entrada grupal distingue solicitud/número/ocupantes, preselecciona la última pendiente y conserva el principal. Una reserva parcialmente ingresada no ofrece cancelación/modificación/no presentación que el servidor rechazaría; el pagador actual se conserva al modificar. La asignación física y facturación se revisaron también a 1280×900. Quedan planes, asistente/portal y auditoría/reversión documentados; el objetivo permanece activo.

## Ampliación: planes, extensión conflictiva y portal

Desde Configuración se guardaron/reabrieron series y formatos y se creó Plan con agua UX-PLAN-001: C$1600, prioridad 30, válido el 19/10/2026 y una unidad por estancia. Entrada H104, agua entregada C$0 mediante MAT-STE-2026-00009 y sin segundo cargo; una segunda unidad fue rechazada. Los errores de negocio de jqXHR se muestran como tales, sin sugerir un reintento incierto de red.

La reserva posterior defpdsutts en H104 quedó intacta al rechazar una extensión hasta el mediodía del 20. Cambio a H105 con ajuste cero, dos segmentos contiguos y H104 sucia con tarea. Extensión posterior hasta el 21/10 09:30 cotizada C$1500 y confirmada: estancia 9mfspa61cd C$3100, dos cargos de alojamiento y un solo beneficio/stock. La estancia continúa abierta, sin cobrar; no se declara salida de este fixture. Capturas 31–36 y plan-*.json. Las horas del asistente indican la zona del establecimiento, incluso si el usuario elige otra zona en Frappe.

Portal habilitado expresamente para el hotel de pruebas: visitante Guest creó guqk0ou0hv, C$1500 para 23–24/10. La Page firmada mostró retención hasta las 09:55, sin datos de contacto ni pago. Recepción convirtió la solicitud en i99qbv6dtl, canal Web, una habitación por asignar, una asignación activa y cero pagos/estancias. El hotel volvió a portal_enabled=0. Capturas 37/38 y portal-converted.json. No se envió correo a un proveedor real.

El navegador detectó que el controlador de la confirmación tenía guiones; Frappe busca el módulo con guiones bajos. Se renombró a hospitality_confirmation.py y se añadió render real de TemplatePage a la prueba de firma/conversión, incluyendo vencimiento y ausencia del correo. Dos pruebas del módulo pasan. Dos pruebas JS del portal cubren edición durante cotización y pérdida de respuesta con referencia/datos conservados; seis de Desk incluyen el rechazo de negocio frente al fallo de red. La última batería completa anterior a esta corrección conserva 103 aprobadas y se repetirá en la auditoría final.

Recepción recibió No permitido al abrir Configuración. Administración vio el asistente de usuarios con nueve roles en español; se cerró sin conceder accesos. Alta de usuario y rechazo de un gerente ya están probados en integración. Capturas 39/40. Continúan inventario/ropa móvil y auditoría/restauración/reversión final.

## Ampliación: inventario, corte y recuperación final

Nuevo almacén Lavandería UX-INV-001 creado en Page, traslado de dos aguas, conteo revisado 2→1 mediante Stock Reconciliation y dos GL Entry. Limpieza envió dos sábanas, recibió una y documentó pérdida de una con tres Stock Entry; saldos nativos: agua 91/1 y sábanas 1/0 por almacén operativo/lavandería. Formulario/resultados revisados a 390×844; capturas 41–44 e inventory-ui.json.

La auditoría detectó close_time guardado sin uso en el resumen. Se corrigió el período por fecha operativa [D corte, D+1 corte), con zona y límites independientes para DST. Prueba nativa: estancia motel 06:15–07:15 y corte 06:45 produce 0.5 horas, mientras calendario completo produce 1; el cierre conserva ese período. Se rechazan 25:00 y zona adjunta al corte; Frappe get_time por sí solo envuelve duraciones mayores a 24h. Dos pruebas puras cubren medianoche/año y días de 23/25 horas. El avance de fecha es manual al confirmar, no automático por reloj. Gerencia, revisión e impresión muestran el período; controles Time normalizan la hora 6:45 a 06:45 para HTML.

Webhook sintético firmado/repetido comprobado por el receptor real con contexto HTTP: un registro Received, CVV redactado y cero efectos financieros, aunque el cuerpo de prueba diga paid. No se activó proveedor. Batería final: 107 aprobadas (94 integración + 13 puras), siete de Desk y dos de portal. Código 9ebf30a. Las dos carreras reales finales tuvieron una confirmación y un rechazo; se cancelaron las reservas de ensayo con auditoría.

Respaldo nativo fresco con cuatro componentes, protegidos modo 600. El helper esperaba tgz y el respaldo produjo tar; se añadió selección inequívoca y preflight antes de reemplazar la base aislada. Restauración correcta, luego migrate, reversión a 8152ac5 en checkout archivado independiente y redespliegue 9ebf30a. El redirector del editable impide usar solamente PYTHONPATH; el launcher carga explícitamente el paquete archivado antes del bench helper, sin cambiar enlaces ni núcleo. Las 70 tablas/866 filas y un archivo privado coinciden por SHA-256 en todas las etapas y tras navegar recepción/H105/gerencia. La verificación del origen también coincide. No acredita reversión arbitraria de cambios destructivos de esquema.

La copia se sirvió temporalmente en 8088 y se detuvo al terminar. Se comprobó lectura/API; Socket.IO del bench está configurado para el servicio principal 8086, no se reconfiguró para esta copia. El destino conserva scheduler pausado. El worker principal terminó limpiamente su trabajo de índice al reiniciarse; después se arrancó un worker nuevo. Capturas 45/46 y recovery-*.json.

El objetivo sigue activo: la revisión siguiente detectó límites de 500/1000 filas e insuficientes dimensiones/fechas en reportes, además del historial de acompañantes. Se registraron como F17c y PENDIENTES.md; las pruebas existentes no acreditan todavía esa parte del alcance.

## Ampliación: consultas completas e historial de acompañantes

paging.permitted_all consulta bloques estables de 500 mediante get_list y sus permisos; la proyección operativa ya no descarta la cola del historial. report_page y guest_history presentan páginas de 50, total y controles, con límite explícito máximo de 200 por página. Las exportaciones usan el conjunto completo. El historial incorpora HS Stay Guest y exige lectura del huésped/alcance del establecimiento; no devuelve otros nombres ni identificaciones.

Cuatro pruebas nuevas: 1105 eventos en todos los segmentos y XLSX, 610 asignaciones de calendario, principal/acompañante con denegación de otro establecimiento y bloqueo completado que conserva hora de auditoría pese a una edición posterior. El calendario mantiene los mantenimientos terminados y su fin procede del evento inmutable Maintenance Completed; la retención de evidencia no amplía el bloqueo histórico. KPI usa esa misma referencia.

Batería conjunta: 111 aprobadas (98 integración + 13 puras); siete de Desk y dos de portal siguen aprobadas. Un primer fallo al crear el usuario de prueba procedió de Redis 13001 detenido; se arrancaron los servicios aislados y se repitió la prueba completa sin fallos. Compilación realizada. Page Auditoría: 51–100 de 142 registros, con retorno/foco al encabezado; H3 muestra H105 como principal y H102 como acompañante. Capturas 47/48. history-ui.json acredita 142 filas de XLSX y todos los identificadores en PDF de 10 páginas.

La revisión visual de primera/última página de ese PDF detectó partición de fila y falta de encabezado repetido. El runtime global instalado es wkhtmltopdf 0.12.6 sin Qt parcheado; queda resolverlo dentro del bench de pruebas y repetir la inspección. Las dimensiones de reportes y fechas de llegada/salida siguen pendientes. El objetivo no se cierra con estas pruebas parciales.

## Ampliación: impresión extensa con Qt parcheado

Paquete oficial 0.12.6.1-3 Jammy amd64 extraído dentro del bench, SHA-256 fijado 4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15. Dependencias y versión with patched qt comprobadas en Ubuntu 24.04. No se instala globalmente ni se cambia el núcleo. Web/worker y helpers seleccionan ese runtime; el servidor temporal también quedó preparado. La exportación PDF rechaza detección incompatible en lugar de devolver un archivo defectuoso.

Qt parcheado respeta el límite de filas y repite encabezados. Al desactivar smart shrinking conforme a Frappe, se detectó otro desbordamiento de ancho: se corrigió con table-layout fixed y ajuste de palabras. Se añadió pie [página]/[total]. Las 18 páginas del reporte de 142 eventos se renderizaron/revisaron sin cortes ni columnas fuera de página; el texto contiene todos los identificadores y ambos endpoints de función/HTTP devuelven el mismo conjunto. Capturas 49/50, history-ui.json, history-pdf-qa.json y pdf-runtime.json.

Se regeneraron diez comprobantes y conciliación/XLSX con el runtime nuevo; diez páginas legibles y sin referencias internas de líneas en factura. qa_exports conserva fixtures explícitos de impresión y actualiza su revisión de cierre, por lo que esa repetición es posterior al checkpoint de recuperación de 70 tablas/866 filas. No se interpreta el hash anterior como comparación después de estas nuevas operaciones ficticias. Manifest nuevo en patched-native-exports-manifest.json. Batería conjunta: 112 aprobadas (99 integración + 13 puras), incluida denegación de PDF incompatible; siete de Desk y dos de portal se conservan. Continúan filtros/dimensiones/fechas y revisión completa de la especificación.

## Ampliación: dimensiones y presentación operativa de reportes

Se implementaron compañía/establecimiento autorizados, fechas de llegada/salida/registro, límites locales de período, categoría/habitación/canal/usuario/turno y filtros particulares. Las opciones no aplicables se rechazan. Disponibilidad reutiliza el barrido de reservas y estancias, incluyendo cupo sin habitación; cuentas pendientes descarta saldos cero. Los cargos y ajustes conservan atribución a la habitación al registrarse; las notas de crédito usan su origen. Se incorporan ventas directas y devoluciones una sola vez y totales por dimensión/moneda.

La petición de legibilidad añadió perfiles de presentación: vista operativa predeterminada con nombres de artículo, habitación, huésped, cuenta, responsable y estados; referencias internas en una vista técnica opcional. Se conserva la identidad original en la API y en las acciones. PDF/XLSX siguen la selección. Los reportes anchos tienen secciones de columnas con referencias repetidas; el operativo de producción reúne diez registros en una página y no contiene hashes ni códigos HS-DEMO. Reservas muestra huésped/fecha y respeta modo discreto.

Diez pruebas nuevas de integración, batería completa de **122 aprobadas (109 integración + 13 puras)**, nueve de Desk y dos del portal. Se amplió precisión financiera para verificar Excel con tres/cero decimales sin cambiar el valor almacenado y moneda base explícita. Ambas carreras reales vuelven a tener una confirmación y un rechazo con REPEATABLE READ. El recorrido de Gerencia comprobó agrupación, fechas/canal Web y disponibilidad a 390×844; los calendarios nativos de fecha conservan ISO sin depender del formato de texto de Frappe.

`report-dimensions.json` acredita por HTTP el conjunto/exportación completa, H104 C$1600 frente a extensión H105 C$1500, devolución sin duplicación, cupo 8 y rechazo de H104 en el intervalo reservado. Cinco combinaciones de exportación: operativo legible, técnico, agrupado, disponibilidad de compañía y llegadas. Las referencias técnicas aparecen completas en cada sección; la vista operativa las oculta expresamente. Capturas 51–56 y pruebas normalizadas acompañan el cambio. Sigue pendiente la auditoría punto por punto del alcance y la recuperación del código/datos de la revisión final; no se cierra el objetivo por esta ampliación.

## Auditoría de reportes mínimos y matriz detallada

Se contrastó la sección 13 con código y datos. La penalización de cancelación/no presentación ya existía como Sales Invoice, pero no se proyectaba en Producción por carecer de estancia. Ahora se incluyen sus líneas y las demás facturas nativas sin representación, con devoluciones reales y sin duplicar cargos/ventas directas. El evento de presentación fija fecha operativa/actor; para documentos anteriores sin evento se conserva fecha contable disponible. Los totales se separan por moneda. Notas de crédito POS nativas conservan update_stock, mientras los consumos operativos siguen el circuito Stock Entry.

Cancelaciones/no presentaciones usa la fecha de decisión o vencimiento inmutable, con alternativa explícita de llegada/salida/registro. Expiración de retención también conserva fecha. Muestra motivo y penalización/factura/estado. Productividad de limpieza agrupa tareas y duración por responsable, documentando la espera de inspección y excluyendo del tiempo tareas sin duración positiva. Arqueos por moneda conserva snapshot de cierre y no inventa conteo en turno abierto ni asientos para ocultar diferencias. Motel distingue entradas de rotaciones por habitación comercializable; se reforzaron ticket/ingreso por hora y ADR/RevPAR positivos.

Tres pruebas nuevas, además de ampliaciones a ciclo de vida e indicadores: **125 aprobadas (112 integración + 13 puras)** y **9 de Desk + 2 del portal**. Compilación de assets y reinicio web/worker ejecutados. HTTP verifica los 24 reportes en las dos propiedades y cuatro PDF/XLSX; ocho páginas renderizadas/revisadas. Capturas 57–59 acreditan las tres vistas en Gerencia, sin modificar operaciones desde el navegador. Los fixtures de penalizaciones y POS pertenecen a transacciones de pruebas revertidas, no al sitio de demostración.

El inventario exacto añade AUDITORIA_ESPECIFICACION.md y specification-audit.json con fuente/huella/línea original: 201 elementos enumerados, diez cláusulas expresas y siete fases, 218 entradas. Se verificaron quince de reportes/indicadores; dos tienen revisión parcial (catálogo superior a 500 artículos y cobertura de textos traducibles), y 201 esperan contraste individual. R no significa función ausente: la matriz resumida conserva los circuitos ya acreditados. El objetivo sigue activo y la restauración del código/datos de la revisión final aún debe repetirse después de resolver el resto.
