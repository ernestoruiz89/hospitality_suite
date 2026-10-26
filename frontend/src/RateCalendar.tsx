import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"

type Category = { name: string; category_name: string; capacity: number }
type Options = { property: string; time_zone: string; mode: string;
  local_now: string; categories: Category[] }
type CalendarRow = { date: string; available: number; starts_at: string;
  ends_at: string; rate_status: "ok" | "no_rate" | "collision" |
    "wrong_currency" | "review_rate"; amount: string | null;
  currency: string; rate: string | null; rate_title: string | null }
type Calendar = { property: string; category: string; category_label: string;
  mode: string; from_date: string; days: number; people: number;
  hours: number | null; time_zone: string; rows: CalendarRow[];
  read_only: boolean }
type Mode = "Hotel" | "Por tiempo" | "Day Pass"

const issues: Record<string, string> = {
  no_rate: "Sin tarifa", collision: "Tarifas con la misma prioridad",
  wrong_currency: "Tarifa en otra moneda", review_rate: "Tarifa por revisar",
}
const modeLabel: Record<Mode, string> = {
  Hotel: "Por noche", "Por tiempo": "Por tiempo", "Day Pass": "Day Pass",
}

export function RateCalendar({ property }: { property: Property }) {
  const active = useRef<AbortController | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [category, setCategory] = useState("")
  const [fromDate, setFromDate] = useState("")
  const [days, setDays] = useState("14")
  const [people, setPeople] = useState("1")
  const [mode, setMode] = useState<Mode>("Hotel")
  const [hours, setHours] = useState("3")
  const [calendar, setCalendar] = useState<Calendar | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setOptions(null); setCalendar(null); setError("")
    call<Options>("availability_options", { property_name: property.name }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setOptions(data)
        setCategory(data.categories[0]?.name || "")
        setFromDate(data.local_now.slice(0, 10))
        setMode(data.mode === "Por tiempo" ? "Por tiempo" : "Hotel")
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las categorías.")
      })
    return () => { controller.abort(); active.current?.abort() }
  }, [property.name])

  function change() {
    active.current?.abort(); active.current = null
    setBusy(false); setCalendar(null); setError("")
  }
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!options || !category || busy) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setBusy(true); setCalendar(null); setError("")
    try {
      const result = await call<Calendar>("rate_calendar", {
        property_name: property.name, category, from_date: fromDate,
        days, people, mode, hours,
      }, controller.signal)
      if (controller.signal.aborted) return
      if (result.property !== property.name || result.category !== category ||
          result.from_date !== fromDate || result.days !== Number(days) ||
          result.mode !== mode || !result.read_only ||
          result.rows.length !== result.days)
        throw new Error("El calendario no coincide con la consulta solicitada.")
      setCalendar(result)
    } catch (issue) {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el calendario.")
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }

  const modes: Mode[] = options?.mode === "Mixed" ? ["Hotel", "Por tiempo", "Day Pass"] :
    options?.mode === "Por tiempo" ? ["Por tiempo", "Day Pass"] : ["Hotel"]
  const chosenCategory = options?.categories.find((item) => item.name === category)
  const interval = mode === "Hotel" ? "Entrada 14:00; salida 11:00 del día siguiente." :
    mode === "Day Pass" ? `Inicio 08:00; duración ${hours} horas, dentro del mismo día.` :
    `Inicio 14:00; duración ${hours} horas.`

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Calendario de tarifas</h1>
      <p className="mt-2 text-sm text-muted-foreground">Compare precio orientativo y cupo por fecha. La tarifa y la disponibilidad se revisan de nuevo al reservar.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {!options && !error ? <Skeleton className="h-60 rounded-xl" /> : options && <>
      <Card><CardHeader><CardTitle>Consulta</CardTitle>
        <CardDescription>Fechas del establecimiento: {options.time_zone}.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => void search(event)} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="space-y-1 text-sm"><span>Categoría</span>
          <select required className="h-9 w-full rounded-md border border-border bg-white px-2" value={category}
            onChange={(event) => { setCategory(event.target.value); change() }}>
            {options.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}
          </select></label>
        <label className="space-y-1 text-sm"><span>Desde</span>
          <Input required type="date" value={fromDate} onChange={(event) => { setFromDate(event.target.value); change() }} /></label>
        <label className="space-y-1 text-sm"><span>Días</span>
          <select className="h-9 w-full rounded-md border border-border bg-white px-2" value={days}
            onChange={(event) => { setDays(event.target.value); change() }}>
            <option value="7">7 días</option><option value="14">14 días</option><option value="31">31 días</option>
          </select></label>
        <label className="space-y-1 text-sm"><span>Personas por habitación</span>
          <Input required type="number" min="1" max={chosenCategory?.capacity} step="1" value={people}
            onChange={(event) => { setPeople(event.target.value); change() }} /></label>
        <label className="space-y-1 text-sm"><span>Modalidad</span>
          <select className="h-9 w-full rounded-md border border-border bg-white px-2" value={mode}
            onChange={(event) => { const chosen = event.target.value as Mode;
              setMode(chosen); setHours(chosen === "Day Pass" ? "8" : "3"); change() }}>
            {modes.map((item) => <option key={item} value={item}>{modeLabel[item]}</option>)}
          </select></label>
        {mode !== "Hotel" && <label className="space-y-1 text-sm"><span>Horas del bloque</span>
          <Input required type="number" min="1" max={mode === "Day Pass" ? "15" : "24"} step="1"
            value={hours} onChange={(event) => { setHours(event.target.value); change() }} /></label>}
        <div className="flex items-end"><Button disabled={busy || !category} className="w-full">{busy ? "Consultando…" : "Consultar tarifas"}</Button></div>
      </form></CardContent></Card>
      {calendar && <Card><CardHeader><CardTitle>{calendar.category_label} · {modeLabel[calendar.mode as Mode]}</CardTitle>
        <CardDescription>{interval} El precio es orientativo y no garantiza cupo futuro.</CardDescription>
      </CardHeader><CardContent>
        <div className="max-h-[65vh] overflow-auto rounded-md border border-border"><table className="w-full min-w-[550px] text-sm">
          <thead className="sticky top-0 bg-secondary text-left"><tr><th className="p-3">Fecha</th><th className="p-3">Tarifa</th><th className="p-3">Precio</th><th className="p-3">Cupo</th></tr></thead>
          <tbody>{calendar.rows.map((row) => <tr key={row.date} className="border-t border-border">
            <th scope="row" className="p-3 text-left font-medium">{row.date}</th>
            <td className="p-3">{row.rate_status === "ok" ? row.rate_title || row.rate || "Tarifa aplicable" : issues[row.rate_status] || "Tarifa por revisar"}</td>
            <td className="p-3 tabular-nums">{row.rate_status === "ok" && row.amount !== null ? `${row.currency} ${row.amount}` : "—"}</td>
            <td className="p-3">{row.available > 0 ? `${row.available} con cupo` : "Sin cupo"}</td>
          </tr>)}</tbody>
        </table></div>
      </CardContent></Card>}
    </>}
  </div>
}
