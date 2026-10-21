# Modelo, estados y flujos principales

Diagramas de la app sobre Frappe 16.52.0 / ERPNext 16.51.1, contrastados con `schema.py` y los servicios actuales. Los nombres HS de los diagramas corresponden a DocTypes; los espacios se representan con guiones bajos. Las etiquetas de las relaciones son campos reales. En los enlaces opcionales puede faltar el documento de destino. La compañía y el establecimiento delimitan las operaciones mediante permisos y contexto del servidor.

## Reservas, alojamiento y tarifa

```mermaid
erDiagram
  Company ||--o{ HS_Property : company
  HS_Property ||--o{ HS_Category : property
  HS_Property ||--o{ HS_Room : property
  HS_Category ||--o{ HS_Room : category
  HS_Category ||--o{ HS_Rate : category
  HS_Rate ||--o{ HS_Rate_Service : included_services
  Item ||--o{ HS_Rate_Service : item
  HS_Guest }o--o| Customer : customer
  HS_Guest }o--o| Contact : contact
  HS_Guest }o--o| Address : address
  HS_Booking }o--o| HS_Guest : guest
  HS_Booking }o--o| Customer : customer
  HS_Booking ||--o{ HS_Booking_Room : rooms
  HS_Category ||--o{ HS_Booking_Room : category
  HS_Booking_Room }o--o| HS_Room : room
  HS_Rate ||--o{ HS_Booking_Room : rate
  HS_Stay }o--o| HS_Booking : booking
  HS_Guest ||--o{ HS_Stay : guest
  HS_Room ||--o{ HS_Stay : room
  HS_Stay ||--o{ HS_Stay_Guest : guests
  HS_Guest ||--o{ HS_Stay_Guest : guest
  HS_Allocation }o--o| HS_Booking : booking
  HS_Allocation }o--o| HS_Stay : stay
  HS_Allocation }o--o| HS_Room : room
  HS_Category ||--o{ HS_Allocation : category
  HS_Folio }o--o| HS_Stay : stay
  HS_Folio }o--o| HS_Booking : booking
  Customer ||--o{ HS_Folio : customer
  HS_Folio ||--o{ HS_Charge : folio
  HS_Stay ||--o{ HS_Charge : stay
  HS_Charge }o--o| Sales_Invoice : sales_invoice
```

El borrador conserva intención sin filas de habitaciones aceptadas ni asignaciones. Confirmar reserva capacidad por categoría, con o sin habitación física. Al ingresar se libera la asignación Reservation de esa fila y se crea la asignación Stay en la misma transacción; otras filas de un grupo pueden seguir pendientes. Un cambio de habitación conserva los segmentos anteriores. Una cuenta grupal puede reunir varias estancias de la reserva.

## Caja, servicios y documentos estándar

```mermaid
erDiagram
  HS_Property ||--o{ HS_Service_Account : service_accounts
  Item ||--o{ HS_Service_Account : item
  HS_Service_Account }o--o| Account : income_account
  HS_Service_Account }o--o| Account : expense_account
  HS_Service_Account }o--o| Cost_Center : cost_center
  HS_Service_Request }o--o| HS_Stay : stay
  HS_Service_Request }o--o| HS_Folio : folio
  HS_Service_Request }o--o| HS_Charge : charge
  HS_Service_Request }o--o| Stock_Entry : stock_entry
  HS_Stock_Policy }o--|| Item : item
  HS_Stock_Policy }o--|| Warehouse : warehouse
  HS_Shift ||--o{ HS_Payment : shift
  HS_Payment_Method ||--o{ HS_Payment : method
  Mode_of_Payment ||--o{ HS_Payment_Method : mode_of_payment
  Account ||--o{ HS_Payment_Method : account
  HS_Payment }o--o| Payment_Entry : payment_entry
  HS_Payment }o--o| Journal_Entry : journal_entry
  HS_Payment }o--o| Sales_Invoice : sales_invoice
  HS_Payment }o--o| HS_Expense_Category : expense_category
  HS_Expense_Category }o--|| Account : account
  HS_Payment }o--o| Purchase_Invoice : purchase_invoice
  HS_Supplier }o--|| Supplier : supplier
  HS_Billing_Party }o--|| Customer : customer
```

Sales Invoice reconoce el ingreso; Payment Entry y Journal Entry registran dinero, anticipos y garantías según su concepto. Los cobros POS nativos ya contabilizados se consultan desde ERPNext y no crean otro HS Payment. Las compras y el inventario utilizan Purchase Order, Purchase Receipt, Purchase Invoice, Stock Entry y Stock Reconciliation estándar. Los libros GL, Payment Ledger y Stock Ledger proceden de sus controladores nativos.

## Limpieza, mantenimiento y equipos

```mermaid
erDiagram
  HS_Room ||--o{ HS_Cleaning_Task : room
  HS_Cleaning_Task }o--o| HS_Stay : stay
  HS_Equipment }o--o| HS_Room : room
  HS_Equipment |o--o| Asset : asset
  HS_Maintenance_Order }o--o| HS_Equipment : equipment
  HS_Maintenance_Order }o--o| HS_Room : room
  HS_Maintenance_Order ||--o{ HS_Maintenance_Part : parts
  HS_Maintenance_Part }o--|| Item : item
  HS_Maintenance_Part }o--|| Stock_Entry : stock_entry
  HS_Allocation }o--o| HS_Maintenance_Order : maintenance
  HS_Room ||--o{ HS_Incident : room
  HS_Incident }o--o| Stock_Entry : stock_entry
```

Una orden de equipo puede existir sin habitación; solo bloquea cupo si su política lo solicita. Asset conserva valoración/depreciación nativas. Un bloqueo hasta reapertura tiene fin vacío y se libera al completar con autorización; una fecha prevista vencida tampoco completa la orden por sí sola. La ocupación, la limpieza y el mantenimiento se consultan como dimensiones distintas.

## Acceso, portal y trazabilidad

```mermaid
erDiagram
  User ||--o{ HS_Access : user
  HS_Property ||--o{ HS_Access : property
  HS_Property ||--o{ HS_Request : property
  HS_Property ||--o{ HS_Audit_Event : property
  User ||--o{ HS_Audit_Event : actor
  HS_Property ||--o{ HS_Daily_Close : property
  HS_Property ||--o{ HS_Integration_Event : property
  HS_Property ||--o{ HS_Portal_Request : property
  HS_Portal_Request }o--o| HS_Booking : booking
  HS_Allocation }o--o| HS_Portal_Request : portal_request
  HS_Property ||--o{ HS_Retention_Run : property
  HS_Retention_Run ||--o{ HS_Retention_File : files
```

HS Request conserva idempotencia; HS Audit Event conserva actor, origen y valores permitidos. HS Retention File es el outbox privado de una ejecución de retención: conserva referencias/rutas para el retiro posterior al commit, sin convertirse en otro archivo contable. HS Integration Event registra el receptor técnico. La sincronización con Airbnb/Booking y otros canales sigue aplazada.

## Estados de reserva y tareas

Las etiquetas incluyen el código persistido para que soporte pueda contrastarlo con el servicio; la interfaz operativa usa las etiquetas en español.

```mermaid
stateDiagram-v2
  state "Borrador · Draft" as Draft
  state "Retenida · Hold" as Hold
  state "Confirmada · Confirmed" as Confirmed
  state "Entrada registrada · Checked In" as CheckedIn
  state "Completada · Completed" as Completed
  state "Cancelada · Cancelled" as Cancelled
  state "No se presentó · No Show" as NoShow
  [*] --> Draft: guardar intención
  [*] --> Hold: aceptar cotización y retener
  [*] --> Confirmed: aceptar cotización
  Draft --> Draft: guardar cambios
  Draft --> Hold: revisar y aceptar
  Draft --> Confirmed: revisar y aceptar
  Draft --> Cancelled: descartar con motivo
  Hold --> Confirmed: confirmar antes de vencer
  Hold --> Cancelled: cancelar o caducar
  Hold --> NoShow: llegada vencida y motivo
  Confirmed --> Cancelled: cancelar con motivo
  Confirmed --> NoShow: llegada vencida y motivo
  Confirmed --> CheckedIn: ingresar una fila
  CheckedIn --> CheckedIn: ingresar otra fila del grupo
  CheckedIn --> Completed: sin estancias activas ni llegadas pendientes
```

```mermaid
stateDiagram-v2
  state "Limpieza" as Cleaning {
    [*] --> Pending
    Pending --> InProgress: iniciar
    InProgress --> Inspection: checklist completo
    InProgress --> Completed: checklist y política sin inspección
    Inspection --> InProgress: supervisión pide corrección con motivo
    Inspection --> Completed: supervisión inspecciona y libera
  }
  state "Mantenimiento" as Maintenance {
    [*] --> Open
    Open --> Working: iniciar
    Open --> Finished: supervisión completa
    Working --> Finished: supervisión completa
  }
```

En limpieza, InProgress representa In Progress, Inspection representa Inspection y Completed representa Completed. En mantenimiento, Working representa In Progress y Finished representa Completed. Completar mantenimiento libera su asignación; no existe una transición que vuelva a abrir una orden completada. Otra incidencia requiere otra orden. La salida de estancia cambia Active a Checked Out y crea la tarea de limpieza con habitación Dirty; iniciar, inspeccionar y completar actualizan Cleaning, Inspection y Clean conforme a la política.

## Flujo de alojamiento y cuenta

```mermaid
flowchart TD
  A[Elegir establecimiento, modalidad y fechas] --> B[Consultar cupo por categoría e intervalo]
  B --> C{Hay cupo}
  C -->|No| A
  C -->|Sí| D[Elegir pagador y revisar cotización]
  D --> E[Aceptar y reservar con clave única]
  E --> F[Registrar entrada con huésped y habitación limpia]
  F --> G[Cuenta y cargos aceptados]
  G --> H[Solicitar y entregar servicios]
  H --> I[Stock Entry y cargo cuando corresponde]
  I --> G
  G --> J[Revisar y emitir Sales Invoice]
  J --> K[Aplicar anticipos y registrar cobro nativo]
  K --> L{Saldo y garantía resueltos}
  L -->|No| G
  L -->|Sí o crédito autorizado| M[Registrar salida y cerrar cuentas aplicables]
  M --> N[Limpieza y eventual inspección]
  N --> O[Habitación limpia para otra entrada]
```

Reservar, ingresar, extender y cambiar habitación vuelven a comprobar cupo bajo bloqueo del establecimiento. Una consulta previa no garantiza cupo posterior. Las cotizaciones conservan precios aceptados y rechazan una aceptación obsoleta. El crédito de salida requiere política, pagador autorizado, límite y motivo; una garantía pendiente o servicio sin resolver sigue bloqueando la salida. La entrada inmediata recorre reserva/entrada sin requerir otra pantalla técnica.

La política Al ingresar crea cargos Pending; Por noche crea Scheduled y el proceso del día los convierte en Pending una sola vez. Facturar o salir genera también los programados pendientes. Los beneficios incluidos no generan otro cargo al consumirlos dentro de su cantidad aceptada.

## Abastecimiento, caja y cierre del día

```mermaid
flowchart LR
  A[Nueva compra desde Consumos] --> B[Purchase Order]
  B --> C[Purchase Receipt parcial o total]
  C --> D[Purchase Invoice sin segunda recepción de stock]
  D --> E[Pago nativo al proveedor desde Caja]
  F[Movimiento o conteo autorizado] --> G[Stock Entry o Stock Reconciliation]
  E --> H[Resolver pendientes y conciliar documentos por moneda]
  G --> H
  H --> I[Contar denominaciones y revisar diferencia de turno]
  I --> J{Sin diferencia o autorización válida}
  J -->|Sí| K[Cerrar turno]
  J -->|No| I
  K --> L[Preparar cierre del día operativo]
  L --> M{Pendientes resueltos y resumen vigente}
  M -->|No| H
  M -->|Sí| N[Gerencia confirma y avanza fecha una vez]
```

Un turno con diferencia pasa a Review y necesita motivo; la aprobación exige el rol autorizado. El cierre diario pasa por Review, Closed y, con motivo/autorización para el último día, Reopened. Preparar otra vez un día reabierto vuelve a Review. La reapertura no revierte facturas ni dinero. El cierre distingue fecha operativa, fecha contable y hora real, y su resumen conserva los valores de la ejecución.

## Fuentes y contraste

Las relaciones se contrastan con `schema.py`; las transiciones y condiciones, con `booking_drafts.py`, `operations.py`, `availability.py`, `housekeeping.py`, `inventory.py`, `cashier.py`, `periodic.py`, `accounting.py`, `procurement.py`, `closing.py` y `service.py`. Los diagramas incluyen los 35 DocTypes propios repartidos en cuatro vistas del modelo.

La batería nativa de esta revisión conserva 379 casos aprobados en [keyboard-review-native-tests.xml](evidence/keyboard-review-native-tests.xml), entre ellos TestBookingDrafts, TestLifecycle, TestHousekeepingAudit, TestProcurement y TestPeriodic. Los recorridos de Pages se conservan por fase en [ACEPTACION_Y_DEMOSTRACION.md](ACEPTACION_Y_DEMOSTRACION.md) y las auditorías de cada área. Estos diagramas documentan el sistema y sus condiciones; S04-17 y la aceptación global de formularios conservan sus pendientes propios.
