import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { availableBillingSections } from "./BillingSections"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Series = { name: string; series_code: string; document_type: "Invoice" | "Credit Note";
  next_number: number; end_number: number; authorization_reference: string }
type Source = { name: string; party: string; party_name: string; folio: string | null; description: string;
  amount: number; net_amount: number; tax_amount: number; tax_treatment: string }
type Fiscal = { name: string; document_type: "Invoice" | "Credit Note"; document_number: string;
  party: string; buyer_name: string; total_amount: number; tax_amount: number; source_invoice: string | null }
type OriginalInvoice = { name: string; document_number: string; party: string;
  buyer_name: string; total_amount: number; business_date: string }
type CandidatePage<T> = { rows: T[]; offset: number; has_more: boolean }
type Snapshot = { currency: string;
  seller_name: string; seller_tax_id: string; tax_regime: string;
  series: Series[]; documents: Fiscal[];
  tax_profiles: { name: string; label: string; treatment: string; rate: number;
    included_in_price: boolean; active: boolean }[];
  liability_accounts: { name: string; account_code: string; account_name: string }[] }
type InvoiceQuote = { series: string; document_number: string; party: string; buyer_name: string;
  currency: string; net_amount: string; tax_amount: string; total_amount: string;
  acceptance: string; lines: { receivable: string; description: string; tax_treatment: string;
    net_amount: string; tax_amount: string; total_amount: string }[] }
type CreditLine = { receivable: string; description: string; net_amount: string;
  tax_amount: string; total_amount: string; remaining_total: string; available: string }
type CreditQuote = { invoice: string; series: string; document_number: string;
  net_amount: string; tax_amount: string; total_amount: string; currency: string;
  lines: CreditLine[]; acceptance: string }
const PAGE_LENGTH = 50

function candidates<T>(property: string, kind: "ready" | "invoices", search: string,
  offset: number) {
  return call<CandidatePage<T>>("pms_fiscal_candidates", {
    property_name: property, kind, search, offset: String(offset),
    page_length: String(PAGE_LENGTH),
  })
}

export function Billing({ property, canSetup, canChart, canApprove }: {
  property: Property; canSetup: boolean; canChart: boolean; canApprove: boolean
}) {
  const send = useIdempotentCommand(property.name)
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableBillingSections(canSetup, canChart, canApprove)
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
  const [seriesCode, setSeriesCode] = useState("")
  const [seriesType, setSeriesType] = useState<"Invoice" | "Credit Note">("Invoice")
  const [start, setStart] = useState("1")
  const [end, setEnd] = useState("")
  const [authorization, setAuthorization] = useState("")
  const [taxLabel, setTaxLabel] = useState("")
  const [treatment, setTreatment] = useState("Taxable")
  const [rate, setRate] = useState("")
  const [included, setIncluded] = useState(false)
  const [taxAccount, setTaxAccount] = useState("")
  const [invoiceSeries, setInvoiceSeries] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [readyQuery, setReadyQuery] = useState("")
  const [readyPage, setReadyPage] = useState<CandidatePage<Source> | null>(null)
  const appliedReadySearch = useRef("")
  const readyOffset = useRef(0)
  const [invoiceQuote, setInvoiceQuote] = useState<InvoiceQuote | null>(null)
  const [creditSeries, setCreditSeries] = useState("")
  const [creditInvoice, setCreditInvoice] = useState("")
  const [invoiceQuery, setInvoiceQuery] = useState("")
  const [invoicePage, setInvoicePage] = useState<CandidatePage<OriginalInvoice> | null>(null)
  const appliedInvoiceSearch = useRef("")
  const invoiceOffset = useRef(0)
  const [creditOptions, setCreditOptions] = useState<CreditLine[] | null>(null)
  const [creditAmounts, setCreditAmounts] = useState<Record<string, string>>({})
  const [creditReason, setCreditReason] = useState("")
  const [creditQuote, setCreditQuote] = useState<CreditQuote | null>(null)

  const refresh = useCallback(async () => {
    const [snapshot, ready, invoices] = await Promise.all([
      call<Snapshot>("pms_fiscal_snapshot", { property_name: property.name }),
      candidates<Source>(property.name, "ready", appliedReadySearch.current,
        readyOffset.current),
      canApprove ? candidates<OriginalInvoice>(property.name, "invoices",
        appliedInvoiceSearch.current, invoiceOffset.current) : Promise.resolve(null),
    ])
    setData(snapshot)
    setReadyPage(ready)
    setInvoicePage(invoices)
  }, [property.name, canApprove])
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el documento.`) }
  }
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setSelected([])
    setReadyPage(null); setInvoicePage(null)
    setReadyQuery(""); setInvoiceQuery("")
    appliedReadySearch.current = ""; readyOffset.current = 0
    appliedInvoiceSearch.current = ""; invoiceOffset.current = 0
    setInvoiceQuote(null); setCreditQuote(null); setCreditInvoice("")
    setCreditOptions(null); setCreditAmounts({})
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar facturación."))
  }, [refresh])
  useEffect(() => {
    if (!creditInvoice) { setCreditOptions(null); setCreditAmounts({}); return }
    let current = true
    call<{ lines: CreditLine[] }>("pms_credit_options",
      { property_name: property.name, invoice: creditInvoice })
      .then((result) => { if (current) { setCreditOptions(result.lines); setCreditAmounts({}) } })
      .catch((issue: unknown) => { if (current) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las líneas de la factura.") })
    return () => { current = false }
  }, [creditInvoice, property.name])
  async function findCandidates(kind: "ready" | "invoices", search: string,
    offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      if (kind === "ready") {
        const page = await candidates<Source>(property.name, kind, search, offset)
        appliedReadySearch.current = search; readyOffset.current = offset
        setReadyPage(page)
      } else {
        const page = await candidates<OriginalInvoice>(property.name, kind, search, offset)
        appliedInvoiceSearch.current = search; invoiceOffset.current = offset
        setInvoicePage(page)
        setCreditInvoice(""); setCreditOptions(null); setCreditAmounts({})
        changeCredit()
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo consultar facturación.") }
    finally { setBusy(false) }
  }
  function changeInvoice() { setInvoiceQuote(null); setError("") }
  function changeCredit() { setCreditQuote(null); setError("") }

  async function createSeries(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canSetup) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_fiscal_series", {
        series_code: seriesCode.trim(), document_type: seriesType,
        start_number: Number(start), end_number: Number(end), padding: Math.max(6, end.length),
        authorization_reference: authorization.trim(),
      })
      setSeriesCode(""); setStart("1"); setEnd(""); setAuthorization("")
      await refreshAfter("Serie registrada para este establecimiento.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear la serie.") }
    finally { setBusy(false) }
  }
  async function createProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canChart) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_tax_profile", {
        label: taxLabel.trim(), treatment, rate: treatment === "Taxable" ? rate : "0",
        included_in_price: included ? 1 : 0,
        liability_account: treatment === "Taxable" ? taxAccount : null,
      })
      setTaxLabel(""); setRate(""); setTaxAccount("")
      await refreshAfter("Perfil tributario guardado. Asígnelo a cada producto antes de contabilizarlo.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el perfil.") }
    finally { setBusy(false) }
  }
  async function invoice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const payload = { series: invoiceSeries, receivables: [...selected].sort() }
    try {
      if (!invoiceQuote) {
        setInvoiceQuote(await call<InvoiceQuote>("pms_invoice_quote",
          { property_name: property.name, data: JSON.stringify(payload) }))
      } else {
        const result = await send<{ document_number: string }>(
          "pms_issue_invoice", { ...payload, acceptance: invoiceQuote.acceptance })
        setSelected([]); setInvoiceQuote(null)
        await refreshAfter(`Factura ${result.document_number} registrada y lista para imprimir.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la factura.") }
    finally { setBusy(false) }
  }
  async function credit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canApprove || !creditOptions) return
    setBusy(true); setError(""); setNotice("")
    const payload = { invoice: creditInvoice, series: creditSeries,
      lines: Object.entries(creditAmounts).filter(([, value]) => Number(value) > 0)
        .map(([receivable, amount]) => ({ receivable, amount })).sort((a, b) => a.receivable.localeCompare(b.receivable)) }
    try {
      if (!creditQuote) {
        setCreditQuote(await call<CreditQuote>("pms_credit_quote",
          { property_name: property.name, data: JSON.stringify(payload) }))
      } else {
        const result = await send<{ document_number: string }>(
          "pms_issue_credit_note", { ...payload, acceptance: creditQuote.acceptance,
            reason: creditReason })
        setCreditQuote(null); setCreditInvoice("")
        setCreditOptions(null); setCreditAmounts({}); setCreditReason("")
        await refreshAfter(`Nota de crédito ${result.document_number} registrada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la nota de crédito.") }
    finally { setBusy(false) }
  }
  const chosenCreditLines = Object.entries(creditAmounts).filter(([, value]) => Number(value) > 0)
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Facturación PMS</h1>
      <p className="mt-2 text-sm text-muted-foreground">{section.label} · {section.description}. Los documentos usan cargos ya contabilizados, sin duplicar sus asientos.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-72 rounded-xl" /> : <>
      {section.id === "identity" && <Card><CardHeader><CardTitle>Identidad fiscal</CardTitle><CardDescription>{data.seller_name} · {data.tax_regime}</CardDescription></CardHeader><CardContent className="space-y-2 text-sm">
        <p>RUC: {data.seller_tax_id || "No registrado"}</p>
        <p>Puede registrar e imprimir documentos aunque no haya RUC o referencia de autorización en la Suite. El usuario del establecimiento debe comprobar el registro y la autorización que le correspondan.</p>
      </CardContent></Card>}
      {((section.id === "profiles" && canChart) || (section.id === "series" && canSetup)) && <div className="max-w-2xl">
        {section.id === "profiles" && canChart && <Card><CardHeader><CardTitle>Perfil tributario</CardTitle><CardDescription>Defina tasa y cuenta de pasivo; los cargos conservarán estos valores aunque cambie la configuración futura.</CardDescription></CardHeader><CardContent><form onSubmit={createProfile} className="grid gap-3">
          <Input required maxLength={140} placeholder="Nombre del perfil" value={taxLabel} onChange={(event) => setTaxLabel(event.target.value)} />
          <select value={treatment} onChange={(event) => setTreatment(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Taxable">Gravado</option><option value="Exempt">Exento</option><option value="Zero Rate">Tasa cero</option><option value="Outside Scope">Fuera de alcance</option></select>
          {treatment === "Taxable" && <><Input required type="number" min="0.000001" max="100" step="0.000001" placeholder="Tasa %" value={rate} onChange={(event) => setRate(event.target.value)} />
            <select required value={taxAccount} onChange={(event) => setTaxAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de impuesto por pagar</option>{data.liability_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select></>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={included} onChange={(event) => setIncluded(event.target.checked)} /> Impuesto incluido en el precio</label>
          <Button disabled={busy}>Crear perfil</Button>
          <p className="text-xs text-muted-foreground">{data.tax_profiles.map((row) => `${row.label} (${row.rate}%)`).join(" · ") || "Sin perfiles tributarios."}</p>
        </form></CardContent></Card>}
        {section.id === "series" && canSetup && <Card><CardHeader><CardTitle>Serie de documentos</CardTitle><CardDescription>Introduzca el rango de numeración. El número siguiente avanza al registrar cada documento.</CardDescription></CardHeader><CardContent><form onSubmit={createSeries} className="grid gap-3 sm:grid-cols-2">
          <select value={seriesType} onChange={(event) => setSeriesType(event.target.value as "Invoice" | "Credit Note")} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Invoice">Factura</option><option value="Credit Note">Nota de crédito</option></select>
          <Input required maxLength={30} placeholder="Prefijo, ej. A-" value={seriesCode} onChange={(event) => setSeriesCode(event.target.value)} />
          <Input required type="number" min="1" step="1" placeholder="Inicio" value={start} onChange={(event) => setStart(event.target.value)} />
          <Input required type="number" min={start || "1"} step="1" placeholder="Final" value={end} onChange={(event) => setEnd(event.target.value)} />
          <Input maxLength={140} placeholder="Referencia de autorización (opcional)" value={authorization} onChange={(event) => setAuthorization(event.target.value)} className="sm:col-span-2" />
          <Button disabled={busy} className="sm:col-span-2">Registrar serie</Button>
        </form></CardContent></Card>}
      </div>}
      {(section.id === "invoices" || section.id === "credits" && canApprove) && <div className="max-w-4xl">
        {section.id === "invoices" && <Card><CardHeader><CardTitle>Registrar factura</CardTitle><CardDescription>Seleccione cargos del mismo cliente y cuenta de estancia. Todos deben tener perfil tributario congelado.</CardDescription></CardHeader><CardContent className="space-y-3">
          <form onSubmit={(event) => { event.preventDefault(); void findCandidates("ready", readyQuery.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar cargo para facturar" placeholder="Cargo, cuenta o cliente" value={readyQuery} onChange={(event) => setReadyQuery(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
          {readyPage && <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Página {Math.floor(readyPage.offset / PAGE_LENGTH) + 1} · {readyPage.rows.length} cargo(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !readyPage.offset} onClick={() => void findCandidates("ready", appliedReadySearch.current, Math.max(0, readyPage.offset - PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !readyPage.has_more} onClick={() => void findCandidates("ready", appliedReadySearch.current, readyPage.offset + PAGE_LENGTH)}>Siguiente</Button></div></div>}
          <form onSubmit={invoice} className="space-y-3">
          <select required value={invoiceSeries} onChange={(event) => { changeInvoice(); setInvoiceSeries(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Serie de factura</option>{data.series.filter((row) => row.document_type === "Invoice" && row.next_number <= row.end_number).map((row) => <option key={row.name} value={row.name}>{row.series_code} · Siguiente {row.next_number}</option>)}</select>
          <div className="max-h-52 space-y-2 overflow-y-auto rounded-lg border p-3">{readyPage?.rows.map((row) => <label key={row.name} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={selected.includes(row.name)} disabled={!selected.includes(row.name) && selected.length >= 100} onChange={(event) => { changeInvoice(); setSelected((current) => event.target.checked ? [...current, row.name] : current.filter((name) => name !== row.name)) }} /><span>{row.party_name} · {row.description} · {data.currency} {row.amount}{row.folio && ` · ${row.folio}`}</span></label>)}{readyPage && !readyPage.rows.length && <p className="text-sm text-muted-foreground">Sin cargos clasificados para esta búsqueda.</p>}</div>
          {!!selected.length && <div className="max-h-28 space-y-1 overflow-y-auto rounded-lg bg-secondary p-3 text-xs"><p>{selected.length} cargo(s) seleccionados. Puede buscar otras páginas del mismo cliente y cuenta de estancia.</p>{selected.map((name) => <div key={name} className="flex items-center justify-between gap-2"><span>{name}</span><Button type="button" size="sm" variant="ghost" onClick={() => { changeInvoice(); setSelected((current) => current.filter((row) => row !== name)) }}>Quitar</Button></div>)}</div>}
          {invoiceQuote && <div className="rounded-lg bg-secondary p-3 text-sm"><strong>{invoiceQuote.document_number}</strong> · {invoiceQuote.buyer_name}<p>Base {data.currency} {invoiceQuote.net_amount} · Impuesto {data.currency} {invoiceQuote.tax_amount} · Total {data.currency} {invoiceQuote.total_amount}</p></div>}
          <Button disabled={busy || !selected.length || !invoiceSeries}>{invoiceQuote ? "Confirmar documento" : "Revisar documento"}</Button>
        </form></CardContent></Card>}
        {section.id === "credits" && canApprove && <Card><CardHeader><CardTitle>Nota de crédito total o parcial</CardTitle><CardDescription>Seleccione cargos e importes pendientes. Los cobros de la porción acreditada deben devolverse primero; cada nota publica su asiento y conserva la factura original.</CardDescription></CardHeader><CardContent className="space-y-3">
          <form onSubmit={(event) => { event.preventDefault(); void findCandidates("invoices", invoiceQuery.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar factura original PMS" placeholder="Factura o cliente" value={invoiceQuery} onChange={(event) => setInvoiceQuery(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
          {invoicePage && <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Página {Math.floor(invoicePage.offset / PAGE_LENGTH) + 1} · {invoicePage.rows.length} factura(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !invoicePage.offset} onClick={() => void findCandidates("invoices", appliedInvoiceSearch.current, Math.max(0, invoicePage.offset - PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !invoicePage.has_more} onClick={() => void findCandidates("invoices", appliedInvoiceSearch.current, invoicePage.offset + PAGE_LENGTH)}>Siguiente</Button></div></div>}
          <form onSubmit={credit} className="space-y-3">
          <select required value={creditInvoice} onChange={(event) => { changeCredit(); setCreditInvoice(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Factura original</option>{invoicePage?.rows.map((row) => <option key={row.name} value={row.name}>{row.document_number} · {row.buyer_name} · {data.currency} {row.total_amount}</option>)}</select>
          <select required value={creditSeries} onChange={(event) => { changeCredit(); setCreditSeries(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Serie de nota de crédito</option>{data.series.filter((row) => row.document_type === "Credit Note" && row.next_number <= row.end_number).map((row) => <option key={row.name} value={row.name}>{row.series_code} · Siguiente {row.next_number}</option>)}</select>
          {creditOptions && <div className="space-y-2 rounded-lg border border-border p-3">{creditOptions.map((row) => <label key={row.receivable} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>{row.description} · Disponible {data.currency} {row.available} de {row.total_amount}</span><Input aria-label={`Acreditar ${row.description}`} type="number" min="0.01" step="0.01" max={row.available} disabled={Number(row.available) <= 0} value={creditAmounts[row.receivable] || ""} onChange={(event) => { changeCredit(); setCreditAmounts((current) => ({ ...current, [row.receivable]: event.target.value })) }} placeholder="Importe a acreditar" className="w-44" /></label>)}<Button type="button" variant="outline" onClick={() => { changeCredit(); setCreditAmounts(Object.fromEntries(creditOptions.filter((row) => Number(row.available) > 0).map((row) => [row.receivable, row.available]))) }}>Usar saldos disponibles</Button></div>}
          <Input required maxLength={500} placeholder="Motivo de la nota" value={creditReason} onChange={(event) => { changeCredit(); setCreditReason(event.target.value) }} />
          {creditQuote && <div className="rounded-lg bg-secondary p-3 text-sm"><strong>{creditQuote.document_number}</strong> · Base {data.currency} {creditQuote.net_amount} · Impuesto {data.currency} {creditQuote.tax_amount} · Total {data.currency} {creditQuote.total_amount}<p className="mt-1">{creditQuote.lines.map((row) => `${row.description}: ${data.currency} ${row.total_amount}`).join(" · ")}</p></div>}
          <Button disabled={busy || !creditInvoice || !creditSeries || !chosenCreditLines.length}>{creditQuote ? "Confirmar nota" : "Revisar nota"}</Button>
        </form></CardContent></Card>}
      </div>}
      {section.id === "documents" && <Card><CardHeader><CardTitle>Documentos registrados</CardTitle><CardDescription>Los 100 más recientes. Consulte e imprima todos en el archivo fiscal.</CardDescription></CardHeader><CardContent className="space-y-2"><Link className="text-sm text-primary underline" to="/fiscal-archive">Abrir archivo fiscal</Link>{data.documents.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{row.document_number}</strong> · {row.document_type === "Invoice" ? "Factura" : "Nota de crédito"} · {row.buyer_name}</span><span>{data.currency} {row.total_amount} · Impuesto {row.tax_amount}</span><a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/printview?doctype=${encodeURIComponent("HS PMS Fiscal Document")}&name=${encodeURIComponent(row.name)}&format=${encodeURIComponent("HS Documento fiscal PMS")}`}>Imprimir</a></div>)}{!data.documents.length && <p className="text-sm text-muted-foreground">Sin documentos registrados.</p>}</CardContent></Card>}
    </>}
  </div>
}
