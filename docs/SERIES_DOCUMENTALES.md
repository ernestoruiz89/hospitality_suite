# Series documentales legibles

Los nuevos documentos de operación usan el contador nativo de Frappe, con prefijo, año calendario del sitio y al menos cinco dígitos. El contador anual es independiente de la fecha operativa y se comparte entre establecimientos del mismo sitio; por eso un número no identifica por sí solo el hotel. Puede haber saltos: el consecutivo no representa cantidad de movimientos ni tiene carácter fiscal.

| Documento | Ejemplo |
|---|---|
| Reserva | RES-2026-00001 |
| Estancia | EST-2026-00001 |
| Cuenta / folio | CTA-2026-00001 |
| Cargo | CAR-2026-00001 |
| Pago | PAG-2026-00001 |
| Turno | TUR-2026-00001 |
| Limpieza | LIM-2026-00001 |
| Mantenimiento | MAN-2026-00001 |
| Servicio / consumo | SER-2026-00001 |
| Novedad | INC-2026-00001 |
| Cierre diario | CIE-2026-00001 |
| Solicitud del portal | SOL-2026-00001 |
| Ejecución autorizada de retención documental | RET-2026-00001 |

Los maestros usan series continuas sin año: ESTAB (establecimiento), CAT (categoría), HAB (habitación), TAR (tarifa), HUE (huésped), MED (medio de pago), CATGTO (categoría de gasto), PROV (proveedor), POLSTK (política de stock), EQP (equipo) y PAGADOR (configuración del pagador). Los nombres comerciales, números de habitación y títulos continúan como información principal visible. Por ejemplo, HAB-00001 puede representar la habitación M103.

La definición está en `hospitality_suite/document_naming.py` y se genera como metadata estándar con `tools/generate_schema.py`; `bench migrate` la aplica sin un renombrado masivo. No se añaden campos obligatorios ni decisiones de configuración al trabajo de recepción. Facturas, Payment Entry, asientos y movimientos de stock conservan las series de ERPNext.

Los documentos existentes mantienen nombre, enlaces, historial, archivos, referencias contables e idempotencia. Un hash antiguo sigue siendo válido en API y enlaces guardados; la interfaz lo acompaña de nombres y contexto. Las tablas hijas y registros técnicos de asignación, autorización, solicitudes idempotentes, eventos de integración y auditoría conservan identificadores internos aleatorios. Las claves y firmas de integraciones permanecen independientes del nombre visible.

Las pruebas ejercitan las 24 series con el generador real de Frappe, sus incrementos y prefijos independientes; crean reserva/estancia/cuenta/cargos mediante API e insisten con la misma clave sin duplicar. Verifican que los maestros anteriores y los enlaces no cambian. La batería de operaciones, finanzas e integraciones se ejecuta con esta metadata. Las carreras de dos conexiones conservan su evidencia histórica; este cambio usa el contador atómico estándar de Frappe y no añade un contador propio. La verificación de arquitectura comprueba las reglas instaladas en el sitio principal.
