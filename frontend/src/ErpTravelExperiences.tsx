import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { availableTravelSections } from "./TravelSections"

type Agent = { name: string; agent_name: string; agent_type: string; commission_pct: number;
  supplier: string | null; contact_name: string; contact_phone: string;
  contact_email: string; active: number; modified: string }
type Experience = { name: string; experience_name: string; experience_category: string;
  item: string | null; duration: string; description: string;
  show_on_booking_page: number; active: number; modified: string }
type Order = { name: string; experience: string; booking: string | null; customer: string;
  stay: string | null; folio: string | null; quantity: number; participants: number;
  scheduled_at: string | null; amount: number; currency: string; status: string;
  charge: string | null; modified: string }
type Booking = { name: string; customer: string; status: string; travel_agent: string | null;
  agent_commission_invoice: string | null; pms_agent_commission: string | null }
type Snapshot = { currency: string; agents: Agent[]; experiences: Experience[];
  orders: Order[]; bookings: Booking[];
  suppliers: { name: string; supplier_name: string }[];
  stays: { name: string; booking: string; room: string }[];
  folios: { name: string; booking: string | null; stay: string | null;
    customer: string; label: string | null }[];
  contribution: { travel_agent: string; bookings: number; accepted_lodging: number;
    estimated_commission: number }[] }
type ItemChoice = { name: string; item_name: string; display_name: string }
type OrderQuote = { acceptance: string; currency: string; line: { amount: string;
  total_amount?: string; tax_amount?: string; name: string } }
type CommissionQuote = { booking: string; modified: string; supplier: string;
  base: string; percent: string; amount: string; currency: string;
  item: string; expense_account: string }

const agentTypes = ["Travel Agent", "OTA", "Tour Operator", "Corporate Desk"]
const categories = ["Spa", "Tour", "Dining", "Activity", "Transport", "Other"]
const emptyAgent = { name: "", modified: "", agent_name: "", agent_type: "Travel Agent",
  commission_pct: "0", supplier: "", contact_name: "", contact_phone: "",
  contact_email: "", active: true }
const emptyExperience = { name: "", modified: "", experience_name: "",
  experience_category: "Other", item: "", duration: "", description: "",
  show_on_booking_page: false, active: true }

export function ErpTravelExperiences({ property, canSetup, canReserve, canService,
  canCommission, canFinance }: { property: Property; canSetup: boolean;
  canReserve: boolean; canService: boolean; canCommission: boolean; canFinance: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableTravelSections({ provider: "erpnext", setup: canSetup,
    reserve: canReserve, service: canService, commission: canCommission, finance: canFinance, approve: false })
  const requestedSection = searchParams.get("section")
  const agentId = searchParams.get("agent")
  const experienceId = searchParams.get("experience")
  const resolvedSection = requestedSection === "commissions" ? "commissions-settle" : requestedSection
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
  const [itemQuery, setItemQuery] = useState("")
  const [itemChoices, setItemChoices] = useState<ItemChoice[]>([])
  const [itemError, setItemError] = useState("")
  const [booking, setBooking] = useState("")
  const [experience, setExperience] = useState("")
  const [quantity, setQuantity] = useState("1")
  const [orderQuote, setOrderQuote] = useState<(OrderQuote & { key: string }) | null>(null)
  const [selectedOrder, setSelectedOrder] = useState("")
  const [scheduledAt, setScheduledAt] = useState("")
  const [participants, setParticipants] = useState("1")
  const [stay, setStay] = useState("")
  const [folio, setFolio] = useState("")
  const [cancelReason, setCancelReason] = useState("")
  const [commissionBooking, setCommissionBooking] = useState("")
  const [commissionQuote, setCommissionQuote] = useState<(CommissionQuote & { key: string }) | null>(null)

  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("erp_travel_experiences_snapshot",
      { property_name: property.name }))
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setAgentForm(emptyAgent)
    setExperienceForm(emptyExperience); setItemQuery(""); setItemChoices([])
    setBooking(""); setExperience(""); setOrderQuote(null); setSelectedOrder("")
    setCommissionBooking(""); setCommissionQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message :
      "No se pudieron consultar las agencias y experiencias."))
  }, [refresh])
  useEffect(() => {
    setSelectedOrder(""); setCancelReason("")
  }, [section.id])
  useEffect(() => {
    if (!data || section.id !== "agency-form") return
    const row = data.agents.find((item) => item.name === agentId)
    setAgentForm(row ? { name: row.name, modified: row.modified,
      agent_name: row.agent_name, agent_type: row.agent_type,
      commission_pct: String(row.commission_pct), supplier: row.supplier || "",
      contact_name: row.contact_name || "", contact_phone: row.contact_phone || "",
      contact_email: row.contact_email || "", active: !!row.active } : emptyAgent)
  }, [data, section.id, agentId])
  useEffect(() => {
    if (!data || section.id !== "experience-form") return
    const row = data.experiences.find((item) => item.name === experienceId)
    setExperienceForm(row ? { name: row.name, modified: row.modified,
      experience_name: row.experience_name, experience_category: row.experience_category,
      item: row.item || "", duration: row.duration || "", description: row.description || "",
      show_on_booking_page: !!row.show_on_booking_page, active: !!row.active } : emptyExperience)
  }, [data, section.id, experienceId])
  useEffect(() => {
    if (!canSetup || section.id !== "experience-form") return
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
  }, [property.name, canSetup, itemQuery, section.id])

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canSetup || section.id !== "agency-form" ||
      agentId && agentForm.name !== agentId) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "travel_agent", {
        ...(agentForm.name ? { agent: agentForm.name, modified: agentForm.modified } : {}),
        agent_name: agentForm.agent_name.trim(), agent_type: agentForm.agent_type,
        commission_pct: agentForm.commission_pct, supplier: agentForm.supplier || null,
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
        item: experienceForm.item, duration: experienceForm.duration.trim(),
        description: experienceForm.description.trim(),
        show_on_booking_page: experienceForm.show_on_booking_page,
        active: experienceForm.active,
      }, crypto.randomUUID())
      await refresh(); setExperienceForm(emptyExperience); setSearchParams({ section: "experiences" })
      setNotice("Experiencia guardada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la experiencia. Revise el precio del artículo en la lista del establecimiento.") }
    finally { setBusy(false) }
  }
  async function reserve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canReserve) return
    setBusy(true); setError(""); setNotice("")
    const request = { booking, experience, quantity: Number(quantity) }
    try {
      if (!orderQuote) {
        const reviewed = await call<OrderQuote>("preview", { property_name: property.name,
          action: "experience_order", data: JSON.stringify(request) })
        setOrderQuote({ ...reviewed, key: crypto.randomUUID() })
      } else {
        const result = await execute<{ order: string }>(property.name, "experience_order",
          { ...request, acceptance: orderQuote.acceptance }, orderQuote.key)
        await refresh(); setOrderQuote(null); setExperience(""); setQuantity("1")
        setNotice(`Experiencia ${result.order} reservada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo reservar la experiencia.") }
    finally { setBusy(false) }
  }
  const selected = data?.orders.find((row) => row.name === selectedOrder)
  const displayedOrders = data?.orders.filter((row) => !!row.booking && (
    section.id === "orders-confirm" ? row.status === "Reserved" :
      section.id === "orders-deliver" ? row.status === "Confirmed" :
        section.id === "orders-cancel" ? ["Reserved", "Confirmed"].includes(row.status) : true)) || []
  const stayOptions = data?.stays.filter((row) => row.booking === selected?.booking) || []
  const folioOptions = data?.folios.filter((row) => selected &&
    row.customer === selected.customer && (row.stay === stay ||
      !row.stay && row.booking === selected.booking)) || []
  async function updateOrder(status: "Confirmed" | "Delivered" | "Cancelled") {
    const requiredSection = status === "Confirmed" ? "orders-confirm" :
      status === "Delivered" ? "orders-deliver" : "orders-cancel"
    if (!selected || !canService || busy || section.id !== requiredSection) return
    setBusy(true); setError(""); setNotice("")
    try {
      const request = { order: selected.name, modified: selected.modified, status,
        ...(status === "Confirmed" ? { scheduled_at: scheduledAt,
          participants: Number(participants) } : {}),
        ...(status === "Delivered" ? { stay, folio } : {}),
        ...(status === "Cancelled" ? { reason: cancelReason.trim() } : {}) }
      await execute(property.name, "experience_status", request, crypto.randomUUID())
      await refresh(); setSelectedOrder(""); setCancelReason("")
      setNotice(status === "Delivered" ? "Experiencia entregada; cargo pendiente en la cuenta de estancia." :
        status === "Confirmed" ? "Horario confirmado." : "Experiencia cancelada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la experiencia.") }
    finally { setBusy(false) }
  }
  async function settleCommission() {
    if (!canCommission || !commissionBooking || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!commissionQuote) {
        const reviewed = await call<CommissionQuote>("preview", {
          property_name: property.name, action: "agent_commission",
          data: JSON.stringify({ booking: commissionBooking }) })
        setCommissionQuote({ ...reviewed, key: crypto.randomUUID() })
      } else {
        const result = await execute<{ invoice: string }>(property.name,
          "agent_commission", { booking: commissionBooking,
            modified: commissionQuote.modified }, commissionQuote.key)
        await refresh(); setCommissionBooking(""); setCommissionQuote(null)
        setNotice(`Comisión contabilizada en ${result.invoice}.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo liquidar la comisión.") }
    finally { setBusy(false) }
  }
  const agentName = (name: string | null) => data?.agents.find((row) => row.name === name)?.agent_name || name
  const experienceName = (name: string) => data?.experiences.find((row) => row.name === name)?.experience_name || name
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Agencias y experiencias</p>
      <h1 className="mt-1 text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{section.description}. Los cargos y comisiones se contabilizan en ERPNext.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-72 rounded-xl" /> : <>
      {canSetup && (section.id === "agency-form" || section.id === "experience-form") && <div className="max-w-2xl space-y-5">
        {section.id === "agency-form" && agentId && !data.agents.some((row) => row.name === agentId) && <p role="alert" className="text-sm text-destructive">No se encontró la agencia solicitada.</p>}
        {section.id === "agency-form" && (!agentId || data.agents.some((row) => row.name === agentId)) && <Card><CardHeader><CardTitle>{agentId ? "Editar agencia" : "Nueva agencia"}</CardTitle><CardDescription>La comisión se congela al confirmar la reserva. El proveedor debe estar vinculado al establecimiento.</CardDescription></CardHeader><CardContent><form onSubmit={saveAgent} className="space-y-3">
          <Input required maxLength={140} placeholder="Nombre de agencia" value={agentForm.agent_name} onChange={(event) => setAgentForm({ ...agentForm, agent_name: event.target.value })} />
          <div className="grid gap-3 sm:grid-cols-2"><select value={agentForm.agent_type} onChange={(event) => setAgentForm({ ...agentForm, agent_type: event.target.value })} className="h-9 rounded-md border border-border bg-white px-2 text-sm">{agentTypes.map((type) => <option key={type}>{type}</option>)}</select><Input required type="number" min="0" max="100" step="0.01" placeholder="Comisión %" value={agentForm.commission_pct} onChange={(event) => setAgentForm({ ...agentForm, commission_pct: event.target.value })} /></div>
          <select value={agentForm.supplier} onChange={(event) => setAgentForm({ ...agentForm, supplier: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Sin proveedor vinculado</option>{data.suppliers.map((row) => <option key={row.name} value={row.name}>{row.supplier_name}</option>)}</select>
          <Input maxLength={140} placeholder="Persona de contacto" value={agentForm.contact_name} onChange={(event) => setAgentForm({ ...agentForm, contact_name: event.target.value })} /><Input maxLength={140} placeholder="Teléfono" value={agentForm.contact_phone} onChange={(event) => setAgentForm({ ...agentForm, contact_phone: event.target.value })} /><Input type="email" maxLength={140} placeholder="Correo" value={agentForm.contact_email} onChange={(event) => setAgentForm({ ...agentForm, contact_email: event.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={agentForm.active} onChange={(event) => setAgentForm({ ...agentForm, active: event.target.checked })} /> Activa</label><div className="flex gap-2"><Button disabled={busy || !!agentId && agentForm.name !== agentId}>Guardar agencia</Button><Button type="button" variant="outline" onClick={() => setSearchParams({ section: "agencies" })}>Volver al directorio</Button></div>
        </form></CardContent></Card>}
        {section.id === "experience-form" && experienceId && !data.experiences.some((row) => row.name === experienceId) && <p role="alert" className="text-sm text-destructive">No se encontró la experiencia solicitada.</p>}
        {section.id === "experience-form" && (!experienceId || data.experiences.some((row) => row.name === experienceId)) && <Card><CardHeader><CardTitle>{experienceId ? "Editar experiencia" : "Nueva experiencia"}</CardTitle><CardDescription>El artículo ERPNext debe ser de venta, sin inventario y tener precio vigente en la lista del establecimiento.</CardDescription></CardHeader><CardContent><form onSubmit={saveExperience} className="space-y-3">
          <Input required maxLength={140} placeholder="Nombre de la experiencia" value={experienceForm.experience_name} onChange={(event) => setExperienceForm({ ...experienceForm, experience_name: event.target.value })} />
          <select value={experienceForm.experience_category} onChange={(event) => setExperienceForm({ ...experienceForm, experience_category: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{categories.map((category) => <option key={category}>{category}</option>)}</select>
          <Input maxLength={140} placeholder="Buscar artículo ERPNext" value={itemQuery} onChange={(event) => setItemQuery(event.target.value)} />
          {itemError && <p role="alert" className="text-sm text-destructive">{itemError}</p>}
          <select required value={experienceForm.item} onChange={(event) => setExperienceForm({ ...experienceForm, item: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Artículo de servicio</option>{experienceForm.item && !itemChoices.some((row) => row.name === experienceForm.item) && <option value={experienceForm.item}>{experienceForm.item}</option>}{itemChoices.map((row) => <option key={row.name} value={row.name}>{row.display_name || row.item_name} · {row.name}</option>)}</select>
          <Input maxLength={140} placeholder="Duración" value={experienceForm.duration} onChange={(event) => setExperienceForm({ ...experienceForm, duration: event.target.value })} /><Input maxLength={500} placeholder="Descripción" value={experienceForm.description} onChange={(event) => setExperienceForm({ ...experienceForm, description: event.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={experienceForm.show_on_booking_page} onChange={(event) => setExperienceForm({ ...experienceForm, show_on_booking_page: event.target.checked })} /> Mostrar en reservas</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={experienceForm.active} onChange={(event) => setExperienceForm({ ...experienceForm, active: event.target.checked })} /> Activa</label><div className="flex gap-2"><Button disabled={busy || !experienceForm.item || !!experienceId && experienceForm.name !== experienceId}>Guardar experiencia</Button><Button type="button" variant="outline" onClick={() => setSearchParams({ section: "experiences" })}>Volver al catálogo</Button></div>
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
      {section.id === "reserve" && canReserve && <div className="max-w-2xl">
        {section.id === "reserve" && canReserve && <Card><CardHeader><CardTitle>Reservar experiencia</CardTitle><CardDescription>Revise el precio vigente antes de asociarla a una reserva.</CardDescription></CardHeader><CardContent><form onSubmit={reserve} className="space-y-3">
          <select required value={booking} onChange={(event) => { setBooking(event.target.value); setOrderQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Reserva confirmada</option>{data.bookings.filter((row) => ["Confirmed", "Checked In"].includes(row.status)).map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>
          <select required value={experience} onChange={(event) => { setExperience(event.target.value); setOrderQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Experiencia activa</option>{data.experiences.filter((row) => row.active && row.item).map((row) => <option key={row.name} value={row.name}>{row.experience_name}</option>)}</select>
          <Input required type="number" min="1" max="1000" step="1" value={quantity} onChange={(event) => { setQuantity(event.target.value); setOrderQuote(null) }} />
          {orderQuote && <p className="rounded-lg bg-secondary p-3 text-sm">Importe aceptado: {orderQuote.currency} {orderQuote.line.total_amount || orderQuote.line.amount}</p>}
          <Button disabled={busy || !booking || !experience}>{orderQuote ? "Confirmar reserva" : "Revisar precio"}</Button>
        </form></CardContent></Card>}
      </div>}
      {section.id === "agency-contribution" && <div className="max-w-2xl"><Card><CardHeader><CardTitle>Aporte de agencias</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{data.contribution.map((row) => <p key={row.travel_agent}>{agentName(row.travel_agent)}: {row.bookings} reservas · alojamiento {data.currency} {row.accepted_lodging} · comisión estimada {data.currency} {row.estimated_commission}</p>)}{!data.contribution.length && <p className="text-muted-foreground">Sin reservas atribuidas.</p>}</CardContent></Card></div>}
      {["orders", "orders-confirm", "orders-deliver", "orders-cancel"].includes(section.id) && <Card>
        <CardHeader><CardTitle>{section.label}</CardTitle>
          <CardDescription>{section.id === "orders" ? "La entrega deja un cargo pendiente en la cuenta de estancia." : section.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {displayedOrders.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 text-sm">
            <span><strong>{experienceName(row.experience)}</strong> × {row.quantity} · {row.currency} {row.amount}
              <span className="block text-muted-foreground">{row.name} · reserva {row.booking} · {row.status}{row.charge && ` · cargo ${row.charge}`}</span>
            </span>
            {section.id !== "orders" && canService && <Button size="sm" variant="outline" onClick={() => {
              setSelectedOrder(row.name); setScheduledAt(row.scheduled_at?.replace(" ", "T").slice(0, 16) || "")
              setParticipants(String(row.participants || row.quantity)); setStay(row.stay || "")
              setFolio(row.folio || ""); setCancelReason("")
            }}>{section.id === "orders-confirm" ? "Programar" : section.id === "orders-deliver" ? "Entregar" : "Cancelar"}</Button>}
          </div>)}
          {!displayedOrders.length && <p className="text-sm text-muted-foreground">Sin órdenes para esta opción.</p>}
          {selected && section.id !== "orders" && <div className="space-y-3 rounded-lg border p-3 text-sm">
            <strong>{experienceName(selected.experience)} · {selected.name}</strong>
            {section.id === "orders-confirm" && selected.status === "Reserved" && <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1"><span>Fecha y hora</span><Input required type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>
              <label className="space-y-1"><span>Participantes</span><Input required type="number" min="1" max="1000" step="1" value={participants} onChange={(event) => setParticipants(event.target.value)} /></label>
            </div>}
            {section.id === "orders-deliver" && selected.status === "Confirmed" && <div className="grid gap-3 sm:grid-cols-2">
              <select value={stay} onChange={(event) => { setStay(event.target.value); setFolio("") }} className="h-9 rounded-md border border-border bg-white px-2">
                <option value="">Seleccione estancia</option>{stayOptions.map((row) => <option key={row.name} value={row.name}>{row.name} · habitación {row.room}</option>)}
              </select>
              <select value={folio} onChange={(event) => setFolio(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2">
                <option value="">Seleccione cuenta</option>{folioOptions.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name}</option>)}
              </select>
            </div>}
            {section.id === "orders-cancel" && <Input maxLength={500} placeholder="Motivo de cancelación" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} />}
            <div className="flex flex-wrap gap-2">
              {section.id === "orders-confirm" && selected.status === "Reserved" && <Button disabled={busy || !scheduledAt} onClick={() => void updateOrder("Confirmed")}>Confirmar horario</Button>}
              {section.id === "orders-deliver" && selected.status === "Confirmed" && <Button disabled={busy || !stay || !folio} onClick={() => void updateOrder("Delivered")}>Entregar y cargar a la cuenta</Button>}
              {section.id === "orders-cancel" && <Button disabled={busy || !cancelReason.trim()} variant="outline" onClick={() => void updateOrder("Cancelled")}>Cancelar orden</Button>}
              <Button variant="ghost" onClick={() => setSelectedOrder("")}>Cerrar</Button>
            </div>
          </div>}
        </CardContent>
      </Card>}
      {section.id === "commissions-settle" && canCommission && <Card><CardHeader><CardTitle>Liquidar comisión de agencia</CardTitle><CardDescription>Requiere alojamiento facturado, artículo y cuenta de gasto de comisión configurados. El pago se gestiona en ERPNext.</CardDescription></CardHeader><CardContent className="space-y-3">
        <select value={commissionBooking} onChange={(event) => { setCommissionBooking(event.target.value); setCommissionQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Reserva completada con agencia</option>{data.bookings.filter((row) => row.status === "Completed" && row.travel_agent && !row.agent_commission_invoice && !row.pms_agent_commission).map((row) => <option key={row.name} value={row.name}>{row.name} · {agentName(row.travel_agent)}</option>)}</select>
        {commissionQuote && <p className="rounded-lg bg-secondary p-3 text-sm">Base {commissionQuote.currency} {commissionQuote.base} × {commissionQuote.percent}% = {commissionQuote.currency} {commissionQuote.amount}<span className="block text-muted-foreground">Proveedor {commissionQuote.supplier} · artículo {commissionQuote.item} · gasto {commissionQuote.expense_account}</span></p>}
        <Button disabled={busy || !commissionBooking} onClick={() => void settleCommission()}>{commissionQuote ? "Contabilizar en ERPNext" : "Revisar comisión"}</Button>
      </CardContent></Card>}
      {section.id === "commissions-history" && canCommission && <Card><CardHeader><CardTitle>Historial de comisiones</CardTitle><CardDescription>Consulte las facturas de comisión registradas en ERPNext.</CardDescription></CardHeader><CardContent className="space-y-3">
        {data.bookings.filter((row) => row.agent_commission_invoice).map((row) => <p key={row.name} className="text-sm">{row.name} · <a className="text-primary underline" href={`/app/purchase-invoice/${encodeURIComponent(row.agent_commission_invoice!)}`}>Factura de comisión {row.agent_commission_invoice}</a></p>)}
        {!data.bookings.some((row) => row.agent_commission_invoice) && <p className="text-sm text-muted-foreground">Sin comisiones contabilizadas.</p>}
      </CardContent></Card>}
      {section.id === "orders" && canFinance && <p className="text-sm text-muted-foreground">Los cargos de cuentas de estancia se cobran desde <Link className="text-primary underline" to="/customer-credits?section=folios">Cobros y créditos ERPNext</Link>. Las ventas directas de experiencias se registran con factura de venta ERPNext.</p>}
    </>}
  </div>
}
