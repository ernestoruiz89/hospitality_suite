# Matriz de alcance obligatorio

Leyenda: P pendiente, I implementado sin prueba ejecutada, V verificado. Ningún módulo se declara completo únicamente por existir su esquema o página. Se detallarán evidencias y limitaciones durante cada fase.

| ID | Requisito | Implementación | Prueba prevista | Estado |
|---|---|---|---|---|
| F01 | Inspección y versión | docs/ARQUITECTURA.md | bench version, estado del repositorio | V |
| F02 | App nativa, migraciones, permisos | schema.py, hooks.py, install.py | sitio limpio y migrate repetido | P |
| F03 | Configuración por compañía/establecimiento | asistente, validación financiera | validación de cuentas, impuestos y almacenes | P |
| F04 | Habitaciones y dimensiones separadas | HS Room, Allocation | ocupación/limpieza/mantenimiento | P |
| F05 | Disponibilidad, grupos y categoría | availability.py | concurrencia, último cupo, límites | P |
| F06 | Tarifas hotel/motel históricas | pricing.py | medianoche, límites, DST y redondeo | P |
| F07 | Reservas, retenciones, cancelación/no show | operations.py, jobs.py | expiración y motivos | P |
| F08 | Entrada, extensión, cambio, salida | Pages, operations.py | aceptación 1,2,6,12 | P |
| F09 | Folios y separación de pagadores | accounting.py | aceptación 3 | P |
| F10 | Factura, anticipo, conciliación | accounting.py | aceptación 9,14 | P |
| F11 | Garantías y devoluciones | accounting.py | devolución y aplicación autorizada | P |
| F12 | Caja, pagos mixtos, multimoneda | cashier.py | aceptación 8,10 | P |
| F13 | Limpieza e inspección móvil | housekeeping Page | salida → disponibilidad | P |
| F14 | Mantenimiento, ropa y objetos | maintenance/services | conflictos y permisos | P |
| F15 | Servicios y existencias estándar | inventory.py | aceptación 13, reversión | P |
| F16 | Cierre diario recuperable | closing.py | repetición, bloqueo y reapertura | P |
| F17 | Reportes/KPI/exportación | reports.py, management Page | fuentes, filtros, denominadores | P |
| F18 | Portal opcional seguro | www, portal.py | desactivado, firma, caducidad | P |
| F19 | Contratos de integraciones | integrations.py | simulaciones identificadas | P |
| F20 | Seguridad compañía/establecimiento/archivos | security.py | aceptación 11, permisos por rol | P |
| F21 | Idempotencia, fallos y tiempo real | service.py, JS | aceptación 4,8,15 | P |
| F22 | Once Pages y accesibilidad | public/js, public/css | flujos reales escritorio/móvil | P |
| F23 | Impresiones operativas y contables | print formats | PDF, privacidad y datos | P |
| F24 | Demo explícita 2×10 habitaciones/roles | demo.py | carga reproducible | P |
| F25 | Documentación/manual/operaciones | docs | instalación, backup, recuperación | P |
| F26 | Instalación/migración sin pérdida | scripts, pruebas | aceptación 16 | P |

## Registro

- 2026-10-19: repositorio vacío, sin AGENTS.md. WSL2 Ubuntu 24.04 con bench existente de otras aplicaciones. Se crea bench separado `/home/frappe/benches/hospitality-bench`. No se migran sitios existentes.
- Integraciones externas de canales, WhatsApp, pasarelas y cerraduras: pendientes de proveedor y credenciales; no bloquean el núcleo.
