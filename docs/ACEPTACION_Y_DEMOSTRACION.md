# Aceptación por roles y demostración operativa — 0.8.0

S17-17/S17-18 y el entregable S18-10 se contrastan individualmente. Se ejecuta el recorrido completo con un usuario que recibe explícitamente HS Receptionist y HS Cashier. Los permisos predeterminados de Recepción no se amplían. No se sustituye la revisión pendiente de todas las tareas secundarias ni de los once formularios/Pages por este recorrido.

## Generador explícito y repetible

La instalación normal conserva `after_install`/`after_migrate` sin invocar el generador. `before_tests` prepara solamente la base vacía de integración. `demo.seed` sigue creando dos establecimientos ficticios, Hotel y Por tiempo, diez habitaciones en cada uno, tarifas distintas, huéspedes, existencias y nueve usuarios por rol. `demo_scenario.build` agrega operaciones persistentes y distinguibles: en cada establecimiento reserva futura para 106, estancia activa en 107 y un agua entregada con cargo y salida estándar de inventario. No simula cobros ni llama proveedores externos.

En un sitio local dedicado **ya instalado con Frappe, ERPNext y hospitality_suite**, separado del sitio vacío de integración:

```sh
cd /ruta/al/bench
bench --site demo.localhost set-config allow_tests true
bench --site demo.localhost set-config hospitality_allow_demo true
bench --site demo.localhost execute hospitality_suite.demo.seed
bench --site demo.localhost execute hospitality_suite.demo_scenario.build
```

El segundo comando de carga requiere Administrator, ambos indicadores y un nombre de sitio terminado en `.localhost`. La base debe ser la ficticia original: compañía, modalidad, diez números de habitación y acceso de los usuarios por rol. En el primer recorrido rechaza reservas, estancias, cargos, caja o consumos previos ajenos a ese escenario. No se debe habilitar como parte de una instalación productiva ni se ofrece como endpoint público.

Un marcador HS Request por establecimiento conserva las referencias y fechas aceptadas de la versión 1. Repetir devuelve las mismas operaciones; informa su estado actual y no rehace reservas, cargos o salidas de stock. Si después se cancela una reserva, la repetición conserva esa cancelación. Una referencia ausente o ajena se rechaza, sin crear una copia. Ambos establecimientos se preparan en una transacción; una interrupción después de la segunda salida de stock revierte todo y permite reintentar. La función no hace commits intermedios. Las contraseñas de los usuarios base permanecen en el archivo privado creado por seed, nunca en Git ni en la respuesta del escenario.

La demostración queda con operaciones hasta que se cambien por sus flujos o se restaure un respaldo. Para ejecutar la batería de integración, use otro sitio designado **sin operaciones**; no intente reutilizar el escenario ocupado. La validación fue sobre la base instalada de aceptación; esta fase no es un nuevo ensayo de instalación desde cero ni sustituye la recuperación final F26.

## Recorrido real desde Pages

`tools/role_acceptance_ux.py prepare` se limita a hospitality-acceptance.localhost, su base de datos designada, scheduler pausado e indicadores de prueba. Guarda la comparación previa, carga ambos escenarios por el generador y comprueba que repetir no cambia ninguna de las 72 tablas. Crea un usuario ficticio adicional con los dos roles explícitos y acceso al hotel. Deja H101 vacía para las acciones del navegador. Las operaciones de 106/107 y el usuario son preparación por comandos, no acciones hechas desde Page.

El navegador ejecuta, con ese mismo usuario:

1. Reservar H101 por una noche desde su tarjeta. Seleccionar pagador/huésped y revisar C$ 1,500.00 antes de confirmar. El canal se identifica como Aceptación Pages.
2. Registrar entrada desde Ver reserva; H101 queda alojada con su saldo.
3. Agregar un agua desde la estancia y confirmar su entrega desde Consumos. Se genera C$ 30.00 y una sola salida de stock.
4. Extender una noche desde el panel, revisar y aceptar C$ 1,500.00 adicionales. El cargo anterior permanece.
5. Abrir turno con fondo cero, revisar y confirmar C$ 3,030.00 en efectivo desde la cuenta. Se observa después la respuesta confirmada y el saldo cero.
6. Registrar salida. El registro persistido queda Checked Out y genera una tarea de limpieza. Cerrar el turno con C$ 3,030.00 contados; diferencia cero.

Limpieza entra en otra sesión y trabaja en móvil 390×844: inicia H101, marca baño/cama/minibar/superficies y solicita inspección. Conserva sus observaciones y no recibe acciones financieras. Con la política original de inspección activa, Supervisión entra en otra sesión y completa la revisión desde **la Page de Limpieza**. Recepción muestra H101 limpia y sin ocupación; no se desactiva la política ni se concede inspección al rol de limpieza.

Contabilidad entra por su propia sesión, filtra Conciliación por la estancia H101 y ve los tres cargos y el cobro, todos OK y sin diferencia. Rastrea además la factura y el pago **nativos** como documentos de contabilidad: factura ACC-SINV-2026-00001 pagada, estancia/cuenta/reserva vinculadas; ACC-PAY-2026-00001 presentado, C$ 3,030.00 asignados a esa factura y cero pendiente. Las tareas operativas anteriores se realizaron en Pages; esta lectura contable estándar es deliberada.

Gerencia entra en su sesión y agrupa Producción por H101: importe e ingreso neto facturado C$ 3,030.00, sin facturar cero y tres orígenes. Los indicadores de la fecha operativa histórica 19/10 no se hacen pasar por los ingresos registrados el 20; el reporte no limita esas fechas y la fecha operativa no se avanza ni cierra. Todas las sesiones terminan en Login, se restablece el viewport y se cierran las dos pestañas temporales.

## Evidencia y límites

La batería final aprueba **373 pruebas nativas: 359 de integración y catorce puras**. Ocho nuevas: siete del generador (autorización, datos/stock, repetición exacta, interrupción tras stock, cambios posteriores conservados, operaciones ajenas y referencia corrupta), y un recorrido de comandos reales con los cinco roles. Este último prueba también que el recepcionista predeterminado continúa sin poder abrir un turno. Un primer pase de demo tenía una consulta de prueba a una columna inexistente; se corrigió para seguir el enlace real `HS Service Request.charge`. No fue una escritura de libros ni un defecto corregido ocultando un resultado. Las **136 pruebas JS anteriores se vuelven a ejecutar y aprueban**; no se añaden regresiones JS ni cambia la interfaz de producción en esta fase.

`role-acceptance-browser.json`, las capturas 228–242 y `role-acceptance-items-ui.json` separan observaciones de navegador y comprobación de documentos persistidos. La captura 234 y su instantánea son **transitorias, anteriores a la actualización del tablero**; no acreditan salida confirmada. La tarea posterior, la liberación observada y la aserción de Checked Out sí la acreditan. Algunos localizadores tuvieron timeout o encontraron el botón de página y el del diálogo; se volvió a observar y se usó el diálogo visible. Los timeouts de herramientas no se presentan como fallos del producto ni como confirmaciones. Socket.IO conserva fallback en el servidor temporal; este recorrido no acredita su transporte.

La inspección final confirma una factura y un pago por C$ 3,030.00, saldo/diferencia cero, limpieza completada e inspeccionada y conciliación OK. Hay **cuatro Stock Entry / cuatro Stock Ledger Entry / doce GL Entry**: una entrada inicial ya existente, dos salidas de los escenarios y una del consumo de H101, más la contabilización nativa de factura/pago. No se exige inventario inicial cero ni se escriben libros directamente. Repetir el generador después del recorrido conserva todas las tablas, incluido el trabajo del usuario.

Se restaura el respaldo original con archivos: aceptación 71 tablas/185 filas, 72/195 con Version, sin operaciones. Principal conserva 72 tablas/1191 filas, dos archivos privados y fecha operativa 19/10; permanece la excepción histórica limitada a cachés Company. Núcleos limpios, web/worker actualizados, servicios/HTTP activos, 8089 apagado y mismo PDF resumido sin nuevo render. No se activa sincronización externa.

S17-17 y S17-18 I→V; S18-10 R→V: **188 V, 8 I, 0 P y 22 R; 30 entradas sin cierre**, mismas 218 entradas y huella original. S00-02/S04-14/S04-20 continúan abiertos para el conjunto de tareas por rol; S04-16/S04-17 para formularios y teclado; S01-04 para literales secundarios, y siguen pendientes los contratos restantes, entregables/fases y F26. El objetivo continúa activo.
