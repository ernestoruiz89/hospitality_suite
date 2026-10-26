export const erpCreditSections = [
  { id: "payers", label: "Cartera y pagadores" },
  { id: "new", label: "Registrar pagador" },
  { id: "terms", label: "Condiciones de crédito" },
] as const

export function availableErpCreditSections(canSetup: boolean) {
  return erpCreditSections.filter((section) => section.id === "payers" || canSetup)
}
