import { useEffect } from "react"
import { useSearchParams } from "react-router-dom"

export type SetupProvider = "pms" | "erpnext"

export const setupSections = [
  { id: "identity", label: "Identidad y modalidad", description: "Nombre, modalidad y zona horaria", group: "Establecimiento", provider: "both" },
  { id: "reservations", label: "Reservas y huéspedes", description: "Retenciones, cobros y portal", group: "Establecimiento", provider: "both" },
  { id: "housekeeping", label: "Limpieza", description: "Tiempo e inspección", group: "Establecimiento", provider: "both" },
  { id: "schedules", label: "Horarios", description: "Entrada, salida y corte", group: "Establecimiento", provider: "both" },
  { id: "privacy", label: "Privacidad", description: "Modo discreto y conservación de datos", group: "Establecimiento", provider: "both" },
  { id: "accounts", label: "Cuentas contables", description: "Centro de costo y cuentas ERPNext", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "warehouses", label: "Almacenes", description: "Existencias y lavandería", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "sales", label: "Artículos de venta", description: "Alojamiento y cargos adicionales", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "pricing-taxes", label: "Precios e impuestos", description: "Lista de precios y plantilla fiscal", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "finance-enable", label: "Habilitar finanzas", description: "Activar operaciones tras revisar la configuración", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "service-accounts", label: "Cuentas por servicio", description: "Reglas específicas", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "document-series", label: "Series de documentos", description: "Numeración de facturas y pagos", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "print-formats", label: "Formatos de impresión", description: "Plantillas para facturas y recibos", group: "Contabilidad y documentos", provider: "erpnext" },
  { id: "linen", label: "Ropa del hotel", description: "Almacenes y traslado", group: "Contabilidad y documentos", provider: "pms" },
  { id: "exchange", label: "Diferencia cambiaria", description: "Cuenta de resultados PMS", group: "Contabilidad y documentos", provider: "pms" },
  { id: "categories", label: "Categorías", description: "Capacidad y comodidades", group: "Habitaciones y tarifas", provider: "both" },
  { id: "categories-new", label: "Nueva categoría", description: "Registrar capacidad y comodidades", group: "Habitaciones y tarifas", provider: "both" },
  { id: "rooms", label: "Habitaciones", description: "Inventario de habitaciones", group: "Habitaciones y tarifas", provider: "both" },
  { id: "rooms-new", label: "Nueva habitación", description: "Asignar categoría, piso y camas", group: "Habitaciones y tarifas", provider: "both" },
  { id: "rates", label: "Tarifas", description: "Precios y modalidades", group: "Habitaciones y tarifas", provider: "both" },
  { id: "rates-new", label: "Nueva tarifa", description: "Definir moneda, precio y modalidad", group: "Habitaciones y tarifas", provider: "both" },
] as const

export function availableSetupSections(provider: SetupProvider) {
  return setupSections.filter((item) => item.provider === "both" || item.provider === provider)
}

export function useSetupSection(provider: SetupProvider) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const resolved = requested === "documents" ? "document-series" :
    requested === "operation" ? "identity" : requested
  const section = availableSetupSections(provider).find((item) => item.id === resolved)?.id || "identity"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}
