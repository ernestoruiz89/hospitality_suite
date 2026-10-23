# Arquitectura de Hospitality Suite sin ERPNext

Estado: implementación en curso. Este documento describe el destino acordado y el estado real del repositorio; la modalidad PMS todavía no tiene paridad funcional ni habilitación fiscal para producción.

## Decisiones de producto

- Una instalación Frappe por dueño; un sitio puede contener varios hoteles. Cada propiedad pertenece a una entidad legal propia de Suite y los permisos siguen limitados por establecimiento.
- El sitio usa un único proveedor contable activo en cada período: libro propio PMS o ERPNext. Nunca publica simultáneamente el mismo hecho económico en ambos.
- La primera versión sin ERPNext debe cubrir las funciones actuales de Hospitality Suite: reservas, estancias y day pass; folios, ventas, cobros mixtos y crédito; caja, caja chica, préstamos y capital; compras, inventario, lavandería, experiencias, agencias, mantenimiento, reportes y cierre.
- El libro PMS será de partida doble, con asientos, reversos y existencias valoradas inmutables. Cada entidad tiene moneda base y cada establecimiento habilita sus monedas de operación. Los asientos conservan importes originales y equivalentes en moneda base, con el tipo de cambio fijado al registrar el hecho. Caja y banco mantienen arqueo o saldo por moneda.
- La facturación de Nicaragua cubrirá régimen general y cuota fija. Cada serie y documento emitido debe preservar numeración, base, tributos, régimen y reversos. La emisión fiscal en producción exige autorización del contribuyente y validación legal vigente de formularios y procedimientos.
- Personal, configuración, portal de huéspedes y reserva pública usarán React con shadcn/ui y marca propia. Frappe Desk queda para administración técnica. Se conservarán enlaces públicos mediante rutas compatibles.

## Diseño de datos y autoridad

| Área | Registros propios y reglas |
| --- | --- |
| Entidad y maestros | `HS Organization`, `HS Party`, `HS Product`, `HS Warehouse`, `HS Account`. Los identificadores de ERPNext se guardarán en mapas del conector, sin convertirlos en identidad primaria del núcleo. |
| Mayor | `HS Journal` y líneas equilibradas. Todo asiento conserva establecimiento, entidad, fecha operativa, origen, propósito, moneda de cada cuenta, importes originales y equivalentes base. Los errores se corrigen con otro asiento enlazado. El catálogo `HS Account` importa y exporta el formato de ocho columnas del CoA Importer de ERPNext. |
| Facturación y cobros | En el estado actual, `HS PMS Receivable` representa un cargo interno, no fiscal, y `HS PMS Allocation` vincula cada cobro o aplicación de anticipo sin exceder el saldo. `HS Payment` conserva cada medio y moneda. Los documentos fiscales con líneas y tributos congelados siguen pendientes; las garantías serán pasivo hasta su aplicación o devolución. |
| Inventario | Movimientos por producto y almacén con cantidad, valor, saldo y origen. La salida usa costo promedio ponderado; el último retiro absorbe residuos de redondeo. Recepciones, consumo, devoluciones, transferencias y conteos se contabilizan en la misma transacción. |
| Cierre | Snapshot diario inmutable por establecimiento, moneda, concepto y fuente. Producción, cartera, caja, banco y movimientos de financiación se muestran por separado y concilian con el mayor. |

Los comandos siguen el contrato autenticado `api.execute(property_name, action, request_key, data)`. Cada intención usa un bloqueo por establecimiento, transacción, clave idempotente y comprobaciones del rol y alcance. Las consultas y exportaciones no conceden acceso por conocer un identificador ajeno. Los cambios de configuración afectan solo operaciones posteriores.

## Interfaz y conector

La SPA se sirve en `/hospitality/app/*`, con recursos compilados por Vite desde `frontend/`. Usa la sesión y CSRF de Frappe y las API existentes. Durante la transición, el lanzador dirige los sitios ERPNext a sus Pages actuales; el acceso principal cambiará a React cuando todas las pantallas y comandos estén migrados. El portal público existente en `/hospitality` permanece operativo hasta trasladarlo a React.

El conector ERPNext asumirá los campos y hooks de documentos nativos. El núcleo mantiene metadatos instalables sin DocTypes de ERPNext; en los sitios ERP se restauran los controles `Link` mediante propiedades específicas del sitio para preservar valores históricos. El proveedor seleccionado se persiste en `HS Site Mode` y solo un procedimiento de migración puede cambiarlo.

## Migraciones

**ERPNext → PMS:** ensayar sobre una copia, reconciliar por entidad, establecimiento, cuenta, tercero, documento abierto, stock y turno; crear un sitio Frappe sin ERPNext, copiar maestros y operaciones aún abiertas, publicar saldos iniciales verificados y conservar el detalle anterior como archivo de consulta dentro de Suite. Activar el libro propio en la fecha de corte y bloquear la escritura en la fuente.

**PMS → ERPNext:** instalar el conector y ERPNext, crear mapas de maestros, trasladar saldos y documentos abiertos sin volver a contabilizar el historial, comprobar cuentas de control y existencias iniciales, y cambiar autoridad al inicio de un período. El historial PMS anterior conserva lectura, impresión y auditoría. Un fallo de conciliación impide el corte.

En ambos sentidos: respaldo conjunto de base, archivos y código; informe de diferencias firmado; ensayo de restauración y plan de reversión antes de mover un hotel real. No se desinstala ERPNext de un sitio con operaciones como mecanismo de migración.

## Estado de implementación y puertas de salida

1. **Iniciado:** interfaz React compilada con shadcn/ui; panel y habitaciones leen proyecciones existentes. Ruta propia y lanzador por modalidad. Las demás pantallas y operaciones siguen en Pages.
2. **Iniciado:** metadatos portables de maestros PMS, mayor y movimientos de stock; reglas de asiento balanceado, reversión y costo promedio con pruebas unitarias. Contabilidad puede registrar asientos manuales y saldos iniciales desde React, importar o exportar el catálogo de cuentas en formato CoA Importer, habilitar monedas por establecimiento y fijar tipos de cambio. Caja, banco e inventario se reservan para sus flujos propios.
3. **Iniciado:** la pantalla React de Caja permite abrir y arquear el turno por moneda, registrar cobros parciales de cuentas internas, anticipos asociados a un cliente, otros ingresos y gastos por efectivo o banco, y crear clientes, medios, categorías y conceptos. Varios medios pueden cobrar una cuenta en transacciones separadas. La pantalla de cuentas por cobrar crea cargos internos y aplica anticipos total o parcialmente, con límites al saldo de ambas partes. Gerencia puede cancelar un cargo sin cobros mediante asiento inverso; uno con aplicaciones queda protegido hasta disponer del flujo de devolución. Cada movimiento genera un asiento PMS y guarda moneda, cambio e importe base. Los cargos internos no son facturas fiscales y todavía no se conectan con folios. El libro PMS aún no recibe las ventas, compras y cierres existentes.
4. **Verificado parcialmente:** instalación nueva en MariaDB con Frappe 16 sin ERPNext y ensayo transaccional de cuentas, asiento inicial, asiento manual, reversión, stock y habitación. También se instaló en Frappe 16 + ERPNext 16 y se verificó que el modo ERP conservó 121 enlaces de maestros. Falta probar actualización de un sitio real existente y migraciones completas.
5. **Pendiente:** facturas fiscales propias, impuestos, integración de cargos con folios, devoluciones y cancelaciones financieras, caja chica, préstamos y capital, compras, reportes y cierre; enrutamiento completo por proveedor y eliminación de hooks ERP del núcleo.
6. **Pendiente:** fiscalidad nicaragüense aprobada, ambas migraciones reales, pruebas de concurrencia e idempotencia y paridad de todas las pantallas React.

Ningún establecimiento existente cambia de proveedor automáticamente. En un sitio nuevo sin ERPNext se debe configurar el catálogo, monedas, tipos de cambio y medios de cobro antes de operar Caja. Las operaciones PMS aún pendientes permanecen deshabilitadas.
