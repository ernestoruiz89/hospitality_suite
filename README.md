# Hospitality Suite

Aplicación nativa Frappe/ERPNext para hoteles, moteles y operación mixta. Interfaz operativa en español mediante Pages de Desk.

Objetivo de desarrollo verificado: **Frappe 16.52.0 / ERPNext 16.51.1 / Python 3.14.6 / MariaDB**, en Ubuntu 24.04 bajo WSL2. Otras versiones no están probadas.

El alcance y los pendientes se registran en [docs/REQUISITOS.md](docs/REQUISITOS.md). El estado del repositorio durante el desarrollo no implica aptitud para producción.

## Instalación

```sh
bench get-app /ruta/al/repositorio/Hotel
bench --site hotel.localhost install-app hospitality_suite
bench --site hotel.localhost migrate
bench build --app hospitality_suite
```

ERPNext debe estar instalado antes. No requiere HRMS. La instalación no crea compañías, cuentas, impuestos ni datos de demostración.

## Desarrollo

```sh
python tools/generate_schema.py
bench --site hotel.localhost run-tests --app hospitality_suite
```

La especificación original se conserva en `SPECIFICATION.txt`. Los archivos JSON de DocTypes y Pages se versionan; `tools/generate_schema.py` es su fuente reproducible.
