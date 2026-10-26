import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"
import { availableDayPassSections } from "./DayPassSections"

type DayPassRow = { name: string; customer: string; guest: string | null; people: number;
  starts_at: string; ends_at: string; effective_status: string; status: string;
  pms_receivable: string | null; opening_historical_invoice: string | null;
  historical_invoice_number: string | null;
  amount: string; currency: string; outstanding: string;
  invoiced: boolean; can_cancel: boolean; can_return: boolean;
  opening_credit_note: string | null; opening_refund: string | null;
  modified: string }
type Snapshot = { currency: string; time_zone: string; property_modified: string;
  receivable_account: string | null;
  receivable_accounts: { name: string; account_code: string; account_name: string }[];
  product: { name: string; product_name: string; sales_rate: number; tax_profile: string | null } | null;
  day_passes: DayPassRow[];
  return_series: { name: string; series_code: string; next_number: number }[];
  return_methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: number }[];
  return_shifts: { name: string; expected: Record<string, string> }[];
  customers: { name: string; party_name: string }[];
  guests: { name: string; full_name: string }[] }
type Quote = { people: number; starts_at: string; ends_at: string;
  product_name: string; unit_rate: string; currency: string;
  net_amount: string; tax_amount: string; total_amount: string;
  acceptance: string }
type ReturnQuote = { document_number: string; historical_invoice_number: string;
  amount: string; currency: string; base_amount: string; base_currency: string;
  net_amount: string; tax_amount: string; debit: string; credit: string;
  exchange_rate: string; acceptance: string }

const statusLabel: Record<string, string> = {
  Upcoming: "Próximo", Active: "Vigente", Expired: "Vencido", Cancelled: "Cancelado",
}
const propertyTime = (value: string) => value.slice(0, 16).replace("T", " ")

export function DayPass({ property, canSetup, canApprove }: {
  property: Property; canSetup: boolean; canApprove: boolean
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableDayPassSections("pms", canSetup, canApprove)
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
  const [customer, setCustomer] = useState("")
  const [guest, setGuest] = useState("")
  const [people, setPeople] = useState("1")
  const [startsAt, setStartsAt] = useState("")
  const [endsAt, setEndsAt] = useState("")
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<(Quote & { requestKey: string }) | null>(null)
  const [account, setAccount] = useState("")
  const [cancelPass, setCancelPass] = useState("")
  const [cancelReason, setCancelReason] = useState("")
  const [returnPass, setReturnPass] = useState("")
  const [returnSeries, setReturnSeries] = useState("")
  const [returnMethod, setReturnMethod] = useState("")
  const [returnShift, setReturnShift] = useState("")
  const [returnAmount, setReturnAmount] = useState("")
  const [returnReference, setReturnReference] = useState("")
  const [returnReason, setReturnReason] = useState("")
  const [returnQuote, setReturnQuote] = useState<(ReturnQuote & { requestKey: string }) | null>(null)

  const refresh = useCallback(async () => {
    const snapshot = await call<Snapshot>("pms_day_pass_snapshot", { property_name: property.name })
    setData(snapshot)
    setAccount(snapshot.receivable_account || "")
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setQuote(null); setCancelPass("")
    setReturnPass(""); setReturnQuote(null)
    setCustomer(""); setGuest(""); setPeople("1"); setStartsAt(""); setEndsAt(""); setNotes("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los Day Pass."))
  }, [refresh])
  useEffect(() => {
    setCancelPass(""); setCancelReason(""); setReturnPass(""); setReturnQuote(null)
  }, [section.id])
  const selectedPass = data?.day_passes.find((row) => row.name === cancelPass)
  const selectedReturn = data?.day_passes.find((row) => row.name === returnPass)
  const displayedPasses = data?.day_passes.filter((row) =>
    section.id === "passes-cancel" ? row.can_cancel :
      section.id === "passes-return" ? row.can_return : true) || []
  const selectedMethod = data?.return_methods.find((row) => row.name === returnMethod)
  const customerLabel = (name: string) => data?.customers.find((row) => row.name === name)?.party_name || name
  const guestLabel = (name: string | null) => data?.guests.find((row) => row.name === name)?.full_name || "Sin huésped asociado"
  const invalidate = () => { setQuote(null); setError("") }

  async function saveAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!data || !canSetup || busy) return
    setBusy(true); setError("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "property",
        request_key: crypto.randomUUID(), expected_modified: data.property_modified,
        data: { receivable_account: account || null } })
      await refresh(); setQuote(null); setNotice("Cuenta por cobrar actualizada para futuras emisiones.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la cuenta.") }
    finally { setBusy(false) }
  }

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setQuote(null)
    try {
      const result = await call<Quote>("preview", { property_name: property.name,
        action: "day_pass_no_room", data: JSON.stringify({ customer, guest: guest || null,
          people: Number(people), starts_at: startsAt, ends_at: endsAt, notes: notes.trim() }) })
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cotizar el Day Pass.") }
    finally { setBusy(false) }
  }

  async function issue() {
    if (!quote || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ day_pass: string; receivable: string }>(property.name,
        "day_pass_no_room", { customer, guest: guest || null, people: Number(people),
          starts_at: startsAt, ends_at: endsAt, notes: notes.trim(),
          acceptance: quote.acceptance }, quote.requestKey)
      await refresh(); setQuote(null); setGuest(""); setNotes("")
      setNotice(`Day Pass ${result.day_pass} emitido. Cargo ${result.receivable} disponible para cobro y factura.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo emitir el Day Pass. Revise la cotización.") }
    finally { setBusy(false) }
  }

  async function cancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPass?.can_cancel || !canApprove || busy ||
      section.id !== "passes-cancel") return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_day_pass_cancel", {
        day_pass: selectedPass.name, modified: selectedPass.modified,
        reason: cancelReason.trim() }, crypto.randomUUID())
      await refresh(); setCancelPass(""); setCancelReason("")
      setNotice(`Day Pass ${selectedPass.name} cancelado.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cancelar el Day Pass.") }
    finally { setBusy(false) }
  }

  const returnData = () => ({ day_pass: returnPass, modified: selectedReturn?.modified,
    series: returnSeries, method: returnMethod,
    shift: selectedMethod?.is_cash ? returnShift : null,
    amount: returnAmount, reference: returnReference.trim(),
    reason: returnReason.trim() })

  async function reviewReturn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedReturn?.can_return || !canApprove || busy ||
      section.id !== "passes-return") return
    setBusy(true); setError(""); setReturnQuote(null)
    try {
      const result = await call<ReturnQuote>("pms_historical_day_pass_return_quote", {
        property_name: property.name, data: JSON.stringify(returnData()) })
      setReturnQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cotizar la devolución histórica.") }
    finally { setBusy(false) }
  }

  async function confirmReturn() {
    if (!selectedReturn?.can_return || !returnQuote || !canApprove || busy ||
      section.id !== "passes-return") return
    setBusy(true); setError("")
    try {
      const result = await execute<{ document_number: string; refund: string }>(
        property.name, "pms_historical_day_pass_return",
        { ...returnData(), acceptance: returnQuote.acceptance },
        returnQuote.requestKey)
      await refresh(); setReturnPass(""); setReturnQuote(null)
      setNotice(`Day Pass devuelto y cancelado. Nota ${result.document_number}; reembolso ${result.refund}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo completar la devolución histórica.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Day Pass sin habitación</h1>
      <p className="mt-1 text-sm text-muted-foreground">{section.label} · {section.description}. El cargo se contabiliza al emitir; el cobro y la factura se gestionan por separado.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-80 rounded-xl" /> : <>
      {(section.id === "issue" || section.id === "account" && canSetup) && <div className="max-w-4xl">
        {section.id === "issue" && <Card><CardHeader><CardTitle>Emitir acceso</CardTitle><CardDescription>Entrada y salida en el mismo día local de {data.time_zone}. Hasta cien personas por emisión.</CardDescription></CardHeader><CardContent className="space-y-3">
          {!data.product?.tax_profile && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Configure un producto Day Pass de servicio con precio y perfil tributario en {canSetup ? <Link to="/products" className="underline">Productos PMS</Link> : "Productos PMS"}.</p>}
          {!data.receivable_account && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Configure una cuenta por cobrar antes de emitir.</p>}
          {data.product && <p className="text-sm">Producto: <strong>{data.product.product_name}</strong> · {data.currency} {data.product.sales_rate} por persona</p>}
          <form onSubmit={review} className="space-y-3">
            <label className="block space-y-1 text-sm"><span>Pagador</span><select required value={customer} onChange={(event) => { setCustomer(event.target.value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione pagador</option>{data.customers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label>
            <label className="block space-y-1 text-sm"><span>Huésped (opcional)</span><select value={guest} onChange={(event) => { setGuest(event.target.value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin huésped asociado</option>{data.guests.map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}</select></label>
            <div className="grid gap-3 sm:grid-cols-3"><label className="space-y-1 text-sm"><span>Personas</span><Input required type="number" min="1" max="100" step="1" value={people} onChange={(event) => { setPeople(event.target.value); invalidate() }} /></label><label className="space-y-1 text-sm"><span>Entrada</span><Input required type="datetime-local" value={startsAt} onChange={(event) => { setStartsAt(event.target.value); invalidate() }} /></label><label className="space-y-1 text-sm"><span>Salida</span><Input required type="datetime-local" value={endsAt} onChange={(event) => { setEndsAt(event.target.value); invalidate() }} /></label></div>
            <label className="block space-y-1 text-sm"><span>Notas</span><Input maxLength={500} value={notes} onChange={(event) => { setNotes(event.target.value); invalidate() }} /></label>
            <Button disabled={busy || !data.product?.tax_profile || !data.receivable_account}>Revisar importe</Button>
          </form>
          {quote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p><strong>{quote.product_name}</strong> · {quote.people} persona(s) · {quote.currency} {quote.unit_rate} cada una</p><p>{propertyTime(quote.starts_at)} → {propertyTime(quote.ends_at)}</p><p>Base {quote.currency} {quote.net_amount} · Impuesto {quote.currency} {quote.tax_amount} · <strong>Total {quote.currency} {quote.total_amount}</strong></p><Button disabled={busy} onClick={() => void issue()}>Emitir Day Pass</Button></div>}
        </CardContent></Card>}
        {section.id === "account" && canSetup && <Card><CardHeader><CardTitle>Cuenta por cobrar</CardTitle><CardDescription>Los Day Pass nuevos usarán esta cuenta. El producto, su precio y su impuesto se configuran en Productos PMS.</CardDescription></CardHeader><CardContent><form onSubmit={saveAccount} className="space-y-3"><select required value={account} onChange={(event) => setAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione cuenta</option>{data.receivable_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select><Button disabled={busy}>Guardar cuenta</Button></form></CardContent></Card>}
      </div>}
      {["passes", "passes-cancel", "passes-return"].includes(section.id) && <Card>
        <CardHeader><CardTitle>{section.label}</CardTitle>
          <CardDescription>{section.id === "passes" ? "El saldo se cobra en Caja y el cargo se factura en Facturación PMS." : section.description}</CardDescription>
        </CardHeader><CardContent className="space-y-3">
        {displayedPasses.map((row) => <div key={row.name} className="space-y-2 border-b border-border pb-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span><strong>{row.name}</strong> · {customerLabel(row.customer)} · {guestLabel(row.guest)} · {row.people} persona(s)
              <span className="block text-muted-foreground">{propertyTime(row.starts_at)} → {propertyTime(row.ends_at)} · {statusLabel[row.effective_status] || row.effective_status}</span>
              {row.historical_invoice_number && <span className="block text-muted-foreground">Factura histórica {row.historical_invoice_number} · <Link to="/fiscal-archive" className="underline">Ver archivo fiscal</Link></span>}
              {row.opening_credit_note && <span className="block text-muted-foreground">Nota y reembolso registrados · <Link to="/fiscal-archive" className="underline">Ver archivo fiscal</Link></span>}
            </span>
            <span>{row.currency} {row.amount} · Pendiente {row.outstanding}</span>
          </div>
          {row.status === "Issued" && <div className="flex flex-wrap gap-2">
            {section.id === "passes" && Number(row.outstanding) > 0 && <Button asChild variant="outline" size="sm"><Link to="/cash?section=collect">Cobrar</Link></Button>}
            {section.id === "passes" && !row.invoiced && <Button asChild variant="outline" size="sm"><Link to="/billing?section=invoices">Facturar</Link></Button>}
            {section.id === "passes-cancel" && canApprove && row.can_cancel && <Button type="button" variant="outline" size="sm" onClick={() => { setCancelPass(row.name); setCancelReason("") }}>Cancelar acceso</Button>}
            {section.id === "passes-return" && canApprove && row.can_return && <Button type="button" variant="outline" size="sm" onClick={() => { setReturnPass(row.name); setReturnQuote(null); setReturnSeries(""); setReturnMethod(""); setReturnShift(""); setReturnAmount(row.amount); setReturnReference(""); setReturnReason("") }}>Devolver y cancelar</Button>}
          </div>}
        </div>)}
        {!displayedPasses.length && <p className="text-sm text-muted-foreground">No hay Day Pass para esta opción.</p>}
        {section.id === "passes-cancel" && selectedPass && <form onSubmit={cancel} className="space-y-3 rounded-lg bg-secondary p-3 text-sm"><p>Cancelar {selectedPass.name}. Devuelva primero los cobros; si tiene factura, emita una nota de crédito completa.</p><Input required maxLength={500} placeholder="Motivo de cancelación" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} /><div className="flex gap-2"><Button disabled={busy}>Confirmar cancelación</Button><Button type="button" variant="outline" onClick={() => setCancelPass("")}>Volver</Button></div></form>}
        {section.id === "passes-return" && selectedReturn && <form onSubmit={reviewReturn} className="space-y-3 rounded-lg bg-secondary p-4 text-sm">
          <h3 className="font-semibold">Devolver Day Pass histórico {selectedReturn.name}</h3>
          <p>Se emitirá una nota de crédito por la factura histórica {selectedReturn.historical_invoice_number} y un reembolso íntegro. Revise las cuentas antes de confirmar.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1"><span>Serie de nota de crédito</span><select required className="h-9 w-full rounded-md border border-border bg-white px-2" value={returnSeries} onChange={(event) => { setReturnSeries(event.target.value); setReturnQuote(null) }}><option value="">Seleccione serie</option>{data.return_series.map((row) => <option key={row.name} value={row.name}>{row.series_code} · próximo {row.next_number}</option>)}</select></label>
            <label className="space-y-1"><span>Medio de devolución</span><select required className="h-9 w-full rounded-md border border-border bg-white px-2" value={returnMethod} onChange={(event) => { setReturnMethod(event.target.value); setReturnShift(""); setReturnQuote(null) }}><option value="">Seleccione medio</option>{data.return_methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
            {selectedMethod?.is_cash && <label className="space-y-1"><span>Turno propio</span><select required className="h-9 w-full rounded-md border border-border bg-white px-2" value={returnShift} onChange={(event) => { setReturnShift(event.target.value); setReturnQuote(null) }}><option value="">Seleccione turno</option>{data.return_shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · disponible {selectedMethod.currency} {row.expected[selectedMethod.currency] || "0.00"}</option>)}</select></label>}
            <label className="space-y-1"><span>Importe a entregar ({selectedMethod?.currency || data.currency})</span><Input required type="number" min="0.01" step="0.01" value={returnAmount} onChange={(event) => { setReturnAmount(event.target.value); setReturnQuote(null) }} /></label>
            <label className="space-y-1"><span>Referencia</span><Input required maxLength={140} value={returnReference} onChange={(event) => { setReturnReference(event.target.value); setReturnQuote(null) }} /></label>
            <label className="space-y-1"><span>Motivo</span><Input required maxLength={500} value={returnReason} onChange={(event) => { setReturnReason(event.target.value); setReturnQuote(null) }} /></label>
          </div>
          <div className="flex gap-2"><Button disabled={busy}>Revisar devolución</Button><Button type="button" variant="outline" onClick={() => { setReturnPass(""); setReturnQuote(null) }}>Volver</Button></div>
          {returnQuote && <div className="space-y-2 rounded-lg border bg-white p-3"><p>Nota <strong>{returnQuote.document_number}</strong> · factura original {returnQuote.historical_invoice_number}</p><p>Base {returnQuote.base_currency} {returnQuote.net_amount} · Impuesto {returnQuote.base_currency} {returnQuote.tax_amount} · Total {returnQuote.base_currency} {returnQuote.base_amount}</p><p>Reembolso {returnQuote.currency} {returnQuote.amount} · Cambio {returnQuote.exchange_rate}</p><p>Asiento de reembolso: débito {returnQuote.debit}, crédito {returnQuote.credit}. La nota revierte las cuentas históricas de ingreso e impuesto.</p><Button type="button" disabled={busy} onClick={() => void confirmReturn()}>Emitir nota, reembolsar y cancelar</Button></div>}
        </form>}
      </CardContent></Card>}
    </>}
  </div>
}
