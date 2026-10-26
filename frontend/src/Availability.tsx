import { useEffect, useRef, useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"

type Category = { name: string; category_name: string; capacity: number }
type Options = { property: string; time_zone: string; mode: string;
  local_now: string; categories: Category[] }
type State = { name: string; room_number: string; status: string;
  label: string; cleaning_status: string }
type Search = { property: string; category: string; category_label: string;
  starts_at: string; ends_at: string; time_zone: string; people: number;
  quantity: number; available: number; enough: boolean;
  physical_available: number; needs_assignment_review: boolean;
  rooms: { name: string; room_number: string; cleaning_status: string }[];
  room_states: State[] }

export type AvailabilityPrefill = { property: string; category: string;
  quantity: number; people: number; starts_at: string; ends_at: string;
  mode: "Hotel" | "Por tiempo"; room?: string }

const addHours = (value: string, hours: number) => {
  const date = new Date(`${value}Z`)
  date.setUTCHours(date.getUTCHours() + hours)
  return date.toISOString().slice(0, 16)
}
const cleaningLabel: Record<string, string> = {
  Clean: "Limpia", Dirty: "Sucia", Cleaning: "En limpieza",
  Inspection: "Pendiente de inspección",
}
const stateLabel: Record<string, string> = {
  Available: "Disponible", Reserved: "Reservada", Occupied: "Ocupada",
  Blocked: "Bloqueada", Buffer: "Colchón de limpieza",
  Inactive: "Inactiva", "Category Full": "Sin cupo por categoría",
}

export function Availability({ property }: { property: Property }) {
  const navigate = useNavigate()
  const active = useRef<AbortController | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [category, setCategory] = useState("")
  const [mode, setMode] = useState<"Hotel" | "Por tiempo">("Hotel")
  const [quantity, setQuantity] = useState("1")
  const [people, setPeople] = useState("1")
  const [startsAt, setStartsAt] = useState("")
  const [endsAt, setEndsAt] = useState("")
  const [result, setResult] = useState<Search | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setOptions(null); setResult(null); setError("")
    call<Options>("availability_options", { property_name: property.name }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setOptions(data)
        setCategory(data.categories.length === 1 ? data.categories[0].name : "")
        setMode(data.mode === "Por tiempo" ? "Por tiempo" : "Hotel")
        setStartsAt(data.local_now)
        setEndsAt(addHours(data.local_now, data.mode === "Por tiempo" ? 3 : 24))
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las categorías.")
      })
    return () => { controller.abort(); active.current?.abort() }
  }, [property.name])

  function change() {
    active.current?.abort(); active.current = null
    setBusy(false); setResult(null); setError("")
  }
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!options || !category || busy) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setBusy(true); setResult(null); setError("")
    try {
      const found = await call<Search>("availability_search", {
        property_name: property.name, category, quantity, people,
        starts_at: startsAt, ends_at: endsAt,
      }, controller.signal)
      if (!controller.signal.aborted) {
        if (found.property !== property.name || found.category !== category)
          throw new Error("La respuesta corresponde a otro establecimiento o categoría.")
        setResult(found)
      }
    } catch (issue) {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar la disponibilidad.")
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }
  function reserve(room?: string) {
    if (!result?.enough || result.property !== property.name) return
    const selectedRoom = room && result.rooms.some((item) => item.name === room) ? room : undefined
    const prefill: AvailabilityPrefill = {
      property: property.name, category: result.category,
      quantity: result.quantity, people: result.people,
      starts_at: startsAt, ends_at: endsAt, mode, room: selectedRoom,
    }
    navigate("/reception?section=reservation", { state: { availability: prefill } })
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Buscar disponibilidad</h1>
      <p className="mt-2 text-sm text-muted-foreground">Consulte el cupo de una categoría durante un intervalo. La búsqueda no reserva habitaciones.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {!options && !error ? <Skeleton className="h-60 rounded-xl" /> : options && <>
      <Card><CardHeader><CardTitle>Fechas y habitaciones</CardTitle>
        <CardDescription>Horario local de {options.time_zone}. Personas y habitaciones se comprueban por categoría.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => void search(event)} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {options.mode === "Mixed" && <label className="space-y-1 text-sm"><span>Modalidad de la reserva</span>
          <select className="h-9 w-full rounded-md border border-border bg-white px-2" value={mode}
            onChange={(event) => { const chosen = event.target.value as "Hotel" | "Por tiempo";
              setMode(chosen); setEndsAt(addHours(startsAt, chosen === "Por tiempo" ? 3 : 24)); change() }}>
            <option value="Hotel">Por noche</option><option value="Por tiempo">Por tiempo</option>
          </select></label>}
        <label className="space-y-1 text-sm"><span>Categoría</span>
          <select required className="h-9 w-full rounded-md border border-border bg-white px-2" value={category}
            onChange={(event) => { setCategory(event.target.value); change() }}>
            <option value="">Seleccione una categoría</option>
            {options.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name} · hasta {item.capacity} persona(s)</option>)}
          </select></label>
        <label className="space-y-1 text-sm"><span>Habitaciones solicitadas</span>
          <Input required type="number" min="1" max="1000" step="1" value={quantity}
            onChange={(event) => { setQuantity(event.target.value); change() }} /></label>
        <label className="space-y-1 text-sm"><span>Personas por habitación</span>
          <Input required type="number" min="1" max={options.categories.find((item) => item.name === category)?.capacity || undefined}
            step="1" value={people} onChange={(event) => { setPeople(event.target.value); change() }} /></label>
        <label className="space-y-1 text-sm"><span>Entrada</span>
          <Input required type="datetime-local" value={startsAt} onChange={(event) => { setStartsAt(event.target.value); change() }} /></label>
        <label className="space-y-1 text-sm"><span>Salida prevista</span>
          <Input required type="datetime-local" min={startsAt} value={endsAt} onChange={(event) => { setEndsAt(event.target.value); change() }} /></label>
        <div className="flex items-end"><Button disabled={busy || !category || !options.categories.length} className="w-full">{busy ? "Consultando…" : "Buscar disponibilidad"}</Button></div>
      </form></CardContent></Card>
      {result && <Card><CardHeader><CardTitle>{result.enough ? `Hay cupo para ${result.quantity} habitación(es)` :
        `No alcanza el cupo para ${result.quantity} habitación(es)`}</CardTitle>
        <CardDescription>{result.category_label} · {result.people} persona(s) por habitación · Cupo disponible: {result.available}</CardDescription>
      </CardHeader><CardContent className="space-y-4 text-sm">
        {result.needs_assignment_review && <p role="status" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900">Hay cupo por categoría, pero no suficientes habitaciones libres durante todo el intervalo. Recepción debe revisar la asignación física.</p>}
        {result.enough && <Button onClick={() => reserve()}>Crear reserva sin asignar habitación</Button>}
        {!!result.rooms.length && result.enough && <div className="space-y-2"><h3 className="font-semibold">Habitaciones libres durante todo el intervalo ({result.physical_available})</h3>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{result.rooms.map((room) => <div key={room.name} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-300 bg-emerald-50 p-3"><span><strong>{room.room_number}</strong><small className="block">Limpieza actual: {cleaningLabel[room.cleaning_status] || room.cleaning_status}</small></span><Button size="sm" variant="outline" onClick={() => reserve(room.name)}>Reservar</Button></div>)}</div></div>}
        <div className="space-y-2"><h3 className="font-semibold">Estado por habitación en el intervalo ({result.room_states.length})</h3>
          <p className="text-muted-foreground">La limpieza mostrada es la actual y debe verificarse antes del ingreso.</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{result.room_states.map((room) => <div key={room.name} className={`rounded-md border p-3 ${room.status === "Available" ? "border-emerald-300 bg-emerald-50" : "border-border bg-muted/50"}`}><div className="flex items-center justify-between gap-2"><strong>{room.room_number}</strong><span>{stateLabel[room.status] || room.status}</span></div><p className="mt-1 text-muted-foreground">{room.label}</p><small>Limpieza actual: {cleaningLabel[room.cleaning_status] || room.cleaning_status}</small></div>)}</div></div>
        <p className="text-xs text-muted-foreground">El cupo se vuelve a comprobar al confirmar la reserva.</p>
      </CardContent></Card>}
    </>}
  </div>
}
