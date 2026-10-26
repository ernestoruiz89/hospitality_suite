import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

export type AdvanceRefundData = {
  currency: string
  advance_page: { search: string; offset: number; has_more: boolean }
  advance_refunds: { name: string; customer: string; reference: string;
    currency: string; method: string; remaining: string; unallocated: string }[]
  methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean; reference_required: boolean }[]
  shifts: { name: string; cashier: string; currency: string; status: string;
    modified: string; expected: Record<string, string> }[]
}
type Quote = { amount: string; currency: string; base_currency: string;
  acceptance: string; refund?: { mode: string; remaining: string;
    unallocated: string; party_amount: string; party_currency: string;
    exchange_difference: string } }

export function AdvanceRefunds({ property, data, refresh, onNotice, onError }: {
  property: Property; data: AdvanceRefundData; refresh: () => Promise<void>;
  onNotice: (message: string) => void; onError: (message: string) => void;
}) {
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
    setSource(""); setMethod(""); setShift(""); setAmount("")
    setReference(""); setReason(""); setQuote(null); setKey("")
  }, [property.name])
  useEffect(() => {
    setSource(""); setMethod(""); setAmount("")
    setQuote(null); setKey("")
  }, [data.advance_page.search, data.advance_page.offset])
  const chosenSource = data.advance_refunds.find((row) => row.name === source)
  const methods = data.methods.filter((row) => row.currency === chosenSource?.currency)
  const chosenMethod = methods.find((row) => row.name === method)
  function change() { setQuote(null); setKey(""); onError("") }

  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !chosenSource || !chosenMethod || !shift) return
    const payload = { kind: "Refund", source_payment: chosenSource.name,
      method, shift, amount, reference: reference.trim(), reason: reason.trim() }
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
        setSource(""); setMethod(""); setAmount(""); setReference("")
        setReason(""); setQuote(null); setKey("")
        onNotice(`Anticipo devuelto en ${result.payment}.`)
      }
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudo devolver el anticipo.") }
    finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Devolver anticipo sin aplicar</CardTitle><CardDescription>Gerencia devuelve dinero aún disponible del anticipo original. Revise el importe y el tipo de cambio antes de confirmar; un anticipo ya aplicado requiere una nota de crédito de su factura.</CardDescription></CardHeader><CardContent><form onSubmit={refund} className="grid gap-3 sm:grid-cols-2">
    <label className="space-y-1 text-sm sm:col-span-2">Anticipo<select required value={source} onChange={(event) => { change(); setSource(event.target.value); setMethod(""); setAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione anticipo</option>{data.advance_refunds.map((row) => <option key={row.name} value={row.name}>{row.reference} · {row.customer} · {row.currency} {row.remaining}</option>)}</select></label>
    {chosenSource && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Saldo nominal {chosenSource.currency} {chosenSource.remaining} · sin aplicar {data.currency} {chosenSource.unallocated}</p>}
    <label className="space-y-1 text-sm">Medio de salida<select required value={method} onChange={(event) => { change(); setMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
    <label className="space-y-1 text-sm">Turno<select required value={shift} onChange={(event) => { change(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
    <label className="space-y-1 text-sm">Importe {chosenSource?.currency || ""}<Input required type="number" min="0.01" step="0.01" max={chosenSource?.remaining} value={amount} onChange={(event) => { change(); setAmount(event.target.value) }} /></label>
    <label className="space-y-1 text-sm">Referencia<Input required={!!chosenMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { change(); setReference(event.target.value) }} /></label>
    <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required minLength={8} maxLength={500} value={reason} onChange={(event) => { change(); setReason(event.target.value) }} /></label>
    {quote?.refund && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Salida {quote.currency} {quote.amount} · crédito liberado {quote.refund.party_currency} {quote.refund.party_amount} · diferencia cambiaria {quote.base_currency} {quote.refund.exchange_difference} · sin aplicar antes {quote.refund.unallocated}</p>}
    <Button disabled={busy || !chosenSource || !methods.length} className="sm:col-span-2">{quote ? "Confirmar devolución" : "Revisar devolución"}</Button>
  </form></CardContent></Card>
}
