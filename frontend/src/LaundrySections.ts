export const laundrySections = [
  { id: "orders", label: "Órdenes", description: "Consultar estados y comprobantes" },
  { id: "process", label: "Procesar órdenes", description: "Iniciar trabajo y marcar prendas listas" },
  { id: "ready", label: "Contar y entregar", description: "Registrar prendas devueltas y entregar" },
  { id: "cancel", label: "Cancelar orden", description: "Cerrar una solicitud con motivo" },
  { id: "request", label: "Solicitar recogida", description: "Crear una solicitud para una estancia" },
  { id: "collect", label: "Recoger prendas", description: "Contar prendas y confirmar el precio" },
  { id: "rates", label: "Tarifas", description: "Configurar prendas y precios", requiresSetup: true },
] as const

export function availableLaundrySections(canSetup: boolean) {
  return laundrySections.filter((section) => !("requiresSetup" in section) || canSetup)
}
