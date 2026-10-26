import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { FolioServiceBrowser, type FolioServiceProduct } from "./FolioServiceBrowser"
import { availableFolioSections } from "./FolioSections"

type Folio = {
  name: string
  label: string
  customer: string
  customer_name: string
  currency: string
  status: string
  stay?: string | null
  booking?: string | null
  balance: { pending: string; scheduled: string; outstanding: string }
}
type FolioPage = { rows: Folio[]; selected: Folio | null;
  offset: number; has_more: boolean }
type Account = { name: string; account_code: string; account_name: string }
type Quote = { folio: string; currency: string; total: string; acceptance: string;
  lines: { source_charge: string; description: string; amount: string;
    net_amount: string; tax_amount: string; tax_treatment: string;
    income_account: string; charge_names: string[] }[] }
type ServiceOptions = { stays: { name: string }[] }
type ServiceQuote = { folio: string; stay: string; product: string; product_name: string;
  quantity: string; rate: string; currency: string; price: string;
  net_amount: string; tax_amount: string; total_amount: string;
  tax_treatment: string; acceptance: string }
type AdjustmentOption = { source_charge: string; description: string;
  current_price: string; adjustments: number }
type AdjustmentQuote = { folio: string; source_charge: string; description: string;
  currency: string; amount: string; reason: string; action: "Adjustment" | "Void";
  current_price: string; new_price: string; current_total: string;
  new_net: string; new_tax: string; new_total: string; acceptance: string }

export function Folios({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableFolioSections(canApprove)
  const section = sections.find((item) => item.id === searchParams.get("section")) || sections[0]
  const folio = searchParams.get("folio") || ""
  const [folioPage, setFolioPage] = useState<FolioPage | null>(null)
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [receivableAccount, setReceivableAccount] = useState("")
  const [quote, setQuote] = useState<(Quote & { requestKey: string }) | null>(null)
  const [serviceOptions, setServiceOptions] = useState<ServiceOptions | null>(null)
  const [serviceStay, setServiceStay] = useState("")
  const [serviceProduct, setServiceProduct] = useState("")
  const [selectedService, setSelectedService] = useState<FolioServiceProduct | null>(null)
  const [serviceQuantity, setServiceQuantity] = useState("1")
  const [serviceQuote, setServiceQuote] = useState<(ServiceQuote & { requestKey: string }) | null>(null)
  const [adjustmentOptions, setAdjustmentOptions] = useState<AdjustmentOption[] | null>(null)
  const [sourceCharge, setSourceCharge] = useState("")
  const [adjustmentAmount, setAdjustmentAmount] = useState("")
  const [adjustmentReason, setAdjustmentReason] = useState("")
  const [adjustmentQuote, setAdjustmentQuote] = useState<(AdjustmentQuote & { requestKey: string }) | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const folios = folioPage?.rows || null
  const selected = folioPage?.selected?.name === folio ? folioPage.selected : null
  useEffect(() => {
    if (!searchParams.has("section") || sections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", sections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams, sections])
  function chooseFolio(name: string, targetSection = section.id) {
    const next = new URLSearchParams(searchParams)
    next.set("section", targetSection)
    if (name) next.set("folio", name)
    else next.delete("folio")
    setSearchParams(next)
    setQuote(null); setServiceQuote(null); setServiceOptions(null)
    setAdjustmentQuote(null); setAdjustmentOptions(null); setError("")
  }

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [page, availableAccounts] = await Promise.all([
      call<FolioPage>("pms_folio_page", { property_name: property.name,
        search: appliedSearch, offset: String(offset), page_length: "25",
        selected: folio }, signal),
      call<Account[]>("pms_receivable_accounts", { property_name: property.name }, signal),
    ])
    if (signal?.aborted) return
    setFolioPage(page)
    setAccounts(availableAccounts)
  }, [property.name, folio, appliedSearch, offset, reload])

  useEffect(() => {
    setFolioPage(null); setSearch(""); setAppliedSearch(""); setOffset(0)
    setReceivableAccount(""); setQuote(null)
    setServiceOptions(null); setServiceStay(""); setServiceProduct(""); setSelectedService(null); setServiceQuantity("1"); setServiceQuote(null)
    setAdjustmentOptions(null); setSourceCharge(""); setAdjustmentAmount(""); setAdjustmentReason(""); setAdjustmentQuote(null)
    setError(""); setNotice("")
  }, [property.name])

  useEffect(() => {
    const controller = new AbortController()
    setFolioPage(null)
    refresh(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted)
        setError(issue instanceof Error ? issue.message : "No se pudieron consultar las cuentas.")
    })
    return () => controller.abort()
  }, [refresh])

  function find(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  useEffect(() => {
    if (section.id !== "services" || !selected) { setServiceOptions(null); return }
    let cancelled = false
    setServiceOptions(null); setServiceStay(""); setServiceProduct(""); setSelectedService(null); setServiceQuote(null)
    call<ServiceOptions>("pms_folio_service_options", { property_name: property.name,
      folio, compact: "1" })
      .then((result) => {
        if (cancelled) return
        setServiceOptions(result)
        if (result.stays.length === 1) setServiceStay(result.stays[0].name)
      })
      .catch((issue: unknown) => { if (!cancelled) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los servicios de la cuenta.") })
    return () => { cancelled = true }
  }, [folio, property.name, section.id, selected?.name])

  const refreshAdjustments = useCallback(async (folioName: string) => {
    if (!canApprove || section.id !== "adjustments" || !folioName) return
    const rows = await call<AdjustmentOption[]>("pms_folio_adjustment_options", {
      property_name: property.name, folio: folioName,
    })
    setAdjustmentOptions(rows)
  }, [canApprove, property.name, section.id])

  useEffect(() => {
    if (section.id !== "adjustments" || !canApprove || !selected) { setAdjustmentOptions(null); return }
    let cancelled = false
    setAdjustmentOptions(null); setSourceCharge(""); setAdjustmentAmount(""); setAdjustmentReason(""); setAdjustmentQuote(null)
    call<AdjustmentOption[]>("pms_folio_adjustment_options", {
      property_name: property.name, folio,
    }).then((rows) => { if (!cancelled) setAdjustmentOptions(rows) })
      .catch((issue: unknown) => { if (!cancelled) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los cargos pendientes.") })
    return () => { cancelled = true }
  }, [canApprove, folio, property.name, section.id, selected?.name])

  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const result = await call<Quote>("pms_folio_quote", {
        property_name: property.name,
        data: JSON.stringify({ folio, receivable_account: receivableAccount }),
      })
      if (!result.lines.length) throw new Error("Esta cuenta no tiene cargos pendientes con importe positivo.")
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la cuenta.") }
    finally { setBusy(false) }
  }

  async function bill() {
    if (!quote || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ receivables: { receivable: string }[] }>(
        property.name, "pms_bill_folio",
        { folio: quote.folio, receivable_account: receivableAccount,
          acceptance: quote.acceptance }, quote.requestKey)
      setQuote(null)
      setNotice(`${result.receivables.length} cargo(s) contabilizado(s). Son cuentas internas, no facturas fiscales.`)
      await refresh()
      await refreshAdjustments(quote.folio)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo contabilizar la cuenta.") }
    finally { setBusy(false) }
  }

  async function previewService(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice(""); setServiceQuote(null)
    try {
      const result = await call<ServiceQuote>("pms_folio_service_quote", {
        property_name: property.name,
        data: JSON.stringify({ folio, stay: serviceStay, product: serviceProduct,
          quantity: serviceQuantity }),
      })
      setServiceQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el servicio.") }
    finally { setBusy(false) }
  }

  async function addService() {
    if (!serviceQuote || busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_add_folio_service", {
        folio: serviceQuote.folio, stay: serviceQuote.stay,
        product: serviceQuote.product, quantity: serviceQuote.quantity,
        acceptance: serviceQuote.acceptance,
      }, serviceQuote.requestKey)
      setServiceQuote(null); setServiceQuantity("1")
      setQuote(null); setNotice("Servicio añadido a la cuenta. Revise los cargos antes de contabilizar.")
      await refresh()
      await refreshAdjustments(serviceQuote.folio)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo añadir el servicio.") }
    finally { setBusy(false) }
  }

  async function previewAdjustment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice(""); setAdjustmentQuote(null)
    try {
      const result = await call<AdjustmentQuote>("pms_folio_adjustment_quote", {
        property_name: property.name,
        data: JSON.stringify({ folio, source_charge: sourceCharge,
          amount: adjustmentAmount, reason: adjustmentReason.trim() }),
      })
      setAdjustmentQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el ajuste.") }
    finally { setBusy(false) }
  }

  async function adjust() {
    if (!adjustmentQuote || busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_adjust_folio_charge", {
        folio: adjustmentQuote.folio, source_charge: adjustmentQuote.source_charge,
        amount: adjustmentQuote.amount, reason: adjustmentQuote.reason,
        acceptance: adjustmentQuote.acceptance,
      }, adjustmentQuote.requestKey)
      setQuote(null); setAdjustmentQuote(null); setAdjustmentAmount(""); setAdjustmentReason("")
      if (adjustmentQuote.action === "Void") setSourceCharge("")
      setNotice(adjustmentQuote.action === "Void" ? "Cargo pendiente anulado." : "Ajuste añadido al cargo pendiente.")
      await refresh()
      await refreshAdjustments(adjustmentQuote.folio)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el ajuste.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Cuentas de estancia</h1>
      <p className="mt-1 text-sm text-muted-foreground">{section.label} · {section.description}. La factura numerada se emite en Facturación PMS.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    <form onSubmit={find} className="flex flex-wrap gap-2">
      <Input aria-label="Buscar cuentas de estancia" maxLength={100}
        placeholder="Buscar por cuenta, huésped, reserva o estancia"
        value={search} onChange={(event) => setSearch(event.target.value)}
        className="min-w-56 max-w-xl flex-1" />
      <Button type="submit" variant="outline">Buscar</Button>
    </form>
    {folioPage && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Página {Math.floor(folioPage.offset / 25) + 1} · {folioPage.rows.length} cuenta(s)</span>
      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline" disabled={!folioPage.offset}
          onClick={() => setOffset(Math.max(0, folioPage.offset - 25))}>Anterior</Button>
        <Button type="button" size="sm" variant="outline" disabled={!folioPage.has_more}
          onClick={() => setOffset(folioPage.offset + 25)}>Siguiente</Button>
      </div>
    </div>}
    {!folios && !error && <Skeleton className="h-64 w-full" />}
    {folios && <div className="space-y-5">
      {section.id !== "accounts" && <Card><CardHeader><CardTitle>Cuenta seleccionada</CardTitle><CardDescription>Elija la cuenta que desea gestionar o <Link className="text-primary underline" to={`/folios?section=accounts${folio ? `&folio=${encodeURIComponent(folio)}` : ""}`}>consulte todas las cuentas</Link>.</CardDescription></CardHeader><CardContent>
        <label className="block max-w-2xl space-y-1 text-sm"><span>Cuenta de estancia</span><select value={selected?.name || ""} onChange={(event) => chooseFolio(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione una cuenta</option>{selected && !folios.some((row) => row.name === selected.name) && <option value={selected.name}>{selected.label || selected.name} · {selected.customer_name || selected.customer} · {selected.currency} {selected.balance.outstanding}</option>}{folios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.customer_name || row.customer} · {row.currency} {row.balance.outstanding}</option>)}</select></label>
      </CardContent></Card>}
      {section.id === "accounts" && <Card><CardHeader><CardTitle>Cuentas de estancia</CardTitle><CardDescription>Saldos en la moneda base del establecimiento.</CardDescription></CardHeader>
        <CardContent className="space-y-2">{folios.map((row) => <button key={row.name} type="button" disabled={busy}
          onClick={() => chooseFolio(row.name, "post")}
          className={`w-full rounded-lg border p-3 text-left text-sm hover:bg-muted ${folio === row.name ? "border-primary bg-secondary" : "border-border"}`}>
          <span className="flex justify-between gap-2"><strong>{row.label || row.name}</strong><span>{row.status}</span></span>
          <span className="block text-muted-foreground">{row.name} · {row.customer_name || row.customer}</span>
          <span className="mt-1 block">Pendiente: {row.currency} {row.balance.pending} · Saldo total: {row.currency} {row.balance.outstanding}</span>
        </button>)}{!folios.length && <p className="text-sm text-muted-foreground">Aún no hay cuentas en este establecimiento.</p>}</CardContent></Card>}
      {section.id === "post" && <Card><CardHeader><CardTitle>Contabilizar cargos</CardTitle><CardDescription>Los ajustes se agrupan con su cargo de origen. Se conserva la cuenta de ingresos del producto.</CardDescription></CardHeader>
        <CardContent className="space-y-4">{selected ? <>
          <p className="text-sm"><strong>{selected.name}</strong> · {selected.customer_name}</p>
          <form onSubmit={preview} className="space-y-3">
            <label className="block space-y-1 text-sm"><span>Cuenta por cobrar</span>
              <select required value={receivableAccount} onChange={(event) => { setReceivableAccount(event.target.value); setQuote(null) }}
                className="h-9 w-full rounded-md border border-border bg-white px-2">
                <option value="">Seleccione una cuenta</option>{accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}
              </select></label>
            <Button disabled={busy || selected.status !== "Open" || Number(selected.balance.pending) <= 0}>Revisar asientos</Button>
          </form>
          {quote && <div className="space-y-3 rounded-lg border border-border p-3">
            {quote.lines.map((line) => <div key={line.source_charge} className="flex justify-between gap-3 border-b border-border pb-2 text-sm">
              <span>{line.description}<span className="block text-xs text-muted-foreground">{line.charge_names.length} movimiento(s) · Base {quote.currency} {line.net_amount} · Impuesto {quote.currency} {line.tax_amount} · {line.tax_treatment} · Ingreso: {line.income_account}</span></span>
              <strong className="whitespace-nowrap">{quote.currency} {line.amount}</strong>
            </div>)}
            <p className="text-right text-sm font-semibold">Total: {quote.currency} {quote.total}</p>
            <Button disabled={busy} onClick={bill}>Confirmar contabilización</Button>
          </div>}
        </> : <p className="text-sm text-muted-foreground">Seleccione una cuenta para revisar sus cargos.</p>}</CardContent></Card>}
      {section.id === "services" && <Card><CardHeader><CardTitle>Añadir servicio a la cuenta</CardTitle><CardDescription>El precio sale del catálogo PMS. El impuesto se vuelve a revisar al contabilizar los cargos pendientes.</CardDescription></CardHeader>
        <CardContent className="space-y-3">{selected?.status === "Open" ? serviceOptions ? <>
          <form onSubmit={previewService} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm"><span>Estancia activa</span><select required value={serviceStay} onChange={(event) => { setServiceStay(event.target.value); setServiceQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione una estancia</option>{serviceOptions.stays.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></label>
            <FolioServiceBrowser key={folio} property={property} folio={folio}
              selected={selectedService} onSelect={(row) => {
                setSelectedService(row); setServiceProduct(row?.name || ""); setServiceQuote(null)
              }} />
            <label className="space-y-1 text-sm"><span>Cantidad</span><input required type="number" min="0.001" max="10000" step="0.001" value={serviceQuantity} onChange={(event) => { setServiceQuantity(event.target.value); setServiceQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2" /></label>
            <div className="flex items-end"><Button disabled={busy || !serviceStay || !serviceProduct}>Revisar servicio</Button></div>
          </form>
          {serviceQuote && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3 text-sm"><span><strong>{serviceQuote.product_name}</strong> · {serviceQuote.quantity} × {serviceQuote.currency} {serviceQuote.rate}<span className="block text-muted-foreground">Base {serviceQuote.net_amount} · Impuesto {serviceQuote.tax_amount} · {serviceQuote.tax_treatment}</span></span><span className="font-semibold">Total estimado {serviceQuote.currency} {serviceQuote.total_amount}</span><Button disabled={busy} onClick={addService}>Añadir cargo</Button></div>}
          {!serviceOptions.stays.length && <p className="text-sm text-muted-foreground">Esta cuenta no tiene una estancia activa para el servicio.</p>}
        </> : <Skeleton className="h-24 w-full" /> : <p className="text-sm text-muted-foreground">Seleccione una cuenta abierta para añadir servicios.</p>}</CardContent></Card>}
      {section.id === "adjustments" && canApprove && <Card><CardHeader><CardTitle>Corregir cargo pendiente</CardTitle><CardDescription>Gerencia puede registrar un descuento o recargo con motivo. Si el descuento cubre todo el cargo, se anulan los movimientos pendientes. Un cargo contabilizado requiere cancelación contable o nota de crédito, según su factura y cobros.</CardDescription></CardHeader>
        <CardContent className="space-y-3">{selected?.status === "Open" ? adjustmentOptions ? <>
          <form onSubmit={previewAdjustment} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm"><span>Cargo de origen</span><select required value={sourceCharge} onChange={(event) => { setSourceCharge(event.target.value); setAdjustmentAmount(""); setAdjustmentQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione un cargo</option>{adjustmentOptions.map((row) => <option key={row.source_charge} value={row.source_charge}>{row.description || row.source_charge} · Base {property.currency} {row.current_price}</option>)}</select></label>
            <label className="space-y-1 text-sm"><span>Ajuste con signo</span><input required type="number" step="0.01" value={adjustmentAmount} onChange={(event) => { setAdjustmentAmount(event.target.value); setAdjustmentQuote(null) }} placeholder="-10.00 o 10.00" className="h-9 w-full rounded-md border border-border bg-white px-2" /></label>
            <label className="space-y-1 text-sm"><span>Motivo</span><input required maxLength={500} value={adjustmentReason} onChange={(event) => { setAdjustmentReason(event.target.value); setAdjustmentQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2" /></label>
            <div className="flex items-end gap-2"><Button disabled={busy || !adjustmentOptions.length}>Revisar ajuste</Button><Button type="button" variant="outline" disabled={busy || !sourceCharge} onClick={() => { const row = adjustmentOptions.find((item) => item.source_charge === sourceCharge); if (row) { setAdjustmentAmount(`-${row.current_price}`); setAdjustmentQuote(null) } }}>Anular todo</Button></div>
          </form>
          {adjustmentQuote && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3 text-sm"><span><strong>{adjustmentQuote.action === "Void" ? "Anular" : "Ajustar"}: {adjustmentQuote.description}</strong><span className="block text-muted-foreground">Base anterior {adjustmentQuote.current_price} · Ajuste {adjustmentQuote.amount} · Base nueva {adjustmentQuote.new_price}</span><span className="block text-muted-foreground">Nueva base {adjustmentQuote.new_net} · Impuesto {adjustmentQuote.new_tax}</span></span><strong>Total nuevo {adjustmentQuote.currency} {adjustmentQuote.new_total}</strong><Button disabled={busy} onClick={adjust}>Confirmar {adjustmentQuote.action === "Void" ? "anulación" : "ajuste"}</Button></div>}
          {!adjustmentOptions.length && <p className="text-sm text-muted-foreground">No hay cargos pendientes para corregir.</p>}
        </> : <Skeleton className="h-24 w-full" /> : <p className="text-sm text-muted-foreground">Seleccione una cuenta abierta para corregir cargos pendientes.</p>}</CardContent></Card>}
    </div>}
  </div>
}
