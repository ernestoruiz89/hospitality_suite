import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { availableLaundrySections } from "./LaundrySections"

type Rate = { name: string; garment: string; service_type: string; item: string | null; pms_product: string | null;
  rate: number; express_rate: number; active: boolean }
type LaundryLine = { name: string; garment: string; service_type: string;
  quantity: number; returned_quantity: number; rate: number; charge: string | null }
type Order = { name: string; stay: string; room: string; folio: string; status: string;
  express: boolean; complimentary: boolean; total: number; billed_total: number;
  ready_by: string | null; counted_at: string | null; notes: string | null;
  shortage_note: string | null; cancel_reason: string | null;
  modified: string; items: LaundryLine[] }
type Snapshot = { rates: Rate[]; orders: Order[];
  stays: { name: string; room: string; booking: string | null }[];
  folios: { name: string; stay: string | null; booking: string | null;
    label: string; currency: string }[];
  products: { name: string; product_name: string }[];
  last_30_days: { orders: number; charges: number; currency: string } }
type CollectLine = { rate: string; quantity: string }
type ItemChoice = { name: string; item_name: string; display_name: string }
const emptyLine = (): CollectLine => ({ rate: "", quantity: "1" })
const labels: Record<string, string> = { Requested: "Solicitada", Collected: "Recogida",
  "In Process": "En proceso", Ready: "Lista", Delivered: "Entregada", Cancelled: "Cancelada" }

export function Laundry({ property, provider, canSetup, canApprove, canService, canFinance }: {
  property: Property; provider: "pms" | "erpnext"; canSetup: boolean; canApprove: boolean;
  canService: boolean; canFinance: boolean
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const visibleSections = availableLaundrySections(canSetup)
  const section = visibleSections.find((item) => item.id === searchParams.get("section")) || visibleSections[0]
  useEffect(() => {
    if (!searchParams.has("section") || visibleSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", visibleSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams, visibleSections])
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [garment, setGarment] = useState("")
  const [serviceType, setServiceType] = useState("Wash & Iron")
  const [product, setProduct] = useState("")
  const [itemQuery, setItemQuery] = useState("")
  const [itemChoices, setItemChoices] = useState<ItemChoice[]>([])
  const [itemError, setItemError] = useState("")
  const [rate, setRate] = useState("")
  const [expressRate, setExpressRate] = useState("")
  const [stay, setStay] = useState("")
  const [folio, setFolio] = useState("")
  const [express, setExpress] = useState(false)
  const [requestNotes, setRequestNotes] = useState("")
  const [collectOrder, setCollectOrder] = useState("")
  const [collectLines, setCollectLines] = useState<CollectLine[]>([emptyLine()])
  const [complimentary, setComplimentary] = useState(false)
  const [counts, setCounts] = useState<Record<string, string>>({})
  const [countDirty, setCountDirty] = useState<Record<string, boolean>>({})
  const [shortageNotes, setShortageNotes] = useState<Record<string, string>>({})
  const [cancelReasons, setCancelReasons] = useState<Record<string, string>>({})
  const refresh = useCallback(async () => setData(await call<Snapshot>(provider === "pms" ?
    "pms_laundry_snapshot" : "erp_laundry_snapshot",
    { property_name: property.name })), [property.name, provider])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setStay(""); setFolio("")
    setProduct(""); setItemQuery(""); setItemChoices([]); setItemError("")
    setCollectOrder(""); setCollectLines([emptyLine()]); setCounts({}); setCountDirty({})
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar lavandería."))
  }, [refresh])
  useEffect(() => {
    if (provider !== "erpnext" || !canSetup || section.id !== "rates") return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: ItemChoice[] }>("catalog_search", {
        property_name: property.name, txt: itemQuery, purpose: "laundry",
      }, controller.signal).then((result) => {
        setItemChoices(result.items); setItemError("")
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setItemError(issue instanceof Error ? issue.message :
          "No se pudieron consultar los artículos ERPNext.")
      })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [property.name, provider, canSetup, itemQuery, section.id])
  const selectedStay = data?.stays.find((row) => row.name === stay)
  const collecting = data?.orders.find((row) => row.name === collectOrder)
  const stayFolios = data?.folios.filter((row) => row.currency === property.currency &&
    (row.stay === stay || (!row.stay && !!selectedStay?.booking &&
      row.booking === selectedStay.booking))) || []
  const rateLabel = (id: string) => {
    const row = data?.rates.find((item) => item.name === id)
    return row ? `${row.garment} · ${row.service_type}` : id
  }
  const roomLabel = (id: string) => data?.stays.find((row) => row.name === id)?.room || id
  const displayedOrders = (data?.orders || []).filter((order) =>
    section.id === "process" ? ["Collected", "In Process"].includes(order.status) :
      section.id === "ready" ? order.status === "Ready" :
        section.id === "cancel" ? order.status === "Requested" ||
          (canApprove && ["Collected", "In Process", "Ready"].includes(order.status)) : true)
  async function action(command: string, payload: Record<string, unknown>, success: string) {
    if (busy) return false
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, command, payload, crypto.randomUUID())
      await refresh(); setNotice(success)
      return true
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo registrar la operación.")
      return false
    } finally { setBusy(false) }
  }
  async function createRate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canSetup) return
    if (await action("laundry_rate", { garment: garment.trim(), service_type: serviceType,
      ...(provider === "pms" ? { pms_product: product } : { item: product }),
      rate, express_rate: expressRate || null, active: 1 },
      "Tarifa de lavandería registrada.")) {
      setGarment(""); setRate(""); setExpressRate("")
    }
  }
  async function request(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (await action("laundry_request", { stay, folio, express: express ? 1 : 0,
      notes: requestNotes.trim() }, "Recogida solicitada.")) {
      setStay(""); setFolio(""); setExpress(false); setRequestNotes("")
    }
  }
  async function collect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const order = data?.orders.find((row) => row.name === collectOrder)
    if (!order) return
    if (await action("laundry_collect", { order: order.name, modified: order.modified,
      complimentary: complimentary ? 1 : 0,
      items: collectLines.map((row) => ({ rate: row.rate, quantity: Number(row.quantity) })) },
      "Prendas recogidas y cotización congelada.")) {
      setCollectOrder(""); setCollectLines([emptyLine()]); setComplimentary(false)
    }
  }
  const changeLine = (index: number, field: keyof CollectLine, value: string) =>
    setCollectLines((rows) => rows.map((row, i) => i === index ? { ...row, [field]: value } : row))
  const defaultCount = (order: Order, line: LaundryLine) =>
    counts[line.name] ?? String(order.counted_at ? line.returned_quantity : line.quantity)
  async function count(order: Order) {
    const values = Object.fromEntries(order.items.map((line) => [line.name, Number(defaultCount(order, line))]))
    if (await action("laundry_return", { order: order.name, modified: order.modified, counts: values },
      "Conteo de prendas devueltas guardado.")) {
      setCountDirty((current) => ({ ...current, [order.name]: false }))
    }
  }
  async function deliver(order: Order) {
    await action("laundry_deliver", { order: order.name, modified: order.modified,
      shortage_note: shortageNotes[order.name] || "" },
      provider === "pms" ? "Lavandería entregada; el cargo quedó pendiente en la cuenta de estancia." :
        "Lavandería entregada; el cargo se facturará en ERPNext desde la cuenta de estancia.")
  }
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Lavandería de huéspedes</h1>
      <p className="mt-1 text-sm text-muted-foreground">{section.label} · {section.description}. {provider === "pms" ? "El cargo PMS se crea al entregar y se contabiliza con la cuenta." : "El cargo se crea al entregar y se factura con la cuenta en ERPNext."}</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section.id === "rates" && canSetup && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Tarifa</CardTitle><CardDescription>{provider === "pms" ? "Vincule la prenda con un servicio PMS que tenga ingreso e impuesto configurados." : "Vincule la prenda con un artículo de servicio ERPNext sin inventario."}</CardDescription></CardHeader><CardContent><form onSubmit={createRate} className="space-y-3">
          <Input required maxLength={80} placeholder="Prenda" value={garment} onChange={(event) => setGarment(event.target.value)} />
          <select value={serviceType} onChange={(event) => setServiceType(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="Wash & Iron">Lavar y planchar</option><option value="Dry Clean">Lavado en seco</option><option value="Iron Only">Solo planchar</option></select>
          {provider === "erpnext" && <Input maxLength={140} placeholder="Buscar artículo ERPNext" value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} />}
          {itemError && <p role="alert" className="text-sm text-destructive">{itemError}</p>}
          <select required value={product} onChange={(event) => setProduct(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">{provider === "pms" ? "Servicio PMS" : "Artículo ERPNext"}</option>{provider === "pms" ? data.products.map((row) => <option key={row.name} value={row.name}>{row.product_name}</option>) : <>{product && !itemChoices.some((row) => row.name === product) && <option value={product}>{product}</option>}{itemChoices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name} · {row.name}</option>)}</>}</select>
          <Input required type="number" min="0.01" step="0.01" placeholder={`Tarifa (${property.currency})`} value={rate} onChange={(event) => setRate(event.target.value)} />
          <Input type="number" min="0.01" step="0.01" placeholder={`Tarifa exprés (${property.currency}, opcional)`} value={expressRate} onChange={(event) => setExpressRate(event.target.value)} />
          <Button disabled={busy || !product}>Guardar tarifa</Button>
          <p className="text-xs text-muted-foreground">{data.rates.filter((row) => row.active).map((row) => `${rateLabel(row.name)}: ${property.currency} ${row.rate}`).join(" · ") || "Sin tarifas activas."}</p>
        </form></CardContent></Card></div>}
      {section.id === "request" && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Solicitar recogida</CardTitle></CardHeader><CardContent><form onSubmit={request} className="space-y-3">
          <select required value={stay} onChange={(event) => { setStay(event.target.value); setFolio("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Estancia activa</option>{data.stays.map((row) => <option key={row.name} value={row.name}>Habitación {row.room} · {row.name}</option>)}</select>
          <select required value={folio} onChange={(event) => setFolio(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta abierta</option>{stayFolios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name}</option>)}</select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={express} onChange={(event) => setExpress(event.target.checked)} /> Servicio exprés</label>
          <Input maxLength={500} placeholder="Observaciones" value={requestNotes} onChange={(event) => setRequestNotes(event.target.value)} />
          <Button disabled={busy || !stayFolios.length}>Solicitar recogida</Button>
        </form></CardContent></Card></div>}
      {section.id === "collect" && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Recoger prendas</CardTitle><CardDescription>Cuente por tarifa y congele el precio antes de procesar.</CardDescription></CardHeader><CardContent><form onSubmit={collect} className="space-y-3">
          <select required value={collectOrder} onChange={(event) => setCollectOrder(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Solicitud pendiente</option>{data.orders.filter((row) => row.status === "Requested").map((row) => <option key={row.name} value={row.name}>{row.name} · habitación {roomLabel(row.stay)}</option>)}</select>
          {collectLines.map((row, index) => <div key={index} className="flex gap-2"><select required aria-label={`Tarifa ${index + 1}`} value={row.rate} onChange={(event) => changeLine(index, "rate", event.target.value)} className="h-9 min-w-0 flex-1 rounded-md border border-border bg-white px-2 text-sm"><option value="">Tarifa</option>{data.rates.filter((item) => item.active && (provider === "pms" ? item.pms_product : item.item)).map((item) => <option key={item.name} value={item.name}>{rateLabel(item.name)} · {property.currency} {collecting?.express && Number(item.express_rate) > 0 ? item.express_rate : item.rate}</option>)}</select><Input required aria-label={`Cantidad ${index + 1}`} type="number" min="1" max="1000" step="1" value={row.quantity} onChange={(event) => changeLine(index, "quantity", event.target.value)} className="w-20" />{collectLines.length > 1 && <Button type="button" variant="outline" onClick={() => setCollectLines((lines) => lines.filter((_, i) => i !== index))}>Quitar</Button>}</div>)}
          <Button type="button" variant="outline" disabled={busy || collectLines.length >= 100} onClick={() => setCollectLines((rows) => [...rows, emptyLine()])}>Añadir prenda</Button>
          {canApprove && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={complimentary} onChange={(event) => setComplimentary(event.target.checked)} /> Cortesía autorizada</label>}
          <Button disabled={busy || !collectOrder || !data.rates.some((row) => row.active && (provider === "pms" ? row.pms_product : row.item))}>Registrar recogida</Button>
        </form></CardContent></Card></div>}
      {["orders", "process", "ready", "cancel"].includes(section.id) && <Card><CardHeader><CardTitle>{section.label}</CardTitle><CardDescription>{section.id === "orders" ? `Últimos 30 días: ${data.last_30_days.orders} entregas · ${property.currency} ${data.last_30_days.charges} cobrables.` : section.description}</CardDescription></CardHeader><CardContent className="space-y-4">{displayedOrders.map((order) => {
        const missing = order.items.reduce((sum, row) => sum + row.quantity - row.returned_quantity, 0)
        return <div key={order.name} className="rounded-lg border p-4 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><strong>{order.name}</strong> · habitación {roomLabel(order.stay)} · {labels[order.status] || order.status}{order.express && " · Exprés"}{order.complimentary && " · Cortesía"}<p className="text-xs text-muted-foreground">Estancia {order.stay} · estimado {property.currency} {order.total}{order.ready_by && ` · lista prevista ${order.ready_by}`}</p></div><div className="flex items-center gap-2"><a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/printview?doctype=${encodeURIComponent("HS Laundry Order")}&name=${encodeURIComponent(order.name)}&format=${encodeURIComponent("HS Comprobante de lavandería")}`}>Imprimir</a>{section.id === "process" && (order.status === "Collected" || order.status === "In Process") && <Button size="sm" disabled={busy} onClick={() => void action("laundry_advance", { order: order.name, modified: order.modified, status: order.status === "Collected" ? "In Process" : "Ready" }, "Estado de lavandería actualizado.")}>{order.status === "Collected" ? "Iniciar proceso" : "Marcar lista"}</Button>}</div></div>
          {order.items.length > 0 && <div className="mt-2 space-y-1">{order.items.map((line) => <p key={line.name}>{line.garment} · {line.service_type} · recogidas {line.quantity} · devueltas {line.returned_quantity}{line.charge && ` · cargo ${line.charge}`}</p>)}</div>}
          {section.id === "ready" && order.status === "Ready" && <div className="mt-3 space-y-3 border-t pt-3"><p className="font-medium">Arqueo de prendas devueltas</p>{order.items.map((line) => <label key={line.name} className="flex items-center gap-3"><span className="min-w-40">{line.garment} · {line.quantity} recogidas</span><Input aria-label={`Devueltas ${line.garment}`} type="number" min="0" max={line.quantity} step="1" value={defaultCount(order, line)} onChange={(event) => { setCounts((current) => ({ ...current, [line.name]: event.target.value })); setCountDirty((current) => ({ ...current, [order.name]: true })) }} className="w-24" /></label>)}<Button type="button" variant="outline" disabled={busy} onClick={() => void count(order)}>Guardar conteo</Button>{order.counted_at && <><p>{missing ? `${missing} prenda(s) faltante(s)` : "Todas las prendas devueltas"}</p>{missing > 0 && <Input required maxLength={500} placeholder="Explique las prendas faltantes" value={shortageNotes[order.name] || ""} onChange={(event) => setShortageNotes((current) => ({ ...current, [order.name]: event.target.value }))} />}<Button type="button" disabled={busy || !!countDirty[order.name] || !canService || (missing > 0 && (!canApprove || !shortageNotes[order.name]?.trim()))} onClick={() => void deliver(order)}>Entregar y crear cargo</Button></>}</div>}
          {section.id === "cancel" && <div className="mt-3 flex flex-wrap gap-2 border-t pt-3"><Input maxLength={500} placeholder="Motivo de cancelación" value={cancelReasons[order.name] || ""} onChange={(event) => setCancelReasons((current) => ({ ...current, [order.name]: event.target.value }))} className="min-w-52 flex-1" /><Button type="button" variant="outline" disabled={busy || !cancelReasons[order.name]?.trim() || (order.status !== "Requested" && !canApprove)} onClick={() => void action("laundry_cancel", { order: order.name, modified: order.modified, reason: cancelReasons[order.name] }, "Orden de lavandería cancelada.")}>Cancelar</Button></div>}
          {section.id === "orders" && order.status === "Delivered" && <p className="mt-2">Entregado · cobrable {property.currency} {order.billed_total}{canFinance && <> · <Link className="text-primary underline" to={provider === "pms" ? "/folios" : "/customer-credits"}>{provider === "pms" ? "Revisar cuenta" : "Cobros ERPNext"}</Link></>}</p>}
          {section.id === "orders" && order.cancel_reason && <p className="mt-2 text-muted-foreground">Cancelación: {order.cancel_reason}</p>}
        </div>
      })}{!displayedOrders.length && <p className="text-sm text-muted-foreground">Sin órdenes para esta opción.</p>}</CardContent></Card>}
    </>}
  </div>
}
