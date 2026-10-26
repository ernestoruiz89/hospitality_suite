import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"

type Options = { property: string; time_zone: string; mode: string; local_now: string }
type Room = { name: string; room_number: string; category: string;
  active: boolean; cleaning_status: string }
type Allocation = { name: string; room: string | null; kind: string;
  status: string; starts_at: string; ends_at: string;
  booking: string | null; stay: string | null;
  block_reason?: string | null }
type Calendar = { property: string; from_date: string; view: "day" | "week";
  time_zone: string; window_start: string; window_end: string;
  ticks: { at: string; label: string }[]; rooms: Room[];
  allocations: Allocation[]; read_only: boolean }

const kindLabel: Record<string, string> = {
  Reservation: "Reserva", Stay: "Estancia", Maintenance: "Mantenimiento",
  "Room Block": "Bloqueo",
}
const kindTone: Record<string, string> = {
  Reservation: "bg-violet-200 text-violet-950 border-violet-400",
  Stay: "bg-blue-200 text-blue-950 border-blue-400",
  Maintenance: "bg-amber-200 text-amber-950 border-amber-400",
  "Room Block": "bg-rose-200 text-rose-950 border-rose-400",
}
const dateLabel = (value: string) => value.slice(8, 10) + "/" + value.slice(5, 7)
const localLabel = (value: string) => value.slice(0, 16).replace("T", " ")

export function RoomCalendar({ property }: { property: Property }) {
  const [options, setOptions] = useState<Options | null>(null)
  const [fromDate, setFromDate] = useState("")
  const [view, setView] = useState<"day" | "week">("week")
  const [revision, setRevision] = useState(0)
  const [calendar, setCalendar] = useState<Calendar | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setOptions(null); setCalendar(null); setError("")
    call<Options>("availability_options", { property_name: property.name }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setOptions(data)
        setFromDate(data.local_now.slice(0, 10))
        setView(data.mode === "Por tiempo" ? "day" : "week")
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el establecimiento.")
      })
    return () => controller.abort()
  }, [property.name])

  useEffect(() => {
    if (!options) return
    if (!fromDate) {
      setCalendar(null)
      setError("Seleccione una fecha para consultar el calendario.")
      return
    }
    const controller = new AbortController()
    setLoading(true); setCalendar(null); setError("")
    call<Calendar>("room_calendar", { property_name: property.name,
      from_date: fromDate, view }, controller.signal).then((data) => {
      if (controller.signal.aborted) return
      const first = Date.parse(data.window_start), last = Date.parse(data.window_end)
      if (data.property !== property.name || data.from_date !== fromDate ||
          data.view !== view || !data.read_only ||
          !Number.isFinite(first) || !Number.isFinite(last) || last <= first)
        throw new Error("El calendario no coincide con la consulta solicitada.")
      setCalendar(data)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo cargar el calendario.")
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [options, property.name, fromDate, view, revision])

  const rows = useMemo(() => {
    if (!calendar) return []
    const rooms = [...calendar.rooms].sort((a, b) =>
      a.room_number.localeCompare(b.room_number, "es", { numeric: true }))
    return [...rooms, { name: "", room_number: "Por asignar",
      category: "", active: true, cleaning_status: "" }]
      .map((room) => ({ room, allocations: calendar.allocations
        .filter((item) => (item.room || "") === room.name)
        .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at)) }))
      .filter(({ room, allocations }) => room.name || allocations.length)
  }, [calendar])
  const first = calendar ? Date.parse(calendar.window_start) : 0
  const span = calendar ? Date.parse(calendar.window_end) - first : 1
  const position = (value: string) => Math.max(0, Math.min(100,
    (Date.parse(value) - first) / span * 100))
  const detail = (item: Allocation) => `${kindLabel[item.kind] || item.kind}` +
    (item.block_reason ? ` · ${item.block_reason}` : "") +
    ` · ${localLabel(item.starts_at)} → ${localLabel(item.ends_at)}`

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div>
      <h1 className="text-3xl font-semibold">Calendario de habitaciones</h1>
      <p className="mt-2 text-sm text-muted-foreground">Reservas, estancias, mantenimiento y bloqueos por habitación. Una zona vacía no confirma disponibilidad futura.</p>
    </div><Button variant="outline" onClick={() => setRevision((value) => value + 1)}>Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {!options && !error ? <Skeleton className="h-64 rounded-xl" /> : options && <>
      <Card><CardHeader><CardTitle>Período</CardTitle><CardDescription>Horario local de {options.time_zone}.</CardDescription></CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <label className="space-y-1 text-sm"><span>Desde</span><Input type="date" value={fromDate}
          onChange={(event) => setFromDate(event.target.value)} className="w-48" /></label>
        <label className="space-y-1 text-sm"><span>Vista</span><select className="block h-9 rounded-md border border-border bg-white px-2"
          value={view} onChange={(event) => setView(event.target.value as "day" | "week")}>
          <option value="day">Un día</option><option value="week">Siete días</option>
        </select></label>
      </CardContent></Card>
      {loading && <Skeleton className="h-72 rounded-xl" />}
      {calendar && <Card><CardHeader><CardTitle>{view === "day" ? "Ocupación del día" : "Ocupación de siete días"}</CardTitle>
        <CardDescription>{calendar.allocations.length} intervalo(s) · Los datos son de consulta; el cupo se comprueba al reservar.</CardDescription>
      </CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3 text-xs">{Object.entries(kindLabel).map(([kind, label]) =>
          <span key={kind} className={`rounded border px-2 py-1 ${kindTone[kind]}`}>{label}</span>)}</div>
        <div className="overflow-x-auto rounded-md border border-border"><div className="min-w-[850px]">
          <div className="flex border-b border-border bg-secondary text-xs font-semibold"><div className="w-36 shrink-0 p-3">Habitación</div>
            <div className="relative h-10 flex-1 border-l border-border">{calendar.ticks.map((tick) =>
              <span key={tick.at} className="absolute top-0 h-full border-l border-border pl-1 pt-2"
                style={{ left: `${position(tick.at)}%` }}>{view === "week" ? dateLabel(tick.label) : tick.label}</span>)}</div></div>
          {rows.map(({ room, allocations }) => <div key={room.name || "unassigned"} className="flex border-b border-border last:border-b-0">
            <div className="w-36 shrink-0 p-2 text-sm">{room.name ? <Link className="font-semibold text-primary underline" to={`/rooms/${encodeURIComponent(room.name)}`}>{room.room_number}</Link> : <strong>Por asignar</strong>}
              {!room.active && <small className="block text-muted-foreground">Inactiva</small>}
              {room.cleaning_status && <small className="block text-muted-foreground">{room.cleaning_status}</small>}</div>
            <div className="relative flex-1 border-l border-border bg-background" style={{ height: Math.max(48, allocations.length * 36 + 8) }}>
              {calendar.ticks.map((tick) => <span key={tick.at} className="absolute inset-y-0 border-l border-border/60"
                style={{ left: `${position(tick.at)}%` }} />)}
              {allocations.map((item, index) => {
                const left = position(item.starts_at), right = position(item.ends_at)
                return <div key={item.name} title={detail(item)}
                  className={`absolute overflow-hidden whitespace-nowrap rounded border px-1 text-xs leading-7 ${kindTone[item.kind] || "bg-slate-200 text-slate-950 border-slate-400"}`}
                  style={{ left: `${left}%`, width: `${Math.max(0.4, right - left)}%`, top: index * 36 + 5 }}>
                  {right - left >= 9 && (kindLabel[item.kind] || item.kind)}
                </div>
              })}
            </div></div>)}
        </div></div>
        <details className="text-sm"><summary className="cursor-pointer font-medium">Lista de intervalos ({calendar.allocations.length})</summary>
          <ul className="mt-3 space-y-2">{rows.flatMap(({ room, allocations }) => allocations.map((item) =>
            <li key={item.name} className="rounded-md border border-border p-2"><strong>{room.room_number}</strong> · {detail(item)}</li>))}</ul>
        </details>
      </CardContent></Card>}
    </>}
  </div>
}
