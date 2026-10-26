import { useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

type Guarantee = { name: string; customer: string; stay: string | null;
  booking: string | null; folio: string | null; method: string; currency: string;
  reference: string; available: string; available_book: string }
type Folio = { name: string; label: string; customer: string;
  stay: string | null; booking: string | null; currency: string; status: string;
  balance: { outstanding: string } }
export type GuaranteeData = {
  currency: string
  guarantees: Guarantee[]
  guarantee_page: { search: string; offset: number; has_more: boolean }
  guarantee_folios: Folio[]
  advance_bookings: { name: string; customer: string; status: string }[]
  advance_stays: { name: string; customer: string; status: string }[]
  methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean; reference_required: boolean }[]
  shifts: { name: string; cashier: string; status: string;
    modified: string; currency: string; expected: Record<string, string> }[]
}
type Quote = { amount: string; currency: string; property_amount: string;
  property_currency: string; exchange_rate: string; acceptance: string;
  origin?: { customer: string; stay: string | null; booking: string | null };
  guarantee?: { available_nominal: string; available_book: string;
    liability_amount: string; liability_account: string } }

export function Guarantees({ property, data, mode, canApprove, refresh, onNotice, onError }: {
  property: Property; data: GuaranteeData; canApprove: boolean;
  mode: "receive" | "apply" | "refund";
  refresh: () => Promise<void>; onNotice: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [origin, setOrigin] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [amount, setAmount] = useState("")
  const [tendered, setTendered] = useState("")
  const [reference, setReference] = useState("")
  const [receiptQuote, setReceiptQuote] = useState<Quote | null>(null)
  const [receiptKey, setReceiptKey] = useState("")
  const [source, setSource] = useState("")
  const [folio, setFolio] = useState("")
  const [applyShift, setApplyShift] = useState("")
  const [applyAmount, setApplyAmount] = useState("")
  const [applyReason, setApplyReason] = useState("")
  const [applyKey, setApplyKey] = useState("")
  const [refundSource, setRefundSource] = useState("")
  const [refundMethod, setRefundMethod] = useState("")
  const [refundShift, setRefundShift] = useState("")
  const [refundAmount, setRefundAmount] = useState("")
  const [refundReference, setRefundReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundQuote, setRefundQuote] = useState<Quote | null>(null)
  const [refundKey, setRefundKey] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setOrigin(""); setMethod(""); setShift(""); setAmount(""); setTendered("")
    setReference(""); setReceiptQuote(null); setReceiptKey("")
    setSource(""); setFolio(""); setApplyShift(""); setApplyAmount("")
    setApplyReason(""); setApplyKey("")
    setRefundSource(""); setRefundMethod(""); setRefundShift("")
    setRefundAmount(""); setRefundReference(""); setRefundReason("")
    setRefundQuote(null); setRefundKey("")
  }, [property.name])
  useEffect(() => {
    setSource(""); setFolio(""); setApplyAmount(""); setApplyKey("")
    setRefundSource(""); setRefundMethod(""); setRefundAmount("")
    setRefundQuote(null); setRefundKey("")
  }, [data.guarantee_page.search, data.guarantee_page.offset])

  const targets = [
    ...data.advance_bookings.map((row) => ({ key: `booking:${row.name}`,
      kind: "booking" as const, name: row.name,
      label: `Reserva ${row.name} · ${row.customer} · ${row.status}` })),
    ...data.advance_stays.map((row) => ({ key: `stay:${row.name}`,
      kind: "stay" as const, name: row.name,
      label: `Estancia ${row.name} · ${row.customer}` })),
  ]
  const target = targets.find((row) => row.key === origin)
  const chosenMethod = data.methods.find((row) => row.name === method)
  const chosenSource = data.guarantees.find((row) => row.name === source)
  const eligibleFolios = data.guarantee_folios.filter((row) => chosenSource &&
    row.customer === chosenSource.customer &&
    (row.stay ? row.stay === chosenSource.stay : row.booking === chosenSource.booking))
  const chosenRefundSource = data.guarantees.find((row) => row.name === refundSource)
  const chosenRefundMethod = data.methods.find((row) => row.name === refundMethod)
  const refundMethods = data.methods.filter((row) =>
    row.currency === chosenRefundSource?.currency)
  const openShifts = data.shifts.filter((row) => row.status === "Open")
  function changeReceipt() { setReceiptQuote(null); setReceiptKey(""); onError("") }
  function changeApply() { setApplyKey(""); onError("") }
  function changeRefund() { setRefundQuote(null); setRefundKey(""); onError("") }

  async function receive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !target || !chosenMethod || !shift) return
    const payload = { kind: "Guarantee", [target.kind]: target.name,
      method, shift, amount, reference: reference.trim(),
      ...(chosenMethod.is_cash && tendered ? { tendered } : {}) }
    setBusy(true); onError(""); onNotice("")
    try {
      if (!receiptQuote) {
        setReceiptQuote(await call<Quote>("preview", { property_name: property.name,
          action: "payment", data: JSON.stringify(payload) }))
      } else {
        const key = receiptKey || crypto.randomUUID(); setReceiptKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: receiptQuote.acceptance }, key)
        await refresh()
        setOrigin(""); setAmount(""); setTendered(""); setReference("")
        setReceiptQuote(null); setReceiptKey("")
        onNotice(`Garantía ${result.payment} recibida para ${target.name}.`)
      }
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudo recibir la garantía.") }
    finally { setBusy(false) }
  }

  async function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canApprove || !chosenSource || !folio || !applyShift) return
    setBusy(true); onError(""); onNotice("")
    try {
      const key = applyKey || crypto.randomUUID(); setApplyKey(key)
      const result = await execute<{ payment: string }>(property.name,
        "apply_guarantee", { source_payment: chosenSource.name, folio,
          shift: applyShift, amount: applyAmount, reason: applyReason.trim() }, key)
      await refresh()
      setSource(""); setFolio(""); setApplyAmount(""); setApplyReason("")
      setApplyKey("")
      onNotice(`Garantía aplicada en ${result.payment}.`)
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudo aplicar la garantía.") }
    finally { setBusy(false) }
  }

  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canApprove || !chosenRefundSource || !chosenRefundMethod || !refundShift) return
    const payload = { kind: "Guarantee Refund", source_payment: refundSource,
      method: refundMethod, shift: refundShift, amount: refundAmount,
      reference: refundReference.trim(), reason: refundReason.trim() }
    setBusy(true); onError(""); onNotice("")
    try {
      if (!refundQuote) {
        setRefundQuote(await call<Quote>("preview", { property_name: property.name,
          action: "payment", data: JSON.stringify(payload) }))
      } else {
        const key = refundKey || crypto.randomUUID(); setRefundKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: refundQuote.acceptance }, key)
        await refresh()
        setRefundSource(""); setRefundMethod(""); setRefundAmount("")
        setRefundReference(""); setRefundReason(""); setRefundQuote(null)
        setRefundKey("")
        onNotice(`Devolución de garantía ${result.payment} registrada.`)
      }
    } catch (issue) { onError(issue instanceof Error ? issue.message : "No se pudo devolver la garantía.") }
    finally { setBusy(false) }
  }

  return <div className="max-w-3xl space-y-5">
    {mode === "receive" && <Card><CardHeader><CardTitle>Recibir garantía</CardTitle><CardDescription>Se registra como pasivo reembolsable de la reserva o estancia. La recepción requiere un turno abierto.</CardDescription></CardHeader><CardContent><form onSubmit={receive} className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-sm sm:col-span-2">Origen<select required value={origin} onChange={(event) => { changeReceipt(); setOrigin(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione reserva o estancia</option>{targets.map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}</select></label>
      <label className="space-y-1 text-sm">Medio<select required value={method} onChange={(event) => { changeReceipt(); setMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
      <label className="space-y-1 text-sm">Turno<select required value={shift} onChange={(event) => { changeReceipt(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Turno abierto</option>{openShifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
      <label className="space-y-1 text-sm">Importe {chosenMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={amount} onChange={(event) => { changeReceipt(); setAmount(event.target.value) }} /></label>
      {chosenMethod?.is_cash && <label className="space-y-1 text-sm">Efectivo recibido {chosenMethod.currency}<Input type="number" min={amount || "0"} step="0.01" value={tendered} onChange={(event) => { changeReceipt(); setTendered(event.target.value) }} placeholder="Igual al importe" /></label>}
      <label className="space-y-1 text-sm sm:col-span-2">Referencia<Input required={!!chosenMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { changeReceipt(); setReference(event.target.value) }} /></label>
      {receiptQuote?.origin && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Cliente {receiptQuote.origin.customer} · {receiptQuote.currency} {receiptQuote.amount} × {receiptQuote.exchange_rate} = {receiptQuote.property_currency} {receiptQuote.property_amount}</p>}
      <Button disabled={busy || !targets.length} className="sm:col-span-2">{receiptQuote ? "Confirmar garantía" : "Revisar garantía"}</Button>
    </form></CardContent></Card>}
    {mode === "apply" && canApprove && <Card><CardHeader><CardTitle>Aplicar garantía</CardTitle><CardDescription>Gerencia aplica el saldo a la cuenta del mismo pagador y origen. El importe se expresa en la moneda de la garantía.</CardDescription></CardHeader><CardContent><form onSubmit={apply} className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2">Garantía disponible<select required value={source} onChange={(event) => { changeApply(); setSource(event.target.value); setFolio(""); setApplyAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione garantía</option>{data.guarantees.map((row) => <option key={row.name} value={row.name}>{row.reference} · {row.customer} · {row.currency} {row.available}</option>)}</select></label>
        {chosenSource && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Saldo nominal {chosenSource.currency} {chosenSource.available} · pasivo {data.currency} {chosenSource.available_book}</p>}
        <label className="space-y-1 text-sm sm:col-span-2">Cuenta compatible<select required value={folio} onChange={(event) => { changeApply(); setFolio(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{eligibleFolios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name} · Saldo {row.currency} {row.balance.outstanding}</option>)}</select></label>
        <p className="text-xs text-muted-foreground sm:col-span-2">Si la cuenta no aparece, <Link to="/customer-credits?section=folios" className="text-primary underline">búsquela en Cuentas de estancia</Link> y vuelva a esta opción.</p>
        <label className="space-y-1 text-sm">Turno<select required value={applyShift} onChange={(event) => { changeApply(); setApplyShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Turno abierto</option>{openShifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
        <label className="space-y-1 text-sm">Importe {chosenSource?.currency || ""}<Input required type="number" min="0.01" step="0.01" max={chosenSource?.available} value={applyAmount} onChange={(event) => { changeApply(); setApplyAmount(event.target.value) }} /></label>
        <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required minLength={8} maxLength={500} value={applyReason} onChange={(event) => { changeApply(); setApplyReason(event.target.value) }} /></label>
        <Button disabled={busy || !chosenSource || !eligibleFolios.length} className="sm:col-span-2">Aplicar garantía</Button>
      </form></CardContent></Card>}
    {mode === "refund" && canApprove && <Card><CardHeader><CardTitle>Devolver garantía</CardTitle><CardDescription>La revisión usa el saldo contable original. Devuelva en la moneda recibida y desde un turno abierto.</CardDescription></CardHeader><CardContent><form onSubmit={refund} className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2">Garantía<select required value={refundSource} onChange={(event) => { changeRefund(); setRefundSource(event.target.value); setRefundMethod(""); setRefundAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione garantía</option>{data.guarantees.map((row) => <option key={row.name} value={row.name}>{row.reference} · {row.customer} · {row.currency} {row.available}</option>)}</select></label>
        <label className="space-y-1 text-sm">Medio de salida<select required value={refundMethod} onChange={(event) => { changeRefund(); setRefundMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{refundMethods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
        <label className="space-y-1 text-sm">Turno<select required value={refundShift} onChange={(event) => { changeRefund(); setRefundShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Turno abierto</option>{openShifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
        <label className="space-y-1 text-sm">Importe {chosenRefundSource?.currency || ""}<Input required type="number" min="0.01" step="0.01" max={chosenRefundSource?.available} value={refundAmount} onChange={(event) => { changeRefund(); setRefundAmount(event.target.value) }} /></label>
        <label className="space-y-1 text-sm">Referencia<Input required={!!chosenRefundMethod?.reference_required} maxLength={140} value={refundReference} onChange={(event) => { changeRefund(); setRefundReference(event.target.value) }} /></label>
        <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required minLength={8} maxLength={500} value={refundReason} onChange={(event) => { changeRefund(); setRefundReason(event.target.value) }} /></label>
        {refundQuote?.guarantee && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Salida {refundQuote.currency} {refundQuote.amount} · pasivo liberado {data.currency} {refundQuote.guarantee.liability_amount} · disponible antes {chosenRefundSource?.currency} {refundQuote.guarantee.available_nominal}</p>}
        <Button disabled={busy || !chosenRefundSource || !refundMethods.length} className="sm:col-span-2">{refundQuote ? "Confirmar devolución" : "Revisar devolución"}</Button>
      </form></CardContent></Card>}
  </div>
}
