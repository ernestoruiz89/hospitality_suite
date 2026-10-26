import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Folio = { name: string; label: string; currency?: string }
type Stay = { name: string; folios: Folio[] }
type Request = { name: string; stay: string; folio: string; item: string; quantity: number;
  status: string; modified: string; charge?: string | null }
type Product = { name: string; product_name: string; product_type: "Stock" | "Service";
  sales_rate: number }
type Item = { name: string; item_name: string; display_name?: string; is_stock_item?: boolean }
type Snapshot = { currency: string; stays: Stay[]; requests: Request[];
  products?: Product[]; warehouses?: { name: string; warehouse_name: string }[];
  balances?: { product: string; warehouse: string; quantity: number }[];
  warehouse?: string | null }
type Quote = { currency: string; unit_rate: string; amount: string; acceptance: string;
  net?: string; tax?: string; total?: string; included_in_price?: boolean }

export function RoomServiceAction({ property, stay, provider, roomNumber, onAccountChanged, initialOpen = false }: {
  property: Property; stay: string; provider: "pms" | "erpnext"; roomNumber: string;
  onAccountChanged: () => Promise<void>; initialOpen?: boolean
}) {
  const [open, setOpen] = useState(initialOpen)
  const [data, setData] = useState<Snapshot | null>(null)
  const [folio, setFolio] = useState("")
  const [item, setItem] = useState("")
  const [itemLabel, setItemLabel] = useState("")
  const [itemQuery, setItemQuery] = useState("")
  const [choices, setChoices] = useState<Item[]>([])
  const [warehouse, setWarehouse] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [pendingService, setPendingService] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const reviewVersion = useRef(0)
  const send = useIdempotentCommand(property.name)

  useEffect(() => { reviewVersion.current += 1; setQuote(null) }, [property.name, stay])
  useEffect(() => { if (initialOpen) setOpen(true) }, [initialOpen])

  const refresh = useCallback(async () => {
    const result = await call<Snapshot>(provider === "pms" ? "pms_service_snapshot" : "erp_service_snapshot",
      { property_name: property.name, stay })
    setData(result)
    return result
  }, [property.name, provider, stay])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    call<Snapshot>(provider === "pms" ? "pms_service_snapshot" : "erp_service_snapshot",
      { property_name: property.name, stay }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los productos.")
      })
    return () => controller.abort()
  }, [open, property.name, provider, stay])

  useEffect(() => {
    if (provider !== "erpnext" || !open) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: Item[] }>("catalog_search", { property_name: property.name,
        txt: itemQuery, purpose: "sale" }, controller.signal)
        .then((result) => { if (!controller.signal.aborted) setChoices(result.items) })
        .catch((issue: unknown) => {
          if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el catálogo.")
        })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [open, property.name, provider, itemQuery])

  const currentStay = data?.stays.find((row) => row.name === stay)
  const folios = currentStay?.folios || []
  const selectedFolio = folios.some((row) => row.name === folio) ? folio : folios.length === 1 ? folios[0].name : ""
  const chosenProduct = data?.products?.find((row) => row.name === item)
  const chosenWarehouse = (data?.warehouses || []).some((row) => row.name === warehouse)
    ? warehouse : data?.warehouses?.length === 1 ? data.warehouses[0].name : ""
  const available = useMemo(() => data?.balances?.find((row) =>
    row.product === item && row.warehouse === chosenWarehouse)?.quantity || 0,
  [data, item, chosenWarehouse])
  const requests = data?.requests.filter((row) => row.stay === stay) || []
  const change = () => { reviewVersion.current += 1; setQuote(null); setError(""); setNotice("") }

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || pendingService || !selectedFolio || !item || Number(quantity) <= 0) return
    setBusy(true); setError(""); setNotice("")
    const version = ++reviewVersion.current
    try {
      const result = await call<Quote>("preview", { property_name: property.name,
        action: "request_service", data: JSON.stringify({ stay, folio: selectedFolio,
          item, quantity, included: false,
          ...(provider === "pms" && chosenProduct?.product_type === "Stock" ? { warehouse: chosenWarehouse } : {}) }) })
      if (version === reviewVersion.current) setQuote(result)
    } catch (issue) {
      if (version === reviewVersion.current)
        setError(issue instanceof Error ? issue.message : "No se pudo revisar el consumo.")
    }
    finally { setBusy(false) }
  }

  async function deliver(service: string, source?: Snapshot) {
    const snapshot = source || await refresh()
    const row = snapshot.requests.find((entry) => entry.name === service && entry.stay === stay)
    if (!row)
      throw new Error("No se encontró la solicitud pendiente de esta habitación. Revise Servicios.")
    if (row.status !== "Delivered" || !row.charge) {
      if (!["Requested", "In Progress"].includes(row.status))
        throw new Error("La solicitud ya no admite entrega. Revise Servicios.")
      await send("update_service", { service, modified: row.modified,
        status: "Delivered" })
    }
    setPendingService("")
    setQuote(null); setItem(""); setItemLabel(""); setQuantity("1"); setNotes("")
    const accountLabel = snapshot.stays.find((entry) => entry.name === stay)?.folios
      .find((entry) => entry.name === row.folio)?.label || row.folio
    setNotice(`Consumo entregado y cargado a la cuenta ${accountLabel}.`)
    await Promise.all([refresh(), onAccountChanged()]).catch(() => {
      setError("El consumo se entregó, pero no se pudo actualizar la lista. Recargue la habitación.")
    })
  }

  async function confirm() {
    if (busy || !quote || !selectedFolio || !item || pendingService) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<{ service: string }>("request_service", {
        stay, folio: selectedFolio, item, quantity, included: false, notes: notes.trim(),
        acceptance: quote.acceptance,
        ...(provider === "pms" ? { warehouse: chosenProduct?.product_type === "Stock" ? chosenWarehouse : null } : {}),
      })
      setPendingService(result.service)
      await deliver(result.service)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cargar el consumo.") }
    finally { setBusy(false) }
  }

  async function retryDelivery() {
    if (busy || !pendingService) return
    setBusy(true); setError("")
    try { await deliver(pendingService) }
    catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo entregar el consumo.") }
    finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Consumos de la habitación</CardTitle>
    <CardDescription>Registre y entregue productos a la estancia activa de {roomNumber}. Al entregar, el cargo entra a su cuenta.</CardDescription></CardHeader>
    <CardContent className="space-y-3">
      {!open && <Button onClick={() => setOpen(true)}>Agregar consumo</Button>}
      {open && <>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-destructive">{error}</p>}
        {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
        {!data && !error && <p className="text-sm text-muted-foreground">Cargando productos y cuentas…</p>}
        {data && !currentStay && <p className="text-sm text-destructive">La estancia ya no está activa. Actualice la habitación.</p>}
        {data && currentStay && <>
          <form onSubmit={review} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm"><span>Cuenta de estancia</span><select required value={selectedFolio}
              onChange={(event) => { setFolio(event.target.value); change() }}
              className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>
              {folios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.currency || data.currency}</option>)}</select></label>
            {provider === "erpnext" && <label className="space-y-1 text-sm"><span>Buscar producto</span>
              <Input value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} placeholder="Ej. agua" maxLength={140} /></label>}
            <label className="space-y-1 text-sm"><span>Producto</span><select required value={item}
              onChange={(event) => { const value = event.target.value; setItem(value);
                setItemLabel(choices.find((row) => row.name === value)?.display_name || value); setWarehouse(""); change() }}
              className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione producto</option>
              {provider === "pms" ? data.products?.map((row) => <option key={row.name} value={row.name}>{row.product_name}</option>)
                : <>{item && !choices.some((row) => row.name === item) && <option value={item}>{itemLabel}</option>}
                  {choices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name}</option>)}</>}</select></label>
            <label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.001" max="10000" step="0.001"
              value={quantity} onChange={(event) => { setQuantity(event.target.value); change() }} /></label>
            {chosenProduct?.product_type === "Stock" && <label className="space-y-1 text-sm"><span>Almacén</span>
              <select required value={chosenWarehouse} onChange={(event) => { setWarehouse(event.target.value); change() }}
                className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione almacén</option>
                {data.warehouses?.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
              <span className="text-xs text-muted-foreground">Disponible: {available}</span></label>}
            <label className="space-y-1 text-sm sm:col-span-2"><span>Observaciones (opcional)</span>
              <Input maxLength={500} value={notes} onChange={(event) => { setNotes(event.target.value); change() }} /></label>
            <Button disabled={busy || !!pendingService || !folios.length || !item ||
              (chosenProduct?.product_type === "Stock" && (!chosenWarehouse || available < Number(quantity)))}
              className="sm:col-span-2">Revisar consumo</Button>
          </form>
          {quote && !pendingService && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm">
            <p><strong>{chosenProduct?.product_name || itemLabel || item}</strong> · {quantity} × {quote.currency} {quote.unit_rate}</p>
            {provider === "pms" ? <>
              <p>Base: <strong>{quote.currency} {quote.net}</strong> · Impuesto: <strong>{quote.currency} {quote.tax}</strong></p>
              <p>Total a la cuenta: <strong>{quote.currency} {quote.total}</strong>{quote.included_in_price ? " · Impuesto incluido en el precio" : ""}</p>
            </> : <p>Subtotal: <strong>{quote.currency} {quote.amount}</strong> · Impuestos según configuración del producto.</p>}
            <Button disabled={busy} onClick={() => void confirm()}>Registrar y entregar a la cuenta</Button>
          </div>}
          {pendingService && <div className="space-y-2 rounded-lg border p-3 text-sm"><p>Solicitud {pendingService} registrada; falta confirmar la entrega.</p>
            <Button disabled={busy} onClick={() => void retryDelivery()}>Reintentar entrega</Button></div>}
          {!!requests.length && <div className="space-y-1 text-sm"><strong>Consumos recientes</strong>
            {requests.slice(0, 5).map((row) => <p key={row.name}>{row.quantity} × {data.products?.find((product) => product.name === row.item)?.product_name ||
              row.item} · {row.status === "Delivered" ? "Entregado" : row.status === "Requested" ? "Solicitado" : row.status}</p>)}</div>}
          <Button asChild variant="outline" size="sm"><Link to="/services?section=requests">Ver todos los servicios</Link></Button>
        </>}
      </>}
    </CardContent></Card>
}
