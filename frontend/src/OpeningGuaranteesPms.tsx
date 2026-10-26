import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"
import { type SendCommand } from "./useIdempotentCommand"

type Guarantee = { name: string; customer: string; opening_source_name: string;
  source_booking: string | null; source_stay: string | null; source_folio: string | null;
  amount: number; available: string; liability_account: string }
type Data = { opening_guarantees: Guarantee[];
  opening_guarantee_applications: { name: string; opening_guarantee: string;
    receivable: string; remaining: number }[];
  receivables: { name: string; party: string; folio: string | null;
    folio_stay: string | null; booking: string | null; reference: string;
    outstanding: string; receivable_account: string }[];
  customers: { name: string; party_name: string }[];
  refund_methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean }[];
  refund_shifts: { name: string; opened_at: string }[] }
type Quote = { acceptance: string; base_amount: string; currency: string;
  liability_account: string; cash_account: string; available_after: string }
type ApplyQuote = { acceptance: string; amount: string; currency: string;
  debit: string; credit: string; available_after: string;
  outstanding_after: string }

export function OpeningGuaranteesPms({ property, data, refresh, send, canApprove, mode }: {
  property: Property; data: Data; refresh: () => Promise<void>; send: SendCommand; canApprove: boolean;
  mode: "apply" | "refund" | "reverse"
}) {
  const [guarantee, setGuarantee] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [applyGuarantee, setApplyGuarantee] = useState("")
  const [applyReceivable, setApplyReceivable] = useState("")
  const [applyAmount, setApplyAmount] = useState("")
  const [applyReason, setApplyReason] = useState("")
  const [applyQuote, setApplyQuote] = useState<ApplyQuote | null>(null)
  const [reverseAllocation, setReverseAllocation] = useState("")
  const [reverseAmount, setReverseAmount] = useState("")
  const [reverseReason, setReverseReason] = useState("")
  const invalidate = () => setQuote(null)
  const invalidateApply = () => setApplyQuote(null)
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el saldo.`) }
  }
  const selectedMethod = data.refund_methods.find((item) => item.name === method)
  const selectedGuarantee = data.opening_guarantees.find((item) => item.name === applyGuarantee)
  const matchingReceivables = selectedGuarantee ? data.receivables.filter((item) =>
    item.party === selectedGuarantee.customer && Number(item.outstanding) > 0 &&
    !!item.folio && (selectedGuarantee.source_folio
      ? item.folio === selectedGuarantee.source_folio
      : selectedGuarantee.source_stay
        ? item.folio_stay === selectedGuarantee.source_stay
        : item.booking === selectedGuarantee.source_booking)) : []
  const selectedApplication = data.opening_guarantee_applications.find(
    (item) => item.name === reverseAllocation)
  const customerName = (id: string) => data.customers.find((item) => item.name === id)?.party_name || id

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const request = { guarantee, method, shift: selectedMethod?.is_cash ? shift : null,
      amount, reference: reference.trim(), reason: reason.trim() }
    try {
      if (!quote) {
        setQuote(await call<Quote>("pms_opening_guarantee_refund_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_refund_opening_guarantee", { ...request, acceptance: quote.acceptance })
        setAmount(""); setReference(""); setReason("")
        invalidate()
        await refreshAfter("Devolución de garantía contabilizada.")
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo devolver la garantía.")
    } finally { setBusy(false) }
  }

  async function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const request = { guarantee: applyGuarantee, receivable: applyReceivable,
      amount: applyAmount, reason: applyReason.trim() }
    try {
      if (!applyQuote) {
        setApplyQuote(await call<ApplyQuote>("pms_opening_guarantee_apply_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_apply_opening_guarantee", { ...request, acceptance: applyQuote.acceptance })
        setApplyAmount(""); setApplyReason("")
        invalidateApply()
        await refreshAfter("Garantía aplicada a la cuenta y contabilizada.")
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo aplicar la garantía.")
    } finally { setBusy(false) }
  }

  async function unapply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_unapply_opening_guarantee",
        { allocation: reverseAllocation, amount: reverseAmount,
          reason: reverseReason.trim() })
      setReverseAllocation(""); setReverseAmount("")
      setReverseReason("")
      await refreshAfter("Aplicación revertida con un asiento nuevo.")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo revertir la aplicación.")
    } finally { setBusy(false) }
  }

  if (!data.opening_guarantees.length) return <Card><CardHeader><CardTitle>Garantías de apertura</CardTitle></CardHeader><CardContent className="text-sm text-muted-foreground">No hay garantías de apertura trasladadas de ERPNext.</CardContent></Card>
  if (mode !== "apply" && !canApprove) return null
  return <div className="space-y-5"><Card><CardHeader><CardTitle>Garantías de apertura</CardTitle>
    <CardDescription>Obligaciones trasladadas de ERPNext. Pueden aplicarse a la cuenta de estancia original o devolverse; el cobro original no se repite.</CardDescription>
  </CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <div className="space-y-2">{data.opening_guarantees.map((item) =>
      <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 text-sm">
        <span><strong>{item.opening_source_name}</strong> · {customerName(item.customer)} · {item.source_folio || item.source_booking}</span>
        <span>Disponible {property.currency} {item.available} / {item.amount}</span>
      </div>)}</div>
  </CardContent></Card>
    {mode === "apply" && canApprove && <Card><CardHeader><CardTitle>Aplicar garantía de apertura</CardTitle>
      <CardDescription>Reduce un cargo pendiente de la misma cuenta de estancia y cliente, sin mover efectivo.</CardDescription></CardHeader><CardContent><form onSubmit={apply} className="grid gap-3 sm:grid-cols-2">
      <select required value={applyGuarantee} onChange={(event) => { setApplyGuarantee(event.target.value); setApplyReceivable(""); invalidateApply() }} className="h-9 rounded-md border bg-white px-2 text-sm sm:col-span-2">
        <option value="">Garantía disponible</option>{data.opening_guarantees.filter((item) => Number(item.available) > 0).map((item) =>
          <option key={item.name} value={item.name}>{item.opening_source_name} · {customerName(item.customer)} · Disponible {property.currency} {item.available}</option>)}
      </select>
      <select required value={applyReceivable} onChange={(event) => { setApplyReceivable(event.target.value); invalidateApply() }} className="h-9 rounded-md border bg-white px-2 text-sm sm:col-span-2">
        <option value="">Cargo pendiente de la cuenta</option>{matchingReceivables.map((item) =>
          <option key={item.name} value={item.name}>{item.reference} · Pendiente {property.currency} {item.outstanding}</option>)}
      </select>
      <Input required type="number" min="0.01" step="0.01" placeholder={`Aplicar ${property.currency}`} value={applyAmount} onChange={(event) => { setApplyAmount(event.target.value); invalidateApply() }} />
      <Input required maxLength={500} placeholder="Motivo" value={applyReason} onChange={(event) => { setApplyReason(event.target.value); invalidateApply() }} />
      {applyQuote && <p className="rounded-md bg-secondary p-3 text-sm sm:col-span-2">Débito {applyQuote.debit} · Crédito {applyQuote.credit} · {applyQuote.currency} {applyQuote.amount}. Garantía disponible después: {applyQuote.available_after}; cuenta pendiente: {applyQuote.outstanding_after}.</p>}
      <Button disabled={busy || !applyReceivable}>{applyQuote ? "Confirmar aplicación" : "Revisar aplicación"}</Button>
    </form></CardContent></Card>}
    {mode === "refund" && canApprove && <Card><CardHeader><CardTitle>Devolver garantía de apertura</CardTitle>
      <CardDescription>Entrega en Caja o banco el saldo que no se haya aplicado.</CardDescription></CardHeader><CardContent><form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <h3 className="font-medium sm:col-span-2">Devolver garantía</h3>
      <select required value={guarantee} onChange={(event) => { setGuarantee(event.target.value); invalidate() }} className="h-9 rounded-md border bg-white px-2 text-sm sm:col-span-2">
        <option value="">Garantía disponible</option>{data.opening_guarantees.filter((item) => Number(item.available) > 0).map((item) =>
          <option key={item.name} value={item.name}>{item.opening_source_name} · {customerName(item.customer)} · {property.currency} {item.available}</option>)}
      </select>
      <select required value={method} onChange={(event) => { setMethod(event.target.value); setShift(""); invalidate() }} className="h-9 rounded-md border bg-white px-2 text-sm">
        <option value="">Medio de devolución</option>{data.refund_methods.map((item) =>
          <option key={item.name} value={item.name}>{item.mode_of_payment} · {item.currency}</option>)}
      </select>
      {selectedMethod?.is_cash && <select required value={shift} onChange={(event) => { setShift(event.target.value); invalidate() }} className="h-9 rounded-md border bg-white px-2 text-sm">
        <option value="">Turno abierto propio</option>{data.refund_shifts.map((item) =>
          <option key={item.name} value={item.name}>{item.name}</option>)}
      </select>}
      <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${selectedMethod?.currency || property.currency}`} value={amount} onChange={(event) => { setAmount(event.target.value); invalidate() }} />
      <Input required maxLength={140} placeholder="Referencia de devolución" value={reference} onChange={(event) => { setReference(event.target.value); invalidate() }} />
      <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { setReason(event.target.value); invalidate() }} className="sm:col-span-2" />
      {quote && <p className="rounded-md bg-secondary p-3 text-sm sm:col-span-2">Débito {quote.liability_account} · Crédito {quote.cash_account} · Importe base {property.currency} {quote.base_amount}. Disponible después: {property.currency} {quote.available_after}.</p>}
      <Button disabled={busy || !guarantee || !method}>{quote ? "Confirmar devolución" : "Revisar devolución"}</Button>
    </form></CardContent></Card>}
    {mode === "reverse" && canApprove && data.opening_guarantee_applications.length > 0 && <Card><CardHeader><CardTitle>Revertir aplicación</CardTitle>
      <CardDescription>Restituye saldo a la garantía y a la cuenta por cobrar.</CardDescription></CardHeader><CardContent><form onSubmit={unapply} className="grid gap-3 sm:grid-cols-2">
      <select required value={reverseAllocation} onChange={(event) => { setReverseAllocation(event.target.value); setReverseAmount("") }} className="h-9 rounded-md border bg-white px-2 text-sm sm:col-span-2">
        <option value="">Aplicación con saldo</option>{data.opening_guarantee_applications.map((item) =>
          <option key={item.name} value={item.name}>{data.receivables.find((row) => row.name === item.receivable)?.reference || item.receivable} · {property.currency} {item.remaining}</option>)}
      </select>
      <Input required type="number" min="0.01" step="0.01" max={selectedApplication?.remaining} placeholder={`Revertir ${property.currency}`} value={reverseAmount} onChange={(event) => setReverseAmount(event.target.value)} />
      <Input required maxLength={500} placeholder="Motivo" value={reverseReason} onChange={(event) => setReverseReason(event.target.value)} />
      <Button disabled={busy || !reverseAllocation}>Revertir y contabilizar</Button>
    </form></CardContent></Card>}
    {mode === "reverse" && !data.opening_guarantee_applications.length && <p className="text-sm text-muted-foreground">No hay aplicaciones de garantías de apertura para revertir.</p>}
  </div>
}
