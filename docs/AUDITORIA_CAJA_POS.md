# Arqueo y cobros POS nativos

La versión 0.4.1 incorpora al esperado del turno los cobros de Sales Invoice con is_pos de ERPNext 16.51.1. Estos documentos contabilizan directamente sus medios de pago; no se crea un HS Payment ni Payment Entry adicional. El módulo nativo POS Invoice y su consolidación no forman parte de este recorrido.

## Fuente del efectivo y controles

native_pos.movements proyecta las cuentas de pago y vuelto de cada factura presentada desde GL Entry, en moneda de cuenta y con signo. cashier.expected suma únicamente los medios configurados como efectivo. Las devoluciones restan; las cancelaciones dejan de aportar. Una transferencia o tarjeta no incrementa el efectivo físico. El cierre diario reutiliza esta misma lectura y conserva su fecha operativa tomada de auditoría, sin duplicar cobros.

Una factura POS del establecimiento exige turno abierto, responsable autorizado y un medio inequívoco por cuenta/modo de pago. La referencia bancaria y el vuelto en efectivo respetan la configuración. La validación toma el bloqueo del establecimiento antes de leer el turno y los medios actuales. Un cajero no puede utilizar el turno de otro responsable sin autorización gerencial. Las lecturas siguen limitadas al establecimiento autorizado.

Los medios utilizados en facturas POS, incluso canceladas, conservan cuenta, moneda y clasificación; no se pueden eliminar para cambiar la historia. Los medios que comparten una cuenta deben coincidir en su clasificación de efectivo. La comprobación de uso también se serializa con el establecimiento. Una factura histórica sin turno o sin correspondencia inequívoca aparece en Conciliación; no se le asigna un turno por aproximación.

Un conteo con diferencia conserva el esperado y contado, el motivo y estado de revisión. El cajero no puede aprobarlo. El permiso específico cash_approve permite aprobar al Supervisor, Gerente y Administrador HS, sin conceder las demás autorizaciones financieras reservadas a gerencia. No se crea un asiento para compensar el faltante. Una cancelación autorizada después del cierre conserva el conteo original y muestra la diferencia actual en Conciliación.

## Presentación y actualización del comprobante

Caja muestra Cobros POS de ERPNext con fecha, turno legible, factura estándar, medio, importe y estado. El comprobante HS Arqueo presenta el conteo y los movimientos POS vigentes, sin la clave aleatoria del turno ni una tabla vacía de movimientos operativos. Su leyenda distingue el cierre conservado de las correcciones posteriores.

La exportación real encontró que el formato instalado tenía una fecha futura respecto al reloj operativo y migrate conservaba el HTML anterior. install.sync_print_formats compara el contenido de los formatos estándar propios y usa el importador nativo con force cuando cambian. Conserva la opción disabled del sitio, evita reimportar contenido idéntico y respeta formatos no estándar o de otro módulo. Se llama desde after_migrate; no modifica facturas ni libros. Las pruebas leen ahora el Print Format instalado mediante frappe.get_print.

## Evidencia y límites

El recorrido sintético crea la factura mediante el controlador estándar de Sales Invoice: dos aguas por C$60, recibido C$100 y vuelto C$40, con fondo de C$100. Gerencia revisó Caja y cerró por denominaciones desde la Page: esperado/contado C$160, diferencia cero. Capturas 72–74 y pos-items-ui.json conservan la lectura; no hubo HS Payment ni Payment Entry. El PDF de una página, output/native-pos/shift.pdf, se exportó, renderizó y revisó después de corregir la actualización del formato.

La batería final aprueba **159 pruebas (145 integración y catorce puras)** y **22 JS (veinte Desk y dos portal)**. Las seis pruebas nativas nuevas y una JS amplían la base de 153/21. La batería y la restauración se registran en pos-native-tests.xml/log, pos-js-tests.log y pos-ux-restored.json. Los casos nuevos cubren vuelto/devolución/cancelación, conteo cerrado, turno/propietario/referencia, caja USD y medio bancario separado, configuración histórica, POS sin turno, aprobación real del Supervisor y formato con fecha futura/opciones del sitio. Los primeros fixtures necesitaron cuentas predeterminadas en Mode of Payment y un modo específico para USD, tal como exige el controlador nativo. La prueba de permisos construye el documento como administrador antes de cambiar al cajero; no amplía los permisos nativos de creación de facturas.

La sesión temporal se cierra hasta Login y el servidor 8089 se detiene. Se restaura el respaldo previo del sitio de aceptación y se comparan sus setenta tablas de negocio; las pruebas finales se ejecutan sobre esa restauración. pos-final-state.json contrasta también las 36 tablas nativas de la demostración principal, sus servicios y HTTP. Esta recuperación acotada no sustituye la recuperación final del conjunto de demostración con archivo privado y reversión de código.

S09-14 queda respaldado por el arqueo/contado/diferencia y autorización del supervisor sin ajuste compensatorio. La devolución de anticipos ya aplicados, la cobertura completa de traducciones y el contraste de los demás capítulos siguen pendientes; no se declara concluido el alcance obligatorio.
