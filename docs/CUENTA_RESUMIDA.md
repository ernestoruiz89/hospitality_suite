# Cuenta de estancia resumida — 0.6.6

Por observación del usuario, el PDF estándar presenta una cuenta para leer y entregar: conceptos, cuentas, cantidades, importes, estado/factura y saldos. Ya no imprime los bloques de cálculo histórico, reglas por noche, tolerancias, fracciones o importes de referencia que alargaban el documento. El detalle continúa disponible por cargo en la Page mediante «Ver cálculo del precio» y en la revisión de la cotización antes de confirmar.

Las facturas/notas de crédito conservan neto, impuestos, total y saldo; los cobros, anticipos y garantías conservan importe, moneda y comprobante. Esas secciones se omiten si no contienen movimientos. Una garantía reembolsable incluye una aclaración breve de su tratamiento. Se conserva la distinción de cuenta compartida, programado sin generar, pendiente de facturar y saldo total pendiente.

No cambia importes, tarifas, impuestos, conciliaciones, documentos contables ni referencias. No reconstruye el precio con los maestros actuales. La proyección del cálculo permanece en stay_detail y en la interfaz, y ya no se calcula innecesariamente para el contexto de impresión. Las descripciones se escapan al imprimir.

Los comprobantes de 0.6.5 y capturas 136–137 son evidencia histórica de la versión extensa que motivó el ajuste; se conservan. La versión actual usa el mismo formato nativo «HS Cuenta de estancia», con Jinja y wkhtmltopdf de Frappe, sin agregar opciones al trabajo de recepción.

## Verificación

Batería final: 272 nativas aprobadas (258 integración y 14 puras), sin errores/fallos/omisiones, y 66 JS aprobadas. Se añadió una prueba con descuento, factura y pago parcial: C$1,400 facturados, C$500 pagados y C$900 pendientes, conservando impuestos, comprobantes y datos antes/después del impreso. Se actualizaron las aserciones del formato anterior para exigir ausencia del desglose en PDF y su conservación en la proyección de pantalla. El primer pase detectó una aserción anterior que aún exigía `pricing` en el contexto de impresión; se corrigió para el contrato resumido y se repitió la batería completa.

Fixture API explícito en aceptación: Hotel C$3,800 menos C$100 de descuento, saldo C$3,700; Por tiempo C$600 más C$150, saldo C$750. Los maestros se cambiaron después de aceptar. Los dos PDF exportados y revisados visualmente tienen una página, sin fórmulas ni secciones vacías, con importes conservados. Capturas 138–139 y account-summary-items-ui.json contienen páginas/SHA y comparación idéntica de 72 tablas con Version tras impresión/consultas.

Recepción abrió el formato nativo y descargó «Obtener PDF» en http://localhost:8089. El archivo descargado se extrajo y renderizó: una página, mismo texto que el exportado, cifras correctas y sin bloques históricos. Esta descarga HTTP funcionó sin la configuración local de host usada por el proceso CLI; account-summary-browser.json y la captura 140 registran el alcance. Guest no pudo abrir el comprobante. Se cerraron sesión y pestaña; no se cambió el viewport ni se guardaron operaciones desde Page.

Después se detuvo 8089 y se restauró el respaldo original con archivos. Se recargó solamente el formato nativo en ambos sitios mediante reload-doc; esta corrección no añade columnas ni patches. Aceptación: 71 tablas/185 filas idénticas, 72/195 con Version y cero operaciones. Principal: 72/1191 y dos archivos privados conservados; fecha operativa 19/10. Web/worker reiniciados, HTTP 200, Socket.IO/Redis activos y núcleos limpios. No sustituye la recuperación final del objetivo.

tools/verify_account_summary.py compara el HTML instalado con la metadata nativa del repositorio en ambos sitios, sin escrituras; account-summary-installed.json conserva versión, SHA y resultados.

S07-09 sigue acreditado por explicación previa y revisión del cálculo en la cuenta de pantalla. La petición del usuario ajusta la presentación del comprobante; la matriz conserva 132 V, 18 I, 0 P y 68 R, de las mismas 218 entradas. Continúan la gestión de huéspedes y las demás verificaciones obligatorias, con sincronización externa aplazada.
