# Revisión de entregables

Contraste realizado el 21/10/2026 sobre el árbol de trabajo 0.8.2. TECLADO_Y_FOCO.md acredita su revisión específica; las verificaciones generales de tareas/formularios secundarios, contratos pendientes y recuperación final conservan entradas abiertas. Entregar una guía o una matriz no equivale a completar todo el alcance que describen.

## S18-04 — modelo, estados y flujos

[MODELO_ESTADOS_Y_FLUJOS.md](MODELO_ESTADOS_Y_FLUJOS.md) contiene cuatro vistas de relaciones, dos diagramas de estados y dos flujos operativos. Las vistas cubren los 35 DocTypes propios y sus relaciones principales con ERPNext. Separan reserva, ocupación, limpieza y mantenimiento; muestran tablas hijas, cuentas grupales, documentos nativos y trazabilidad.

El contraste de solo lectura en [delivery-review-diagrams.json](evidence/delivery-review-diagrams.json) comprueba la cobertura de los 35 nombres y cada relación dibujada frente al campo Link/Table real. Incluye hashes del documento y las fuentes revisadas. El contraste de condiciones se realizó leyendo los servicios indicados en el documento: borrador sin cupo, grupo parcialmente ingresado, inspección separada, bloqueo hasta reapertura, cobro/garantía/crédito y cierre autorizado. Los casos nativos referenciados constan aprobados en el JUnit de esta fase. La comprobación estructural no se presenta como un renderizado de Mermaid ni como una prueba nueva de navegador.

## S18-05 — matriz de requisitos

`specification-audit.json` conserva por entrada ID, línea y texto original, implementación, evidencia, estado y pendiente. `AUDITORIA_ESPECIFICACION.md` es su vista legible generada; `REQUISITOS.md` conserva además el resumen por área y las fases históricas. R distingue contraste pendiente; I conserva verificaciones incompletas; P señala una diferencia material; V exige evidencia y ausencia de pendientes en la entrada.

Se ejecuta `tools/specification_audit.py --verify-source` contra el adjunto original. Comprueba huella, secuencia exacta de ID/línea/texto, unicidad, estados válidos y referencias a archivos existentes; exige implementación, evidencia y pendiente vacío para cada V. [delivery-review-matrix.json](evidence/delivery-review-matrix.json) conserva el resultado de esa ejecución y el recuento resultante. Esta revisión acredita la entrega de la matriz, con los pendientes visibles, y no promueve otras funciones por el mero hecho de estar inventariadas.

## S18-06 — instalación y pruebas

README.md identifica las versiones efectivamente probadas y el límite de compatibilidad, instalación con Bench/ERPNext previo, configuración, compilación, migración y pruebas en un sitio designado sin operaciones. Declara la dependencia opcional JUnit, su opción nativa y la normalización de las dos cohortes. Diferencia demostración, aceptación y el sitio histórico en cuarentena. pyproject.toml y hooks conservan la estructura nativa de la app; los assets usan la compilación del bench y la demostración es una acción explícita, separada de la instalación normal.

tools/verify_delivery_guides.py contrasta diez ayudas nativas y tres diagnósticos de solo lectura. [delivery-review-cli.json](evidence/delivery-review-cli.json) conserva opciones/sintaxis, hashes y salidas; las 13 llamadas terminaron correctamente y list-apps registra 0.8.2 tras migrar. La revisión previa había distinguido código 0.8.2 de metadata instalada 0.8.1; la guía explica por qué list-apps debe contrastarse con el código. El helper no instala, migra, restaura ni cambia mantenimiento/scheduler.

## S18-07 — manual por rol

MANUAL.md ofrece una guía inicial por los nueve roles, procesos diarios y recuperación ante conexión perdida, respuesta incierta, documento modificado, errores de stock/factura y correcciones. Distingue huésped/pagador, consulta/confirmación y rol HS de administración del sistema. La referencia externa manual se anota en Solicitudes especiales; no inventa un campo separado. Incluye el manejo de teclado y el resultado accesible del portal.

El recorrido de TECLADO_Y_FOCO.md contrasta los nueve usuarios reales en sus Pages y conserva capturas/documentos: reserva, cobro separado, inspección independiente, reapertura, conciliación, gerencia y auditoría. Las pruebas nativas acreditan las reglas y rechazos descritos. Esta revisión acredita el manual; los requisitos generales S00-02/S04-14/S04-16/S04-20 conservan el contraste del conjunto de tareas secundarias.

## S18-08 — configuración contable

CONTABILIDAD.md distingue registros operativos de documentos/libros ERPNext; documenta cuentas, moneda, impuestos revisados, clasificación por servicio, anticipos, garantías recibidas/aplicadas/devueltas, cobros y arqueos, notas de crédito, liquidaciones, compras, stock y conciliación. El texto usa las modalidades visibles y remite las precisiones/variantes posteriores a sus auditorías, conservando los límites fiscales de configuración por instalación.

Se contrastó con install.py, accounting.py, payment_policies.py, service_accounting.py, treasury.py y reports.py: pertenencia y moneda de las cuentas, validación antes de habilitar finanzas, controladores nativos y conciliación conservando originales. El JUnit final de 380 casos incluye configuración, finanzas, devoluciones, garantías, servicio, tesorería y cierre; la factura/pago de 1530 y las tres filas en OK se consultaron desde Contabilidad. Los ensayos ficticios no se presentan como configuración tributaria de un cliente.

## S18-09 — operación, actualización y reversión

OPERACION.md describe procesos/colas/scheduler, monitoreo y recuperación de trabajos, runtime PDF, respaldos con archivos y clave de cifrado, restauración separada y una secuencia de actualización/reversión. Identifica la ventana de mantenimiento, espera de trabajos, versiones/código/dependencias compatibles y verificación antes de reabrir. Distingue una reversión previa a nuevas operaciones de la recuperación que debe conservar y conciliar operaciones posteriores.

La ayuda nativa acredita los comandos del procedimiento y los diagnósticos ejecutados. Las restauraciones de esta fase conservan datos/archivos y la salud final está comprobada. El caso antiguo de catálogo queda marcado como histórico y no invita a reutilizar el sitio en cuarentena. Esta entrada acredita la guía solicitada; el ensayo final de despliegue/reversión continúa en F26/S19-07.

[delivery-review-guides.json](evidence/delivery-review-guides.json) vincula estas cuatro revisiones con las fuentes, guías, CLI, JUnit y recorrido realmente inspeccionados. Sus hashes acotan la evidencia; no sustituyen la lectura de los procedimientos ni acreditan una instalación/reversión productiva.

## Revisión restante

S18-02 y S18-03 se contrastan posteriormente en [IMPRESIONES_OPERATIVAS.md](IMPRESIONES_OPERATIVAS.md), 0.8.7: inventario instalado en ambos sitios, nueve impresiones, regresión nativa completa y acceso por rol. S18-11/S18-12 se mantienen en la lista de [estado y evidencias](ESTADO_Y_EVIDENCIAS_ENTREGA.md). Las fases de S19, S18-01/S00-01 y las declaraciones globales de completitud requieren terminar las verificaciones abiertas; S19-07 y F26 requieren la recuperación y reversión de la versión final. Ninguna restauración histórica o del fixture se presenta como ese ensayo final.
