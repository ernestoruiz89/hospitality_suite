import { useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { useDirectSaleSection } from "./DirectSaleSections"

type Method = { name: string; mode_of_payment: string; currency: string; is_cash: boolean; reference_required: boolean }
type Series = { name: string; series_code: string; document_type: string; next_number: number; end_number: number }
type Options = { methods: Method[]; shifts: { name: string; cashier: string }[];
  series: Series[]; warehouses: { name: string; warehouse_name: string }[] }
type Customer = { name: string; customer_name: string }
type Product = { name: string; product_code: string; product_name: string; product_type: string; sales_rate: number }
type Page<T> = { rows: T[]; has_more: boolean }
type Sale = { name: string; creation: string; customer_name: string; item_name: string;
  product_type: string; quantity: number; amount: number; currency: string; status: string;
  sales_invoice: string; credit_note: string | null; document_number: string; credit_number: string | null;
  payment: { method: string; amount: number; currency: string; shift: string | null } | null }
type Quote = { customer: string; item: string; product_name: string; quantity: string;
  unit_rate: string; price: string; net_amount: string; tax_amount: string; total: string;
  currency: string; document_number: string; payment_currency: string; payment_amount: string;
  market_rate: string; exchange_rate: string; change: string; acceptance: string; requestKey: string }
type ReturnQuote = { service: string; original_document_number: string; document_number: string;
  total: string; currency: string; refund: { amount: string; currency: string; base_amount: string;
    debit: string; credit: string }; stock_value: string | null; acceptance: string; requestKey: string }
type Issued = { invoice: string; document_number: string; amount: string; currency: string;
  change: string; total: string; base_currency: string }

const pageSize = 25
const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"
const errorText = (error: unknown) => error instanceof Error ? error.message : "No se pudo completar la operación."
const printDocument = (name: string) => `/printview?doctype=${encodeURIComponent("HS PMS Fiscal Document")}&name=${encodeURIComponent(name)}&format=${encodeURIComponent("HS Documento fiscal PMS")}`

export function PmsDirectSales({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const navigate = useNavigate()
  const section = useDirectSaleSection(canApprove)
  const [options, setOptions] = useState<Options | null>(null)
  const [customerSearch, setCustomerSearch] = useState("")
  const [customerOffset, setCustomerOffset] = useState(0)
  const [customers, setCustomers] = useState<Page<Customer> | null>(null)
  const [customer, setCustomer] = useState("")
  const [customerLabel, setCustomerLabel] = useState("")
  const [productSearch, setProductSearch] = useState("")
  const [productOffset, setProductOffset] = useState(0)
  const [products, setProducts] = useState<Page<Product> | null>(null)
  const [item, setItem] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [warehouse, setWarehouse] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [series, setSeries] = useState("")
  const [reference, setReference] = useState("")
  const [tendered, setTendered] = useState("")
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [historySearch, setHistorySearch] = useState("")
  const [historyOffset, setHistoryOffset] = useState(0)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [history, setHistory] = useState<Page<Sale> | null>(null)
  const [returnSale, setReturnSale] = useState("")
  const [returnSeries, setReturnSeries] = useState("")
  const [returnShift, setReturnShift] = useState("")
  const [returnReference, setReturnReference] = useState("")
  const [returnReason, setReturnReason] = useState("")
  const [returnQuote, setReturnQuote] = useState<ReturnQuote | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    call<Options>("pms_direct_sale_options", { property_name: property.name }, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setOptions(value) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, historyRevision])
  useEffect(() => {
    const controller = new AbortController()
    setCustomers(null)
    call<Page<Customer>>("pms_direct_sale_customers", { property_name: property.name,
      search: customerSearch, offset: String(customerOffset), page_length: String(pageSize) }, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setCustomers(value) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, customerSearch, customerOffset])
  useEffect(() => {
    const controller = new AbortController()
    setProducts(null)
    call<Page<Product>>("pms_direct_sale_products", { property_name: property.name,
      search: productSearch, offset: String(productOffset), page_length: String(pageSize) }, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setProducts(value) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, productSearch, productOffset])
  useEffect(() => {
    if (section === "new") return
    const controller = new AbortController()
    setHistory(null)
    call<Page<Sale>>("pms_direct_sale_history", { property_name: property.name,
      search: historySearch, offset: String(historyOffset), page_length: String(pageSize),
      returnable: section === "returns" ? "1" : "0" }, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setHistory(value) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, section, historySearch, historyOffset, historyRevision])

  const selectedProduct = products?.rows.find((row) => row.name === item)
  const selectedMethod = options?.methods.find((row) => row.name === method)
  const selectedReturn = history?.rows.find((row) => row.name === returnSale)
  const returnMethod = options?.methods.find((row) => row.name === selectedReturn?.payment?.method)
  const saleData = () => ({ customer, item, quantity, warehouse: selectedProduct?.product_type === "Stock" ? warehouse : undefined,
    method, shift: selectedMethod?.is_cash ? shift : undefined, series, reference: reference.trim(),
    tendered: selectedMethod?.is_cash && tendered ? tendered : undefined, notes: notes.trim() })
  const returnData = () => ({ service: returnSale, series: returnSeries,
    shift: returnMethod?.is_cash ? returnShift : undefined,
    reference: returnReference.trim(), reason: returnReason.trim() })
  const invalidateSale = () => { setQuote(null); setIssued(null) }
  const invalidateReturn = () => setReturnQuote(null)

  async function reviewSale(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const result = await call<Omit<Quote, "requestKey">>("preview", { property_name: property.name,
        action: "pms_direct_sale", data: JSON.stringify(saleData()) })
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function issueSale() {
    if (!quote || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<Issued>(property.name, "pms_direct_sale",
        { ...saleData(), acceptance: quote.acceptance }, quote.requestKey)
      setIssued(result); setQuote(null)
      setNotice(`Venta ${result.document_number} facturada y cobrada.`)
      setHistoryRevision((value) => value + 1)
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function reviewReturn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canApprove || busy) return
    setBusy(true); setError(""); setNotice(""); setReturnQuote(null)
    try {
      const result = await call<Omit<ReturnQuote, "requestKey">>("pms_direct_sale_return_quote",
        { property_name: property.name, data: JSON.stringify(returnData()) })
      setReturnQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function issueReturn() {
    if (!returnQuote || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ credit_note: string; document_number: string }>(property.name,
        "pms_direct_sale_return", { ...returnData(), acceptance: returnQuote.acceptance }, returnQuote.requestKey)
      setReturnSale(""); setReturnQuote(null); setReturnReason(""); setReturnReference("")
      setNotice(`Venta devuelta. Nota de crédito ${result.document_number}.`)
      setHistoryRevision((value) => value + 1)
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Ventas directas</h1><p className="mt-1 text-sm text-muted-foreground">{property.brand_name || property.property_name} · Facturación de mostrador sin estancia en PMS.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {issued && <Card><CardHeader><CardTitle>Factura {issued.document_number}</CardTitle><CardDescription>Cobro {issued.currency} {issued.amount} · Vuelto {issued.currency} {issued.change}</CardDescription></CardHeader><CardContent className="flex gap-2"><Button asChild variant="outline"><a href={printDocument(issued.invoice)} target="_blank" rel="noopener noreferrer">Consultar e imprimir</a></Button><Button variant="outline" onClick={() => { setIssued(null); navigate("/direct-sales?section=history") }}>Ver historial</Button></CardContent></Card>}
    {section === "new" && <>
      <Card><CardHeader><CardTitle>Pagador</CardTitle><CardDescription>Seleccione una persona o empresa de este establecimiento.</CardDescription></CardHeader><CardContent className="space-y-3">
        <form onSubmit={(event) => { event.preventDefault(); setCustomerOffset(0); setCustomerSearch(String(new FormData(event.currentTarget).get("search") || "").trim()) }} className="flex gap-2"><Input name="search" aria-label="Buscar pagador" maxLength={100} placeholder="Nombre o código" /><Button type="submit" variant="outline">Buscar</Button></form>
        {customer && <p className="text-sm">Seleccionado: <strong>{customerLabel}</strong></p>}
        {!customers ? <Skeleton className="h-20" /> : <><div className="max-h-44 space-y-1 overflow-auto">{customers.rows.map((row) => <button type="button" key={row.name} onClick={() => { setCustomer(row.name); setCustomerLabel(row.customer_name); invalidateSale() }} className={`block w-full rounded-md border p-2 text-left text-sm hover:bg-secondary ${customer === row.name ? "border-primary bg-secondary/50" : "border-border"}`}>{row.customer_name}<span className="block text-xs text-muted-foreground">{row.name}</span></button>)}{!customers.rows.length && <p className="text-sm text-muted-foreground">Sin pagadores para esta búsqueda.</p>}</div><div className="flex gap-2"><Button variant="outline" disabled={!customerOffset} onClick={() => setCustomerOffset(Math.max(0, customerOffset - pageSize))}>Anterior</Button><Button variant="outline" disabled={!customers.has_more} onClick={() => setCustomerOffset(customerOffset + pageSize)}>Siguiente</Button></div></>}
        <p className="text-xs text-muted-foreground">Si falta un pagador, regístrelo en <Link to="/reception?section=guest-new" className="underline">Recepción</Link>.</p>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Artículo y cobro</CardTitle><CardDescription>Seleccione serie fiscal, medio de pago y almacén para artículos físicos.</CardDescription></CardHeader><CardContent className="space-y-4">{!options ? <Skeleton className="h-64" /> : <>
        <form onSubmit={(event) => void reviewSale(event)} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm sm:col-span-2"><span>Buscar artículo</span><Input maxLength={100} value={productSearch} onChange={(event) => { setProductSearch(event.target.value); setProductOffset(0); setItem(""); invalidateSale() }} placeholder="Código o nombre" /></label>
          <label className="space-y-1 text-sm"><span>Artículo</span><select required className={selectClass} value={item} onChange={(event) => { setItem(event.target.value); setWarehouse(""); invalidateSale() }}><option value="">Seleccione artículo</option>{products?.rows.map((row) => <option key={row.name} value={row.name}>{row.product_name} · {row.product_code}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidateSale() }} /></label>
          {selectedProduct?.product_type === "Stock" && <label className="space-y-1 text-sm"><span>Almacén</span><select required className={selectClass} value={warehouse} onChange={(event) => { setWarehouse(event.target.value); invalidateSale() }}><option value="">Seleccione almacén</option>{options.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select></label>}
          <label className="space-y-1 text-sm"><span>Serie de factura</span><select required className={selectClass} value={series} onChange={(event) => { setSeries(event.target.value); invalidateSale() }}><option value="">Seleccione serie</option>{options.series.filter((row) => row.document_type === "Invoice" && row.next_number <= row.end_number).map((row) => <option key={row.name} value={row.name}>{row.series_code}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Medio de pago</span><select required className={selectClass} value={method} onChange={(event) => { setMethod(event.target.value); setShift(""); setTendered(""); invalidateSale() }}><option value="">Seleccione medio</option>{options.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
          {selectedMethod?.is_cash && <label className="space-y-1 text-sm"><span>Turno propio abierto</span><select required className={selectClass} value={shift} onChange={(event) => { setShift(event.target.value); invalidateSale() }}><option value="">Seleccione turno</option>{options.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></label>}
          <label className="space-y-1 text-sm"><span>Referencia{selectedMethod?.reference_required ? " obligatoria" : ""}</span><Input required={!!selectedMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { setReference(event.target.value); invalidateSale() }} /></label>
          {selectedMethod?.is_cash && <label className="space-y-1 text-sm"><span>Recibido ({selectedMethod.currency})</span><Input type="number" min="0" step="0.01" value={tendered} onChange={(event) => { setTendered(event.target.value); invalidateSale() }} placeholder="Vacío = exacto" /></label>}
          <label className="space-y-1 text-sm sm:col-span-2"><span>Notas</span><Input maxLength={500} value={notes} onChange={(event) => { setNotes(event.target.value); invalidateSale() }} /></label>
          <Button type="submit" variant="outline" disabled={busy || !customer || !item || !method || !series || !!selectedMethod?.is_cash && !shift || selectedProduct?.product_type === "Stock" && !warehouse}>Cotizar venta</Button>
        </form>
        {products && <div className="flex gap-2"><Button variant="outline" disabled={!productOffset} onClick={() => setProductOffset(Math.max(0, productOffset - pageSize))}>Artículos anteriores</Button><Button variant="outline" disabled={!products.has_more} onClick={() => setProductOffset(productOffset + pageSize)}>Más artículos</Button></div>}
        {quote && <div className="space-y-2 rounded-lg border border-primary/30 bg-secondary/50 p-4 text-sm"><p><strong>{quote.document_number}</strong> · {quote.product_name} × {quote.quantity}</p><p>Neto {quote.currency} {quote.net_amount} · Impuesto {quote.currency} {quote.tax_amount}</p><p>Factura: <strong>{quote.currency} {quote.total}</strong></p><p>Cobro: <strong>{quote.payment_currency} {quote.payment_amount}</strong>{quote.payment_currency !== quote.currency && ` · Cambio de mercado ${quote.market_rate} · Cambio aplicado ${quote.exchange_rate}`}</p><p>Vuelto: {quote.payment_currency} {quote.change}</p><Button disabled={busy} onClick={() => void issueSale()}>Emitir factura y cobrar</Button></div>}
        <p className="text-xs text-muted-foreground">El usuario verifica el registro y la autorización fiscal antes de imprimir.</p>
      </>}</CardContent></Card>
    </>}
    {section !== "new" && <Card><CardHeader><CardTitle>{section === "returns" ? "Devoluciones" : "Historial de ventas"}</CardTitle><CardDescription>Busque por factura, venta, pagador o artículo.</CardDescription></CardHeader><CardContent className="space-y-4">
      <form onSubmit={(event) => { event.preventDefault(); setHistoryOffset(0); setHistorySearch(String(new FormData(event.currentTarget).get("search") || "").trim()); setReturnSale("") }} className="flex gap-2"><Input name="search" aria-label="Buscar ventas" maxLength={100} /><Button type="submit" variant="outline">Buscar</Button></form>
      {!history ? <Skeleton className="h-40" /> : <><div className="space-y-2">{history.rows.map((row) => <div key={row.name} className="rounded-md border p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><div><strong>{row.document_number}</strong><p>{row.customer_name} · {row.item_name} × {row.quantity}</p><p className="text-xs text-muted-foreground">{row.name} · {row.status === "Returned" ? "Devuelta" : "Entregada"} · {new Date(row.creation).toLocaleString("es-NI")}</p></div><div>{row.currency} {row.amount}{row.payment && <span className="block text-xs text-muted-foreground">Cobro {row.payment.currency} {row.payment.amount}</span>}</div></div><div className="mt-2 flex flex-wrap gap-2"><Button asChild size="sm" variant="outline"><a href={printDocument(row.sales_invoice)} target="_blank" rel="noopener noreferrer">Factura</a></Button>{row.credit_note && <Button asChild size="sm" variant="outline"><a href={printDocument(row.credit_note)} target="_blank" rel="noopener noreferrer">Nota de crédito</a></Button>}{section === "returns" && row.status === "Delivered" && <Button size="sm" variant="outline" onClick={() => { setReturnSale(row.name); setReturnQuote(null); setReturnSeries(""); setReturnShift(""); setReturnReference(""); setReturnReason("") }}>Devolver</Button>}</div></div>)}{!history.rows.length && <p className="text-sm text-muted-foreground">Sin ventas para este criterio.</p>}</div><div className="flex gap-2"><Button variant="outline" disabled={!historyOffset} onClick={() => { setHistoryOffset(Math.max(0, historyOffset - pageSize)); setReturnSale("") }}>Anterior</Button><Button variant="outline" disabled={!history.has_more} onClick={() => { setHistoryOffset(historyOffset + pageSize); setReturnSale("") }}>Siguiente</Button></div></>}
      {section === "returns" && selectedReturn && <form onSubmit={(event) => void reviewReturn(event)} className="space-y-3 rounded-lg bg-secondary p-4 text-sm"><p>Devolución completa de factura <strong>{selectedReturn.document_number}</strong>. Se restituirá el inventario si corresponde.</p><label className="block space-y-1"><span>Serie de nota de crédito</span><select required className={selectClass} value={returnSeries} onChange={(event) => { setReturnSeries(event.target.value); invalidateReturn() }}><option value="">Seleccione serie</option>{options?.series.filter((row) => row.document_type === "Credit Note" && row.next_number <= row.end_number).map((row) => <option key={row.name} value={row.name}>{row.series_code}</option>)}</select></label>{returnMethod?.is_cash && <label className="block space-y-1"><span>Turno propio abierto</span><select required className={selectClass} value={returnShift} onChange={(event) => { setReturnShift(event.target.value); invalidateReturn() }}><option value="">Seleccione turno</option>{options?.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></label>}<label className="block space-y-1"><span>Referencia del reembolso</span><Input required maxLength={140} value={returnReference} onChange={(event) => { setReturnReference(event.target.value); invalidateReturn() }} /></label><label className="block space-y-1"><span>Motivo</span><Input required maxLength={500} value={returnReason} onChange={(event) => { setReturnReason(event.target.value); invalidateReturn() }} /></label><div className="flex gap-2"><Button type="submit" variant="outline" disabled={busy}>Revisar devolución</Button><Button type="button" variant="outline" onClick={() => { setReturnSale(""); setReturnQuote(null) }}>Cancelar</Button></div>{returnQuote && <div className="rounded-md border border-primary/30 bg-white p-3"><p>Nota {returnQuote.document_number} · Reembolso <strong>{returnQuote.refund.currency} {returnQuote.refund.amount}</strong></p><p>Asiento: débito {returnQuote.refund.debit} / crédito {returnQuote.refund.credit} · {returnQuote.currency} {returnQuote.refund.base_amount}</p>{returnQuote.stock_value && <p>Inventario a restituir: {returnQuote.currency} {returnQuote.stock_value}</p>}<Button type="button" className="mt-3" disabled={busy} onClick={() => void issueReturn()}>Emitir nota y reembolsar</Button></div>}</form>}
    </CardContent></Card>}
  </div>
}
