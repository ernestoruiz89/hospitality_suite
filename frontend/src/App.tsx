import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { Link, NavLink, Navigate, Route, Routes, useParams } from "react-router-dom"
import { Banknote, BedDouble, BookOpen, CalendarDays, ChevronRight, ClipboardList, LayoutDashboard, FolderTree, HandCoins, LogIn, Menu, RefreshCw, Search, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Bootstrap, type Property, type Room, type RoomBoard, type RoomDetail } from "./api"
import { Journal } from "./Journal"
import { Chart } from "./Chart"
import { Cash } from "./Cash"
import { Receivables } from "./Receivables"

const PROPERTY_KEY = "hospitality-suite-property"

function useBootstrap() {
  const [base, setBase] = useState<Bootstrap | null>(null)
  const [property, setProperty] = useState<string>("")
  const [detail, setDetail] = useState<Bootstrap | null>(null)
  const [error, setError] = useState<string>("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    call<Bootstrap>("bootstrap", {}, controller.signal)
      .then((data) => {
        setBase(data)
        const saved = localStorage.getItem(PROPERTY_KEY)
        setProperty(data.properties.some((item) => item.name === saved) ? saved! : data.properties[0]?.name || "")
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!property) return
    const controller = new AbortController()
    setDetail(null)
    setError("")
    localStorage.setItem(PROPERTY_KEY, property)
    call<Bootstrap>("bootstrap", { property_name: property }, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property])

  return { base, detail, property, setProperty, error, loading }
}

function Shell({ children, properties, property, setProperty, showJournal, showChart, showCash }: {
  children: ReactNode
  properties: Property[]
  property: string
  setProperty: (value: string) => void
  showJournal: boolean
  showChart: boolean
  showCash: boolean
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const selected = properties.find((item) => item.name === property)
  const nav = [
    { to: "/", label: "Inicio", icon: LayoutDashboard },
    { to: "/rooms", label: "Habitaciones", icon: BedDouble },
    ...(showCash ? [{ to: "/cash", label: "Caja", icon: Banknote }] : []),
    ...(showCash ? [{ to: "/receivables", label: "Cuentas por cobrar", icon: HandCoins }] : []),
    ...(showJournal ? [{ to: "/journal", label: "Asiento contable", icon: BookOpen }] : []),
    ...(showChart ? [{ to: "/chart", label: "Catálogo de cuentas", icon: FolderTree }] : []),
  ]
  return <div className="min-h-screen lg:flex">
    {menuOpen && <button className="fixed inset-0 z-30 bg-black/35 lg:hidden" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)} />}
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-68 flex-col border-r border-border bg-white p-5 shadow-xl transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:shadow-none ${menuOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="mb-9 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3" onClick={() => setMenuOpen(false)}>
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-white"><BedDouble size={23} /></span>
          <span><strong className="block text-base leading-tight">Hospitality</strong><span className="text-xs tracking-[0.2em] text-muted-foreground">SUITE</span></span>
        </Link>
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)}><X /></Button>
      </div>
      <p className="mb-3 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Operación</p>
      <nav className="space-y-1" aria-label="Navegación principal">
        {nav.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} onClick={() => setMenuOpen(false)}
          className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium ${isActive ? "bg-secondary text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
          <Icon size={18} />{label}
        </NavLink>)}
      </nav>
      <div className="mt-auto rounded-xl border border-border bg-background p-3">
        <p className="text-xs text-muted-foreground">Establecimiento activo</p>
        <p className="mt-1 text-sm font-semibold">{selected?.brand_name || selected?.property_name || "Seleccione uno"}</p>
        <p className="mt-1 text-xs text-muted-foreground">{selected?.mode}</p>
      </div>
    </aside>
    <div className="min-w-0 flex-1">
      <header className="sticky top-0 z-20 flex min-h-18 items-center gap-3 border-b border-border bg-white/95 px-4 backdrop-blur lg:px-8">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Abrir menú" onClick={() => setMenuOpen(true)}><Menu /></Button>
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{selected?.brand_name || selected?.property_name || "Hospitality Suite"}</p><p className="text-xs text-muted-foreground">Operación del establecimiento</p></div>
        <label className="sr-only" htmlFor="property-picker">Establecimiento</label>
        <select id="property-picker" className="max-w-48 rounded-md border border-border bg-white px-3 py-2 text-sm" value={property} onChange={(event) => setProperty(event.target.value)}>
          {properties.map((item) => <option key={item.name} value={item.name}>{item.brand_name || item.property_name}</option>)}
        </select>
      </header>
      <main className="mx-auto max-w-7xl p-4 lg:p-8">{children}</main>
    </div>
  </div>
}

function StatCard({ label, value, hint, icon: Icon }: { label: string; value: number | string; hint: string; icon: typeof BedDouble }) {
  return <Card className="gap-3"><CardHeader className="flex flex-row items-center justify-between"><CardDescription>{label}</CardDescription><Icon size={18} className="text-primary" /></CardHeader><CardContent><p className="text-3xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-xs text-muted-foreground">{hint}</p></CardContent></Card>
}

function Dashboard({ property, data }: { property: Property; data: Bootstrap | null }) {
  const [board, setBoard] = useState<RoomBoard | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    const controller = new AbortController()
    setBoard(null)
    call<RoomBoard>("room_board_snapshot", { property_name: property.name }, controller.signal)
      .then(setBoard)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property.name])
  return <div className="space-y-7">
    <div><p className="text-sm font-medium text-primary">{property.business_date}</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Panel del establecimiento</h1><p className="mt-2 text-muted-foreground">Situación operativa de {property.brand_name || property.property_name}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {board ? <>
        <StatCard label="Habitaciones ocupadas" value={board.counts.occupied} hint={`de ${board.rooms.filter((room) => room.active).length} activas`} icon={BedDouble} />
        <StatCard label="Llegadas" value={board.counts.arrival} hint="Con habitación asignada" icon={CalendarDays} />
        <StatCard label="Salidas" value={board.counts.departure} hint="Previstas para hoy" icon={ChevronRight} />
        <StatCard label="Trabajo pendiente" value={board.counts.work} hint="Habitaciones con tareas" icon={ClipboardList} />
      </> : Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-33 rounded-xl" />)}
    </div>
    <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card><CardHeader><CardTitle>Atención inmediata</CardTitle><CardDescription>Habitaciones con llegada, salida o trabajo pendiente.</CardDescription></CardHeader><CardContent className="space-y-2">
        {board?.rooms.filter((room) => room.arrival || room.departure || room.work).slice(0, 8).map((room) => <Link key={room.name} to={`/rooms/${encodeURIComponent(room.name)}`} className="flex items-center justify-between rounded-lg border border-border p-3 hover:bg-muted"><div><strong>Habitación {room.room_number}</strong><p className="text-sm text-muted-foreground">{room.category_label}</p></div><div className="flex gap-1">{room.arrival && <Badge>Entrada</Badge>}{room.departure && <Badge variant="secondary">Salida</Badge>}{room.work && <Badge variant="outline">Trabajo</Badge>}</div></Link>)}
        {board && !board.rooms.some((room) => room.arrival || room.departure || room.work) && <p className="py-8 text-center text-sm text-muted-foreground">No hay habitaciones que requieran atención inmediata.</p>}
        {!board && <Skeleton className="h-20" />}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Fecha operativa</CardTitle><CardDescription>Información del establecimiento seleccionado.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Fecha</span><strong>{property.business_date}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Modalidad</span><strong>{property.mode}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Moneda</span><strong>{property.currency}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Zona horaria</span><strong>{property.time_zone}</strong></div>
        {data?.shifts && <div className="flex justify-between gap-3"><span className="text-muted-foreground">Turnos abiertos</span><strong>{data.shifts.filter((shift) => shift.status === "Open").length}</strong></div>}
        <Button asChild className="mt-3 w-full"><Link to="/rooms">Ver habitaciones <ChevronRight /></Link></Button>
      </CardContent></Card>
    </div>
  </div>
}

function status(room: Room) {
  if (!room.active) return { text: "Inactiva", tone: "bg-slate-100 text-slate-700" }
  if (room.blocked) return { text: "Bloqueada", tone: "bg-amber-100 text-amber-800" }
  if (room.occupied) return { text: "Ocupada", tone: "bg-blue-100 text-blue-800" }
  if (room.arrival) return { text: "Llegada", tone: "bg-violet-100 text-violet-800" }
  return { text: "Disponible", tone: "bg-emerald-100 text-emerald-800" }
}

function RoomList({ property }: { property: Property }) {
  const [board, setBoard] = useState<RoomBoard | null>(null)
  const [search, setSearch] = useState("")
  const [error, setError] = useState("")
  const refresh = useCallback((signal?: AbortSignal) => {
    setError("")
    call<RoomBoard>("room_board_snapshot", { property_name: property.name }, signal)
      .then(setBoard)
      .catch((reason: unknown) => { if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
  }, [property.name])
  useEffect(() => { const controller = new AbortController(); setBoard(null); refresh(controller.signal); return () => controller.abort() }, [refresh])
  const filtered = useMemo(() => (board?.rooms || []).filter((room) => `${room.room_number} ${room.category_label} ${room.floor || ""} ${room.zone || ""}`.toLowerCase().includes(search.toLowerCase())), [board, search])
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-3xl font-semibold tracking-tight">Habitaciones</h1><p className="mt-2 text-sm text-muted-foreground">Estado actual, llegadas y tareas por habitación.</p></div><Button variant="outline" onClick={() => refresh()}><RefreshCw size={16} /> Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <div className="relative max-w-sm"><Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input aria-label="Buscar habitación" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar habitación o categoría" className="pl-9" /></div>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {!board && Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-43 rounded-xl" />)}
      {filtered.map((room) => { const state = status(room); return <Link to={`/rooms/${encodeURIComponent(room.name)}`} key={room.name} className="group"><Card className="h-full gap-4 transition-shadow hover:shadow-md"><CardHeader><div className="flex items-start justify-between gap-3"><div><CardTitle className="text-xl">{room.room_number}</CardTitle><CardDescription>{room.category_label}{room.floor ? ` · Piso ${room.floor}` : ""}</CardDescription></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${state.tone}`}>{state.text}</span></div></CardHeader><CardContent><p className="min-h-5 truncate text-sm text-muted-foreground">{room.guest_label || room.arrival_label || "Sin huésped activo"}</p><div className="mt-4 flex flex-wrap gap-1.5">{room.cleaning_status !== "Clean" && <Badge variant="outline">Limpieza: {room.cleaning_status}</Badge>}{room.work && <Badge variant="secondary">{room.task_count + room.maintenance_count + room.ticket_count} tareas</Badge>}{room.departure && <Badge variant="outline">Salida</Badge>}</div></CardContent></Card></Link> })}
    </div>
    {board && filtered.length === 0 && <p className="rounded-xl border border-dashed border-border p-12 text-center text-sm text-muted-foreground">No hay habitaciones que coincidan con la búsqueda.</p>}
    {board && <p className="text-xs text-muted-foreground">Actualizado: {new Date(board.checked_at).toLocaleString("es-NI")}</p>}
  </div>
}

function RoomView({ property }: { property: Property }) {
  const { room } = useParams()
  const [data, setData] = useState<RoomDetail | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    if (!room) return
    const controller = new AbortController()
    setData(null)
    setError("")
    call<RoomDetail>("room_snapshot", { property_name: property.name, room }, controller.signal)
      .then(setData)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property.name, room])
  if (error) return <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>
  if (!data) return <Skeleton className="h-80 rounded-xl" />
  const state = status(data.room)
  return <div className="space-y-6">
    <Link to="/rooms" className="text-sm font-medium text-primary hover:underline">← Habitaciones</Link>
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm text-muted-foreground">{data.room.category_label}</p><h1 className="text-3xl font-semibold">Habitación {data.room.room_number}</h1></div><span className={`rounded-full px-3 py-1.5 text-sm font-semibold ${state.tone}`}>{state.text}</span></div>
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Estancia actual</CardTitle></CardHeader><CardContent>{data.current ? <div className="space-y-2 text-sm"><p className="font-semibold">{data.current.guest_label || "Huésped registrado"}</p><p>Entrada: {new Date(data.current.starts_at).toLocaleString("es-NI")}</p><p>Salida: {new Date(data.current.ends_at).toLocaleString("es-NI")}</p>{data.current.account_balances?.map((balance) => <p key={balance.currency}>Saldo: {balance.outstanding.toLocaleString("es-NI", { style: "currency", currency: balance.currency })}</p>)}</div> : <p className="text-sm text-muted-foreground">Sin estancia activa.</p>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Próxima llegada</CardTitle></CardHeader><CardContent>{data.next_arrival ? <div className="space-y-2 text-sm"><p className="font-semibold">{data.next_arrival.guest_label || "Huésped registrado"}</p><p>Entrada: {new Date(data.next_arrival.starts_at).toLocaleString("es-NI")}</p><p>Salida: {new Date(data.next_arrival.ends_at).toLocaleString("es-NI")}</p></div> : <p className="text-sm text-muted-foreground">Sin llegada asignada.</p>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Trabajo de habitación</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p>Limpieza: <strong>{data.room.cleaning_status}</strong></p>{data.tasks.map((task) => <p key={task.name}>{task.kind} · {task.status}</p>)}{data.maintenance.map((order) => <p key={order.name}>{order.title} · {order.status}</p>)}{data.tickets.map((ticket) => <p key={ticket.name}>{ticket.subject} · {ticket.status}</p>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Características</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p>Capacidad: {data.details.capacity ?? "—"} · Camas: {data.details.beds ?? "—"}</p>{data.details.amenities && <p>{data.details.amenities}</p>}{data.details.description && <p className="text-muted-foreground">{data.details.description}</p>}</CardContent></Card>
    </div>
  </div>
}

export default function App() {
  const { base, detail, property, setProperty, error, loading } = useBootstrap()
  if (loading) return <div className="mx-auto max-w-5xl space-y-6 p-8"><Skeleton className="h-16" /><Skeleton className="h-32" /><Skeleton className="h-64" /></div>
  if (error && !base) return <div className="mx-auto max-w-lg p-8"><Card><CardHeader><CardTitle>No se pudo abrir Hospitality Suite</CardTitle><CardDescription>{error}</CardDescription></CardHeader><CardContent><Button asChild><a href="/login?redirect-to=/hospitality/app"><LogIn /> Iniciar sesión</a></Button></CardContent></Card></div>
  if (!base?.properties.length) return <div className="mx-auto max-w-lg p-8"><Card><CardHeader><CardTitle>Sin establecimientos asignados</CardTitle><CardDescription>Solicite acceso a un establecimiento para usar la aplicación.</CardDescription></CardHeader></Card></div>
  const selected = base.properties.find((item) => item.name === property) || base.properties[0]
  const showJournal = base.accounting_provider === "pms" && base.actions.includes("journal")
  const showChart = base.accounting_provider === "pms" && base.actions.includes("chart")
  const showCash = base.accounting_provider === "pms" && base.actions.includes("finance")
  return <Shell properties={base.properties} property={selected.name} setProperty={setProperty} showJournal={showJournal} showChart={showChart} showCash={showCash}>
    {error && <p role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <Routes>
      <Route path="/" element={<Dashboard property={selected} data={detail} />} />
      <Route path="/rooms" element={<RoomList property={selected} />} />
      <Route path="/rooms/:room" element={<RoomView property={selected} />} />
      {showJournal && <Route path="/journal" element={<Journal property={selected} />} />}
      {showChart && <Route path="/chart" element={<Chart property={selected} />} />}
      {showCash && <Route path="/cash" element={<Cash property={selected} canSetup={showChart} />} />}
      {showCash && <Route path="/receivables" element={<Receivables property={selected} canCreate={showChart} canCancel={base.actions.includes("approve")} />} />}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </Shell>
}
