import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

export type AppliedRefundData = {
  currency: string
  methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean; reference_required: boolean }[]
  shifts: { name: string; cashier: string; currency: string; status: string;
    modified: string; expected: Record<string, string> }[]
}
type Note = { name: string; customer: string; invoice: string; available: string }
type Source = { credit_note: string; source: string;
  kind: "Advance" | "Guarantee Applied" | "Payment";
  customer: string; currency: string; method: string | null;
  remaining: string; available_party: string }
type Page = { notes: Note[]; sources: Source[]; offset: number; has_more: boolean }
type Quote = { amount: string; currency: string; base_currency: string;
  acceptance: string; refund?: { mode: string; invoice: string;
    allocated: string; credit_outstanding: string;
    party_amount: string; party_currency: string;
    exchange_difference: string } }
const PAGE_LENGTH = 50
const KINDS = { Advance: "Anticipo", "Guarantee Applied": "Garantía aplicada",
  Payment: "Cobro de cuenta" }

export function AppliedRefunds({ property, data, refresh, onNotice, onError }: {
  property: Property; data: AppliedRefundData; refresh: () => Promise<void>;
  onNotice: (message: string) => void; onError: (message: string) => void;
}) {
  const [notePage, setNotePage] = useState<Page | null>(null)
  const [sourcePage, setSourcePage] = useState<Page | null>(null)
  const [noteSearch, setNoteSearch] = useState("")
  const [appliedNoteSearch, setAppliedNoteSearch] = useState("")
  const [sourceSearch, setSourceSearch] = useState("")
  const [appliedSourceSearch, setAppliedSourceSearch] = useState("")
  const [credit, setCredit] = useState("")
  const [source, setSource] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [key, setKey] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setNotePage(null); setSourcePage(null); setNoteSearch("")
    setAppliedNoteSearch(""); setSourceSearch("")
    setAppliedSourceSearch(""); setCredit(""); setSource("")
    setMethod(""); setShift(""); setAmount(""); setReference("")
    setReason(""); setQuote(null); setKey(""); setBusy(true)
    call<Page>("erp_credit_refund_search", {
      property_name: property.name, page_length: String(PAGE_LENGTH),
    }, controller.signal).then(setNotePage).catch((issue: unknown) => {
      if (!controller.signal.aborted) onError(issue instanceof Error ? issue.message : "No se pudieron consultar las notas de crédito.")
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [property.name])

  const chosenCredit = (sourcePage?.notes[0]?.name === credit
    ? sourcePage.notes[0] : notePage?.notes.find((row) => row.name === credit))
  const sources = sourcePage?.sources || []
  const chosenSource = sources.find((row) => row.source === source)
  const methods = data.methods.filter((row) => row.currency === chosenSource?.currency)
  const chosenMethod = methods.find((row) => row.name === method)
  function change() { setQuote(null); setKey(""); onError("") }

  async function loadNotes(query: string, offset: number) {
    setBusy(true); onError("")
    try {
      const page = await call<Page>("erp_credit_refund_search", {
        property_name: property.name, search: query,
        offset: String(offset), page_length: String(PAGE_LENGTH),
      })
      setNotePage(page); setAppliedNoteSearch(query)
      setCredit(""); setSourcePage(null); setSource(""); setMethod("")
      setAmount(""); setQuote(null); setKey("")
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudieron buscar las notas.") }
    finally { setBusy(false) }
  }

  async function loadSources(note: string, query: string, offset: number) {
    setBusy(true); onError("")
    try {
      const page = await call<Page>("erp_credit_refund_search", {
        property_name: property.name, credit_note: note,
        source_search: query, offset: String(offset),
        page_length: String(PAGE_LENGTH),
      })
      setSourcePage(page); setAppliedSourceSearch(query)
      setSource(""); setMethod(""); setAmount("")
      setQuote(null); setKey("")
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudieron buscar los movimientos originales.") }
    finally { setBusy(false) }
  }

  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !chosenCredit || !chosenSource || !chosenMethod || !shift) return
    const payload = { kind: "Refund", credit_note: chosenCredit.name,
      source_payment: chosenSource.source, method, shift, amount,
      reference: reference.trim(), reason: reason.trim() }
    setBusy(true); onError(""); onNotice("")
    try {
      if (!quote) {
        setQuote(await call<Quote>("preview", { property_name: property.name,
          action: "payment", data: JSON.stringify(payload) }))
      } else {
        const requestKey = key || crypto.randomUUID(); setKey(requestKey)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: quote.acceptance }, requestKey)
        await refresh()
        await loadNotes(appliedNoteSearch, notePage?.offset || 0)
        setReference(""); setReason(""); setQuote(null); setKey("")
        onNotice(`Devolución ${result.payment} registrada contra la nota ${chosenCredit.name}.`)
      }
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudo devolver el importe acreditado.") }
    finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Devolver importe acreditado</CardTitle><CardDescription>Busque la nota de crédito y el anticipo, garantía aplicada o cobro de la cuenta que financió su factura. La revisión limita la salida al crédito y a la asignación original. Los cobros directos usan el formulario de devolución directa.</CardDescription></CardHeader><CardContent className="space-y-3">
    <form onSubmit={(event) => { event.preventDefault(); if (!busy) void loadNotes(noteSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar nota, factura o cliente" placeholder="Buscar nota, factura o cliente" value={noteSearch} onChange={(event) => setNoteSearch(event.target.value)} /><Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>
    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Notas: página {notePage ? Math.floor(notePage.offset / PAGE_LENGTH) + 1 : "cargando"} · {notePage?.notes.length || 0} resultado(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !notePage?.offset} onClick={() => void loadNotes(appliedNoteSearch, Math.max(0, (notePage?.offset || 0) - PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !notePage?.has_more} onClick={() => void loadNotes(appliedNoteSearch, (notePage?.offset || 0) + PAGE_LENGTH)}>Siguiente</Button></div></div>
    <label className="block space-y-1 text-sm">Nota con saldo a favor<select required value={credit} disabled={busy} onChange={(event) => { change(); const value = event.target.value; setCredit(value); setSourceSearch(""); setSourcePage(null); setSource(""); setMethod(""); setAmount(""); if (value) void loadSources(value, "", 0) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione nota</option>{(notePage?.notes || []).map((row) => <option key={row.name} value={row.name}>{row.name} · factura {row.invoice} · {row.customer} · {data.currency} {row.available}</option>)}</select></label>
    {credit && <><form onSubmit={(event) => { event.preventDefault(); if (!busy) void loadSources(credit, sourceSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar pago o referencia" placeholder="Buscar pago o referencia" value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} /><Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Movimientos: página {sourcePage ? Math.floor(sourcePage.offset / PAGE_LENGTH) + 1 : "cargando"} · {sources.length} compatible(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !sourcePage?.offset} onClick={() => void loadSources(credit, appliedSourceSearch, Math.max(0, (sourcePage?.offset || 0) - PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !sourcePage?.has_more} onClick={() => void loadSources(credit, appliedSourceSearch, (sourcePage?.offset || 0) + PAGE_LENGTH)}>Siguiente</Button></div></div>
      {sourcePage && !sources.length && <p className="text-sm text-muted-foreground">Sin movimientos compatibles en esta página. Busque por pago o avance a la siguiente página.</p>}
    </>}
    <form onSubmit={refund} className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-sm sm:col-span-2">Movimiento original<select required value={source} onChange={(event) => { change(); setSource(event.target.value); setMethod(""); setAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione origen</option>{sources.map((row) => <option key={row.source} value={row.source}>{KINDS[row.kind]} {row.source} · {row.currency} {row.remaining} · asignado {data.currency} {row.available_party}</option>)}</select></label>
      <label className="space-y-1 text-sm">Medio de salida<select required value={method} onChange={(event) => { change(); setMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
      <label className="space-y-1 text-sm">Turno<select required value={shift} onChange={(event) => { change(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
      <label className="space-y-1 text-sm">Importe {chosenSource?.currency || ""}<Input required type="number" min="0.01" step="0.01" max={chosenSource?.remaining} value={amount} onChange={(event) => { change(); setAmount(event.target.value) }} /></label>
      <label className="space-y-1 text-sm">Referencia<Input required={!!chosenMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { change(); setReference(event.target.value) }} /></label>
      <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required minLength={8} maxLength={500} value={reason} onChange={(event) => { change(); setReason(event.target.value) }} /></label>
      {quote?.refund && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Salida {quote.currency} {quote.amount} · crédito de origen {quote.refund.party_currency} {quote.refund.party_amount} · asignación disponible {quote.refund.allocated} · nota disponible {quote.refund.credit_outstanding} · diferencia cambiaria {quote.base_currency} {quote.refund.exchange_difference}</p>}
      <Button disabled={busy || !chosenSource || !chosenCredit || !methods.length} className="sm:col-span-2">{quote ? "Confirmar devolución" : "Revisar devolución"}</Button>
    </form>
  </CardContent></Card>
}
