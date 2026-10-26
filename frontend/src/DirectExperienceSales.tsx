import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

type Order = { name: string; experience: string; booking: string | null;
  customer: string; quantity: number; participants: number; scheduled_at: string | null;
  amount: number; currency: string; status: string; pms_receivable: string | null;
  modified: string; accepted_net: number | null; accepted_tax: number | null;
  accepted_total: number | null; accepted_tax_profile: string | null;
  income_account: string | null; tax_account: string | null }
type Snapshot = {
  currency: string
  customers: { name: string; party_name: string }[]
  experiences: { name: string; experience_name: string; active: number }[]
  receivable_accounts: { name: string; account_code: string; account_name: string }[]
  income_accounts: { name: string; account_code: string; account_name: string }[]
  tax_profiles: { name: string; label: string; treatment: string; rate: number;
    included_in_price: number }[]
  orders: Order[]
}
type OrderQuote = { customer_name: string; currency: string; acceptance: string;
  line: { name: string; quantity: number; rate: string; amount: string;
    tax_amount: string; total_amount: string } }
type DeliveryQuote = { acceptance: string; price: string; net_amount: string;
  tax_amount: string; total_amount: string; currency: string;
  income_account: string; receivable_account: string }
type LegacyQuote = { acceptance: string; price: string; net_amount: string;
  tax_amount: string; total_amount: string; currency: string;
  tax_profile: string; tax_account: string | null; income_account: string }

export function DirectExperienceSales({ property, data, onChanged, canApprove }: {
  property: Property; data: Snapshot; onChanged: () => Promise<void>; canApprove: boolean
}) {
  const [customer, setCustomer] = useState("")
  const [experience, setExperience] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [quote, setQuote] = useState<OrderQuote | null>(null)
  const [orderKey, setOrderKey] = useState("")
  const [selected, setSelected] = useState("")
  const [scheduledAt, setScheduledAt] = useState("")
  const [participants, setParticipants] = useState("1")
  const [receivableAccount, setReceivableAccount] = useState("")
  const [deliveryQuote, setDeliveryQuote] = useState<DeliveryQuote | null>(null)
  const [deliveryKey, setDeliveryKey] = useState("")
  const [reason, setReason] = useState("")
  const [legacySelected, setLegacySelected] = useState("")
  const [legacyProfile, setLegacyProfile] = useState("")
  const [legacyIncome, setLegacyIncome] = useState("")
  const [legacyEvidence, setLegacyEvidence] = useState("")
  const [legacyQuote, setLegacyQuote] = useState<LegacyQuote | null>(null)
  const [legacyKey, setLegacyKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const direct = data.orders.filter((row) => !row.booking)
  const current = direct.find((row) => row.name === selected)
  const legacy = direct.filter((row) => ["Reserved", "Confirmed"].includes(row.status) &&
    !row.pms_receivable && !row.accepted_net && !row.accepted_tax &&
    !row.accepted_total && !row.accepted_tax_profile &&
    !row.income_account && !row.tax_account)
  const historical = legacy.find((row) => row.name === legacySelected)

  async function create() {
    if (busy || !customer || !experience) return
    setBusy(true); setError(""); setNotice("")
    const request = { customer, experience, quantity: Number(quantity) }
    try {
      if (!quote) {
        setQuote(await call<OrderQuote>("preview", { property_name: property.name,
          action: "pms_direct_experience_order", data: JSON.stringify(request) }))
        setOrderKey(crypto.randomUUID())
      } else {
        const result = await execute<{ order: string }>(property.name,
          "pms_direct_experience_order", { ...request, acceptance: quote.acceptance }, orderKey)
        setQuote(null); setOrderKey(""); setCustomer(""); setExperience(""); setQuantity("1")
        await onChanged(); setNotice(`Orden directa ${result.order} registrada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la experiencia.") }
    finally { setBusy(false) }
  }

  async function change(status: "Confirmed" | "Cancelled") {
    if (busy || !current) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_direct_experience_status", {
        order: current.name, modified: current.modified, status,
        ...(status === "Confirmed" ? { scheduled_at: scheduledAt,
          participants: Number(participants) } : { reason: reason.trim() }),
      }, crypto.randomUUID())
      setSelected(""); setReason(""); await onChanged()
      setNotice(status === "Confirmed" ? "Experiencia confirmada." : "Orden cancelada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la orden.") }
    finally { setBusy(false) }
  }

  async function deliver() {
    if (busy || !current || !receivableAccount) return
    setBusy(true); setError(""); setNotice("")
    const request = { order: current.name, receivable_account: receivableAccount }
    try {
      if (!deliveryQuote) {
        setDeliveryQuote(await call<DeliveryQuote>("preview", {
          property_name: property.name, action: "pms_direct_experience_delivery",
          data: JSON.stringify(request) }))
        setDeliveryKey(crypto.randomUUID())
      } else {
        const result = await execute<{ pms_receivable: string }>(property.name,
          "pms_direct_experience_status", { ...request, status: "Delivered",
            modified: current.modified, acceptance: deliveryQuote.acceptance }, deliveryKey)
        setSelected(""); setDeliveryQuote(null); setDeliveryKey("")
        await onChanged(); setNotice(`Experiencia entregada. Cargo ${result.pms_receivable} listo para facturar y cobrar.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo contabilizar la entrega.") }
    finally { setBusy(false) }
  }

  async function reviewLegacy() {
    if (busy || !canApprove || !historical || !legacyProfile || !legacyIncome ||
        legacyEvidence.trim().length < 10) return
    setBusy(true); setError(""); setNotice("")
    const request = { order: historical.name, modified: historical.modified,
      tax_profile: legacyProfile, income_account: legacyIncome,
      evidence: legacyEvidence.trim() }
    try {
      if (!legacyQuote) {
        setLegacyQuote(await call<LegacyQuote>("preview", {
          property_name: property.name, action: "pms_legacy_direct_experience_review",
          data: JSON.stringify(request) }))
        setLegacyKey(crypto.randomUUID())
      } else {
        await execute(property.name, "pms_legacy_direct_experience_review",
          { ...request, acceptance: legacyQuote.acceptance }, legacyKey)
        setLegacySelected(""); setLegacyProfile(""); setLegacyIncome("")
        setLegacyEvidence(""); setLegacyQuote(null); setLegacyKey("")
        await onChanged(); setNotice("Desglose histórico revisado y registrado para esta orden.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la orden histórica.") }
    finally { setBusy(false) }
  }

  return <div className="grid gap-5 xl:grid-cols-2">
    <Card><CardHeader><CardTitle>Venta directa sin estancia</CardTitle>
      <CardDescription>Registre la orden del cliente. El ingreso y el impuesto se contabilizan al entregarla.</CardDescription>
    </CardHeader><CardContent className="space-y-3">
      <select value={customer} onChange={(event) => { setCustomer(event.target.value); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cliente PMS</option>{data.customers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select>
      <select value={experience} onChange={(event) => { setExperience(event.target.value); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Experiencia</option>{data.experiences.filter((row) => row.active).map((row) => <option key={row.name} value={row.name}>{row.experience_name}</option>)}</select>
      <Input type="number" min="1" max="1000" step="1" value={quantity} onChange={(event) => { setQuantity(event.target.value); setQuote(null) }} />
      {quote && <p className="rounded-lg bg-secondary p-3 text-sm">{quote.line.name} × {quote.line.quantity} · base {quote.currency} {quote.line.amount} · impuesto {quote.currency} {quote.line.tax_amount} · total {quote.currency} {quote.line.total_amount}</p>}
      <Button disabled={busy || !customer || !experience} onClick={() => void create()}>{quote ? "Registrar orden" : "Revisar precio"}</Button>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>Órdenes sin estancia</CardTitle>
      <CardDescription>Confirme la fecha y entregue el servicio. Después puede <Link className="text-primary underline" to="/billing?section=invoices">facturar</Link> y <Link className="text-primary underline" to="/cash?section=collect">cobrar</Link> el cargo.</CardDescription>
    </CardHeader><CardContent className="space-y-3 text-sm">
      {direct.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2"><span><strong>{data.experiences.find((item) => item.name === row.experience)?.experience_name || row.experience}</strong> × {row.quantity} · {row.currency} {row.amount}<span className="block text-muted-foreground">{row.name} · {data.customers.find((item) => item.name === row.customer)?.party_name || row.customer} · {row.status}{row.pms_receivable && ` · cargo ${row.pms_receivable}`}</span></span>{["Reserved", "Confirmed"].includes(row.status) && <Button size="sm" variant="outline" onClick={() => { setSelected(row.name); setScheduledAt(row.scheduled_at?.replace(" ", "T").slice(0, 16) || ""); setParticipants(String(row.participants || row.quantity)); setDeliveryQuote(null); setReason("") }}>Gestionar</Button>}</div>)}
      {!direct.length && <p className="text-muted-foreground">Sin ventas directas de experiencias.</p>}
      {current && <div className="space-y-3 rounded-lg border p-3"><strong>{current.name} · {current.status}</strong>
        {current.status === "Confirmed" && !current.accepted_total && <p className="text-amber-800">Esta orden antigua requiere revisión del desglose antes de entregarse.</p>}
        {current.status === "Reserved" && <div className="grid gap-3 sm:grid-cols-2"><Input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /><Input type="number" min="1" max="1000" step="1" value={participants} onChange={(event) => setParticipants(event.target.value)} /></div>}
        {current.status === "Confirmed" && <select value={receivableAccount} onChange={(event) => { setReceivableAccount(event.target.value); setDeliveryQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Cuenta por cobrar</option>{data.receivable_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
        {deliveryQuote && <p className="rounded-lg bg-secondary p-3">Base {deliveryQuote.currency} {deliveryQuote.net_amount} · impuesto {deliveryQuote.tax_amount} · total {deliveryQuote.total_amount}<span className="block text-muted-foreground">Ingreso {deliveryQuote.income_account} · por cobrar {deliveryQuote.receivable_account}</span></p>}
        <Input maxLength={500} placeholder="Motivo si cancela" value={reason} onChange={(event) => setReason(event.target.value)} />
        <div className="flex flex-wrap gap-2">{current.status === "Reserved" && <Button disabled={busy || !scheduledAt} onClick={() => void change("Confirmed")}>Confirmar horario</Button>}{current.status === "Confirmed" && <Button disabled={busy || !receivableAccount} onClick={() => void deliver()}>{deliveryQuote ? "Contabilizar entrega" : "Revisar entrega"}</Button>}<Button disabled={busy || !reason.trim()} variant="outline" onClick={() => void change("Cancelled")}>Cancelar orden</Button><Button variant="ghost" onClick={() => setSelected("")}>Cerrar</Button></div>
      </div>}
    </CardContent></Card>
    {canApprove && legacy.length > 0 && <Card className="xl:col-span-2"><CardHeader><CardTitle>Órdenes antiguas sin desglose</CardTitle>
      <CardDescription>Gerencia selecciona el perfil tributario que correspondía a la venta y registra una referencia de respaldo. La Suite no deduce el impuesto histórico del producto actual.</CardDescription>
    </CardHeader><CardContent className="space-y-3 text-sm">
      <select value={legacySelected} onChange={(event) => { setLegacySelected(event.target.value); setLegacyQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Orden pendiente de revisión</option>{legacy.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.currency} {row.amount} · {row.status}</option>)}</select>
      {historical && <><div className="grid gap-3 sm:grid-cols-2">
        <select value={legacyProfile} onChange={(event) => { setLegacyProfile(event.target.value); setLegacyQuote(null) }} className="h-9 rounded-md border border-border bg-white px-2"><option value="">Perfil tributario histórico</option>{data.tax_profiles.map((row) => <option key={row.name} value={row.name}>{row.label} · {row.treatment} {row.rate}%{row.included_in_price ? " incluido" : " adicional"}</option>)}</select>
        <select value={legacyIncome} onChange={(event) => { setLegacyIncome(event.target.value); setLegacyQuote(null) }} className="h-9 rounded-md border border-border bg-white px-2"><option value="">Cuenta de ingreso</option>{data.income_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
      </div><Input maxLength={500} placeholder="Referencia del respaldo histórico y motivo de la selección" value={legacyEvidence} onChange={(event) => { setLegacyEvidence(event.target.value); setLegacyQuote(null) }} />
      {legacyQuote && <p className="rounded-lg bg-secondary p-3">Precio {legacyQuote.currency} {legacyQuote.price} · base {legacyQuote.net_amount} · impuesto {legacyQuote.tax_amount} · total {legacyQuote.total_amount}<span className="block text-muted-foreground">Ingreso {legacyQuote.income_account} · impuesto {legacyQuote.tax_account || "sin cuenta"}</span></p>}
      <Button disabled={busy || !legacyProfile || !legacyIncome || legacyEvidence.trim().length < 10} onClick={() => void reviewLegacy()}>{legacyQuote ? "Confirmar desglose" : "Revisar desglose"}</Button></>}
    </CardContent></Card>}
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive xl:col-span-2">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800 xl:col-span-2">{notice}</p>}
  </div>
}
