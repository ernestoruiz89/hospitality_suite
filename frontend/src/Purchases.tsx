import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { OpeningSupplierCreditsPms } from "./OpeningSupplierCreditsPms"
import { purchaseSections, usePurchaseSection, type PurchaseSection } from "./PurchaseSections"
import { useIdempotentCommand, type SendCommand } from "./useIdempotentCommand"

type Account = { name: string; account_code: string; account_name: string;
  root_type: string; account_type: string }
type PurchaseLine = { product: string; warehouse: string; quantity: string;
  invoice_amount: string; recoverable_tax: string }
const emptyLine = (): PurchaseLine => ({ product: "", warehouse: "", quantity: "",
  invoice_amount: "", recoverable_tax: "0" })
type Purchase = { name: string; supplier: string; supplier_reference: string;
  purchase_order: string | null;
  product: string; warehouse: string; quantity: number; invoice_currency: string;
  invoice_amount: number; recoverable_tax: number; base_amount: number; base_cost: number;
  base_tax: number; business_date: string; outstanding: string;
  status: string; cancellation_return: string | null;
  lines: { product: string; warehouse: string; quantity: number; invoice_amount: number;
    base_cost: number; stock_movement: string | null }[] }
type OpeningPayable = { name: string; supplier: string; opening_source_name: string;
  business_date: string; due_date: string; currency: string; amount: number;
  base_amount: number; outstanding: string; base_outstanding: string;
  payable_account: string }
type ReturnRow = { name: string; purchase: string; supplier: string; reference: string;
  kind: string;
  invoice_currency: string; credit_amount: number; base_credit: number;
  supplier_credit: number; refund_available: string; business_date: string }
type OrderLine = { name: string; product: string; warehouse: string; quantity: string;
  received_quantity: string; remaining_quantity: string;
  amount: string; recoverable_tax: string }
type Order = { name: string; supplier: string; reference: string; currency: string;
  payable_account: string; tax_account: string | null; amount: number;
  recoverable_tax: number; expected_date: string | null; requested_by: string;
  approved_by: string | null; status: string; progress: string; modified: string;
  close_reason: string | null; lines: OrderLine[] }
type Snapshot = { currency: string; currencies: string[];
  suppliers: { name: string; party_name: string; tax_id?: string }[];
  products: { name: string; product_code: string; product_name: string }[];
  warehouses: { name: string; warehouse_name: string }[];
  accounts: Account[];
  methods: { name: string; mode_of_payment: string; currency: string; is_cash: boolean }[];
  shifts: { name: string; opened_at: string }[];
  purchases: Purchase[];
  opening_payables: OpeningPayable[];
  opening_supplier_credits: {
    credits: { name: string; supplier: string; opening_source_name: string;
      currency: string; amount: number; base_amount: number;
      available: string; base_available: string }[];
    applications: { name: string; opening_credit: string; target_type: string;
      opening_payable: string | null; purchase: string | null;
      currency: string; remaining: string }[] };
  orders: Order[];
  returns: ReturnRow[];
  payments: { name: string; kind: string; pms_purchase: string | null;
    pms_opening_payable: string | null;
    pms_opening_supplier_credit?: string | null;
    pms_purchase_return: string | null; amount: number; currency: string;
    base_amount: number; method: string; reference: string; business_date: string;
    pms_settlement_currency?: string | null; pms_settled_amount?: number | null;
    pms_released_base_amount?: number | null }[] }
type PurchaseQuote = { acceptance: string; supplier_name: string;
  lines: { product_name: string; quantity: string; invoice_amount: string;
    recoverable_tax: string; base_cost: string }[];
  invoice_currency: string; invoice_amount: string; recoverable_tax: string;
  exchange_rate: string; base_currency: string; base_amount: string; base_cost: string;
  base_tax: string; inventory_account: string; payable_account: string; tax_account?: string }
type PaymentQuote = { acceptance: string; purchase: string; amount: string; currency: string;
  exchange_rate: string; base_amount: string; base_currency: string;
  outstanding_before: string; outstanding_after: string;
  payable_account: string; cash_account: string;
  settled_amount?: string; settlement_currency?: string;
  payable_release_base?: string; exchange_variance_base?: string;
  base_outstanding_after?: string }
type ReturnQuote = { acceptance: string | null; invoice_currency: string;
  credit_amount: string; base_credit: string; base_tax: string; stock_value: string;
  variance: string; variance_nature: "Income" | "Expense" | null;
  payable_applied: string; supplier_credit: string;
  lines: { product: string; quantity: string; credit_amount: string;
    stock_value: string }[] }
type RefundQuote = { acceptance: string; amount: string; currency: string;
  base_amount: string; available_before: string; available_after: string;
  cash_account: string; payable_account: string }

export function Purchases({ property, canPurchase, canApprove }: {
  property: Property; canPurchase: boolean; canApprove: boolean }) {
  const send = useIdempotentCommand(property.name)
  const navigate = useNavigate()
  const section = usePurchaseSection(canPurchase, canApprove)
  const sectionInfo = purchaseSections.find((item) => item.id === section)!
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [supplierName, setSupplierName] = useState("")
  const [supplierTaxId, setSupplierTaxId] = useState("")
  const [supplier, setSupplier] = useState("")
  const [billReference, setBillReference] = useState("")
  const [lineRows, setLineRows] = useState<PurchaseLine[]>([emptyLine()])
  const [currency, setCurrency] = useState(property.currency)
  const [payableAccount, setPayableAccount] = useState("")
  const [taxAccount, setTaxAccount] = useState("")
  const [purchaseNotes, setPurchaseNotes] = useState("")
  const [purchaseQuote, setPurchaseQuote] = useState<PurchaseQuote | null>(null)
  const [selectedPurchase, setSelectedPurchase] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [paymentAmount, setPaymentAmount] = useState("")
  const [settledAmount, setSettledAmount] = useState("")
  const [paymentReference, setPaymentReference] = useState("")
  const [paymentReason, setPaymentReason] = useState("")
  const [paymentQuote, setPaymentQuote] = useState<PaymentQuote | null>(null)
  const refresh = useCallback(async () => setData(await call<Snapshot>("pms_purchase_snapshot",
    { property_name: property.name })), [property.name])
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar la compra.`) }
  }
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setSupplierName(""); setSupplierTaxId("");
    setSupplier(""); setBillReference(""); setLineRows([emptyLine()]);
    setCurrency(property.currency); setPayableAccount(""); setTaxAccount("");
    setPurchaseNotes(""); setPurchaseQuote(null)
    setSelectedPurchase(""); setMethod(""); setShift(""); setPaymentAmount(""); setSettledAmount("");
    setPaymentReference(""); setPaymentReason(""); setPaymentQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar las compras."))
  }, [refresh, property.currency])
  const changePurchase = () => setPurchaseQuote(null)
  const changePayment = () => setPaymentQuote(null)
  const totalTax = lineRows.reduce((total, row) => total + Number(row.recoverable_tax || 0), 0)
  const purchaseData = { supplier, supplier_reference: billReference.trim(),
    lines: lineRows.map((row) => ({ ...row, recoverable_tax: row.recoverable_tax || "0" })),
    invoice_currency: currency, payable_account: payableAccount,
    tax_account: totalTax > 0 ? taxAccount : null, notes: purchaseNotes.trim() }
  const updateLine = (index: number, field: keyof PurchaseLine, value: string) => {
    changePurchase(); setLineRows((rows) => rows.map((row, position) =>
      position === index ? { ...row, [field]: value } : row))
  }
  const selectedMethod = data?.methods.find((row) => row.name === method)
  const isOpeningPayment = selectedPurchase.startsWith("opening:")
  const selectedOpening = isOpeningPayment ? data?.opening_payables.find((row) =>
    row.name === selectedPurchase.slice(8)) : undefined
  const foreignOpening = !!selectedOpening && selectedOpening.currency !== data?.currency
  const paymentData = { [isOpeningPayment ? "payable" : "purchase"]:
      isOpeningPayment ? selectedPurchase.slice(8) : selectedPurchase,
    method, amount: paymentAmount,
    ...(foreignOpening ? { settled_amount: settledAmount } : {}),
    shift: selectedMethod?.is_cash ? shift : null,
    reference: paymentReference.trim(), reason: paymentReason.trim() }
  const supplierLabel = (id: string) => data?.suppliers.find((row) => row.name === id)?.party_name || id
  const productLabel = (id: string) => data?.products.find((row) => row.name === id)?.product_name || id

  async function createSupplier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_supplier", {
        party_name: supplierName.trim(), tax_id: supplierTaxId.trim(),
      })
      setSupplierName(""); setSupplierTaxId("")
      await refreshAfter("Proveedor registrado.")
      navigate("/purchases?section=suppliers")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el proveedor.") }
    finally { setBusy(false) }
  }
  async function receive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!purchaseQuote) {
        setPurchaseQuote(await call<PurchaseQuote>("pms_purchase_quote",
          { property_name: property.name, data: JSON.stringify(purchaseData) }))
      } else {
        await send("pms_receive_purchase", { ...purchaseData, acceptance: purchaseQuote.acceptance })
        setBillReference(""); setLineRows([emptyLine()]);
        setTaxAccount(""); setPurchaseNotes("");
        setPurchaseQuote(null)
        await refreshAfter("Compra recibida, inventario valorizado y cuenta por pagar registrada.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la compra.") }
    finally { setBusy(false) }
  }
  async function pay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!paymentQuote) {
        setPaymentQuote(await call<PaymentQuote>(isOpeningPayment ?
          "pms_opening_supplier_payment_quote" : "pms_supplier_payment_quote",
          { property_name: property.name, data: JSON.stringify(paymentData) }))
      } else {
        await send(isOpeningPayment ?
          "pms_pay_opening_supplier" : "pms_pay_supplier",
          { ...paymentData, acceptance: paymentQuote.acceptance })
        setSelectedPurchase(""); setPaymentAmount(""); setSettledAmount(""); setPaymentReference(""); setPaymentReason("");
        setPaymentQuote(null)
        await refreshAfter("Pago aplicado a la cuenta por pagar.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo pagar al proveedor.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Compras PMS</p><h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1><p className="mt-1 text-sm text-muted-foreground">{`${sectionInfo.description}.`}</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {(section === "orders" || section === "order-new" || section === "order-receive") &&
        <PurchaseOrders property={property} data={data} refresh={refresh} send={send} section={section}
          canPurchase={canPurchase} canApprove={canApprove} />}
      {(section === "credits" || section === "credit-apply" || section === "credit-refund" || section === "credit-unapply") &&
        <OpeningSupplierCreditsPms key={property.name} property={property} data={data}
          refresh={refresh} send={send} section={section} canApprove={canApprove} />}
      {section === "supplier-new" && canPurchase && <Card className="max-w-2xl"><CardHeader><CardTitle>Registrar proveedor</CardTitle><CardDescription>Proveedor propio del establecimiento.</CardDescription></CardHeader><CardContent><form onSubmit={createSupplier} className="space-y-3"><Input required maxLength={140} placeholder="Nombre" value={supplierName} onChange={(event) => setSupplierName(event.target.value)} /><Input maxLength={140} placeholder="Identificación fiscal (opcional)" value={supplierTaxId} onChange={(event) => setSupplierTaxId(event.target.value)} /><Button disabled={busy}>Crear proveedor</Button></form></CardContent></Card>}
      {section === "suppliers" && canPurchase &&
        <Card><CardHeader><CardTitle>Proveedores registrados</CardTitle></CardHeader><CardContent className="space-y-2">{data.suppliers.map((row) => <div key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.party_name}</strong>{row.tax_id && <span className="ml-2 text-muted-foreground">{row.tax_id}</span>}</div>)}{!data.suppliers.length && <p className="text-sm text-muted-foreground">Sin proveedores registrados.</p>}</CardContent></Card>
      }
      {section === "receive" && canPurchase && <Card><CardHeader><CardTitle>Recepción de compra</CardTitle><CardDescription>Una factura y una cuenta por pagar con hasta 50 líneas. El impuesto recuperable se separa del costo del inventario.</CardDescription></CardHeader><CardContent><form onSubmit={receive} className="grid gap-3 sm:grid-cols-2">
          <select required value={supplier} onChange={(event) => { changePurchase(); setSupplier(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Proveedor</option>{data.suppliers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select>
          <Input required maxLength={140} placeholder="Referencia de factura" value={billReference} onChange={(event) => { changePurchase(); setBillReference(event.target.value) }} />
          <select required value={currency} onChange={(event) => { changePurchase(); setCurrency(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm">{data.currencies.map((row) => <option key={row} value={row}>{row}</option>)}</select>
          <div className="space-y-3 sm:col-span-2">{lineRows.map((row, index) => <div key={index} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2"><div className="flex items-center justify-between sm:col-span-2"><strong className="text-sm">Línea {index + 1}</strong>{lineRows.length > 1 && <Button type="button" variant="outline" size="sm" onClick={() => { changePurchase(); setLineRows((rows) => rows.filter((_, position) => position !== index)) }}>Quitar</Button>}</div><select required aria-label={`Producto línea ${index + 1}`} value={row.product} onChange={(event) => updateLine(index, "product", event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto</option>{data.products.map((item) => <option key={item.name} value={item.name}>{item.product_code} · {item.product_name}</option>)}</select><select required aria-label={`Almacén línea ${index + 1}`} value={row.warehouse} onChange={(event) => updateLine(index, "warehouse", event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((store) => <option key={store.name} value={store.name}>{store.warehouse_name}</option>)}</select><Input required aria-label={`Cantidad línea ${index + 1}`} type="number" min="0.000001" step="0.000001" value={row.quantity} onChange={(event) => updateLine(index, "quantity", event.target.value)} placeholder="Cantidad" /><Input required aria-label={`Total línea ${index + 1} en ${currency}`} type="number" min="0.01" step="0.01" value={row.invoice_amount} onChange={(event) => updateLine(index, "invoice_amount", event.target.value)} placeholder={`Total (${currency})`} /><Input aria-label={`Impuesto recuperable línea ${index + 1} en ${currency}`} type="number" min="0" step="0.01" value={row.recoverable_tax} onChange={(event) => updateLine(index, "recoverable_tax", event.target.value)} placeholder={`Impuesto recuperable (${currency})`} /></div>)}<Button type="button" variant="outline" disabled={busy || lineRows.length >= 50} onClick={() => { changePurchase(); setLineRows((rows) => [...rows, emptyLine()]) }}>Añadir línea</Button></div>
          <select required value={payableAccount} onChange={(event) => { changePurchase(); setPayableAccount(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por pagar</option>{data.accounts.filter((row) => row.root_type === "Liability" && row.account_type === "Payable").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
          {totalTax > 0 && <select required value={taxAccount} onChange={(event) => { changePurchase(); setTaxAccount(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de impuesto recuperable</option>{data.accounts.filter((row) => row.root_type === "Asset" && row.account_type === "Tax").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
          <Input maxLength={500} placeholder="Observaciones" value={purchaseNotes} onChange={(event) => { changePurchase(); setPurchaseNotes(event.target.value) }} className="sm:col-span-2" />
          {purchaseQuote && <div className="space-y-1 rounded-lg bg-secondary p-3 text-sm sm:col-span-2"><strong>{purchaseQuote.supplier_name} · {purchaseQuote.lines.length} línea(s)</strong>{purchaseQuote.lines.map((line, index) => <p key={index}>{line.product_name} · {line.quantity} · {purchaseQuote.invoice_currency} {line.invoice_amount} · costo base {property.currency} {line.base_cost}</p>)}<p>Factura {purchaseQuote.invoice_currency} {purchaseQuote.invoice_amount} · Cambio {purchaseQuote.exchange_rate}</p><p>Débito inventario {property.currency} {purchaseQuote.base_cost}{Number(purchaseQuote.base_tax) > 0 && ` · Débito impuesto ${property.currency} ${purchaseQuote.base_tax}`} · Crédito proveedores {property.currency} {purchaseQuote.base_amount}</p></div>}
          <Button disabled={busy || !data.products.length || !data.warehouses.length} className="sm:col-span-2">{purchaseQuote ? "Confirmar recepción" : "Revisar compra"}</Button>
        </form></CardContent></Card>
      }
      {section === "payables" && <Card><CardHeader><CardTitle>Cuentas por pagar</CardTitle></CardHeader><CardContent className="space-y-2">{data.opening_payables.map((row) => <div key={row.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{row.opening_source_name}</strong> · {supplierLabel(row.supplier)}<span className="block text-xs text-muted-foreground">Factura abierta trasladada de ERPNext · Vence {row.due_date}</span></span><span className="text-right">Pendiente {row.currency} {row.outstanding}<span className="block text-xs text-muted-foreground">Base {data.currency} {row.base_outstanding}</span></span></div>)}{data.purchases.map((row) => <div key={row.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{row.supplier_reference}</strong> · {supplierLabel(row.supplier)}{row.status === "Cancelled" && " · Cancelada"}<span className="block text-xs text-muted-foreground">{row.lines.map((line) => `${productLabel(line.product)} (${line.quantity})`).join(" · ")} · Factura {row.invoice_currency} {row.invoice_amount}</span></span><span className="text-right">Pendiente {data.currency} {row.outstanding}<span className="block text-xs text-muted-foreground">Costo {data.currency} {row.base_cost}</span></span></div>)}{!data.purchases.length && !data.opening_payables.length && <p className="text-sm text-muted-foreground">No hay cuentas por pagar registradas.</p>}</CardContent></Card>}
      {section === "supplier-pay" && <Card><CardHeader><CardTitle>Abono al proveedor</CardTitle><CardDescription>El efectivo requiere turno propio y saldo disponible. El banco usa su cuenta contable.</CardDescription></CardHeader><CardContent><form onSubmit={pay} className="space-y-3">
          <select required value={selectedPurchase} onChange={(event) => { changePayment(); setSelectedPurchase(event.target.value); setSettledAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por pagar pendiente</option>{data.opening_payables.filter((row) => Number(row.outstanding) > 0).map((row) => <option key={row.name} value={`opening:${row.name}`}>{row.opening_source_name} · {supplierLabel(row.supplier)} · {row.currency} {row.outstanding} · Apertura</option>)}{data.purchases.filter((row) => Number(row.outstanding) > 0).map((row) => <option key={row.name} value={row.name}>{row.supplier_reference} · {supplierLabel(row.supplier)} · {data.currency} {row.outstanding}</option>)}</select>
          <select required value={method} onChange={(event) => { changePayment(); setMethod(event.target.value); setShift("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de pago</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select>
          {selectedMethod?.is_cash && <select required value={shift} onChange={(event) => { changePayment(); setShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto propio</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>}
          <Input required aria-label={`Importe del pago en ${selectedMethod?.currency || data.currency}`} type="number" min="0.01" step="0.01" value={paymentAmount} onChange={(event) => { changePayment(); setPaymentAmount(event.target.value) }} placeholder={`Importe (${selectedMethod?.currency || data.currency})`} />
          {foreignOpening && <label className="block space-y-1 text-sm"><span>Deuda que se liquida ({selectedOpening?.currency})</span><Input aria-label={`Deuda liquidada en ${selectedOpening?.currency}`} type="number" min="0.01" max={selectedOpening?.outstanding} step="0.01" required={selectedMethod?.currency !== selectedOpening?.currency} value={settledAmount} onChange={(event) => { changePayment(); setSettledAmount(event.target.value) }} placeholder={selectedMethod?.currency === selectedOpening?.currency ? `Igual al pago si se deja vacío` : `Importe (${selectedOpening?.currency})`} /></label>}
          <Input required maxLength={140} placeholder="Referencia del pago" value={paymentReference} onChange={(event) => { changePayment(); setPaymentReference(event.target.value) }} />
          <Input required maxLength={500} placeholder="Motivo" value={paymentReason} onChange={(event) => { changePayment(); setPaymentReason(event.target.value) }} />
          {paymentQuote && <div className="rounded-lg bg-secondary p-3 text-sm"><strong>{paymentQuote.currency} {paymentQuote.amount}</strong> · Cambio {paymentQuote.exchange_rate}<p>Débito proveedores {data.currency} {paymentQuote.payable_release_base || paymentQuote.base_amount} · Crédito Caja/banco {data.currency} {paymentQuote.base_amount}</p>{paymentQuote.settlement_currency && <p>Deuda liquidada: {paymentQuote.settlement_currency} {paymentQuote.settled_amount}</p>}{Number(paymentQuote.exchange_variance_base || 0) !== 0 && <p>Diferencia de cambio: {data.currency} {paymentQuote.exchange_variance_base}</p>}<p>Pendiente luego del pago: {paymentQuote.settlement_currency || data.currency} {paymentQuote.outstanding_after}{paymentQuote.base_outstanding_after && ` · Base ${data.currency} ${paymentQuote.base_outstanding_after}`}</p></div>}
          <Button disabled={busy || !selectedPurchase || !method}>{paymentQuote ? "Confirmar pago" : "Revisar pago"}</Button>
        </form></CardContent></Card>}
      {(section === "returns" || section === "return-new" || section === "supplier-refund") &&
        <PurchaseReturns property={property} data={data} refresh={refresh} send={send} section={section} canApprove={canApprove} />}
      {section === "supplier-payments" && <Card><CardHeader><CardTitle>Pagos y reintegros recientes</CardTitle></CardHeader>
        <CardContent className="space-y-2">{data.payments.map((row) =>
          <div key={row.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm">
            <span>{row.kind === "Supplier Refund" ? "Reintegro" : "Pago"} · {row.reference} · {
              row.pms_opening_supplier_credit
                ? data.opening_supplier_credits.credits.find((item) => item.name === row.pms_opening_supplier_credit)?.opening_source_name || row.pms_opening_supplier_credit
                : row.pms_opening_payable
                  ? data.opening_payables.find((item) => item.name === row.pms_opening_payable)?.opening_source_name || row.pms_opening_payable
                  : data.purchases.find((item) => item.name === row.pms_purchase)?.supplier_reference || row.pms_purchase
            }{row.pms_settlement_currency && <span className="block text-xs text-muted-foreground">
              Principal liquidado {row.pms_settlement_currency} {row.pms_settled_amount} · Valor base liberado {data.currency} {row.pms_released_base_amount}
            </span>}</span>
            <strong>{row.currency} {row.amount} · Base {data.currency} {row.base_amount}</strong>
          </div>)}{!data.payments.length && <p className="text-sm text-muted-foreground">Sin movimientos de proveedores.</p>}</CardContent></Card>}
    </>}
  </div>
}

function PurchaseReturns({ property, data, refresh, send, section, canApprove }: {
  property: Property; data: Snapshot; refresh: () => Promise<void>; send: SendCommand;
  section: PurchaseSection; canApprove: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  useEffect(() => { setError(""); setNotice("") }, [section])
  const [purchase, setPurchase] = useState("")
  const [cancelEntire, setCancelEntire] = useState(false)
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [varianceAccount, setVarianceAccount] = useState("")
  const [reviewed, setReviewed] = useState<ReturnQuote | null>(null)
  const [refundReturn, setRefundReturn] = useState("")
  const [refundMethod, setRefundMethod] = useState("")
  const [refundShift, setRefundShift] = useState("")
  const [refundAmount, setRefundAmount] = useState("")
  const [refundReference, setRefundReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundReviewed, setRefundReviewed] = useState<RefundQuote | null>(null)
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el movimiento.`) }
  }
  const selectedPurchase = data.purchases.find((row) => row.name === purchase)
  const canCancelSelected = !!selectedPurchase && selectedPurchase.status === "Posted" &&
    !data.payments.some((row) => row.pms_purchase === selectedPurchase.name &&
      row.kind === "Supplier Payment") &&
    !data.returns.some((row) => row.purchase === selectedPurchase.name)
  const selectedRefund = data.returns.find((row) => row.name === refundReturn)
  const selectedMethod = data.methods.find((row) => row.name === refundMethod)
  const returnData = { purchase, reference: reference.trim(), reason: reason.trim(),
    variance_account: varianceAccount || null,
    lines: (selectedPurchase?.lines || []).filter((line) => line.stock_movement &&
      (cancelEntire || Number(quantities[line.stock_movement] || 0) > 0)).map((line) => ({
        source_movement: line.stock_movement,
        quantity: cancelEntire ? String(line.quantity) : quantities[line.stock_movement!] })) }
  const refundData = { return: refundReturn, method: refundMethod,
    shift: selectedMethod?.is_cash ? refundShift : null,
    amount: refundAmount, reference: refundReference.trim(),
    reason: refundReason.trim() }
  const invalidateReturn = () => setReviewed(null)
  const invalidateRefund = () => setRefundReviewed(null)
  const productLabel = (name: string) => data.products.find((row) => row.name === name)?.product_name || name
  const purchaseLabel = (name: string) => data.purchases.find((row) => row.name === name)?.supplier_reference || name

  async function returnStock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!reviewed?.acceptance) {
        setReviewed(await call<ReturnQuote>(cancelEntire ? "pms_purchase_cancel_quote" :
          "pms_purchase_return_quote", {
          property_name: property.name, data: JSON.stringify(returnData) }))
      } else {
        await send(cancelEntire ? "pms_cancel_purchase" : "pms_return_purchase",
          { ...returnData, acceptance: reviewed.acceptance })
        setPurchase(""); setQuantities({}); setReference(""); setReason("")
        setCancelEntire(false); setVarianceAccount(""); setReviewed(null)
        await refreshAfter(cancelEntire ? "Compra cancelada con devolución íntegra publicada." :
          "Devolución registrada y crédito del proveedor actualizado.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la devolución.") }
    finally { setBusy(false) }
  }

  async function receiveRefund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!refundReviewed) {
        setRefundReviewed(await call<RefundQuote>("pms_supplier_refund_quote", {
          property_name: property.name, data: JSON.stringify(refundData) }))
      } else {
        await send("pms_supplier_refund", { ...refundData, acceptance: refundReviewed.acceptance })
        setRefundReturn(""); setRefundMethod(""); setRefundShift("")
        setRefundAmount(""); setRefundReference(""); setRefundReason("")
        setRefundReviewed(null)
        await refreshAfter("Reintegro del proveedor recibido y contabilizado.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el reintegro.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-5">
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {section === "return-new" && canApprove && <Card><CardHeader><CardTitle>Devolución o cancelación</CardTitle><CardDescription>Una devolución reduce la deuda abierta o crea un crédito si ya se pagó. La cancelación devuelve toda una factura sin pagos ni devoluciones previas. La diferencia de costo se registra en una cuenta de variación.</CardDescription></CardHeader><CardContent><form onSubmit={returnStock} className="space-y-3">
        <select required value={purchase} onChange={(event) => { setPurchase(event.target.value); setQuantities({}); setCancelEntire(false); setVarianceAccount(""); invalidateReturn() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione factura de compra</option>{data.purchases.filter((row) => row.status === "Posted").map((row) => <option key={row.name} value={row.name}>{row.supplier_reference} · {row.invoice_currency} {row.invoice_amount}</option>)}</select>
        {canCancelSelected && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cancelEntire} onChange={(event) => { setCancelEntire(event.target.checked); setVarianceAccount(""); invalidateReturn() }} />Cancelar la factura completa y devolver todas las líneas</label>}
        {selectedPurchase?.lines.map((line) => <label key={line.stock_movement || line.product} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-2 text-sm"><span>{productLabel(line.product)} · recibido {line.quantity}</span><Input aria-label={`Cantidad a devolver de ${productLabel(line.product)}`} type="number" min="0" max={line.quantity} step="0.000001" value={cancelEntire ? String(line.quantity) : line.stock_movement ? quantities[line.stock_movement] || "" : ""} disabled={!line.stock_movement || cancelEntire} onChange={(event) => { if (!line.stock_movement) return; setQuantities((current) => ({ ...current, [line.stock_movement!]: event.target.value })); setVarianceAccount(""); invalidateReturn() }} className="w-32" placeholder="Cantidad" /></label>)}
        <Input required maxLength={140} placeholder="Referencia de devolución" value={reference} onChange={(event) => { setReference(event.target.value); invalidateReturn() }} />
        <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { setReason(event.target.value); invalidateReturn() }} />
        {reviewed && <div className="space-y-1 rounded-lg bg-secondary p-3 text-sm"><p>Crédito del proveedor: {reviewed.invoice_currency} {reviewed.credit_amount} · Base {property.currency} {reviewed.base_credit}</p><p>Sale inventario {property.currency} {reviewed.stock_value} · Revierte impuesto {property.currency} {reviewed.base_tax}</p><p>Reduce deuda {property.currency} {reviewed.payable_applied} · Reintegro pendiente {property.currency} {reviewed.supplier_credit}</p>{Number(reviewed.variance) !== 0 && <p>Variación {property.currency} {reviewed.variance} ({reviewed.variance_nature === "Income" ? "ingreso" : "gasto"})</p>}</div>}
        {reviewed?.variance_nature && <select required value={varianceAccount} onChange={(event) => { setVarianceAccount(event.target.value); setReviewed((quote) => quote ? { ...quote, acceptance: null } : null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de variación {reviewed.variance_nature === "Income" ? "de ingreso" : "de gasto"}</option>{data.accounts.filter((row) => row.root_type === reviewed.variance_nature).map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
        <Button disabled={busy || !purchase || !returnData.lines.length}>{reviewed?.acceptance ? cancelEntire ? "Confirmar cancelación" : "Confirmar devolución" : cancelEntire ? "Revisar cancelación" : "Revisar devolución"}</Button>
      </form></CardContent></Card>}
    {section === "supplier-refund" && <Card><CardHeader><CardTitle>Reintegro del proveedor</CardTitle><CardDescription>Reciba total o parcialmente el crédito generado por una devolución ya pagada. Efectivo requiere turno abierto; banco usa su cuenta contable.</CardDescription></CardHeader><CardContent><form onSubmit={receiveRefund} className="space-y-3">
        <select required value={refundReturn} onChange={(event) => { setRefundReturn(event.target.value); invalidateRefund() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione crédito pendiente</option>{data.returns.filter((row) => Number(row.refund_available) > 0).map((row) => <option key={row.name} value={row.name}>{row.reference} · {purchaseLabel(row.purchase)} · {property.currency} {row.refund_available}</option>)}</select>
        <select required value={refundMethod} onChange={(event) => { setRefundMethod(event.target.value); setRefundShift(""); invalidateRefund() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de recepción</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select>
        {selectedMethod?.is_cash && <select required value={refundShift} onChange={(event) => { setRefundShift(event.target.value); invalidateRefund() }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto propio</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>}
        <Input required aria-label={`Importe del reintegro en ${selectedMethod?.currency || property.currency}`} type="number" min="0.01" step="0.01" value={refundAmount} onChange={(event) => { setRefundAmount(event.target.value); invalidateRefund() }} placeholder={`Importe (${selectedMethod?.currency || property.currency})`} />
        <Input required maxLength={140} placeholder="Referencia del reintegro" value={refundReference} onChange={(event) => { setRefundReference(event.target.value); invalidateRefund() }} />
        <Input required maxLength={500} placeholder="Motivo" value={refundReason} onChange={(event) => { setRefundReason(event.target.value); invalidateRefund() }} />
        {refundReviewed && <div className="rounded-lg bg-secondary p-3 text-sm"><p>Débito Caja/banco {refundReviewed.currency} {refundReviewed.amount} · Crédito proveedores {property.currency} {refundReviewed.base_amount}</p><p>Crédito disponible después: {property.currency} {refundReviewed.available_after}</p></div>}
        <Button disabled={busy || !selectedRefund || !refundMethod}>{refundReviewed ? "Confirmar reintegro" : "Revisar reintegro"}</Button>
      </form></CardContent></Card>}
    {section === "returns" && <Card><CardHeader><CardTitle>Devoluciones registradas</CardTitle></CardHeader><CardContent className="space-y-2">{data.returns.map((row) => <div key={row.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span><strong>{row.reference}</strong> · {purchaseLabel(row.purchase)} · {row.kind === "Full Cancellation" ? "Cancelación completa" : "Devolución"} · {row.business_date}</span><span>{row.invoice_currency} {row.credit_amount} · Crédito pendiente {property.currency} {row.refund_available}</span></div>)}{!data.returns.length && <p className="text-sm text-muted-foreground">Sin devoluciones al proveedor.</p>}</CardContent></Card>}
  </div>
}

function PurchaseOrders({ property, data, refresh, send, section, canPurchase, canApprove }: {
  property: Property; data: Snapshot; refresh: () => Promise<void>; send: SendCommand;
  section: PurchaseSection; canPurchase: boolean; canApprove: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  useEffect(() => { setError(""); setNotice("") }, [section])
  const [supplier, setSupplier] = useState("")
  const [reference, setReference] = useState("")
  const [currency, setCurrency] = useState(property.currency)
  const [payableAccount, setPayableAccount] = useState("")
  const [taxAccount, setTaxAccount] = useState("")
  const [expectedDate, setExpectedDate] = useState("")
  const [notes, setNotes] = useState("")
  const [rows, setRows] = useState<PurchaseLine[]>([emptyLine()])
  const [reviewed, setReviewed] = useState<{ acceptance: string; amount: string;
    recoverable_tax: string; currency: string } | null>(null)
  const [selectedOrder, setSelectedOrder] = useState("")
  const [billReference, setBillReference] = useState("")
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [receiptQuote, setReceiptQuote] = useState<PurchaseQuote | null>(null)
  const [closeReason, setCloseReason] = useState("")
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar la orden.`) }
  }
  const chosen = data.orders.find((row) => row.name === selectedOrder)
  const hasTax = rows.some((row) => Number(row.recoverable_tax) > 0)
  const orderPayload = { supplier, reference: reference.trim(), currency,
    payable_account: payableAccount, tax_account: hasTax ? taxAccount : null,
    expected_date: expectedDate || null, notes: notes.trim(),
    lines: rows.map((row) => ({ product: row.product, warehouse: row.warehouse,
      quantity: row.quantity, amount: row.invoice_amount,
      recoverable_tax: row.recoverable_tax || "0" })) }
  const receiptPayload = chosen ? {
    purchase_order: chosen.name, supplier: chosen.supplier,
    supplier_reference: billReference.trim(), invoice_currency: chosen.currency,
    payable_account: chosen.payable_account, tax_account: chosen.tax_account,
    lines: chosen.lines.filter((line) => Number(quantities[line.name]) > 0)
      .map((line) => ({ order_line: line.name, product: line.product,
        warehouse: line.warehouse, quantity: quantities[line.name] })),
  } : null
  const invalidateOrder = () => setReviewed(null)
  const invalidateReceipt = () => setReceiptQuote(null)
  const productLabel = (id: string) => data.products.find((row) => row.name === id)?.product_name || id
  const supplierLabel = (id: string) => data.suppliers.find((row) => row.name === id)?.party_name || id
  const statusLabel = (value: string) => ({ Pending: "Pendiente de aprobación",
    Approved: "Aprobada", "Partially Received": "Recibida parcialmente",
    Completed: "Recibida completamente", Closed: "Cerrada",
    Cancelled: "Cancelada" }[value] || value)

  async function requestOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canPurchase) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!reviewed) {
        setReviewed(await call("pms_order_quote", {
          property_name: property.name, data: JSON.stringify(orderPayload),
        }))
      } else {
        await send("pms_order_request", { ...orderPayload, acceptance: reviewed.acceptance })
        invalidateOrder(); setReference(""); setRows([emptyLine()]); setNotes("")
        setExpectedDate("")
        await refreshAfter("Orden enviada a Gerencia para aprobación.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo solicitar la orden.") }
    finally { setBusy(false) }
  }
  async function approveOrder(order: Order) {
    if (busy || !canApprove) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_order_approve", { order: order.name, modified: order.modified })
      await refreshAfter(`Orden ${order.reference} aprobada.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aprobar la orden.") }
    finally { setBusy(false) }
  }
  async function closeOrder(order: Order) {
    if (busy || !closeReason.trim()) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_order_close",
        { order: order.name, modified: order.modified, reason: closeReason.trim() })
      setCloseReason("")
      await refreshAfter(`Orden ${order.reference} cerrada.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cerrar la orden.") }
    finally { setBusy(false) }
  }
  async function receiveOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canPurchase || !receiptPayload || !receiptPayload.lines.length) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!receiptQuote) {
        setReceiptQuote(await call<PurchaseQuote>("pms_purchase_quote", {
          property_name: property.name, data: JSON.stringify(receiptPayload),
        }))
      } else {
        await send("pms_receive_purchase", { ...receiptPayload, acceptance: receiptQuote.acceptance })
        invalidateReceipt(); setSelectedOrder(""); setBillReference(""); setQuantities({});
        await refreshAfter("Recepción registrada con factura y cuenta por pagar propias.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo recibir la orden.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-5">
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {section === "order-receive" && <p className="text-sm text-muted-foreground">La orden aprobada fija cantidades y precios. Cada recepción parcial registra su propia factura, inventario y cuenta por pagar.</p>}
    {canPurchase && (section === "order-new" || section === "order-receive") && <div className="space-y-5">
      {section === "order-new" &&
      <Card><CardHeader><CardTitle>Solicitar orden</CardTitle></CardHeader><CardContent><form onSubmit={requestOrder} className="grid gap-3 sm:grid-cols-2">
        <select required value={supplier} onChange={(event) => { invalidateOrder(); setSupplier(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Proveedor</option>{data.suppliers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select>
        <Input required maxLength={140} placeholder="Referencia de orden" value={reference} onChange={(event) => { invalidateOrder(); setReference(event.target.value) }} />
        <select required value={currency} onChange={(event) => { invalidateOrder(); setCurrency(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm">{data.currencies.map((row) => <option key={row} value={row}>{row}</option>)}</select>
        <Input type="date" value={expectedDate} onChange={(event) => { invalidateOrder(); setExpectedDate(event.target.value) }} aria-label="Fecha esperada" />
        <select required value={payableAccount} onChange={(event) => { invalidateOrder(); setPayableAccount(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por pagar</option>{data.accounts.filter((row) => row.root_type === "Liability" && row.account_type === "Payable").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
        {hasTax && <select required value={taxAccount} onChange={(event) => { invalidateOrder(); setTaxAccount(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Impuesto recuperable</option>{data.accounts.filter((row) => row.root_type === "Asset" && row.account_type === "Tax").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
        <div className="space-y-2 sm:col-span-2">{rows.map((row, index) => <div key={index} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-2"><div className="flex justify-between sm:col-span-2"><strong>Línea {index + 1}</strong>{rows.length > 1 && <Button type="button" size="sm" variant="outline" onClick={() => { invalidateOrder(); setRows((current) => current.filter((_, i) => i !== index)) }}>Quitar</Button>}</div><select required aria-label={`Producto de orden ${index + 1}`} value={row.product} onChange={(event) => { invalidateOrder(); setRows((current) => current.map((item, i) => i === index ? { ...item, product: event.target.value } : item)) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto</option>{data.products.map((item) => <option key={item.name} value={item.name}>{item.product_name}</option>)}</select><select required aria-label={`Almacén de orden ${index + 1}`} value={row.warehouse} onChange={(event) => { invalidateOrder(); setRows((current) => current.map((item, i) => i === index ? { ...item, warehouse: event.target.value } : item)) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Almacén</option>{data.warehouses.map((item) => <option key={item.name} value={item.name}>{item.warehouse_name}</option>)}</select>{(["quantity", "invoice_amount", "recoverable_tax"] as const).map((field) => <Input key={field} required aria-label={`${field} de orden ${index + 1}`} type="number" min={field === "recoverable_tax" ? "0" : "0.01"} step={field === "quantity" ? "0.000001" : "0.01"} placeholder={field === "quantity" ? "Cantidad" : field === "invoice_amount" ? `Total (${currency})` : `Impuesto (${currency})`} value={row[field]} onChange={(event) => { invalidateOrder(); setRows((current) => current.map((item, i) => i === index ? { ...item, [field]: event.target.value } : item)) }} />)}</div>)}<Button type="button" variant="outline" disabled={busy || rows.length >= 50} onClick={() => { invalidateOrder(); setRows((current) => [...current, emptyLine()]) }}>Añadir línea</Button></div>
        <Input maxLength={500} placeholder="Observaciones" value={notes} onChange={(event) => { invalidateOrder(); setNotes(event.target.value) }} className="sm:col-span-2" />
        {reviewed && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Orden {reviewed.currency} {reviewed.amount} · impuesto recuperable {reviewed.recoverable_tax}</p>}
        <Button disabled={busy || !data.suppliers.length || !data.products.length} className="sm:col-span-2">{reviewed ? "Solicitar orden" : "Revisar orden"}</Button>
      </form></CardContent></Card>}
      {section === "order-receive" &&
      <Card><CardHeader><CardTitle>Recibir contra orden</CardTitle></CardHeader><CardContent><form onSubmit={receiveOrder} className="space-y-3">
        <select required value={selectedOrder} onChange={(event) => { invalidateReceipt(); setSelectedOrder(event.target.value); setQuantities({}) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Orden aprobada con saldo</option>{data.orders.filter((order) => order.status === "Approved" && order.lines.some((line) => Number(line.remaining_quantity) > 0)).map((order) => <option key={order.name} value={order.name}>{order.reference} · {supplierLabel(order.supplier)} · {order.currency}</option>)}</select>
        <Input required maxLength={140} placeholder="Referencia de factura del proveedor" value={billReference} onChange={(event) => { invalidateReceipt(); setBillReference(event.target.value) }} />
        {chosen?.lines.map((line) => <label key={line.name} className="grid gap-1 text-sm"><span>{productLabel(line.product)} · pendiente {line.remaining_quantity} de {line.quantity} · {chosen.currency} {line.amount} ordenados</span><Input type="number" min="0" max={line.remaining_quantity} step="0.000001" value={quantities[line.name] || ""} onChange={(event) => { invalidateReceipt(); setQuantities((current) => ({ ...current, [line.name]: event.target.value })) }} placeholder="Cantidad a recibir" disabled={Number(line.remaining_quantity) <= 0} /></label>)}
        {receiptQuote && <div className="rounded-lg bg-secondary p-3 text-sm"><strong>Factura {receiptQuote.invoice_currency} {receiptQuote.invoice_amount}</strong><p>Inventario {property.currency} {receiptQuote.base_cost} · impuesto {property.currency} {receiptQuote.base_tax} · proveedores {property.currency} {receiptQuote.base_amount}</p></div>}
        <Button disabled={busy || !chosen || !receiptPayload?.lines.length}>{receiptQuote ? "Confirmar recepción" : "Revisar recepción"}</Button>
      </form></CardContent></Card>}
    </div>}
    {section === "orders" && <Card><CardHeader><CardTitle>Seguimiento de órdenes</CardTitle></CardHeader><CardContent className="space-y-3">{data.orders.map((order) => <div key={order.name} className="rounded-lg border p-3 text-sm"><div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{order.reference}</strong> · {supplierLabel(order.supplier)} · {statusLabel(order.progress)}<p className="text-xs text-muted-foreground">{order.currency} {order.amount} · solicitó {order.requested_by}{order.approved_by && ` · aprobó ${order.approved_by}`}</p></div><div className="flex gap-2">{canApprove && order.status === "Pending" && <Button size="sm" disabled={busy} onClick={() => void approveOrder(order)}>Aprobar</Button>}</div></div><div className="mt-2 space-y-1">{order.lines.map((line) => <p key={line.name}>{productLabel(line.product)} · recibido {line.received_quantity} / {line.quantity} · pendiente {line.remaining_quantity}</p>)}</div>{order.status === "Pending" || order.status === "Approved" ? <div className="mt-3 flex flex-wrap gap-2"><Input maxLength={500} placeholder="Motivo de cierre" value={closeReason} onChange={(event) => setCloseReason(event.target.value)} className="min-w-48 flex-1" /><Button type="button" size="sm" variant="outline" disabled={busy || !closeReason.trim() || (order.status === "Approved" && !canApprove)} onClick={() => void closeOrder(order)}>Cerrar orden</Button></div> : order.close_reason && <p className="mt-2 text-xs text-muted-foreground">Cierre: {order.close_reason}</p>}</div>)}{!data.orders.length && <p className="text-sm text-muted-foreground">Sin órdenes de compra.</p>}</CardContent></Card>}
  </div>
}
