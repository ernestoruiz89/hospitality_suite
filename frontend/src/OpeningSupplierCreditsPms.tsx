import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"
import { type PurchaseSection } from "./PurchaseSections"
import { type SendCommand } from "./useIdempotentCommand"

type Credit = { name: string; supplier: string; opening_source_name: string;
  currency: string; amount: number; base_amount: number;
  available: string; base_available: string }
type Application = { name: string; opening_credit: string; target_type: string;
  opening_payable: string | null; purchase: string | null;
  currency: string; remaining: string }
type Data = { currency: string;
  suppliers: { name: string; party_name: string }[];
  opening_payables: { name: string; supplier: string; opening_source_name: string;
    currency: string; outstanding: string }[];
  purchases: { name: string; supplier: string; supplier_reference: string;
    outstanding: string }[];
  opening_supplier_credits: { credits: Credit[]; applications: Application[] };
  methods: { name: string; mode_of_payment: string; currency: string; is_cash: boolean }[];
  shifts: { name: string }[] }
type ApplyQuote = { acceptance: string; journal_required: boolean;
  source_account: string; target_account: string;
  available_after: string; outstanding_after: string;
  source_base_amount?: string; target_base_amount?: string;
  exchange_variance_base?: string; exchange_variance_account?: string }
type RefundQuote = { acceptance: string; amount: string; currency: string;
  base_amount: string; cash_account: string; payable_account: string;
  available_after: string; settled_amount?: string;
  released_base_amount?: string; exchange_variance_base?: string }

export function OpeningSupplierCreditsPms({ property, data, refresh, send, section, canApprove }: {
  property: Property; data: Data; refresh: () => Promise<void>; send: SendCommand;
  section: PurchaseSection; canApprove: boolean
}) {
  const [credit, setCredit] = useState("")
  const [target, setTarget] = useState("")
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [applyQuote, setApplyQuote] = useState<ApplyQuote | null>(null)
  const [refundCredit, setRefundCredit] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [refundAmount, setRefundAmount] = useState("")
  const [settledAmount, setSettledAmount] = useState("")
  const [reference, setReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundQuote, setRefundQuote] = useState<RefundQuote | null>(null)
  const [reversal, setReversal] = useState("")
  const [reversalAmount, setReversalAmount] = useState("")
  const [reversalReason, setReversalReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  useEffect(() => { setError(""); setNotice("") }, [section])
  const invalidateApply = () => setApplyQuote(null)
  const invalidateRefund = () => setRefundQuote(null)
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el saldo.`) }
  }
  const selectedCredit = data.opening_supplier_credits.credits.find((item) => item.name === credit)
  const selectedRefundCredit = data.opening_supplier_credits.credits.find((item) => item.name === refundCredit)
  const selectedMethod = data.methods.find((item) => item.name === method)
  const supplierName = (id: string) => data.suppliers.find((item) => item.name === id)?.party_name || id
  const creditName = (id: string) => data.opening_supplier_credits.credits.find((item) => item.name === id)?.opening_source_name || id
  const selectedTarget = target.startsWith("opening:") ? {
    target_type: "Opening Payable", target: target.slice(8) } : {
    target_type: "Purchase", target }

  async function applyCredit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const request = { credit, ...selectedTarget, amount, reason: reason.trim() }
    try {
      if (!applyQuote) {
        setApplyQuote(await call<ApplyQuote>("pms_opening_supplier_credit_apply_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_apply_opening_supplier_credit", { ...request, acceptance: applyQuote.acceptance })
        setCredit(""); setTarget(""); setAmount(""); setReason(""); invalidateApply()
        await refreshAfter("Crédito aplicado a la deuda del proveedor.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aplicar el crédito.") }
    finally { setBusy(false) }
  }

  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const request = { credit: refundCredit, method,
      shift: selectedMethod?.is_cash ? shift : null, amount: refundAmount,
      ...(selectedRefundCredit && selectedRefundCredit.currency !== property.currency &&
        selectedMethod?.currency !== selectedRefundCredit?.currency ?
        { settled_amount: settledAmount } : {}),
      reference: reference.trim(), reason: refundReason.trim() }
    try {
      if (!refundQuote) {
        setRefundQuote(await call<RefundQuote>("pms_opening_supplier_credit_refund_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
      } else {
        await send("pms_refund_opening_supplier_credit", { ...request, acceptance: refundQuote.acceptance })
        setRefundCredit(""); setRefundAmount(""); setSettledAmount("")
        setReference(""); setRefundReason("")
        invalidateRefund()
        await refreshAfter("Reintegro contabilizado desde el proveedor.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el reintegro.") }
    finally { setBusy(false) }
  }

  async function unapply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_unapply_opening_supplier_credit",
        { allocation: reversal, amount: reversalAmount,
          reason: reversalReason.trim() })
      setReversal(""); setReversalAmount(""); setReversalReason("")
      await refreshAfter("Aplicación del crédito revertida.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revertir la aplicación.") }
    finally { setBusy(false) }
  }

  if (!data.opening_supplier_credits.credits.length) return <Card><CardHeader>
    <CardTitle>Créditos de proveedores de apertura</CardTitle>
    <CardDescription>No hay créditos de proveedor trasladados a este establecimiento.</CardDescription>
  </CardHeader></Card>
  return <Card><CardHeader><CardTitle>Créditos de proveedores de apertura</CardTitle>
    <CardDescription>{section === "credits" ? "Saldo disponible de cada crédito trasladado de ERPNext." : section === "credit-apply" ? "Compensar una deuda no repite una compra ni mueve inventario." : section === "credit-refund" ? "El reintegro ingresa a Caja o banco." : "La reversión restaura el crédito y la deuda por el importe corregido."}</CardDescription>
  </CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {section === "credits" && <div className="space-y-2">{data.opening_supplier_credits.credits.map((item) =>
      <div key={item.name} className="flex flex-wrap justify-between gap-2 border-b py-2 text-sm"><span><strong>{item.opening_source_name}</strong> · {supplierName(item.supplier)}</span><span>Disponible {item.currency} {item.available} / {item.amount}{item.currency !== property.currency && <> · Valor base {property.currency} {item.base_available} / {item.base_amount}</>}</span></div>)}</div>}
    {section === "credit-apply" &&
      <form onSubmit={applyCredit} className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">Aplicar a una deuda</h3>
        <select required value={credit} onChange={(event) => { setCredit(event.target.value); setTarget(""); invalidateApply() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Crédito disponible</option>{data.opening_supplier_credits.credits.filter((item) => Number(item.available) > 0).map((item) => <option key={item.name} value={item.name}>{item.opening_source_name} · {supplierName(item.supplier)} · {item.currency} {item.available}</option>)}</select>
        <select required value={target} onChange={(event) => { setTarget(event.target.value); invalidateApply() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Deuda del mismo proveedor</option>{data.opening_payables.filter((item) => item.supplier === selectedCredit?.supplier && item.currency === selectedCredit?.currency && Number(item.outstanding) > 0).map((item) => <option key={item.name} value={`opening:${item.name}`}>{item.opening_source_name} · Apertura · {item.currency} {item.outstanding}</option>)}{selectedCredit?.currency === property.currency && data.purchases.filter((item) => item.supplier === selectedCredit?.supplier && Number(item.outstanding) > 0).map((item) => <option key={item.name} value={item.name}>{item.supplier_reference} · Compra PMS · {property.currency} {item.outstanding}</option>)}</select>
        <Input required type="number" min="0.01" step="0.01" max={selectedCredit?.available} placeholder={`Importe ${selectedCredit?.currency || property.currency}`} value={amount} onChange={(event) => { setAmount(event.target.value); invalidateApply() }} />
        <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { setReason(event.target.value); invalidateApply() }} />
        {applyQuote && <p className="rounded-md bg-secondary p-3 text-sm">{applyQuote.journal_required ? `Débito ${applyQuote.target_account} · Crédito ${applyQuote.source_account}. ` : "Compensación dentro de la misma cuenta. "}Crédito restante {selectedCredit?.currency || property.currency} {applyQuote.available_after} · Deuda restante {selectedCredit?.currency || property.currency} {applyQuote.outstanding_after}.{applyQuote.source_base_amount && <> Valor base del crédito {property.currency} {applyQuote.source_base_amount} · Deuda liberada {property.currency} {applyQuote.target_base_amount} · Diferencia {property.currency} {applyQuote.exchange_variance_base}.</>}</p>}
        <Button disabled={busy || !credit || !target}>{applyQuote ? "Confirmar aplicación" : "Revisar aplicación"}</Button>
      </form>}
    {section === "credit-refund" &&
      <form onSubmit={refund} className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">Registrar reintegro del proveedor</h3>
        <select required value={refundCredit} onChange={(event) => { setRefundCredit(event.target.value); setSettledAmount(""); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Crédito disponible</option>{data.opening_supplier_credits.credits.filter((item) => Number(item.available) > 0).map((item) => <option key={item.name} value={item.name}>{item.opening_source_name} · {item.currency} {item.available}</option>)}</select>
        <select required value={method} onChange={(event) => { setMethod(event.target.value); setShift(""); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Medio de cobro</option>{data.methods.map((item) => <option key={item.name} value={item.name}>{item.mode_of_payment} · {item.currency}</option>)}</select>
        {selectedMethod?.is_cash && <select required value={shift} onChange={(event) => { setShift(event.target.value); invalidateRefund() }} className="h-9 w-full rounded-md border bg-white px-2 text-sm"><option value="">Turno abierto propio</option>{data.shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>}
        <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${selectedMethod?.currency || property.currency}`} value={refundAmount} onChange={(event) => { setRefundAmount(event.target.value); invalidateRefund() }} />
        {selectedRefundCredit && selectedRefundCredit.currency !== property.currency && selectedMethod?.currency !== selectedRefundCredit.currency && <Input required type="number" min="0.01" step="0.01" max={selectedRefundCredit.available} placeholder={`Crédito liquidado ${selectedRefundCredit.currency}`} value={settledAmount} onChange={(event) => { setSettledAmount(event.target.value); invalidateRefund() }} />}
        <Input required maxLength={140} placeholder="Referencia del reintegro" value={reference} onChange={(event) => { setReference(event.target.value); invalidateRefund() }} />
        <Input required maxLength={500} placeholder="Motivo" value={refundReason} onChange={(event) => { setRefundReason(event.target.value); invalidateRefund() }} />
        {refundQuote && <p className="rounded-md bg-secondary p-3 text-sm">Débito Caja/banco {property.currency} {refundQuote.base_amount} · Crédito proveedores {property.currency} {refundQuote.released_base_amount || refundQuote.base_amount}. Disponible después: {selectedRefundCredit?.currency || property.currency} {refundQuote.available_after}.{refundQuote.settled_amount && <> Principal reintegrado {selectedRefundCredit?.currency} {refundQuote.settled_amount} · Diferencia {property.currency} {refundQuote.exchange_variance_base}.</>}</p>}
        <Button disabled={busy || !refundCredit || !method}>{refundQuote ? "Confirmar reintegro" : "Revisar reintegro"}</Button>
      </form>}
    {section === "credit-unapply" && canApprove && (data.opening_supplier_credits.applications.length ? <form onSubmit={unapply} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-3"><h3 className="font-medium sm:col-span-3">Revertir aplicación</h3>
      <select required value={reversal} onChange={(event) => { setReversal(event.target.value); setReversalAmount("") }} className="h-9 rounded-md border bg-white px-2 text-sm sm:col-span-3"><option value="">Aplicación vigente</option>{data.opening_supplier_credits.applications.map((item) => <option key={item.name} value={item.name}>{creditName(item.opening_credit)} · {item.target_type === "Opening Payable" ? data.opening_payables.find((row) => row.name === item.opening_payable)?.opening_source_name : data.purchases.find((row) => row.name === item.purchase)?.supplier_reference} · Pendiente de reversión {item.currency} {item.remaining}</option>)}</select>
      <Input required type="number" min="0.01" step="0.01" max={data.opening_supplier_credits.applications.find((item) => item.name === reversal)?.remaining} placeholder={`Importe ${data.opening_supplier_credits.applications.find((item) => item.name === reversal)?.currency || property.currency}`} value={reversalAmount} onChange={(event) => setReversalAmount(event.target.value)} />
      <Input required maxLength={500} placeholder="Motivo" value={reversalReason} onChange={(event) => setReversalReason(event.target.value)} />
      <Button disabled={busy || !reversal}>Revertir aplicación</Button>
    </form> : <p className="text-sm text-muted-foreground">No hay aplicaciones vigentes para revertir.</p>)}
  </CardContent></Card>
}
