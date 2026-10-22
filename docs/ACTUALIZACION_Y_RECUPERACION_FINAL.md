# Actualización y recuperación final

Ensayo F26 en curso: versión anterior 0.8.8 (`be67c92`) y candidata 0.8.9. Destino único: `hospitality-release.localhost`, base `hospitality_release`, bench independiente `/home/frappe/.hospitality-release-install/benches/hospitality-release-bench`. El sitio principal y el de aceptación tienen respaldos previos independientes. No se activa un proveedor externo ni sincronización OTA.

Se conserva primero el estado original del destino, sus 21 archivos físicos, configuración y usuarios sintéticos. La copia para el ensayo procede del respaldo con archivos del sitio principal y debe conservar sus 72 tablas/1,246 filas, incluidos documentos estándar y dos archivos privados. Los datos de negocio, archivos y configuración permanecen privados; las evidencias públicas contienen conteos y hashes.

La secuencia prevista comprende: lectura con código anterior; respaldo coordinado; despliegue de la candidata con dependencias, migración repetida y construcción; comparación de datos/archivos y revisión por rol; fallo controlado de asset junto a una sonda explícita de QA en base/archivo privado; respaldo del estado fallido; recuperación de código, base y archivos anteriores; nueva comparación y revisión; segundo despliegue; instalación limpia de la candidata y batería completa en ese destino; restauración del estado original del destino; comparación del principal y aceptación y paquete final. Las sondas no representan actividad financiera nueva ni creación mediante UI.

Hasta ejecutar y verificar esa secuencia, F26 y los cuatro cierres generales permanecen abiertos. El archivo se completará con los resultados reales, sin presentar esta preparación como recuperación terminada.
