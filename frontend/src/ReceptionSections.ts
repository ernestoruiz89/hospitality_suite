export const receptionSections = [
  { id: "arrivals", label: "Llegadas", description: "Reservas pendientes y solicitudes web" },
  { id: "reservation", label: "Reserva directa", description: "Cotizar y confirmar una reserva" },
  { id: "folios", label: "Cuentas de estancia", description: "Gestionar cuentas de huéspedes" },
  { id: "policies", label: "Penalizaciones", description: "Política de cancelación y no presentación", requiresSetup: true },
  { id: "guests", label: "Perfiles de huéspedes", description: "Consultar y corregir perfiles", permission: "guest" },
  { id: "guest-new", label: "Registrar huésped", description: "Crear un huésped y su pagador" },
  { id: "stays", label: "Estancias activas", description: "Consultar las estancias en curso" },
  { id: "stay-extend", label: "Extender estancia", description: "Cotizar y confirmar tiempo adicional", permission: "stay" },
  { id: "stay-move", label: "Cambiar habitación", description: "Revisar disponibilidad y tarifa", permission: "stay" },
  { id: "stay-companions", label: "Acompañantes", description: "Registrar acompañantes de la estancia", permission: "guest" },
] as const

export function availableReceptionSections(provider: "pms" | "erpnext", canSetup: boolean,
  canStay: boolean, canManageGuests: boolean) {
  return receptionSections.filter((section) =>
    (!("requiresSetup" in section) || provider === "pms" && canSetup) &&
    (!("permission" in section) || section.permission === "stay" && canStay ||
      section.permission === "guest" && canManageGuests))
}
