import { useEffect } from "react"
import { useSearchParams } from "react-router-dom"

export type PmsCashSection = "shift-overview" | "shift-open" | "shift-close" | "collect" | "advance" | "guarantee" | "income" | "expense" | "refunds" | "history" | "method-setup" | "category-setup" | "concept-setup"
export type ErpCashSection = "shift-overview" | "shift-open" | "close" | "expense" | "withdraw" | "history" | "expense-categories" | "setup" | "settlement" | "method-settings"

const movementKinds: Partial<Record<PmsCashSection, string>> = {
  collect: "Payment", advance: "Advance", guarantee: "Guarantee",
  income: "Other Income", expense: "Expense",
}
const setupKinds: Partial<Record<PmsCashSection, string>> = {
  "method-setup": "method", "category-setup": "category", "concept-setup": "concept",
}

export function pmsCashMovementKind(section: PmsCashSection): string | null {
  return movementKinds[section] || null
}

export function pmsCashSetupKind(section: PmsCashSection): string | null {
  return setupKinds[section] || null
}

export const pmsCashSections: { id: PmsCashSection; label: string; description: string;
  permission?: "refund" | "setup" }[] = [
  { id: "shift-overview", label: "Turnos", description: "Consultar efectivo esperado" },
  { id: "shift-open", label: "Abrir turno", description: "Declarar efectivo inicial por moneda" },
  { id: "shift-close", label: "Arqueo y cierre", description: "Contar efectivo y cerrar un turno" },
  { id: "collect", label: "Cobrar cuenta", description: "Liquidar una cuenta por cobrar" },
  { id: "advance", label: "Recibir anticipo", description: "Registrar un anticipo del cliente" },
  { id: "guarantee", label: "Recibir garantía", description: "Registrar una garantía de reserva o cuenta de estancia" },
  { id: "income", label: "Otro ingreso", description: "Registrar un ingreso sin factura" },
  { id: "expense", label: "Registrar gasto", description: "Desembolsar un gasto de Caja" },
  { id: "refunds", label: "Devoluciones", description: "Devolver cobros, anticipos o garantías", permission: "refund" },
  { id: "history", label: "Últimos movimientos", description: "Consultar importes y referencias" },
  { id: "method-setup", label: "Medios de pago", description: "Vincular medios con cuentas de Caja o banco", permission: "setup" },
  { id: "category-setup", label: "Categorías de gasto", description: "Definir cuentas y límites", permission: "setup" },
  { id: "concept-setup", label: "Conceptos de ingreso", description: "Definir cuentas para otros ingresos", permission: "setup" },
]

export const erpCashSections: { id: ErpCashSection; label: string; description: string;
  permission?: "setup" }[] = [
  { id: "shift-overview", label: "Turnos", description: "Consultar turnos activos y cerrados" },
  { id: "shift-open", label: "Abrir turno", description: "Declarar moneda y fondo inicial" },
  { id: "close", label: "Arqueo y cierre", description: "Contar efectivo y cerrar el turno" },
  { id: "expense", label: "Registrar gasto", description: "Desembolsar un gasto menor desde Caja" },
  { id: "withdraw", label: "Retiro de efectivo", description: "Traspasar efectivo a la cuenta configurada" },
  { id: "history", label: "Movimientos del turno", description: "Consultar entradas y salidas del turno" },
  { id: "settlement", label: "Liquidar tarjetas y bancos", description: "Conciliar cobros no efectivos con el abono bancario" },
  { id: "method-settings", label: "Medios de pago", description: "Configurar cuentas y política de liquidación", permission: "setup" },
  { id: "expense-categories", label: "Categorías de gasto", description: "Definir cuentas y límites por desembolso", permission: "setup" },
  { id: "setup", label: "Cuenta de traslado", description: "Configurar la cuenta para retiros", permission: "setup" },
]

export function usePmsCashSection(canRefund: boolean, canSetup: boolean) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const resolved = requested === "movements" ? "collect" :
    requested === "setup" ? "method-setup" :
      requested === "shifts" ? "shift-overview" : requested
  const section = pmsCashSections.find((item) => item.id === resolved &&
    (item.permission !== "refund" || canRefund) &&
    (item.permission !== "setup" || canSetup))?.id || "shift-overview"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}

export function useErpCashSection(canSetup: boolean) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const resolved = requested === "shifts" ? "shift-overview" : requested
  const section = erpCashSections.find((item) => item.id === resolved &&
    (item.permission !== "setup" || canSetup))?.id || "shift-overview"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}
