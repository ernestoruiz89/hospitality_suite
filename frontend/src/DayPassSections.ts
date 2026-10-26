export const dayPassSections = [
  { id: "issue", label: "Emitir acceso", description: "Registrar un Day Pass sin habitación" },
  { id: "passes", label: "Accesos emitidos", description: "Consultar accesos y sus saldos" },
  { id: "passes-cancel", label: "Cancelar acceso", description: "Cancelar accesos sin cobros pendientes de reversión" },
  { id: "passes-return", label: "Devolver acceso", description: "Reembolsar y emitir la nota de crédito correspondiente" },
  { id: "account", label: "Cuenta por cobrar", description: "Configurar la cuenta de nuevas emisiones" },
] as const

export function availableDayPassSections(provider: "pms" | "erpnext", canSetup: boolean,
  canApprove: boolean) {
  return dayPassSections.filter((section) => {
    if (section.id === "account") return provider === "pms" && canSetup
    if (section.id === "passes-cancel") return provider === "pms" && canApprove
    if (section.id === "passes-return") return canApprove
    return true
  })
}
