# Estado de entrega y evidencias — revisión 21/10/2026

La app continúa en desarrollo. Esta lista diferencia funciones completadas con evidencia individual, limitaciones verificadas y trabajo externo pendiente. La [auditoría original](AUDITORIA_ESPECIFICACION.md) mantiene las mismas 218 entradas, texto y huella. **198 V, seis I, cero P y catorce R: veinte entradas sin cierre**. V acredita solo el texto de su entrada; la entrega completa y la aptitud para producción siguen sin acreditarse.

## Funciones completadas con evidencia individual

| Área | Función acreditada | Evidencia de alcance y condiciones |
|---|---|---|
| Reservas | Cupo por cantidad, intervalos y concurrencia; borradores persistentes y confirmación con precio aceptado | [Disponibilidad](DISPONIBILIDAD_POR_CANTIDAD.md), [borradores](BORRADORES_DE_RESERVA.md), [auditoría de reservas/estancias](AUDITORIA_RESERVAS_TARIFAS_ESTANCIAS.md) |
| Estancias | Llegadas, salidas, cuentas y grupos; extensiones/cambios con precio y asignaciones conservadas | [Tablero](ESTANCIAS_Y_LLEGADAS.md), [tarifa histórica](EXPLICACION_TARIFA_HISTORICA.md), entradas V individuales de S06/S07 |
| Caja y contabilidad | Cobros, anticipos, garantías, devoluciones, liquidaciones y conciliación mediante documentos nativos | [Auditoría de Caja/Contabilidad](AUDITORIA_CAJA_CONTABILIDAD.md), [facturación desde Pages](FACTURACION_DESDE_PAGES.md), [configuración contable](CONTABILIDAD.md) |
| Limpieza y mantenimiento | Checklist, inspección separada, bloqueo hasta reapertura, conflictos y trazabilidad | [Auditoría de limpieza/mantenimiento](AUDITORIA_LIMPIEZA_MANTENIMIENTO.md) |
| Servicios e inventario | Preparación/entrega/devolución única, stock y ERPNext nativo; funcionamiento sin HRMS | [Auditoría de servicios/inventario](AUDITORIA_INVENTARIO_SERVICIOS.md) |
| Cierre y bitácora | Fecha/corte explícitos, pendientes, resumen congelado y excepciones conservadas | [Fecha y cierre](FECHA_Y_PENDIENTES_CIERRE.md), [bitácora](BITACORA_Y_CIERRES.md) |
| Seguimiento | Historial de habitación, reloj del servidor y recuperación de trabajos | [Historial](HISTORIAL_HABITACIONES.md), [contador](CONTADOR_Y_RELOJ.md), [trabajos/reintentos](TRABAJOS_Y_REINTENTOS.md) |
| Acceso e interfaz | Roles/establecimientos, idioma, teclado y foco; disponibilidad con colores y textos | [Seguridad](AUDITORIA_SEGURIDAD.md), [idioma](IDIOMA_Y_ETIQUETAS.md), [teclado](TECLADO_Y_FOCO.md), [disponibilidad visual](DISPONIBILIDAD_VISUAL_Y_LIMITES.md) |
| Portal opcional | Solicitud/confirmación por token y aceptación con datos ficticios | [Aceptación/demostración](ACEPTACION_Y_DEMOSTRACION.md), [API](API.md) |
| Documentación | Modelo/estados, matriz y guías por rol, instalación, contabilidad y operación | [Revisión de entregables](ENTREGABLES_Y_REVISION.md) |

La tabla agrupa funciones acreditadas; no convierte en V las revisiones generales de todas las tareas, formularios o entregables. Las condiciones financieras y permisos siguen dependiendo de la configuración real de cada establecimiento.

## Limitaciones y trabajo pendiente verificados

| Estado | Alcance pendiente | Referencia |
|---|---|---|
| I | S00-02/S04-14/S04-20: contrastar las tareas habituales y secundarias del conjunto de roles/Pages | [Matriz](REQUISITOS.md) y [siguiente fase](PENDIENTES.md) |
| I | S04-16: demás reglas por campo y estados de vistas secundarias; selector manual de categoría/habitación expone códigos/filtros técnicos y el vacío de reservas confirmadas debe distinguirse de borradores pendientes | [Validación](VALIDACION_FORMULARIOS.md), [actividad/recuperación](ACTIVIDAD_Y_RECUPERACION_PAGES.md), capturas 298/305 |
| Observación abierta | Algunos clics inmediatos durante el cierre visual de un diálogo no abren la siguiente acción; después de desaparecer la capa nativa sí continúa | Recorrido de actividad/recuperación, sin atribuir una causa completa ni afirmar una solución total |
| I | S14-05/S14-07: completar contraste de contratos y simulaciones de las demás familias externas | [API](API.md), contratos de integrations.py; no exige activar proveedores |
| R | S00-01/S01-12, S18-01/S18-02/S18-03 y S19-01 a S19-09: contraste individual de completitud, artefactos/impresiones y fases | Auditoría original con pendiente explícito |
| Ensayo final | F26/S19-07: instalación, actualización y reversión de la versión final; las restauraciones de fixtures no lo sustituyen | [Operación](OPERACION.md) y matriz |

## Integraciones externas pendientes

| Familia | Entregado actualmente | Lo que falta antes de operar |
|---|---|---|
| Pasarela de pago | Contrato abstracto y doble de prueba que nunca liquida dinero; receptor firmado/idempotente/minimizado probado | Seleccionar proveedor, credenciales y entorno de pruebas; adaptar y validar liquidación, referencias y conciliación. Ninguna pasarela real activada |
| Correo / WhatsApp | Contrato de mensajería; no hay envío externo activado | Completar adaptador/simulación, seleccionar proveedor, credenciales y configuración del remitente |
| Cerraduras | Contrato de concesión/revocación; no hay apertura física activada | Completar adaptador/simulación, seleccionar dispositivo/proveedor, acceso de pruebas y credenciales |
| Airbnb / Booking y otros canales | Contrato abstracto conservado | **Sincronización aplazada por instrucción del usuario. No implementarla ni activarla ahora.** No es un bloqueo de credenciales de esta fase |

Las simulaciones son pruebas identificadas; no se ofrecen como integraciones operativas. Los secretos del entorno local permanecen en archivos privados y no forman parte de las evidencias públicas.

## Evidencias realmente ejecutadas — S18-11

- Última fase 0.8.5: **196 pruebas JavaScript, 193 Desk/tres portal**, compilación y recorrido inicial de 21 eventos con Caja/Recepción, más tres eventos de regresión final después de restaurar el primer escenario. Demoras de ocho segundos y un 503 sintéticos explícitos. [Resultados](evidence/page-activity-js-tests.log), [traza inicial](evidence/page-activity-browser.json), [traza final](evidence/page-activity-final-browser.json), [documentos iniciales](evidence/page-activity-items-ui.json), [borrador final](evidence/page-activity-final-items-ui.json), capturas 294–306. La 298 registra un defecto pendiente; la 301 motivó la corrección visible en 305. Las observaciones de ambas trazas conservan su alcance.
- Regresión nativa conservada de **beac44d / 0.8.2: 380 casos**, 366 de integración y catorce puros, sin fallo/error/omitidos en [JUnit](evidence/keyboard-review-native-tests.xml) y [salida original](evidence/keyboard-review-native-tests.log). No se vuelve a ejecutar esa batería en 0.8.5. El Python de producción solo cambia versión desde aquella revisión; esto acota la pertinencia de la evidencia, sin probar el frontend nuevo mediante pruebas antiguas.
- La fase anterior de colores conserva 191 JS y once capturas, con H101 reservada y H105 ocupada en rojo; [verificación 0.8.4](evidence/action-context-verification.json). Las pruebas y capturas históricas conservan su versión, condiciones y alcance.
- La [verificación de entrega](evidence/delivery-status-review.json) vincula hashes, versiones/alcance, entradas V/I/R y cada referencia de esta lista. No ejecuta UI ni altera datos. La verificación de fase acredita restauración y conservación de datos/archivos, no la entrega productiva completa.

S18-11 acredita la entrega de evidencias de pruebas realmente realizadas. S18-12 acredita esta lista diferenciada. Ninguna de las dos elimina las veinte entradas abiertas ni declara terminado el objetivo.
