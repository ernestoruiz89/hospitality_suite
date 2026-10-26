import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property, type RoomBoard } from "./api"
import { ticketSections } from "./TicketSections"

type View = "open" | "mine" | "unassigned" | "overdue" | "resolved" | "all"
type Status = "Open" | "In Progress" | "Resolved" | "Cancelled"
type Step = "start" | "resolve" | "assign" | "due" | "note" | "reopen" | "cancel"
type Ticket = { name: string; room: string | null; stay: string | null; subject: string;
  description?: string; category: string; priority: string; status: Status;
  assigned_to: string | null; due_at: string; modified: string;
  resolution?: string | null; resolved_at?: string | null }
type Board = { rows: Ticket[]; total: number; offset: number; has_more: boolean;
  assignees: { name: string; full_name: string }[]; now: string }
type Event = { kind: string; actor: string; occurred_at: string;
  note: string | null; before_value: string | null; after_value: string | null }
type Detail = { ticket: Ticket; events: Event[]; total_events: number;
  offset: number; has_older: boolean }

const views: { code: View; label: string }[] = [
  { code: "open", label: "Pendientes" }, { code: "mine", label: "Mis tickets" },
  { code: "unassigned", label: "Sin responsable" }, { code: "overdue", label: "Vencidos" },
  { code: "resolved", label: "Resueltos" }, { code: "all", label: "Todos" },
]
const categories = ["Guest Request", "Housekeeping", "Maintenance", "Complaint", "Other"]
const categoryLabels: Record<string, string> = { "Guest Request": "Solicitud", Housekeeping: "Limpieza",
  Maintenance: "Mantenimiento", Complaint: "Queja", Other: "Otro" }
const eventLabels: Record<string, string> = { Created: "Creado", Assigned: "Asignado",
  Started: "Iniciado", Resolved: "Resuelto", Reopened: "Reabierto",
  Cancelled: "Cancelado", Note: "Nota", "Due Changed": "Plazo cambiado" }
const stepLabels: Record<Step, string> = { start: "Iniciar", resolve: "Resolver",
  assign: "Asignar", due: "Cambiar plazo", note: "Agregar nota",
  reopen: "Reabrir", cancel: "Cancelar" }
const PAGE_SIZE = 40
const HISTORY_SIZE = 100
const stamp = (value?: string | null) => value ? value.replace("T", " ").slice(0, 16) : "—"
const issueText = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo completar la operación."

export function Tickets({ property, canInspect }: { property: Property; canInspect: boolean }) {
  const [params, setParams] = useSearchParams()
  const requestedRoom = params.get("room") || ""
  const requestedSection = params.get("section")
  const section = ticketSections.find((item) => item.id === requestedSection) ||
    (requestedRoom ? ticketSections[1] : ticketSections[0])
  const [view, setView] = useState<View>("open")
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [board, setBoard] = useState<Board | null>(null)
  const [rooms, setRooms] = useState<RoomBoard["rooms"]>([])
  const [detail, setDetail] = useState<Detail | null>(null)
  const [step, setStep] = useState<Step | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [room, setRoom] = useState(requestedRoom)
  const [subject, setSubject] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("Guest Request")
  const [priority, setPriority] = useState("Normal")
  const [assignee, setAssignee] = useState("")
  const [due, setDue] = useState("")
  const [note, setNote] = useState("")
  const detailRequest = useRef(0)

  useEffect(() => {
    if (requestedSection === section.id || !requestedSection && !requestedRoom) return
    const next = new URLSearchParams(params)
    next.set("section", section.id)
    setParams(next, { replace: true })
  }, [requestedSection, requestedRoom, section.id, params, setParams])

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const result = await call<Board>("ticket_board", {
      property_name: property.name, view, offset: String(offset), page_length: String(PAGE_SIZE),
    }, signal)
    if (!signal?.aborted) setBoard(result)
  }, [property.name, view, offset])

  useEffect(() => {
    const controller = new AbortController()
    detailRequest.current += 1
    setBoard(null); setDetail(null); setStep(null); setError("")
    refresh(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issueText(issue))
    })
    return () => controller.abort()
  }, [refresh, revision])

  useEffect(() => {
    const controller = new AbortController()
    setRooms([]); setRoom(requestedRoom)
    call<RoomBoard>("room_board_snapshot", { property_name: property.name }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setRooms(result.rooms) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(issueText(issue)) })
    return () => controller.abort()
  }, [property.name, requestedRoom])

  async function showDetail(name: string, historyOffset = 0) {
    const request = ++detailRequest.current
    setError("")
    try {
      const result = await call<Detail>("ticket_detail", { name,
        offset: String(historyOffset), page_length: String(HISTORY_SIZE) })
      if (request === detailRequest.current && result.ticket.name === name) setDetail(result)
    } catch (issue) { if (request === detailRequest.current) setError(issueText(issue)) }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "ticket", { kind: "create", room: room || null,
        subject: subject.trim(), description: description.trim(), category, priority,
        assigned_to: assignee || null, ...(due ? { due_at: due } : {}) }, crypto.randomUUID())
      setSubject(""); setDescription(""); setDue(""); setAssignee("")
      setView("open"); setOffset(0); setRevision((value) => value + 1)
      setParams({ section: "board" }); setNotice("Ticket creado.")
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }

  async function applyStep(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!detail || !step || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const data: Record<string, string> = { kind: step, ticket: detail.ticket.name,
        modified: detail.ticket.modified }
      if (step === "assign") data.assigned_to = assignee
      if (step === "due") { data.due_at = due; data.note = note.trim() }
      if (["note", "reopen", "cancel"].includes(step)) data.note = note.trim()
      if (step === "resolve") data.resolution = note.trim()
      await execute(property.name, "ticket", data, crypto.randomUUID())
      await Promise.all([refresh(), showDetail(detail.ticket.name)])
      setStep(null); setNote(""); setDue(""); setAssignee("")
      setNotice(`Ticket actualizado: ${stepLabels[step].toLowerCase()}.`)
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }

  const roomLabel = (name: string | null) => rooms.find((item) => item.name === name)?.room_number || name || "—"
  const current = detail?.ticket
  const open = (status: Status) => status === "Open" || status === "In Progress"
  const availableSteps = (ticket: Ticket): Step[] => [
    ...(ticket.status === "Open" ? ["start" as const] : []),
    ...(open(ticket.status) ? ["resolve" as const, "note" as const] : []),
    ...(open(ticket.status) && canInspect ? ["assign" as const, "due" as const, "cancel" as const] : []),
    ...(ticket.status === "Resolved" && canInspect ? ["reopen" as const] : []),
  ]

  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-3"><div>
      <h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">Solicitudes, responsable, plazo e historial por establecimiento.</p>
    </div><Button asChild variant="outline"><Link to={section.id === "new" ? "/tickets?section=board" : "/tickets?section=new"}>
      {section.id === "new" ? "Ver seguimiento" : "Crear ticket"}</Link></Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {section.id === "new" && <Card><CardHeader><CardTitle>Nuevo ticket</CardTitle><CardDescription>El plazo predeterminado depende de la prioridad. Horario de {property.time_zone}.</CardDescription></CardHeader><CardContent>
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm"><span>Habitación (opcional)</span><select value={room} onChange={(event) => setRoom(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin habitación</option>{rooms.map((item) => <option key={item.name} value={item.name}>{item.room_number}</option>)}</select></label>
        <label className="space-y-1 text-sm"><span>Asunto</span><Input required maxLength={140} value={subject} onChange={(event) => setSubject(event.target.value)} /></label>
        <label className="space-y-1 text-sm sm:col-span-2"><span>Descripción</span><textarea required maxLength={2000} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} className="w-full rounded-md border border-border bg-white p-2" /></label>
        <label className="space-y-1 text-sm"><span>Categoría</span><select value={category} onChange={(event) => setCategory(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">{categories.map((item) => <option key={item} value={item}>{categoryLabels[item]}</option>)}</select></label>
        <label className="space-y-1 text-sm"><span>Prioridad</span><select value={priority} onChange={(event) => setPriority(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="Normal">Normal</option><option value="High">Alta</option><option value="Urgent">Urgente</option></select></label>
        <label className="space-y-1 text-sm"><span>Responsable (opcional)</span><select value={assignee} onChange={(event) => setAssignee(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin asignar</option>{board?.assignees.map((item) => <option key={item.name} value={item.name}>{item.full_name || item.name}</option>)}</select></label>
        <label className="space-y-1 text-sm"><span>Plazo específico (opcional)</span><Input type="datetime-local" value={due} onChange={(event) => setDue(event.target.value)} /></label>
        <Button disabled={busy} className="sm:col-span-2">Crear ticket</Button>
      </form>
    </CardContent></Card>}
    {section.id === "board" && <Card><CardHeader><CardTitle>Seguimiento</CardTitle><CardDescription>Seleccione una vista para revisar los tickets de este establecimiento.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div className="flex flex-wrap gap-2">{views.map((item) => <Button key={item.code} size="sm" variant={view === item.code ? "default" : "outline"} onClick={() => { setView(item.code); setOffset(0) }}>{item.label}</Button>)}</div>
      {!board ? <Skeleton className="h-40" /> : <>
        <p className="text-sm text-muted-foreground">{board.total} tickets · mostrando {board.total ? offset + 1 : 0}–{offset + board.rows.length}</p>
        <div className="space-y-3">{board.rows.map((ticket) => <div key={ticket.name} className="rounded-lg border border-border p-4 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{ticket.subject}</strong><p className="mt-1 text-muted-foreground">{categoryLabels[ticket.category] || ticket.category} · Habitación {roomLabel(ticket.room)}</p></div><div className="flex gap-1"><Badge variant={ticket.priority === "Urgent" ? "destructive" : "secondary"}>{ticket.priority === "High" ? "Alta" : ticket.priority === "Urgent" ? "Urgente" : "Normal"}</Badge><Badge variant="outline">{ticket.status}</Badge></div></div>
          <p className="mt-2 text-muted-foreground">Responsable: {board.assignees.find((item) => item.name === ticket.assigned_to)?.full_name || ticket.assigned_to || "Sin responsable"} · Plazo: {stamp(ticket.due_at)}{open(ticket.status) && ticket.due_at < board.now ? " · Vencido" : ""}</p>
          <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => { setDetail(null); setStep(null); void showDetail(ticket.name) }}>Ver historial</Button>{ticket.room && <Button asChild size="sm" variant="outline"><Link to={`/rooms/${encodeURIComponent(ticket.room)}`}>Ver habitación</Link></Button>}{availableSteps(ticket).map((kind) => <Button key={kind} size="sm" variant="outline" onClick={() => { setDetail(null); setStep(kind); setNote(""); setDue(""); setAssignee(""); void showDetail(ticket.name) }}>{stepLabels[kind]}</Button>)}</div>
        </div>)}{!board.rows.length && <p className="py-5 text-center text-sm text-muted-foreground">No hay tickets en esta vista.</p>}</div>
        <div className="flex justify-end gap-2"><Button variant="outline" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button><Button variant="outline" disabled={!board.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</Button></div>
      </>}
    </CardContent></Card>}
    {section.id === "board" && current && <Card><CardHeader><CardTitle>{current.subject}</CardTitle><CardDescription>{categoryLabels[current.category] || current.category} · {current.status} · Habitación {roomLabel(current.room)}</CardDescription></CardHeader><CardContent className="space-y-4 text-sm">
      <p>{current.description}</p><p className="text-muted-foreground">Responsable: {current.assigned_to || "Sin responsable"} · Plazo: {stamp(current.due_at)}</p>
      {current.resolution && <p><strong>Resolución:</strong> {current.resolution}</p>}
      {step && <form onSubmit={applyStep} className="space-y-3 rounded-lg border border-border p-3"><strong>{stepLabels[step]}</strong>
        {step === "assign" && <label className="block space-y-1"><span>Nuevo responsable</span><select required value={assignee} onChange={(event) => setAssignee(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione</option>{board?.assignees.filter((item) => item.name !== current.assigned_to).map((item) => <option key={item.name} value={item.name}>{item.full_name || item.name}</option>)}</select></label>}
        {step === "due" && <label className="block space-y-1"><span>Nuevo plazo · {property.time_zone}</span><Input required type="datetime-local" value={due} onChange={(event) => setDue(event.target.value)} /></label>}
        {["resolve", "due", "note", "reopen", "cancel"].includes(step) && <label className="block space-y-1"><span>{step === "resolve" ? "Resolución" : "Motivo o nota"}</span><textarea required maxLength={2000} rows={2} value={note} onChange={(event) => setNote(event.target.value)} className="w-full rounded-md border border-border bg-white p-2" /></label>}
        <div className="flex gap-2"><Button disabled={busy}>Confirmar</Button><Button type="button" variant="outline" onClick={() => setStep(null)}>Cerrar</Button></div>
      </form>}
      <div><strong>Historial</strong><p className="text-muted-foreground">Eventos {detail.total_events ? detail.offset + 1 : 0}–{detail.offset + detail.events.length} de {detail.total_events}</p></div>
      <div className="space-y-2">{detail.events.map((event, index) => <div key={`${event.occurred_at}-${index}`} className="rounded-md border border-border p-3"><strong>{eventLabels[event.kind] || event.kind}</strong> · {stamp(event.occurred_at)} · {event.actor}{event.note && <p className="mt-1">{event.note}</p>}{(event.before_value || event.after_value) && <p className="text-muted-foreground">{event.before_value || "—"} → {event.after_value || "—"}</p>}</div>)}</div>
      <div className="flex gap-2"><Button variant="outline" disabled={!detail.offset} onClick={() => void showDetail(current.name, Math.max(0, detail.offset - HISTORY_SIZE))}>Más recientes</Button><Button variant="outline" disabled={!detail.has_older} onClick={() => void showDetail(current.name, detail.offset + HISTORY_SIZE)}>Más antiguos</Button></div>
    </CardContent></Card>}
  </div>
}
