import { useSearchParams } from "react-router-dom"

export type PmsInventorySection = "stock" | "warehouses" | "opening" | "transfers" | "counts" | "history"
export type ErpInventorySection = "stock" | "warehouses" | "policies" | "moves" | "counts"

export const pmsInventorySections: { id: PmsInventorySection; label: string; description: string;
  permission?: "setup" | "approve" }[] = [
  { id: "stock", label: "Existencias", description: "Consultar cantidades y valores" },
  { id: "warehouses", label: "Almacenes", description: "Crear ubicaciones", permission: "setup" },
  { id: "opening", label: "Saldo inicial", description: "Registrar existencias de apertura" },
  { id: "transfers", label: "Traslados", description: "Mover productos entre almacenes" },
  { id: "counts", label: "Conteo físico", description: "Aprobar diferencias", permission: "approve" },
  { id: "history", label: "Historial", description: "Consultar movimientos y conteos" },
]

export const erpInventorySections: { id: ErpInventorySection; label: string; description: string;
  permission?: "setup" | "approve" }[] = [
  { id: "stock", label: "Existencias", description: "Consultar cantidades y mínimos" },
  { id: "warehouses", label: "Almacenes", description: "Crear ubicaciones ERPNext" },
  { id: "policies", label: "Clasificación y mínimos", description: "Configurar reposición", permission: "setup" },
  { id: "moves", label: "Movimientos", description: "Trasladar o consumir stock" },
  { id: "counts", label: "Conteo físico", description: "Revisar y ajustar existencias", permission: "approve" },
]

export function usePmsInventorySection(canSetup: boolean, canApprove: boolean) {
  const [params] = useSearchParams()
  const requested = params.get("section")
  return pmsInventorySections.find((item) => item.id === requested &&
    (item.permission !== "setup" || canSetup) &&
    (item.permission !== "approve" || canApprove))?.id || "stock"
}

export function useErpInventorySection(canSetup: boolean, canApprove: boolean) {
  const [params] = useSearchParams()
  const requested = params.get("section")
  return erpInventorySections.find((item) => item.id === requested &&
    (item.permission !== "setup" || canSetup) &&
    (item.permission !== "approve" || canApprove))?.id || "stock"
}
