import { Suspense, useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Dialog as DialogPrimitive } from "radix-ui"
import { X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property, type RoomDetail } from "./api"
import { RoomAccountActions } from "./RoomAccountActions"
import { RoomDetailSections } from "./RoomDetailSections"
import { RoomServiceAction } from "./RoomServiceAction"
import { Departure, Reception } from "./LazyPages"

export type RoomPanelTab = "now" | "reservation" | "arrival" | "departure" |
  "service" | "account" | "work" | "schedule" | "history" | "insights" | "details"
const panelTabs: RoomPanelTab[] = ["now", "reservation", "arrival", "departure", "service",
  "account", "work", "schedule", "history", "insights", "details"]
export const roomPanelTab = (value: string | null): RoomPanelTab =>
  panelTabs.includes(value as RoomPanelTab) ? value as RoomPanelTab : "now"

const stamp = (value?: string | null) => value ? value.slice(0, 16).replace("T", " ") : "—"
const cleaning: Record<string, string> = { Clean: "Limpia", Dirty: "Sucia",
  Cleaning: "En limpieza", Inspection: "Por inspeccionar" }

export function RoomPanel({ property, provider, actions, room, initialTab, onClose, onChanged, onTabChange }: {
  property: Property; provider: "pms" | "erpnext"; actions: string[]; room: string
  initialTab: RoomPanelTab; onClose: () => void; onChanged: () => void;
  onTabChange: (tab: RoomPanelTab) => void
}) {
  const [detail, setDetail] = useState<RoomDetail | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [tab, setTab] = useState<RoomPanelTab>(initialTab)
  const refresh = useCallback(async () => {
    const result = await call<RoomDetail>("room_snapshot", { property_name: property.name, room })
    if (result.property !== property.name || result.room.name !== room)
      throw new Error("La ficha recibida no corresponde a esta habitación.")
    setDetail(result)
  }, [property.name, room])

  useEffect(() => {
    const controller = new AbortController()
    setDetail(null); setError(""); setNotice("")
    call<RoomDetail>("room_snapshot", { property_name: property.name, room }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.room.name !== room)
          throw new Error("La ficha recibida no corresponde a esta habitación.")
        setDetail(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo cargar la habitación.")
      })
    return () => controller.abort()
  }, [property.name, room])

  useEffect(() => setTab(initialTab), [initialTab])

  useEffect(() => {
    if (!detail) return
    if ((tab === "departure" && !detail.current?.name) ||
        (tab === "arrival" && !detail.next_arrival?.booking) ||
        (tab === "service" && !detail.current?.service_stay))
      selectTab("now")
  }, [detail, tab])

  const selectTab = (next: RoomPanelTab) => { setTab(next); onTabChange(next) }
  const updated = async () => {
    try { await refresh(); setNotice("Operación registrada. La ficha se actualizó.") }
    catch (issue) { setError(issue instanceof Error ? issue.message : "La operación se registró, pero no se pudo actualizar la ficha.") }
    onChanged()
  }
  const canFinance = actions.includes("finance")
  const current = detail?.current
  const arrival = detail?.next_arrival
  const sections: { id: RoomPanelTab; label: string; visible: boolean }[] = [
    { id: "now", label: "Ahora", visible: true },
    { id: "reservation", label: "Reservar", visible: Boolean(detail?.can.reserve && !detail.room.occupied && !detail.room.blocked) },
    { id: "arrival", label: "Entrada", visible: Boolean(detail?.can.reserve && detail?.can.stay && arrival?.booking) },
    { id: "departure", label: "Salida", visible: Boolean(detail?.can.stay && current?.name) },
    { id: "service", label: "Consumos", visible: Boolean(detail?.can.service && current?.service_stay) },
    { id: "account", label: "Cuenta", visible: Boolean(detail?.can.account && current) },
    { id: "work", label: "Trabajo", visible: true },
    { id: "schedule", label: "Agenda", visible: true },
    { id: "history", label: "Historial", visible: Boolean(detail?.can.history) },
    { id: "insights", label: "Indicadores", visible: true },
    { id: "details", label: "Datos", visible: true },
  ]

  return <DialogPrimitive.Root open onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45" />
      <DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-background shadow-2xl outline-none sm:max-w-3xl"
        aria-describedby="room-panel-description">
        <header className="flex items-start justify-between gap-3 border-b px-4 py-4 sm:px-6">
          <div className="min-w-0"><DialogPrimitive.Title className="text-xl font-semibold">Ficha de habitación {detail?.room.room_number || ""}</DialogPrimitive.Title>
            <DialogPrimitive.Description id="room-panel-description" className="text-sm text-muted-foreground">
              {detail ? `${detail.room.category_label}${detail.room.floor ? ` · Piso ${detail.room.floor}` : ""}` : "Cargando habitación"}
            </DialogPrimitive.Description></div>
          <DialogPrimitive.Close asChild><Button type="button" variant="ghost" size="icon" aria-label="Cerrar ficha"><X size={18} /></Button></DialogPrimitive.Close>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
          {notice && <p role="status" className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
          {!detail && !error && <Skeleton className="h-64 w-full rounded-xl" />}
          {detail && <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{detail.room.occupied ? "Ocupada" : "Sin ocupación"}</Badge>
              <Badge variant="outline">{cleaning[detail.room.cleaning_status] || detail.room.cleaning_status}</Badge>
              {detail.room.arrival && <Badge variant="secondary">Llegada pendiente</Badge>}
              {detail.room.departure && <Badge variant="secondary">Salida prevista</Badge>}
              {detail.room.blocked && <Badge variant="destructive">Fuera de servicio</Badge>}
            </div>
            <div role="tablist" aria-label="Secciones de la ficha" className="flex gap-1 overflow-x-auto border-b pb-2">
              {sections.filter((section) => section.visible).map((section) => <Button key={section.id}
                type="button" role="tab" aria-selected={tab === section.id} size="sm"
                variant={tab === section.id ? "default" : "ghost"} onClick={() => selectTab(section.id)}>{section.label}</Button>)}
            </div>
            {tab === "now" && <div role="tabpanel" className="space-y-4 text-sm">
              <section className="rounded-lg border p-4"><h3 className="font-semibold">Estancia actual</h3>
                {current ? <div className="mt-2 space-y-2"><p>{current.guest_label || "Huésped registrado"}</p>
                  <p className="text-muted-foreground">{stamp(current.starts_at)} → {stamp(current.ends_at)}</p>
                  {current.account_balances?.map((balance) => <p key={balance.currency}>Saldo: {balance.currency} {balance.outstanding}</p>)}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {detail.can.service && current.service_stay && <Button size="sm" onClick={() => selectTab("service")}>Agregar consumo</Button>}
                    {detail.can.account && <Button size="sm" variant="outline" onClick={() => selectTab("account")}>Ver cuenta</Button>}
                    {detail.can.stay && current.name && <Button size="sm" variant="outline" onClick={() => selectTab("departure")}>Revisar salida</Button>}
                  </div></div> : <p className="mt-2 text-muted-foreground">Sin estancia activa.</p>}
              </section>
              <section className="rounded-lg border p-4"><h3 className="font-semibold">Próxima llegada asignada</h3>
                {arrival ? <div className="mt-2 space-y-2"><p>{arrival.guest_label || "Huésped registrado"}</p>
                  <p className="text-muted-foreground">{stamp(arrival.starts_at)} → {stamp(arrival.ends_at)}</p>
                  {detail.can.reserve && detail.can.stay && arrival.booking && <Button size="sm"
                    onClick={() => selectTab("arrival")}>Registrar entrada</Button>}
                </div> : <p className="mt-2 text-muted-foreground">Sin llegada asignada pendiente.</p>}
              </section>
              {!current && !arrival && detail.can.reserve && <Button onClick={() => selectTab("reservation")}>Reservar habitación</Button>}
            </div>}
            {tab === "reservation" && detail.can.reserve && <div role="tabpanel"><Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <Reception key={`${room}:reservation`} property={property} provider={provider} canApprove={actions.includes("approve")}
                canSetup={actions.includes("setup")} canManageGuests={actions.includes("guest")}
                canStay={actions.includes("stay")} embeddedSection="reservation" onChanged={() => void updated()}
                initialRoomChoice={{ property: property.name, room, category: detail.room.category }} />
            </Suspense></div>}
            {tab === "arrival" && arrival?.booking && <div role="tabpanel"><Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <Reception key={`${room}:arrival`} property={property} provider={provider} canApprove={actions.includes("approve")}
                canSetup={actions.includes("setup")} canManageGuests={actions.includes("guest")}
                canStay={actions.includes("stay")} embeddedSection="arrivals" onChanged={() => void updated()}
                initialBooking={{ property: property.name, name: arrival.booking, action: "arrival" }} />
            </Suspense></div>}
            {tab === "departure" && current?.name && <div role="tabpanel"><Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <Departure key={`${room}:departure`} property={property} provider={provider} canInspect={actions.includes("inspect")}
                canFinance={canFinance} canApprove={actions.includes("approve")} embedded initialStay={current.name}
                onChanged={() => void updated()} />
            </Suspense></div>}
            {tab === "service" && detail.can.service && current?.service_stay && <div role="tabpanel">
              <RoomServiceAction key={`${property.name}:${current.service_stay}`} property={property} stay={current.service_stay}
                provider={provider} roomNumber={detail.room.room_number} initialOpen onAccountChanged={updated} />
            </div>}
            {tab === "account" && detail.can.account && current && <div role="tabpanel" className="text-sm">
              <RoomAccountActions accounts={current.accounts || []} charges={current.recent_charges || []}
                provider={provider} canFinance={canFinance} />
            </div>}
            {tab === "work" && <div role="tabpanel" className="space-y-4 text-sm">
              <section className="rounded-lg border p-4"><h3 className="font-semibold">Limpieza e inspección</h3>
                <p className="mt-2">Estado: {cleaning[detail.room.cleaning_status] || detail.room.cleaning_status}</p>
                {detail.tasks.map((task) => <p key={task.name}>{task.kind} · {task.status} · {task.priority}</p>)}
                {!detail.tasks.length && <p className="mt-1 text-muted-foreground">Sin tareas abiertas.</p>}</section>
              <section className="rounded-lg border p-4"><h3 className="font-semibold">Mantenimiento y tickets</h3>
                {detail.maintenance.map((row) => <p key={row.name}>{row.title} · {row.status}</p>)}
                {detail.tickets.map((row) => <p key={row.name}>{row.subject} · {row.status}</p>)}
                {!detail.maintenance.length && !detail.tickets.length && <p className="mt-1 text-muted-foreground">Sin incidencias abiertas.</p>}</section>
              {(detail.can.clean || detail.can.maintain || detail.can.block) && <Button asChild variant="outline" size="sm"><Link
                to={`/room-work?room=${encodeURIComponent(detail.room.name)}`}>Gestionar trabajo</Link></Button>}
            </div>}
            {(tab === "schedule" || tab === "history" || tab === "insights") && <div role="tabpanel">
              <RoomDetailSections key={`${room}:${tab}`} property={property} detail={detail} initialTab={tab} embedded />
            </div>}
            {tab === "details" && <div role="tabpanel" className="space-y-2 rounded-lg border p-4 text-sm">
              <p>Capacidad: {detail.details.capacity ?? "—"} · Camas: {detail.details.beds ?? "—"}</p>
              {detail.details.parking && <p>Estacionamiento: {detail.details.parking}</p>}
              {detail.details.amenities && <p>{detail.details.amenities}</p>}
              {detail.details.description && <p className="text-muted-foreground">{detail.details.description}</p>}
            </div>}
            <p className="text-xs text-muted-foreground">Actualizado: {stamp(detail.checked_at)} · {detail.time_zone}</p>
          </div>}
        </div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
}
