import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { serviceSections } from "./ServiceSections"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Folio = { name: string; label: string; customer: string }
type Stay = { name: string; guest: string; folios: Folio[] }
type Product = { name: string; product_name: string; product_type: "Service" | "Stock";
  sales_rate: number }
type Service = { name: string; stay: string; folio: string; item: string; warehouse?: string;
  quantity: number; included: boolean; amount: number; currency: string; status: string;
  modified: string; charge?: string; stock_entry?: string; return_stock_entry?: string; notes?: string }
type Snapshot = { currency: string; stays: Stay[]; products: Product[];
  warehouses: { name: string; warehouse_name: string }[];
  balances: { product: string; warehouse: string; quantity: number }[]; requests: Service[] }
type Quote = { currency: string; amount: string; net: string; tax: string; total: string;
  included_in_price: boolean; acceptance: string }

const states: Record<string, string> = {
  Requested: "Solicitado", "In Progress": "En preparación", Delivered: "Entregado",
  Cancelled: "Cancelado", Returned: "Devuelto",
}

export function Services({ property, canApprove, canSetup }: { property: Property; canApprove: boolean; canSetup: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = serviceSections.find((item) => item.id === searchParams.get("section")) || serviceSections[0]
  const [data, setData] = useState<Snapshot | null>(null)
  const [stay, setStay] = useState("")
  const [folio, setFolio] = useState("")
  const [product, setProduct] = useState("")
  const [warehouse, setWarehouse] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [included, setIncluded] = useState(false)
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const reviewVersion = useRef(0)
  const snapshotVersion = useRef(0)
  const currentProperty = useRef(property.name)
  currentProperty.current = property.name
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const send = useIdempotentCommand(property.name)
  const refresh = useCallback(async () => {
    const version = ++snapshotVersion.current
    const result = await call<Snapshot>("pms_service_snapshot", { property_name: property.name })
    if (currentProperty.current === property.name && version === snapshotVersion.current)
      setData(result)
    return result
  }, [property.name])
  useEffect(() => {
    if (!searchParams.has("section") || serviceSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", serviceSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    snapshotVersion.current += 1
    const requestedProperty = property.name
    setData(null); setStay(""); setFolio(""); setProduct(""); setWarehouse("");
    setQuantity("1"); setIncluded(false); setNotes(""); setQuote(null);
    reviewVersion.current += 1; setReasons({}); setError(""); setNotice("")
    refresh().catch((issue: unknown) => {
      if (currentProperty.current === requestedProperty)
        setError(issue instanceof Error ? issue.message : "No se pudieron consultar los servicios.")
    })
  }, [refresh, property.name])
  const selectedStay = data?.stays.find((row) => row.name === stay)
  const selectedProduct = data?.products.find((row) => row.name === product)
  const available = useMemo(() => data?.balances.find((row) =>
    row.product === product && row.warehouse === warehouse)?.quantity || 0,
  [data, product, warehouse])
  const invalidateQuote = () => { reviewVersion.current += 1; setQuote(null); setError("") }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const version = ++reviewVersion.current
    const request = { stay, folio, item: product,
      warehouse: selectedProduct?.product_type === "Stock" ? warehouse : null,
      quantity, included, notes: notes.trim() }
    try {
      if (!quote) {
        const reviewed = await call<Quote>("preview", { property_name: property.name,
          action: "request_service", data: JSON.stringify(request) })
        if (version === reviewVersion.current && currentProperty.current === property.name)
          setQuote(reviewed)
      } else {
        await send("request_service", { ...request, acceptance: quote.acceptance })
        if (version !== reviewVersion.current || currentProperty.current !== property.name) return
        setQuote(null); setQuantity("1"); setNotes(""); setNotice("Solicitud registrada.")
        setSearchParams({ section: "requests" })
        try { await refresh() }
        catch {
          if (currentProperty.current === property.name)
            setError("La solicitud se registró, pero la lista no se actualizó. Recargue Servicios.")
        }
      }
    } catch (issue) {
      if (version === reviewVersion.current && currentProperty.current === property.name)
        setError(issue instanceof Error ? issue.message : "No se pudo registrar la solicitud.")
    }
    finally { setBusy(false) }
  }

  async function change(row: Service, status: string) {
    if (busy) return
    if (status === "Returned" && (reasons[row.name] || "").trim().length < 3) {
      setError("Indique el motivo de la devolución."); return
    }
    setBusy(true); setError(""); setNotice("")
    const operationProperty = property.name
    try {
      await send("update_service", {
        service: row.name, modified: row.modified, status,
        ...(status === "Returned" ? { reason: reasons[row.name].trim() } : {}),
      })
      if (currentProperty.current !== operationProperty) return
      setReasons((current) => ({ ...current, [row.name]: "" }));
      setNotice(`Servicio ${states[status].toLowerCase()}.`)
      try { await refresh() }
      catch {
        if (currentProperty.current === operationProperty)
          setError("El servicio se actualizó, pero la lista no se refrescó. Recargue Servicios.")
      }
    } catch (issue) {
      if (currentProperty.current === operationProperty)
        setError(issue instanceof Error ? issue.message : "No se pudo actualizar el servicio.")
    }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">Solicite, prepare, entregue y devuelva servicios de estancias activas. Los cargos entran a la cuenta al entregar; los productos con inventario registran su costo.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data && !error && <Skeleton className="h-72 w-full" />}
    {data && <>
      {section.id === "new" && <Card><CardHeader><CardTitle>Nueva solicitud</CardTitle><CardDescription>Los beneficios incluidos se descuentan de la estancia. El precio del producto se fija al solicitar.</CardDescription></CardHeader>
        <CardContent><form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
          <select required disabled={busy} value={stay} onChange={(event) => { setStay(event.target.value); setFolio(""); invalidateQuote() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Estancia activa</option>{data.stays.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.guest}</option>)}</select>
          <select required disabled={busy} value={folio} onChange={(event) => { setFolio(event.target.value); invalidateQuote() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta abierta</option>{selectedStay?.folios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name}</option>)}</select>
          <select required disabled={busy} value={product} onChange={(event) => { setProduct(event.target.value); setWarehouse(""); invalidateQuote() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto</option>{data.products.map((row) => <option key={row.name} value={row.name}>{row.product_name} · {row.product_type === "Stock" ? "Inventario" : "Servicio"}</option>)}</select>
          <Input required disabled={busy} aria-label="Cantidad" type="number" min="0.001" max="10000" step="0.001" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidateQuote() }} />
          {selectedProduct?.product_type === "Stock" && <select required disabled={busy} value={warehouse} onChange={(event) => { setWarehouse(event.target.value); invalidateQuote() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>}
          {selectedProduct?.product_type === "Stock" && warehouse && <p className="self-center text-sm text-muted-foreground">Existencia disponible: {available}</p>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={busy} checked={included} onChange={(event) => { setIncluded(event.target.checked); invalidateQuote() }} /> Incluido en la tarifa</label>
          <Input disabled={busy} maxLength={500} placeholder="Observaciones (opcional)" value={notes} onChange={(event) => { setNotes(event.target.value); invalidateQuote() }} className="sm:col-span-2" />
          {quote && <div className="space-y-1 rounded-lg bg-secondary p-3 text-sm sm:col-span-2">
            {included ? <p>Incluido en la tarifa · Total {quote.currency} {quote.total}</p> : <>
              <p>Base {quote.currency} {quote.net} · Impuesto {quote.currency} {quote.tax}</p>
              <p>Total a la cuenta <strong>{quote.currency} {quote.total}</strong>{quote.included_in_price ? " · Impuesto incluido" : ""}</p>
            </>}
          </div>}
          <Button disabled={busy || !stay || !folio || !product} className="sm:col-span-2">{quote ? "Registrar solicitud" : "Revisar solicitud"}</Button>
        </form>{canSetup && <p className="mt-3 text-xs text-muted-foreground">Configure precios y perfiles tributarios en <Link to="/products" className="text-primary underline">Productos PMS</Link>.</p>}</CardContent></Card>}
      {section.id === "requests" && <Card><CardHeader><CardTitle>Solicitudes recientes</CardTitle><CardDescription>La entrega de inventario requiere existencias y cuenta de costo configuradas.</CardDescription></CardHeader><CardContent className="space-y-3">
        {data.requests.map((row) => <div key={row.name} className="rounded-lg border border-border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><strong>{data.products.find((item) => item.name === row.item)?.product_name || row.item}</strong> · {row.quantity} · {states[row.status] || row.status}<p className="text-xs text-muted-foreground">{row.stay} · {row.folio} · {row.included ? "Incluido" : `${row.currency} ${row.amount}`} {row.notes && `· ${row.notes}`}</p></div><div className="flex flex-wrap gap-2">
            {row.status === "Requested" && <Button variant="outline" size="sm" disabled={busy} onClick={() => change(row, "In Progress")}>Preparar</Button>}
            {["Requested", "In Progress"].includes(row.status) && <><Button size="sm" disabled={busy} onClick={() => change(row, "Delivered")}>Entregar</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => change(row, "Cancelled")}>Cancelar</Button></>}
            {row.status === "Delivered" && canApprove && <Button variant="outline" size="sm" disabled={busy} onClick={() => change(row, "Returned")}>Devolver</Button>}
          </div></div>
          {row.status === "Delivered" && canApprove && <Input aria-label={`Motivo de devolución de ${row.name}`} value={reasons[row.name] || ""} onChange={(event) => setReasons((current) => ({ ...current, [row.name]: event.target.value }))} placeholder="Motivo para devolver (Gerencia)" className="mt-2" />}
        </div>)}{!data.requests.length && <p className="text-sm text-muted-foreground">No hay solicitudes registradas.</p>}
      </CardContent></Card>}
    </>}
  </div>
}
