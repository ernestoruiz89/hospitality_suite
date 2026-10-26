import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { erpInventorySections, useErpInventorySection } from "./InventorySections"

type Warehouse = { name: string; warehouse_name: string }
type Category = { name: string; label: string; account: string }
type Stock = { item_code: string; item_name: string; actual_qty: number | null;
  projected_qty: number | null; minimum: number | null; reorder_quantity: number | null;
  purpose: string; stock_managed: boolean; needs_restock: boolean }
type Snapshot = { currency: string; default_warehouse: string | null;
  warehouses: Warehouse[]; categories: Category[] }
type InventoryStatus = { warehouse: string | null; items: Stock[] }
type CountQuote = { item: string; warehouse: string; current_quantity: string;
  counted_quantity: string; valuation_rate: string; acceptance: string }
type ItemChoice = { name: string; item_name: string; display_name?: string }
const classNames: Record<string, string> = {
  Merchandise: "Mercancía", Cleaning: "Limpieza", Linen: "Blancos", Parts: "Repuestos",
}
const movementNames: Record<string, string> = {
  Transfer: "Traslado", Cleaning: "Consumo de limpieza", Waste: "Merma",
  "Linen Replacement": "Reposición de blancos",
}

export function ErpInventory({ property, canSetup, canApprove }: {
  property: Property; canSetup: boolean; canApprove: boolean }) {
  const section = useErpInventorySection(canSetup, canApprove)
  const sectionInfo = erpInventorySections.find((item) => item.id === section)!
  const [data, setData] = useState<Snapshot | null>(null)
  const [stock, setStock] = useState<InventoryStatus | null>(null)
  const [warehouse, setWarehouse] = useState("")
  const [itemQuery, setItemQuery] = useState("")
  const [choices, setChoices] = useState<ItemChoice[]>([])
  const [item, setItem] = useState("")
  const [itemLabel, setItemLabel] = useState("")
  const [newWarehouse, setNewWarehouse] = useState("")
  const [classPurpose, setClassPurpose] = useState("Merchandise")
  const [minimum, setMinimum] = useState("0")
  const [reorder, setReorder] = useState("0")
  const [movePurpose, setMovePurpose] = useState("Transfer")
  const [target, setTarget] = useState("")
  const [quantity, setQuantity] = useState("")
  const [category, setCategory] = useState("")
  const [reason, setReason] = useState("")
  const [counted, setCounted] = useState("")
  const [countCategory, setCountCategory] = useState("")
  const [countReason, setCountReason] = useState("")
  const [quote, setQuote] = useState<(CountQuote & { requestKey: string }) | null>(null)
  const [moveKey, setMoveKey] = useState("")
  const [policyKey, setPolicyKey] = useState("")
  const [warehouseKey, setWarehouseKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const refreshSetup = useCallback(async () => {
    const result = await call<Snapshot>("erp_inventory_snapshot", { property_name: property.name })
    setData(result)
    setWarehouse((current) => result.warehouses.some((row) => row.name === current) ? current :
      result.default_warehouse || result.warehouses[0]?.name || "")
  }, [property.name])
  const refreshStock = useCallback(async (name: string) => {
    if (name) setStock(await call<InventoryStatus>("inventory_status", {
      property_name: property.name, warehouse_name: name }))
    else setStock({ warehouse: null, items: [] })
  }, [property.name])
  useEffect(() => {
    setData(null); setStock(null); setWarehouse(""); setItem(""); setItemLabel("")
    setItemQuery(""); setChoices([]); setQuote(null); setError(""); setNotice("")
    setMoveKey(""); setPolicyKey(""); setWarehouseKey("")
    refreshSetup().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar el inventario."))
  }, [refreshSetup])
  useEffect(() => {
    const controller = new AbortController()
    setStock(null)
    if (warehouse) call<InventoryStatus>("inventory_status", {
      property_name: property.name, warehouse_name: warehouse,
    }, controller.signal).then(setStock).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las existencias.")
    })
    else setStock({ warehouse: null, items: [] })
    return () => controller.abort()
  }, [property.name, warehouse])
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: ItemChoice[] }>("catalog_search", {
        property_name: property.name, txt: itemQuery, purpose: "stock",
      }, controller.signal).then((result) => setChoices(result.items)).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el catálogo.")
      })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [property.name, itemQuery])
  const selectedStock = stock?.items.find((row) => row.item_code === item)
  const selectedChoice = choices.find((row) => row.name === item)
  const targetRequired = movePurpose === "Transfer" || movePurpose === "Linen Replacement"
  const invalidateCount = () => { setQuote(null); setError("") }

  async function createWarehouse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const key = warehouseKey || crypto.randomUUID(); setWarehouseKey(key)
    try {
      const result = await execute<{ warehouse: string }>(property.name, "create_warehouse",
        { warehouse_name: newWarehouse.trim() }, key)
      await refreshSetup(); setWarehouse(result.warehouse); setNewWarehouse(""); setWarehouseKey("")
      setNotice(`Almacén ${result.warehouse} creado.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el almacén.") }
    finally { setBusy(false) }
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const key = policyKey || crypto.randomUUID(); setPolicyKey(key)
    try {
      await execute(property.name, "stock_policy", { item, warehouse,
        purpose: classPurpose, minimum, reorder_quantity: reorder }, key)
      await refreshStock(warehouse); setPolicyKey("")
      setNotice("Clasificación y mínimos actualizados.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la política.") }
    finally { setBusy(false) }
  }

  async function move(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    const key = moveKey || crypto.randomUUID(); setMoveKey(key)
    try {
      const result = await execute<{ stock_entry: string }>(property.name, "move_stock", {
        item, source_warehouse: warehouse, target_warehouse: targetRequired ? target : null,
        purpose: movePurpose, quantity, category: targetRequired ? null : category,
        reason: reason.trim(),
      }, key)
      await refreshStock(warehouse); setMoveKey(""); setQuantity(""); setReason("")
      setNotice(`Movimiento ${result.stock_entry} registrado.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el movimiento.") }
    finally { setBusy(false) }
  }

  async function reviewCount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setQuote(null)
    try {
      const result = await call<CountQuote>("preview", { property_name: property.name,
        action: "adjust_stock", data: JSON.stringify({ item, warehouse,
          counted_quantity: counted }) })
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el conteo.") }
    finally { setBusy(false) }
  }

  async function confirmCount() {
    if (!quote || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ stock_reconciliation: string }>(property.name,
        "adjust_stock", { item, warehouse, counted_quantity: counted,
          category: countCategory, reason: countReason.trim(),
          acceptance: quote.acceptance }, quote.requestKey)
      await refreshStock(warehouse); setQuote(null); setCounted(""); setCountReason("")
      setNotice(`Ajuste ${result.stock_reconciliation} contabilizado.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo contabilizar el conteo.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Inventario ERPNext</p><h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1><p className="mt-1 text-sm text-muted-foreground">{`${sectionInfo.description}.`}</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section !== "warehouses" && <Card><CardHeader><CardTitle>Almacén de trabajo</CardTitle><CardDescription>Seleccione el almacén antes de consultar o registrar existencias.</CardDescription></CardHeader><CardContent>
        <select value={warehouse} onChange={(event) => { setWarehouse(event.target.value); setItem(""); setQuote(null) }} className="h-9 w-full max-w-lg rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione almacén</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
      </CardContent></Card>}
      {section === "stock" && <Card><CardHeader><CardTitle>Existencias por almacén</CardTitle><CardDescription>Señales de reposición según el mínimo configurado en el artículo ERPNext.</CardDescription></CardHeader><CardContent className="space-y-3">
        {!stock ? <Skeleton className="h-36 w-full" /> : <div className="max-h-96 overflow-auto"><table className="w-full min-w-[540px] text-left text-sm"><thead><tr className="border-b border-border"><th className="py-2">Artículo</th><th>Categoría</th><th>Existencia</th><th>Proyectado</th><th>Mínimo</th></tr></thead><tbody>{stock.items.map((row) => <tr key={row.item_code} className="border-b border-border"><td className="py-2">{row.item_name || row.item_code}<span className="block text-xs text-muted-foreground">{row.item_code}</span></td><td>{classNames[row.purpose] || row.purpose}</td><td>{row.stock_managed ? row.actual_qty : "—"}</td><td>{row.stock_managed ? row.projected_qty : "—"}</td><td>{row.stock_managed ? row.minimum ?? "—" : "—"}{row.needs_restock && <span className="ml-2 rounded bg-amber-100 px-1 text-amber-900">Reponer</span>}</td></tr>)}</tbody></table>{!stock.items.length && <p className="py-4 text-sm text-muted-foreground">Sin existencias ni mínimos en este almacén.</p>}</div>}
      </CardContent></Card>}
      {section !== "stock" && section !== "warehouses" && <Card><CardHeader><CardTitle>Seleccionar artículo</CardTitle><CardDescription>Busque un artículo inventariable habilitado para las operaciones siguientes.</CardDescription></CardHeader><CardContent className="space-y-3"><Input aria-label="Buscar artículo" value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} placeholder="Código o nombre" maxLength={140} /><select value={item} onChange={(event) => { const value = event.target.value; setItem(value); setItemLabel(choices.find((row) => row.name === value)?.display_name || value); setPolicyKey(""); setMoveKey(""); invalidateCount() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione artículo</option>{item && !selectedChoice && <option value={item}>{itemLabel || item}</option>}{choices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name}</option>)}</select>{selectedStock && <p className="text-sm">Existencia actual: <strong>{selectedStock.actual_qty}</strong> · {classNames[selectedStock.purpose] || selectedStock.purpose}</p>}</CardContent></Card>}
      {section === "warehouses" && <Card><CardHeader><CardTitle>Nuevo almacén</CardTitle><CardDescription>Se asigna exclusivamente al establecimiento seleccionado.</CardDescription></CardHeader><CardContent><form onSubmit={createWarehouse} className="space-y-3"><Input required maxLength={140} value={newWarehouse} onChange={(event) => { setNewWarehouse(event.target.value); setWarehouseKey("") }} placeholder="Nombre del almacén" /><Button disabled={busy}>Crear almacén</Button></form></CardContent></Card>}
      {section === "warehouses" && <Card><CardHeader><CardTitle>Almacenes disponibles</CardTitle></CardHeader><CardContent className="space-y-2">{data.warehouses.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm">{row.warehouse_name}</p>)}{!data.warehouses.length && <p className="text-sm text-muted-foreground">Sin almacenes habilitados.</p>}</CardContent></Card>}
      {section === "policies" && canSetup && <Card><CardHeader><CardTitle>Clasificación y mínimos</CardTitle><CardDescription>ERPNext generará la señal de reposición cuando la existencia sea inferior al mínimo.</CardDescription></CardHeader><CardContent><form onSubmit={savePolicy} className="space-y-3"><select required value={classPurpose} onChange={(event) => { setClassPurpose(event.target.value); setPolicyKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{Object.entries(classNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><div className="grid grid-cols-2 gap-3"><Input required type="number" min="0" step="0.001" aria-label="Existencia mínima" value={minimum} onChange={(event) => { setMinimum(event.target.value); setPolicyKey("") }} /><Input required type="number" min="0" step="0.001" aria-label="Cantidad a reponer" value={reorder} onChange={(event) => { setReorder(event.target.value); setPolicyKey("") }} /></div><Button disabled={busy || !item || !warehouse}>Guardar mínimos</Button></form></CardContent></Card>}
      {section === "moves" && <Card><CardHeader><CardTitle>Movimiento de stock</CardTitle><CardDescription>El traslado o consumo publica un Stock Entry nativo y conserva el motivo.</CardDescription></CardHeader><CardContent><form onSubmit={move} className="space-y-3"><select value={movePurpose} onChange={(event) => { setMovePurpose(event.target.value); setMoveKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{Object.entries(movementNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{targetRequired ? <select required value={target} onChange={(event) => { setTarget(event.target.value); setMoveKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén de destino</option>{data.warehouses.filter((row) => row.name !== warehouse).map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select> : <select required value={category} onChange={(event) => { setCategory(event.target.value); setMoveKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Categoría de gasto</option>{data.categories.map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select>}<Input required type="number" min="0.001" step="0.001" aria-label="Cantidad a mover" value={quantity} onChange={(event) => { setQuantity(event.target.value); setMoveKey("") }} /><Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { setReason(event.target.value); setMoveKey("") }} /><Button disabled={busy || !item || !warehouse}>Registrar movimiento</Button></form></CardContent></Card>}
      {section === "counts" && canApprove && <Card><CardHeader><CardTitle>Conteo físico</CardTitle><CardDescription>Compare el conteo con la existencia vigente y revise la valoración antes de publicar el ajuste.</CardDescription></CardHeader><CardContent className="space-y-3"><form onSubmit={reviewCount} className="grid gap-3 sm:grid-cols-2"><Input required type="number" min="0" step="0.001" aria-label="Cantidad contada" value={counted} onChange={(event) => { setCounted(event.target.value); invalidateCount() }} /><select required value={countCategory} onChange={(event) => { setCountCategory(event.target.value); invalidateCount() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Categoría de diferencia</option>{data.categories.map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select><Input required maxLength={500} placeholder="Motivo del ajuste" value={countReason} onChange={(event) => { setCountReason(event.target.value); invalidateCount() }} className="sm:col-span-2" /><Button disabled={busy || !item || !warehouse}>Revisar conteo</Button></form>{quote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p>Actual: <strong>{quote.current_quantity}</strong> · Contado: <strong>{quote.counted_quantity}</strong> · Diferencia: <strong>{Number(quote.counted_quantity) - Number(quote.current_quantity)}</strong></p><p>Valoración por unidad: {data.currency} {quote.valuation_rate}</p><Button disabled={busy || Number(quote.current_quantity) === Number(quote.counted_quantity)} onClick={() => void confirmCount()}>Contabilizar diferencia</Button></div>}</CardContent></Card>}
    </>}
  </div>
}
