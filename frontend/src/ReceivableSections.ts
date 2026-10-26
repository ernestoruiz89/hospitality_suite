export const receivableSections = [
  { id: "balances", label: "Saldos pendientes", group: "Cuentas por cobrar", permission: "finance" },
  { id: "create", label: "Registrar cargo", group: "Cuentas por cobrar", permission: "create" },
  { id: "apply", label: "Aplicar depósito", group: "Cuentas por cobrar", permission: "finance" },
  { id: "unapply", label: "Revertir depósito", group: "Cuentas por cobrar", permission: "approve" },
  { id: "cancelled", label: "Cargos cancelados", group: "Cuentas por cobrar", permission: "approve" },
  { id: "opening-credits", label: "Aplicar crédito", group: "Créditos de apertura", permission: "finance" },
  { id: "opening-credit-refunds", label: "Devolver crédito", group: "Créditos de apertura", permission: "approve" },
  { id: "opening-credit-reversals", label: "Revertir aplicación", group: "Créditos de apertura", permission: "approve" },
  { id: "opening-guarantees", label: "Garantías trasladadas", group: "Garantías de apertura", permission: "finance" },
  { id: "opening-guarantee-refunds", label: "Devolver garantía", group: "Garantías de apertura", permission: "approve" },
  { id: "opening-guarantee-reversals", label: "Revertir aplicación", group: "Garantías de apertura", permission: "approve" },
] as const

export function availableReceivableSections(canCreate: boolean, canApprove: boolean) {
  return receivableSections.filter((section) =>
    section.permission === "finance" || section.permission === "create" && canCreate ||
    section.permission === "approve" && canApprove)
}
