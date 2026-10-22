# Entrega de Hospitality Suite 0.8.9

Aplicación para modalidad **Hotel, Por tiempo y Mixta**, con once Pages y nueve roles. El alcance obligatorio del adjunto y los ajustes de interfaz están contrastados en [COTEJO_FINAL.md](COTEJO_FINAL.md) y la [matriz de 218 requisitos](AUDITORIA_ESPECIFICACION.md). La sincronización real Airbnb/Booking permanece aplazada.

## Abrir la demostración instalada en WSL

Desde PowerShell, en el directorio del proyecto:

```powershell
.\tools\start_local_hotel.ps1
```

Abra [Reservas](http://hospitality.localhost:8086/desk/hospitality-suite/hospitality-reservations). El lanzador verifica/reutiliza los procesos existentes y la respuesta dentro de WSL; no instala ni reinicia los datos. Las cuentas ficticias por rol están en el archivo privado `sites/hospitality.localhost/private/hospitality-demo-users.json` del bench, fuera del repositorio y los paquetes.

La demostración conserva dos establecimientos, veinte habitaciones, reservas/estancias y documentos ficticios. Recepción y Caja tienen permisos separados; para que una misma persona reserve y cobre, asigne ambos roles y su establecimiento desde Configuración. Los recorridos de aceptación utilizaron esa autorización explícita.

## Archivos de entrega

Los artefactos definitivos se reúnen en `output/entrega-0.8.9/`:

- `hospitality-suite-0.8.9-entrega.zip`: conjunto de entrega con repositorio archivado, sdist, wheel, manifiesto y documentos de cierre.
- `hospitality-suite-repository.tar.gz`: código y documentación del repositorio sin `.git`, entornos, bases ni secretos.
- `hospitality_suite-0.8.9.tar.gz`: distribución fuente con documentación y herramientas.
- `hospitality_suite-0.8.9-py3-none-any.whl`: paquete Python/datos de la app.
- `manifest.json` y `SHA256SUMS`: revisión, versiones, tamaño e integridad de cada artefacto.

El repositorio Git completo sigue en el directorio de este proyecto. Para instalar en otro bench use un clon de ese repositorio, según el README; los tar/whl son distribuciones verificadas y no incluyen historial Git. No copie archivos `site_config.json`, SQL ni credenciales del bench de demostración a un repositorio o paquete público.

## Instalar y operar

Entorno acreditado: **Frappe 16.52.0, ERPNext 16.51.1, Python 3.14.6, Node 24.18.0 y MariaDB 10.11.14**, Ubuntu 24.04/WSL2. PDF requiere el runtime con Qt parcheado descrito en [README](../README.md). Otras versiones no tienen aceptación acreditada.

Con Frappe y ERPNext instalados en un bench de pruebas nuevo, obtenga el repositorio local como app, instálelo en el sitio, migre y construya:

```sh
bench get-app hospitality_suite /ruta/al/repositorio-git
bench --site hotel.localhost install-app hospitality_suite
bench --site hotel.localhost migrate
bench build --app hospitality_suite
```

Los comandos y requisitos completos están en [README](../README.md). Instalar no crea la compañía ni datos de demostración: complete primero el asistente nativo de ERPNext, cree el establecimiento desde Inicio y configure habitaciones/tarifas, impuestos, cuentas, almacenes, medios de pago y permisos antes de habilitar finanzas. La demostración y la batería nativa se preparan explícitamente en sitios designados, separados del sitio con operaciones.

## Guías y evidencia

- [Manual por rol](MANUAL.md): procesos diarios, autorizaciones y recuperación.
- [Contabilidad](CONTABILIDAD.md): anticipo/garantía, facturas, pagos, monedas, conciliación e indicadores.
- [Operación](OPERACION.md): workers/scheduler, monitoreo, respaldos, restauración y despliegue/reversión.
- [Modelo, estados y flujos](MODELO_ESTADOS_Y_FLUJOS.md).
- [Funciones, límites e integraciones externas](ESTADO_Y_EVIDENCIAS_ENTREGA.md).
- [410 pruebas nativas](evidence/final-recovery-native-tests.xml), [232 JS](evidence/f26-js-tests-tap.log), [instalación limpia](evidence/f26-clean-install.json) y [actualización/recuperación F26](ACTUALIZACION_Y_RECUPERACION_FINAL.md).

La app utiliza los documentos estándar de ERPNext para dinero y stock. No procesa pagos desconectados ni presenta simulaciones de pasarelas, mensajería o cerraduras como servicios activos. La entrega se acredita en el entorno de pruebas descrito y no es una certificación de despliegues o proveedores ajenos a esa configuración.
