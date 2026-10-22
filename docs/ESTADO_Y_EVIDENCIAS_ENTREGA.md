# Estado de entrega y evidencias — 0.8.9

El alcance obligatorio se contrasta en **218 requisitos**, con implementación y evidencia individual en [la matriz](AUDITORIA_ESPECIFICACION.md) y [el cotejo final](COTEJO_FINAL.md). La entrega conserva el objetivo completo y los ajustes de interfaz. La sincronización real con Airbnb/Booking permanece aplazada por instrucción expresa del usuario.

## Funciones completadas

| Área | Entregado y probado | Evidencia principal |
|---|---|---|
| Recepción/reservas | Disponibilidad por fechas/cantidad, cupo físico o categoría, grupos, borradores/holds, cotización, entrada, extensión/cambio y salida | [Aceptación real](ACEPTACION_Y_DEMOSTRACION.md), [tarifas/reservas](AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md), [tareas](TAREAS_Y_ESTADOS_POR_ROL.md) |
| Caja/contabilidad | Turno, pagos/FX/vuelto, anticipos/garantías, facturas/notas/devoluciones, gastos/liquidaciones y conciliación con ERPNext | [Caja/contabilidad](AUDITORIA_CAJA_CONTABILIDAD.md), [devoluciones](AUDITORIA_DEVOLUCIONES.md), [tesorería](TESORERIA_Y_COMPRAS_DESDE_PAGES.md) |
| Limpieza/mantenimiento | Móvil, checklist e inspección, bloqueos/equipos/repuestos, novedades/evidencias y ropa | [Limpieza](AUDITORIA_LIMPIEZA_MANTENIMIENTO.md), [ropa](ROPA_Y_POLITICAS_DESDE_PAGES.md), [evidencias](VENTANAS_Y_EVIDENCIAS_PRIVADAS.md) |
| Servicios/inventario | Solicitud/preparación/entrega/devolución, POS nativo, compras/movimientos/conteos, mínimos y activos sin doble stock | [Inventario](AUDITORIA_INVENTARIO_SERVICIOS.md), [compras](TESORERIA_Y_COMPRAS_DESDE_PAGES.md) |
| Gestión y cierre | Reportes filtrables/exportables, KPI por noches/horas, origen nativo, fecha/corte, resúmenes congelados y recuperación | [Contabilidad](CONTABILIDAD.md), [cierres](FECHA_Y_PENDIENTES_CIERRE.md), [bitácora](BITACORA_Y_CIERRES.md) |
| Acceso y UX | Nueve roles/sedes, once Pages, nombres/series, formularios agrupados, teclado/móvil, estados/reintento y tiempo real | [Seguridad](AUDITORIA_SEGURIDAD.md), [teclado](TECLADO_Y_FOCO.md), [tareas](TAREAS_Y_ESTADOS_POR_ROL.md), [tiempo real](TIEMPO_REAL_SITIOS_LOCALES.md) |
| Portal y retención | Portal desactivado por defecto, solicitud/hold/token y conversión manual; revisión/retención privada con fallo y reintento | [Recorrido completo](RETENCION_Y_PORTAL_DESDE_PAGES.md) |
| Impresión/documentación | Nueve formatos, cuenta concisa y explicación histórica en pantalla, modelo/estados y guías en español | [Impresiones](IMPRESIONES_OPERATIVAS.md), [cuenta](CUENTA_RESUMIDA.md), [entregables](ENTREGABLES_Y_REVISION.md) |
| Instalación/recuperación | Paquetes comparados, instalación limpia actual, actualización 0.8.8→0.8.9, fallo, recuperación de código/base/archivos y segundo despliegue | [F26](ACTUALIZACION_Y_RECUPERACION_FINAL.md), [entrega](ENTREGA_FINAL.md) |

## Evidencia actual y alcance

**410 pruebas nativas: 378 integración/32 unitarias**, sin errores/fallos/omisiones, y **232 JS: 229 Desk/tres portal**, desde el bench independiente con app 0.8.9. [JUnit](evidence/final-recovery-native-tests.xml), [salida](evidence/final-recovery-native-tests.log), [JS](evidence/f26-js-run.json). Instalación actual: 35 DocTypes, once Pages, nueve roles, nueve formatos, seis patches y 28 APIs contra fuentes. [Metadatos](evidence/f26-clean-install.json).

Los recorridos GUI y sus fixtures se describen por fase. Se conserva la aceptación completa de recepción/caja/limpieza/supervisión/contabilidad/gerencia y las variantes de compras, ropa, mantenimiento, privacidad y portal. El inventario de 84 manejadores y las pruebas JS no se convierten en 84 nuevas ejecuciones GUI. Los fallos previos de producto, supuestos corregidos de pruebas y límites de los recorridos se conservan en sus documentos originales.

El ensayo F26 conserva 72 tablas/1,246 filas y los archivos de la copia del principal tras actualización, recuperación y segundo despliegue. El destino original y sus 21 archivos vuelven a su estado anterior; catorce archivos del escenario nativo se archivan fuera del sitio. Principal y aceptación registran 0.8.9 y conservan sus datos; los procesos temporales quedan apagados. [Verificación](evidence/f26-verification.json).

## Límites verificados de esta entrega

- Entorno acreditado: Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, Node 24.18.0 y MariaDB 10.11.14 en Ubuntu 24.04/WSL2. Otras versiones requieren su propia aceptación.
- La instalación no carga demostración. La batería necesita sitio designado sin operaciones y scheduler pausado; no se debe ejecutar en el sitio ocupado de demostración ni producción.
- Impuestos, identificación, cuentas, políticas y autorizaciones se configuran por implementación; los datos actuales son ficticios. HRMS es opcional y no estaba instalado.
- Sin cobros desconectados. Los roles de recepción/caja son separados y se combinan solamente cuando se autoriza a una persona. El portal confirma manualmente y su página no acredita pago.
- PDF requiere Qt parcheado. Workers/scheduler y aliases locales deben estar activos; el lanzador de WSL verifica el sitio existente después de reinicios.
- Las evidencias no certifican un entorno productivo ajeno ni la seguridad de proveedores externos.

## Integraciones externas pendientes de proveedor/acceso

| Familia | Entregado | Pendiente antes de operar |
|---|---|---|
| Pasarela | Contrato/adaptador de referencia, intención pendiente, firma/caducidad/idempotencia y simulación sin contabilización | Proveedor, documentación, credenciales y aceptación de pagos/liquidación/conciliación reales |
| Correo/WhatsApp | Contrato de destinatario/plantilla/enlace firmado, respuesta y pruebas sin red | Proveedor, remitente/plantillas, acceso/credenciales y prueba real de entrega |
| Cerraduras | Vigencia/revocación acotadas y pruebas simuladas sin códigos de acceso exportados | Equipo/proveedor, documentación, acceso y aceptación física |
| Airbnb/Booking/canales | Contrato y normalizador entrante de solo lectura; publicar disponibilidad rechaza | **Sincronización real aplazada por el usuario. No implementada ni activada.** |

[CONTRATOS_PROVEEDORES.md](CONTRATOS_PROVEEDORES.md) delimita las simulaciones. Estos pendientes opcionales se separan del núcleo obligatorio; no se presentan como conectores comerciales activos ni como bloqueos ocultos del núcleo.
