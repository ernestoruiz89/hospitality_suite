import { useEffect, useRef, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"

type Folio = { name: string; label: string | null; customer: string;
  customer_name: string; currency: string; stay: string | null; booking: string | null }
type FolioPage = { offset: number; has_more: boolean; rows: Folio[] }
type Quote = { ready: boolean; folio: string; label: string; customer: string;
  posting_date: string; currency: string; net_total: string; taxes: string;
  total: string; payable: string; advance: string; outstanding: string;
  outstanding_currency: string; scheduled: string; lines: number;
  acceptance: string }
type Issued = { invoice: string; outstanding: string; currency: string }

const PAGE_LENGTH = 25
const issueText = (issue: unknown) => issue instanceof Error ? issue.message :
  "No se pudo completar la operación."
const printInvoice = (name: string) =>
  `/printview?doctype=${encodeURIComponent("Sales Invoice")}&name=${encodeURIComponent(name)}`

export function ErpInvoicing({ property }: { property: Property }) {
  const [params] = useSearchParams()
  const initialFolio = params.get("folio") || ""
  const [search, setSearch] = useState(initialFolio)
  const [appliedSearch, setAppliedSearch] = useState(initialFolio)
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [page, setPage] = useState<FolioPage | null>(null)
  const [folio, setFolio] = useState(initialFolio)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError("")
    call<FolioPage>("erp_invoice_folios", { property_name: property.name,
      search: appliedSearch, offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setPage(result)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issueText(issue))
    })
    return () => controller.abort()
  }, [property.name, appliedSearch, offset, revision])

  const selected = page?.rows.find((row) => row.name === folio)
  function select(name: string) {
    setFolio(name); setQuote(null); setIssued(null); setError(""); setNotice("")
    pending.current = null
  }
  function searchFolios(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    select(""); setOffset(0); setAppliedSearch(search.trim())
  }
  async function review() {
    if (!selected || busy) return
    setBusy(true); setError(""); setNotice(""); setQuote(null); setIssued(null)
    try {
      const result = await postMethod<Quote>("preview", { property_name: property.name,
        action: "invoice", data: { folio: selected.name } })
      if (result.folio !== selected.name) throw new Error("La cuenta revisada no coincide con la selección.")
      setQuote(result)
      pending.current = null
      if (!result.ready) setNotice("Esta cuenta no tiene cargos nuevos para facturar.")
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }
  async function issue() {
    if (!selected || !quote?.ready || quote.folio !== selected.name || busy) return
    const signature = JSON.stringify([property.name, quote.folio, quote.acceptance])
    if (pending.current?.signature !== signature) pending.current = {
      signature, key: crypto.randomUUID(),
    }
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<Issued>(property.name, "invoice", {
        folio: quote.folio, invoice_acceptance: quote.acceptance,
      }, pending.current.key)
      pending.current = null
      setIssued(result); setQuote(null)
      setNotice("Factura emitida. La estancia permanece activa y no se registró un cobro.")
      setRevision((value) => value + 1)
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Facturar cuenta</h1>
      <p className="mt-1 text-sm text-muted-foreground">{property.brand_name || property.property_name} · Emita una factura ERPNext después de revisar los cargos; la estancia permanece activa.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {issued?.invoice && <Card><CardHeader><CardTitle>Factura {issued.invoice}</CardTitle>
      <CardDescription>Saldo pendiente: {issued.currency} {issued.outstanding}</CardDescription>
    </CardHeader><CardContent><Button asChild variant="outline"><a href={printInvoice(issued.invoice)} target="_blank" rel="noopener noreferrer">Consultar e imprimir factura</a></Button></CardContent></Card>}
    <Card><CardHeader><CardTitle>Cuentas abiertas</CardTitle>
      <CardDescription>Busque por cuenta, etiqueta, cliente, estancia o reserva. La revisión incluirá cargos pendientes y noches programadas.</CardDescription>
    </CardHeader><CardContent className="space-y-4">
      <form onSubmit={searchFolios} className="flex flex-wrap gap-2"><Input aria-label="Buscar cuentas" maxLength={80} value={search}
        onChange={(event) => setSearch(event.target.value)} className="min-w-48 flex-1" />
        <Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>
      {!page && !error ? <Skeleton className="h-48" /> : page && <>
        <div className="space-y-2">{page.rows.map((row) => <button type="button" key={row.name}
          onClick={() => select(row.name)} className={`block w-full rounded-md border p-3 text-left text-sm hover:bg-secondary ${folio === row.name ? "border-primary bg-secondary/50" : "border-border"}`}>
          <strong>{row.label || row.name}</strong> · {row.currency}<span className="block text-xs text-muted-foreground">{row.name} · {row.customer_name} · {row.stay ? `Estancia ${row.stay}` : row.booking ? `Reserva ${row.booking}` : "Sin estancia"}</span>
        </button>)}{!page.rows.length && <p className="text-sm text-muted-foreground">No hay cuentas abiertas con ese criterio.</p>}</div>
        <div className="flex gap-2"><Button type="button" variant="outline" disabled={busy || !offset} onClick={() => { select(""); setOffset(Math.max(0, offset - PAGE_LENGTH)) }}>Anterior</Button>
          <Button type="button" variant="outline" disabled={busy || !page.has_more} onClick={() => { select(""); setOffset(offset + PAGE_LENGTH) }}>Siguiente</Button></div>
      </>}
      {selected && <div className="space-y-3 border-t pt-4"><p className="text-sm">Cuenta elegida: <strong>{selected.label || selected.name}</strong> · {selected.customer_name}</p>
        <Button type="button" variant="outline" disabled={busy} onClick={() => void review()}>Revisar factura</Button></div>}
    </CardContent></Card>
    {selected && quote?.folio === selected.name && quote.ready && <Card><CardHeader><CardTitle>Revisión de factura</CardTitle>
      <CardDescription>{quote.label || quote.folio} · {quote.customer} · Fecha contable {quote.posting_date}</CardDescription>
    </CardHeader><CardContent className="space-y-3 text-sm">
      <p className="text-lg font-semibold">Total a facturar: {quote.currency} {quote.payable}</p>
      <div className="grid gap-2 sm:grid-cols-2"><p>Neto: {quote.currency} {quote.net_total}</p><p>Impuestos: {quote.currency} {quote.taxes}</p>
        <p>Anticipos y garantías por aplicar: {quote.currency} {quote.advance}</p>
        <p>Saldo de la nueva factura: {quote.outstanding_currency} {quote.outstanding}</p>
        <p>Alojamiento programado incluido: {quote.currency} {quote.scheduled}</p><p>Líneas: {quote.lines}</p></div>
      {quote.total !== quote.payable && <p>Total antes del redondeo: {quote.currency} {quote.total}</p>}
      <p className="text-muted-foreground">Emitir la factura no agrega un movimiento de dinero ni registra la salida.</p>
      <Button type="button" disabled={busy} onClick={() => void issue()}>Emitir factura</Button>
    </CardContent></Card>}
  </div>
}
