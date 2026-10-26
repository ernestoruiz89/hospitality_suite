export const customerCreditSections = [
  { id: "folios", label: "Cuentas de estancia", description: "Cobros de estancias" },
  { id: "invoices", label: "Facturas", description: "Cobros directos" },
  { id: "receive-advance", label: "Recibir anticipo", description: "Registrar dinero recibido" },
  { id: "apply-advance", label: "Aplicar anticipo", description: "Cubrir una factura" },
  { id: "refund-advance", label: "Devolver anticipo", description: "Restituir saldo aún disponible" },
  { id: "refund-applied", label: "Devolver importe acreditado", description: "Restituir un anticipo aplicado a una factura" },
  { id: "receive-guarantee", label: "Recibir garantía", description: "Registrar garantía de reserva o estancia" },
  { id: "apply-guarantee", label: "Aplicar garantía", description: "Abonar una cuenta compatible" },
  { id: "refund-guarantee", label: "Devolver garantía", description: "Restituir saldo disponible" },
  { id: "credit-note", label: "Nota de crédito", description: "Acreditar una factura directa" },
  { id: "direct-refund", label: "Devolver cobro directo", description: "Restituir un cobro contra una nota" },
] as const

export function availableCustomerCreditSections(canApprove: boolean) {
  return customerCreditSections.filter((section) => canApprove ||
    !["credit-note", "direct-refund", "refund-advance", "refund-applied", "apply-guarantee", "refund-guarantee"].includes(section.id))
}
