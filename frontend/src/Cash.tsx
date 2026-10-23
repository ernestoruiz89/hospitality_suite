import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Banknote, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type ChartData, type Property } from "./api"

type CashData = {
  base_currency: string
  accepted_currencies: string[]
  methods: { name: string; mode_of_payment: string; account: string; currency: string; is_cash: boolean }[]
  categories: { name: string; label: string; account: string; max_amount: number }[]
  concepts: { name: string; label: string; account: string }[]
  customers: { name: string; party_name: string; tax_id: string }[]
  shifts: { name: string; cashier: string; opened_at: string; expected: Record<string, string> }[]
  movements: { name: string; kind: string; currency: string; amount: number; base_amount: number;
    exchange_rate: number; reference: string; business_date: string; shift: string | null;
    method: string; pms_receivable: string | null; pms_party: string | null }[]
  deposit_accounts: { name: string; account_code: string; account_name: string }[]
  receivables: { name: string; party: string; reference: string; outstanding: string }[]
}
type Quote = { kind: string; amount: string; currency: string; exchange_rate: string; base_amount: string;
  base_currency: string; debit: string; credit: string; exchange_rate_record: string | null }

const KINDS = [
  { value: "Payment", label: "Cobro de cuenta" },
  { value: "Advance", label: "Anticipo de cliente" },
  { value: "Other Income", label: "Otro ingreso" },
  { value: "Expense", label: "Gasto" },
]

export function Cash({ property, canSetup }: { property: Property; canSetup: boolean }) {
  const [snapshot, setSnapshot] = useState<CashData | null>(null)
  const [chart, setChart] = useState<ChartData | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [opening, setOpening] = useState<Record<string, string>>({})
  const [counted, setCounted] = useState<Record<string, string>>({})
  const [kind, setKind] = useState("Advance")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [counter, setCounter] = useState("")
  const [receivable, setReceivable] = useState("")
  const [party, setParty] = useState("")
  const [customerName, setCustomerName] = useState("")
  const [category, setCategory] = useState("")
  const [concept, setConcept] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [requestKey, setRequestKey] = useState("")
  const [setupLabel, setSetupLabel] = useState("")
  const [setupAccount, setSetupAccount] = useState("")
  const [setupKind, setSetupKind] = useState("method")
  const [setupLimit, setSetupLimit] = useState("")

  const refresh = useCallback(async () => {
    const result = await call<CashData>("pms_cash_snapshot", { property_name: property.name })
    setSnapshot(result)
    setOpening((current) => Object.keys(current).length ? current : Object.fromEntries(result.accepted_currencies.map((currency) => [currency, "0"])))
  }, [property.name])
  useEffect(() => {
    setSnapshot(null); setChart(null); setError(""); setNotice("")
    setOpening({}); setCounted({}); setMethod(""); setShift(""); setQuote(null); setRequestKey("")
    setCounter(""); setReceivable(""); setParty(""); setCustomerName(""); setCategory(""); setConcept("")
    refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo consultar Caja."))
    if (canSetup) call<ChartData>("pms_chart", { property_name: property.name }).then(setChart)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo consultar el catálogo."))
  }, [refresh, canSetup])

  const chosenMethod = snapshot?.methods.find((item) => item.name === method)
  const chosenShift = snapshot?.shifts.find((item) => item.name === shift)
  const payload = useMemo(() => ({ kind, amount, method, ...(chosenMethod?.is_cash ? { shift } : {}),
    ...(kind === "Payment" ? { receivable } : kind === "Advance" ? { counter_account: counter, party } : kind === "Expense" ? { category } : { concept }),
    reference, reason }), [kind, amount, method, chosenMethod?.is_cash, shift, counter, receivable, party, category, concept, reference, reason])
  function changed() { setQuote(null); setRequestKey(""); setError(""); setNotice("") }
  async function transact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError("")
    try {
      if (!quote) {
        const result = await call<Quote>("pms_cash_preview", { property_name: property.name, data: JSON.stringify(payload) })
        setQuote(result)
      } else {
        const key = requestKey || crypto.randomUUID()
        setRequestKey(key)
        const result = await execute<{ payment: string }>(property.name, "pms_cash_movement", {
          ...payload, expected_exchange_rate: quote.exchange_rate,
          expected_rate_record: quote.exchange_rate_record,
          expected_debit: quote.debit, expected_credit: quote.credit,
        }, key)
        await refresh()
        setNotice(`Movimiento ${result.payment} contabilizado.`)
        setQuote(null); setRequestKey(""); setAmount(""); setReference(""); setReason("")
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo procesar el movimiento.") }
    finally { setBusy(false) }
  }
  async function openShift() {
    setBusy(true); setError("")
    try {
      const result = await execute<{ shift: string }>(property.name, "pms_open_shift", { opening_by_currency: opening }, crypto.randomUUID())
      await refresh(); setShift(result.shift); setNotice(`Turno ${result.shift} abierto.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo abrir el turno.") }
    finally { setBusy(false) }
  }
  async function closeShift() {
    if (!chosenShift) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_close_shift", { shift: chosenShift.name, counted_by_currency: counted }, crypto.randomUUID())
      await refresh(); setShift(""); setNotice("Turno cerrado y arqueo conciliado.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "El arqueo no coincide.") }
    finally { setBusy(false) }
  }
  async function createSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSetup) return
    setBusy(true); setError("")
    const action = setupKind === "method" ? "pms_payment_method" : setupKind === "category" ? "pms_expense_category" : "pms_income_concept"
    const data = setupKind === "method" ? { label: setupLabel, account: setupAccount } :
      setupKind === "category" ? { label: setupLabel, account: setupAccount, max_amount: setupLimit || "0" } :
      { label: setupLabel, account: setupAccount, nature: "Other Income" }
    try {
      await execute(property.name, action, data, crypto.randomUUID())
      await refresh(); setSetupLabel(""); setSetupAccount(""); setSetupLimit(""); setNotice("Configuración guardada.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo guardar la configuración.") }
    finally { setBusy(false) }
  }
  async function createCustomer() {
    if (!customerName.trim() || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ party: string }>(property.name, "pms_customer",
        { party_name: customerName.trim() }, crypto.randomUUID())
      await refresh(); setParty(result.party); setCustomerName(""); changed()
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo crear el cliente.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="flex items-center gap-3"><Banknote className="text-primary" /><h1 className="text-3xl font-semibold">Caja y movimientos</h1></div><p className="mt-2 text-sm text-muted-foreground">Cobros de cuentas, anticipos, otros ingresos y gastos en las monedas del establecimiento.</p></div><Button variant="outline" onClick={() => refresh()}><RefreshCw size={16} /> Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!snapshot ? <Skeleton className="h-72 rounded-xl" /> : <>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Turno y efectivo esperado</CardTitle><CardDescription>El arqueo conserva cada moneda por separado.</CardDescription></CardHeader><CardContent className="space-y-4">
          {snapshot.shifts.map((item) => <div key={item.name} className="rounded-lg border border-border p-3 text-sm"><strong>{item.name}</strong><span className="ml-2 text-muted-foreground">{item.opened_at}</span><div className="mt-2 flex flex-wrap gap-2">{Object.entries(item.expected).map(([currency, value]) => <Badge key={currency} variant="secondary">{currency} {value}</Badge>)}</div></div>)}
          {!snapshot.shifts.length && <div className="space-y-3"><p className="text-sm text-muted-foreground">Abra un turno para recibir o entregar efectivo.</p>{snapshot.accepted_currencies.map((currency) => <label key={currency} className="flex items-center gap-3 text-sm">{currency}<Input type="number" min="0" step="0.01" value={opening[currency] ?? "0"} onChange={(event) => setOpening((current) => ({ ...current, [currency]: event.target.value }))} className="max-w-36" /></label>)}<Button onClick={openShift} disabled={busy}>Abrir turno</Button></div>}
          {!!snapshot.shifts.length && <div className="space-y-3"><select value={shift} onChange={(event) => { setShift(event.target.value); setCounted({}) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione turno para arquear</option>{snapshot.shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>{chosenShift && <>{Object.keys(chosenShift.expected).map((currency) => <label key={currency} className="flex items-center gap-3 text-sm">Contado {currency}<Input type="number" min="0" step="0.01" value={counted[currency] ?? ""} onChange={(event) => setCounted((current) => ({ ...current, [currency]: event.target.value }))} className="max-w-36" /></label>)}<Button variant="outline" onClick={closeShift} disabled={busy}>Cerrar con arqueo</Button></>}</div>}
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Nuevo movimiento</CardTitle><CardDescription>Revise las cuentas, el tipo de cambio y el importe base antes de contabilizar.</CardDescription></CardHeader><CardContent><form onSubmit={transact} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">Operación<select value={kind} onChange={(event) => { changed(); setKind(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="Payment">Cobro de cuenta</option><option value="Advance">Anticipo de cliente</option><option value="Other Income">Otro ingreso</option><option value="Expense">Gasto</option></select></label>
          <label className="space-y-1 text-sm">Medio<select required value={method} onChange={(event) => { changed(); setMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{snapshot.methods.map((item) => <option key={item.name} value={item.name}>{item.mode_of_payment} · {item.currency}</option>)}</select></label>
          {chosenMethod?.is_cash && <label className="space-y-1 text-sm">Turno<select required value={shift} onChange={(event) => { changed(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno</option>{snapshot.shifts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>}
          {kind === "Advance" && <label className="space-y-1 text-sm">Cuenta de anticipos<select required value={counter} onChange={(event) => { changed(); setCounter(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione pasivo</option>{snapshot.deposit_accounts.map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select></label>}
          {kind === "Payment" && <label className="space-y-1 text-sm sm:col-span-2">Cuenta por cobrar<select required value={receivable} onChange={(event) => { changed(); setReceivable(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta pendiente</option>{snapshot.receivables.filter((item) => Number(item.outstanding) > 0).map((item) => <option key={item.name} value={item.name}>{item.reference} · Saldo {property.currency} {item.outstanding}</option>)}</select></label>}
          {kind === "Advance" && <label className="space-y-1 text-sm">Cliente<select required value={party} onChange={(event) => { changed(); setParty(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cliente</option>{snapshot.customers.map((item) => <option key={item.name} value={item.name}>{item.party_name}</option>)}</select></label>}
          {kind === "Advance" && <div className="flex items-end gap-2"><Input aria-label="Nuevo cliente" maxLength={140} placeholder="Nombre del nuevo cliente" value={customerName} onChange={(event) => setCustomerName(event.target.value)} /><Button type="button" variant="outline" disabled={busy || !customerName.trim()} onClick={createCustomer}>Crear</Button></div>}
          {kind === "Expense" && <label className="space-y-1 text-sm">Categoría<select required value={category} onChange={(event) => { changed(); setCategory(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione categoría</option>{snapshot.categories.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}</select></label>}
          {kind === "Other Income" && <label className="space-y-1 text-sm">Concepto<select required value={concept} onChange={(event) => { changed(); setConcept(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione concepto</option>{snapshot.concepts.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}</select></label>}
          <label className="space-y-1 text-sm">Importe {chosenMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={amount} onChange={(event) => { changed(); setAmount(event.target.value) }} /></label>
          <label className="space-y-1 text-sm">Referencia<Input required maxLength={140} value={reference} onChange={(event) => { changed(); setReference(event.target.value) }} /></label>
          <label className="space-y-1 text-sm sm:col-span-2">Motivo<Input required maxLength={140} value={reason} onChange={(event) => { changed(); setReason(event.target.value) }} /></label>
          {quote && <div className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">{quote.currency} {quote.amount} × {quote.exchange_rate} = <strong>{quote.base_currency} {quote.base_amount}</strong><p className="mt-1 text-xs">Débito: {quote.debit} · Crédito: {quote.credit}</p></div>}
          <Button type="submit" disabled={busy || !snapshot.methods.length} className="sm:col-span-2">{quote ? "Confirmar y contabilizar" : "Revisar asiento"}</Button>
        </form></CardContent></Card>
      </div>
      {canSetup && <Card><CardHeader><CardTitle>Configurar Caja</CardTitle><CardDescription>Cree medios contra cuentas de Caja o banco, categorías de gasto y conceptos de ingreso.</CardDescription></CardHeader><CardContent><form onSubmit={createSetup} className="grid gap-3 sm:grid-cols-4"><select value={setupKind} onChange={(event) => { setSetupKind(event.target.value); setSetupAccount("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="method">Medio de pago</option><option value="category">Categoría de gasto</option><option value="concept">Otro ingreso</option></select><Input required placeholder="Nombre" value={setupLabel} onChange={(event) => setSetupLabel(event.target.value)} /><select required value={setupAccount} onChange={(event) => setSetupAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta contable</option>{chart?.accounts.filter((account) => !account.is_group && account.active && (setupKind === "method" ? (account.is_cash || account.is_bank) : account.root_type === (setupKind === "category" ? "Expense" : "Income") && account.account_currency === property.currency)).map((account) => <option key={account.name} value={account.name}>{account.account_code} · {account.account_name}</option>)}</select>{setupKind === "category" ? <Input type="number" min="0" step="0.01" placeholder="Límite por operación" value={setupLimit} onChange={(event) => setSetupLimit(event.target.value)} /> : <Button type="submit" disabled={busy || !chart}>Crear</Button>}{setupKind === "category" && <Button type="submit" disabled={busy || !chart}>Crear categoría</Button>}</form></CardContent></Card>}
      <Card><CardHeader><CardTitle>Últimos movimientos</CardTitle><CardDescription>Importes originales y equivalentes en {property.currency}.</CardDescription></CardHeader><CardContent className="space-y-2">{snapshot.movements.map((item) => <div key={item.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{KINDS.find((entry) => entry.value === item.kind)?.label || item.kind}</strong><span className="ml-2 text-muted-foreground">{item.reference}{item.pms_receivable && ` · ${snapshot.receivables.find((row) => row.name === item.pms_receivable)?.reference || item.pms_receivable}`}</span></span><span>{item.currency} {item.amount} <span className="text-muted-foreground">· {property.currency} {item.base_amount}</span></span></div>)}{!snapshot.movements.length && <p className="text-sm text-muted-foreground">Sin movimientos.</p>}</CardContent></Card>
    </>}
  </div>
}
