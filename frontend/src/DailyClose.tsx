import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { dailyCloseSections } from "./DailyCloseSections"

type Row = Record<string, string | number | null>
type Balance = { account: string; account_code: string; account_name: string;
  account_currency: string; balance: string; account_balance: string }
type Snapshot = { business_date: string; base_currency: string;
  breakdown: Record<string, Row[]>; ledger: { day_debit: string; day_credit: string;
    balances: Balance[]; control_accounts: Balance[] }; sources: Record<string, unknown[]> }
type Review = { snapshot: Snapshot; blockers: { type: string; count: number; documents: string[] }[];
  review_acceptance: string }
type Close = { name: string; business_date: string; revision: number; status: string; closed_at: string; reason: string }
type Detail = Close & { snapshot: Snapshot }

const labels: Record<string, string> = {
  production: "Producción por cuenta de ingreso", taxes: "Impuestos de los cargos",
  fiscal_documents: "Facturas y notas de crédito", credit_notes: "Notas de crédito",
  opening_receivables: "Cartera trasladada de ERPNext",
  opening_payables: "Proveedores trasladados de ERPNext",
  opening_customer_credits: "Créditos y anticipos de apertura",
  opening_guarantees: "Garantías trasladadas de ERPNext",
  opening_guarantee_refunds: "Devoluciones de garantías de apertura",
  opening_supplier_credits: "Créditos de proveedores de apertura",
  supplier_credit_applications: "Aplicaciones de créditos de proveedores",
  foreign_supplier_credit_applications: "Créditos extranjeros aplicados a deudas",
  supplier_credit_exchange_variance: "Cambio en aplicaciones de créditos de proveedores",
  opening_supplier_credit_refunds: "Reintegros de créditos de proveedores",
  foreign_supplier_credit_refunds: "Principal extranjero reintegrado por proveedores",
  supplier_credit_refund_exchange_variance: "Cambio en reintegros de créditos de proveedores",
  opening_credit_applications: "Aplicaciones de créditos de apertura",
  foreign_opening_credit_applications: "Aplicaciones de notas extranjeras a cartera",
  foreign_opening_credit_source_release: "Valor histórico liberado de notas extranjeras",
  foreign_opening_credit_exchange_differences: "Cambio en aplicaciones de notas extranjeras",
  opening_guarantee_applications: "Aplicaciones de garantías de apertura",
  opening_credit_refunds: "Devoluciones de créditos de apertura",
  foreign_opening_credit_refunds: "Principal extranjero devuelto de notas",
  foreign_opening_credit_refund_exchange_differences: "Cambio en devoluciones de notas extranjeras",
  opening_supplier_payments: "Pagos de proveedores de apertura",
  opening_supplier_settlements: "Deudas de apertura liquidadas",
  opening_exchange_differences: "Cambio de deudas de apertura",
  opening_customer_settlements: "Cartera extranjera cobrada",
  opening_customer_refunds: "Cartera extranjera restituida",
  opening_customer_exchange_differences: "Cambio de cartera extranjera",
  opening_customer_refund_exchange_differences: "Cambio revertido de cartera extranjera",
  customer_cash: "Cobros y depósitos de huéspedes", other_cash: "Otros movimientos de Caja y banco",
  supplier_returns: "Devoluciones a proveedores",
  agency_commissions: "Comisiones devengadas de agencias",
  agency_commission_cancellations: "Comisiones de agencia anuladas",
  agency_commission_payments: "Pagos de comisiones de agencias",
  treasury: "Financiación y entregas de Caja Chica", petty_expenses: "Desembolsos de Caja Chica",
  petty_variances: "Diferencias aprobadas de Caja Chica",
}
const fields: Record<string, string> = {
  kind: "Tipo", document_type: "Documento", currency: "Moneda",
  invoice_currency: "Moneda de factura", supplier: "Proveedor", purchase: "Compra",
  agent: "Agencia", payable_account: "Cuenta por pagar",
  party: "Cliente", customer: "Cliente", receivable_account: "Cuenta por cobrar",
  opening_credit: "Crédito de apertura", receivable: "Cargo",
  pms_opening_credit: "Crédito de apertura",
  pms_opening_payable: "Factura de apertura", credit_kind: "Origen del crédito",
  pms_opening_supplier_credit: "Crédito de proveedor", target_type: "Destino",
  opening_payable: "Factura de apertura",
  pms_agent_commission: "Comisión",
  channel: "Canal",
  income_account: "Ingreso", tax_account: "Impuesto", cash_account: "Caja/banco",
  counter_account: "Contracuenta", pms_counter_account: "Contracuenta",
  pms_concept: "Concepto", concept: "Concepto", concept_label: "Nombre original",
  category: "Categoría", category_label: "Nombre original", expense_account: "Gasto",
  petty_account: "Caja Chica", account: "Cuenta",
}
function total(rows: Row[] | undefined, predicate?: (row: Row) => boolean) {
  return (rows || []).filter((row) => !predicate || predicate(row))
    .reduce((sum, row) => sum + Number(row.base_amount || 0), 0).toFixed(2)
}

export function DailyClose({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = dailyCloseSections.find((item) => item.id === searchParams.get("section")) || dailyCloseSections[0]
  const closeName = searchParams.get("close") || ""
  const [review, setReview] = useState<Review | null>(null)
  const [history, setHistory] = useState<Close[] | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [reason, setReason] = useState("")
  const [reopenReason, setReopenReason] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)
  const refresh = useCallback(async () => {
    const [nextReview, nextHistory] = await Promise.all([
      call<Review>("pms_close_preview", { property_name: property.name }),
      call<Close[]>("pms_close_history", { property_name: property.name }),
    ])
    setReview(nextReview); setHistory(nextHistory)
  }, [property.name])
  useEffect(() => {
    if (!searchParams.has("section") || dailyCloseSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", dailyCloseSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    setReview(null); setDetail(null); setHistory(null); setError("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo revisar el cierre."))
  }, [refresh])
  useEffect(() => {
    if (!closeName) { setDetail(null); return }
    let active = true
    setDetail(null); setError("")
    call<Detail>("pms_close_detail", { property_name: property.name, name: closeName })
      .then((result) => { if (active) setDetail(result) })
      .catch((issue: unknown) => { if (active) setError(issue instanceof Error ? issue.message : "No se pudo consultar el cierre.") })
    return () => { active = false }
  }, [closeName, property.name])
  async function confirm() {
    if (!review || busy || review.blockers.length || !canApprove) return
    setBusy(true); setError("")
    const payload = { review_acceptance: review.review_acceptance, reason: reason.trim() }
    const signature = JSON.stringify([property.name, "pms_daily_close", payload])
    if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() }
    try {
      await execute(property.name, "pms_daily_close", payload, pending.current.key)
      pending.current = null
      window.location.reload()
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo confirmar el cierre.")
      setBusy(false)
    }
  }
  function viewDetail(name: string) {
    const next = new URLSearchParams(searchParams)
    next.set("section", "snapshot")
    next.set("close", name)
    setSearchParams(next)
  }
  function viewCurrent() {
    const next = new URLSearchParams(searchParams)
    next.set("section", "snapshot")
    next.delete("close")
    setSearchParams(next)
  }
  async function reopen() {
    if (!detail || !reopenReason.trim() || !canApprove || busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "reopen_day",
        { close: detail.name, reason: reopenReason.trim() }, crypto.randomUUID())
      window.location.reload()
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo reabrir el día.")
      setBusy(false)
    }
  }
  const snapshot = closeName ? detail?.snapshot : review?.snapshot
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1><p className="mt-2 text-sm text-muted-foreground">Cierre diario PMS · Fecha operativa {property.business_date}. El snapshot conserva saldos y fuentes sin sumar financiación ni Caja Chica a las ventas.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {section.id === "review" && (review ? <Card><CardHeader><CardTitle>Pendientes de cierre</CardTitle><CardDescription>{review.blockers.length ? "Resuelva estos registros y actualice la revisión." : "La revisión actual no tiene pendientes bloqueantes."}</CardDescription></CardHeader><CardContent className="space-y-3">{review.blockers.map((row) => <div key={row.type} className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm"><strong>{row.type} · {row.count}</strong><p className="mt-1 break-all text-xs text-muted-foreground">{row.documents.join(", ")}</p></div>)}<div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void refresh()}>Actualizar revisión</Button><Button variant="outline" onClick={viewCurrent}>Ver resumen financiero</Button></div>{canApprove && <div className="flex flex-wrap gap-3 border-t pt-4"><Input maxLength={1000} placeholder="Observación de cierre (opcional)" value={reason} onChange={(event) => setReason(event.target.value)} className="min-w-64 flex-1" /><Button disabled={busy || !!review.blockers.length} onClick={() => void confirm()}>Confirmar cierre y avanzar fecha</Button></div>}</CardContent></Card> : !error && <Skeleton className="h-80 rounded-xl" />)}
    {section.id === "snapshot" && (snapshot ? <>
      {detail ? <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-5 text-sm"><span>Snapshot del {detail.business_date} · Revisión {detail.revision} · {detail.status} · {detail.closed_at || "—"}{detail.reason && ` · ${detail.reason}`}</span><Button variant="outline" onClick={viewCurrent}>Volver al día actual</Button></CardContent></Card> : <p className="text-sm text-muted-foreground">Vista previa del día {property.business_date}. El cierre confirmado conservará su propio snapshot.</p>}
      <div className="grid gap-4 md:grid-cols-4">
        {[["Cargos base", total(snapshot.breakdown.production)],
          ["Cobros de clientes", total(snapshot.breakdown.customer_cash, (row) => row.kind === "Payment")],
          ["Gastos de Caja Chica", total(snapshot.breakdown.petty_expenses)],
          ["Asientos del día", snapshot.ledger.day_debit]].map(([label, value]) => <Card key={label}><CardContent className="pt-5"><p className="text-xs text-muted-foreground">{label}</p><strong className="mt-2 block text-lg">{snapshot.base_currency} {value}</strong></CardContent></Card>)}
      </div>
      <Card><CardHeader><CardTitle>Mayor y saldos de control</CardTitle><CardDescription>Débitos {snapshot.base_currency} {snapshot.ledger.day_debit} · Créditos {snapshot.base_currency} {snapshot.ledger.day_credit}. Saldos acumulados al cierre de la fecha.</CardDescription></CardHeader><CardContent className="space-y-2">{snapshot.ledger.control_accounts.map((row) => <div key={row.account} className="flex flex-wrap justify-between gap-2 border-b pb-2 text-sm"><span>{row.account_code} · {row.account_name}</span><strong>{row.account_currency} {row.account_balance} · Base {snapshot.base_currency} {row.balance}</strong></div>)}{!snapshot.ledger.control_accounts.length && <p className="text-sm text-muted-foreground">Sin cuentas de control configuradas.</p>}</CardContent></Card>
      {Object.entries(labels).map(([key, label]) => <Card key={key}><CardHeader><CardTitle>{label}</CardTitle><CardDescription>{snapshot.breakdown[key]?.length || 0} grupo(s), separados por cuenta, concepto y moneda.</CardDescription></CardHeader><CardContent className="space-y-2">{(snapshot.breakdown[key] || []).map((row, index) => <div key={index} className="flex flex-wrap items-start justify-between gap-2 border-b pb-2 text-sm"><span>{Object.entries(row).filter(([field, value]) => !["amount", "base_amount", "count"].includes(field) && value).map(([field, value]) => `${fields[field] || field}: ${value}`).join(" · ")}</span><strong>{row.currency || row.invoice_currency || snapshot.base_currency} {row.amount} · Base {snapshot.base_currency} {row.base_amount}</strong></div>)}{!snapshot.breakdown[key]?.length && <p className="text-sm text-muted-foreground">Sin movimientos.</p>}</CardContent></Card>)}
      {detail?.status === "Closed" && canApprove && history?.[0]?.name === detail.name && <Card><CardHeader><CardTitle>Reabrir último cierre</CardTitle><CardDescription>Indique el motivo antes de revertir el cierre de este día.</CardDescription></CardHeader><CardContent className="flex flex-wrap gap-3"><Input required maxLength={500} placeholder="Motivo para reabrir" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} className="min-w-64 flex-1" /><Button variant="outline" disabled={busy || !reopenReason.trim()} onClick={() => void reopen()}>Reabrir último día</Button></CardContent></Card>}
    </> : !error && <Skeleton className="h-80 rounded-xl" />)}
    {section.id === "history" && (history ? <Card><CardHeader><CardTitle>Cierres anteriores</CardTitle><CardDescription>Cada confirmación conserva su snapshot, incluso si el día fue reabierto.</CardDescription></CardHeader><CardContent className="space-y-2">{history.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 text-sm"><span>{row.business_date} · Revisión {row.revision} · {row.status} · {row.closed_at || "—"}</span><Button size="sm" variant="outline" disabled={busy} onClick={() => viewDetail(row.name)}>Ver snapshot</Button></div>)}{!history.length && <p className="text-sm text-muted-foreground">Aún no hay cierres.</p>}</CardContent></Card> : !error && <Skeleton className="h-80 rounded-xl" />)}
  </div>
}
