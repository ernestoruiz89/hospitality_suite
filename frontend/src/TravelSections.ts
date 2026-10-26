export const travelSections = [
  { id: "orders", label: "Órdenes con estancia", description: "Consultar todas las experiencias reservadas para huéspedes" },
  { id: "orders-confirm", label: "Confirmar horario", description: "Programar experiencias reservadas" },
  { id: "orders-deliver", label: "Entregar experiencia", description: "Entregar experiencias confirmadas y cargar la cuenta de estancia" },
  { id: "orders-cancel", label: "Cancelar orden", description: "Cancelar experiencias pendientes con un motivo" },
  { id: "reserve", label: "Reservar experiencia", description: "Añadir una experiencia a una reserva" },
  { id: "direct", label: "Venta directa", description: "Vender experiencias sin estancia" },
  { id: "agencies", label: "Directorio de agencias", description: "Consultar agencias vinculadas al establecimiento" },
  { id: "agency-form", label: "Registrar agencia", description: "Crear o editar una agencia y su comisión" },
  { id: "agency-contribution", label: "Aporte de agencias", description: "Consultar reservas y comisiones estimadas por agencia" },
  { id: "experiences", label: "Catálogo de experiencias", description: "Consultar experiencias disponibles para reservar" },
  { id: "experience-form", label: "Registrar experiencia", description: "Crear o editar un servicio de experiencias" },
  { id: "commissions-settle", label: "Liquidar comisión", description: "Contabilizar la comisión de una reserva" },
  { id: "commissions-pay", label: "Pagar comisión", description: "Abonar una comisión pendiente" },
  { id: "commissions-cancel", label: "Anular comisión", description: "Revertir una comisión sin pagos" },
  { id: "commissions-history", label: "Historial de comisiones", description: "Consultar comisiones contabilizadas" },
  { id: "commission-accounts", label: "Cuentas de comisión", description: "Configurar cuentas contables PMS" },
] as const

export type TravelSectionAccess = {
  provider: "pms" | "erpnext"
  setup: boolean
  reserve: boolean
  service: boolean
  commission: boolean
  finance: boolean
  approve: boolean
}

export function availableTravelSections(access: TravelSectionAccess) {
  return travelSections.filter((section) => {
    switch (section.id) {
      case "reserve": return access.reserve
      case "orders-confirm":
      case "orders-deliver":
      case "orders-cancel": return access.service
      case "direct": return access.provider === "pms" && access.finance
      case "agency-form":
      case "experience-form": return access.setup
      case "commissions-settle": return access.commission
      case "commissions-pay": return access.provider === "pms" && access.finance
      case "commissions-cancel": return access.provider === "pms" && access.approve
      case "commissions-history": return access.commission || access.provider === "pms" && (access.finance || access.approve)
      case "commission-accounts": return access.provider === "pms" && access.setup
      default: return true
    }
  })
}
