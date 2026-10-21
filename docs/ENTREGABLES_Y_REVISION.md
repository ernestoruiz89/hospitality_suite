# Revisión de entregables

Contraste iniciado el 21/10/2026 sobre el árbol de trabajo 0.8.2. La revisión de teclado continúa por separado en TECLADO_Y_FOCO.md. La aceptación integral, las integraciones pendientes y la recuperación final de despliegue conservan sus entradas abiertas.

## S18-04 — modelo, estados y flujos

[MODELO_ESTADOS_Y_FLUJOS.md](MODELO_ESTADOS_Y_FLUJOS.md) contiene cuatro vistas de relaciones, dos diagramas de estados y dos flujos operativos. Las vistas cubren los 35 DocTypes propios y sus relaciones principales con ERPNext. Separan reserva, ocupación, limpieza y mantenimiento; muestran tablas hijas, cuentas grupales, documentos nativos y trazabilidad.

El contraste de solo lectura en [delivery-review-diagrams.json](evidence/delivery-review-diagrams.json) comprueba la cobertura de los 35 nombres y cada relación dibujada frente al campo Link/Table real. Incluye hashes del documento y las fuentes revisadas. El contraste de condiciones se realizó leyendo los servicios indicados en el documento: borrador sin cupo, grupo parcialmente ingresado, inspección separada, bloqueo hasta reapertura, cobro/garantía/crédito y cierre autorizado. Los casos nativos referenciados constan aprobados en el JUnit de esta fase. La comprobación estructural no se presenta como un renderizado de Mermaid ni como una prueba nueva de navegador.

## S18-05 — matriz de requisitos

`specification-audit.json` conserva por entrada ID, línea y texto original, implementación, evidencia, estado y pendiente. `AUDITORIA_ESPECIFICACION.md` es su vista legible generada; `REQUISITOS.md` conserva además el resumen por área y las fases históricas. R distingue contraste pendiente; I conserva verificaciones incompletas; P señala una diferencia material; V exige evidencia y ausencia de pendientes en la entrada.

Se ejecuta `tools/specification_audit.py --verify-source` contra el adjunto original. Comprueba huella, secuencia exacta de ID/línea/texto, unicidad, estados válidos y referencias a archivos existentes; exige implementación, evidencia y pendiente vacío para cada V. [delivery-review-matrix.json](evidence/delivery-review-matrix.json) conserva el resultado de esa ejecución y el recuento resultante. Esta revisión acredita la entrega de la matriz, con los pendientes visibles, y no promueve otras funciones por el mero hecho de estar inventariadas.

## Revisión restante

Los otros entregables de S18 y las fases de S19 deben contrastarse individualmente. En particular, S18-01/S00-01 y las declaraciones globales de completitud requieren terminar las verificaciones abiertas; S18-09/S19-07 y F26 requieren la recuperación y reversión de la versión final. Ninguna evidencia histórica de restauración se presenta como ensayo final de 0.8.2.
