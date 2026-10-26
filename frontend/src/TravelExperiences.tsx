import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"
import { DirectExperienceSales } from "./DirectExperienceSales"
import { availableTravelSections } from "./TravelSections"

type Agent = { name: string; agent_name: string; agent_type: string; commission_pct: number;
  pms_supplier: string | null; contact_name: string; contact_phone: string;
  contact_email: string; active: number; modified: string }
type Experience = { name: string; experience_name: string; experience_category: string;
  pms_product: string | null; duration: string; description: string;
  show_on_booking_page: number; active: number; modified: string }
type Order = { name: string; experience: string; booking: string | null; customer: string;
  pms_receivable: string | null; stay: string | null;
  folio: string | null; quantity: number; participants: number; scheduled_at: string | null;
  amount: number; currency: string; status: string; charge: string | null; modified: string;
  accepted_net: number | null; accepted_tax: number | null; accepted_total: number | null;
  accepted_tax_profile: string | null; income_account: string | null; tax_account: string | null }
type Snapshot = { currency: string; agents: Agent[]; experiences: Experience[]; orders: Order[];
  property_modified: string; commission_expense_account: string | null;
  commission_payable_account: string | null;
  commission_accounts: { name: string; account_code: string; account_name: string;
    root_type: string; account_type: string }[];
  methods: { name: string; mode_of_payment: string; currency: string; is_cash: number }[];
  shifts: { name: string; opened_at: string }[];
  commissions: { name: string; booking: string; agent_name: string; supplier: string;
    amount: number; currency: string; outstanding: string; status: string;
    journal: string; modified: string }[];
  products: { name: string; product_name: string; sales_rate: number; tax_profile: string | null }[];
  suppliers: { name: string; party_name: string }[];
  customers: { name: string; party_name: string }[];
  receivable_accounts: { name: string; account_code: string; account_name: string }[];
  income_accounts: { name: string; account_code: string; account_name: string }[];
  tax_profiles: { name: string; label: string; treatment: string; rate: number;
    included_in_price: number }[];
  bookings: { name: string; customer: string; status: string; travel_agent: string | null;
    pms_agent_commission: string | null }[];
  stays: { name: string; booking: string | null; room: string }[];
  folios: { name: string; booking: string | null; stay: string | null;
    customer: string; label: string }[];
  contribution: { travel_agent: string; bookings: number; accepted_lodging: number;
    estimated_commission: number }[] }
type OrderQuote = { booking: string; currency: string; acceptance: string;
  line: { name: string; quantity: number; rate: string; amount: string;
    tax_amount?: string; total_amount?: string } }
type CommissionQuote = { booking: string; modified: string; agent_name: string;
  supplier: string; base: string; percent: string; amount: string; currency: string;
  expense_account: string; payable_account: string; acceptance: string }
type PaymentQuote = { acceptance: string; amount: string; currency: string;
  exchange_rate: string; base_amount: string; base_currency: string;
  outstanding_after: string }
const agentTypes = ["Travel Agent", "OTA", "Tour Operator", "Corporate Desk"]
const categories = ["Spa", "Tour", "Dining", "Activity", "Transport", "Other"]
const emptyAgent = { name: "", modified: "", agent_name: "", agent_type: "Travel Agent",
  commission_pct: "0", pms_supplier: "", contact_name: "", contact_phone: "",
  contact_email: "", active: true }
const emptyExperience = { name: "", modified: "", experience_name: "",
  experience_category: "Other", pms_product: "", duration: "", description: "",
  show_on_booking_page: false, active: true }

export function TravelExperiences({ property, canSetup, canReserve, canService, canCommission, canFinance, canApprove }: {
  property: Property; canSetup: boolean; canReserve: boolean; canService: boolean;
  canCommission: boolean; canFinance: boolean; canApprove: boolean
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableTravelSections({ provider: "pms", setup: canSetup, reserve: canReserve, service: canService,
    commission: canCommission, finance: canFinance, approve: canApprove })
  const requestedSection = searchParams.get("section")
  const agentId = searchParams.get("agent")
  const experienceId = searchParams.get("experience")
  const resolvedSection = requestedSection === "commissions" ?
    (canCommission ? "commissions-settle" : canFinance ? "commissions-pay" : canApprove ? "commissions-cancel" : "orders") : requestedSection
  const section = sections.find((item) => item.id === resolvedSection) || sections[0]
  useEffect(() => {
    if (!requestedSection || requestedSection === section.id) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section.id)
    setSearchParams(next, { replace: true })
  }, [requestedSection, section.id, searchParams, setSearchParams])
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [agentForm, setAgentForm] = useState(emptyAgent)
  const [experienceForm, setExperienceForm] = useState(emptyExperience)
  const [booking, setBooking] = useState("")
  const [experience, setExperience] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [quote, setQuote] = useState<OrderQuote | null>(null)
  const [requestKey, setRequestKey] = useState("")
  const [selectedOrder, setSelectedOrder] = useState("")
  const [scheduledAt, setScheduledAt] = useState("")
  const [participants, setParticipants] = useState("1")
  const [stay, setStay] = useState("")
  const [folio, setFolio] = useState("")
  const [reason, setReason] = useState("")
  const [commissionBooking, setCommissionBooking] = useState("")
  const [commissionQuote, setCommissionQuote] = useState<CommissionQuote | null>(null)
  const [commissionKey, setCommissionKey] = useState("")
  const [expenseAccount, setExpenseAccount] = useState("")
  const [payableAccount, setPayableAccount] = useState("")
  const [paymentCommission, setPaymentCommission] = useState("")
  const [paymentMethod, setPaymentMethod] = useState("")
  const [paymentShift, setPaymentShift] = useState("")
  const [paymentAmount, setPaymentAmount] = useState("")
  const [paymentReference, setPaymentReference] = useState("")
  const [paymentReason, setPaymentReason] = useState("")
  const [paymentQuote, setPaymentQuote] = useState<PaymentQuote | null>(null)
  const [paymentKey, setPaymentKey] = useState("")
  const [cancelReason, setCancelReason] = useState("")

  const refresh = useCallback(async () => {
    const snapshot = await call<Snapshot>("pms_travel_experiences_snapshot",
      { property_name: property.name })
    setData(snapshot)
    setExpenseAccount(snapshot.commission_expense_account || "")
    setPayableAccount(snapshot.commission_payable_account || "")
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setQuote(null); setRequestKey("")
    setAgentForm(emptyAgent); setExperienceForm(emptyExperience)
    setBooking(""); setExperience(""); setSelectedOrder("")
    setCommissionBooking(""); setCommissionQuote(null); setPaymentCommission("")
    setPaymentQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar agencias y experiencias."))
  }, [refresh])
  useEffect(() => {
    setCommissionBooking(""); setCommissionQuote(null); setCommissionKey("")
    setPaymentCommission(""); setPaymentMethod(""); setPaymentShift("")
    setPaymentAmount(""); setPaymentReference(""); setPaymentReason("")
    setPaymentQuote(null); setPaymentKey(""); setCancelReason("")
    setSelectedOrder(""); setReason("")
  }, [section.id])
  useEffect(() => {
    if (!data || section.id !== "agency-form") return
    const row = data.agents.find((item) => item.name === agentId)
    setAgentForm(row ? { name: row.name, modified: row.modified,
      agent_name: row.agent_name, agent_type: row.agent_type,
      commission_pct: String(row.commission_pct), pms_supplier: row.pms_supplier || "",
      contact_name: row.contact_name || "", contact_phone: row.contact_phone || "",
      contact_email: row.contact_email || "", active: !!row.active } : emptyAgent)
  }, [data, section.id, agentId])
  useEffect(() => {
    if (!data || section.id !== "experience-form") return
    const row = data.experiences.find((item) => item.name === experienceId)
    setExperienceForm(row ? { name: row.name, modified: row.modified,
      experience_name: row.experience_name, experience_category: row.experience_category,
      pms_product: row.pms_product || "", duration: row.duration || "",
      description: row.description || "", show_on_booking_page: !!row.show_on_booking_page,
      active: !!row.active } : emptyExperience)
  }, [data, section.id, experienceId])

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canSetup || section.id !== "agency-form" ||
      agentId && agentForm.name !== agentId) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "travel_agent", {
        ...(agentForm.name ? { agent: agentForm.name, modified: agentForm.modified } : {}),
        agent_name: agentForm.agent_name.trim(), agent_type: agentForm.agent_type,
        commission_pct: agentForm.commission_pct, pms_supplier: agentForm.pms_supplier || null,
        contact_name: agentForm.contact_name.trim(), contact_phone: agentForm.contact_phone.trim(),
        contact_email: agentForm.contact_email.trim(), active: agentForm.active,
      }, crypto.randomUUID())
      await refresh(); setAgentForm(emptyAgent); setSearchParams({ section: "agencies" })
      setNotice("Agencia guardada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la agencia.") }
    finally { setBusy(false) }
  }
  async function saveExperience(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canSetup || section.id !== "experience-form" ||
      experienceId && experienceForm.name !== experienceId) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "experience", {
        ...(experienceForm.name ? { experience: experienceForm.name,
          modified: experienceForm.modified } : {}),
        experience_name: experienceForm.experience_name.trim(),
        experience_category: experienceForm.experience_category,
        pms_product: experienceForm.pms_product, duration: experienceForm.duration.trim(),
        description: experienceForm.description.trim(),
        show_on_booking_page: experienceForm.show_on_booking_page,
        active: experienceForm.active,
      }, crypto.randomUUID())
      await refresh(); setExperienceForm(emptyExperience); setSearchParams({ section: "experiences" })
      setNotice("Experiencia guardada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la experiencia.") }
    finally { setBusy(false) }
  }
  async function order(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canReserve) return
    setBusy(true); setError(""); setNotice("")
    const request = { booking, experience, quantity: Number(quantity) }
    try {
      if (!quote) {
        setQuote(await call<OrderQuote>("preview", { property_name: property.name,
          action: "experience_order", data: JSON.stringify(request) }))
        setRequestKey(crypto.randomUUID())
      } else {
        const result = await execute<{ order: string }>(property.name, "experience_order",
          { ...request, acceptance: quote.acceptance }, requestKey)
        await refresh(); setQuote(null); setRequestKey("")
        setNotice(`Experiencia ${result.order} reservada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo reservar la experiencia.") }
    finally { setBusy(false) }
  }
  function selectOrder(row: Order) {
    setSelectedOrder(row.name); setScheduledAt(row.scheduled_at?.replace(" ", "T").slice(0, 16) || "")
    setParticipants(String(row.participants || row.quantity)); setStay(row.stay || "")
    setFolio(row.folio || ""); setReason(""); setError("")
  }
  async function updateOrder(status: "Confirmed" | "Delivered" | "Cancelled") {
    const row = data?.orders.find((item) => item.name === selectedOrder)
    const requiredSection = status === "Confirmed" ? "orders-confirm" :
      status === "Delivered" ? "orders-deliver" : "orders-cancel"
    if (!row || busy || !canService || section.id !== requiredSection) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "experience_status", { order: row.name,
        modified: row.modified, status,
        ...(status === "Confirmed" ? { scheduled_at: scheduledAt,
          participants: Number(participants) } : {}),
        ...(status === "Delivered" ? { stay: stay || undefined,
          folio: folio || undefined } : {}),
        ...(status === "Cancelled" ? { reason: reason.trim() } : {}),
      }, crypto.randomUUID())
      await refresh(); setSelectedOrder(""); setNotice("Estado de la experiencia actualizado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la experiencia.") }
    finally { setBusy(false) }
  }
  async function saveCommissionAccounts(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !data || !canSetup) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "property",
        data: { pms_commission_expense_account: expenseAccount,
          pms_commission_payable_account: payableAccount },
        request_key: crypto.randomUUID(), expected_modified: data.property_modified })
      setCommissionQuote(null); await refresh(); setNotice("Cuentas de comisión guardadas.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron guardar las cuentas.") }
    finally { setBusy(false) }
  }
  async function settleCommission() {
    if (busy || !commissionBooking || !canCommission) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!commissionQuote) {
        setCommissionQuote(await call<CommissionQuote>("preview", {
          property_name: property.name, action: "agent_commission",
          data: JSON.stringify({ booking: commissionBooking }) }))
        setCommissionKey(crypto.randomUUID())
      } else {
        const result = await execute<{ commission: string }>(property.name,
          "agent_commission", { booking: commissionBooking,
            modified: commissionQuote.modified, acceptance: commissionQuote.acceptance },
          commissionKey)
        setCommissionBooking(""); setCommissionQuote(null); setCommissionKey("")
        await refresh(); setNotice(`Comisión ${result.commission} contabilizada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo liquidar la comisión.") }
    finally { setBusy(false) }
  }
  async function payCommission() {
    if (busy || !canFinance || !paymentCommission) return
    setBusy(true); setError(""); setNotice("")
    const request = { commission: paymentCommission, method: paymentMethod,
      ...(data?.methods.find((row) => row.name === paymentMethod)?.is_cash ?
        { shift: paymentShift } : {}), amount: paymentAmount,
      reference: paymentReference.trim(), reason: paymentReason.trim() }
    try {
      if (!paymentQuote) {
        setPaymentQuote(await call<PaymentQuote>("pms_agent_commission_payment_quote",
          { property_name: property.name, data: JSON.stringify(request) }))
        setPaymentKey(crypto.randomUUID())
      } else {
        const result = await execute<{ payment: string }>(property.name,
          "pms_pay_agent_commission", { ...request, acceptance: paymentQuote.acceptance }, paymentKey)
        setPaymentQuote(null); setPaymentKey(""); setPaymentCommission(""); setPaymentAmount("");
        setPaymentReference(""); setPaymentReason("")
        await refresh(); setNotice(`Pago ${result.payment} contabilizado.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo pagar la comisión.") }
    finally { setBusy(false) }
  }
  async function cancelCommission(row: Snapshot["commissions"][number]) {
    if (busy || !canApprove || !cancelReason.trim()) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_cancel_agent_commission", {
        commission: row.name, modified: row.modified, reason: cancelReason.trim(),
      }, crypto.randomUUID())
        setCancelReason(""); setPaymentCommission(""); await refresh(); setNotice("Comisión anulada con asiento inverso.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo anular la comisión.") }
    finally { setBusy(false) }
  }
  const current = data?.orders.find((row) => row.name === selectedOrder)
  const displayedOrders = data?.orders.filter((row) => !!row.booking && (
    section.id === "orders-confirm" ? row.status === "Reserved" :
      section.id === "orders-deliver" ? row.status === "Confirmed" :
        section.id === "orders-cancel" ? ["Reserved", "Confirmed"].includes(row.status) : true)) || []
  const stayOptions = data?.stays.filter((row) => row.booking === current?.booking) || []
  const folioOptions = data?.folios.filter((row) => stayOptions.some((item) =>
    item.name === row.stay || !row.stay && row.booking === item.booking)) || []
  const nameOf = (id: string) => data?.experiences.find((row) => row.name === id)?.experience_name || id
  const displayedCommissions = data?.commissions.filter((row) =>
    section.id === "commissions-pay" ? row.status === "Posted" && Number(row.outstanding) > 0 :
      section.id === "commissions-cancel" ? row.status === "Posted" && Number(row.outstanding) === Number(row.amount) : true) || []
  function selectCommission(name: string) {
    setPaymentCommission(name); setPaymentMethod(""); setPaymentShift("")
    setPaymentAmount(""); setPaymentReference(""); setPaymentReason("")
    setPaymentQuote(null); setPaymentKey(""); setCancelReason("")
  }
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Agencias y experiencias</p>
      <h1 className="mt-1 text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{section.description}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-72 rounded-xl" /> : <>
      {canSetup && (section.id === "agency-form" || section.id === "experience-form") && <div className="max-w-2xl space-y-5">
        {section.id === "agency-form" && agentId && !data.agents.some((row) => row.name === agentId) && <p role="alert" className="text-sm text-destructive">No se encontró la agencia solicitada.</p>}
        {section.id === "agency-form" && (!agentId || data.agents.some((row) => row.name === agentId)) && <Card><CardHeader><CardTitle>{agentId ? "Editar agencia" : "Nueva agencia"}</CardTitle><CardDescription>La comisión se congela al confirmar cada reserva.</CardDescription></CardHeader><CardContent><form onSubmit={saveAgent} className="space-y-3">
          <Input required maxLength={140} placeholder="Nombre de agencia" value={agentForm.agent_name} onChange={(event) => setAgentForm({ ...agentForm, agent_name: event.target.value })} />
          <div className="grid gap-3 sm:grid-cols-2"><select value={agentForm.agent_type} onChange={(event) => setAgentForm({ ...agentForm, agent_type: event.target.value })} className="h-9 rounded-md border border-border bg-white px-2 text-sm">{agentTypes.map((type) => <option key={type}>{type}</option>)}</select><Input required type="number" min="0" max="100" step="0.01" placeholder="Comisión %" value={agentForm.commission_pct} onChange={(event) => setAgentForm({ ...agentForm, commission_pct: event.target.value })} /></div>
          <select value={agentForm.pms_supplier} onChange={(event) => setAgentForm({ ...agentForm, pms_supplier: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Sin proveedor vinculado</option>{data.suppliers.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select>
          <Input maxLength={140} placeholder="Persona de contacto" value={agentForm.contact_name} onChange={(event) => setAgentForm({ ...agentForm, contact_name: event.target.value })} /><Input maxLength={140} placeholder="Teléfono" value={agentForm.contact_phone} onChange={(event) => setAgentForm({ ...agentForm, contact_phone: event.target.value })} /><Input type="email" maxLength={140} placeholder="Correo" value={agentForm.contact_email} onChange={(event) => setAgentForm({ ...agentForm, contact_email: event.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={agentForm.active} onChange={(event) => setAgentForm({ ...agentForm, active: event.target.checked })} /> Activa</label><div className="flex gap-2"><Button disabled={busy || !!agentId && agentForm.name !== agentId}>Guardar agencia</Button><Button type="button" variant="outline" onClick={() => setSearchParams({ section: "agencies" })}>Volver al directorio</Button></div>
        </form></CardContent></Card>}
        {section.id === "experience-form" && experienceId && !data.experiences.some((row) => row.name === experienceId) && <p role="alert" className="text-sm text-destructive">No se encontró la experiencia solicitada.</p>}
        {section.id === "experience-form" && (!experienceId || data.experiences.some((row) => row.name === experienceId)) && <Card><CardHeader><CardTitle>{experienceId ? "Editar experiencia" : "Nueva experiencia"}</CardTitle><CardDescription>Use un producto de servicio PMS con precio e impuesto configurados.</CardDescription></CardHeader><CardContent><form onSubmit={saveExperience} className="space-y-3">
          <Input required maxLength={140} placeholder="Nombre de la experiencia" value={experienceForm.experience_name} onChange={(event) => setExperienceForm({ ...experienceForm, experience_name: event.target.value })} />
          <div className="grid gap-3 sm:grid-cols-2"><select value={experienceForm.experience_category} onChange={(event) => setExperienceForm({ ...experienceForm, experience_category: event.target.value })} className="h-9 rounded-md border border-border bg-white px-2 text-sm">{categories.map((type) => <option key={type}>{type}</option>)}</select><select required value={experienceForm.pms_product} onChange={(event) => setExperienceForm({ ...experienceForm, pms_product: event.target.value })} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Producto de servicio PMS</option>{data.products.filter((row) => !!row.tax_profile).map((row) => <option key={row.name} value={row.name}>{row.product_name} · {data.currency} {row.sales_rate}</option>)}</select></div>
          <Input maxLength={140} placeholder="Duración" value={experienceForm.duration} onChange={(event) => setExperienceForm({ ...experienceForm, duration: event.target.value })} /><Input maxLength={500} placeholder="Descripción" value={experienceForm.description} onChange={(event) => setExperienceForm({ ...experienceForm, description: event.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={experienceForm.show_on_booking_page} onChange={(event) => setExperienceForm({ ...experienceForm, show_on_booking_page: event.target.checked })} /> Mostrar en portal</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={experienceForm.active} onChange={(event) => setExperienceForm({ ...experienceForm, active: event.target.checked })} /> Activa</label>
          <div className="flex gap-2"><Button disabled={busy || !!experienceId && experienceForm.name !== experienceId}>Guardar experiencia</Button><Button type="button" variant="outline" onClick={() => setSearchParams({ section: "experiences" })}>Volver al catálogo</Button></div>
        </form></CardContent></Card>}
      </div>}
      {section.id === "agencies" && <Card className="max-w-2xl"><CardHeader><CardTitle>Directorio de agencias</CardTitle><CardDescription>Consulte la comisión y el estado de cada agencia.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
        {canSetup && <Button asChild size="sm"><Link to="?section=agency-form">Registrar agencia</Link></Button>}
        {data.agents.map((row) => <div key={row.name} className="flex items-center justify-between gap-2 border-b pb-2"><span>{row.agent_name} · {row.commission_pct}%{!row.active && " · Inactiva"}</span>{canSetup && <Button size="sm" variant="outline" onClick={() => setSearchParams({ section: "agency-form", agent: row.name })}>Editar</Button>}</div>)}
        {!data.agents.length && <p className="text-muted-foreground">Sin agencias registradas.</p>}
      </CardContent></Card>}
      {section.id === "experiences" && <Card className="max-w-2xl"><CardHeader><CardTitle>Catálogo de experiencias</CardTitle><CardDescription>Consulte los servicios disponibles para reservas.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
        {canSetup && <Button asChild size="sm"><Link to="?section=experience-form">Registrar experiencia</Link></Button>}
        {data.experiences.map((row) => <div key={row.name} className="flex items-center justify-between gap-2 border-b pb-2"><span>{row.experience_name}{!row.active && " · Inactiva"}</span>{canSetup && <Button size="sm" variant="outline" onClick={() => setSearchParams({ section: "experience-form", experience: row.name })}>Editar</Button>}</div>)}
        {!data.experiences.length && <p className="text-muted-foreground">Sin experiencias registradas.</p>}
      </CardContent></Card>}
      {section.id === "reserve" && canReserve && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Reservar experiencia adicional</CardTitle><CardDescription>También puede añadir experiencias al confirmar la reserva en <Link className="text-primary underline" to="/reception?section=reservation">Recepción</Link>.</CardDescription></CardHeader><CardContent><form onSubmit={order} className="space-y-3"><select required value={booking} onChange={(event) => { setBooking(event.target.value); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione reserva</option>{data.bookings.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.status}</option>)}</select><select required value={experience} onChange={(event) => { setExperience(event.target.value); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione experiencia</option>{data.experiences.filter((row) => row.active).map((row) => <option key={row.name} value={row.name}>{row.experience_name}</option>)}</select><Input required type="number" min="1" max="1000" step="1" value={quantity} onChange={(event) => { setQuantity(event.target.value); setQuote(null) }} /><Button disabled={busy || !booking || !experience}>{quote ? "Confirmar experiencia" : "Revisar precio"}</Button>{quote && <p className="rounded-lg bg-secondary p-3 text-sm">{quote.line.name} × {quote.line.quantity} · {quote.currency} {quote.line.total_amount || quote.line.amount}{quote.line.tax_amount && ` · impuesto ${quote.line.tax_amount}`}</p>}</form></CardContent></Card></div>}
      {section.id === "agency-contribution" && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Agencias atribuidas</CardTitle><CardDescription>Estimaciones al reservar; el devengo final usa el alojamiento facturado sin impuestos.</CardDescription></CardHeader><CardContent className="space-y-2 text-sm">{data.contribution.map((row) => <p key={row.travel_agent}>{data.agents.find((agent) => agent.name === row.travel_agent)?.agent_name || row.travel_agent}: {row.bookings} reservas · alojamiento {data.currency} {row.accepted_lodging} · comisión estimada {data.currency} {row.estimated_commission}</p>)}{!data.contribution.length && <p className="text-muted-foreground">Sin reservas atribuidas.</p>}</CardContent></Card></div>}
      {((section.id === "commission-accounts" && canSetup) || section.id === "commissions-settle" ||
        section.id === "commissions-pay" || section.id === "commissions-cancel" ||
        section.id === "commissions-history") && <div className="max-w-3xl space-y-5">
        {section.id === "commission-accounts" && canSetup && <Card><CardHeader><CardTitle>Cuentas de comisión PMS</CardTitle><CardDescription>El devengo carga gasto y abona la cuenta por pagar en {data.currency}.</CardDescription></CardHeader><CardContent><form onSubmit={saveCommissionAccounts} className="space-y-3"><select required value={expenseAccount} onChange={(event) => setExpenseAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de gasto</option>{data.commission_accounts.filter((row) => row.root_type === "Expense").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select><select required value={payableAccount} onChange={(event) => setPayableAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por pagar</option>{data.commission_accounts.filter((row) => row.root_type === "Liability" && row.account_type === "Payable").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select><Button disabled={busy}>Guardar cuentas</Button></form></CardContent></Card>}
        {section.id === "commissions-settle" && canCommission && <Card><CardHeader><CardTitle>Liquidar comisión</CardTitle><CardDescription>Seleccione una reserva completada con agencia y alojamiento facturado.</CardDescription></CardHeader><CardContent className="space-y-3"><select value={commissionBooking} onChange={(event) => { setCommissionBooking(event.target.value); setCommissionQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione reserva</option>{data.bookings.filter((row) => row.status === "Completed" && row.travel_agent && !row.pms_agent_commission).map((row) => <option key={row.name} value={row.name}>{row.name} · {data.agents.find((agent) => agent.name === row.travel_agent)?.agent_name || row.travel_agent}</option>)}</select>{commissionQuote && <p className="rounded-lg bg-secondary p-3 text-sm">{commissionQuote.agent_name} · base {commissionQuote.currency} {commissionQuote.base} × {commissionQuote.percent}% = {commissionQuote.currency} {commissionQuote.amount}<span className="block text-muted-foreground">Proveedor {commissionQuote.supplier} · gasto {commissionQuote.expense_account} · por pagar {commissionQuote.payable_account}</span></p>}<Button disabled={busy || !commissionBooking} onClick={() => void settleCommission()}>{commissionQuote ? "Contabilizar comisión" : "Revisar liquidación"}</Button></CardContent></Card>}
        {["commissions-pay", "commissions-cancel", "commissions-history"].includes(section.id) && <Card><CardHeader><CardTitle>{section.label}</CardTitle><CardDescription>El saldo pendiente descuenta los abonos registrados por Caja o banco.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">{displayedCommissions.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2"><span><strong>{row.agent_name}</strong> · {row.booking} · {row.currency} {row.amount}<span className="block text-muted-foreground">{row.name} · {row.status} · pendiente {row.currency} {row.outstanding}</span></span><div className="flex gap-2">{section.id === "commissions-pay" && canFinance && row.status === "Posted" && Number(row.outstanding) > 0 && <Button size="sm" variant="outline" onClick={() => selectCommission(row.name)}>Pagar</Button>}{section.id === "commissions-cancel" && canApprove && row.status === "Posted" && Number(row.outstanding) === Number(row.amount) && <Button size="sm" variant="outline" onClick={() => selectCommission(row.name)}>Anular</Button>}</div></div>)}{!displayedCommissions.length && <p className="text-muted-foreground">Sin comisiones para esta opción.</p>}{(section.id === "commissions-pay" || section.id === "commissions-cancel") && paymentCommission && (() => { const selected = data.commissions.find((row) => row.name === paymentCommission); return selected?.status === "Posted" ? <div className="space-y-3 rounded-lg border p-3"><strong>{selected.agent_name} · {selected.name}</strong>{section.id === "commissions-pay" && canFinance && Number(selected.outstanding) > 0 && <div className="grid gap-3 sm:grid-cols-2"><select value={paymentMethod} onChange={(event) => { setPaymentMethod(event.target.value); setPaymentQuote(null) }} className="h-9 rounded-md border border-border bg-white px-2"><option value="">Medio de pago</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select>{data.methods.find((row) => row.name === paymentMethod)?.is_cash && <select value={paymentShift} onChange={(event) => { setPaymentShift(event.target.value); setPaymentQuote(null) }} className="h-9 rounded-md border border-border bg-white px-2"><option value="">Turno de Caja</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>}<Input type="number" min="0.01" step="0.01" placeholder="Importe en moneda del medio" value={paymentAmount} onChange={(event) => { setPaymentAmount(event.target.value); setPaymentQuote(null) }} /><Input maxLength={140} placeholder="Referencia" value={paymentReference} onChange={(event) => { setPaymentReference(event.target.value); setPaymentQuote(null) }} /><Input maxLength={500} placeholder="Motivo del pago" value={paymentReason} onChange={(event) => { setPaymentReason(event.target.value); setPaymentQuote(null) }} /></div>}{section.id === "commissions-pay" && paymentQuote && <p className="rounded-lg bg-secondary p-3">Pago {paymentQuote.currency} {paymentQuote.amount} · cambio {paymentQuote.exchange_rate} · base {paymentQuote.base_currency} {paymentQuote.base_amount} · pendiente {paymentQuote.base_currency} {paymentQuote.outstanding_after}</p>}<div className="flex flex-wrap gap-2">{section.id === "commissions-pay" && canFinance && Number(selected.outstanding) > 0 && <Button disabled={busy || !paymentMethod || !paymentAmount || !paymentReference.trim() || !paymentReason.trim() || !!data.methods.find((row) => row.name === paymentMethod)?.is_cash && !paymentShift} onClick={() => void payCommission()}>{paymentQuote ? "Contabilizar pago" : "Revisar pago"}</Button>}{section.id === "commissions-cancel" && canApprove && Number(selected.outstanding) === Number(selected.amount) && <><Input maxLength={500} placeholder="Motivo de anulación" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} /><Button variant="outline" disabled={busy || !cancelReason.trim()} onClick={() => void cancelCommission(selected)}>Anular con asiento inverso</Button></>}<Button variant="ghost" onClick={() => selectCommission("")}>Cerrar</Button></div></div> : null })()}</CardContent></Card>}
      </div>}
      {section.id === "direct" && canFinance && <DirectExperienceSales property={property} data={data} onChanged={refresh} canApprove={canApprove} />}
      {["orders", "orders-confirm", "orders-deliver", "orders-cancel"].includes(section.id) && <Card>
        <CardHeader><CardTitle>{section.label}</CardTitle>
          <CardDescription>{section.id === "orders" ? "Consulte las órdenes y sus cargos en Cuentas de estancia." : section.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {displayedOrders.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 text-sm">
            <span><strong>{nameOf(row.experience)}</strong> × {row.quantity} · {row.currency} {row.amount}
              <span className="block text-muted-foreground">{row.name} · reserva {row.booking} · {row.status}{row.charge && ` · cargo ${row.charge}`}</span>
            </span>
            {section.id !== "orders" && canService && <Button size="sm" variant="outline" onClick={() => selectOrder(row)}>
              {section.id === "orders-confirm" ? "Programar" : section.id === "orders-deliver" ? "Entregar" : "Cancelar"}
            </Button>}
          </div>)}
          {!displayedOrders.length && <p className="text-sm text-muted-foreground">Sin órdenes para esta opción.</p>}
          {current && section.id !== "orders" && <div className="space-y-3 rounded-lg border p-3 text-sm">
            <strong>{nameOf(current.experience)} · {current.name}</strong>
            {section.id === "orders-confirm" && current.status === "Reserved" && <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1"><span>Fecha y hora</span><Input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>
              <label className="space-y-1"><span>Participantes</span><Input type="number" min="1" max="1000" step="1" value={participants} onChange={(event) => setParticipants(event.target.value)} /></label>
            </div>}
            {section.id === "orders-deliver" && current.status === "Confirmed" && <div className="grid gap-3 sm:grid-cols-2">
              <select value={stay} onChange={(event) => { setStay(event.target.value); setFolio("") }} className="h-9 rounded-md border border-border bg-white px-2">
                <option value="">Estancia automática si es única</option>{stayOptions.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}
              </select>
              <select value={folio} onChange={(event) => setFolio(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2">
                <option value="">Cuenta automática si es única</option>{folioOptions.filter((row) => !stay || row.stay === stay || !row.stay && row.booking === current.booking).map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name}</option>)}
              </select>
            </div>}
            {section.id === "orders-cancel" && <Input maxLength={500} placeholder="Motivo de cancelación" value={reason} onChange={(event) => setReason(event.target.value)} />}
            <div className="flex flex-wrap gap-2">
              {section.id === "orders-confirm" && current.status === "Reserved" && <Button disabled={busy || !scheduledAt} onClick={() => void updateOrder("Confirmed")}>Confirmar horario</Button>}
              {section.id === "orders-deliver" && current.status === "Confirmed" && <Button disabled={busy || !stayOptions.length} onClick={() => void updateOrder("Delivered")}>Entregar y cargar a la cuenta</Button>}
              {section.id === "orders-cancel" && <Button disabled={busy || !reason.trim()} variant="outline" onClick={() => void updateOrder("Cancelled")}>Cancelar orden</Button>}
              <Button variant="ghost" onClick={() => setSelectedOrder("")}>Cerrar</Button>
            </div>
          </div>}
        </CardContent>
      </Card>}
    </>}
  </div>
}
