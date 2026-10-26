import { useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { useDirectSaleSection } from "./DirectSaleSections"

type Method = { name: string; mode_of_payment: string; currency: string;
  is_cash: boolean; reference_required: boolean }
type Shift = { name: string; cashier: string; currency: string }
type Options = { property: string; currency: string; can_approve: boolean;
  methods: Method[]; shifts: Shift[] }
type Customer = { name: string; customer_name: string }
type CustomerPage = { rows: Customer[]; has_more: boolean }
type Item = { name: string; item_name: string; display_name?: string }
type Sale = { name: string; creation: string; customer: string;
  customer_name: string | null; item: string; item_name: string | null;
  quantity: number; amount: number;
  currency: string; status: string; sales_invoice: string; credit_note: string | null;
  payment: { method: string; amount: number; currency: string; shift: string } | null }
type SalePage = { rows: Sale[]; has_more: boolean }
type Quote = { customer: string; item: string; quantity: string; rate: string;
  total: string; currency: string; method: string; payment_amount: string;
  payment_currency: string; exchange_rate: string; acceptance: string;
  requestKey: string }
type Issued = { service: string; invoice: string; payment: string;
  amount: string; currency: string; change: string }

const PAGE_LENGTH = 25
const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"
const errorText = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo completar la operación."
const invoicePrint = (name: string) => `/printview?doctype=${encodeURIComponent("Sales Invoice")}&name=${encodeURIComponent(name)}`
const statusLabels: Record<string, string> = { Delivered: "Entregada", Returned: "Devuelta" }

export function ErpDirectSales({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const navigate = useNavigate()
  const section = useDirectSaleSection(canApprove)
  const [options, setOptions] = useState<Options | null>(null)
  const [customerInput, setCustomerInput] = useState("")
  const [customerSearch, setCustomerSearch] = useState("")
  const [customerOffset, setCustomerOffset] = useState(0)
  const [customers, setCustomers] = useState<CustomerPage | null>(null)
  const [customer, setCustomer] = useState("")
  const [customerLabel, setCustomerLabel] = useState("")
  const [itemInput, setItemInput] = useState("")
  const [items, setItems] = useState<Item[]>([])
  const [item, setItem] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [reference, setReference] = useState("")
  const [tendered, setTendered] = useState("")
  const [notes, setNotes] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [historyInput, setHistoryInput] = useState("")
  const [historySearch, setHistorySearch] = useState("")
  const [historyOffset, setHistoryOffset] = useState(0)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [history, setHistory] = useState<SalePage | null>(null)
  const [returnSale, setReturnSale] = useState("")
  const [returnShift, setReturnShift] = useState("")
  const [returnReason, setReturnReason] = useState("")
  const [returnKey, setReturnKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setOptions(null); setError("")
    call<Options>("erp_direct_sale_options", { property_name: property.name }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setOptions(result) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, historyRevision])

  useEffect(() => {
    const controller = new AbortController()
    setCustomers(null)
    call<CustomerPage>("erp_direct_sale_customers", { property_name: property.name,
      search: customerSearch, offset: String(customerOffset), page_length: String(PAGE_LENGTH),
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setCustomers(result)
    }).catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, customerSearch, customerOffset])

  useEffect(() => {
    if (section !== "new") return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ items: Item[] }>("catalog_search", { property_name: property.name,
        txt: itemInput, purpose: "sale" }, controller.signal).then((result) => {
        if (!controller.signal.aborted) setItems(result.items)
      }).catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    }, 200)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [property.name, itemInput, section])

  useEffect(() => {
    if (section === "new") return
    const controller = new AbortController()
    setHistory(null)
    call<SalePage>("erp_direct_sale_history", { property_name: property.name,
      search: historySearch, offset: String(historyOffset), page_length: String(PAGE_LENGTH),
      returnable: section === "returns" ? "1" : "0",
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setHistory(result)
    }).catch((issue: unknown) => { if (!controller.signal.aborted) setError(errorText(issue)) })
    return () => controller.abort()
  }, [property.name, section, historySearch, historyOffset, historyRevision])

  const selectedMethod = options?.methods.find((row) => row.name === method)
  const selectedReturn = history?.rows.find((row) => row.name === returnSale)
  const invalidate = () => { setQuote(null); setIssued(null); setError("") }
  const saleData = () => ({ customer, item, quantity, method, shift,
    reference: reference.trim(), tendered: tendered || undefined, notes: notes.trim() })
  function searchCustomers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setCustomerOffset(0); setCustomerSearch(customerInput.trim())
  }
  function searchHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setHistoryOffset(0); setHistorySearch(historyInput.trim())
    setReturnSale(""); setReturnKey("")
  }
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !customer || !item || !method || !shift) return
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const result = await call<Omit<Quote, "requestKey">>("preview", {
        property_name: property.name, action: "direct_sale",
        data: JSON.stringify(saleData()),
      })
      if (result.customer !== customer || result.item !== item || result.method !== method)
        throw new Error("La cotización no coincide con la selección.")
      setQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function issue() {
    if (!quote || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<Issued>(property.name, "direct_sale",
        { ...saleData(), acceptance: quote.acceptance }, quote.requestKey)
      setIssued(result); setQuote(null)
      setNotice(`Venta facturada y cobrada. Factura ${result.invoice}.`)
      setHistoryRevision((value) => value + 1)
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canApprove || !selectedReturn || busy || !returnShift || !returnReason.trim()) return
    const key = returnKey || crypto.randomUUID()
    setReturnKey(key); setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ credit_note: string }>(property.name,
        "return_direct_sale", { service: selectedReturn.name, shift: returnShift,
          reason: returnReason.trim() }, key)
      setReturnSale(""); setReturnShift(""); setReturnReason(""); setReturnKey("")
      setNotice(`Venta devuelta. Nota de crédito ${result.credit_note}.`)
      setHistoryRevision((value) => value + 1)
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Ventas directas</h1>
      <p className="mt-1 text-sm text-muted-foreground">{property.brand_name || property.property_name} · {section === "new" ? "Facture y cobre un artículo sin estancia." : section === "returns" ? "Gerencia puede devolver una venta completa." : "Consulte los comprobantes de mostrador."}</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {issued && <Card><CardHeader><CardTitle>Factura {issued.invoice}</CardTitle><CardDescription>Cobro {issued.currency} {issued.amount} · Vuelto {issued.currency} {issued.change}</CardDescription></CardHeader>
      <CardContent className="flex flex-wrap gap-2"><Button asChild variant="outline"><a href={invoicePrint(issued.invoice)} target="_blank" rel="noopener noreferrer">Consultar e imprimir</a></Button>
        <Button variant="outline" onClick={() => { setIssued(null); navigate("/direct-sales?section=history") }}>Ver historial</Button></CardContent></Card>}
    {section === "new" && <>
      <Card><CardHeader><CardTitle>Pagador</CardTitle><CardDescription>Seleccione una persona o empresa registrada en este establecimiento.</CardDescription></CardHeader>
        <CardContent className="space-y-3"><form onSubmit={searchCustomers} className="flex gap-2"><Input aria-label="Buscar pagador" maxLength={100} value={customerInput} onChange={(event) => setCustomerInput(event.target.value)} placeholder="Nombre o código" /><Button type="submit" variant="outline">Buscar</Button></form>
          {customer && <p className="text-sm">Seleccionado: <strong>{customerLabel || customer}</strong></p>}
          {!customers ? <Skeleton className="h-20" /> : <><div className="max-h-44 space-y-1 overflow-auto">{customers.rows.map((row) => <button type="button" key={row.name}
            onClick={() => { setCustomer(row.name); setCustomerLabel(row.customer_name); invalidate() }} className={`block w-full rounded-md border p-2 text-left text-sm hover:bg-secondary ${customer === row.name ? "border-primary bg-secondary/50" : "border-border"}`}>{row.customer_name}<span className="block text-xs text-muted-foreground">{row.name}</span></button>)}
            {!customers.rows.length && <p className="text-sm text-muted-foreground">Sin pagadores para esta búsqueda.</p>}</div>
            <div className="flex gap-2"><Button variant="outline" disabled={!customerOffset} onClick={() => setCustomerOffset(Math.max(0, customerOffset - PAGE_LENGTH))}>Anterior</Button><Button variant="outline" disabled={!customers.has_more} onClick={() => setCustomerOffset(customerOffset + PAGE_LENGTH)}>Siguiente</Button></div></>}
          <p className="text-xs text-muted-foreground">Si falta un pagador, regístrelo desde <Link to="/reception?section=guest-new" className="underline">Recepción</Link> con el permiso correspondiente.</p>
        </CardContent></Card>
      <Card><CardHeader><CardTitle>Artículo y cobro</CardTitle><CardDescription>El precio, los impuestos y la moneda del medio se calculan al cotizar.</CardDescription></CardHeader>
        <CardContent className="space-y-4">{!options ? <Skeleton className="h-64" /> : <>
          {!options.shifts.length && <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">Abra su turno en <Link to="/cash?section=shift-open" className="underline">Caja</Link> antes de vender.</p>}
          <form onSubmit={(event) => void review(event)} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm sm:col-span-2"><span>Buscar artículo</span><Input maxLength={140} value={itemInput} onChange={(event) => { setItemInput(event.target.value); setItem(""); invalidate() }} placeholder="Código o nombre" /></label>
            <label className="space-y-1 text-sm"><span>Artículo</span><select required value={item} onChange={(event) => { setItem(event.target.value); invalidate() }} className={selectClass}><option value="">Seleccione artículo</option>{items.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name} · {row.name}</option>)}</select></label>
            <label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidate() }} /></label>
            <label className="space-y-1 text-sm"><span>Medio de pago</span><select required value={method} onChange={(event) => { setMethod(event.target.value); setReference(""); setTendered(""); invalidate() }} className={selectClass}><option value="">Seleccione medio</option>{options.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
            <label className="space-y-1 text-sm"><span>Turno abierto</span><select required value={shift} onChange={(event) => { setShift(event.target.value); invalidate() }} className={selectClass}><option value="">Seleccione turno</option>{options.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
            <label className="space-y-1 text-sm"><span>Referencia{selectedMethod?.reference_required ? " obligatoria" : ""}</span><Input required={!!selectedMethod?.reference_required} maxLength={140} value={reference} onChange={(event) => { setReference(event.target.value); invalidate() }} /></label>
            {selectedMethod?.is_cash && <label className="space-y-1 text-sm"><span>Recibido ({selectedMethod.currency})</span><Input type="number" min="0" step="0.01" value={tendered} onChange={(event) => { setTendered(event.target.value); invalidate() }} placeholder="Vacío = importe exacto" /></label>}
            <label className="space-y-1 text-sm sm:col-span-2"><span>Notas</span><Input maxLength={500} value={notes} onChange={(event) => { setNotes(event.target.value); invalidate() }} /></label>
            <Button type="submit" variant="outline" disabled={busy || !customer || !item || !method || !shift}>Cotizar venta</Button>
          </form>
          {quote && <div className="space-y-2 rounded-lg border border-primary/30 bg-secondary/50 p-4 text-sm"><p>{customerLabel || customer} · {quote.quantity} × {item}</p>
            <p>Precio unitario: {quote.currency} {quote.rate}</p><p>Factura con impuestos: <strong>{quote.currency} {quote.total}</strong></p>
            <p>Cobro: <strong>{quote.payment_currency} {quote.payment_amount}</strong>{quote.payment_currency !== quote.currency && ` · Cambio ${quote.exchange_rate}`}</p>
            {selectedMethod?.is_cash && tendered && <p>Vuelto previsto: {quote.payment_currency} {(Number(tendered) - Number(quote.payment_amount)).toFixed(2)}</p>}
            <Button disabled={busy || !!tendered && Number(tendered) < Number(quote.payment_amount)} onClick={() => void issue()}>Emitir factura y cobrar</Button></div>}
          <p className="text-xs text-muted-foreground">El usuario verifica el registro y la autorización fiscal antes de imprimir.</p>
        </>}</CardContent></Card>
    </>}
    {section !== "new" && <Card><CardHeader><CardTitle>{section === "returns" ? "Devolver venta" : "Historial de ventas"}</CardTitle>
      <CardDescription>Busque por factura, venta, pagador o artículo. Se excluyen los Day Pass.</CardDescription></CardHeader><CardContent className="space-y-4">
      <form onSubmit={searchHistory} className="flex gap-2"><Input aria-label="Buscar ventas" maxLength={100} value={historyInput} onChange={(event) => setHistoryInput(event.target.value)} /><Button type="submit" variant="outline">Buscar</Button></form>
      {!history ? <Skeleton className="h-40" /> : <><div className="space-y-2">{history.rows.map((row) => <div key={row.name} className="rounded-md border p-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><div><strong>{row.sales_invoice}</strong><p>{row.customer_name || row.customer} · {row.item_name || row.item} × {row.quantity}</p>
          <p className="text-xs text-muted-foreground">{row.name} · {statusLabels[row.status] || row.status} · {new Date(row.creation).toLocaleString("es-NI")}</p></div>
          <p>{row.currency} {row.amount}{row.payment && <span className="block text-xs text-muted-foreground">Cobro {row.payment.currency} {row.payment.amount}</span>}</p></div>
        <div className="mt-2 flex flex-wrap gap-2"><Button asChild size="sm" variant="outline"><a href={invoicePrint(row.sales_invoice)} target="_blank" rel="noopener noreferrer">Factura</a></Button>
          {row.credit_note && <Button asChild size="sm" variant="outline"><a href={invoicePrint(row.credit_note)} target="_blank" rel="noopener noreferrer">Nota de crédito</a></Button>}
          {section === "returns" && canApprove && row.status === "Delivered" && <Button size="sm" variant="outline" onClick={() => { setReturnSale(row.name); setReturnShift(""); setReturnReason(""); setReturnKey("") }}>Devolver</Button>}</div>
      </div>)}{!history.rows.length && <p className="text-sm text-muted-foreground">No hay ventas con ese criterio.</p>}</div>
      <div className="flex gap-2"><Button variant="outline" disabled={!historyOffset} onClick={() => { setHistoryOffset(Math.max(0, historyOffset - PAGE_LENGTH)); setReturnSale("") }}>Anterior</Button><Button variant="outline" disabled={!history.has_more} onClick={() => { setHistoryOffset(historyOffset + PAGE_LENGTH); setReturnSale("") }}>Siguiente</Button></div></>}
      {section === "returns" && selectedReturn && <form onSubmit={(event) => void refund(event)} className="space-y-3 rounded-lg bg-secondary p-4 text-sm"><p>Se emitirá una nota de crédito completa y se devolverá el cobro original de <strong>{selectedReturn.sales_invoice}</strong>.</p>
        <label className="block space-y-1"><span>Turno abierto para devolver</span><select required className={selectClass} value={returnShift} onChange={(event) => { setReturnShift(event.target.value); setReturnKey("") }}><option value="">Seleccione turno</option>{options?.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
        <label className="block space-y-1"><span>Motivo</span><Input required maxLength={500} value={returnReason} onChange={(event) => { setReturnReason(event.target.value); setReturnKey("") }} /></label>
        <div className="flex gap-2"><Button disabled={busy || !returnShift}>Confirmar devolución</Button><Button type="button" variant="outline" onClick={() => setReturnSale("")}>Cancelar</Button></div></form>}
    </CardContent></Card>}
  </div>
}
