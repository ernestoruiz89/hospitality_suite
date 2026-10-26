import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"
import { availableErpCreditSections } from "./ErpCreditSections"

type Balance = { receivable: string; unbilled: string; overdue: string;
  exposure: string; oldest_due: string | null }
type CreditRow = { party: string; customer: string; customer_name: string;
  kind: string; modified: string; status: string; grant_authorized: boolean;
  credit_authorized: boolean; limit: string; receivable: string;
  unbilled: string; overdue: string; available: string; exposure: string;
  credit_days: number; valid_until: string | null; by_currency: Record<string, Balance> }
type Overview = { currency: string; property_credit_enabled: boolean;
  total: number; offset: number; page_length: number; rows: CreditRow[] }
type Detail = CreditRow & { reason: string; invoice_total: number;
  invoice_offset: number; invoice_has_more: boolean;
  invoices: { name: string; currency: string; outstanding: string;
    due_date: string; overdue: boolean }[] }
type Customer = { name: string; customer_name: string }
type Terms = { kind: string; credit_authorized: boolean; credit_limit: string;
  credit_days: string; valid_until: string; reason: string }

const emptyTerms: Terms = { kind: "Company", credit_authorized: false,
  credit_limit: "0", credit_days: "30", valid_until: "", reason: "" }
const statusLabels: Record<string, string> = {
  "Not Authorized": "Sin autorización vigente", "Currency Review": "Revisar otra moneda",
  Overdue: "Vencido", "Over Limit": "Sobre el límite", Available: "Disponible",
}
const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"
const issueText = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo completar la operación."
const money = (value: string, currency: string) => `${currency} ${value}`

export function ErpCredit({ property, canSetup }: { property: Property; canSetup: boolean }) {
  const [params, setParams] = useSearchParams()
  const sections = availableErpCreditSections(canSetup)
  const section = sections.find((item) => item.id === params.get("section"))?.id || "payers"
  const customer = params.get("customer") || ""
  const requestedOffset = Number(params.get("offset") || 0)
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0
  const requestedInvoiceOffset = Number(params.get("invoice_offset") || 0)
  const invoiceOffset = Number.isSafeInteger(requestedInvoiceOffset) && requestedInvoiceOffset >= 0
    ? requestedInvoiceOffset : 0
  const [overview, setOverview] = useState<Overview | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [search, setSearch] = useState("")
  const [candidates, setCandidates] = useState<Customer[]>([])
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)
  const [terms, setTerms] = useState<Terms>(emptyTerms)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  const refreshOverview = useCallback(async (signal?: AbortSignal) => {
    const result = await call<Overview>("credit_overview", {
      property_name: property.name, offset: String(offset), page_length: "50",
    }, signal)
    if (!signal?.aborted) setOverview(result)
  }, [property.name, offset])
  const refreshDetail = useCallback(async (signal?: AbortSignal) => {
    if (!customer) { setDetail(null); return }
    const result = await call<Detail>("credit_status", {
      property_name: property.name, customer, offset: String(invoiceOffset),
      page_length: "50",
    }, signal)
    if (!signal?.aborted) setDetail(result)
  }, [property.name, customer, invoiceOffset])

  useEffect(() => {
    if (!params.has("section") || section === params.get("section")) return
    const next = new URLSearchParams(params); next.set("section", section)
    setParams(next, { replace: true })
  }, [params, section, setParams])
  useEffect(() => {
    const controller = new AbortController()
    setOverview(null); setError("")
    refreshOverview(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issueText(issue))
    })
    return () => controller.abort()
  }, [refreshOverview])
  useEffect(() => {
    const controller = new AbortController()
    setDetail(null); setDetailError("")
    refreshDetail(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setDetailError(issueText(issue))
    })
    return () => controller.abort()
  }, [refreshDetail])
  useEffect(() => {
    if (!detail) return
    setTerms({ kind: detail.kind, credit_authorized: detail.grant_authorized,
      credit_limit: detail.limit, credit_days: String(detail.credit_days),
      valid_until: detail.valid_until || "", reason: "" })
  }, [detail?.party, detail?.modified])

  function navigate(nextSection: string, nextCustomer = "") {
    const next = new URLSearchParams()
    next.set("section", nextSection)
    if (nextCustomer) next.set("customer", nextCustomer)
    setParams(next)
    setError(""); setDetailError(""); setNotice("")
    if (nextSection === "new") {
      setTerms(emptyTerms); setSelectedCustomer(null); setCandidates([]); setSearch("")
    }
  }
  function changePage(nextOffset: number) {
    const next = new URLSearchParams(params)
    if (nextOffset) next.set("offset", String(nextOffset))
    else next.delete("offset")
    setParams(next)
  }
  function changeInvoicePage(nextOffset: number) {
    const next = new URLSearchParams(params)
    if (nextOffset) next.set("invoice_offset", String(nextOffset))
    else next.delete("invoice_offset")
    setParams(next)
  }
  async function findCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (search.trim().length < 2 || busy) return
    setBusy(true); setError(""); setCandidates([]); setSelectedCustomer(null)
    try {
      const result = await call<{ rows: Customer[] }>("erp_credit_customer_search", {
        property_name: property.name, search: search.trim(),
      })
      setCandidates(result.rows)
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSetup || busy || section === "new" && !selectedCustomer ||
        section === "terms" && !detail) return
    const values = { kind: terms.kind, credit_authorized: terms.credit_authorized ? 1 : 0,
      credit_limit: terms.credit_limit, credit_days: Number(terms.credit_days),
      valid_until: terms.valid_until || null, reason: terms.reason.trim() }
    const signature = JSON.stringify([property.name, section, selectedCustomer?.name,
      detail?.party, detail?.modified, values])
    if (pending.current?.signature !== signature) pending.current = {
      signature, key: crypto.randomUUID(),
    }
    setBusy(true); setError(""); setNotice("")
    try {
      if (section === "new" && selectedCustomer) {
        await postMethod("save_setup", { property_name: property.name,
          section: "billing_party", data: { customer: selectedCustomer.name, ...values },
          request_key: pending.current.key })
        pending.current = null
        await refreshOverview()
        navigate("terms", selectedCustomer.name)
      } else if (detail) {
        await execute(property.name, "billing_party", { party: detail.party,
          modified: detail.modified, ...values }, pending.current.key)
        pending.current = null
        await Promise.all([refreshOverview(), refreshDetail()])
        setNotice("Condiciones de crédito guardadas.")
      }
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }

  const termsForm = <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
    <label className="space-y-1 text-sm"><span>Tipo de pagador</span><select className={selectClass}
      value={terms.kind} onChange={(event) => setTerms({ ...terms, kind: event.target.value })}>
      <option value="Company">Empresa</option><option value="Agency">Agencia</option>
      <option value="Individual">Persona</option></select></label>
    <label className="flex items-center gap-2 self-end text-sm"><input type="checkbox"
      checked={terms.credit_authorized} onChange={(event) => setTerms({ ...terms,
        credit_authorized: event.target.checked })} />Autorizar crédito</label>
    <label className="space-y-1 text-sm"><span>Límite ({property.currency})</span><Input required
      type="number" min="0" step="0.01" value={terms.credit_limit}
      onChange={(event) => setTerms({ ...terms, credit_limit: event.target.value })} /></label>
    <label className="space-y-1 text-sm"><span>Plazo de pago (días)</span><Input required
      type="number" min="0" max="365" step="1" value={terms.credit_days}
      onChange={(event) => setTerms({ ...terms, credit_days: event.target.value })} /></label>
    <label className="space-y-1 text-sm"><span>Vigente hasta</span><Input type="date"
      value={terms.valid_until} onChange={(event) => setTerms({ ...terms,
        valid_until: event.target.value })} /></label>
    <label className="space-y-1 text-sm sm:col-span-2"><span>Motivo</span><Input required
      minLength={8} maxLength={500} value={terms.reason}
      onChange={(event) => setTerms({ ...terms, reason: event.target.value })} /></label>
    <Button disabled={busy} className="sm:col-span-2">{section === "new" ? "Registrar pagador" : "Guardar condiciones"}</Button>
  </form>

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Crédito empresarial</h1>
      <p className="mt-1 text-sm text-muted-foreground">{property.brand_name || property.property_name} · {sections.find((item) => item.id === section)?.label}</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {detailError && section === "payers" && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{detailError}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!overview && !error ? <Skeleton className="h-72" /> : overview && <>
      {!overview.property_credit_enabled && <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">El crédito del establecimiento está deshabilitado. {canSetup && <Link className="underline" to="/setup?section=reservations">Revise la política en Configuración</Link>}</p>}
      {section === "payers" && <Card><CardHeader><CardTitle>Pagadores y exposición</CardTitle>
        <CardDescription>{overview.total} pagadores · saldos facturados y sin facturar separados de otras monedas.</CardDescription>
      </CardHeader><CardContent className="space-y-3">
        {overview.rows.map((row) => <div key={row.party} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
          <div><strong>{row.customer_name || row.customer}</strong><p className="text-muted-foreground">{statusLabels[row.status] || row.status} · Límite {money(row.limit, overview.currency)} · Por cobrar {money(row.receivable, overview.currency)} · Sin facturar {money(row.unbilled, overview.currency)} · Vencido {money(row.overdue, overview.currency)} · Disponible {money(row.available, overview.currency)}</p></div>
          <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => navigate("payers", row.customer)}>Ver facturas</Button>
            {canSetup && <Button size="sm" variant="outline" onClick={() => navigate("terms", row.customer)}>Condiciones</Button>}</div>
        </div>)}
        {!overview.rows.length && <p className="text-sm text-muted-foreground">No hay pagadores registrados.</p>}
        <div className="flex gap-2"><Button type="button" variant="outline" disabled={!offset || busy} onClick={() => changePage(Math.max(0, offset - 50))}>Anterior</Button>
          <Button type="button" variant="outline" disabled={offset + overview.rows.length >= overview.total || busy} onClick={() => changePage(offset + 50)}>Siguiente</Button></div>
      </CardContent></Card>}
      {section === "new" && canSetup && <Card><CardHeader><CardTitle>Registrar pagador</CardTitle>
        <CardDescription>Busque un cliente ERPNext existente y defina sus condiciones para este establecimiento.</CardDescription>
      </CardHeader><CardContent className="space-y-5">
        <form onSubmit={findCustomer} className="flex flex-wrap items-end gap-2"><label className="min-w-52 flex-1 space-y-1 text-sm"><span>Buscar cliente</span><Input minLength={2} maxLength={100} value={search} onChange={(event) => { setSearch(event.target.value); setSelectedCustomer(null); setCandidates([]) }} /></label><Button type="submit" variant="outline" disabled={busy || search.trim().length < 2}>Buscar</Button></form>
        {!!candidates.length && <div className="grid gap-2">{candidates.map((row) => <Button key={row.name} type="button" variant={selectedCustomer?.name === row.name ? "secondary" : "outline"} className="justify-start" onClick={() => setSelectedCustomer(row)}>{row.customer_name} · {row.name}</Button>)}</div>}
        {selectedCustomer && <><p className="text-sm">Pagador seleccionado: <strong>{selectedCustomer.customer_name}</strong></p>{termsForm}</>}
      </CardContent></Card>}
      {section === "terms" && canSetup && <Card><CardHeader><CardTitle>Condiciones de crédito</CardTitle>
        <CardDescription>{detail ? `${detail.customer_name || detail.customer} · ${detail.customer}` : "Seleccione un pagador desde Cartera y pagadores."}</CardDescription>
      </CardHeader><CardContent>{detailError ? <p role="alert" className="text-sm text-destructive">{detailError}</p> :
        customer && !detail ? <Skeleton className="h-48" /> : detail ? termsForm :
        <Button type="button" variant="outline" onClick={() => navigate("payers")}>Ver pagadores</Button>}</CardContent></Card>}
      {customer && detail && <Card><CardHeader><CardTitle>Facturas y exposición de {detail.customer_name || detail.customer}</CardTitle>
        <CardDescription>{statusLabels[detail.status] || detail.status} · {detail.invoice_total} facturas pendientes de este establecimiento.</CardDescription>
      </CardHeader><CardContent className="space-y-4 text-sm">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(detail.by_currency).map(([currency, balance]) => <div key={currency} className="rounded-lg border p-3"><strong>{currency}</strong><p>Por cobrar: {money(balance.receivable, currency)}</p><p>Sin facturar: {money(balance.unbilled, currency)}</p><p>Vencido: {money(balance.overdue, currency)}</p></div>)}</div>
        <div className="space-y-2">{detail.invoices.map((invoice) => <div key={invoice.name} className="flex flex-wrap justify-between gap-2 rounded-lg border p-3"><span><strong>{invoice.name}</strong> · vence {invoice.due_date} {invoice.overdue && "· Vencida"}</span><span>{money(invoice.outstanding, invoice.currency)}</span></div>)}
          {!detail.invoices.length && <p className="text-muted-foreground">Sin facturas pendientes en este establecimiento.</p>}</div>
        <div className="flex gap-2"><Button type="button" variant="outline" disabled={!invoiceOffset} onClick={() => changeInvoicePage(Math.max(0, invoiceOffset - 50))}>Anterior</Button><Button type="button" variant="outline" disabled={!detail.invoice_has_more} onClick={() => changeInvoicePage(invoiceOffset + 50)}>Siguiente</Button></div>
      </CardContent></Card>}
    </>}
  </div>
}
