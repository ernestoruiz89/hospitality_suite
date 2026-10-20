# Contraste de reservas, tarifas y estancias

Revisión del 20/10/2026 sobre el código de aplicación de `43ce506` (0.6.2), sin cambios de aplicación en esta fase. Se revisan las **32 entradas R** de las secciones 6, 7 y 8; S08-10 ya era V y se conserva sin modificar. El texto, las líneas y la huella de las 218 entradas originales permanecen intactos. La matriz canónica y `evidence/reservations-audit.json` relacionan individualmente cada entrada con archivos, casos aprobados y pendientes.

Resultado del bloque: **26 V, tres I y tres P**. Inventario completo: **127 V, veinte I, tres P y 68 R**. R significa contraste individual pendiente; estos números no son un porcentaje de desarrollo ni una fecha de entrega. El objetivo sigue activo.

## Diferencias confirmadas

- **S06-01, consulta por cantidad.** Buscar disponibilidad admite fechas, horas, categoría y personas. La API no recibe una cantidad de habitaciones solicitadas y la Page no ofrece ese filtro ni informa si alcanza el cupo para ese número. La reserva grupal sí valida todas sus líneas mediante el motor compartido. Falta completar la consulta sin crear reservas ni confundir habitaciones candidatas con cupo simultáneo.
- **S06-03, borrador persistente.** Draft está declarado en HS Booking, pero reserve crea Hold o Confirmed. No existe una acción API/Page para guardar y retomar Draft, y el controlador impide crear reservas directamente fuera del motor. El borrador del formulario entre pestañas no satisface este requisito. Falta guardar sin ocupar cupo y recalcular disponibilidad/precio al confirmar.
- **S07-09, cálculo al revisar la cuenta.** La cotización previa contiene explicaciones; los snapshots históricos conservan reglas e importes. La Page y el impreso de cuenta muestran conceptos/importes, pero no explican el cálculo de la tarifa aplicada. Se requiere una presentación legible por noche o bloque, con reglas históricas, suplementos y ajustes, sin recalcular cargos anteriores con tarifas actuales.

La cuenta imprimible **sí incluye facturas/impuestos, cobros, anticipos, garantías y saldo**. La prueba nueva comprueba su HTML nativo con alojamiento 3000, descuento 100, agua 30, neto 2930, impuesto sintético 439.50 y total 3369.50. La configuración nativa redondea el importe exigible a 3370; un pago de 500 deja saldo 2870 y la garantía de 200 permanece separada. Por tanto S08-04 queda V: no se atribuye una ausencia funcional basándose solo en el panel compacto. Al mejorar la explicación de cuenta conviene mostrar también el ajuste de redondeo de 0.50 y el total exigible; ahora el impreso presenta total y saldo sin esa línea explicativa.

## Verificación aún incompleta

- **S06-08, fiabilidad de retenciones.** Expiración, liberación e idempotencia están probadas. La evidencia RQ anterior acredita fallo, rollback y recuperación. Falta la política/prueba de reintentos limitados automáticos del mismo trabajo, relacionada con S16-10; un nuevo despacho periódico o una recuperación manual no la sustituyen.
- **S07-10, contador tras recarga.** El servidor conserva autoridad del tiempo/importe y la evidencia anterior muestra el contador avanzando. Falta acreditar explícitamente una recarga y un reloj cliente desfasado conservando el vencimiento y sin cambiar importes o estados.
- **S08-02, datos exigidos y corrección desde Pages.** Existen registro/acompañantes, capacidad y validación de identificación en el servidor. bootstrap omite guest_id_required, que el formulario consulta para situar identificación entre los datos principales. Falta completar la edición del huésped existente desde Page y aceptar el flujo con política activada/desactivada sin duplicar la persona.

Estos pendientes se suman a la aceptación general de UX y roles que ya conservaban S00-02/S04-14/S04-20. La revisión de backend no acredita por sí sola todas las acciones habituales, navegación por teclado, claridad de formularios ni estados secundarios.

## Pruebas nuevas y alcance

Se añadieron siete casos en `hospitality_suite/tests/test_booking_rate_audit.py`, ejecutados contra los DocTypes y documentos nativos de ERPNext:

| Caso | Aserciones principales |
|---|---|
| season_weekday_payer_plan_and_priority | Lunes estacional 2050 y martes negociado 1200; total 3250. Sin contrato 3800; contrato de igual prioridad gana a regla general; dos contratos empatados se rechazan. Servicio incluido de la noche correcta, sin sumar reglas concurrentes. |
| motel_blocks_fraction_boundaries_and_night_window | Bloques de 2/3/6/12/24 horas; fin exacto y diez minutos de gracia sin extra; un segundo después inicia fracción de quince minutos; extremos de la siguiente fracción. Ventana nocturna [21:00, 06:00) con ambos límites y segundo anterior. |
| active_mode_change_requires_mixed_property_and_accepted_new_price | Hotel rechaza Motel en establecimiento no mixto; en mixto, cambio explícito a otra habitación requiere aceptar el ajuste -1050. Total 450, snapshot nuevo Motel, segmento histórico Hotel y continuidad entre segmentos. Es la regla actual de cambio con traslado, no conversión directa en la misma habitación. |
| hotel_early_arrival_exact_grace_and_fraction_boundaries | Entrada a las 13:50 para horario 14:00 sin cargo; 13:49:59 cobra 60; límite de fracción 13:20 y segundo anterior 120. |
| calendar_month_year_and_dst | Noches de hotel a través de mes, año y cambios horarios de primavera/otoño; horas ambiguas/inexistentes rechazadas sin offset; dos offsets explícitos del mismo reloj representan instantes separados por una hora. Se combina con la prueba pura de motel por tiempo transcurrido y días operativos de 23/25 horas. |
| printed_account_includes_native_tax_discount_services_payment_and_guarantee | Factura nativa, redondeo configurado, cobro y pasivo de garantía; importes y encabezados presentes en el HTML de HS Cuenta de estancia. No se generó ni revisó un PDF nuevo en esta fase. |
| after_checkout_credit_requires_permission_reason_native_return_and_audit | Después de salir, recepción rechazada y gerente sin motivo rechazado; gerente con motivo crea devolución estándar de -1500 referenciada a la factura. Estancia permanece Checked Out y auditoría conserva actor, motivo y nota. |

La primera ejecución parcial corrigió dos expectativas del fixture: el cambio congelado exactamente al instante de entrada producía un segmento de duración cero, y el saldo debía respetar el redondeo nativo de 0.50. El cambio se prueba con reloj fijo a las 10:00 y traslado un minuto después, para evitar cruzar de noche si la batería se inicia cerca de medianoche; se habilita una cama extra en la categoría del fixture y se comprueba explícitamente el redondeo; no se modificó la aplicación para adaptar esas expectativas. La segunda ejecución parcial aprueba siete casos y la batería conjunta posterior aprueba **236 casos: 222 de integración y catorce puros, sin fallos, errores ni omisiones**. `evidence/reservations-native-tests.log/xml` conserva la ejecución conjunta.

También se contrastaron las aserciones existentes sobre grupos/cupo, modificación/cancelación/no presentación, snapshots, extras/incluidos, impuestos/precisiones, crédito, anticipo/liquidación, limpieza y reversión estándar. La evidencia histórica de carreras de dos conexiones, grupo desde Pages, plan incluido, contador y formatos está identificada por entrada. No se repitieron esas sesiones de navegador ni se presenta su evidencia como nueva. Los 45 casos JavaScript anteriores corresponden al mismo código de aplicación sin cambios; no se volvió a ejecutar esa batería en esta fase.

## Conservación y reproducción

La batería se ejecuta solo en `hospitality-acceptance.localhost`, designado para integración, sin operaciones previas y con scheduler pausado. Cada caso revierte su transacción. Al terminar se compararon todas las columnas y archivos con la línea de base privada de la fase anterior: **72 tablas/195 filas** de aceptación y **72 tablas/1191 filas/dos archivos privados** principales idénticos. Durante una repetición se iniciaron por error dos baterías sobre el mismo sitio: una terminó con seis errores de bloqueo y la adicional se canceló. Se descartaron ambas como evidencia. Se guardó un respaldo de diagnóstico con archivos, se restauró nativamente el respaldo original fijado de la fase board y se comprobó la igualdad de las tablas antes de repetir. La batería final se ejecutó una sola vez de forma secuencial y aprueba los 236 casos; la comparación de conservación indicada es posterior a esa ejecución. `evidence/reservations-recovery.json` acredita diagnóstico, restauración y conservación sin cambiar la línea de base. Aceptación queda sin reservas, estancias, cargos, cobros, turnos, facturas, asientos ni cierres.

La demostración principal sigue con fecha operativa 19/10/2026; su cierre no se confirmó. La excepción histórica de Company se limita a las dos cachés nativas y modified ya acreditados; las 36 tablas nativas coinciden con el respaldo previo. HTTP 200 en 8086, Socket.IO/Redis activos y 8089 apagado. `evidence/reservations-conservation.json` conserva los resultados de las comprobaciones posteriores sin sustituir huellas iniciales.

Desde el bench WSL, con una ruta XML nueva porque Frappe agrega documentos por cohorte:

```sh
bench --site hospitality-acceptance.localhost run-tests --module hospitality_suite.tests.test_booking_rate_audit
bench --site hospitality-acceptance.localhost run-tests --app hospitality_suite --junit-xml-output /ruta/nueva/resultados.raw.xml
env/bin/python apps/hospitality_suite/tools/normalize_junit.py /ruta/nueva/resultados.raw.xml /ruta/resultados.xml
env/bin/python apps/hospitality_suite/tools/periodic_upgrade.py verify --phase board
env/bin/python apps/hospitality_suite/tools/verify_acceptance_site.py --phase board
```

Los dos verificadores comparan la línea de base privada conservada y no deben ejecutarse con before para reemplazarla. `evidence/reservations-audit.json` es un contraste histórico del código indicado; las ausencias registradas deberán volver a contrastarse después de implementarlas. La sincronización con Airbnb, Booking y otros canales sigue pendiente por instrucción del usuario; no se implementó ni activó.
