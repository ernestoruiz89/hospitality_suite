import { useEffect } from "react"
import { useSearchParams } from "react-router-dom"

export type PurchaseSection = "suppliers" | "supplier-new" | "orders" | "order-new" | "order-receive" | "receive" | "payables" | "supplier-pay" | "supplier-payments" | "credits" | "credit-apply" | "credit-refund" | "credit-unapply" | "returns" | "return-new" | "supplier-refund"
export type ErpPurchaseSection = "suppliers" | "supplier-new" | "orders" | "order-new" | "receive" | "bills" | "payables" | "supplier-pay"

export const purchaseSections: { id: PurchaseSection; label: string; description: string; requiresPurchase?: boolean; requiresApprove?: boolean }[] = [
  { id: "suppliers", label: "Proveedores", description: "Consultar proveedores del establecimiento", requiresPurchase: true },
  { id: "supplier-new", label: "Registrar proveedor", description: "Crear un proveedor del establecimiento", requiresPurchase: true },
  { id: "orders", label: "Órdenes de compra", description: "Consultar y aprobar órdenes" },
  { id: "order-new", label: "Solicitar orden", description: "Preparar una orden para aprobación", requiresPurchase: true },
  { id: "order-receive", label: "Recibir orden", description: "Registrar una recepción parcial o completa", requiresPurchase: true },
  { id: "receive", label: "Recepción de compras", description: "Registrar compras directas de inventario", requiresPurchase: true },
  { id: "payables", label: "Cuentas por pagar", description: "Consultar deudas y pagos recientes" },
  { id: "supplier-pay", label: "Abonar proveedor", description: "Revisar y registrar un pago" },
  { id: "supplier-payments", label: "Pagos y reintegros", description: "Consultar movimientos recientes de proveedores" },
  { id: "credits", label: "Créditos de proveedor", description: "Consultar saldos de apertura" },
  { id: "credit-apply", label: "Aplicar crédito", description: "Compensar una deuda del proveedor" },
  { id: "credit-refund", label: "Cobrar crédito", description: "Recibir un reintegro de apertura" },
  { id: "credit-unapply", label: "Revertir aplicación", description: "Corregir una compensación", requiresApprove: true },
  { id: "returns", label: "Devoluciones", description: "Consultar devoluciones y créditos pendientes" },
  { id: "return-new", label: "Devolver o cancelar", description: "Revisar y contabilizar una devolución", requiresApprove: true },
  { id: "supplier-refund", label: "Reintegro proveedor", description: "Recibir un crédito generado por devolución" },
]

export const erpPurchaseSections: { id: ErpPurchaseSection; label: string; description: string;
  permission: "purchase" | "finance" }[] = [
  { id: "suppliers", label: "Proveedores", description: "Consultar proveedores habilitados", permission: "purchase" },
  { id: "supplier-new", label: "Registrar proveedor", description: "Habilitar un proveedor para el establecimiento", permission: "purchase" },
  { id: "orders", label: "Órdenes de compra", description: "Consultar órdenes abiertas en ERPNext", permission: "purchase" },
  { id: "order-new", label: "Nueva orden", description: "Preparar y presentar una orden en ERPNext", permission: "purchase" },
  { id: "receive", label: "Recepciones", description: "Registrar entregas parciales contra órdenes", permission: "purchase" },
  { id: "bills", label: "Facturas de proveedor", description: "Vincular documentos a recepciones contabilizadas", permission: "purchase" },
  { id: "payables", label: "Facturas por pagar", description: "Consultar facturas con saldo", permission: "finance" },
  { id: "supplier-pay", label: "Pagar proveedor", description: "Revisar y registrar un pago", permission: "finance" },
]

export function usePurchaseSection(canPurchase: boolean, canApprove: boolean) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const section = purchaseSections.find((item) => item.id === requested &&
    (!item.requiresPurchase || canPurchase) &&
    (!item.requiresApprove || canApprove))?.id || "orders"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}

export function useErpPurchaseSection(canPurchase: boolean, canFinance: boolean) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const section = erpPurchaseSections.find((item) => item.id === requested &&
    (item.permission === "purchase" ? canPurchase : canFinance))?.id ||
    (canPurchase ? "orders" : "payables")
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}
