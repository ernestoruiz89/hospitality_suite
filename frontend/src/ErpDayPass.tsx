import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { availableDayPassSections } from "./DayPassSections"

type Pass = { name: string; modified: string; customer: string; guest: string | null; people: number;
  starts_at: string; ends_at: string; status: string; effective_status: string;
  service: string | null; sales_invoice: string | null; amount: string | null;
  erp_opening_invoice: string | null; historical_invoice_number: string | null;
  erp_return_credit_note: string | null; erp_return_refund: string | null;
  correction_count: number;
  historical: boolean; transfer_problem: boolean;
  currency: string; outstanding: string | null;
  can_return: boolean }
type Snapshot = { currency: string; time_zone: string;
  item: { name: string; item_name: string; disabled: boolean; is_stock_item: boolean } | null;
  price_list: string | null; receivable_account: string | null;
  customers: { name: string; party_name: string }[];
  guests: { name: string; full_name: string; customer: string | null }[];
  methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean; reference_required: boolean }[];
  shifts: { name: string; cashier: string; currency: string; status: string }[];
  day_passes: Pass[] }
type Quote = { item: string; quantity: string; rate: string; total: string;
  currency: string; payment_amount: string; payment_currency: string;
  exchange_rate: string; people: number; starts_at: string; ends_at: string;
  acceptance: string }
type Issued = { day_pass: string; invoice: string; payment: string;
  amount: string; currency: string; change: string }
type HistoricalReturnQuote = { day_pass: string; modified: string;
  original_invoice: string | null; currency: string; credit_net: string;
  credit_tax: string; credit_total: string; opening_applied: string;
  refund_base: string; refund_amount: string; refund_currency: string | null;
  exchange_rate: string; method: string | null; shift: string | null;
  reference: string; reason: string; acceptance: string }
type HistoricalCorrectionQuote = { credit_note: string; refund: string | null;
  payment_entry: string | null; opening_invoice: string | null;
  opening_applied: string; refund_currency: string | null;
  refund_amount: string; business_date: string; acceptance: string }
const statusLabel: Record<string, string> = {
  Upcoming: "Próximo", Active: "Vigente", Expired: "Vencido", Cancelled: "Cancelado",
}
const localTime = (value: string) => value.slice(0, 16).replace("T", " ")
const invoicePrint = (name: string) => `/printview?doctype=${encodeURIComponent("Sales Invoice")}&name=${encodeURIComponent(name)}`

export function ErpDayPass({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableDayPassSections("erpnext", false, canApprove)
  const section = sections.find((item) => item.id === searchParams.get("section")) || sections[0]
  useEffect(() => {
    if (!searchParams.has("section") || sections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", sections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams, sections])
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [issuedInvoice, setIssuedInvoice] = useState("")
  const [customer, setCustomer] = useState("")
  const [guest, setGuest] = useState("")
  const [people, setPeople] = useState("1")
  const [startsAt, setStartsAt] = useState("")
  const [endsAt, setEndsAt] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [reference, setReference] = useState("")
  const [tendered, setTendered] = useState("")
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<(Quote & { requestKey: string }) | null>(null)
  const [returnPass, setReturnPass] = useState("")
  const [returnMethod, setReturnMethod] = useState("")
  const [returnShift, setReturnShift] = useState("")
  const [returnReference, setReturnReference] = useState("")
  const [returnReason, setReturnReason] = useState("")
  const [returnKey, setReturnKey] = useState("")
  const [returnQuote, setReturnQuote] = useState<HistoricalReturnQuote | null>(null)
  const [correctionPass, setCorrectionPass] = useState("")
  const [correctionReason, setCorrectionReason] = useState("")
  const [correctionQuote, setCorrectionQuote] = useState<HistoricalCorrectionQuote | null>(null)
  const [correctionKey, setCorrectionKey] = useState("")

  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("erp_day_pass_snapshot", { property_name: property.name }))
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setIssuedInvoice(""); setQuote(null)
    setCustomer(""); setGuest(""); setPeople("1"); setStartsAt(""); setEndsAt("")
    setMethod(""); setShift(""); setReference(""); setTendered(""); setNotes("")
    setReturnPass(""); setReturnMethod(""); setReturnShift(""); setReturnReference("")
    setReturnReason(""); setReturnKey(""); setReturnQuote(null)
    setCorrectionPass(""); setCorrectionReason(""); setCorrectionQuote(null); setCorrectionKey("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los Day Pass."))
  }, [refresh])
  useEffect(() => {
    setReturnPass(""); setReturnMethod(""); setReturnShift(""); setReturnReference("")
    setReturnReason(""); setReturnKey(""); setReturnQuote(null)
    setCorrectionPass(""); setCorrectionReason(""); setCorrectionQuote(null); setCorrectionKey("")
  }, [section.id])
  const selectedMethod = data?.methods.find((row) => row.name === method)
  const selectedReturn = data?.day_passes.find((row) => row.name === returnPass)
  const selectedCorrection = data?.day_passes.find((row) => row.name === correctionPass)
  const selectedReturnMethod = data?.methods.find((row) => row.name === returnMethod)
  const displayedPasses = data?.day_passes.filter((row) =>
    section.id === "passes-return" ? row.can_return : true) || []
  const customerLabel = (name: string) => data?.customers.find((row) => row.name === name)?.party_name || name
  const guestLabel = (name: string | null) => data?.guests.find((row) => row.name === name)?.full_name || "Sin huésped asociado"
  const invalidate = () => { setQuote(null); setError(""); setIssuedInvoice("") }
  const saleData = () => ({ customer, guest: guest || null, people: Number(people),
    starts_at: startsAt, ends_at: endsAt, method, shift,
    reference: reference.trim(), tendered: tendered || undefined, notes: notes.trim() })

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setQuote(null)
    try {
      const result = await call<Quote>("preview", { property_name: property.name,
        action: "day_pass_no_room", data: JSON.stringify(saleData()) })
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cotizar el Day Pass.") }
    finally { setBusy(false) }
  }

  async function issue() {
    if (!quote || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<Issued>(property.name, "day_pass_no_room",
        { ...saleData(), acceptance: quote.acceptance }, quote.requestKey)
      await refresh(); setQuote(null); setGuest(""); setNotes(""); setTendered("")
      setIssuedInvoice(result.invoice)
      setNotice(`Day Pass ${result.day_pass} emitido y cobrado: ${result.currency} ${result.amount}. Factura ${result.invoice}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo emitir el Day Pass. Revise la cotización y el turno.") }
    finally { setBusy(false) }
  }

  async function returnSale(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedReturn?.service || !selectedReturn.can_return ||
      !canApprove || busy || section.id !== "passes-return") return
    setBusy(true); setError("")
    const key = returnKey || crypto.randomUUID()
    setReturnKey(key)
    try {
      const result = await execute<{ credit_note: string; payment: string }>(property.name,
        "return_direct_sale", { service: selectedReturn.service, shift: returnShift,
          reason: returnReason.trim() }, key)
      await refresh(); setReturnPass(""); setReturnShift(""); setReturnReason(""); setReturnKey("")
      setNotice(`Day Pass ${selectedReturn.name} devuelto. Nota de crédito ${result.credit_note}; devolución ${result.payment}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el Day Pass.") }
    finally { setBusy(false) }
  }

  const historicalReturnData = () => ({ day_pass: selectedReturn?.name,
    modified: selectedReturn?.modified, method: returnMethod, shift: returnShift,
    amount: "", reference: returnReference.trim(), reason: returnReason.trim() })

  async function reviewHistoricalReturn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedReturn?.historical || !selectedReturn.can_return || !canApprove || busy) return
    setBusy(true); setError(""); setReturnQuote(null)
    try {
      const result = await call<HistoricalReturnQuote>("erp_historical_day_pass_return_quote", {
        property_name: property.name, data: JSON.stringify(historicalReturnData()) })
      setReturnQuote(result); setReturnKey(crypto.randomUUID())
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la devolución histórica.") }
    finally { setBusy(false) }
  }

  async function confirmHistoricalReturn() {
    if (!selectedReturn?.historical || !returnQuote || busy) return
    setBusy(true); setError("")
    const key = returnKey || crypto.randomUUID()
    setReturnKey(key)
    try {
      const result = await execute<{ credit_note: string; refund: string | null }>(
        property.name, "erp_historical_day_pass_return",
        { ...historicalReturnData(), amount: returnQuote.refund_amount,
          acceptance: returnQuote.acceptance }, key)
      await refresh()
      setReturnPass(""); setReturnMethod(""); setReturnShift(""); setReturnReference("")
      setReturnReason(""); setReturnKey(""); setReturnQuote(null)
      setNotice(`Day Pass ${selectedReturn.name} devuelto. Nota de crédito ${result.credit_note}` +
        (result.refund ? `; reembolso ${result.refund}.` : "; el crédito se aplicó al saldo abierto."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el Day Pass histórico.") }
    finally { setBusy(false) }
  }

  const correctionData = () => ({ day_pass: selectedCorrection?.name || "",
    modified: selectedCorrection?.modified || "", reason: correctionReason.trim() })
  async function reviewHistoricalCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canApprove || !selectedCorrection || !correctionReason.trim() || busy) return
    setBusy(true); setError(""); setCorrectionQuote(null); setCorrectionKey("")
    try {
      const result = await call<HistoricalCorrectionQuote>(
        "erp_historical_day_pass_return_reversal_quote", {
          property_name: property.name, data: JSON.stringify(correctionData()) })
      setCorrectionQuote(result); setCorrectionKey(crypto.randomUUID())
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la corrección.") }
    finally { setBusy(false) }
  }
  async function confirmHistoricalCorrection() {
    if (!selectedCorrection || !correctionQuote || !correctionKey || busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "erp_historical_day_pass_return_reversal",
        { ...correctionData(), acceptance: correctionQuote.acceptance }, correctionKey)
      await refresh()
      setCorrectionPass(""); setCorrectionReason(""); setCorrectionQuote(null); setCorrectionKey("")
      setNotice(`Devolución del Day Pass ${selectedCorrection.name} corregida. El acceso vuelve a estar vigente.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo corregir la devolución.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Day Pass sin habitación</h1>
      <p className="mt-1 text-sm text-muted-foreground">{section.label} · {section.description}. En ERPNext la emisión crea la factura y registra el cobro en el mismo paso.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice} {issuedInvoice && <a className="underline" href={invoicePrint(issuedInvoice)} target="_blank" rel="noopener noreferrer">Imprimir factura</a>}</p>}
    {!data ? <Skeleton className="h-80 rounded-xl" /> : <>
      {section.id === "issue" && <Card><CardHeader><CardTitle>Emitir acceso y cobrar</CardTitle><CardDescription>Entrada y salida el mismo día local de {data.time_zone}. Hasta cien personas por emisión.</CardDescription></CardHeader><CardContent className="space-y-3">
        {(!data.item || data.item.disabled || data.item.is_stock_item || !data.price_list || !data.receivable_account) && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Configure un artículo de servicio Day Pass, lista de precios y cuenta por cobrar para este establecimiento en ERPNext.</p>}
        {data.item && <p className="text-sm">Artículo: <strong>{data.item.item_name}</strong> · Precio e impuestos se calculan al cotizar.</p>}
        {!data.shifts.length && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Abra un turno en <Link to="/cash?section=shift-open" className="underline">Caja ERPNext</Link> antes de emitir.</p>}
        <form onSubmit={review} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Pagador</span><select required value={customer} onChange={(event) => { setCustomer(event.target.value); setGuest(""); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione pagador</option>{data.customers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Huésped (opcional)</span><select value={guest} onChange={(event) => { setGuest(event.target.value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin huésped asociado</option>{data.guests.filter((row) => row.customer === customer).map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Personas</span><Input required type="number" min="1" max="100" step="1" value={people} onChange={(event) => { setPeople(event.target.value); invalidate() }} /></label>
          <label className="space-y-1 text-sm"><span>Medio de pago</span><select required value={method} onChange={(event) => { setMethod(event.target.value); setReference(""); setTendered(""); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Entrada</span><Input required type="datetime-local" value={startsAt} onChange={(event) => { setStartsAt(event.target.value); invalidate() }} /></label>
          <label className="space-y-1 text-sm"><span>Salida</span><Input required type="datetime-local" value={endsAt} onChange={(event) => { setEndsAt(event.target.value); invalidate() }} /></label>
          <label className="space-y-1 text-sm"><span>Turno abierto</span><select required value={shift} onChange={(event) => { setShift(event.target.value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Referencia{selectedMethod?.reference_required ? " (obligatoria)" : " (opcional)"}</span><Input required={!!selectedMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { setReference(event.target.value); invalidate() }} /></label>
          {selectedMethod?.is_cash && <label className="space-y-1 text-sm"><span>Recibido en {selectedMethod.currency} (opcional)</span><Input type="number" min="0" step="0.01" value={tendered} onChange={(event) => { setTendered(event.target.value); invalidate() }} /></label>}
          <label className="space-y-1 text-sm"><span>Notas</span><Input maxLength={500} value={notes} onChange={(event) => { setNotes(event.target.value); invalidate() }} /></label>
          <div className="md:col-span-2"><Button disabled={busy || !data.item || !!data.item.disabled || !!data.item.is_stock_item || !data.price_list || !data.receivable_account || !data.shifts.length}>Revisar importe</Button></div>
        </form>
        {quote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p>{quote.people} persona(s) · {localTime(startsAt)} → {localTime(endsAt)}</p><p>Precio unitario {quote.currency} {quote.rate} · Factura <strong>{quote.currency} {quote.total}</strong></p><p>Cobro: <strong>{quote.payment_currency} {quote.payment_amount}</strong>{quote.payment_currency !== quote.currency && ` · Cambio ${quote.exchange_rate}`}</p><Button disabled={busy} onClick={() => void issue()}>Emitir factura y cobrar</Button></div>}
        <p className="text-xs text-muted-foreground">El usuario verifica el registro y la autorización fiscal que correspondan antes de imprimir.</p>
      </CardContent></Card>}
      {(section.id === "passes" || section.id === "passes-return") && <Card>
        <CardHeader><CardTitle>{section.label}</CardTitle>
          <CardDescription>{section.id === "passes" ? "Últimos cien Day Pass del establecimiento, incluidos los anteriores a ERPNext." : section.description}</CardDescription>
        </CardHeader><CardContent className="space-y-3">
        {displayedPasses.map((row) => <div key={row.name} className="space-y-2 border-b border-border pb-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3"><span><strong>{row.name}</strong> · {customerLabel(row.customer)} · {guestLabel(row.guest)} · {row.people} persona(s)
            <span className="block text-muted-foreground">{localTime(row.starts_at)} → {localTime(row.ends_at)} · {statusLabel[row.effective_status] || row.effective_status}</span></span>
            <span className="text-right">{row.amount ? `${row.currency} ${row.amount}` : "Cargo PMS histórico"}
              {row.historical && <span className="block text-xs text-muted-foreground">
                {row.transfer_problem ? "El saldo histórico requiere conciliación." : <>
                  Factura PMS {row.historical_invoice_number || "sin emitir"} ·
                  Saldo trasladado {row.currency} {row.outstanding || "0"}
                </>}
              </span>}
            </span>
          </div>
          <div className="flex gap-2">
            {row.sales_invoice && <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" href={invoicePrint(row.sales_invoice)} target="_blank" rel="noopener noreferrer">Imprimir factura</a>}
            {row.erp_opening_invoice && Number(row.outstanding) > 0 &&
              <Button asChild type="button" variant="outline" size="sm"><Link to={`/customer-credits?section=invoices&invoice=${encodeURIComponent(row.erp_opening_invoice)}`}>Cobrar saldo trasladado</Link></Button>}
            {row.erp_return_credit_note && <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" href={invoicePrint(row.erp_return_credit_note)} target="_blank" rel="noopener noreferrer">Imprimir nota de crédito</a>}
            {row.correction_count > 0 && <span className="self-center text-xs text-muted-foreground">Correcciones: {row.correction_count}</span>}
            {section.id === "passes" && canApprove && row.historical && row.status === "Cancelled" && row.erp_return_credit_note && <Button type="button" variant="outline" size="sm" onClick={() => { setCorrectionPass(row.name); setCorrectionReason(""); setCorrectionQuote(null); setCorrectionKey("") }}>Corregir devolución</Button>}
            {section.id === "passes-return" && canApprove && row.can_return && <Button type="button" variant="outline" size="sm" onClick={() => { setReturnPass(row.name); setReturnMethod(""); setReturnShift(""); setReturnReference(""); setReturnReason(""); setReturnKey(""); setReturnQuote(null) }}>Devolver acceso</Button>}
          </div>
        </div>)}
        {!displayedPasses.length && <p className="text-sm text-muted-foreground">No hay Day Pass para esta opción.</p>}
        {section.id === "passes" && selectedCorrection && <form onSubmit={(event) => void reviewHistoricalCorrection(event)} className="space-y-3 rounded-lg bg-secondary p-3 text-sm">
          <p>Day Pass {selectedCorrection.name} · nota {selectedCorrection.erp_return_credit_note}. La corrección requiere fecha operativa abierta y cancelará todos los comprobantes vinculados.</p>
          <label className="block space-y-1"><span>Motivo de corrección</span><Input required maxLength={500} value={correctionReason} onChange={(event) => { setCorrectionReason(event.target.value); setCorrectionQuote(null); setCorrectionKey("") }} /></label>
          <div className="flex gap-2"><Button type="submit" variant="outline" disabled={busy || !correctionReason.trim()}>Revisar corrección</Button><Button type="button" variant="outline" onClick={() => { setCorrectionPass(""); setCorrectionQuote(null) }}>Volver</Button></div>
          {correctionQuote && <div className="space-y-2 rounded-md border border-border bg-white p-3"><p>Fecha {correctionQuote.business_date}. Se cancelarán nota {correctionQuote.credit_note}{correctionQuote.payment_entry && ` y reembolso ${correctionQuote.refund_currency} ${correctionQuote.refund_amount} (${correctionQuote.payment_entry})`}. Se restaurará el saldo de apertura {property.currency} {correctionQuote.opening_applied}.</p>
            <Button type="button" disabled={busy} onClick={() => void confirmHistoricalCorrection()}>Confirmar corrección integral</Button></div>}
        </form>}
        {section.id === "passes-return" && selectedReturn && (selectedReturn.historical ?
          <div className="space-y-3 rounded-lg bg-secondary p-3 text-sm">
            <p>Devolver {selectedReturn.name}. La nota revierte la venta PMS aún no acreditada; se aplica al saldo trasladado y solo se reembolsa el resto.</p>
            <form onSubmit={reviewHistoricalReturn} className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1"><span>Medio de reembolso (si corresponde)</span><select value={returnMethod} onChange={(event) => { setReturnMethod(event.target.value); setReturnShift(""); setReturnQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin movimiento de Caja</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
              {selectedReturnMethod?.is_cash && <label className="space-y-1"><span>Turno propio abierto</span><select required value={returnShift} onChange={(event) => { setReturnShift(event.target.value); setReturnQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno</option>{data.shifts.filter((row) => row.currency === selectedReturnMethod.currency).map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>}
              <label className="space-y-1"><span>Referencia</span><Input required={!!selectedReturnMethod?.reference_required} maxLength={140} value={returnReference} onChange={(event) => { setReturnReference(event.target.value); setReturnQuote(null) }} /></label>
              <label className="space-y-1 md:col-span-2"><span>Motivo de devolución</span><Input required maxLength={500} value={returnReason} onChange={(event) => { setReturnReason(event.target.value); setReturnQuote(null) }} /></label>
              <div className="md:col-span-2 flex gap-2"><Button disabled={busy}>Revisar devolución</Button><Button type="button" variant="outline" onClick={() => { setReturnPass(""); setReturnQuote(null) }}>Volver</Button></div>
            </form>
            {returnQuote && <div className="space-y-2 rounded-lg border border-border bg-white p-3">
              <p>Nota de crédito: <strong>{returnQuote.currency} {returnQuote.credit_total}</strong> (base {returnQuote.credit_net}; impuesto {returnQuote.credit_tax}).</p>
              <p>Aplicar al saldo trasladado: {returnQuote.currency} {returnQuote.opening_applied}.</p>
              <p>Reembolso: <strong>{returnQuote.refund_currency || returnQuote.currency} {returnQuote.refund_amount}</strong>{returnQuote.refund_currency && returnQuote.refund_currency !== returnQuote.currency && ` · cambio ${returnQuote.exchange_rate}`}</p>
              <Button type="button" disabled={busy} onClick={() => void confirmHistoricalReturn()}>Emitir nota y devolver</Button>
            </div>}
          </div> :
          <form onSubmit={returnSale} className="space-y-3 rounded-lg bg-secondary p-3 text-sm"><p>Devolver {selectedReturn.name}. Se emitirá una nota de crédito completa y se reembolsará el pago original.</p><select required value={returnShift} onChange={(event) => { setReturnShift(event.target.value); setReturnKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno abierto</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select><Input required maxLength={500} placeholder="Motivo de devolución" value={returnReason} onChange={(event) => { setReturnReason(event.target.value); setReturnKey("") }} /><div className="flex gap-2"><Button disabled={busy}>Confirmar devolución</Button><Button type="button" variant="outline" onClick={() => setReturnPass("")}>Volver</Button></div></form>)}
      </CardContent></Card>}
    </>}
  </div>
}
