import { useEffect } from "react"
import { useSearchParams } from "react-router-dom"

export const directSaleSections = [
  { id: "new", label: "Nueva venta", description: "Cotizar, facturar y cobrar" },
  { id: "history", label: "Historial de ventas", description: "Consultar facturas y cobros" },
  { id: "returns", label: "Devoluciones", description: "Anular y reembolsar una venta completa" },
] as const

export function availableDirectSaleSections(canApprove: boolean) {
  return directSaleSections.filter((section) => canApprove || section.id !== "returns")
}

export function useDirectSaleSection(canApprove: boolean) {
  const [params, setParams] = useSearchParams()
  const sections = availableDirectSaleSections(canApprove)
  const requested = params.get("section")
  const section = sections.find((item) => item.id === requested)?.id || "new"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}
