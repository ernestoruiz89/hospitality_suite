import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { pmsInventorySections, usePmsInventorySection } from "./InventorySections"

type Snapshot = { currency: string;
  products: { name: string; product_code: string; product_name: string;
    inventory_account: string; expense_account: string }[];
  warehouses: { name: string; warehouse_code: string; warehouse_name: string }[];
  balances: { product: string; warehouse: string; quantity: number; value: number }[];
  movements: { name: string; product: string; warehouse: string; direction: string;
    quantity_delta: number; value_delta: number; purpose: string; business_date: string; source_name: string }[];
  equity_accounts: Account[]; clearing_accounts: Account[];
  expense_accounts: Account[]; income_accounts: Account[];
  transfers: { name: string; product: string; source_warehouse: string; target_warehouse: string;
    quantity: number; value: number; reference: string; business_date: string }[];
  counts: { name: string; product: string; warehouse: string; expected_quantity: number;
    counted_quantity: number; difference_quantity: number; adjustment_value: number;
    reference: string; business_date: string }[] }
type Account = { name: string; account_code: string; account_name: string }

export function Inventory({ property, canSetup, canApprove }: { property: Property; canSetup: boolean; canApprove: boolean }) {
  const section = usePmsInventorySection(canSetup, canApprove)
  const sectionInfo = pmsInventorySections.find((item) => item.id === section)!
  const [data, setData] = useState<Snapshot | null>(null)
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [product, setProduct] = useState("")
  const [warehouse, setWarehouse] = useState("")
  const [quantity, setQuantity] = useState("")
  const [value, setValue] = useState("")
  const [equity, setEquity] = useState("")
  const [reference, setReference] = useState("")
  const [transferProduct, setTransferProduct] = useState("")
  const [sourceWarehouse, setSourceWarehouse] = useState("")
  const [targetWarehouse, setTargetWarehouse] = useState("")
  const [transferQuantity, setTransferQuantity] = useState("")
  const [clearingAccount, setClearingAccount] = useState("")
  const [transferReference, setTransferReference] = useState("")
  const [transferReason, setTransferReason] = useState("")
  const [countProduct, setCountProduct] = useState("")
  const [countWarehouse, setCountWarehouse] = useState("")
  const [countedQuantity, setCountedQuantity] = useState("")
  const [adjustmentAccount, setAdjustmentAccount] = useState("")
  const [countValue, setCountValue] = useState("")
  const [countReference, setCountReference] = useState("")
  const [countReason, setCountReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const refresh = useCallback(async () => setData(await call<Snapshot>("pms_inventory_snapshot",
    { property_name: property.name })), [property.name])
  useEffect(() => {
    setData(null); setCode(""); setName(""); setProduct(""); setWarehouse("");
    setQuantity(""); setValue(""); setEquity(""); setReference(""); setError(""); setNotice("")
    setTransferProduct(""); setSourceWarehouse(""); setTargetWarehouse(""); setTransferQuantity("");
    setClearingAccount(""); setTransferReference(""); setTransferReason("");
    setCountProduct(""); setCountWarehouse(""); setCountedQuantity("");
    setAdjustmentAccount(""); setCountValue(""); setCountReference(""); setCountReason("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar el inventario."))
  }, [refresh])
  async function createWarehouse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_warehouse", {
        warehouse_code: code.trim(), warehouse_name: name.trim(),
      }, crypto.randomUUID())
      setCode(""); setName(""); await refresh(); setNotice("Almacén creado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el almacén.") }
    finally { setBusy(false) }
  }
  async function opening(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_opening_stock", {
        product, warehouse, quantity, value, equity_account: equity, reference: reference.trim(),
      }, crypto.randomUUID())
      setQuantity(""); setValue(""); setReference(""); await refresh()
      setNotice("Existencias iniciales y asiento registrados.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el saldo inicial.") }
    finally { setBusy(false) }
  }
  async function transfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_transfer_stock", {
        product: transferProduct, source_warehouse: sourceWarehouse,
        target_warehouse: targetWarehouse, quantity: transferQuantity,
        clearing_account: clearingAccount, reference: transferReference.trim(),
        reason: transferReason.trim(),
      }, crypto.randomUUID())
      setTransferQuantity(""); setTransferReference(""); setTransferReason("")
      await refresh(); setNotice("Traslado y asientos registrados.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo trasladar el inventario.") }
    finally { setBusy(false) }
  }
  async function count(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !data) return
    setBusy(true); setError(""); setNotice("")
    try {
      const expected = Number(data.balances.find((row) => row.product === countProduct &&
        row.warehouse === countWarehouse)?.quantity || 0)
      const difference = Number(countedQuantity) - expected
      const selectedProduct = data.products.find((row) => row.name === countProduct)
      await execute(property.name, "pms_count_stock", {
        product: countProduct, warehouse: countWarehouse,
        counted_quantity: countedQuantity, reference: countReference.trim(),
        reason: countReason.trim(),
        ...(difference !== 0 ? { adjustment_account: adjustmentAccount ||
          (difference < 0 ? selectedProduct?.expense_account : "") } : {}),
        ...(difference > 0 && expected === 0 ? { value: countValue } : {}),
      }, crypto.randomUUID())
      setCountedQuantity(""); setCountValue(""); setCountReference(""); setCountReason("")
      await refresh(); setNotice("Conteo aprobado y diferencia contabilizada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el conteo.") }
    finally { setBusy(false) }
  }
  const productName = (id: string) => data?.products.find((row) => row.name === id)?.product_name || id
  const warehouseName = (id: string) => data?.warehouses.find((row) => row.name === id)?.warehouse_name || id
  const selectedTransferProduct = data?.products.find((row) => row.name === transferProduct)
  const countedExpected = Number(data?.balances.find((row) => row.product === countProduct &&
    row.warehouse === countWarehouse)?.quantity || 0)
  const countDifference = countedQuantity === "" ? 0 : Number(countedQuantity) - countedExpected
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Inventario PMS</p><h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1><p className="mt-1 text-sm text-muted-foreground">{`${sectionInfo.description}.`}</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section === "warehouses" && canSetup && <>
        <Card><CardHeader><CardTitle>Nuevo almacén</CardTitle><CardDescription>Disponible para productos de inventario del establecimiento.</CardDescription></CardHeader><CardContent><form onSubmit={createWarehouse} className="space-y-3"><Input required maxLength={40} placeholder="Código" value={code} onChange={(event) => setCode(event.target.value)} /><Input required maxLength={140} placeholder="Nombre del almacén" value={name} onChange={(event) => setName(event.target.value)} /><Button disabled={busy}>Crear almacén</Button></form></CardContent></Card>
        <Card><CardHeader><CardTitle>Almacenes registrados</CardTitle></CardHeader><CardContent className="space-y-2">{data.warehouses.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.warehouse_code}</strong> · {row.warehouse_name}</p>)}{!data.warehouses.length && <p className="text-sm text-muted-foreground">Sin almacenes registrados.</p>}</CardContent></Card>
      </>}
      {section === "opening" && <Card><CardHeader><CardTitle>Existencias iniciales</CardTitle><CardDescription>Registre el primer conteo de cada producto y almacén contra patrimonio. Las compras y recepciones posteriores tendrán su propio flujo.</CardDescription></CardHeader><CardContent><form onSubmit={opening} className="space-y-3">
          <select required value={product} onChange={(event) => setProduct(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto de inventario</option>{data.products.map((row) => <option key={row.name} value={row.name}>{row.product_code} · {row.product_name}</option>)}</select>
          <select required value={warehouse} onChange={(event) => setWarehouse(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
          <Input required aria-label="Cantidad inicial" type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="Cantidad inicial" />
          <Input required aria-label={`Valor total inicial en ${data.currency}`} type="number" min="0.01" step="0.01" value={value} onChange={(event) => setValue(event.target.value)} placeholder={`Valor total (${data.currency})`} />
          <select required value={equity} onChange={(event) => setEquity(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de patrimonio</option>{data.equity_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
          <Input required maxLength={140} placeholder="Referencia del conteo inicial" value={reference} onChange={(event) => setReference(event.target.value)} />
          <Button disabled={busy || !data.products.length || !data.warehouses.length}>Registrar saldo inicial</Button>
        </form>{canSetup && <p className="mt-3 text-xs text-muted-foreground">Cree productos de inventario en <Link to="/products" className="text-primary underline">Productos PMS</Link>.</p>}</CardContent></Card>}
      {section === "transfers" && <Card><CardHeader><CardTitle>Traslado entre almacenes</CardTitle><CardDescription>Conserva el costo promedio de origen. La cuenta temporal queda en cero al completar ambos movimientos.</CardDescription></CardHeader><CardContent><form onSubmit={transfer} className="space-y-3">
          <select required value={transferProduct} onChange={(event) => { setTransferProduct(event.target.value); setClearingAccount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto</option>{data.products.map((row) => <option key={row.name} value={row.name}>{row.product_code} · {row.product_name}</option>)}</select>
          <select required value={sourceWarehouse} onChange={(event) => setSourceWarehouse(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén de origen</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
          <select required value={targetWarehouse} onChange={(event) => setTargetWarehouse(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén de destino</option>{data.warehouses.filter((row) => row.name !== sourceWarehouse).map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
          <Input required aria-label="Cantidad a trasladar" type="number" min="0.000001" step="0.000001" value={transferQuantity} onChange={(event) => setTransferQuantity(event.target.value)} placeholder="Cantidad" />
          <select required value={clearingAccount} onChange={(event) => setClearingAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta temporal de traslado</option>{data.clearing_accounts.filter((row) => row.name !== selectedTransferProduct?.inventory_account).map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
          <Input required maxLength={140} placeholder="Referencia del traslado" value={transferReference} onChange={(event) => setTransferReference(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={transferReason} onChange={(event) => setTransferReason(event.target.value)} />
          <Button disabled={busy || !transferProduct || !sourceWarehouse || !targetWarehouse || sourceWarehouse === targetWarehouse}>Registrar traslado</Button>
        </form></CardContent></Card>}
      {section === "counts" && canApprove && <Card><CardHeader><CardTitle>Arqueo de existencias</CardTitle><CardDescription>Gerencia registra el conteo físico. Los faltantes usan costo promedio; un sobrante sin saldo previo requiere costo total.</CardDescription></CardHeader><CardContent><form onSubmit={count} className="space-y-3">
          <select required value={countProduct} onChange={(event) => { setCountProduct(event.target.value); setAdjustmentAccount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto</option>{data.products.map((row) => <option key={row.name} value={row.name}>{row.product_code} · {row.product_name}</option>)}</select>
          <select required value={countWarehouse} onChange={(event) => setCountWarehouse(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select>
          <p className="text-sm text-muted-foreground">Existencia contable: {countedExpected} · Diferencia: {countDifference}</p>
          <Input required aria-label="Cantidad contada" type="number" min="0" step="0.000001" value={countedQuantity} onChange={(event) => setCountedQuantity(event.target.value)} placeholder="Cantidad física contada" />
          {countDifference !== 0 && <select required={countDifference > 0} value={adjustmentAccount} onChange={(event) => setAdjustmentAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">{countDifference < 0 ? "Costo configurado del producto" : "Cuenta de ingreso por sobrante"}</option>{(countDifference < 0 ? data.expense_accounts : data.income_accounts).map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
          {countDifference > 0 && countedExpected === 0 && <Input required aria-label={`Costo total del sobrante en ${data.currency}`} type="number" min="0.01" step="0.01" value={countValue} onChange={(event) => setCountValue(event.target.value)} placeholder={`Costo total del sobrante (${data.currency})`} />}
          <Input required maxLength={140} placeholder="Referencia del conteo" value={countReference} onChange={(event) => setCountReference(event.target.value)} />
          <Input required maxLength={500} placeholder="Justificación del conteo" value={countReason} onChange={(event) => setCountReason(event.target.value)} />
          <Button disabled={busy || !countProduct || !countWarehouse || countedQuantity === ""}>Aprobar conteo</Button>
        </form></CardContent></Card>}
      {section === "stock" && <Card><CardHeader><CardTitle>Existencias actuales</CardTitle></CardHeader><CardContent className="space-y-2">{data.balances.map((row) => <div key={`${row.product}:${row.warehouse}`} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span>{productName(row.product)} · {warehouseName(row.warehouse)}</span><strong>{row.quantity} unidades · {data.currency} {row.value}</strong></div>)}{!data.balances.length && <p className="text-sm text-muted-foreground">Sin existencias registradas.</p>}</CardContent></Card>}
      {section === "history" && <><div className="grid gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle>Traslados recientes</CardTitle></CardHeader><CardContent className="space-y-2">{data.transfers.map((row) => <div key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.reference}</strong> · {productName(row.product)} · {row.quantity}<p className="text-xs text-muted-foreground">{warehouseName(row.source_warehouse)} → {warehouseName(row.target_warehouse)} · {data.currency} {row.value}</p></div>)}{!data.transfers.length && <p className="text-sm text-muted-foreground">Sin traslados.</p>}</CardContent></Card>
        <Card><CardHeader><CardTitle>Conteos recientes</CardTitle></CardHeader><CardContent className="space-y-2">{data.counts.map((row) => <div key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.reference}</strong> · {productName(row.product)} · {warehouseName(row.warehouse)}<p className="text-xs text-muted-foreground">Contable {row.expected_quantity} · Físico {row.counted_quantity} · Diferencia {row.difference_quantity} · Valor {data.currency} {row.adjustment_value}</p></div>)}{!data.counts.length && <p className="text-sm text-muted-foreground">Sin conteos.</p>}</CardContent></Card></div>
      <Card><CardHeader><CardTitle>Movimientos recientes</CardTitle></CardHeader><CardContent className="space-y-2">{data.movements.map((row) => <div key={row.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span>{row.business_date} · {productName(row.product)} · {warehouseName(row.warehouse)}<span className="block text-xs text-muted-foreground">{row.purpose} · {row.source_name}</span></span><strong>{row.direction === "Receipt" ? "+" : ""}{row.quantity_delta} · {data.currency} {row.value_delta}</strong></div>)}{!data.movements.length && <p className="text-sm text-muted-foreground">Sin movimientos.</p>}</CardContent></Card></>}
    </>}
  </div>
}
