export const folioSections = [
  { id: "accounts", label: "Cuentas de estancia", description: "Consultar saldos y elegir una cuenta" },
  { id: "post", label: "Contabilizar cargos", description: "Revisar y publicar cargos pendientes" },
  { id: "services", label: "Añadir servicio", description: "Cargar servicios a una estancia" },
  { id: "adjustments", label: "Corregir cargo", description: "Descuentos, recargos y anulaciones" },
] as const

export function availableFolioSections(canApprove: boolean) {
  return folioSections.filter((section) => section.id !== "adjustments" || canApprove)
}
