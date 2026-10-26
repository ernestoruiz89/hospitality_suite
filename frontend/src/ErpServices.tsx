import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { serviceSections } from "./ServiceSections"

type Folio = { name: string; label: string; customer: string; currency: string }
type Stay = { name: string; guest: string; folios: Folio[] }
type Service = { name: string; stay: string; folio: string; item: string;
  quantity: number; included: boolean; amount: number; currency: string;
  status: string; modified: string; charge: string | null; stock_entry: string | null;
  notes: string | null }
type Item = { name: string; item_name: string; display_name?: string; is_stock_item?: boolean }
type Snapshot = { currency: string; stays: Stay[]; requests: Service[];
  items: Item[]; warehouse: string | null }
type Quote = { stay: string; folio: string; customer: string; item: string;
  quantity: string; included: boolean; currency: string; unit_rate: string;
  amount: string; acceptance: string }
const states: Record<string, string> = {
  Requested: "Solicitado", "In Progress": "En preparación", Delivered: "Entregado",
  Cancelled: "Cancelado", Returned: "Devuelto",
}

export function ErpServices({ property, canApprove, canFinance }: { property: Property; canApprove: boolean; canFinance: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = serviceSections.find((item) => item.id === searchParams.get("section")) || serviceSections[0]
  const [data, setData] = useState<Snapshot | null>(null)
  const [stay, setStay] = useState("")
  const [folio, setFolio] = useState("")
  const [item, setItem] = useState("")
  const [itemLabel, setItemLabel] = useState("")
  const [itemQuery, setItemQuery] = useState("")
  const [itemChoices, setItemChoices] = useState<Item[]>([])
  const [quantity, setQuantity] = useState("1")
  const [included, setIncluded] = useState(false)
  const [notes, setNotes] = useState("")
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [requestKey, setRequestKey] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [actionKeys, setActionKeys] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const refresh = useCallback(async () => setData(await call<Snapshot>("erp_service_snapshot",
    { property_name: property.name })), [property.name])
  useEffect(() => {
    if (!searchParams.has("section") || serviceSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", serviceSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    setData(null); setStay(""); setFolio(""); setItem(""); setItemLabel("")
    setItemQuery(""); setItemChoices([]); setQuantity("1"); setIncluded(false)
    setNotes(""); setReasons({}); setRequestKey(""); setQuote(null); setActionKeys({})
    setError(""); setNotice("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los servicios."))
  }, [refresh])
  useEffect(() => {
    if (section.id !== "new") { setItemChoices([]); return }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: Item[] }>("catalog_search", {
        property_name: property.name, txt: itemQuery, purpose: "sale",
      }, controller.signal).then((result) => setItemChoices(result.items)).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el catálogo de artículos.")
      })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [property.name, itemQuery, section.id])
  const selectedStay = data?.stays.find((row) => row.name === stay)
  const selectedItem = itemChoices.find((row) => row.name === item)
  const invalidate = () => { setRequestKey(""); setQuote(null); setError("") }
  const itemName = (name: string) => data?.items.find((row) => row.name === name)?.item_name || name

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await call<Quote>("preview", { property_name: property.name,
        action: "request_service", data: JSON.stringify({ stay, folio, item,
          quantity, included }) })
      setQuote(result); setRequestKey(crypto.randomUUID())
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el importe del servicio.") }
    finally { setBusy(false) }
  }

  async function create() {
    if (!quote || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ service: string; amount: string }>(property.name,
        "request_service", { stay, folio, item, quantity, included,
          notes: notes.trim(), acceptance: quote.acceptance }, requestKey)
      await refresh(); setRequestKey(""); setQuote(null); setQuantity("1"); setNotes("")
      setNotice(`Solicitud ${result.service} registrada por ${quote.currency} ${result.amount}.`)
      setSearchParams({ section: "requests" })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la solicitud.") }
    finally { setBusy(false) }
  }

  async function change(row: Service, status: string) {
    if (busy) return
    const reason = (reasons[row.name] || "").trim()
    if (status === "Returned" && !reason) { setError("Indique el motivo de la devolución."); return }
    setBusy(true); setError(""); setNotice("")
    const action = `${row.name}:${status}`
    const key = actionKeys[action] || crypto.randomUUID()
    setActionKeys((current) => ({ ...current, [action]: key }))
    try {
      await execute(property.name, "update_service", { service: row.name,
        modified: row.modified, status, ...(status === "Returned" ? { reason } : {}) }, key)
      await refresh()
      setActionKeys((current) => { const next = { ...current }; delete next[action]; return next })
      setReasons((current) => ({ ...current, [row.name]: "" }))
      setNotice(`Servicio ${states[status].toLowerCase()}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar el servicio.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">Solicite, prepare y entregue artículos de ERPNext a una estancia. Los cargos entran a la cuenta al entregar; el inventario se descarga del almacén configurado.</p>
      {canFinance && <Button asChild size="sm" variant="outline" className="mt-3"><Link to="/direct-sales?section=new">Venta directa sin estancia</Link></Button>}</div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data && !error && <Skeleton className="h-72 w-full" />}
    {data && <>
      {section.id === "new" && <Card><CardHeader><CardTitle>Nueva solicitud</CardTitle><CardDescription>El precio ERPNext vigente se fija al solicitar; los beneficios incluidos se validan contra la estancia.</CardDescription></CardHeader><CardContent>
        <form onSubmit={review} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Estancia activa</span><select required value={stay} onChange={(event) => { setStay(event.target.value); setFolio(""); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione estancia</option>{data.stays.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.guest}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Cuenta abierta</span><select required value={folio} onChange={(event) => { setFolio(event.target.value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{selectedStay?.folios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.currency}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Buscar artículo</span><Input value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} placeholder="Código o nombre" maxLength={140} /></label>
          <label className="space-y-1 text-sm"><span>Artículo para venta</span><select required value={item} onChange={(event) => { const value = event.target.value; setItem(value); setItemLabel(itemChoices.find((row) => row.name === value)?.display_name || value); invalidate() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione artículo</option>{item && !selectedItem && <option value={item}>{itemLabel || item}</option>}{itemChoices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name} · {row.is_stock_item ? "Inventario" : "Servicio"}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.001" max="10000" step="0.001" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidate() }} /></label>
          <label className="flex items-center gap-2 self-end text-sm"><input type="checkbox" checked={included} onChange={(event) => { setIncluded(event.target.checked); invalidate() }} /> Incluido en la tarifa</label>
          <Input maxLength={500} placeholder="Observaciones (opcional)" value={notes} onChange={(event) => { setNotes(event.target.value); invalidate() }} className="sm:col-span-2" />
          <div className="sm:col-span-2"><Button disabled={busy || !stay || !folio || !item}>Revisar servicio</Button></div>
        </form>
        {quote && <div className="mt-3 space-y-2 rounded-lg bg-secondary p-3 text-sm"><p><strong>{itemLabel || item}</strong> · {quote.quantity} unidad(es) · {quote.included ? "Incluido en tarifa" : `${quote.currency} ${quote.unit_rate} por unidad`}</p><p>Importe antes de impuestos: <strong>{quote.currency} {quote.amount}</strong></p><Button disabled={busy} onClick={() => void create()}>Registrar solicitud</Button></div>}
        {!data.warehouse && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Configure un almacén ERPNext antes de entregar artículos con inventario.</p>}
      </CardContent></Card>}
      {section.id === "requests" && <Card><CardHeader><CardTitle>Solicitudes recientes</CardTitle><CardDescription>La devolución de un cargo facturado requiere primero su nota de crédito. Gerencia autoriza la devolución.</CardDescription></CardHeader><CardContent className="space-y-3">
        {data.requests.map((row) => <div key={row.name} className="rounded-lg border border-border p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><strong>{itemName(row.item)}</strong> · {row.quantity} · {states[row.status] || row.status}<p className="text-xs text-muted-foreground">{row.stay} · {row.folio} · {row.included ? "Incluido" : `${row.currency} ${row.amount}`} {row.notes && `· ${row.notes}`}</p></div><div className="flex flex-wrap gap-2">
          {row.status === "Requested" && <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(row, "In Progress")}>Preparar</Button>}
          {["Requested", "In Progress"].includes(row.status) && <><Button size="sm" disabled={busy} onClick={() => void change(row, "Delivered")}>Entregar</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => void change(row, "Cancelled")}>Cancelar</Button></>}
          {row.status === "Delivered" && canApprove && <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(row, "Returned")}>Devolver</Button>}
        </div></div>{row.status === "Delivered" && canApprove && <Input aria-label={`Motivo de devolución de ${row.name}`} value={reasons[row.name] || ""} onChange={(event) => { setReasons((current) => ({ ...current, [row.name]: event.target.value })); setActionKeys((current) => { const next = { ...current }; delete next[`${row.name}:Returned`]; return next }) }} placeholder="Motivo de devolución" className="mt-2" />}</div>)}
        {!data.requests.length && <p className="text-sm text-muted-foreground">No hay solicitudes registradas.</p>}
        <p className="text-xs text-muted-foreground">Los cargos entregados se facturan desde la cuenta en <Link to="/departures" className="underline">Salidas</Link>.</p>
      </CardContent></Card>}
    </>}
  </div>
}
