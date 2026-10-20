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

## Catálogo completo desde las Pages

La auditoría del selector encontró que bootstrap cargaba 500 Item y las opciones se construían únicamente con esas filas. Se sustituyó por búsqueda nativa de la app, por nombre/código y uso (venta, stock, compra o general), con 50 coincidencias/refinamiento y los mismos permisos de establecimiento/rol. La proyección del maestro Item compartido solo contiene nombres y banderas de uso; no concede lectura de precios, costos o saldos. Los precios siguen sus operaciones/listas/monedas ERPNext.

Ocho selectores de consumos, venta directa, ropa, repuestos, movimientos, conteo, clasificación y filtros utilizan el mismo control. Las respuestas atrasadas se descartan, el cierre invalida consultas y una búsqueda fallida o pendiente impide confirmar. Cambiar el texto conserva explícitamente la selección previa. Los nombres repetidos se distinguen por código; la clave enviada al comando sigue siendo el Item original. Bootstrap conserva 50 opciones iniciales y todos los nombres ya referenciados, incluidos artículos históricos deshabilitados; no descarga todo el catálogo ni recorta las opciones de búsqueda.

Dos nuevas pruebas nativas: 606 artículos, consulta por código y texto con comodines literales, consumo por recepción a C$41.25, entrega sin stock para servicio no inventariable y conservación del nombre después de deshabilitarlo; proyección de limpieza, límites/tipos, Guest y otra propiedad rechazados. Batería conjunta: **127 aprobadas (114 integración + 13 puras)**. Once pruebas de Desk, incluidas dos nuevas de catálogo, y dos del portal: **13 aprobadas**. Assets compilados y servicio principal reiniciado.

La comprobación visual usó hospitality-clean.localhost:8089 y 606 artículos explícitos de prueba; buscó/seleccionó Servicio especial del catálogo (HS-CATALOG-QA-0605), fuera de las primeras 500 opciones. Captura 60 y catalog-ui-selection.json conservan etiqueta/valor. No se envió el consumo desde el navegador ni se crearon movimientos financieros por ese ensayo. Los fixtures de precio/cargo pertenecen a las pruebas revertidas. El catálogo de prueba queda solo en el sitio limpio; el sitio principal conserva sus artículos. La vista temporal no acredita Socket.IO y se detuvo; salud final 8086 activo/8089 cerrado.

La auditoría granular registra 16 V, una I (preparación de todos los textos para traducción) y 201 R de contraste individual. El alcance original, las demás verificaciones y la recuperación final continúan; este cambio no cierra el objetivo.

## Presentación y preparación de traducciones

Se marcaron etiquetas de Pages y portal, errores operativos, explicaciones de precios y nueve comprobantes con los mecanismos nativos de Frappe. El registro de mensajes estáticos permite extraer etiquetas que se resuelven desde diccionarios. El extractor nativo encuentra los mensajes representativos; ese recuento no acredita por sí solo cobertura completa. S01-04 permanece I mientras se revisan los literales dinámicos y secundarios.

Los Select de los diálogos operativos insertan opciones con text(), conservan valores/defaults y distinguen nombres de maestros de etiquetas traducibles. No se cambia el ControlSelect del núcleo. La extensión de planes usa base_explanation y los servicios estructurados; deja de filtrar un prefijo español en texto visible. La clave baño del checklist permanece sin traducir y las traducciones de encabezados Excel reciben la misma protección contra fórmulas que los demás textos.

Dos pruebas nativas con Translation en francés prueban reportes, nombres que coinciden con una etiqueta, importes tipados, comprobantes, checklist y beneficios incluidos al extender. Sus registros/diccionarios se revierten y se limpia la caché. Dos pruebas JS prueban opciones literales, valores, selección, estado deshabilitado y texto con marcado. La comparación estructural conserva los literales de protocolo existentes de ocho fuentes JS.

La primera ejecución completa se lanzó por error en hospitality.localhost, que contiene recorridos UX y carece de la línea de base de los casos: produjo ocho fallos y 41 errores por ocupación, tarifas, referencias y saldos preexistentes. Se corrigió el sitio de ejecución; la batería completa de hospitality-clean.localhost aprobó **129 pruebas (116 integración y 13 puras)**. La ampliación final del checklist volvió a pasar sus dos pruebas dirigidas. Las **15 pruebas JS** pasan. Las operaciones de cada prueba se revierten; no se usa el resultado de la demostración como evidencia de aceptación de la batería.

Se regeneraron los nueve JSON de Print Format desde sus fuentes y migraron ambos sitios. El generador no produjo cambios de esquema, Pages ni permisos. Assets compilados y web/worker principal reiniciados. Se imprimieron nueve comprobantes existentes, sin crear operaciones: ocho PDF coinciden por SHA-256 con sus versiones ya revisadas; mantenimiento se renderizó y revisó. Producción exporta los diez registros legibles en una página y diez filas numéricas en XLSX, sin claves internas ni HS-DEMO. Captura 61 y localization-exports.json conservan la evidencia.

No se ha instalado un idioma completo adicional ni se acredita aún cada requisito de la especificación. La recuperación final y el contraste de los demás capítulos siguen pendientes.

## Auditoría de arquitectura y alta inicial

La revisión de capítulos 1–3 se documenta en AUDITORIA_ARQUITECTURA.md y el inventario de solo lectura architecture-current.json: versiones/commits del núcleo sin modificaciones, base/Python, 34 modelos con campos/opciones/obligatoriedad/unicidad e índices, once Pages con roles y 25 DocTypes estándar utilizados. El inventario no sustituye las pruebas de permisos. La documentación oficial de Pages/transacciones/anticipos se contrasta con las APIs instaladas; no se ofrece compatibilidad con versiones adicionales.

Se encontró que create_property ignoraba la zona/corte al elegir fecha y solo validaba una clave sin registrar su resultado. Ahora setup.create_property serializa en Company (el establecimiento aún no existe), registra HS Request/auditoría y devuelve el mismo resultado al repetir. La clave con otra carga se rechaza. Permite fecha inicial/corte, calcula el default local antes/después del corte y conserva los valores iniciales editables. Las modificaciones posteriores de fecha requieren cierre/reapertura; un round-trip con la misma fecha ISO sigue permitido. El botón de alta también aparece con establecimientos existentes y solo para administración del sistema; al confirmar se selecciona el nuevo.

Cuatro casos nuevos y batería completa en hospitality-clean.localhost: **133 aprobados, 120 integración y trece puros**. Cotización de un establecimiento mixto distingue C$1500 por hotel/C$450 por bloque y comparte la exclusión de habitación. Un primer test consultó por error una columna mode inexistente en reserva; la comprobación correcta lee quote_snapshot y la batería completa posterior pasa. Quince pruebas JS, incluida fecha ISO y corte sin establecimiento previo, pasan. La fecha inicial usa el control HTML de fecha ya empleado en reportes; evita depender de la máscara regional de Date de Frappe. No hay cambio de esquema, roles o índices.

Assets compilados; web/worker del bench principal reiniciados. La Page del sitio limpio creó Establecimiento UX de prueba, Mixto/NIO/Managua, fecha inicial 18/10 y corte 05:30, y lo conservó al recargar. Sus cuentas/plantilla permanecen sin asignar, finanzas deshabilitadas y cero reservas/estancias/cargos/cobros/turnos/documentos nativos. Es un fixture administrativo explícito solo en el sitio limpio, posterior a la batería; capturas 62/63 e initial-setup-ui.json. El sitio temporal no tiene segundo Socket.IO configurado y se detiene al terminar; no acredita tiempo real en esa copia.

La auditoría conserva 218 entradas con la misma huella/texto: **44 V, dos I, dos P y 170 R**. Las 28 nuevas V cubren las obligaciones contrastadas de arquitectura/configuración; no cierran el alcance general. Se explicitan S03-05 (políticas de uso de anticipos/garantías por establecimiento) y S12-05 (facturación/cobros/saldos diferenciados en el snapshot del cierre). S03-06 mantiene contraste parcial de asignación de artículos/servicios, especialmente horas adicionales; S01-04 sigue parcial. La recuperación final se repite después de esas diferencias y el resto de la auditoría.

## Políticas y cierre financiero, versión 0.3.0

Se completan las dos diferencias localizadas. Anticipos/garantías admiten Manual, Approval o Disabled por establecimiento y tipo, con validación de cotización, comando y presentación nativa. La aprobación conserva actor/regla; supervisor no puede quitarla mediante configuración o formulario nativo. La desactivación conserva devoluciones/aplicaciones de fondos anteriores. Se rechaza mezclar cobro de factura y anticipo sin asignar en un Payment Entry. Se reforzó el bloqueo de finanzas deshabilitadas en facturas/pagos nativos.

El cierre conserva ocupación, producción, facturación, movimientos y saldos por moneda, con fechas y fuentes. La factura usa posting_date; los movimientos guardan business_date desde la propiedad bloqueada. El patch solo recupera fechas históricas acreditadas por auditoría y advierte las desconocidas. Las once existentes en la demostración tienen fecha Audit. Facturas/anticipos pendientes usan moneda de la cuenta del cliente. Créditos a favor permanecen separados de facturas sin conciliación. El POS nativo incorpora su dinero real desde GL, neto de vuelto y devoluciones, sin crear otro cobro. Ver resumen y PDF leen la captura conservada. La Page envía una huella al confirmar y rechaza una revisión financiera obsoleta.

La primera ampliación esperaba que ERPNext compensara automáticamente una nota de crédito; se corrigió la expectativa para contrastar factura pendiente 600 y crédito no aplicado 1400 por separado. El mapper POS copiaba el efectivo entregado (100); el fixture devuelve el importe real (60). El caso de moneda extranjera establece primero la moneda contable del cliente mediante factura NIO. Esos ajustes no concilian documentos ni modifican el núcleo.

Durante el archivado se reinició WSL: desaparecieron temporales y procesos Redis/web. Una ejecución sin Redis fue interrumpida y dejó una estancia/factura parciales en hospitality-clean.localhost. Se respaldó su estado con archivos y pausó su scheduler, sin borrar ni ajustar manualmente los libros. Se creó hospitality-acceptance.localhost/base independiente, instaló ERPNext/app y conservó respaldo inicial antes de pruebas. El fixture administrativo UX sigue vacío y con Approval/Disabled; el resto de ese sitio limpio conserva el diagnóstico. before_tests ahora exige sitio designado, Redis disponible y ausencia de operaciones.

La instalación desde cero detectó almacenes iniciales traducidos y un valor predeterminado de compañía heredado por facturas operativas. El seed explícito crea Stores si falta. Las líneas generadas eligen el almacén del establecimiento antes de obtener valores predeterminados; las devoluciones conservan el original. Se probó venta directa como cajero con su propio turno y el recorrido de recepción/caja/limpieza/supervisor. Las primeras ejecuciones del nuevo sitio señalaron ese problema; tres casos dirigidos y la batería final pasan.

Resultado final: **145 pruebas aprobadas (132 integración + 13 puras)** en el nuevo sitio, y **19 JS (17 de Desk + dos del portal)**. Son doce casos nativos nuevos y cuatro JS sobre la base de 133/15. Los movimientos se revierten: la lectura final del sitio de aceptación registra cero estancias/reservas/cargos/cobros/turnos/cierres/facturas/pagos/asientos de diario, con ambos establecimientos de fixture y respaldo inicial.

La migración principal conserva 70 tablas/908 filas y un archivo privado por huella, excluyendo solamente las cuatro columnas nuevas declaradas. La lectura final confirma sus 36 tablas nativas sin cambios, fecha operativa 19/10, núcleos limpios y servicios 8086/9001/11001/13001 activos con HTTP 200. Assets compilados y web/worker reiniciados. El sitio temporal 8089 está detenido y la sesión administrativa se cerró hasta la pantalla Login.

Capturas 64–66 prueban revisión, pendientes y lectura guardada, sin confirmar el día; PDF nativo de dos páginas renderizadas/revisadas. Captura 67 y lectura posterior prueban política guardada/recargada sin habilitar finanzas ni crear operaciones en ese establecimiento. AUDITORIA_CIERRE_POLITICAS.md identifica fuentes y límites. La matriz conserva texto/huella originales: **46 V, dos I y 170 R**. Continúan los servicios/artículos, la cobertura completa de textos, los demás capítulos, POS frente al arqueo, devolución de anticipos aplicados y recuperación final; el objetivo permanece activo.

## Artículos y servicios, versión 0.4.0

Se completa S03-06. El asistente Artículos y servicios selecciona artículos estándar de alojamiento, horas adicionales de motel y horarios de hotel, con nombres actuales y consulta de precio/entrega. Alimentación, minibar, lavandería de huésped y otros servicios utilizan Item e Item Price existentes de la lista del establecimiento. No se añade otro catálogo contable ni inventario. El artículo automático debe ser un servicio habilitado sin stock/activo fijo; motel/mixto con tarifa de horas adicionales requiere asignación. La migración conserva el artículo anterior para propiedades existentes sin crear maestros ni cambiar historia.

Las cotizaciones nuevas conservan las asignaciones y los componentes de motel. La entrada separa alojamiento/horas adicionales; extensión y exceso de salida registran solo incrementos con el artículo aceptado. Cambiar configuración no reescribe cargos anteriores. La reserva anterior sin esas claves mantiene un solo cargo aceptado. Los importes de tarifa conservan su origen y clasificación de alojamiento; no se sustituyen por Item Price. El artículo distinto de horas requiere una unidad que permita fracciones; la demostración utiliza Hour y la factura comprueba cantidades 0.25/0.5/0.25. La asignación anterior al mismo artículo de alojamiento conserva una unidad por cargo. Un cambio a habitación más barata reparte su crédito entre los cargos pendientes de origen, incluidos alojamiento y horas, y factura sin líneas negativas.

Se encontró que el consumo a habitación seleccionaba un precio sin comprobar vigencia. Ahora comparte la selección con venta directa: lista habilitada/de venta/moneda, fechas inclusivas, unidad y pagador. No aplica precios de otro cliente, proveedor, lote o empaque no seleccionado. Un precio del pagador prevalece sobre el general; ausencia/superposición se rechaza antes de crear el consumo. La auditoría conserva la referencia de precio. La consulta del asistente indica que muestra precio general y lista guardada.

Siete casos nativos nuevos prueban artículo distinto, entrada/extensión/exceso/reintento/factura, cambio de configuración, contratos antiguos, tipos/roles/migración y las cuatro clases de servicios con stock único. También prueban precio vencido/futuro/superpuesto y del pagador. La fecha de un fixture de precio caducado se corrigió para respetar valid_from≤valid_upto. Se comprueba además que una tarifa sin establecimiento produce validación obligatoria, sin acceder a una variable de propiedad inexistente. Una prueba pura nueva contrasta componentes/fracciones a precisión 0/2/3; dos JS prueban guardado/versiones y respuestas atrasadas/cierre.

Resultado final, también después de restaurar el sitio: **153 aprobadas (139 integración y catorce puras)**, y **21 JS (diecinueve Desk y dos portal)**. Assets compilados y web/worker reiniciados. La migración principal conserva **70 tablas/911 filas y un archivo privado** con la misma huella, excluyendo solo extra_hour_item.

Gerencia guardó/recargó Hora adicional de motel y consultó agua a C$30 con entrega de inventario (68/69). Recepción cotizó y confirmó cuatro horas de M101 por C$600 (70); la cuenta muestra alojamiento C$450 y horas adicionales C$150 (71). Se exportó y revisó PDF de una página; no se facturó ni cobró en ese recorrido. Una URL local temporal resolvió los assets de wkhtmltopdf y se retiró al restaurar. La sesión salió hasta Login y el servidor 8089 se detuvo, sin segundo Socket.IO configurado.

Se respaldó el sitio de aceptación antes del recorrido y se restauró mediante Bench: sus **70 tablas/185 filas** coinciden exactamente con la línea de base, sin estancias/facturas/cobros de UX. La batería final vuelve a pasar sobre esa restauración y la comparación de las setenta tablas sigue idéntica después de las pruebas. El seed explícito evita guardar una propiedad cuando su almacén no ha cambiado. Un recibo privado de restauración vincula la verificación al respaldo realmente restaurado. El principal conserva sus 36 tablas nativas, fecha operativa y HTTP 200. Esta recuperación acotada no sustituye la recuperación final del conjunto de demostración con archivo privado y reversión de código.

AUDITORIA_SERVICIOS.md y las evidencias service-* identifican cada contraste. La matriz mantiene 218 entradas/texto/huella: **47 V, una I y 170 R**. Permanecen los textos pendientes de S01-04, los demás capítulos y controles financieros/recuperación final. El objetivo sigue activo.

## Arqueo y POS nativo, versión 0.4.1

Sales Invoice con is_pos ya aporta al arqueo el dinero real de sus cuentas de pago/vuelto desde GL Entry, con signo y moneda. Caja y cierre diario comparten la proyección; no se crea otro HS Payment ni Payment Entry. Se exige turno abierto/propietario autorizado, medio inequívoco y referencia bancaria según configuración. Se preservan los medios utilizados, incluso después de cancelar; una factura histórica sin turno queda en conciliación. Un crédito en otro turno no modifica el conteo del original y una cancelación posterior muestra la diferencia contra ese conteo.

El Supervisor no podía aprobar un faltante con la autorización general reservada a gerencia. cash_approve habilita específicamente su aprobación de arqueo, sin ampliar las demás operaciones. Un caso real por roles conserva esperado 160, contado 150, diferencia -10, motivo/aprobador y cero asientos compensatorios.

Seis casos nativos cubren cobro/vuelto/devolución/cancelación, monedas/caja/banco, alcance/turno/referencia, clasificación histórica y formato actualizado. Los primeros fixtures debieron configurar la cuenta predeterminada de Mode of Payment y un modo USD distinto; la preparación de la factura para la prueba de permisos se realiza antes de cambiar al cajero. La batería final posterior a restauración aprueba **159 (145 integración y catorce puras)**; las **22 JS** incluyen presentación legible/escapada del POS y sus estados.

Gerencia abrió Caja del sitio de aceptación con una factura sintética creada por el controlador estándar: fondo C$100, venta C$60, recibido C$100/vuelto C$40. Contó 16×10 y cerró desde la Page por C$160, diferencia cero. Capturas 72–74 y pos-items-ui.json; PDF nativo de una página renderizada/revisada en 75. La primera exportación descubrió el HTML antiguo del formato con una fecha futura: sync_print_formats lo actualiza por contenido mediante importador nativo, conserva disabled y formatos del sitio, y se ejecuta desde after_migrate. El PDF elimina la clave aleatoria del turno y la tabla vacía.

La sesión se cerró hasta Login y 8089 se detuvo. Bench restauró el respaldo previo; las **70 tablas/185 filas** vuelven a coincidir, también después de la batería final. Tras la restauración se reiniciaron los servicios aislados antes de migrate; el primer intento sin Redis se detuvo antes de migrar/probar. El worker anterior completó su índice y se detuvo de forma normal antes de iniciarse otro. No se ejecutó la batería sobre datos UX. La demostración conserva 36 tablas nativas, HTTP 200 y núcleos limpios. Esta recuperación no sustituye la revisión final con archivo privado/reversión de código.

AUDITORIA_CAJA_POS.md conserva fuentes y límites. S09-14 pasa a V: **48 V, una I y 169 R**, con las mismas 218 entradas y huella. Continúan anticipos aplicados, traducciones y el resto del contraste obligatorio. Objetivo activo.

## Devolución de anticipos aplicados, versión 0.4.2

Caja devuelve un anticipo aplicado contra una nota de crédito estándar de su factura original, mediante Payment Entry de salida. Conserva importes/asignaciones/turno del original y controla fondos restantes, aportación a cada factura y crédito disponible. El anticipo sin aplicar conserva Journal Entry y conciliación estándar. La revisión incluye versiones/saldos, por lo que rechaza otra devolución hecha mientras se revisaba, incluso sin cambiar el tipo de cambio. Se prueba cancelar una devolución con motivo y reutilizar solo los fondos liberados.

El valor del cliente procede del movimiento original; el efectivo sale al cambio actual y la diferencia se registra con documentos estándar. USD10 liquida NIO366.24 y registra diferencia NIO3.76 al devolver con cambio 37. El último pago absorbe el residuo: USD0.03 valorado NIO1.10 se devuelve en tres fracciones que liquidan 0.37/0.37/0.36. El primer fixture de cantidad parcial necesitaba una UOM fraccionaria: Nos se rechazó correctamente y se utilizó Hour antes de emitir su factura.

El selector muestra concepto/fecha/importe/recibo estándar, conserva claves al enviar y omite fuentes incompatibles. Reservas y cuentas de grupo reutilizan su descripción legible y modo discreto. La revisión muestra nota, valor liquidado, cambio y dinero entregado; el resultado identifica el documento ERPNext. Dos pruebas JS prueban valores/etiquetas y escape de la revisión.

La batería final posterior a restauración aprueba **165 (151 integración y catorce puras)** y **24 JS (veintidós Desk y dos portal)**. Se añaden seis casos nativos y dos JS a 159/22. Ambos sitios migrados y assets compilados; web/worker principal actualizados. Gerencia confirmó desde Caja la devolución de C$1500 ya aplicada, con crédito/esperado cero e importes/asignación originales conservados; capturas 76–78 y refund-items-ui.json. La preparación anterior se hizo por API/controladores y no se presenta como entrada/factura creadas desde Page.

La sesión llegó a Login y 8089 se detuvo. El respaldo se restauró con Bench y **70 tablas/185 filas** coinciden después de la batería. La demostración conserva 36 tablas nativas, HTTP 200 y núcleos limpios. AUDITORIA_DEVOLUCIONES.md delimita evidencia y pendientes. La matriz conserva 218 entradas y huella: **48 V, dos I y 168 R**, con S09-08 parcial. Continúan garantías aplicadas, notas POS desde Pages, traducciones, demás capítulos y recuperación final. Objetivo activo.

## Devolución de garantías aplicadas, versión 0.4.3

Los fondos convertidos del pasivo al cliente se devuelven desde su Journal Entry: contra nota de la factura original si ya se asignaron, o asiento/conciliación estándar para la parte disponible. Se preservan valoración, asignaciones y turno históricos, límites y aprobación; no se reabre el pasivo ni se duplica caja. El resumen financiero incluye el crédito convertido aún sin factura. Cuatro casos nativos nuevos cubren ambos momentos, retorno parcial, remanente facturable, USD, turno cerrado y reintento.

Caja presenta recibos por concepto/fecha/importe/documento. Aplicar garantía permite elegir el turno abierto; Garantía aplicada (sin nuevo ingreso) explica su efecto. El filtro de orígenes de devolución ya no modifica otros asistentes, incluida liquidación de tarjeta; dos JS nuevos lo verifican.

Gerencia aplicó y devolvió C$1500 desde Page en aceptación. Recibo/estancia y factura/nota se prepararon por API/controladores; aplicación y devolución fueron acciones del navegador. El pasivo, crédito y esperado final son cero, y la asignación original se conserva; capturas 79–81. La sesión llegó a Login y 8089 se detuvo. Bench restauró las 70 tablas/185 filas antes de la batería final; coinciden también después. Resultado: **169 (155 integración y catorce puras)** y **26 JS (veinticuatro Desk y dos portal)**, ambos sitios migrados y assets compilados. Las 36 tablas nativas principales permanecen iguales y el resumen financiero principal se consulta sin cambios.

AUDITORIA_GARANTIAS_APLICADAS.md recoge alcance y pruebas. S08-10 pasa a V; las 218 entradas conservan texto/huella: **49 V, dos I y 167 R**. Continúan notas POS desde Pages, traducciones, contraste del resto de capítulos y recuperación final. Objetivo activo.

## Notas de crédito POS desde Caja, versión 0.4.4

La Page cotiza notas por los artículos/servicios originales y permite cantidades parciales sin mostrar claves de línea. Para POS presenta el neto real por medio/moneda, turno, parte de deuda compensada, ajuste original y diferencia de cambio. Un Journal Entry estándar enlazado devuelve/recupera dinero y liquida la nota estándar con stock nativo, sin otro HS Payment/Payment Entry ni alteración del original. El nuevo movimiento entra una sola vez en arqueo, conciliación y cierre. Los residuos monetarios no gastan fondos de notas anteriores impagas.

Catorce casos nuevos cubren NIO/USD, vuelto, mixtos, moneda del medio distinta, parciales, write-off, cambio de tasa, residuos, turno histórico, reintento, permisos y reversión. La primera alternativa de filas de pago POS no expresaba recuperar efectivo ni el residuo extranjero; se sustituyó por nota y asiento estándar enlazado. La batería final tras restauración aprueba **183 (169 integración y catorce puras)** y **28 JS (veintiséis Desk y dos portal)**. Dos JS nuevos prueban revisión/cantidades/etiquetas y aceptación conservada; el caso POS existente verifica enlaces de Journal Entry. tools/run_ui_tests.cjs simplifica la ejecución completa.

Gerencia devolvió dos unidades en dos notas de C$30 desde Page y cerró el turno en C$100, con fondo C$160 y diferencia cero; el original cerrado conserva C$160. La venta y preparación de turnos se hicieron por controlador/API. Se preservan recibo/stock y ambos créditos quedan liquidados; capturas 82–85 y credits-items-ui.json. La revisión explica los efectos y el resultado omite el aviso técnico duplicado de conciliación, conservando validaciones y mensajes previos. Los movimientos nativos ya no quedan detrás de una tarjeta vacía de movimientos operativos.

El arqueo real de una página se renderizó/revisó con ambas devoluciones: captura 86. La sesión terminó en Login y el servidor temporal quedó detenido. Respaldo restaurado con archivos y 70 tablas/185 filas idénticas también después de la batería final. Ambos sitios migrados/compilación correcta y 36 tablas nativas principales intactas; AUDITORIA_NOTAS_POS.md delimita las pruebas. S09-08 mantiene contraste parcial: **49 V, dos I y 167 R** de las mismas 218 entradas. Continúan el contraste individual de capítulos restantes, traducciones y recuperación final. Objetivo activo.

## Notas POS y recibos adicionales, versión 0.4.5

Caja distingue «Dinero que se devuelve ahora» y «Crédito pendiente de devolver». Los recibos se muestran por concepto, fecha, importe y documento ERPNext, conservando las claves internas. El asiento de la nota devuelve solo el cobro POS; Cobrar → Devolución liquida el crédito con el recibo adicional original, incluso sin estancia/reserva, conservando los límites por factura y globales. La devolución adicional no consume otra vez el presupuesto del POS. Los fondos no identificados y la valoración POS incoherente siguen rechazados.

La batería completa aprueba **187 (173 integración y catorce puros)** y **29 JS (veintisiete Desk y dos portal)**, cuatro casos nativos y un JS más. Prueba parciales sucesivas, POS financiado por otro recibo, garantía aplicada y USD10/NIO366.24 distribuido en dos facturas que se devuelve como USD2.73/USD7.27 sin residuo contable. El caso anterior de circuito compuesto pasa de rechazo a devolución por origen, con originales y reintento conservados.

Gerencia crea desde Page una nota de 60, devuelve POS 30, luego devuelve el recibo adicional 30 contra la nota y cierra el turno con fondo 160 y contado/esperado 100. El original cerrado conserva 160, el crédito y stock neto quedan en cero y no se duplica el movimiento en el cierre. Venta/recibos/turnos se prepararon por API/controladores nativos; capturas 87–91 y mixed-items-ui.json identifican las acciones de interfaz. Sesión cerrada en Login y 8089 detenido. Bench restaura con archivos; **70 tablas/185 filas** coinciden. Ambos sitios migrados/assets compilados, servicios restablecidos tras reinicio de WSL, HTTP 200 y **36 tablas nativas principales intactas**. No se modificó el núcleo.

AUDITORIA_RECIBOS_POS.md detalla el contraste. S09-08 pasa a V y la matriz conserva las 218 entradas y huella: **50 V, una I y 167 R**. Continúan traducciones, auditoría individual de los capítulos restantes y recuperación final con archivo privado/reversión. Objetivo activo.

## Contabilidad por establecimiento y servicio, versión 0.5.0

Configuración incorpora cuentas de ingreso/gasto y centro de costo de la sede, con excepciones por Item y resumen por nombre. HS Service Account es una tabla hija; no cambia Item Default compartidos. Las validaciones impiden cuentas incompatibles/deshabilitadas y versiones obsoletas, incluso antes de cotizar. Factura y entrega usan la clasificación elegida, compras con stock conservan las cuentas nativas de inventario y notas/cancelaciones revierten la historia original. Auditoría y permisos en el servidor.

La batería final aprueba **193 (179 integración y catorce puros)** y **30 JS (veintiocho Desk y dos portal)**. Seis casos nuevos prueban GL real, dos sedes en una compañía, compra/entrega sin duplicar gastos, devolución histórica, errores de alcance/versión y cuenta deshabilitada. Se hicieron explícitas las fechas de los escenarios de cierre que fallaban al cambiar de día; la fecha principal y el cálculo no cambian. El fixture de cuenta ajena crea una compañía real distinta, porque las sedes demo comparten compañía.

Gerencia guarda/reabre la configuración desde Page, vende Agua minibar por 30 y cierra el turno con fondo 100 y esperado/contado 130. GL acredita ingreso 30, costo 10 y centro Minibar; stock 100→99 e Item Default intacto. Cuentas/centros/turno se preparan por controladores/API, capturas 92–95. Sesión terminada en Login y 8089 cerrado. Bench restaura con archivos y **71 tablas/185 filas** coinciden también tras la batería final. La actualización conserva **70 tablas/911 filas** previas, campos nuevos vacíos y ninguna asignación contable en el sitio principal. Ambos sitios migrados, assets/servicios actualizados, 35 DocTypes/once Pages y núcleos limpios.

La huella antigua de Company difiere por dos cachés y modified del mantenimiento estándar de ERPNext de las 00:00:22 del 20/10. Se acredita con fila de respaldo que reproduce la huella original, tarea completada y valores derivados de las funciones nativas de lectura. Company coincide con el respaldo previo a esta fase; las otras 35 tablas nativas mantienen su huella histórica. No se modifican datos para forzar la comparación. Véase accounting-company-cache.json y AUDITORIA_CONTABILIDAD_SERVICIOS.md.

S09-09 pasa a V: **51 V, una I y 166 R** de las mismas 218 entradas. La matriz resumida aclara que la recuperación final actual sigue pendiente, conservando el ensayo histórico. El siguiente contraste recorrerá el resto del inventario en bloque para precisar diferencias materiales y esfuerzo restante, junto con traducción y recuperación final. Objetivo activo.

## Contraste en bloque de flujos, transacciones y aceptación, 20/10/2026

Se contrastaron 38 entradas contra código, aserciones y evidencia conservada: portal/integraciones, transacciones y escenarios de aceptación, además de S12-03. Veintiocho pasan a V, siete a I y tres a P. El inventario original conserva texto/huella y sus 218 entradas: **79 V, ocho I, tres P y 128 R**. Esta revisión no interpreta R como función ausente ni convierte el recuento en porcentaje de programación.

Se acreditan escenarios hotel/motel/grupo, cancelación/no presentación/expiración, anticipos/garantías, monedas/arqueo, sincronización nativa, limpieza/inspección, stock único/reversión y fallos de red/facturación/worker. Las dos carreras reales con conexiones independientes confirman una sola solicitud. La revisión estática no localiza commits intermedios en módulos de ejecución; los explícitos son herramientas de prueba. Los enlaces de casos en la matriz se comprobaron contra el JUnit actual sin fallos.

Las tres P representan dos diferencias materiales: falta la generación periódica de cargos de alojamiento y el webhook persiste estructuras alternativas que la lista de nombres prohibidos no redacta. La reproducción pura conserva un marcador ficticio en nested.card.number y redacta cvv, sin HTTP ni base. Se requieren campos permitidos del contrato. Cargo operativo periódico y reconocimiento contable al presentar factura son obligaciones diferentes; no se crea otro libro.

Quedan verificaciones específicas de extremos del colchón de disponibilidad, reintentos de expiración, las otras familias de contratos/simulaciones, repetición nocturna, demo con operaciones y recepción+caja/sesión contable. La matriz resumida corrige F19/F21/F24 a I en su alcance completo. Se aclara el resultado vigente en el índice de evidencia y se retira un pendiente documental de devoluciones adicionales ya resuelto en 0.4.5.

No se cambió código de aplicación ni se escribieron bases/sitios. No se ejecutó otra batería o recorrido: siguen vigentes **193 pruebas** y **30 regresiones JavaScript**, que no equivalen a treinta recorridos de navegador. AUDITORIA_FLUJOS_TRANSACCIONES.md y flow-audit.json registran el contraste. Continúan 128 R, las diferencias y verificaciones abiertas, traducciones y recuperación final de la revisión que se entregue; objetivo activo y sin fecha fiable de terminación todavía.

## Receptor sin cuerpos arbitrarios, versión 0.5.1

El usuario pidió dejar pendiente la sincronización con Airbnb, Booking y otras plataformas y después priorizó formularios más cortos y acciones claras. Se registra en INTEGRACIONES.md/PENDIENTES.md; no se implementa ni activa sincronización. Se completa únicamente la corrección del receptor preexistente detectada en la auditoría.

El payload conserva solo versión/origen/longitud/huella; event_id es una huella por proveedor y el estado sigue Received, sin efectos de reserva, pago o cerradura. Se valida forma del JSON/identificador sin copiar valores a errores. La migración retira contenidos históricos de payload/error y Version, conserva otros metadatos/cambios y audita una sola vez. Los respaldos históricos siguen su política de almacenamiento, sin reescribirlos.

La batería completa final aprueba **196 (182 integración y catorce puras)** y **30 JavaScript**. Tres casos nativos nuevos prueban formas inválidas sin efectos, identidad/reenvío y migración con Version/auditoría repetible; la prueba pura exige datos mínimos con claves desconocidas/anidadas. Las primeras ejecuciones detectaron un paréntesis de test y comparación de fechas texto/datetime del fixture; se corrigieron sin relajar metadatos. No se presentan como aprobadas esas ejecuciones iniciales.

Respaldos nativos con archivos y migrate en ambos sitios. Se conservan todas las columnas de 72 tablas con Version: 1191 filas principales y 195 de aceptación, más dos archivos privados principales idénticos. Ambos sitios tenían cero eventos de proveedor; los datos legacy se probaron dentro de transacciones revertidas. Web reiniciado; el worker terminó gradualmente después de la espera del helper y se comprobó su ausencia real antes de arrancarlo. HTTP/puertos y núcleos verificados; aceptación continúa sin operaciones. Sin cambios de interfaz ni recorridos nuevos en esta fase.

S14-08 pasa a V: **80 V, ocho I, dos P y 128 R** de las mismas 218 entradas/huella. Las P restantes son generación periódica e idempotencia. Continúan mejora de formularios, auditoría del resto de capítulos, traducciones, aceptación completa y recuperación final. Objetivo activo.


## Formularios por tarea, versión 0.5.2

Se atiende la prioridad del usuario: configuración, tarifas, medios, horarios, reserva/entrada, huésped y establecimiento se distribuyen en pestañas nativas. Cobros separa cuenta/importe/devolución, muestra controles según medio/modalidad y nombra la revisión/confirmación por intención. Encabezado/pie permanecen fuera del desplazamiento; móvil apila columnas, ajusta pestañas y ofrece acciones de 44 px. La validación abre la sección faltante con selección accesible. Una revisión oculta y vuelve inerte su borrador; cerrarla lo restaura intacto.

Aprueban **37 regresiones JavaScript**, siete nuevas. La batería de backend vigente es **196 (182 integración y catorce puras)** ejecutada en 0.5.1; esta fase no cambia esas reglas ni afirma otra ejecución conjunta. El navegador real verifica 1280×720/390×844: configuración/tarifa/huésped guardados desde otras pestañas, validación sin alta incompleta, entrada H101 y cobro 1500/recibido 1600/vuelto 100, revisión cancelada/reabierta sin pérdida y cierre con contado/esperado 1500. Lectura nativa acredita una reserva, estancia, cuenta, factura y pago; saldo/diferencia cero. Capturas 96–101 y forms-items-ui.json.

Aceptación termina en Login, se detiene 8089 y se restaura por Bench con archivos: **71 tablas/185 filas** idénticas. Comparación adicional con Version: **72 tablas/195 filas de aceptación y 72/1191 principales**, dos archivos privados principales conservados. Ambos sitios migrados, assets compilados, web principal actualizado; fecha operativa 19/10, guardia de fixtures, HTTP/servicios y núcleos limpios comprobados. No se añade operación principal.

UX_FORMULARIOS.md registra los ajustes detectados en prueba: apertura explícita de Tab Break, clases reales del botón Frappe 16 y comparación textual de saldo en la herramienta de inspección. F22a V acredita esta mejora; F22 general sigue I. La matriz canónica conserva **80 V, ocho I, dos P y 128 R de 218** y agrega esta evidencia a las decisiones previas correspondientes. Continúan cargos periódicos, contraste restante, traducciones, aceptación completa y recuperación final de la revisión que se entregue. Sincronización externa pendiente por indicación del usuario. Objetivo activo.


## Cargos por noche, versión 0.6.0

Se incorpora política Al ingresar/Por noche para nuevas estancias hoteleras, conservada en la estancia. Cada noche mantiene precio/artículo/fecha aceptados y una referencia única. Las extensiones incluyen noches de precio cero. Preparar cierre genera la fecha operativa y vencidas una sola vez; futuras permanecen programadas. Cuenta, producción y resumen distinguen programado/generado/facturado. Facturación anticipada y salida liquidan todas las noches pendientes mediante ERPNext, sin otro libro. Ajustes/traslados conservan origen y autorización.

La revisión de factura externa detectó que una línea sin origen podía omitir las programaciones; se amplió la guardia nativa y se probaron fuentes explícitas/sin origen. La revisión de extensión cero añadió su noche aun sin incremento monetario. Aprueban **211 pruebas (197 integración y catorce puras)**, quince nativas nuevas, y **38 JS**, una nueva. Los informes de 208/210 se conservan como comprobaciones anteriores, sin sustituir la batería final. Núcleos intactos.

Page: gerente guarda/reabre política móvil, acepta H101 por tres noches/4500 y prepara dos veces 19/10: una generada/1500 y dos programadas/3000, una bitácora, sin factura/pago. El cierre ofrece secciones desplegables y el PDF de una página separa importes; Poppler revisado, capturas 102–105. El primer PDF no resolvió el hostname WSL; la herramienta usa loopback solo en memoria. Sesión terminada en Login, 8089 detenido y aceptación restaurada por Bench con archivos: 71 tablas/185 filas idénticas también tras la batería final. La actualización conserva columnas anteriores de 72 tablas/1191 filas y dos archivos privados principales, 195 filas de aceptación y valores nuevos iniciales. Fecha principal 19/10; servicios/web/worker actualizados.

S12-03/S16-06/S17-08 pasan a V. El contraste de S00-02 encuentra una diferencia de Pages: no hay acción explícita para facturar sin cobrar/salir, aunque el contrato de servidor existe. Se registra P y es el siguiente cambio, incluidas cuentas cero. La matriz queda **83 V, siete I, una P y 127 R** de las mismas 218 entradas/huella. CARGOS_PERIODICOS.md y periodic-page-invoice-gap.json conservan el alcance. Continúan auditoría restante, límites/reintentos, traducciones, aceptación/demostración y recuperación final. Sincronización externa pendiente por instrucción del usuario; objetivo activo.

## Facturar cuenta desde Pages, versión 0.6.1

Se resuelve la ruta ausente encontrada en 0.6.0. Recepción → Ver estancia → Facturar cuenta permite seleccionar cuenta, revisar valores de Sales Invoice y emitir sin cobrar ni registrar salida. La revisión compacta destaca total, neto/impuestos, anticipos y saldo; conserva el borrador, permite importe cero y explica el efecto antes de confirmar. El resultado muestra total, saldo, estancia activa y enlace legal. La moneda de la cuenta del cliente se determina expresamente para el cálculo transitorio nativo.

La cotización no escribe documentos/series, genera programaciones ni aplica conciliaciones. La confirmación valida una huella actual de cargos/configuración/valores nativos antes de liquidar programaciones; el reintento conserva la clave. Una cuenta sin cargos nuevos devuelve aviso sin nueva factura ni conciliación. El primer intento parcial detectó la importación ausente de canonical; corregida antes de la batería final. Aprueban **220 pruebas, 206 integración y catorce puras**, nueve nativas nuevas, y **41 JS**, tres nuevas.

Navegador real: entrada cero desde Page, revisión a 390×844 y emisión; segunda estancia de C$1250 preparada mediante fixture API, revisión/emisión desde Pages. Ambas siguen activas, tres cargos facturados, cero pagos/turnos/Payment Entry/Journal Entry/limpiezas/cierres. Se comprueba también el aviso de cuenta ya facturada. Capturas 106–110 y billing-items-ui.json; no acredita tiempo real ni entrada positiva desde Page.

Respaldos nativos con archivos, migraciones y bundle completados. billing-ui-upgrade.json conserva todas las columnas de 72 tablas/1191 filas/dos archivos privados principales y 195 filas de aceptación. Tras cerrar sesión y detener 8089 se restaura aceptación: 71 tablas/185 filas y cero operaciones. Web/worker reiniciados; 8086/9001/Redis activos. Las 35 tablas nativas históricas siguen iguales, Company mantiene su acreditación de cachés y las 36 coinciden con el respaldo previo. Fecha principal 19/10 conservada, sin confirmar cierre. Núcleos limpios y datos privados fuera de Git.

S00-02 y F22 pasan P→I; F22b acredita este flujo concreto. La matriz conserva **83 V, ocho I, cero P y 127 R**, 218 entradas/huella originales. Continúan la auditoría amplia, aceptación por rol, límites/reintentos, traducciones, demo y recuperación final. La sincronización de canales sigue pendiente por instrucción del usuario. El objetivo permanece activo. FACTURACION_DESDE_PAGES.md conserva detalles y límites.
