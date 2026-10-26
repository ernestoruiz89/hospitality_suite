import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Banknote, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type ChartData, type Property } from "./api"
import { pmsCashMovementKind, pmsCashSections, pmsCashSetupKind, usePmsCashSection } from "./CashSections"
import { CashRefundSourcePicker, type RefundablePayment } from "./CashRefundSourcePicker"
import { ReceivablePicker, type OpenReceivable } from "./ReceivablePicker"
import { useIdempotentCommand } from "./useIdempotentCommand"

type CashData = {
  base_currency: string
  accepted_currencies: string[]
  methods: { name: string; mode_of_payment: string; account: string; currency: string; is_cash: boolean }[]
  categories: { name: string; label: string; account: string; max_amount: number }[]
  concepts: { name: string; label: string; account: string }[]
  customers: { name: string; party_name: string; tax_id: string }[]
  folios: { name: string; customer: string; label: string }[]
  bookings: { name: string; customer: string; status: string; starts_at: string; hold_until: string | null }[]
  shifts: { name: string; cashier: string; opened_at: string; expected: Record<string, string> }[]
  movements: { name: string; kind: string; currency: string; amount: number; base_amount: number;
    exchange_rate: number; reference: string; business_date: string; shift: string | null;
    method: string; pms_receivable: string | null; pms_party: string | null;
    folio: string | null; booking: string | null }[]
  refundable: RefundablePayment[]
  deposit_accounts: { name: string; account_code: string; account_name: string }[]
  receivables: OpenReceivable[]
}
type Quote = { kind: string; amount: string; currency: string; exchange_rate: string; base_amount: string;
  base_currency: string; debit: string; credit: string; exchange_rate_record: string | null;
  settlement_currency?: string | null; settled_amount?: string | null;
  released_base_amount?: string | null; exchange_variance_base?: string | null }

const KINDS = [
  { value: "Payment", label: "Cobro de cuenta" },
  { value: "Advance", label: "Anticipo de cliente" },
  { value: "Guarantee", label: "Garantía de reserva o cuenta de estancia" },
  { value: "Guarantee Refund", label: "Devolución de garantía" },
  { value: "Other Income", label: "Otro ingreso" },
  { value: "Expense", label: "Gasto" },
]

export function Cash({ property, canSetup, canRefund }: { property: Property; canSetup: boolean; canRefund: boolean }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const section = usePmsCashSection(canRefund, canSetup)
  const requestedFolio = section === "collect" ? searchParams.get("folio") || "" : ""
  const requestedReceivable = section === "collect" ? searchParams.get("receivable") || "" : ""
  const sectionInfo = pmsCashSections.find((item) => item.id === section)!
  const kind = pmsCashMovementKind(section) || "Payment"
  const setupKind = pmsCashSetupKind(section) || "method"
  const [snapshot, setSnapshot] = useState<CashData | null>(null)
  const [chart, setChart] = useState<ChartData | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [opening, setOpening] = useState<Record<string, string>>({})
  const [counted, setCounted] = useState<Record<string, string>>({})
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [counter, setCounter] = useState("")
  const [receivable, setReceivable] = useState("")
  const [selectedReceivable, setSelectedReceivable] = useState<OpenReceivable | null>(null)
  const [settledAmount, setSettledAmount] = useState("")
  const [party, setParty] = useState("")
  const [folio, setFolio] = useState("")
  const [booking, setBooking] = useState("")
  const [guaranteeTarget, setGuaranteeTarget] = useState<"booking" | "folio">("booking")
  const [customerName, setCustomerName] = useState("")
  const [category, setCategory] = useState("")
  const [concept, setConcept] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const send = useIdempotentCommand(property.name)
  const [setupLabel, setSetupLabel] = useState("")
  const [setupAccount, setSetupAccount] = useState("")
  const [setupLimit, setSetupLimit] = useState("")
  const [selectedRefund, setSelectedRefund] = useState<RefundablePayment | null>(null)
  const [refundAmount, setRefundAmount] = useState("")
  const [refundShift, setRefundShift] = useState("")
  const [refundReference, setRefundReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundQuote, setRefundQuote] = useState<Quote | null>(null)
  const appliedCollectContext = useRef("")

  const refresh = useCallback(async () => {
    const result = await call<CashData>("pms_cash_snapshot", {
      property_name: property.name,
      ...(requestedFolio ? { folio: requestedFolio } : {}),
      ...(requestedReceivable ? { receivable: requestedReceivable } : {}),
    })
    setSnapshot(result)
    setOpening((current) => Object.keys(current).length ? current : Object.fromEntries(result.accepted_currencies.map((currency) => [currency, "0"])))
  }, [property.name, requestedFolio, requestedReceivable])
  useEffect(() => {
    setSnapshot(null); setChart(null); setError(""); setNotice("")
    setOpening({}); setCounted({}); setMethod(""); setShift(""); setQuote(null)
    setCounter(""); setReceivable(""); setSelectedReceivable(null); setSettledAmount(""); setParty(""); setFolio(""); setBooking(""); setGuaranteeTarget("booking"); setCustomerName(""); setCategory(""); setConcept("")
    setSelectedRefund(null); setRefundQuote(null)
    refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo consultar Caja."))
    if (canSetup) call<ChartData>("pms_chart", { property_name: property.name }).then(setChart)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo consultar el catálogo."))
  }, [refresh, canSetup])
  useEffect(() => {
    appliedCollectContext.current = ""
    setMethod(""); setShift(""); setCounter(""); setReceivable(""); setSelectedReceivable(null); setSettledAmount("")
    setParty(""); setFolio(""); setBooking(""); setGuaranteeTarget("booking"); setCustomerName("")
    setCategory(""); setConcept(""); setAmount(""); setReference(""); setReason("")
    setQuote(null); setSetupLabel(""); setSetupAccount(""); setSetupLimit("")
    setSelectedRefund(null); setRefundAmount(""); setRefundShift(""); setRefundReference("")
    setRefundReason(""); setRefundQuote(null)
  }, [section])
  useEffect(() => {
    if (!snapshot || section !== "collect" || !(requestedFolio || requestedReceivable)) return
    const context = [property.name, requestedFolio, requestedReceivable].join(":")
    if (appliedCollectContext.current === context) return
    const matches = snapshot.receivables.filter((row) =>
      (!requestedFolio || row.folio === requestedFolio) &&
      (!requestedReceivable || row.name === requestedReceivable))
    if (matches.length === 1) {
      appliedCollectContext.current = context
      setReceivable(matches[0].name)
      setSelectedReceivable(matches[0])
    }
  }, [snapshot, requestedFolio, requestedReceivable, section, property.name])

  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el registro.`) }
  }

  const chosenMethod = snapshot?.methods.find((item) => item.name === method)
  const chosenShift = snapshot?.shifts.find((item) => item.name === shift)
  const countComplete = !!chosenShift && Object.keys(chosenShift.expected).every((currency) =>
    counted[currency] !== undefined && counted[currency] !== "")
  const chosenFolio = snapshot?.folios.find((item) => item.name === folio)
  const chosenBooking = snapshot?.bookings.find((item) => item.name === booking)
  const chosenReceivable = snapshot?.receivables.find((item) => item.name === receivable &&
    (!requestedFolio || item.folio === requestedFolio) &&
    (!requestedReceivable || item.name === requestedReceivable)) ||
    (selectedReceivable?.name === receivable &&
    (!requestedFolio || selectedReceivable.folio === requestedFolio) &&
    (!requestedReceivable || selectedReceivable.name === requestedReceivable) ? selectedReceivable : null)
  const availableReceivables = snapshot?.receivables.filter((item) =>
    Number(item.outstanding) > 0 && (!requestedFolio || item.folio === requestedFolio) &&
    (!requestedReceivable || item.name === requestedReceivable)) || []
  const foreignReceivable = kind === "Payment" && chosenReceivable?.currency !== property.currency && !!chosenReceivable
  const payload = useMemo(() => ({ kind, amount, method, ...(chosenMethod?.is_cash ? { shift } : {}),
    ...(kind === "Payment" ? { receivable, ...(foreignReceivable && settledAmount ? { settled_amount: settledAmount } : {}) } : kind === "Advance" ? { counter_account: counter, party } :
      kind === "Guarantee" ? { counter_account: counter,
        party: guaranteeTarget === "booking" ? chosenBooking?.customer || "" : chosenFolio?.customer || "",
        ...(guaranteeTarget === "booking" ? { booking } : { folio }) } :
      kind === "Expense" ? { category } : { concept }),
    reference, reason }), [kind, amount, method, chosenMethod?.is_cash, shift, counter, receivable, settledAmount, foreignReceivable, party,
      folio, booking, guaranteeTarget, chosenFolio?.customer, chosenBooking?.customer,
      category, concept, reference, reason])
  function changed() { setQuote(null); setError(""); setNotice("") }
  async function transact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (kind === "Payment" && (requestedFolio || requestedReceivable) && !chosenReceivable) {
      setError("La cuenta por cobrar indicada ya no tiene saldo pendiente en este establecimiento.")
      return
    }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!quote) {
        const result = await call<Quote>("pms_cash_preview", { property_name: property.name, data: JSON.stringify(payload) })
        setQuote(result)
      } else {
        const result = await send<{ payment: string }>("pms_cash_movement", {
          ...payload, expected_exchange_rate: quote.exchange_rate,
          expected_rate_record: quote.exchange_rate_record,
          expected_debit: quote.debit, expected_credit: quote.credit,
          ...(quote.settlement_currency ? {
            expected_settled_amount: quote.settled_amount,
            expected_released_base_amount: quote.released_base_amount,
            expected_exchange_variance_base: quote.exchange_variance_base,
          } : {}),
        })
        setQuote(null); setAmount(""); setReference(""); setReason("")
        if (kind === "Payment") { setReceivable(""); setSelectedReceivable(null); setSettledAmount("") }
        await refreshAfter(`Movimiento ${result.payment} contabilizado.`)
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo procesar el movimiento.") }
    finally { setBusy(false) }
  }
  async function openShift() {
    if (busy || snapshot?.shifts.length) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<{ shift: string }>("pms_open_shift", { opening_by_currency: opening })
      setOpening(Object.fromEntries((snapshot?.accepted_currencies || [property.currency]).map((currency) => [currency, "0"])))
      try { await refresh(); setShift(result.shift); setNotice(`Turno ${result.shift} abierto.`) }
      catch { setNotice(`Turno ${result.shift} abierto. Actualice la vista para consultar su saldo.`) }
      navigate("/cash?section=shift-overview")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo abrir el turno.") }
    finally { setBusy(false) }
  }
  async function closeShift() {
    if (!chosenShift || !countComplete || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_close_shift", { shift: chosenShift.name, counted_by_currency: counted })
      setShift(""); setCounted({})
      await refreshAfter("Turno cerrado y arqueo conciliado.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo cerrar el turno.") }
    finally { setBusy(false) }
  }
  async function createSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSetup) return
    setBusy(true); setError(""); setNotice("")
    const action = setupKind === "method" ? "pms_payment_method" : setupKind === "category" ? "pms_expense_category" : "pms_income_concept"
    const data = setupKind === "method" ? { label: setupLabel, account: setupAccount } :
      setupKind === "category" ? { label: setupLabel, account: setupAccount, max_amount: setupLimit || "0" } :
      { label: setupLabel, account: setupAccount, nature: "Other Income" }
    try {
      await send(action, data)
      setSetupLabel(""); setSetupAccount(""); setSetupLimit("")
      await refreshAfter("Configuración guardada.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo guardar la configuración.") }
    finally { setBusy(false) }
  }
  async function createCustomer() {
    if (!customerName.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<{ party: string }>("pms_customer", { party_name: customerName.trim() })
      setParty(result.party); setCustomerName(""); changed()
      await refreshAfter("Cliente creado.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo crear el cliente.") }
    finally { setBusy(false) }
  }
  const refundMethod = snapshot?.methods.find((item) => item.name === selectedRefund?.method)
  function refundChanged() { setRefundQuote(null); setError(""); setNotice("") }
  async function submitRefund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canRefund) return
    setBusy(true); setError(""); setNotice("")
    const data = { source_payment: selectedRefund?.name || "", amount: refundAmount,
      ...(refundMethod?.is_cash ? { shift: refundShift } : {}),
      reference: refundReference, reason: refundReason }
    try {
      if (!refundQuote) {
        setRefundQuote(await call<Quote>("pms_refund_preview",
          { property_name: property.name, data: JSON.stringify(data) }))
      } else {
        const result = await send<{ payment: string }>("pms_refund",
          { ...data, expected_base_amount: refundQuote.base_amount,
            expected_debit: refundQuote.debit, expected_credit: refundQuote.credit,
            ...(refundQuote.settlement_currency ? {
              expected_settled_amount: refundQuote.settled_amount,
              expected_released_base_amount: refundQuote.released_base_amount,
              expected_exchange_variance_base: refundQuote.exchange_variance_base,
            } : {}) })
        setRefundQuote(null); setSelectedRefund(null)
        setRefundAmount(""); setRefundReference(""); setRefundReason("")
        await refreshAfter(`Devolución ${result.payment} contabilizada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el pago.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-medium text-primary">Caja PMS</p><div className="mt-1 flex items-center gap-3"><Banknote className="text-primary" /><h1 className="text-3xl font-semibold">{sectionInfo.label}</h1></div><p className="mt-2 text-sm text-muted-foreground">{`${sectionInfo.description}.`}</p></div><Button variant="outline" onClick={() => refresh()}><RefreshCw size={16} /> Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!snapshot ? <Skeleton className="h-72 rounded-xl" /> : <>
      <div className="space-y-5">
        {section === "shift-overview" && <Card><CardHeader><CardTitle>Turnos abiertos</CardTitle><CardDescription>El efectivo esperado se conserva por moneda.</CardDescription></CardHeader><CardContent className="space-y-4">
          {snapshot.shifts.map((item) => <div key={item.name} className="rounded-lg border border-border p-3 text-sm"><strong>{item.name}</strong><span className="ml-2 text-muted-foreground">{item.opened_at}</span><div className="mt-2 flex flex-wrap gap-2">{Object.entries(item.expected).map(([currency, value]) => <Badge key={currency} variant="secondary">{currency} {value}</Badge>)}</div></div>)}
          {!snapshot.shifts.length && <p className="text-sm text-muted-foreground">No hay un turno abierto. Use “Abrir turno” para declarar el efectivo inicial.</p>}
        </CardContent></Card>}
        {section === "shift-open" && <Card><CardHeader><CardTitle>Abrir turno</CardTitle><CardDescription>Declare el efectivo inicial de cada moneda habilitada. Solo puede mantener un turno propio abierto.</CardDescription></CardHeader><CardContent className="space-y-3">
          {snapshot.shifts.length ? <p className="text-sm text-muted-foreground">Ya tiene un turno abierto. Ciérrelo antes de abrir otro.</p> : <form onSubmit={(event) => { event.preventDefault(); void openShift() }} className="space-y-3">{snapshot.accepted_currencies.map((currency) => <label key={currency} className="flex items-center gap-3 text-sm">{currency}<Input required type="number" min="0" step="0.01" value={opening[currency] ?? "0"} onChange={(event) => setOpening((current) => ({ ...current, [currency]: event.target.value }))} className="max-w-36" /></label>)}<Button disabled={busy}>Abrir turno</Button></form>}
        </CardContent></Card>}
        {section === "shift-close" && <Card><CardHeader><CardTitle>Arqueo y cierre</CardTitle><CardDescription>Cuente cada moneda del turno. Una diferencia debe resolverse antes de cerrar.</CardDescription></CardHeader><CardContent className="space-y-3">
          <select aria-label="Turno abierto propio" value={shift} onChange={(event) => { setShift(event.target.value); setCounted({}) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto propio</option>{snapshot.shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
          {chosenShift && <form onSubmit={(event) => { event.preventDefault(); void closeShift() }} className="space-y-3">{Object.entries(chosenShift.expected).map(([currency, expected]) => <label key={currency} className="flex items-center gap-3 text-sm">Contado {currency} · Esperado {expected}<Input required type="number" min="0" step="0.01" value={counted[currency] ?? ""} onChange={(event) => setCounted((current) => ({ ...current, [currency]: event.target.value }))} className="max-w-36" /></label>)}<Button variant="outline" disabled={busy || !countComplete}>Cerrar con arqueo</Button></form>}
          {!snapshot.shifts.length && <p className="text-sm text-muted-foreground">No hay un turno abierto para arquear.</p>}
        </CardContent></Card>}
        {pmsCashMovementKind(section) && <Card><CardHeader><CardTitle>{sectionInfo.label}</CardTitle><CardDescription>Revise las cuentas, el tipo de cambio y el importe base antes de contabilizar.</CardDescription></CardHeader><CardContent><form onSubmit={transact} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">Medio<select required value={method} onChange={(event) => { changed(); setMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{snapshot.methods.map((item) => <option key={item.name} value={item.name}>{item.mode_of_payment} · {item.currency}</option>)}</select></label>
          {chosenMethod?.is_cash && <label className="space-y-1 text-sm">Turno<select required value={shift} onChange={(event) => { changed(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno</option>{snapshot.shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>}
          {(kind === "Advance" || kind === "Guarantee") && <label className="space-y-1 text-sm">Cuenta de depósitos<select required value={counter} onChange={(event) => { changed(); setCounter(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione pasivo</option>{snapshot.deposit_accounts.map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select></label>}
          {kind === "Payment" && (requestedReceivable ?
            <label className="space-y-1 text-sm sm:col-span-2">Cuenta por cobrar<select required value={receivable} onChange={(event) => { changed(); const chosen = availableReceivables.find((item) => item.name === event.target.value) || null; setReceivable(chosen?.name || ""); setSelectedReceivable(chosen); setSettledAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta pendiente</option>{availableReceivables.map((item) => <option key={item.name} value={item.name}>{item.reference} · Saldo {item.currency} {item.outstanding}</option>)}</select></label> :
            <div className="space-y-1 text-sm sm:col-span-2"><span>Cuenta por cobrar</span><ReceivablePicker property={property} selected={chosenReceivable || null}
              onSelect={(item) => { changed(); setReceivable(item?.name || ""); setSelectedReceivable(item); setSettledAmount("") }}
              folio={requestedFolio} refreshToken={snapshot} label="Seleccione cuenta pendiente" /></div>)}
          {kind === "Payment" && requestedReceivable && <div className="text-sm sm:col-span-2">
            <p>Cuenta por cobrar: <strong>{availableReceivables[0]?.reference || requestedReceivable}</strong></p>
            {!availableReceivables.length && <p className="mt-1 text-muted-foreground">Esta cuenta ya no tiene saldo pendiente o no pertenece al establecimiento. <Link className="text-primary underline" to="/receivables?section=balances">Ver saldos pendientes</Link></p>}
          </div>}
          {kind === "Payment" && requestedFolio && <div className="text-sm sm:col-span-2">
            <p>Cuenta de estancia: <strong>{snapshot.folios.find((item) => item.name === requestedFolio)?.label || requestedFolio}</strong></p>
            {!availableReceivables.length && <p className="mt-1 text-muted-foreground">No hay cargos contabilizados pendientes de cobro para esta cuenta. <Link className="text-primary underline" to={"/folios?section=post&folio=" + encodeURIComponent(requestedFolio)}>Revisar cargos</Link></p>}
          </div>}
          {kind === "Advance" && <label className="space-y-1 text-sm">Cliente<select required value={party} onChange={(event) => { changed(); setParty(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cliente</option>{snapshot.customers.map((item) => <option key={item.name} value={item.name}>{item.party_name}</option>)}</select></label>}
          {kind === "Advance" && <div className="flex items-end gap-2"><Input aria-label="Nuevo cliente" maxLength={140} placeholder="Nombre del nuevo cliente" value={customerName} onChange={(event) => setCustomerName(event.target.value)} /><Button type="button" variant="outline" disabled={busy || !customerName.trim()} onClick={createCustomer}>Crear</Button></div>}
          {kind === "Guarantee" && <><label className="space-y-1 text-sm">Origen<select value={guaranteeTarget} onChange={(event) => { changed(); setGuaranteeTarget(event.target.value as "booking" | "folio"); setFolio(""); setBooking("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="booking">Reserva</option><option value="folio">Cuenta de estancia</option></select></label>{guaranteeTarget === "booking" ? <label className="space-y-1 text-sm sm:col-span-2">Reserva del huésped<select required value={booking} onChange={(event) => { changed(); setBooking(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione reserva vigente</option>{snapshot.bookings.map((item) => <option key={item.name} value={item.name}>{item.name} · {snapshot.customers.find((customer) => customer.name === item.customer)?.party_name || item.customer} · {item.status}</option>)}</select></label> : <label className="space-y-1 text-sm sm:col-span-2">Cuenta del huésped<select required value={folio} onChange={(event) => { changed(); setFolio(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta abierta</option>{snapshot.folios.map((item) => <option key={item.name} value={item.name}>{item.label} · {snapshot.customers.find((customer) => customer.name === item.customer)?.party_name || item.customer} · {item.name}</option>)}</select></label>}</>}
          {kind === "Expense" && <label className="space-y-1 text-sm">Categoría<select required value={category} onChange={(event) => { changed(); setCategory(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione categoría</option>{snapshot.categories.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}</select></label>}
          {kind === "Other Income" && <label className="space-y-1 text-sm">Concepto<select required value={concept} onChange={(event) => { changed(); setConcept(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione concepto</option>{snapshot.concepts.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}</select></label>}
          <label className="space-y-1 text-sm">Importe {chosenMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={amount} onChange={(event) => { changed(); setAmount(event.target.value) }} /></label>
          {foreignReceivable && <label className="space-y-1 text-sm">Principal liquidado {chosenReceivable?.currency}<Input type="number" min="0.01" step="0.01" max={chosenReceivable?.outstanding} required={chosenMethod?.currency !== chosenReceivable?.currency} placeholder={chosenMethod?.currency === chosenReceivable?.currency ? "Igual al cobro si se deja vacío" : "Importe en la moneda de la deuda"} value={settledAmount} onChange={(event) => { changed(); setSettledAmount(event.target.value) }} /></label>}
          <label className="space-y-1 text-sm">Referencia<Input required maxLength={140} value={reference} onChange={(event) => { changed(); setReference(event.target.value) }} /></label>
          <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required maxLength={140} value={reason} onChange={(event) => { changed(); setReason(event.target.value) }} /></label>
          {quote && <div className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">{quote.currency} {quote.amount} × {quote.exchange_rate} = <strong>{quote.base_currency} {quote.base_amount}</strong>{quote.settlement_currency && <p className="mt-2">Principal {quote.settlement_currency} {quote.settled_amount} · Valor contable liberado {quote.base_currency} {quote.released_base_amount} · Diferencia cambiaria {quote.base_currency} {quote.exchange_variance_base}</p>}<p className="mt-1 text-xs">Débito: {quote.debit} · Crédito: {quote.credit}</p></div>}
          <Button type="submit" disabled={busy || !snapshot.methods.length} className="sm:col-span-2">{quote ? "Confirmar y contabilizar" : "Revisar asiento"}</Button>
        </form></CardContent></Card>}
      </div>
      {pmsCashSetupKind(section) && canSetup && <Card><CardHeader><CardTitle>{sectionInfo.label}</CardTitle><CardDescription>{sectionInfo.description}.</CardDescription></CardHeader><CardContent><form onSubmit={createSetup} className="grid gap-3 sm:grid-cols-3"><Input required placeholder="Nombre" value={setupLabel} onChange={(event) => setSetupLabel(event.target.value)} /><select required value={setupAccount} onChange={(event) => setSetupAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta contable</option>{chart?.accounts.filter((account) => !account.is_group && account.active && (setupKind === "method" ? (account.is_cash || account.is_bank) : account.root_type === (setupKind === "category" ? "Expense" : "Income") && account.account_currency === property.currency)).map((account) => <option key={account.name} value={account.name}>{account.account_code} · {account.account_name}</option>)}</select>{setupKind === "category" && <Input type="number" min="0" step="0.01" placeholder="Límite por operación" value={setupLimit} onChange={(event) => setSetupLimit(event.target.value)} />}<Button type="submit" disabled={busy || !chart}>Crear {setupKind === "method" ? "medio" : setupKind === "category" ? "categoría" : "concepto"}</Button></form></CardContent></Card>}
      {section === "refunds" && canRefund && <Card><CardHeader><CardTitle>Devolver cobro, anticipo o garantía</CardTitle><CardDescription>La devolución conserva el movimiento original y publica el asiento contrario en su misma moneda.</CardDescription></CardHeader><CardContent><form onSubmit={submitRefund} className="grid gap-3 sm:grid-cols-2">
        <CashRefundSourcePicker property={property} selected={selectedRefund} refreshToken={snapshot}
          onSelect={(payment) => { refundChanged(); setSelectedRefund(payment); setRefundAmount("") }} />
        {refundMethod?.is_cash && <select required value={refundShift} onChange={(event) => { refundChanged(); setRefundShift(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto</option>{snapshot.shifts.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.expected[refundMethod.currency] || "0.00"} {refundMethod.currency}</option>)}</select>}
        <Input required type="number" min="0.01" step="0.01" max={selectedRefund?.remaining_amount} placeholder={`Importe ${selectedRefund?.currency || ""}`} value={refundAmount} onChange={(event) => { refundChanged(); setRefundAmount(event.target.value) }} />
        <Input required maxLength={140} placeholder="Referencia de devolución" value={refundReference} onChange={(event) => { refundChanged(); setRefundReference(event.target.value) }} />
        <Input required maxLength={140} placeholder="Motivo" value={refundReason} onChange={(event) => { refundChanged(); setRefundReason(event.target.value) }} />
        {refundQuote && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">{refundQuote.currency} {refundQuote.amount} · {property.currency} {refundQuote.base_amount}<br />Débito: {refundQuote.debit} · Crédito: {refundQuote.credit}{refundQuote.settlement_currency && <><br />Principal restaurado: {refundQuote.settlement_currency} {refundQuote.settled_amount} · Valor base: {property.currency} {refundQuote.released_base_amount} · Cambio revertido: {property.currency} {refundQuote.exchange_variance_base}</>}</p>}
        <Button disabled={busy || !selectedRefund} className="sm:col-span-2">{refundQuote ? "Confirmar devolución" : "Revisar asiento"}</Button>
      </form></CardContent></Card>}
      {section === "history" && <Card><CardHeader><CardTitle>Últimos movimientos</CardTitle><CardDescription>Importes originales y equivalentes en {property.currency}.</CardDescription></CardHeader><CardContent className="space-y-2">{snapshot.movements.map((item) => <div key={item.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{KINDS.find((entry) => entry.value === item.kind)?.label || item.kind}</strong><span className="ml-2 text-muted-foreground">{item.reference}{item.folio && ` · ${item.folio}`}{item.booking && ` · ${item.booking}`}{item.pms_receivable && ` · ${snapshot.receivables.find((row) => row.name === item.pms_receivable)?.reference || item.pms_receivable}`}</span></span><span>{item.currency} {item.amount} <span className="text-muted-foreground">· {property.currency} {item.base_amount}</span></span></div>)}{!snapshot.movements.length && <p className="text-sm text-muted-foreground">Sin movimientos.</p>}</CardContent></Card>}
    </>}
  </div>
}
