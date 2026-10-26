export const billingSections = [
  { id: "invoices", label: "Emitir factura", description: "Documentar cargos contabilizados" },
  { id: "credits", label: "Notas de crédito", description: "Acreditar una factura total o parcialmente" },
  { id: "documents", label: "Documentos registrados", description: "Consultar e imprimir documentos recientes" },
  { id: "identity", label: "Identidad fiscal", description: "Ver los datos fiscales del establecimiento" },
  { id: "profiles", label: "Perfiles tributarios", description: "Configurar tasas y cuentas de impuesto" },
  { id: "series", label: "Series de documentos", description: "Configurar la numeración fiscal" },
] as const

export function availableBillingSections(canSetup: boolean, canChart: boolean, canApprove: boolean) {
  return billingSections.filter((section) => {
    if (section.id === "credits") return canApprove
    if (section.id === "profiles") return canChart
    if (section.id === "series") return canSetup
    return true
  })
}
