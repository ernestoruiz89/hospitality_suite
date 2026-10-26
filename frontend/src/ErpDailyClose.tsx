import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { dailyCloseSections } from "./DailyCloseSections"
import { AuditReviewPanel, type AuditReview } from "./AuditReviewPanel"

type Blocker = { type: string; documents: string[]; hint?: string;
  items?: { name: string; label?: string; detail?: string }[] }
type Currency = { currency: string; precision: number } & Record<string, string | number>
type Source = Record<string, string | number | boolean | null>
type Financial = { currencies?: Currency[]; sources?: Record<string, Source[]>;
  breakdown?: { treasury?: Source[]; petty_expenses?: Source[] }; captured_at?: string }
type Snapshot = { production?: string; occupancy_percent?: number;
  room_nights?: number; rotations?: number; day_pass_no_room_count?: number;
  close_review?: { starts_at: string; ends_at: string; time_zone: string };
  audit_review?: AuditReview;
  financial: Financial }
type Close = { name: string; business_date: string; revision: number;
  status: string; closed_at?: string | null; reason?: string | null }
type Detail = Close & { snapshot: Snapshot; blockers: Blocker[] }
type Overview = { business_date: string; base_currency: string;
  groups: { title: string; metrics: { key: string; label: string }[] }[];
  current: Detail | null }
type History = { rows: Close[]; offset: number; has_more: boolean }
type Review = { close: string; status: string; period: Snapshot;
  blockers: Blocker[]; review_acceptance: string }

const sourceLabels: Record<string, string> = {
  invoices: "Facturas y notas de crédito", cutover_opening_invoices: "Cartera trasladada",
  movements: "Cobros y depósitos", native_pos: "Caja POS",
  pending_charges: "Cargos pendientes", scheduled_charges: "Cargos programados",
  receivables: "Cartera vigente", unallocated_advances: "Anticipos por aplicar",
  guarantees: "Garantías disponibles", petty_expenses: "Gastos de Caja Chica",
  petty_variances: "Diferencias de Caja Chica",
  treasury_movements: "Otros movimientos financieros",
  unattributed_movements: "Movimientos sin fecha operativa",
}

export function ErpDailyClose({ property, canApprove }: {
  property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = dailyCloseSections.find((item) => item.id === searchParams.get("section")) || dailyCloseSections[0]
  const closeName = searchParams.get("close") || ""
  const [overview, setOverview] = useState<Overview | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  const [latestCloseName, setLatestCloseName] = useState("")
  const [review, setReview] = useState<Review | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [reason, setReason] = useState("")
  const [reopenReason, setReopenReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)
  const refreshOverview = useCallback(async () => {
    setOverview(await call<Overview>("erp_close_snapshot", { property_name: property.name }))
  }, [property.name])
  const loadHistory = useCallback(async (query: string, start: number) => {
    const result = await call<History>("erp_close_history", { property_name: property.name,
      search: query, offset: String(start), page_length: "50" })
    setHistory(result)
    if (!query && start === 0) setLatestCloseName(result.rows[0]?.name || "")
  }, [property.name])
  useEffect(() => {
    if (!searchParams.has("section") || dailyCloseSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", dailyCloseSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    setOverview(null); setHistory(null); setLatestCloseName(""); setReview(null); setDetail(null)
    setSearch(""); setAppliedSearch(""); setOffset(0); setReason("")
    setReopenReason(""); setError(""); setNotice(""); pending.current = null
    Promise.all([refreshOverview(), loadHistory("", 0)])
      .catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar el cierre."))
  }, [refreshOverview, loadHistory])
  useEffect(() => {
    if (!closeName) { setDetail(null); return }
    let active = true
    setDetail(null); setError("")
    call<Detail>("erp_close_detail", { property_name: property.name, name: closeName })
      .then((result) => { if (active) setDetail(result) })
      .catch((issue: unknown) => { if (active) setError(issue instanceof Error ? issue.message : "No se pudo consultar el cierre.") })
    return () => { active = false }
  }, [closeName, property.name])
  async function command<T>(action: string, payload: Record<string, unknown>): Promise<T | null> {
    if (busy) return null
    setBusy(true); setError(""); setNotice("")
    const signature = JSON.stringify([property.name, action, payload])
    if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() }
    try {
      const result = await execute<T>(property.name, action, payload, pending.current.key)
      pending.current = null
      return result
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo completar el cierre.")
      return null
    } finally { setBusy(false) }
  }
  async function prepare() {
    const result = await command<Review>("daily_close", { confirm: false,
      reason: reason.trim() })
    if (!result) return
    setReview(result)
    setNotice("Revisión preparada. Compruebe cifras y pendientes antes de confirmar.")
    try { await Promise.all([refreshOverview(), loadHistory(appliedSearch, offset)]) }
    catch { setNotice("Revisión preparada. Actualice el historial para consultar el registro.") }
  }
  async function confirm() {
    if (!review || review.blockers.length || !canApprove) return
    const result = await command<{ status: string }>("daily_close", {
      confirm: true, review_acceptance: review.review_acceptance,
      reason: reason.trim() })
    if (result?.status === "Closed") window.location.reload()
  }
  async function reopen() {
    if (!detail || !reopenReason.trim() || !canApprove) return
    const result = await command<{ status: string }>("reopen_day", {
      close: detail.name, reason: reopenReason.trim() })
    if (result?.status === "Reopened") window.location.reload()
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
  async function searchHistory(query: string, start: number) {
    setBusy(true); setError("")
    try { await loadHistory(query, start); setAppliedSearch(query); setOffset(start) }
    catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo consultar el historial.") }
    finally { setBusy(false) }
  }
  const snapshot = closeName ? detail?.snapshot : review?.period || overview?.current?.snapshot
  const reviewBlockers = review?.blockers || overview?.current?.blockers || []
  const blockers = closeName ? detail?.blockers || [] : reviewBlockers
  const financial = snapshot?.financial
  const currencies = financial?.currencies || []
  const treasury = financial?.breakdown?.treasury || []
  const pettyExpenses = financial?.breakdown?.petty_expenses || []
  const sources = financial?.sources || {}
  const download = () => {
    if (!snapshot) return
    const blob = new Blob([JSON.stringify({ property: property.name,
      business_date: detail?.business_date || overview?.business_date,
      revision: detail?.revision || overview?.current?.revision,
      snapshot, blockers }, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `cierre-${detail?.business_date || overview?.business_date}-${detail?.revision || overview?.current?.revision || "revision"}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Cierre diario · {property.property_name} · Fecha operativa {overview?.business_date || property.business_date}. La producción, los cobros, Caja Chica y la financiación se presentan por separado y por moneda.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{notice}</p>}
    {section.id === "review" && (overview ? <Card><CardHeader><CardTitle>Preparar y confirmar</CardTitle><CardDescription>Preparar actualiza cargos programados y congela una revisión del día. Si cambia la observación, prepare una nueva revisión antes de confirmar.</CardDescription></CardHeader><CardContent className="space-y-3">
      <Input maxLength={1000} placeholder="Observación de cierre (opcional)" value={reason} onChange={(event) => { setReason(event.target.value); setReview(null) }} />
      <div className="flex flex-wrap gap-2"><Button disabled={busy} variant="outline" onClick={() => void prepare()}>{review ? "Actualizar revisión" : "Preparar revisión"}</Button><Button variant="outline" onClick={viewCurrent}>Ver resumen financiero</Button>{canApprove && <Button disabled={busy || !review || !!review.blockers.length} onClick={() => void confirm()}>Confirmar cierre y avanzar fecha</Button>}</div>
      {overview.current && !review && <p className="text-sm text-muted-foreground">Hay una revisión guardada. Prepare una revisión actual para poder confirmarla.</p>}
      {reviewBlockers.length ? <div className="space-y-2">{reviewBlockers.map((row) => <div key={row.type} className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm"><strong>{row.type} · {row.documents.length}</strong>{row.hint && <p className="mt-1 text-xs">{row.hint}</p>}{row.items?.map((item) => <p key={item.name} className="mt-1 text-xs text-muted-foreground">{item.name} · {item.label} · {item.detail}</p>)}</div>)}</div> : <p className="text-sm text-muted-foreground">Sin pendientes bloqueantes en la revisión mostrada.</p>}
    </CardContent></Card> : !error && <Skeleton className="h-80 rounded-xl" />)}
    {section.id === "review" && review?.period.audit_review && <AuditReviewPanel key={`${property.name}:${review.close}:${review.review_acceptance}`} propertyName={property.name} review={review.period.audit_review} />}
    {section.id === "snapshot" && (overview && snapshot && financial ? <>
      {detail ? <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-5 text-sm"><span>Snapshot {detail.business_date} · Revisión {detail.revision} · {detail.status} · {detail.closed_at || "—"}</span><Button variant="outline" onClick={viewCurrent}>Volver al día actual</Button></CardContent></Card> : <p className="text-sm text-muted-foreground">Resumen del día actual. Prepare la revisión antes de confirmar el cierre.</p>}
      <div className="grid gap-4 md:grid-cols-4">{[["Producción operativa", snapshot.production || "0"], ["Ocupación", `${snapshot.occupancy_percent || 0}%`], ["Noches comercializadas", String(snapshot.room_nights || 0)], ["Day Pass sin habitación", String(snapshot.day_pass_no_room_count || 0)]].map(([label, value]) => <Card key={label}><CardContent className="pt-5"><p className="text-xs text-muted-foreground">{label}</p><strong className="mt-2 block text-lg">{value}</strong></CardContent></Card>)}</div>
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-muted-foreground">Período {snapshot.close_review?.starts_at || "—"} → {snapshot.close_review?.ends_at || "—"} · Capturado {financial.captured_at}</p><Button variant="outline" onClick={download}>Descargar snapshot JSON</Button></div>
      {overview.groups.map((group) => <Card key={group.title}><CardHeader><CardTitle>{group.title}</CardTitle><CardDescription>Importes separados por moneda del establecimiento.</CardDescription></CardHeader><CardContent className="overflow-x-auto"><table className="w-full min-w-[500px] text-sm"><thead><tr className="border-b text-left"><th className="py-2">Indicador</th>{currencies.map((row) => <th key={row.currency} className="py-2 text-right">{row.currency}</th>)}</tr></thead><tbody>{group.metrics.map((metric) => <tr key={metric.key} className="border-b last:border-0"><td className="py-2">{metric.label}</td>{currencies.map((row) => <td key={row.currency} className="py-2 text-right tabular-nums">{row[metric.key] ?? "0.00"}</td>)}</tr>)}</tbody></table></CardContent></Card>)}
      <div className="grid gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle>Financiación y traspasos</CardTitle></CardHeader><CardContent className="space-y-2">{treasury.map((row, index) => <p key={index} className="border-b pb-2 text-sm">{row.kind} · {row.concept} · {row.channel}<span className="block text-xs text-muted-foreground">{row.currency} {row.amount} · {row.counter_account} → {row.cash_account}</span></p>)}{!treasury.length && <p className="text-sm text-muted-foreground">Sin movimientos.</p>}</CardContent></Card><Card><CardHeader><CardTitle>Gastos de Caja Chica</CardTitle></CardHeader><CardContent className="space-y-2">{pettyExpenses.map((row, index) => <p key={index} className="border-b pb-2 text-sm">{row.category_label} · {row.currency} {row.amount}<span className="block text-xs text-muted-foreground">{row.expense_account} → {row.petty_account}</span></p>)}{!pettyExpenses.length && <p className="text-sm text-muted-foreground">Sin desembolsos.</p>}</CardContent></Card></div>
      <Card><CardHeader><CardTitle>Documentos del snapshot</CardTitle><CardDescription>El archivo descargable incluye todos los documentos y saldos capturados.</CardDescription></CardHeader><CardContent className="space-y-2">{Object.entries(sources).filter(([, rows]) => rows.length).map(([key, rows]) => <details key={key} className="rounded-md border p-3 text-sm"><summary className="cursor-pointer font-medium">{sourceLabels[key] || key} · {rows.length}</summary><div className="mt-2 space-y-1">{rows.slice(0, 50).map((row, index) => <p key={index} className="break-all border-b pb-1 text-xs text-muted-foreground">{row.name || row.source || "Documento"} · {row.currency || ""} · {row.amount || row.outstanding || row.available || ""}</p>)}{rows.length > 50 && <p className="text-xs text-muted-foreground">Primeros 50. Descargue el snapshot para consultar todos.</p>}</div></details>)}{!Object.values(sources).some((rows) => rows.length) && <p className="text-sm text-muted-foreground">Sin documentos.</p>}</CardContent></Card>
      {snapshot.audit_review && <AuditReviewPanel key={`${property.name}:${closeName || "current"}:${snapshot.audit_review.business_date}`} propertyName={property.name} review={snapshot.audit_review} />}
      {detail?.status === "Closed" && canApprove && latestCloseName === detail.name && <Card><CardHeader><CardTitle>Reabrir cierre</CardTitle><CardDescription>Solo puede reabrirse el último cierre confirmado.</CardDescription></CardHeader><CardContent className="flex flex-wrap gap-2"><Input maxLength={500} placeholder="Motivo para reabrir el último cierre" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} className="min-w-64 flex-1" /><Button variant="outline" disabled={busy || !reopenReason.trim()} onClick={() => void reopen()}>Reabrir último día</Button></CardContent></Card>}
    </> : !error && <Skeleton className="h-80 rounded-xl" />)}
    {section.id === "history" && (history ? <Card><CardHeader><CardTitle>Historial de cierres</CardTitle><CardDescription>Cada revisión confirmada conserva su resumen aun si el día se reabre.</CardDescription></CardHeader><CardContent className="space-y-3"><form onSubmit={(event) => { event.preventDefault(); void searchHistory(search.trim(), 0) }} className="flex flex-wrap gap-2"><Input maxLength={100} placeholder="Fecha AAAA-MM-DD o número de cierre" value={search} onChange={(event) => setSearch(event.target.value)} className="min-w-64 flex-1" /><Button disabled={busy} variant="outline">Buscar</Button></form>{history.rows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 text-sm"><span>{row.business_date} · Revisión {row.revision} · {row.status} · {row.closed_at || "—"}</span><Button size="sm" variant="outline" disabled={busy} onClick={() => viewDetail(row.name)}>Ver snapshot</Button></div>)}{!history.rows.length && <p className="text-sm text-muted-foreground">Sin cierres para esta búsqueda.</p>}<div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy || offset === 0} onClick={() => void searchHistory(appliedSearch, Math.max(0, offset - 50))}>Anterior</Button><Button size="sm" variant="outline" disabled={busy || !history.has_more} onClick={() => void searchHistory(appliedSearch, offset + 50)}>Siguiente</Button></div></CardContent></Card> : !error && <Skeleton className="h-80 rounded-xl" />)}
  </div>
}
