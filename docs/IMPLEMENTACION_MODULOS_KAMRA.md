# Módulos implementados tras revisar Kamra PMS

Referencia local: `C:\Users\Ernesto\Desktop\Proyectos\kamra-pms`, revisión `bb4e36e13f98fd97d589f8dc6239b2940f6dfe2a`. El análisis funcional y la ficha de habitación están en `REVISION_KAMRA_PMS.md` y `REVISION_VISTA_HABITACIONES_KAMRA.md`.

## Tickets de huéspedes

- La página **Tickets** ofrece pendientes, propios, sin responsable, vencidos, resueltos y todos, con paginación de 40 filas.
- Cada ticket admite habitación, estancia, categoría, prioridad, responsable y fecha límite. Si no se fija el plazo, se calcula desde la prioridad: 24, 8 o 2 horas. Las fechas que introduce el usuario se interpretan en la zona horaria del establecimiento y se guardan en la del sitio.
- Se registran creación, asignación, inicio, resolución, reapertura, cancelación, notas y cambio de plazo. El historial se consulta de 100 en 100 eventos. La ficha de habitación muestra sus tickets abiertos y permite crearlos.
- Los comandos usan la transacción e idempotencia de Hospitality Suite. Asignar valida usuario activo, rol y acceso a la misma sede. Supervisor o gerencia cambian responsable y plazo; los demás roles de tickets pueden iniciar, anotar y resolver. Los eventos no aceptan escritura directa por roles operativos.

## Salud del sistema

- La página **Salud del sistema** es de solo lectura para administración. Comprueba base de datos, programador, espacio libre y la configuración financiera obligatoria que exige la operación, además de habitaciones, tarifas y medios de pago.
- Una comprobación no verificable se muestra como `No comprobado`; la vista no presenta ese caso como correcto.

## Crédito empresarial

- La página **Crédito empresarial** muestra límite, plazo de pago, facturas pendientes, cargos devengados todavía sin facturar, vencidos y cupo disponible. El detalle de facturas y la lista de pagadores están paginados.
- La exposición usa los saldos abiertos de `Sales Invoice` en la moneda de la cuenta por cobrar y añade únicamente cargos `Pending` de folios del mismo cliente y compañía. Los cargos `Scheduled` futuros no se tratan como deuda devengada. Se evita contar dos veces los cargos facturados.
- Se impide la salida a crédito sin autorización vigente, por exceso de límite, con facturas vencidas o con exposición en otra moneda sin conversión aprobada. Gerencia puede justificar una excepción por límite o vencimiento; queda en la auditoría. La otra moneda exige revisión contable antes de salir a crédito.
- El plazo configurado determina el vencimiento de nuevas facturas de folios con crédito autorizado. Gerencia puede editar las condiciones desde la vista; el guardado exige motivo y versión vigente.

## Dashboard de cartera

- La página **Cartera** reúne todas las sedes autorizadas: habitaciones activas, ocupadas y bloqueadas ahora, limpieza, mantenimiento y tickets abiertos o vencidos.
- Presenta cuentas por cobrar, vencidos y cargos sin facturar por moneda. No suma NIO y USD ni mezcla indicadores de hotel por noche con los de motel por hora. Cada sede conserva su fecha operativa.
- El botón **Abrir sede** lleva al inicio con ese establecimiento seleccionado.

## Verificación

Los DocTypes y Pages se generan desde `hospitality_suite/schema.py`. En el bench local se migraron `hospitality-acceptance.localhost` y `hospitality.localhost`, se compiló el bundle y se reinició web. Pasaron cuatro pruebas de integración nuevas, seis pruebas de políticas de pago, siete de ficha de habitación y las pruebas JavaScript de Tickets, Cartera y ficha. Se consultaron en el sitio principal las APIs de cartera y salud, y se revisó Tickets en el navegador.

La salud comprueba estado y configuración en el momento de la consulta; no reemplaza una prueba activa de correo, Socket.IO o conciliación contable. El crédito deliberadamente detiene monedas distintas hasta que exista una política de conversión explícita.
