import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property, type RoomDetail } from "./api"

type ScheduleRow = { kind: string; status: string; starts_at: string; ends_at: string;
  until_reopened: boolean; block_reason?: string | null }
type Schedule = { property: string; room: string; starts_at: string; ends_at: string;
  time_zone: string; rows: ScheduleRow[] }
type HistoryRow = { id: string; kind: "operation" | "change" | "period";
  title: string; occurred_at?: string | null; starts_at?: string | null;
  ends_at?: string | null; actor?: string; note?: string;
  relation?: string; fields: { label: string; before: string; after: string }[] }
type History = { property: string; room: string; time_zone: string; view: string;
  starts_at: string; ends_at: string; rows: HistoryRow[]; total: number;
  offset: number; page_length: number; has_more: boolean }
type InsightRow = { room: string; occupied_nights: number; blocked_nights: number;
  used_hours: number; blocked_hours: number; sellable_hours: number;
  utilization_pct: number | null; rotations: number; completed_cleans: number;
  timed_cleans: number; avg_clean_minutes: number | null }
type Insights = { property: string; days: number; mode: string;
  time_zone: string; from_date: string; through_date: string;
  denominator: string; rooms: InsightRow[] }
type HistoryView = "activity" | "changes" | "periods" | "all"
type HistoryQuery = { from: string; to: string; view: HistoryView; offset: number; revision: number }

const addDays = (date: string, days: number) => {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  Number.isFinite(Date.parse(`${value}T00:00:00Z`)) &&
  new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
const stamp = (value?: string | null) => value ? value.slice(0, 16).replace("T", " ") : "Sin fecha final"
const label: Record<string, string> = {
  Reservation: "Reserva", Stay: "Estancia", Maintenance: "Mantenimiento", "Room Block": "Bloqueo",
  operation: "Operación", change: "Cambio de datos", period: "Período",
}
const tone: Record<string, string> = {
  Reservation: "bg-violet-200", Stay: "bg-blue-200", Maintenance: "bg-amber-200",
  "Room Block": "bg-rose-200",
}

export function RoomDetailSections({ property, detail }: { property: Property; detail: RoomDetail }) {
  const room = detail.room.name
  const today = detail.checked_at.slice(0, 10)
  const allowedDays = detail.mode === "Por tiempo" ? [1, 2, 7] : [7, 14, 30]
  const [tab, setTab] = useState<"schedule" | "history" | "insights">("schedule")
  const [scheduleDate, setScheduleDate] = useState(today)
  const [scheduleDays, setScheduleDays] = useState(allowedDays[0])
  const [scheduleQuery, setScheduleQuery] = useState({ date: today, days: allowedDays[0], revision: 0 })
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [scheduleError, setScheduleError] = useState("")
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [historyFrom, setHistoryFrom] = useState(addDays(today, -7))
  const [historyTo, setHistoryTo] = useState(addDays(today, 1))
  const [historyView, setHistoryView] = useState<HistoryView>("activity")
  const [historyQuery, setHistoryQuery] = useState<HistoryQuery | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  const [historyError, setHistoryError] = useState("")
  const [historyLoading, setHistoryLoading] = useState(false)
  const [insightDays, setInsightDays] = useState(30)
  const [insights, setInsights] = useState<Insights | null>(null)
  const [insightsError, setInsightsError] = useState("")
  const [insightsLoading, setInsightsLoading] = useState(false)

  useEffect(() => {
    if (tab !== "schedule" || !scheduleQuery.date ||
        scheduleDate !== scheduleQuery.date || scheduleDays !== scheduleQuery.days) return
    const controller = new AbortController()
    setSchedule(null); setScheduleError(""); setScheduleLoading(true)
    const until = addDays(scheduleQuery.date, scheduleQuery.days)
    call<Schedule>("room_schedule", { property_name: property.name, room,
      starts_at: `${scheduleQuery.date}T00:00:00`, ends_at: `${until}T00:00:00` }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.room !== room ||
            !Array.isArray(result.rows) || Date.parse(result.ends_at) <= Date.parse(result.starts_at))
          throw new Error("La agenda no coincide con la habitación consultada.")
        setSchedule(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setScheduleError(issue instanceof Error ? issue.message : "No se pudo consultar la agenda.")
      }).finally(() => { if (!controller.signal.aborted) setScheduleLoading(false) })
    return () => controller.abort()
  }, [tab, property.name, room, scheduleQuery, scheduleDate, scheduleDays])

  useEffect(() => {
    if (tab !== "history" || !historyQuery || !detail.can.history ||
        historyFrom !== historyQuery.from || historyTo !== historyQuery.to ||
        historyView !== historyQuery.view) return
    const controller = new AbortController()
    setHistory(null); setHistoryError(""); setHistoryLoading(true)
    call<History>("room_history", { property_name: property.name, room,
      starts_at: `${historyQuery.from}T00:00:00`, ends_at: `${historyQuery.to}T00:00:00`,
      view: historyQuery.view, offset: String(historyQuery.offset), page_length: "25" }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.room !== room ||
            result.view !== historyQuery.view || result.offset !== historyQuery.offset ||
            !Array.isArray(result.rows))
          throw new Error("El historial no coincide con la consulta solicitada.")
        setHistory(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setHistoryError(issue instanceof Error ? issue.message : "No se pudo consultar el historial.")
      }).finally(() => { if (!controller.signal.aborted) setHistoryLoading(false) })
    return () => controller.abort()
  }, [tab, property.name, room, detail.can.history, historyQuery, historyFrom, historyTo, historyView])

  useEffect(() => {
    if (tab !== "insights") return
    const controller = new AbortController()
    setInsights(null); setInsightsError(""); setInsightsLoading(true)
    call<Insights>("room_insights", { property_name: property.name,
      days: String(insightDays) }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.days !== insightDays ||
            !Array.isArray(result.rooms) || !result.rooms.some((row) => row.room === room))
          throw new Error("No se encontraron indicadores para esta habitación.")
        setInsights(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setInsightsError(issue instanceof Error ? issue.message : "No se pudieron calcular los indicadores.")
      }).finally(() => { if (!controller.signal.aborted) setInsightsLoading(false) })
    return () => controller.abort()
  }, [tab, property.name, room, insightDays])

  const searchSchedule = () => {
    if (!validDate(scheduleDate) || !allowedDays.includes(scheduleDays)) {
      setSchedule(null); setScheduleError("Seleccione una fecha y un período válidos."); return
    }
    setScheduleQuery((current) => ({ date: scheduleDate, days: scheduleDays, revision: current.revision + 1 }))
  }
  const searchHistory = () => {
    if (!validDate(historyFrom) || !validDate(historyTo) || historyTo <= historyFrom) {
      setHistory(null); setHistoryError("Indique un rango de fechas válido."); return
    }
    setHistoryQuery((current) => ({ from: historyFrom, to: historyTo,
      view: historyView, offset: 0, revision: (current?.revision || 0) + 1 }))
  }
  const scheduleStart = schedule ? Date.parse(schedule.starts_at) : 0
  const scheduleSpan = schedule ? Date.parse(schedule.ends_at) - scheduleStart : 1
  const position = (value: string) => Math.max(0, Math.min(100,
    (Date.parse(value) - scheduleStart) / scheduleSpan * 100))
  const selectedInsight = insights?.rooms.find((row) => row.room === room)
  const metrics = selectedInsight ? [
    ...(insights?.mode === "Por tiempo" ? [] : [{ name: "Noches ocupadas", value: selectedInsight.occupied_nights }]),
    { name: "Horas utilizadas", value: `${selectedInsight.used_hours} h` },
    { name: "Horas fuera de servicio", value: `${selectedInsight.blocked_hours} h` },
    { name: "Horas comercializables", value: `${selectedInsight.sellable_hours} h` },
    { name: "Utilización", value: selectedInsight.utilization_pct === null ? "Sin horas comercializables" : `${selectedInsight.utilization_pct} %` },
    { name: "Rotaciones", value: selectedInsight.rotations },
    { name: "Limpiezas completadas", value: selectedInsight.completed_cleans },
    { name: "Limpieza media", value: selectedInsight.avg_clean_minutes === null ? "Sin mediciones" : `${selectedInsight.avg_clean_minutes} min` },
  ] : []

  return <Card><CardHeader><CardTitle>Agenda e historial</CardTitle>
    <CardDescription>Consultas de la habitación en el horario de {detail.time_zone}.</CardDescription></CardHeader>
    <CardContent className="space-y-5">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Secciones de la habitación">
        {(["schedule", ...(detail.can.history ? ["history"] : []), "insights"] as const).map((item) =>
          <Button key={item} type="button" role="tab" aria-selected={tab === item}
            variant={tab === item ? "default" : "outline"} onClick={() => setTab(item as typeof tab)}>
            {item === "schedule" ? "Agenda" : item === "history" ? "Historial" : "Indicadores"}
          </Button>)}
      </div>
      {tab === "schedule" && <div className="space-y-4" role="tabpanel">
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm"><span>Desde</span><Input className="w-48" type="date" value={scheduleDate}
            onChange={(event) => { setScheduleDate(event.target.value); setSchedule(null); setScheduleError("") }} /></label>
          <label className="space-y-1 text-sm"><span>Días</span><select className="block h-9 rounded-md border border-border bg-white px-2"
            value={scheduleDays} onChange={(event) => { setScheduleDays(Number(event.target.value)); setSchedule(null); setScheduleError("") }}>
            {allowedDays.map((days) => <option key={days} value={days}>{days}</option>)}
          </select></label>
          <Button onClick={searchSchedule}>Consultar agenda</Button>
          {detail.can.reserve && <Button asChild variant="outline"><Link to="/availability">Buscar disponibilidad</Link></Button>}
        </div>
        {scheduleError && <p role="alert" className="text-sm text-destructive">{scheduleError}</p>}
        {scheduleLoading && <Skeleton className="h-28 rounded-lg" />}
        {schedule && <><p className="text-sm text-muted-foreground">{stamp(schedule.starts_at)} → {stamp(schedule.ends_at)} · {schedule.time_zone}</p>
          {schedule.rows.length > 0 ? <><div className="relative h-8 overflow-hidden rounded-md border border-border bg-muted" aria-hidden="true">
            {schedule.rows.map((row, index) => <span key={index} className={`absolute inset-y-1 rounded border border-foreground/25 ${tone[row.kind] || "bg-slate-200"}`}
              style={{ left: `${position(row.starts_at)}%`, width: `${Math.max(.4, position(row.ends_at) - position(row.starts_at))}%` }} />)}
          </div><div className="space-y-2">{schedule.rows.map((row, index) => <div key={index} className="rounded-md border border-border p-3 text-sm">
            <strong>{row.block_reason || label[row.kind] || row.kind}</strong>{row.until_reopened && <span> · Hasta reapertura autorizada</span>}
            <p>{stamp(row.starts_at)} → {stamp(row.ends_at)} · {row.status}</p>
          </div>)}</div></> : <p className="text-sm text-muted-foreground">Sin asignaciones en este período.</p>}
          <p className="text-xs text-muted-foreground">Una franja vacía no confirma cupo; compruebe disponibilidad antes de reservar.</p>
        </>}
      </div>}
      {tab === "history" && detail.can.history && <div className="space-y-4" role="tabpanel">
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm"><span>Desde</span><Input className="w-44" type="date" value={historyFrom}
            onChange={(event) => { setHistoryFrom(event.target.value); setHistory(null); setHistoryError("") }} /></label>
          <label className="space-y-1 text-sm"><span>Hasta (sin incluir)</span><Input className="w-44" type="date" value={historyTo}
            onChange={(event) => { setHistoryTo(event.target.value); setHistory(null); setHistoryError("") }} /></label>
          <label className="space-y-1 text-sm"><span>Vista</span><select className="block h-9 rounded-md border border-border bg-white px-2"
            value={historyView} onChange={(event) => { setHistoryView(event.target.value as HistoryView); setHistory(null); setHistoryError("") }}>
            <option value="activity">Actividad</option><option value="changes">Cambios de datos</option>
            <option value="periods">Estancias y bloqueos</option><option value="all">Todo</option>
          </select></label>
          <Button onClick={searchHistory}>Consultar historial</Button>
        </div>
        {historyError && <p role="alert" className="text-sm text-destructive">{historyError}</p>}
        {historyLoading && <Skeleton className="h-40 rounded-lg" />}
        {history && <><p className="text-sm text-muted-foreground">{stamp(history.starts_at)} → {stamp(history.ends_at)} · {history.time_zone}</p>
          <div className="space-y-2">{history.rows.map((row) => <article key={row.id} className="rounded-md border border-border p-3 text-sm">
            <p className="text-xs font-medium text-muted-foreground">{label[row.kind] || row.kind} · {row.kind === "period" ? `${stamp(row.starts_at)} → ${stamp(row.ends_at)}` : stamp(row.occurred_at)}</p>
            <strong>{row.title}</strong>{row.actor && <p>Registrado por: {row.actor}</p>}
            {row.note && <p className="mt-1">{row.note}</p>}
            {row.relation === "related" && <p className="text-xs text-muted-foreground">La habitación de este documento relacionado no pudo reconstruirse de forma única.</p>}
            {row.fields?.length > 0 && <details className="mt-2"><summary className="cursor-pointer">Ver valores registrados ({row.fields.length})</summary>
              <div className="mt-2 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th>Dato</th><th>Antes</th><th>Después</th></tr></thead>
                <tbody>{row.fields.map((field, index) => <tr key={index} className="border-t border-border"><td className="p-1">{field.label}</td><td className="p-1">{field.before}</td><td className="p-1">{field.after}</td></tr>)}</tbody></table></div>
            </details>}
          </article>)}{!history.rows.length && <p className="text-sm text-muted-foreground">No hay movimientos para estas fechas.</p>}</div>
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>{history.total ? history.offset + 1 : 0}–{history.offset + history.rows.length} de {history.total}</span>
            <div className="flex gap-2"><Button variant="outline" disabled={historyLoading || history.offset === 0} onClick={() => setHistoryQuery((query) => query && ({ ...query, offset: Math.max(0, query.offset - 25) }))}>Anterior</Button>
              <Button variant="outline" disabled={historyLoading || !history.has_more} onClick={() => setHistoryQuery((query) => query && ({ ...query, offset: query.offset + 25 }))}>Siguiente</Button></div>
          </div></>}
        {!history && !historyLoading && !historyError && <p className="text-sm text-muted-foreground">Consulte períodos que cruzan las fechas y cambios registrados dentro del rango.</p>}
      </div>}
      {tab === "insights" && <div className="space-y-4" role="tabpanel">
        <label className="block space-y-1 text-sm"><span>Período</span><select className="block h-9 rounded-md border border-border bg-white px-2"
          value={insightDays} onChange={(event) => setInsightDays(Number(event.target.value))}>
          {[7, 30, 90].map((days) => <option key={days} value={days}>{days} días</option>)}
        </select></label>
        {insightsError && <p role="alert" className="text-sm text-destructive">{insightsError}</p>}
        {insightsLoading && <Skeleton className="h-36 rounded-lg" />}
        {insights && selectedInsight && <><p className="text-sm text-muted-foreground">{insights.from_date} → {insights.through_date} · {insights.time_zone}</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{metrics.map((metric) => <div key={metric.name} className="rounded-md border border-border p-3">
            <p className="text-xs text-muted-foreground">{metric.name}</p><strong className="text-lg">{metric.value}</strong>
          </div>)}</div>
          <p className="text-xs text-muted-foreground">{insights.denominator}. Los ingresos por habitación requieren atribuir cargos y cambios de cuarto al período.</p>
        </>}
      </div>}
    </CardContent>
  </Card>
}
