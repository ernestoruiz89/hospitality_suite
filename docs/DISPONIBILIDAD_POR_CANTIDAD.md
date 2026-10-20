# Disponibilidad por cantidad — 0.6.3

Reservas → **Buscar disponibilidad** consulta categoría, cantidad de habitaciones, personas por habitación y fechas/horas. El formulario tiene cinco controles, dos columnas en escritorio y una en móvil. Conserva los filtros después de buscar; resultado y acción permanecen en la misma ventana. La lista de opciones se puede desplegar cuando hace falta. Editar un filtro retira el resultado anterior y solicita una nueva búsqueda.

La consulta usa el motor de disponibilidad de reservas y no crea documentos ni conserva cupo. Confirma la cantidad solicitada contra el **cupo simultáneo de categoría**. Las habitaciones libres todo el intervalo son alternativas físicas, y pueden ser más numerosas que ese cupo: una reserva por categoría sin asignación ya consume unidades aunque aún existan varias opciones entre las que elegir.

El escenario de aceptación tiene diez habitaciones y una reserva grupal de nueve unidades sin habitación asignada. La consulta de dos habitaciones informa **«No alcanza el cupo para 2 habitaciones»**, cupo 1/solicitadas 2. Cambiar a una informa **«Hay cupo para 1 habitación»**, cupo 1/solicitadas 1. El desplegable conserva diez alternativas y explica que solo se puede elegir hasta el cupo disponible. La preparación de ese escenario se hizo por API; las consultas y la edición de filtros se probaron desde Page con recepción.

## Reglas y permisos

- Cantidad y personas por habitación deben ser enteros positivos. El servidor rechaza cero, negativos, fracciones, valores no finitos, booleanos y valores fuera del intervalo de Int; no trunca una fracción recibida por API. Personas también debe caber en la categoría.
- Las fechas se interpretan en la zona del establecimiento o con un offset explícito. La salida debe ser posterior a la entrada. Se aplican los intervalos [inicio, fin) y el margen de limpieza del motor compartido.
- Cero cupo es una respuesta normal, con resultado negativo para la solicitud. Un fallo de consulta se presenta como error y permite reintentar; no se convierte en cero cupo.
- Si la categoría tiene cupo, pero los intervalos ya asignados impiden encontrar suficientes habitaciones libres todo el período, la respuesta lo advierte y requiere revisar la asignación física. No promete una asignación continua ni confirma una reserva automáticamente.
- Consultar requiere permiso reserve y acceso al establecimiento. El botón se oculta para los roles sin esa acción. Se rechaza una categoría de otro establecimiento y el acceso a un establecimiento no concedido.
- El resultado usa nombres de categoría y números de habitación; las claves internas se conservan para el contrato API y no se muestran como etiquetas operativas. No incluye huéspedes, precios ni movimientos financieros.
- Las respuestas tardías no sustituyen filtros editados ni un contexto cerrado/cambiado. Las opciones de habitación se despliegan a petición; el texto indica que la limpieza se verifica antes del ingreso.

`availability_search.py` devuelve cupo y alternativas a partir de `availability.capacity`. El endpoint no expira retenciones ni adquiere cupo al consultar: la confirmación sigue validando disponibilidad bajo el bloqueo de establecimiento. La fiabilidad de los reintentos de expiración continúa pendiente en S06-08/S16-10.

Desde 0.6.3 el endpoint `availability_search` devuelve un objeto en lugar de la lista anterior. La Page se actualiza a la vez y API.md documenta los campos y el cambio de contrato. No se activan integraciones externas ni sincronización de canales.

## Pruebas y evidencia

Siete casos nuevos en `hospitality_suite/tests/test_availability_search.py`:

| Caso | Evidencia |
|---|---|
| quantity_and_people_query_is_read_only | Cantidad/personas/nombres de habitación y comparación de trece tablas, incluida Version, sin escrituras por consulta. |
| roomless_group_reduces_quota_and_conversion | Grupo de nueve unidades deja cupo 1 con diez alternativas; al registrar una entrada quedan nueve asignaciones activas, cupo 1 y nueve alternativas, sin contar dos veces la conversión. |
| full_roomless_category_returns_zero | Diez unidades reservadas por categoría devuelven cupo cero sin excepción ni cambios de datos. |
| category_capacity_does_not_promise_a_fixed_room | Diez asignaciones sucesivas de doce minutos dejan cupo simultáneo 9, pero ninguna habitación continua en las dos horas: la consulta de dos requiere revisión de asignación. |
| half_open_cleaning_buffer_edges | Asignación 10:00–11:00 con margen 30: entrada 11:29:59 rechazada/11:30 admitida; salida consultada 09:30 admitida/09:30:01 rechazada al sumar su margen. Sin margen: 10:59:59 rechazada/11:00 admitida; salida 10:00 admitida/10:00:01 rechazada. Se comprueban tanto la consulta como check, usado por los comandos de reservas. |
| invalid_numbers_and_nonpositive_intervals | Entradas inválidas, ocupación superior a capacidad e intervalos de duración cero/negativa rechazados. |
| scope_and_roles | Categoría ajena, limpieza, contabilidad y Guest rechazados; recepción autorizada consulta y no puede acceder a un establecimiento nuevo sin concesión. |

El primer ensayo corrigió dos supuestos del fixture: la demostración tiene diez habitaciones por establecimiento y recepción tiene acceso a ambos establecimientos demo. Las pruebas ahora obtienen el inventario de la categoría y usan un establecimiento sin concesión para el rechazo. La aplicación no se alteró para acomodar esos supuestos. El segundo ensayo aprueba siete casos; la batería conjunta posterior aprueba **243 pruebas: 229 de integración y catorce puras**, sin fallos/errores. Cuatro casos JavaScript nuevos cubren forma/petición, cupo cero/fragmentación, respuestas obsoletas y fallos/contexto; la batería completa aprueba **49 casos: 47 Desk y dos portal**.

Las mejoras finales de fecha/gramática y separación del resultado se comprobaron con JavaScript/navegador después de la batería de backend, sin cambiar Python funcional. No se atribuye a esa batería una validación visual. Las sesiones acreditadas son:

- `118-disponibilidad-cantidad-escritorio.jpg`: solicitud de dos habitaciones frente a cupo uno, con los cinco filtros y la acción explícita.
- `119-disponibilidad-cantidad-movil.jpg`: solicitud de una, resultado positivo, fechas y botón completos. En viewport 390×844, contenido de 374 px, cuerpo con clientWidth/scrollWidth 372 y botón de 342×44 px; no hay desborde horizontal.
- `120-disponibilidad-filtros-editados.jpg`: cambia cantidad de una a dos; el resultado anterior se retira hasta volver a buscar.
- `121-disponibilidad-opciones.jpg`: diez números de habitación y explicación del límite de cupo; no se presentan como diez unidades disponibles.

`availability-browser.json` conserva observaciones y geometría. Las capturas son JPEG nativos del navegador; la captura móvil mide 390×787 y contiene el modal completo. `availability-items-ui.json` contrasta el fixture después de las consultas de Page/API: las mismas **72 tablas con Version** que después de la preparación y cero estancias/cargos/cobros/turnos/facturas/asientos/cierres. La reserva y sus nueve asignaciones proceden únicamente de la preparación API. La sesión se cerró y se restableció el viewport al terminar.

## Conservación y alcance

Antes de actualizar se conservaron respaldos nativos con archivos y huellas de columnas/archivos. Ambos sitios se migraron y los assets se construyeron para 0.6.3; web y worker principales se reiniciaron. Después del recorrido se detuvo 8089 y se restauró el respaldo original del sitio de aceptación con archivos. La comparación posterior incluye las columnas nuevas y Version: aceptación **72 tablas/195 filas** y principal **72 tablas/1191 filas/dos archivos privados** idénticos a sus líneas de base. La comprobación de la restauración sobre 71 tablas conserva 185 filas; aceptación queda sin operaciones y con scheduler pausado. La fecha principal permanece 19/10 y su cierre no se confirmó.

`availability-upgrade.json`, `availability-ux-restored.json` y `availability-final-state.json` conservan las comprobaciones; `availability-feature.json` relaciona los casos, fuentes y capturas con S06-01/S05-07/S16-03. Se mantiene la excepción histórica acotada de Company acreditada antes de esta fase, sin sustituir huellas para ocultar cambios. La restauración de esta revisión no sustituye la recuperación final de F26.

S06-01 pasa P→V y S05-07/S16-03 pasan I→V. Quedan **130 V, dieciocho I, dos P y 68 R** de las mismas 218 entradas/huella. Las dos diferencias materiales restantes son borradores persistentes y explicación de la tarifa histórica en la cuenta. Continúan las otras verificaciones de UX, roles, contador, identificación, trabajos, contratos, demo, traducciones y recuperación final. Este recorrido no acredita todos esos flujos ni tiempo real.

Para repetir las pruebas, use solo el sitio de integración designado, vacío, y una ruta XML nueva:

```sh
bench --site hospitality-acceptance.localhost run-tests --module hospitality_suite.tests.test_availability_search
bench --site hospitality-acceptance.localhost run-tests --app hospitality_suite --junit-xml-output /ruta/nueva/resultados.raw.xml
env/bin/python apps/hospitality_suite/tools/normalize_junit.py /ruta/nueva/resultados.raw.xml /ruta/resultados.xml
env/bin/python apps/hospitality_suite/tools/service_ux.py verify --phase availability
env/bin/python apps/hospitality_suite/tools/periodic_upgrade.py verify --phase availability
env/bin/python apps/hospitality_suite/tools/verify_acceptance_site.py --phase availability
```

Ejecute las baterías de integración de forma secuencial y confirme la terminación de una antes de iniciar otra. Los verificadores reutilizan las líneas de base privadas fijadas; no vuelva a ejecutar before/prepare para reemplazarlas. Las pruebas no dejan una demostración operativa persistente; S17-17 conserva ese entregable pendiente.
