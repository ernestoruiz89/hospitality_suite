export const roomWorkSections = [
  { id: "cleaning", label: "Limpieza", description: "Ejecutar e inspeccionar tareas pendientes" },
  { id: "cleaning-new", label: "Programar limpieza", description: "Crear una tarea de limpieza" },
  { id: "linen", label: "Historial de ropa", description: "Consultar los movimientos del hotel" },
  { id: "linen-send", label: "Enviar ropa", description: "Trasladar ropa a lavandería" },
  { id: "linen-receive", label: "Recibir ropa", description: "Recibir ropa desde lavandería" },
  { id: "linen-loss", label: "Registrar pérdida", description: "Contabilizar ropa faltante" },
  { id: "incidents", label: "Novedades", description: "Consultar y resolver daños u objetos encontrados" },
  { id: "incidents-new", label: "Registrar novedad", description: "Crear una constancia en la habitación" },
  { id: "maintenance", label: "Mantenimiento", description: "Trabajar en órdenes y repuestos" },
  { id: "maintenance-new", label: "Nueva orden", description: "Programar trabajo de mantenimiento" },
  { id: "blocks", label: "Bloqueos", description: "Consultar y liberar habitaciones bloqueadas" },
  { id: "blocks-new", label: "Nuevo bloqueo", description: "Reservar una habitación para uso interno" },
] as const

export type RoomWorkAccess = { clean: boolean; inspect: boolean; maintain: boolean;
  block: boolean; incident: boolean }

export function availableRoomWorkSections(can: RoomWorkAccess) {
  return roomWorkSections.filter((section) => {
    if (section.id === "cleaning") return can.clean || can.inspect
    if (section.id === "cleaning-new") return can.inspect
    if (section.id.startsWith("linen")) return can.clean
    if (section.id === "incidents") return can.incident || can.inspect
    if (section.id === "incidents-new") return can.incident
    if (section.id === "maintenance") return can.maintain || can.inspect
    if (section.id === "maintenance-new") return can.maintain
    return can.block
  })
}
