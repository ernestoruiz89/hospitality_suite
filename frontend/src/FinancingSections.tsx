import { useEffect } from "react"
import { useSearchParams } from "react-router-dom"

export type FinancingSection = "income" | "request-loan" | "repay-loan" | "contribute-capital" | "withdraw-capital" | "approvals" | "post" | "history" | "concepts"
export type FinancingRequestKind = "Loan Received" | "Loan Repayment" | "Capital Contribution" | "Capital Withdrawal"

const requestKinds: Partial<Record<FinancingSection, FinancingRequestKind>> = {
  "request-loan": "Loan Received", "repay-loan": "Loan Repayment",
  "contribute-capital": "Capital Contribution", "withdraw-capital": "Capital Withdrawal",
}

export function financingRequestKind(section: FinancingSection): FinancingRequestKind | null {
  return requestKinds[section] || null
}

export const financingSections: { id: FinancingSection; label: string; description: string }[] = [
  { id: "income", label: "Otros ingresos", description: "Registrar entradas sin factura" },
  { id: "request-loan", label: "Recibir préstamo", description: "Solicitar principal de un préstamo" },
  { id: "repay-loan", label: "Devolver préstamo", description: "Solicitar devolución de principal" },
  { id: "contribute-capital", label: "Aportar capital", description: "Solicitar entrada de capital" },
  { id: "withdraw-capital", label: "Retirar capital", description: "Solicitar retiro de un aporte" },
  { id: "approvals", label: "Solicitudes", description: "Revisar y aprobar pendientes" },
  { id: "post", label: "Contabilizar", description: "Registrar solicitudes aprobadas" },
  { id: "history", label: "Historial", description: "Consultar saldos y movimientos" },
  { id: "concepts", label: "Conceptos", description: "Configurar cuentas contables" },
]

export function useFinancingSection(canConfigure: boolean) {
  const [params, setParams] = useSearchParams()
  const requested = params.get("section")
  const resolved = requested === "request" ? "request-loan" : requested
  const section = financingSections.find((item) => item.id === resolved && (canConfigure || item.id !== "concepts"))?.id || "income"
  useEffect(() => {
    if (!requested || requested === section) return
    const next = new URLSearchParams(params)
    next.set("section", section)
    setParams(next, { replace: true })
  }, [requested, section, params, setParams])
  return section
}
