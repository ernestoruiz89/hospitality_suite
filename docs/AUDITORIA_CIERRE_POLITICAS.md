# Políticas de caja y resumen financiero del cierre

La versión 0.3.0 amplía S03-05 y S12-05. La contabilidad continúa en los documentos estándar de ERPNext; el cierre conserva una captura y no crea asientos.

## Políticas del establecimiento

HS Property permite configurar anticipos y garantías de forma independiente: Manual (según rol de caja), Approval (gerencia) o Disabled (sin nuevos ingresos de ese tipo). Configuración → Anticipos y garantías utiliza etiquetas en español y exige aprobación para guardar. El controlador también protege cambios por formulario nativo, incluso frente a un supervisor que tiene configuración pero carece de aprobación.

La cotización y el comando financiero vuelven a aplicar la política en servidor. La política aceptada forma parte de la huella y se conserva con el actor que autoriza en la auditoría. Los Payment Entry nuevos sin referencias y Journal Entry con crédito al pasivo de garantías también pasan por la política al presentarse. No se permiten cobro de factura y anticipo sin aplicar mezclados en un Payment Entry. Los documentos anteriores siguen admitiendo devolución/aplicación autorizada: deshabilitar ingresos no confisca fondos existentes.

Se mantiene el resto de S03-05: cancelación/no presentación configurables (None, Fixed, First Night, Percent), crédito por establecimiento y pagador con límite/vigencia, descuento/cortesía con motivo y aprobación. Los casos de lifecycle/report_dimensions contrastan las penalizaciones; timing_metrics prueba cortesía; payment_policies añade rechazo de descuento a supervisor, tope del cargo y salida a crédito deshabilitada, sin autorización, vencida o sobre límite, seguida de aprobación válida. La configuración tributaria/financiera deshabilitada bloquea también la presentación nativa de facturas y pagos.

## Conceptos y fechas del cierre

close_financials.snapshot conserva importes separados por moneda y documentos de origen:

- Producción operativa de cargos/ventas, junto con los indicadores de ocupación ya conservados.
- Facturación por Sales Invoice.posting_date: neto, impuestos, total, redondeo y notas de crédito ya deducidas del total.
- Movimientos por fecha operativa: cobros, anticipos, garantías, devoluciones y aplicaciones. La aplicación de garantía no es otro ingreso de dinero.
- Cobros POS nativos sin Payment Entry: neto real de sus cuentas de pago en GL, incluido vuelto y devoluciones; su fecha operativa procede del evento de presentación. No se duplica la venta como cobro de Payment Entry.
- Saldos a la hora de revisión/cierre, de todas las fechas: cargos pendientes, facturas por cobrar y créditos a favor separados, anticipos sin aplicar y garantías disponibles.

outstanding_amount y unallocated_amount nativos están expresados en moneda de la cuenta del cliente; no se etiquetan con la moneda de la factura o del efectivo si difieren. Las garantías conservan moneda original. No se suman USD y NIO ni se concilian facturas contra créditos dentro del reporte. Una factura pendiente y una nota de crédito no aplicada permanecen visibles por separado.

HS Payment registra business_date desde la propiedad bloqueada al insertar. El patch solo recupera fechas históricas acreditadas por auditoría de creación/presentación; no deduce el día operativo de posting_date ni del reloj. Los registros sin prueba quedan Unknown y se advierten sin atribuirlos a un período. Los once movimientos existentes de la demostración obtuvieron fecha Audit.

La revisión devuelve una huella de los importes, fuentes y pendientes. La Page la envía al confirmar; un cambio financiero exige actualizar la revisión. Los contadores que avanzan con el reloj y el instante de captura no provocan falsos cambios de esa huella. El JSON cerrado conserva importes, precisión, período y fuentes aunque después se pague una factura. Ver resumen lee ese JSON; un cierre antiguo sin ampliación lo indica expresamente.

## Evidencia y límites

financial-native-tests.xml y financial-js-tests.log conservan la aceptación ejecutada: 145 pruebas nativas (132 de integración y trece puras) y diecinueve JS (diecisiete de Desk y dos del portal). Los doce nuevos casos nativos cubren políticas/cotización/roles/formularios ERP, descuentos/crédito, fecha operativa/migración, devoluciones/impuestos/POS/monedas y estabilidad del cierre. Las cuatro nuevas pruebas JS cubren opciones restringidas, referencias estables, consulta histórica y confirmación de lo revisado. Los casos revierten sus operaciones.

La migración principal conservó las 70 tablas/908 filas verificadas y un archivo privado con la misma huella; solo se excluyen de esa comparación las cuatro columnas nuevas declaradas. financial-upgrade-before/after.json y verify_financial_upgrade.py identifican ese alcance. No equivale a la restauración final de toda la versión.

La Page de Gerencia creó una revisión, sin confirmar el día ni alterar asientos: capturas 64–66 y financial-close-ui-export.json. Facturación NIO 9120, cobros de facturas 8650, anticipos 500, devolución 30 y cargos pendientes 3100 se muestran diferenciados. El botón confirmar permanece deshabilitado por dos cargos pendientes. El PDF nativo se renderizó y revisó en dos páginas, con títulos/tablas juntos y referencia técnica al pie. Se exporta el resumen guardado sin recalcularlo.

Configuración guardó Approval/Disabled en el establecimiento administrativo vacío de hospitality-clean.localhost y lo conservó al recargar: captura 67 y payment-policy-ui.json. No se habilitaron finanzas ni se crearon movimientos en ese establecimiento. Esa vista temporal no acredita un segundo Socket.IO y se detiene al terminar.

Durante el archivado se reinició WSL y se perdieron los archivos temporales y los procesos Redis/web. Una ejecución sin Redis se interrumpió; su salida dejó una estancia y factura parciales en el sitio limpio. Se conservó un respaldo de diagnóstico y no se eliminó ni ajustó su libro mayor manualmente. hospitality-acceptance.localhost se creó con base independiente, apps actuales, datos sintéticos y respaldo inicial antes de la nueva batería. El sitio de demostración no se usó como sustituto del estado inicial de pruebas.

before_tests ahora exige hospitality_integration_test_site, Redis disponible y ausencia de operaciones antes de cargar fixtures. Esto evita ejecutar la batería sobre una demostración o un sitio contaminado por una interrupción. La creación desde cero detectó además nombres iniciales de Warehouse traducidos: el seed explícito crea su almacén Stores si falta; la instalación normal sigue sin crear maestros de negocio. El recorrido por roles detectó que una factura operativa heredaba un almacén predeterminado ajeno al establecimiento; sus líneas ahora seleccionan el almacén de la propiedad antes de pedir valores predeterminados a ERPNext. Las devoluciones conservan su almacén de origen. El recorrido de cuatro roles y la venta directa como cajero comprueban el circuito sin ampliar permisos.

En 0.3.0, S01-04 y S03-06 mantuvieron contraste parcial. La ampliación de S03-06 se documenta posteriormente en AUDITORIA_SERVICIOS.md. Los demás capítulos, la relación entre POS nativo y arqueo de turno, la devolución de anticipos ya aplicados y la recuperación de la revisión final requieren continuar la auditoría; este avance no completa el objetivo general.
