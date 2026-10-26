import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type Source = { name: string; kind: string; creation: string; business_date?: string | null;
  amount: string; settled: string; available: string; currency: string;
  direction: "Receive" | "Pay"; reference?: string | null; voucher?: string | null;
  method: string; method_label: string }
type Sources = { sources: Source[]; offset: number; has_more: boolean }
type Quote = { acceptance: string; source_payment: string; amount: string; fee: string;
  withholding: string; net: string; currency: string; direction: "Receive" | "Pay";
  exchange_rate: string; clearing_base: string; base_currency: string;
  previous: string; policy: { settlement_account: string; fee_account?: string;
    withholding_account?: string } }

const PAGE_LENGTH = 20
const kindLabel: Record<string, string> = {
  Payment: "Cobro", Advance: "Anticipo", Guarantee: "Garantía",
  Refund: "Devolución", "Guarantee Refund": "Devolución de garantía",
}

export function ErpSettlement({ property, shift, canOperate, onPosted }: {
  property: Property; shift: string; canOperate: boolean; onPosted: () => Promise<unknown> }) {
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [sources, setSources] = useState<Sources | null>(null)
  const [selected, setSelected] = useState<Source | null>(null)
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setSources(null); setError("")
    call<Sources>("erp_cash_settlement_sources", {
      property_name: property.name, search: query,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setSources(result)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error
        ? issue.message : "No se pudieron consultar los cobros pendientes.")
    })
    return () => controller.abort()
  }, [property.name, query, offset, version])

  useEffect(() => { setQuote(null); pending.current = null }, [shift, canOperate])

  function selectSource(source: Source) {
    setSelected(source); setAmount(source.available)
    setReference(""); setReason(""); setQuote(null); setError(""); setNotice("")
    pending.current = null
  }

  function searchSources(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSelected(null); setQuote(null); pending.current = null
    setOffset(0); setQuery(search.trim())
    if (search.trim() === query && offset === 0) setVersion((current) => current + 1)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !shift || !canOperate || busy) return
    const values = { source_payment: selected.name, amount,
      shift, reference: reference.trim(), reason: reason.trim() }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!quote) {
        setQuote(await call<Quote>("preview", {
          property_name: property.name, action: "settle_payment",
          data: JSON.stringify(values),
        }))
        return
      }
      const payload = { ...values, acceptance: quote.acceptance }
      const signature = JSON.stringify([property.name, "settle_payment", payload])
      if (pending.current?.signature !== signature) pending.current = {
        signature, key: crypto.randomUUID(),
      }
      const result = await execute<{ payment: string; journal_entry: string }>(
        property.name, "settle_payment", payload, pending.current.key)
      pending.current = null
      setSelected(null); setAmount(""); setReference(""); setReason(""); setQuote(null)
      setNotice(`Liquidación ${result.payment} registrada. Asiento ${result.journal_entry}.`)
      setVersion((current) => current + 1)
      try { await onPosted() } catch { /* The posting succeeded; the shift may need a reload. */ }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo liquidar el cobro.")
      setQuote(null)
    } finally { setBusy(false) }
  }

  return <div className="space-y-4">
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{notice}</p>}
    <Card><CardHeader><CardTitle>Cobros pendientes de liquidación</CardTitle>
      <CardDescription>Tarjetas, transferencias y devoluciones con cuenta bancaria de liquidación. El importe disponible es bruto y admite liquidaciones parciales.</CardDescription>
    </CardHeader><CardContent className="space-y-4">
      <form onSubmit={searchSources} className="flex flex-wrap gap-2">
        <Input className="min-w-56 flex-1" aria-label="Buscar cobro pendiente" placeholder="Registro, referencia o asiento original" maxLength={140} value={search} onChange={(event) => setSearch(event.target.value)} />
        <Button type="submit" variant="outline">Buscar</Button>
      </form>
      {!sources && !error && <Skeleton className="h-40" />}
      {sources && <>
        <div className="space-y-2">{sources.sources.map((source) => <div key={source.name} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
          <div><p className="font-medium">{source.name} · {kindLabel[source.kind] || source.kind}</p>
            <p className="text-muted-foreground">{source.method_label} · {source.business_date || source.creation} · {source.voucher || "Sin asiento"}</p>
            {source.reference && <p className="text-muted-foreground">Referencia original: {source.reference}</p>}
            <p>Pendiente <strong>{source.currency} {source.available}</strong> de {source.amount} · Liquidado {source.settled}</p>
          </div>
          <Button type="button" size="sm" variant={selected?.name === source.name ? "default" : "outline"} onClick={() => selectSource(source)}>Seleccionar</Button>
        </div>)}</div>
        {!sources.sources.length && <p className="text-sm text-muted-foreground">No hay cobros pendientes con esta búsqueda.</p>}
        <div className="flex items-center justify-between text-sm"><span>Desde {offset + (sources.sources.length ? 1 : 0)} · {sources.sources.length} registros</span>
          <div className="flex gap-2"><Button type="button" variant="outline" disabled={offset === 0} onClick={() => { setSelected(null); setQuote(null); setOffset(Math.max(0, offset - PAGE_LENGTH)) }}>Anterior</Button>
            <Button type="button" variant="outline" disabled={!sources.has_more} onClick={() => { setSelected(null); setQuote(null); setOffset(offset + PAGE_LENGTH) }}>Siguiente</Button></div></div>
      </>}
    </CardContent></Card>
    {selected && <Card><CardHeader><CardTitle>Liquidar {selected.name}</CardTitle>
      <CardDescription>{selected.direction === "Pay" ? "Salida bancaria por devolución" : "Ingreso bancario"} · {selected.currency} {selected.available} bruto pendiente. Se usará la política aceptada al registrar el cobro original.</CardDescription>
    </CardHeader><CardContent><form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      {!shift && <p className="text-sm text-amber-800 sm:col-span-2">Abra y seleccione un turno para vincular el asiento bancario.</p>}
      {shift && !canOperate && <p className="text-sm text-amber-800 sm:col-span-2">Seleccione un turno abierto propio o uno autorizado por Gerencia.</p>}
      <label className="space-y-1 text-sm">Importe bruto ({selected.currency})<Input required type="number" min="0.01" max={selected.available} step="any" value={amount} onChange={(event) => { setAmount(event.target.value); setQuote(null); pending.current = null }} /></label>
      <label className="space-y-1 text-sm">Referencia bancaria<Input required maxLength={140} value={reference} onChange={(event) => { setReference(event.target.value); setQuote(null); pending.current = null }} /></label>
      <label className="space-y-1 text-sm sm:col-span-2">Nota opcional<Input maxLength={500} value={reason} onChange={(event) => { setReason(event.target.value); setQuote(null); pending.current = null }} /></label>
      {quote && <div className="space-y-1 rounded-lg border border-primary/30 bg-secondary p-4 text-sm sm:col-span-2">
        <p><strong>{quote.direction === "Pay" ? "Salida" : "Ingreso"} bancaria {quote.currency} {quote.net}</strong> · Bruto {quote.amount}</p>
        <p>Comisión {quote.currency} {quote.fee} · Retención {quote.currency} {quote.withholding}</p>
        <p>Banco: {quote.policy.settlement_account}</p>
        {Number(quote.fee) > 0 && <p>Gasto de comisión: {quote.policy.fee_account}</p>}
        {Number(quote.withholding) > 0 && <p>Activo por retención: {quote.policy.withholding_account}</p>}
        <p>Compensación histórica {quote.base_currency} {quote.clearing_base} · Tipo de cambio actual {quote.exchange_rate}</p>
        <p className="text-muted-foreground">El asiento puede incluir una diferencia cambiaria al tipo vigente.</p>
      </div>}
      <Button disabled={busy || !shift || !canOperate || !reference.trim() || !amount} className="sm:col-span-2">{quote ? "Confirmar liquidación" : "Revisar liquidación"}</Button>
    </form></CardContent></Card>}
  </div>
}
