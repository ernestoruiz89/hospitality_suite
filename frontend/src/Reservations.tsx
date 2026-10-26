import { useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Dialog as DialogPrimitive } from "radix-ui"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { reservationSections } from "./ReservationSections"
import { Reception } from "./Reception"

type View = "current" | "history" | "draft"
type Booking = { name: string; status: string; guest: string | null;
  guest_label: string | null; customer: string | null;
  customer_label: string | null; starts_at_local: string | null;
  ends_at_local: string | null; channel: string | null;
  currency: string; amount: string; modified: string;
  modifiable: boolean; can_arrive: boolean; can_cancel: boolean }
type Page = { property: string; status: View; search: string;
  offset: number; page_length: number; has_more: boolean; rows: Booking[] }
type Detail = { booking: { name: string; property: string; status: string;
  channel: string | null; instructions: string | null; reason: string | null;
  rooms: { name: string; category: string; room: string | null;
    people: number; extra_beds: number }[] };
  summary: { guest_label: string; customer_label: string; mode_label: string;
    rooms: { number: number; category_label: string; room_label: string;
      people: number; extra_beds: number; stays: { name: string; status: string;
        guest_label: string; room_label: string }[] }[] };
  workflow: { modified: string; modifiable: boolean; can_arrive: boolean;
    can_cancel: boolean };
  draft?: { rooms: { category: string | null; room: string | null;
    people: number | null }[] } | null }

const dateLabel = (value: string | null) => value ? value.slice(0, 16).replace("T", " ") : "Por definir"
const statusLabel: Record<string, string> = { Hold: "Retenida", Confirmed: "Confirmada",
  "Checked In": "Con entradas", Draft: "Borrador", Completed: "Finalizada",
  Cancelled: "Cancelada", "No Show": "No presentación" }
const PAGE_LENGTH = 25
type Workflow = { booking: string; action: "edit" | "arrival" | "cancel" }

export function Reservations({ property, provider, canStay }: { property: Property;
  provider: "pms" | "erpnext"; canStay: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get("section")
  const section = reservationSections.find((item) => item.id === requested) || reservationSections[0]
  const view: View = section.id
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [detailName, setDetailName] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const holdRequest = useRef<{ booking: string; modified: string; key: string } | null>(null)

  useEffect(() => {
    if (!requested || requested === section.id) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section.id)
    setSearchParams(next, { replace: true })
  }, [requested, section.id, searchParams, setSearchParams])

  useEffect(() => {
    setOffset(0); setSearch(""); setSearchInput(""); setDetailName(""); setDetail(null)
  }, [view])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setDetail(null); setDetailName(""); setError(""); setLoading(true)
    call<Page>("reservation_page", { property_name: property.name, status: view,
      search, offset: String(offset), page_length: String(PAGE_LENGTH) }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.status !== view ||
            result.search !== search || result.offset !== offset || !Array.isArray(result.rows))
          throw new Error("La lista de reservas no coincide con la consulta solicitada.")
        setPage(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las reservas.")
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, view, search, offset, revision])

  useEffect(() => {
    if (!detailName) return
    const controller = new AbortController()
    setDetail(null); setDetailError("")
    call<Detail>("booking_detail", { name: detailName }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.booking.name !== detailName || result.booking.property !== property.name)
          throw new Error("La reserva no pertenece al establecimiento seleccionado.")
        setDetail(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setDetailError(issue instanceof Error ? issue.message : "No se pudo consultar la reserva.")
      })
    return () => controller.abort()
  }, [property.name, detailName])
  useEffect(() => {
    if (detail && detailName) document.getElementById("reservation-detail")?.scrollIntoView({
      behavior: "smooth", block: "start" })
  }, [detail, detailName])

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setOffset(0); setSearch(searchInput.trim()); setRevision((value) => value + 1)
  }
  const selected = page?.rows.find((row) => row.name === detailName)
  async function confirmHold(booking: string, modified: string) {
    if (busy) return
    if (holdRequest.current?.booking !== booking || holdRequest.current.modified !== modified)
      holdRequest.current = { booking, modified, key: crypto.randomUUID() }
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "booking_status", { booking, modified,
        status: "Confirmed" }, holdRequest.current.key)
      holdRequest.current = null
      setDetailName(""); setDetail(null)
      setRevision((value) => value + 1)
      setNotice(`Reserva ${booking} confirmada.`)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo confirmar la retención.")
    } finally { setBusy(false) }
  }
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div>
      <h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Retenciones, confirmadas, historial y borradores del establecimiento.</p>
    </div><div className="flex gap-2"><Button asChild><Link to="/reservations/draft/new">Nuevo borrador</Link></Button>
      <Button asChild variant="outline"><Link to="/reception?section=reservation">Reserva directa</Link></Button>
      <Button variant="outline" onClick={() => setRevision((value) => value + 1)}>Actualizar</Button></div></div>
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <Card><CardHeader><CardTitle>{view === "current" ? "Reservas vigentes" : view === "history" ? "Reservas históricas" : "Borradores por completar"}</CardTitle>
      <CardDescription>{view === "draft" ? "Un borrador no ocupa cupo ni fija precio. Al retomarlo, revise la tarifa antes de confirmar." :
        "La retención libera cupo al vencer; consulte disponibilidad antes de modificar una reserva."}</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={submit} className="flex max-w-xl gap-2"><Input maxLength={80} aria-label="Buscar reserva por número o canal"
          placeholder="Número o canal" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} />
          <Button>Buscar</Button></form>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {loading && <Skeleton className="h-52 rounded-lg" />}
        {page && <><div className="space-y-2">{page.rows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
          <div><strong>{row.name}</strong> · {statusLabel[row.status] || row.status}<p>{row.guest_label || "Huésped por definir"} · {row.customer_label || "Pagador por definir"}</p>
            <p className="text-xs text-muted-foreground">{dateLabel(row.starts_at_local)} → {dateLabel(row.ends_at_local)} · {row.channel || "Recepción"}
              {row.status !== "Draft" && <> · {row.currency} {row.amount}</>}</p></div>
          <div className="flex flex-wrap gap-2">
            {row.status === "Hold" && <Button type="button" size="sm" disabled={busy}
              onClick={() => void confirmHold(row.name, row.modified)}>Confirmar</Button>}
            {canStay && row.can_arrive && <Button size="sm" onClick={() => setWorkflow({ booking: row.name,
              action: "arrival" })}>Registrar entrada</Button>}
            {row.modifiable && <Button size="sm" variant="outline" onClick={() => setWorkflow({ booking: row.name,
              action: "edit" })}>Modificar</Button>}
            {row.can_cancel && <Button size="sm" variant="outline" onClick={() => setWorkflow({ booking: row.name,
              action: "cancel" })}>Cancelar</Button>}
            <Button type="button" size="sm" variant="outline" aria-expanded={detailName === row.name}
              onClick={() => setDetailName((current) => current === row.name ? "" : row.name)}>Detalle</Button>
            {row.status === "Draft" && <Button asChild size="sm"><Link to={`/reservations/draft/${encodeURIComponent(row.name)}`}>Retomar</Link></Button>}
            <a className="inline-flex h-8 items-center rounded-md border border-border px-3 text-sm hover:bg-secondary"
                href={`/printview?doctype=${encodeURIComponent("HS Booking")}&name=${encodeURIComponent(row.name)}&format=${encodeURIComponent("HS Confirmación de reserva")}`}
                target="_blank" rel="noopener noreferrer">Imprimir</a>
          </div>
        </div>)}{!page.rows.length && <p className="py-8 text-center text-sm text-muted-foreground">Sin reservas para estos filtros.</p>}</div>
          <div className="flex items-center justify-between text-sm"><span>Mostrando {page.rows.length ? page.offset + 1 : 0}–{page.offset + page.rows.length}</span>
            <div className="flex gap-2"><Button variant="outline" disabled={page.offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_LENGTH))}>Anterior</Button>
              <Button variant="outline" disabled={!page.has_more || loading} onClick={() => setOffset(offset + PAGE_LENGTH)}>Siguiente</Button></div></div>
        </>}
      </CardContent></Card>
    {detailName && <Card id="reservation-detail"><CardHeader><CardTitle>Detalle de {detailName}</CardTitle>
      <CardDescription>{selected?.status || detail?.booking.status}</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
      {detailError && <p role="alert" className="text-destructive">{detailError}</p>}
      {!detail && !detailError && <Skeleton className="h-32 rounded-lg" />}
      {detail && <><p>Canal: {detail.booking.channel || "Recepción"}</p>
        {detail.booking.instructions && <p>Solicitudes: {detail.booking.instructions}</p>}
        {detail.booking.reason && <p>Motivo registrado: {detail.booking.reason}</p>}
        <p>Huésped: {detail.summary.guest_label} · Pagador: {detail.summary.customer_label}</p>
        <p>Modalidad: {detail.summary.mode_label}</p>
        <div><strong>Habitaciones solicitadas</strong><ul className="mt-2 space-y-1">
          {(detail.booking.status === "Draft" ? (detail.draft?.rooms || []).map((line) => ({
            category: line.category || "Categoría por definir", room: line.room || "Por asignar",
            people: line.people || "Personas por definir", stays: [] as Detail["summary"]["rooms"][number]["stays"],
          })) : detail.summary.rooms.map((line) => ({ category: line.category_label,
            room: line.room_label, people: line.people, stays: line.stays }))).map((line, index) => <li key={index} className="rounded-md bg-muted p-2">
            {line.category} · {line.room} · {line.people} persona(s)
            {line.stays.map((stay) => <span className="block text-xs text-muted-foreground" key={stay.name}>
              Estancia {stay.name} · {stay.status} · {stay.guest_label}
            </span>)}
          </li>)}
          {!(detail.booking.status === "Draft" ? detail.draft?.rooms : detail.summary.rooms)?.length && <li>Aún no hay habitaciones seleccionadas.</li>}
        </ul></div>
        <div className="flex flex-wrap gap-2">
          {detail.booking.status === "Draft" && <Button asChild><Link to={`/reservations/draft/${encodeURIComponent(detailName)}`}>Retomar borrador</Link></Button>}
          {detail.booking.status === "Hold" && <Button disabled={busy} onClick={() => void confirmHold(detailName, detail.workflow.modified)}>Confirmar retención</Button>}
          {detail.workflow.modifiable && <Button variant="outline" onClick={() => setWorkflow({ booking: detailName,
            action: "edit" })}>Modificar</Button>}
          {canStay && detail.workflow.can_arrive && <Button variant="outline" onClick={() => setWorkflow({ booking: detailName,
            action: "arrival" })}>Registrar entrada</Button>}
          {detail.workflow.can_cancel && <Button variant="outline" onClick={() => setWorkflow({ booking: detailName,
            action: "cancel" })}>Cancelar / no presentación</Button>}
        </div>
      </>}
    </CardContent></Card>}
    {workflow && <DialogPrimitive.Root open onOpenChange={(open) => { if (!open) setWorkflow(null) }}>
      <DialogPrimitive.Portal><DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45" />
        <DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-background shadow-2xl outline-none sm:max-w-3xl"
          aria-describedby="reservation-workflow-description">
          <header className="flex items-start justify-between gap-3 border-b px-4 py-4 sm:px-6">
            <div><DialogPrimitive.Title className="text-xl font-semibold">{workflow.action === "edit" ? "Modificar" :
              workflow.action === "cancel" ? "Cancelar" : "Registrar entrada de"} reserva {workflow.booking}</DialogPrimitive.Title>
              <DialogPrimitive.Description id="reservation-workflow-description" className="text-sm text-muted-foreground">
                Revise los datos antes de confirmar la operación.
              </DialogPrimitive.Description></div>
            <DialogPrimitive.Close asChild><Button variant="ghost" size="icon" aria-label="Cerrar operación"><X size={18} /></Button></DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
            <Reception key={`${property.name}:${workflow.booking}:${workflow.action}`} property={property}
              provider={provider} canApprove={false} canSetup={false} canManageGuests={false}
              canStay={canStay} embeddedSection={workflow.action === "edit" ? "reservation" : "arrivals"}
              initialBooking={{ property: property.name, name: workflow.booking, action: workflow.action }}
              onChanged={() => setRevision((value) => value + 1)} />
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>}
  </div>
}
