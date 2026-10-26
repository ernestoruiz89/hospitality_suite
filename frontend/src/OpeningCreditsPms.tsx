import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"
import { ApplicationPicker, type ReversibleApplication } from "./ApplicationPicker"
import { ReceivablePicker, type OpenReceivable } from "./ReceivablePicker"
import { type SendCommand } from "./useIdempotentCommand"

type Credit = { name: string; credit_kind: string; customer: string;
  opening_source_name: string; currency: string; amount: number; available: string;
  base_amount: number; base_available: string;
  receivable_account: string; historical_document: string | null }
type Application = { name: string; opening_credit: string; receivable: string;
  remaining: string }
type Data = { opening_credits: { credits: Credit[]; applications: Application[] };
  receivables: { name: string; party: string; reference: string;
    currency: string; outstanding: string }[];
  customers: { name: string; party_name: string }[];
  refund_methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean }[];
  refund_shifts: { name: string; opened_at: string }[] }
type ApplyQuote = { acceptance: string; amount: string; debit: string; credit: string;
  journal_required: boolean; available_after: string; outstanding_after: string;
  settlement_currency?: string | null; source_base_amount?: string;
  target_base_amount?: string; exchange_variance_base?: string }
type RefundQuote = { acceptance: string; amount: string; currency: string;
  base_amount: string; cash_account: string; receivable_account: string;
  available_after: string; settlement_currency?: string | null;
  settled_amount?: string; released_base_amount?: string;
  exchange_variance_base?: string; base_available_after?: string }

export function OpeningCreditsPms({ property, data, refresh, send, canApprove, mode }: {
  property: Property; data: Data; refresh: () => Promise<void>; send: SendCommand; canApprove: boolean;
  mode: "apply" | "refund" | "reverse"
}) {
  const [credit, setCredit] = useState("")
  const [selectedReceivable, setSelectedReceivable] = useState<OpenReceivable | null>(null)
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [applyQuote, setApplyQuote] = useState<ApplyQuote | null>(null)
  const [refundCredit, setRefundCredit] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [refundAmount, setRefundAmount] = useState("")
  const [refundSettled, setRefundSettled] = useState("")
  const [reference, setReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundQuote, setRefundQuote] = useState<RefundQuote | null>(null)
  const [reversal, setReversal] = useState<ReversibleApplication | null>(null)
  const [reversalAmount, setReversalAmount] = useState("")
  const [reversalReason, setReversalReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const invalidateApply = () => setApplyQuote(null)
  const invalidateRefund = () => setRefundQuote(null)
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el saldo.`) }
  }
  const selected = data.opening_credits.credits.find((item) => item.name === credit)
  const selectedRefund = data.opening_credits.credits.find((item) => item.name === refundCredit)
  const selectedMethod = data.refund_methods.find((item) => item.name === method)
  const customerName = (id: string) => data.customers.find((item) => item.name === id)?.party_name || id

  async function applyCredit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !selectedReceivable) return
    setBusy(true); setError(""); setNotice("")
    const request = { credit, receivable: selectedReceivable.name,
      amount, reason: reason.trim() }
    try {
      if (!applyQuote) {
        setApplyQuote(await call<ApplyQuote>("pms_opening_credit_apply_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_apply_opening_credit", { ...request, acceptance: applyQuote.acceptance })
        setAmount(""); setReason(""); setSelectedReceivable(null); invalidateApply()
        await refreshAfter("Crédito inicial aplicado a la cuenta por cobrar.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aplicar el crédito.") }
    finally { setBusy(false) }
  }

  async function submitRefund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const request = { credit: refundCredit, method,
      shift: selectedMethod?.is_cash ? shift : null, amount: refundAmount,
      ...(selectedRefund && selectedRefund.currency !== property.currency ? {
        settled_amount: refundSettled || undefined } : {}),
      reference: reference.trim(), reason: refundReason.trim() }
    try {
      if (!refundQuote) {
        setRefundQuote(await call<RefundQuote>("pms_opening_credit_refund_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_refund_opening_credit", { ...request, acceptance: refundQuote.acceptance })
        setRefundAmount(""); setRefundSettled("")
        setReference(""); setRefundReason("")
        invalidateRefund()
        await refreshAfter("Devolución del crédito contabilizada.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el crédito.") }
    finally { setBusy(false) }
  }

  async function unapplyCredit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !reversal) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_unapply_opening_credit",
        { allocation: reversal.name, amount: reversalAmount,
          reason: reversalReason.trim() })
      setReversal(null); setReversalAmount(""); setReversalReason("")
      await refreshAfter("Aplicación del crédito revertida.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revertir la aplicación.") }
    finally { setBusy(false) }
  }

  if (!data.opening_credits.credits.length) return <Card><CardHeader><CardTitle>Créditos y anticipos de apertura</CardTitle></CardHeader><CardContent className="text-sm text-muted-foreground">No hay créditos de apertura trasladados de ERPNext.</CardContent></Card>
  if (mode !== "apply" && !canApprove) return null
  return <Card><CardHeader><CardTitle>{mode === "apply" ? "Aplicar crédito de apertura" : mode === "refund" ? "Devolver crédito de apertura" : "Revertir crédito aplicado"}</CardTitle>
    <CardDescription>Saldos trasladados de ERPNext. Aplicarlos no registra una venta ni un cobro nuevo; las devoluciones sí salen de Caja o banco.</CardDescription>
  </CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <div className="space-y-2">{data.opening_credits.credits.map((item) => <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 text-sm"><span><strong>{item.opening_source_name}</strong> · {item.credit_kind === "Credit Note" ? "Nota de crédito" : "Anticipo"} · {customerName(item.customer)}{item.historical_document && <a className="ml-2 text-primary underline" target="_blank" rel="noopener noreferrer" href={`/api/method/hospitality_suite.api.historical_fiscal_pdf?document=${encodeURIComponent(item.historical_document)}`}>Imprimir copia fiscal</a>}</span><span>Disponible {item.currency} {item.available} / {item.amount}{item.currency !== property.currency && <small className="block text-muted-foreground">Valor base {property.currency} {item.base_available} / {item.base_amount}</small>}</span></div>)}</div>
    <div className="max-w-2xl">
      {mode === "apply" && <form onSubmit={applyCredit} className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">Aplicar a una cuenta</h3>
        <select required value={credit} onChange={(event) => { setCredit(event.target.value); setSelectedReceivable(null); invalidateApply() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Crédito disponible</option>{data.opening_credits.credits.filter((item) => Number(item.available) > 0).map((item) => <option key={item.name} value={item.name}>{item.opening_source_name} · {customerName(item.customer)} · {item.currency} {item.available}</option>)}</select>
        <ReceivablePicker property={property} party={selected?.customer}
          currency={selected?.currency} enabled={!!selected} label="Cuenta por cobrar"
          selected={selectedReceivable} refreshToken={data}
          onSelect={(item) => { setSelectedReceivable(item); invalidateApply() }} />
        <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${selected?.currency || property.currency}`} value={amount} onChange={(event) => { setAmount(event.target.value); invalidateApply() }} />
        <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { setReason(event.target.value); invalidateApply() }} />
        {applyQuote && <p className="rounded-md bg-secondary p-3 text-sm">{applyQuote.journal_required ? `Débito ${applyQuote.debit} · Crédito ${applyQuote.credit}. ` : "Aplicación dentro de la misma cuenta. "}Disponible después: {selected?.currency || property.currency} {applyQuote.available_after}. Cuenta pendiente: {selected?.currency || property.currency} {applyQuote.outstanding_after}.{applyQuote.settlement_currency && <span className="block">Valor base del crédito {property.currency} {applyQuote.source_base_amount} · Cartera liberada {property.currency} {applyQuote.target_base_amount} · Cambio {property.currency} {applyQuote.exchange_variance_base}</span>}</p>}
        <Button disabled={busy || !credit || !selectedReceivable}>{applyQuote ? "Confirmar aplicación" : "Revisar aplicación"}</Button>
      </form>}
      {mode === "refund" && canApprove && <form onSubmit={submitRefund} className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">Devolver crédito</h3>
        <select required value={refundCredit} onChange={(event) => { setRefundCredit(event.target.value); setRefundSettled(""); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Crédito disponible</option>{data.opening_credits.credits.filter((item) => Number(item.available) > 0).map((item) => <option key={item.name} value={item.name}>{item.opening_source_name} · {item.currency} {item.available}</option>)}</select>
        <select required value={method} onChange={(event) => { setMethod(event.target.value); setShift(""); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Medio de devolución</option>{data.refund_methods.map((item) => <option key={item.name} value={item.name}>{item.mode_of_payment} · {item.currency}</option>)}</select>
        {selectedMethod?.is_cash && <select required value={shift} onChange={(event) => { setShift(event.target.value); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Turno abierto propio</option>{data.refund_shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>}
        <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${selectedMethod?.currency || property.currency}`} value={refundAmount} onChange={(event) => { setRefundAmount(event.target.value); invalidateRefund() }} />
        {selectedRefund && selectedRefund.currency !== property.currency && selectedMethod?.currency !== selectedRefund.currency && <Input required type="number" min="0.01" step="0.01" max={selectedRefund.available} placeholder={`Principal devuelto ${selectedRefund.currency}`} value={refundSettled} onChange={(event) => { setRefundSettled(event.target.value); invalidateRefund() }} />}
        <Input required maxLength={140} placeholder="Referencia de devolución" value={reference} onChange={(event) => { setReference(event.target.value); invalidateRefund() }} />
        <Input required maxLength={500} placeholder="Motivo" value={refundReason} onChange={(event) => { setRefundReason(event.target.value); invalidateRefund() }} />
        {refundQuote && <p className="rounded-md bg-secondary p-3 text-sm">Débito cartera {property.currency} {refundQuote.released_base_amount || refundQuote.base_amount} · Crédito Caja/banco {property.currency} {refundQuote.base_amount}. Disponible después: {selectedRefund?.currency || property.currency} {refundQuote.available_after}.{refundQuote.settlement_currency && <span className="block">Principal devuelto {refundQuote.settlement_currency} {refundQuote.settled_amount} · Cambio {property.currency} {refundQuote.exchange_variance_base} · Valor base restante {property.currency} {refundQuote.base_available_after}</span>}</p>}
        <Button disabled={busy || !refundCredit || !method}>{refundQuote ? "Confirmar devolución" : "Revisar devolución"}</Button>
      </form>}
    </div>
    {mode === "reverse" && canApprove && <form onSubmit={unapplyCredit} className="grid max-w-2xl gap-3 rounded-lg border p-4 sm:grid-cols-3"><h3 className="font-medium sm:col-span-3">Revertir aplicación</h3>
      <ApplicationPicker property={property} kind="Opening Credit" selected={reversal}
        refreshToken={data} onSelect={(row) => { setReversal(row); setReversalAmount("") }} />
      <Input required type="number" min="0.01" step="0.01" max={reversal?.remaining} placeholder={`Importe ${reversal?.currency || property.currency}`} value={reversalAmount} onChange={(event) => setReversalAmount(event.target.value)} />
      <Input required maxLength={500} placeholder="Motivo" value={reversalReason} onChange={(event) => setReversalReason(event.target.value)} />
      <Button disabled={busy || !reversal}>Revertir aplicación</Button>
    </form>}
  </CardContent></Card>
}
