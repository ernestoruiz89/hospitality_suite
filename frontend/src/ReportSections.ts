export const pmsReportSections = [
  { id: "trial_balance", label: "Balance de comprobación", description: "Saldos de cuentas a la fecha de corte" },
  { id: "general_ledger", label: "Mayor general", description: "Movimientos y saldo acumulado por cuenta" },
  { id: "receivables", label: "Cartera por vencimiento", description: "Saldos pendientes de clientes" },
  { id: "funds", label: "Movimientos de fondos", description: "Entradas y salidas de caja y banco" },
  { id: "sales", label: "Producción neta", description: "Ingresos e impuestos del período" },
] as const

export const erpReportSections = [
  { id: "occupancy", label: "Reservas y ocupación", reports: [
    "Disponibilidad", "Reservas", "Llegadas", "Estancias", "Salidas",
    "Huéspedes alojados", "Cancelaciones y no presentaciones",
  ] },
  { id: "revenue", label: "Ingresos y clientes", reports: [
    "Producción", "Descuentos y cortesías", "Facturas", "Cuentas pendientes",
    "Cobros", "Anticipos y garantías", "Conciliación",
  ] },
  { id: "treasury", label: "Caja y tesorería", reports: [
    "Liquidaciones", "Egresos", "Caja Chica", "Rendiciones de Caja Chica",
    "Movimientos financieros", "Turnos", "Arqueos por moneda",
  ] },
  { id: "work", label: "Trabajo e inventario", reports: [
    "Limpieza", "Productividad de limpieza", "Mantenimiento", "Inventario",
    "Movimientos de inventario",
  ] },
  { id: "audit", label: "Auditoría", reports: ["Auditoría"] },
  { id: "all", label: "Todos los reportes", reports: [] },
] as const

export function erpReportsInSection(reports: string[], sectionId: string): string[] {
  const section = erpReportSections.find((item) => item.id === sectionId) || erpReportSections[0]
  return section.id === "all" ? reports : section.reports.filter((name) => reports.includes(name))
}
