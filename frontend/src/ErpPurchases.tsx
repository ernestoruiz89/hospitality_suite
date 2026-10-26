import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { erpPurchaseSections, useErpPurchaseSection } from "./PurchaseSections"

type Item = { name: string; item_name: string; display_name?: string }
type OrderLine = { name: string; item_code: string; item_name: string;
  qty: number; received_qty: number; rate: number }
type Order = { name: string; supplier: string; currency: string; grand_total: number;
  schedule_date: string; status: string; per_received: number; items: OrderLine[] }
type Receipt = { name: string; supplier: string; posting_date: string;
  currency: string; grand_total: number; per_billed: number }
type Invoice = { name: string; supplier: string; bill_no: string;
  currency: string; grand_total: number; outstanding_amount: number }
type Method = { name: string; mode_of_payment: string; currency: string;
  is_cash: boolean; reference_required: boolean }
type Snapshot = { currency: string; default_warehouse: string | null;
  suppliers: { name: string; supplier_name: string }[];
  warehouses: { name: string; warehouse_name: string }[];
  orders: Order[]; receipts: Receipt[]; invoices: Invoice[];
  methods: Method[]; shifts: { name: string; cashier: string; currency: string }[] }
type NewLine = { item: string; label: string; quantity: string; rate: string }
type OrderQuote = { supplier: string; warehouse: string; schedule_date: string;
  currency: string; total: string; exchange_rate: string;
  taxes: { account: string; amount: string }[]; acceptance: string }
type PaymentQuote = { invoice: string; supplier: string; amount: string;
  currency: string; party_amount: string; party_currency: string;
  exchange_rate: string; acceptance: string }
type Page<T> = { rows: T[]; offset: number; has_more: boolean }
type PurchaseMode = "orders" | "receipts" | "invoices"
const PAGE_SIZE = 50

function usePurchasePage<T>(property: string, mode: PurchaseMode, version: number) {
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page<T> | null>(null)
  const [error, setError] = useState("")
  useEffect(() => { setQuery(""); setSearch(""); setOffset(0); setPage(null); setError("") }, [property])
  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError("")
    call<Page<T>>("erp_purchase_search", { property_name: property, mode,
      search, offset: String(offset), page_length: String(PAGE_SIZE),
    }, controller.signal).then(setPage).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron buscar los documentos.")
    })
    return () => controller.abort()
  }, [property, mode, search, offset, version])
  return { query, setQuery, page, error,
    find: (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setSearch(query.trim()); setOffset(0) },
    previous: () => setOffset((current) => Math.max(0, current - PAGE_SIZE)),
    next: () => setOffset((current) => current + PAGE_SIZE),
    reset: () => { setQuery(""); setSearch(""); setOffset(0) },
  }
}

function DocumentFinder({ label, finder }: { label: string; finder: ReturnType<typeof usePurchasePage> }) {
  return <div className="space-y-2"><form onSubmit={finder.find} className="flex flex-wrap gap-2"><Input aria-label={label} placeholder={`Buscar ${label.toLowerCase()} por número o proveedor`} value={finder.query} onChange={(event) => finder.setQuery(event.target.value)} maxLength={100} className="min-w-44 flex-1" /><Button variant="outline">Buscar</Button></form>{finder.error && <p role="alert" className="text-sm text-destructive">{finder.error}</p>}<div className="flex items-center justify-between text-xs text-muted-foreground"><span>{finder.page ? finder.page.rows.length ? `${finder.page.offset + 1}–${finder.page.offset + finder.page.rows.length}` : "Sin resultados" : "Consultando…"}</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!finder.page || finder.page.offset === 0} onClick={finder.previous}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={!finder.page?.has_more} onClick={finder.next}>Siguiente</Button></div></div></div>
}

export function ErpPurchases({ property, canPurchase, canFinance }: {
  property: Property; canPurchase: boolean; canFinance: boolean }) {
  const [, setSearchParams] = useSearchParams()
  const section = useErpPurchaseSection(canPurchase, canFinance)
  const sectionInfo = erpPurchaseSections.find((item) => item.id === section)!
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [pageVersion, setPageVersion] = useState(0)
  const orders = usePurchasePage<Order>(property.name, "orders", pageVersion)
  const receipts = usePurchasePage<Receipt>(property.name, "receipts", pageVersion)
  const invoices = usePurchasePage<Invoice>(property.name, "invoices", pageVersion)
  const [supplierName, setSupplierName] = useState("")
  const [supplierKey, setSupplierKey] = useState("")
  const [supplier, setSupplier] = useState("")
  const [warehouse, setWarehouse] = useState("")
  const [scheduleDate, setScheduleDate] = useState("")
  const [orderReason, setOrderReason] = useState("")
  const [itemQuery, setItemQuery] = useState("")
  const [choices, setChoices] = useState<Item[]>([])
  const [item, setItem] = useState("")
  const [lineQuantity, setLineQuantity] = useState("1")
  const [lineRate, setLineRate] = useState("")
  const [lines, setLines] = useState<NewLine[]>([])
  const [orderQuote, setOrderQuote] = useState<(OrderQuote & { requestKey: string }) | null>(null)
  const [receiveOrder, setReceiveOrder] = useState("")
  const [receiveWarehouse, setReceiveWarehouse] = useState("")
  const [receiveQuantity, setReceiveQuantity] = useState<Record<string, string>>({})
  const [receiveReason, setReceiveReason] = useState("")
  const [receiveKey, setReceiveKey] = useState("")
  const [billReceipt, setBillReceipt] = useState("")
  const [billNo, setBillNo] = useState("")
  const [billDate, setBillDate] = useState("")
  const [billReason, setBillReason] = useState("")
  const [billKey, setBillKey] = useState("")
  const [payInvoice, setPayInvoice] = useState("")
  const [payMethod, setPayMethod] = useState("")
  const [payShift, setPayShift] = useState("")
  const [payAmount, setPayAmount] = useState("")
  const [payReference, setPayReference] = useState("")
  const [payReason, setPayReason] = useState("")
  const [payQuote, setPayQuote] = useState<(PaymentQuote & { requestKey: string }) | null>(null)
  const refresh = useCallback(async () => {
    const result = await call<Snapshot>("erp_purchases_snapshot", { property_name: property.name })
    setData(result)
    setPageVersion((current) => current + 1)
    setWarehouse((current) => current || result.default_warehouse || result.warehouses[0]?.name || "")
    setReceiveWarehouse((current) => current || result.default_warehouse || result.warehouses[0]?.name || "")
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setSupplierName(""); setSupplierKey("")
    setSupplier(""); setWarehouse(""); setScheduleDate(""); setOrderReason("")
    setItemQuery(""); setChoices([]); setItem(""); setLines([]); setOrderQuote(null)
    setReceiveOrder(""); setReceiveWarehouse(""); setReceiveQuantity({}); setReceiveReason(""); setReceiveKey("")
    setBillReceipt(""); setBillNo(""); setBillDate(""); setBillReason(""); setBillKey("")
    setPayInvoice(""); setPayMethod(""); setPayShift(""); setPayAmount("")
    setPayReference(""); setPayReason(""); setPayQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar las compras."))
  }, [refresh])
  useEffect(() => {
    if (!canPurchase || section !== "order-new") return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: Item[] }>("catalog_search", {
        property_name: property.name, txt: itemQuery, purpose: "purchase",
      }, controller.signal).then((result) => setChoices(result.items)).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el catálogo de artículos.")
      })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [property.name, canPurchase, itemQuery, section])
  const orderRows = orders.page?.rows || []
  const receiptRows = receipts.page?.rows || []
  const invoiceRows = invoices.page?.rows || []
  const selectedOrder = orderRows.find((row) => row.name === receiveOrder &&
    row.items.some((item) => Number(item.qty) > Number(item.received_qty || 0)))
  const selectedMethod = data?.methods.find((row) => row.name === payMethod)
  const supplierLabel = (name: string) => data?.suppliers.find((row) => row.name === name)?.supplier_name || name
  const invalidateOrder = () => { setOrderQuote(null); setError("") }
  const invalidatePayment = () => { setPayQuote(null); setError("") }
  const orderData = () => ({ supplier, warehouse, schedule_date: scheduleDate || undefined,
    reason: orderReason.trim(), items: lines.map(({ item: code, quantity, rate }) =>
      ({ item: code, quantity, rate })) })

  async function registerSupplier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canPurchase || section !== "supplier-new") return
    setBusy(true); setError(""); setNotice("")
    const key = supplierKey || crypto.randomUUID(); setSupplierKey(key)
    try {
      const result = await execute<{ supplier: string }>(property.name,
        "register_supplier", { supplier_name: supplierName.trim() }, key)
      await refresh(); setSupplier(result.supplier); setSupplierName(""); setSupplierKey("")
      setNotice(`Proveedor ${result.supplier} registrado.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el proveedor.") }
    finally { setBusy(false) }
  }
  function addLine() {
    const selected = choices.find((row) => row.name === item)
    if (!selected || Number(lineQuantity) <= 0 || Number(lineRate) < 0 || !lineRate) return
    setLines((current) => [...current, { item, label: selected.display_name || selected.item_name,
      quantity: lineQuantity, rate: lineRate }])
    setItem(""); setLineQuantity("1"); setLineRate(""); invalidateOrder()
  }
  async function reviewOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!lines.length || busy || !canPurchase || section !== "order-new") return
    setBusy(true); setError(""); setOrderQuote(null)
    try {
      const result = await call<OrderQuote>("preview", { property_name: property.name,
        action: "purchase_order", data: JSON.stringify(orderData()) })
      setOrderQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la orden.") }
    finally { setBusy(false) }
  }
  async function submitOrder() {
    if (!orderQuote || busy || !canPurchase || section !== "order-new") return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ order: string; total: string; currency: string }>(
        property.name, "purchase_order", { ...orderData(), acceptance: orderQuote.acceptance },
        orderQuote.requestKey)
      await refresh(); setOrderQuote(null); setLines([]); setOrderReason("")
      setNotice(`Orden ${result.order} presentada por ${result.currency} ${result.total}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo presentar la orden.") }
    finally { setBusy(false) }
  }
  async function receive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedOrder || busy || !canPurchase || section !== "receive") return
    const items = selectedOrder.items.map((row) => ({ order_item: row.name,
      quantity: receiveQuantity[row.name] || "0" })).filter((row) => Number(row.quantity) > 0)
    if (!items.length) { setError("Indique al menos una cantidad recibida."); return }
    setBusy(true); setError(""); setNotice("")
    const key = receiveKey || crypto.randomUUID(); setReceiveKey(key)
    try {
      const result = await execute<{ receipt: string }>(property.name, "receive_purchase",
        { order: selectedOrder.name, warehouse: receiveWarehouse,
          items, reason: receiveReason.trim() }, key)
      await refresh(); setReceiveQuantity({}); setReceiveReason(""); setReceiveKey("")
      setBillReceipt(result.receipt); setNotice(`Recepción ${result.receipt} presentada.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo recibir la orden.") }
    finally { setBusy(false) }
  }
  async function bill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canPurchase || section !== "bills") return
    setBusy(true); setError(""); setNotice("")
    const key = billKey || crypto.randomUUID(); setBillKey(key)
    try {
      const result = await execute<{ invoice: string; total: string; currency: string }>(
        property.name, "purchase_invoice", { receipt: billReceipt,
          bill_no: billNo.trim(), bill_date: billDate, reason: billReason.trim() }, key)
      await refresh(); setBillReceipt(""); setBillNo(""); setBillReason(""); setBillKey("")
      setPayInvoice(result.invoice)
      setNotice(`Factura ${result.invoice} registrada por ${result.currency} ${result.total}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo facturar la recepción.") }
    finally { setBusy(false) }
  }
  async function reviewPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canFinance || section !== "supplier-pay") return
    setBusy(true); setError(""); setPayQuote(null)
    try {
      const result = await call<PaymentQuote>("preview", { property_name: property.name,
        action: "supplier_payment", data: JSON.stringify({ invoice: payInvoice,
          method: payMethod, amount: payAmount }) })
      setPayQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el pago.") }
    finally { setBusy(false) }
  }
  async function pay() {
    if (!payQuote || busy || !canFinance || section !== "supplier-pay") return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ payment: string; amount: string; currency: string }>(
        property.name, "supplier_payment", { invoice: payInvoice,
          method: payMethod, shift: payShift, amount: payAmount,
          reference: payReference.trim(), reason: payReason.trim(),
          acceptance: payQuote.acceptance }, payQuote.requestKey)
      await refresh(); setPayQuote(null); setPayInvoice(""); setPayAmount(""); setPayReference(""); setPayReason("")
      setNotice(`Pago ${result.payment} registrado por ${result.currency} ${result.amount}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo pagar la factura.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Compras ERPNext</p><h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1><p className="mt-1 text-sm text-muted-foreground">{`${sectionInfo.description}.`}</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section === "suppliers" && canPurchase && <Card><CardHeader><CardTitle>Proveedores habilitados</CardTitle><CardDescription>Estos proveedores pueden usarse en compras del establecimiento.</CardDescription></CardHeader><CardContent className="space-y-2"><Button asChild size="sm"><Link to="?section=supplier-new">Registrar proveedor</Link></Button>{data.suppliers.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm">{row.supplier_name}</p>)}{!data.suppliers.length && <p className="text-sm text-muted-foreground">Sin proveedores habilitados.</p>}</CardContent></Card>}
      {section === "supplier-new" && canPurchase && <Card><CardHeader><CardTitle>Registrar proveedor</CardTitle><CardDescription>Quedará habilitado solo para este establecimiento.</CardDescription></CardHeader><CardContent><form onSubmit={registerSupplier} className="flex flex-wrap gap-2"><Input required maxLength={140} placeholder="Nombre comercial" value={supplierName} onChange={(event) => { setSupplierName(event.target.value); setSupplierKey("") }} className="min-w-48 flex-1" /><Button disabled={busy}>Registrar</Button></form></CardContent></Card>}
      {section === "orders" && canPurchase && <Card><CardHeader><CardTitle>Órdenes abiertas</CardTitle><CardDescription>Busque órdenes pendientes de recepción.</CardDescription></CardHeader><CardContent className="space-y-3"><Button asChild size="sm"><Link to="?section=order-new">Nueva orden</Link></Button><DocumentFinder label="Órdenes" finder={orders} />{orderRows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm"><span>{row.name} · {supplierLabel(row.supplier)}<span className="block text-muted-foreground">{row.currency} {row.grand_total} · recibido {row.per_received}%</span></span>{row.items.some((item) => Number(item.qty) > Number(item.received_qty || 0)) && <Button size="sm" variant="outline" onClick={() => { setReceiveOrder(row.name); setReceiveQuantity({}); setReceiveKey(""); setSearchParams({ section: "receive" }) }}>Recibir</Button>}</div>)}{!orderRows.length && <p className="text-sm text-muted-foreground">Sin órdenes pendientes.</p>}</CardContent></Card>}
      {canPurchase && <>
        {section === "order-new" && <div className="grid gap-5 xl:grid-cols-2">
          <Card><CardHeader><CardTitle>Artículos de la orden</CardTitle><CardDescription>Busque artículos ERPNext habilitados para compra. Máximo cien líneas.</CardDescription></CardHeader><CardContent className="space-y-2"><Input aria-label="Buscar artículo de compra" value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} placeholder="Código o nombre" maxLength={140} /><select value={item} onChange={(event) => setItem(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione artículo</option>{choices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name}</option>)}</select><div className="grid grid-cols-2 gap-2"><Input type="number" min="0.001" step="0.001" aria-label="Cantidad de línea" value={lineQuantity} onChange={(event) => setLineQuantity(event.target.value)} /><Input type="number" min="0" step="0.01" aria-label={`Precio unitario en ${data.currency}`} value={lineRate} onChange={(event) => setLineRate(event.target.value)} placeholder={`Precio ${data.currency}`} /></div><Button type="button" variant="outline" disabled={busy || !item || !lineRate || lines.length >= 100} onClick={addLine}>Añadir línea</Button></CardContent></Card>
        </div>}
        {section === "order-new" && <Card><CardHeader><CardTitle>Nueva orden de compra</CardTitle><CardDescription>Revise el total e impuestos antes de presentarla en ERPNext.</CardDescription></CardHeader><CardContent className="space-y-3"><form onSubmit={reviewOrder} className="grid gap-3 sm:grid-cols-2"><select required value={supplier} onChange={(event) => { setSupplier(event.target.value); invalidateOrder() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Proveedor habilitado</option>{data.suppliers.map((row) => <option key={row.name} value={row.name}>{row.supplier_name}</option>)}</select><select required value={warehouse} onChange={(event) => { setWarehouse(event.target.value); invalidateOrder() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén de recepción</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select><label className="space-y-1 text-sm"><span>Fecha prevista (opcional)</span><Input type="date" value={scheduleDate} onChange={(event) => { setScheduleDate(event.target.value); invalidateOrder() }} /></label><label className="space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={orderReason} onChange={(event) => { setOrderReason(event.target.value); invalidateOrder() }} /></label><div className="space-y-1 text-sm sm:col-span-2">{lines.map((row, index) => <div key={`${row.item}-${index}`} className="flex items-center justify-between gap-2 border-b border-border py-1"><span>{row.label} · {row.quantity} × {data.currency} {row.rate}</span><Button type="button" size="sm" variant="ghost" onClick={() => { setLines((current) => current.filter((_, i) => i !== index)); invalidateOrder() }}>Quitar</Button></div>)}{!lines.length && <p className="text-muted-foreground">Añada al menos un artículo.</p>}</div><div className="sm:col-span-2"><Button disabled={busy || !lines.length}>Revisar orden</Button></div></form>{orderQuote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p>Proveedor: {supplierLabel(orderQuote.supplier)} · {orderQuote.currency} <strong>{orderQuote.total}</strong></p>{orderQuote.taxes.map((tax, index) => <p key={index}>Impuesto {tax.account}: {orderQuote.currency} {tax.amount}</p>)}<Button disabled={busy} onClick={() => void submitOrder()}>Presentar orden</Button></div>}</CardContent></Card>}
        <div className="grid gap-5 xl:grid-cols-2">
          {section === "receive" && <Card><CardHeader><CardTitle>Recibir orden</CardTitle><CardDescription>Registre solo las cantidades físicamente recibidas; puede completar la orden en varias recepciones.</CardDescription></CardHeader><CardContent><DocumentFinder label="Órdenes" finder={orders} /><form onSubmit={receive} className="space-y-3"><select required value={receiveOrder} onChange={(event) => { setReceiveOrder(event.target.value); setReceiveQuantity({}); setReceiveKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Orden pendiente</option>{orderRows.filter((row) => row.items.some((item) => Number(item.qty) > Number(item.received_qty || 0))).map((row) => <option key={row.name} value={row.name}>{row.name} · {supplierLabel(row.supplier)} · {row.currency} {row.grand_total}</option>)}</select>{selectedOrder?.items.filter((row) => Number(row.qty) > Number(row.received_qty || 0)).map((row) => <label key={row.name} className="block space-y-1 text-sm"><span>{row.item_name || row.item_code} · pendiente {Number(row.qty) - Number(row.received_qty || 0)}</span><Input type="number" min="0" max={Number(row.qty) - Number(row.received_qty || 0)} step="0.001" value={receiveQuantity[row.name] || ""} onChange={(event) => { setReceiveQuantity((current) => ({ ...current, [row.name]: event.target.value })); setReceiveKey("") }} placeholder="Cantidad recibida" /></label>)}<select required value={receiveWarehouse} onChange={(event) => { setReceiveWarehouse(event.target.value); setReceiveKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select><Input required maxLength={500} placeholder="Referencia o motivo de recepción" value={receiveReason} onChange={(event) => { setReceiveReason(event.target.value); setReceiveKey("") }} /><Button disabled={busy || !selectedOrder}>Registrar recepción</Button></form></CardContent></Card>}
          {section === "bills" && <Card><CardHeader><CardTitle>Factura del proveedor</CardTitle><CardDescription>Vincule el documento del proveedor a una recepción contabilizada.</CardDescription></CardHeader><CardContent><DocumentFinder label="Recepciones" finder={receipts} /><form onSubmit={bill} className="space-y-3"><select required value={billReceipt} onChange={(event) => { setBillReceipt(event.target.value); setBillKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Recepción sin facturar</option>{billReceipt && !receiptRows.some((row) => row.name === billReceipt) && <option value={billReceipt}>{billReceipt}</option>}{receiptRows.map((row) => <option key={row.name} value={row.name}>{row.name} · {supplierLabel(row.supplier)} · {row.currency} {row.grand_total}</option>)}</select><Input required maxLength={140} placeholder="Número del documento" value={billNo} onChange={(event) => { setBillNo(event.target.value); setBillKey("") }} /><label className="block space-y-1 text-sm"><span>Fecha del documento</span><Input required type="date" value={billDate} onChange={(event) => { setBillDate(event.target.value); setBillKey("") }} /></label><Input maxLength={500} placeholder="Observaciones (opcional)" value={billReason} onChange={(event) => { setBillReason(event.target.value); setBillKey("") }} /><Button disabled={busy}>Registrar factura</Button></form></CardContent></Card>}
        </div>
      </>}
      {section === "payables" && canFinance && <Card>
        <CardHeader><CardTitle>Facturas con saldo</CardTitle><CardDescription>Seleccione una factura para registrar un abono.</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          <Button asChild size="sm"><Link to="?section=supplier-pay">Pagar proveedor</Link></Button>
          <DocumentFinder label="Facturas" finder={invoices} />
          {invoiceRows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
            <span>{row.name} · {supplierLabel(row.supplier)}<span className="block text-muted-foreground">{row.currency} {row.outstanding_amount} pendiente</span></span>
            <Button size="sm" variant="outline" onClick={() => { setPayInvoice(row.name); invalidatePayment(); setSearchParams({ section: "supplier-pay" }) }}>Pagar</Button>
          </div>)}
          {!invoiceRows.length && <p className="text-sm text-muted-foreground">Sin facturas pendientes.</p>}
        </CardContent>
      </Card>}
      {section === "supplier-pay" && canFinance && <Card><CardHeader><CardTitle>Pagar factura</CardTitle><CardDescription>Revise saldo, moneda y tipo de cambio; el pago exige turno abierto y efectivo disponible cuando corresponda.</CardDescription></CardHeader><CardContent className="space-y-3"><DocumentFinder label="Facturas" finder={invoices} /><form onSubmit={reviewPayment} className="grid gap-3 sm:grid-cols-2"><select required value={payInvoice} onChange={(event) => { setPayInvoice(event.target.value); invalidatePayment() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Factura con saldo</option>{payInvoice && !invoiceRows.some((row) => row.name === payInvoice) && <option value={payInvoice}>{payInvoice}</option>}{invoiceRows.map((row) => <option key={row.name} value={row.name}>{row.name} · {supplierLabel(row.supplier)} · pendiente {row.currency} {row.outstanding_amount}</option>)}</select><select required value={payMethod} onChange={(event) => { setPayMethod(event.target.value); invalidatePayment() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de pago</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select><select required value={payShift} onChange={(event) => { setPayShift(event.target.value); invalidatePayment() }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select><Input required type="number" min="0.01" step="0.01" aria-label={`Importe en ${selectedMethod?.currency || "moneda del medio"}`} value={payAmount} onChange={(event) => { setPayAmount(event.target.value); invalidatePayment() }} /><Input required={!!selectedMethod?.reference_required} maxLength={140} placeholder={selectedMethod?.reference_required ? "Referencia obligatoria" : "Referencia (opcional)"} value={payReference} onChange={(event) => { setPayReference(event.target.value); invalidatePayment() }} /><Input required maxLength={500} placeholder="Motivo del pago" value={payReason} onChange={(event) => { setPayReason(event.target.value); invalidatePayment() }} /><div className="sm:col-span-2"><Button disabled={busy || !data.shifts.length}>Revisar pago</Button></div></form>{payQuote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p>Salida: <strong>{payQuote.currency} {payQuote.amount}</strong> · Aplicado al proveedor: <strong>{payQuote.party_currency} {payQuote.party_amount}</strong></p><p>Tipo de cambio: {payQuote.exchange_rate}</p><Button disabled={busy} onClick={() => void pay()}>Registrar pago</Button></div>}</CardContent></Card>}
    </>}
  </div>
}
