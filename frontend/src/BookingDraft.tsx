import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, call, execute, type Property } from "./api"

type Options = { property: string;
  parties: { name: string; party_name: string }[];
  guests: { name: string; full_name: string; customer: string | null }[];
  categories: { name: string; category_name: string; capacity: number; max_extra_beds: number }[];
  rooms: { name: string; room_number: string; category: string }[];
  rates: { name: string; title: string; category: string; mode: string;
    day_pass: boolean; currency: string; amount: number }[];
  agents: { name: string; agent_name: string }[];
  experiences: { name: string; experience_name: string }[] }
type RoomLine = { id: string; category: string; room: string; rate: string;
  people: string; extra_beds: string }
type ExperienceLine = { id: string; experience: string; quantity: string }
type DraftValues = { mode: string; hold: boolean; guest: string | null;
  customer: string | null; starts_at: string | null; ends_at: string | null;
  channel: string; instructions: string | null; travel_agent: string | null;
  rooms: { category: string | null; room: string | null; rate: string | null;
    people: number | null; extra_beds: number | null }[];
  experiences: { experience: string | null; quantity: number | null }[] }
type Saved = { booking: string; status: string; modified: string }
type Detail = { booking: { name: string; property: string; status: string; modified: string };
  draft: { mode: string; hold: boolean; guest: string | null; customer: string | null;
    starts_at: string | null; ends_at: string | null; channel: string | null;
    instructions: string | null; travel_agent: string | null;
    rooms: { category: string | null; room: string | null; rate: string | null;
      people: number | null; extra_beds: number | null }[];
    experiences: { experience: string | null; quantity: number | null }[] } | null }
type Quote = { amount: string; estimated_total: string; currency: string;
  lines: { amount: string; explanation: string[] }[];
  experiences: { name: string; quantity: number; amount: string }[];
  draft_acceptance: string; values: DraftValues; key: string; modified: string }
type PendingSave = { data: { booking?: string; modified?: string; values: DraftValues };
  key: string; fingerprint: string }

const freshRoom = (): RoomLine => ({ id: crypto.randomUUID(), category: "", room: "",
  rate: "", people: "1", extra_beds: "0" })
const wall = (value: string | null) => value ? value.slice(0, 16) : ""
const originalDate = (value: string, saved: string | null) =>
  value ? saved && wall(saved) === value ? saved : value : null

export function BookingDraft({ property, provider }: { property: Property; provider: "pms" | "erpnext" }) {
  const { booking = "new" } = useParams()
  const navigate = useNavigate()
  const [options, setOptions] = useState<Options | null>(null)
  const [session, setSession] = useState<Saved | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [guest, setGuest] = useState("")
  const [payer, setPayer] = useState("")
  const [mode, setMode] = useState(property.mode === "Mixed" ? "Hotel" : property.mode)
  const [startsAt, setStartsAt] = useState("")
  const [endsAt, setEndsAt] = useState("")
  const [channel, setChannel] = useState("Recepción")
  const [instructions, setInstructions] = useState("")
  const [agent, setAgent] = useState("")
  const [hold, setHold] = useState(false)
  const [rooms, setRooms] = useState<RoomLine[]>([freshRoom()])
  const [experiences, setExperiences] = useState<ExperienceLine[]>([])
  const [quote, setQuote] = useState<Quote | null>(null)
  const [discardReason, setDiscardReason] = useState("")
  const pendingSave = useRef<PendingSave | null>(null)
  const pendingDiscard = useRef<{ key: string; reason: string } | null>(null)
  const savedDates = useRef<{ starts_at: string | null; ends_at: string | null }>({ starts_at: null, ends_at: null })

  useEffect(() => {
    const controller = new AbortController()
    setOptions(null); setSession(null); setError(""); setNotice(""); setQuote(null)
    pendingSave.current = null; pendingDiscard.current = null
    const requests: [Promise<Options>, Promise<Detail | null>] = [
      call<Options>(provider === "pms" ? "pms_reception_snapshot" : "erp_reception_snapshot",
        { property_name: property.name }, controller.signal),
      booking === "new" ? Promise.resolve(null) :
        call<Detail>("booking_detail", { name: booking }, controller.signal),
    ]
    Promise.all(requests).then(([pickers, detail]) => {
      if (controller.signal.aborted) return
      if (pickers.property !== property.name || detail &&
          (detail.booking.property !== property.name || detail.booking.status !== "Draft" || !detail.draft))
        throw new Error("El borrador no pertenece a este establecimiento o ya fue confirmado.")
      setOptions(pickers)
      if (detail?.draft) {
        const values = detail.draft
        setSession({ booking: detail.booking.name, modified: detail.booking.modified, status: "Draft" })
        setGuest(values.guest || ""); setPayer(values.customer || "")
        setMode(values.mode); setHold(Boolean(values.hold))
        setStartsAt(wall(values.starts_at)); setEndsAt(wall(values.ends_at))
        setChannel(values.channel || "Recepción"); setInstructions(values.instructions || "")
        setAgent(values.travel_agent || "")
        setRooms(values.rooms.length ? values.rooms.map((row) => ({ id: crypto.randomUUID(),
          category: row.category || "", room: row.room || "", rate: row.rate || "",
          people: row.people == null ? "" : String(row.people),
          extra_beds: row.extra_beds == null ? "" : String(row.extra_beds) })) : [freshRoom()])
        setExperiences(values.experiences.map((row) => ({ id: crypto.randomUUID(),
          experience: row.experience || "", quantity: row.quantity == null ? "" : String(row.quantity) })))
        savedDates.current = { starts_at: values.starts_at, ends_at: values.ends_at }
      }
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo abrir el borrador.")
    })
    return () => controller.abort()
  }, [booking, property.name, provider])

  const changeRoom = (id: string, patch: Partial<RoomLine>) => {
    setRooms((current) => current.map((row) => row.id === id ? { ...row, ...patch } : row))
    setQuote(null)
  }
  const values = (): DraftValues => ({ mode, hold, guest: guest || null,
    customer: payer || null,
    starts_at: originalDate(startsAt, savedDates.current.starts_at),
    ends_at: originalDate(endsAt, savedDates.current.ends_at),
    channel: channel.trim() || "Recepción", instructions: instructions.trim() || null,
    travel_agent: agent || null,
    rooms: rooms.map((row) => ({ category: row.category || null,
      room: row.room || null, rate: row.rate || null,
      people: row.people === "" ? null : Number(row.people),
      extra_beds: row.extra_beds === "" ? null : Number(row.extra_beds) })),
    experiences: experiences.map((row) => ({ experience: row.experience || null,
      quantity: row.quantity === "" ? null : Number(row.quantity) })),
  })

  const save = async () => {
    if (busy) return
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const currentValues = values()
      const fingerprint = JSON.stringify(currentValues)
      let current = session
      if (pendingSave.current) {
        const pending = pendingSave.current
        const settled = await execute<Saved>(property.name, "save_booking_draft",
          pending.data, pending.key)
        current = settled; setSession(settled); pendingSave.current = null
        if (pending.fingerprint === fingerprint) {
          setNotice(`Borrador ${settled.booking} guardado. No ocupa cupo ni fija precio.`)
          if (booking === "new") navigate(`/reservations/draft/${encodeURIComponent(settled.booking)}`, { replace: true })
          return
        }
      }
      const data = { ...(current ? { booking: current.booking, modified: current.modified } : {}),
        values: currentValues }
      const pending = { data, fingerprint, key: crypto.randomUUID() }
      pendingSave.current = pending
      const saved = await execute<Saved>(property.name, "save_booking_draft", data, pending.key)
      pendingSave.current = null; setSession(saved)
      setNotice(`Borrador ${saved.booking} guardado. No ocupa cupo ni fija precio.`)
      if (booking === "new") navigate(`/reservations/draft/${encodeURIComponent(saved.booking)}`, { replace: true })
    } catch (issue) {
      if (issue instanceof ApiError && [400, 403, 409, 417].includes(issue.status)) pendingSave.current = null
      setError(issue instanceof Error ? issue.message : "No se pudo guardar el borrador.")
    } finally { setBusy(false) }
  }

  const review = async () => {
    if (busy || !session) return
    if (pendingSave.current) { setError("Reintente guardar el borrador antes de revisar la tarifa."); return }
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const frozen = values()
      const result = await call<Omit<Quote, "values" | "key" | "modified">>("preview", {
        property_name: property.name, action: "confirm_booking_draft",
        data: JSON.stringify({ booking: session.booking, modified: session.modified, values: frozen }) })
      if (result.draft_acceptance) setQuote({ ...result, values: frozen,
        key: crypto.randomUUID(), modified: session.modified })
      else throw new Error("El servidor no devolvió la aceptación del borrador.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la tarifa.") }
    finally { setBusy(false) }
  }

  const confirm = async () => {
    if (!quote || !session || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<Saved>(property.name, "confirm_booking_draft",
        { booking: session.booking, modified: quote.modified, values: quote.values,
          draft_acceptance: quote.draft_acceptance }, quote.key)
      navigate("/reservations?section=current", { replace: true, state: { confirmed: result.booking } })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo confirmar el borrador.") }
    finally { setBusy(false) }
  }

  const discard = async () => {
    if (!session || !discardReason.trim() || busy) return
    setBusy(true); setError("")
    try {
      const reason = discardReason.trim()
      if (!pendingDiscard.current) pendingDiscard.current = { key: crypto.randomUUID(), reason }
      await execute(property.name, "discard_booking_draft", { booking: session.booking,
        modified: session.modified, reason: pendingDiscard.current.reason }, pendingDiscard.current.key)
      pendingDiscard.current = null
      navigate("/reservations?section=draft", { replace: true })
    } catch (issue) {
      if (issue instanceof ApiError && [400, 403, 409, 417].includes(issue.status)) pendingDiscard.current = null
      setError(issue instanceof Error ? issue.message : "No se pudo descartar el borrador.")
    } finally { setBusy(false) }
  }

  if (!options && !error) return <Skeleton className="h-96 rounded-xl" />
  return <div className="space-y-6">
    <Link to="/reservations?section=draft" className="text-sm font-medium text-primary underline">← Borradores</Link>
    <div><h1 className="text-3xl font-semibold">{session ? `Borrador ${session.booking}` : "Nuevo borrador"}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Guarde datos incompletos y confirme solo después de revisar precio y disponibilidad. El borrador no retiene habitaciones.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {options && <Card><CardHeader><CardTitle>Datos de la reserva</CardTitle><CardDescription>Las fechas usan la zona {property.time_zone}.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Huésped principal</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={guest}
          onChange={(event) => { const selected = event.target.value; setGuest(selected);
            if (selected) setPayer(options.guests.find((row) => row.name === selected)?.customer || ""); setQuote(null) }}>
          <option value="">Por definir</option>{options.guests.map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}
        </select></label><label className="space-y-1 text-sm"><span>Pagador</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={payer}
          onChange={(event) => { setPayer(event.target.value); setQuote(null) }}><option value="">Por definir</option>
          {options.parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label></div>
        <div className="grid gap-3 sm:grid-cols-3"><label className="space-y-1 text-sm"><span>Modalidad</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={mode}
          onChange={(event) => { setMode(event.target.value); setQuote(null) }}>
          {(property.mode === "Mixed" ? ["Hotel", "Por tiempo", "Day Pass"] :
            property.mode === "Por tiempo" ? ["Por tiempo", "Day Pass"] : ["Hotel"]).map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label><label className="space-y-1 text-sm"><span>Entrada prevista</span><Input type="datetime-local" value={startsAt}
          onChange={(event) => { setStartsAt(event.target.value); setQuote(null) }} /></label>
          <label className="space-y-1 text-sm"><span>Salida prevista</span><Input type="datetime-local" value={endsAt}
            onChange={(event) => { setEndsAt(event.target.value); setQuote(null) }} /></label></div>
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Canal</span><Input maxLength={140} value={channel}
          onChange={(event) => { setChannel(event.target.value); setQuote(null) }} /></label>
          <label className="space-y-1 text-sm"><span>Agencia de viajes</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={agent}
            onChange={(event) => { setAgent(event.target.value); setQuote(null) }}><option value="">Reserva directa</option>
            {options.agents.map((row) => <option key={row.name} value={row.name}>{row.agent_name}</option>)}</select></label></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={hold} onChange={(event) => { setHold(event.target.checked); setQuote(null) }} />Retener cupo temporalmente al confirmar</label>
        <label className="block space-y-1 text-sm"><span>Solicitudes especiales</span><textarea className="min-h-20 w-full rounded-md border border-border bg-white p-2" maxLength={1000}
          value={instructions} onChange={(event) => { setInstructions(event.target.value); setQuote(null) }} /></label>
        <div className="space-y-3"><strong className="text-sm">Habitaciones solicitadas</strong>
          {rooms.map((row, index) => <div key={row.id} className="rounded-md border border-border p-3"><div className="mb-2 flex justify-between"><strong className="text-sm">Habitación {index + 1}</strong>
            <Button type="button" size="sm" variant="outline" onClick={() => { setRooms((current) => current.filter((item) => item.id !== row.id)); setQuote(null) }}>Quitar</Button></div>
            <div className="grid gap-2 sm:grid-cols-5"><label className="space-y-1 text-sm"><span>Categoría</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={row.category}
              onChange={(event) => changeRoom(row.id, { category: event.target.value, room: "", rate: "" })}><option value="">Por definir</option>
              {options.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Habitación</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={row.room}
                onChange={(event) => changeRoom(row.id, { room: event.target.value })}><option value="">Por asignar</option>
                {options.rooms.filter((item) => item.category === row.category).map((item) => <option key={item.name} value={item.name}>{item.room_number}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Personas</span><Input type="number" min="1" max={options.categories.find((item) => item.name === row.category)?.capacity || 20} value={row.people}
                onChange={(event) => changeRoom(row.id, { people: event.target.value })} /></label>
              <label className="space-y-1 text-sm"><span>Camas extra</span><Input type="number" min="0" max={options.categories.find((item) => item.name === row.category)?.max_extra_beds || 0} value={row.extra_beds}
                onChange={(event) => changeRoom(row.id, { extra_beds: event.target.value })} /></label>
              <label className="space-y-1 text-sm"><span>Tarifa</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={row.rate}
                onChange={(event) => changeRoom(row.id, { rate: event.target.value })}><option value="">Automática</option>
                {options.rates.filter((item) => item.category === row.category &&
                  item.mode === (mode === "Day Pass" ? "Por tiempo" : mode) && Boolean(item.day_pass) === (mode === "Day Pass"))
                  .map((item) => <option key={item.name} value={item.name}>{item.title} · {item.currency} {item.amount}</option>)}</select></label></div></div>)}
          <Button type="button" variant="outline" disabled={rooms.length >= 20} onClick={() => { setRooms((current) => [...current, freshRoom()]); setQuote(null) }}>Añadir habitación</Button>
        </div>
        <div className="space-y-2"><strong className="text-sm">Experiencias adicionales</strong>
          {experiences.map((row) => <div key={row.id} className="flex flex-wrap items-end gap-2"><label className="min-w-48 flex-1 space-y-1 text-sm"><span>Experiencia</span><select className="block h-9 w-full rounded-md border border-border bg-white px-2" value={row.experience}
            onChange={(event) => { setExperiences((current) => current.map((item) => item.id === row.id ? { ...item, experience: event.target.value } : item)); setQuote(null) }}><option value="">Por definir</option>
            {options.experiences.map((item) => <option key={item.name} value={item.name}>{item.experience_name}</option>)}</select></label>
            <label className="w-28 space-y-1 text-sm"><span>Cantidad</span><Input type="number" min="1" value={row.quantity}
              onChange={(event) => { setExperiences((current) => current.map((item) => item.id === row.id ? { ...item, quantity: event.target.value } : item)); setQuote(null) }} /></label>
            <Button type="button" variant="outline" onClick={() => { setExperiences((current) => current.filter((item) => item.id !== row.id)); setQuote(null) }}>Quitar</Button></div>)}
          <Button type="button" variant="outline" disabled={experiences.length >= 20} onClick={() => { setExperiences((current) => [...current,
            { id: crypto.randomUUID(), experience: "", quantity: "1" }]); setQuote(null) }}>Añadir experiencia</Button></div>
        <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void save()}>Guardar borrador</Button>
          {session && <Button variant="outline" disabled={busy} onClick={() => void review()}>Revisar precio y disponibilidad</Button>}</div>
        {quote && <div className="space-y-2 rounded-md border border-border bg-secondary p-3 text-sm"><p><strong>Alojamiento:</strong> {quote.currency} {quote.amount}</p>
          <p><strong>Total estimado:</strong> {quote.currency} {quote.estimated_total}</p>
          {quote.lines.map((line, index) => <p key={index}>Habitación {index + 1}: {quote.currency} {line.amount} · {line.explanation.join(" · ")}</p>)}
          {quote.experiences.map((row, index) => <p key={index}>{row.name} × {row.quantity}: {quote.currency} {row.amount}</p>)}
          <p>{quote.values.hold ? "Al aceptar se retendrá el cupo temporalmente." : "Al aceptar se confirmará la reserva."}</p>
          <Button disabled={busy} onClick={() => void confirm()}>{quote.values.hold ? "Aceptar retención" : "Confirmar reserva"}</Button></div>}
        {session && <div className="flex flex-wrap items-end gap-2 border-t border-border pt-4"><label className="min-w-56 flex-1 space-y-1 text-sm"><span>Motivo para descartar</span><Input maxLength={500} value={discardReason}
          onChange={(event) => setDiscardReason(event.target.value)} /></label><Button variant="destructive" disabled={busy || !discardReason.trim()} onClick={() => void discard()}>Descartar borrador</Button></div>}
      </CardContent></Card>}
  </div>
}
