import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, uploadPrivateEvidence, type Property } from "./api"
import { availableRoomWorkSections, type RoomWorkAccess } from "./RoomWorkSections"

type Room = { name: string; room_number: string; active: boolean; cleaning_status: string }
type Task = { name: string; room: string; kind: string; priority: string;
  status: "Pending" | "In Progress" | "Inspection"; assigned_to: string | null;
  checklist: Record<string, boolean>; notes: string | null; modified: string }
type Order = { name: string; room: string | null; title: string; kind: string;
  status: "Open" | "In Progress"; starts_at: string; ends_at: string | null;
  blocks_room: boolean; until_reopened: boolean; notes: string | null;
  evidence: string | null; modified: string }
type Block = { name: string; room: string; reason: string; starts_at: string;
  ends_at: string; note: string | null; modified: string }
type Incident = { name: string; room: string; kind: "Damage" | "Lost Property";
  description: string; status: "Open" | "Resolved"; evidence: string | null;
  resolution: string | null; resolved_by: string | null; resolved_at: string | null;
  created_at: string; modified: string }
type IncidentPage = { status: "Open" | "Resolved"; total: number;
  offset: number; has_more: boolean; rows: Incident[] }
type PartsBoard = { order: string; status: "Open" | "In Progress" | "Completed";
  modified: string; cost: string; provider: "pms" | "erpnext";
  warehouses: { name: string; warehouse_name: string }[]; warehouse: string;
  total: number; offset: number; has_more: boolean; can_approve: boolean;
  products: { name: string; product_name: string; quantity: number;
    has_expense_account?: boolean }[];
  parts: { item: string; item_label: string; quantity: number;
    stock_entry: string; cost: number; status: "Issued" | "Returned" }[] }
type LinenDirection = "Send" | "Receive" | "Loss"
type LinenBoard = { configured: boolean; provider: "pms" | "erpnext";
  operating_warehouse: string | null; laundry_warehouse: string | null;
  stock_warehouse: string | null; direction: LinenDirection;
  products: { name: string; product_name: string; quantity: number;
    expense_account?: string | null }[];
  total: number; offset: number; has_more: boolean;
  history: { name: string; room: string; item: string; quantity: number;
    linen_direction: LinenDirection | null; description: string;
    stock_entry: string; created_at: string }[];
  history_total: number; history_offset: number; history_has_more: boolean }
type Snapshot = { time_zone: string; inspection_required: boolean;
  can: RoomWorkAccess;
  rooms: Room[]; tasks: Task[]; maintenance: Order[]; room_blocks: Block[] }

const checklistLabels: Record<string, string> = {
  "baño": "Baño", cama: "Cama", minibar: "Minibar", superficies: "Superficies",
}
const taskStatus: Record<Task["status"], string> = {
  Pending: "Pendiente", "In Progress": "En proceso", Inspection: "Inspección",
}

export function RoomOperations({ property, provider }: {
  property: Property; provider: "pms" | "erpnext" }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const preferredRoom = searchParams.get("room") || ""
  const [data, setData] = useState<Snapshot | null>(null)
  const visibleSections = data ? availableRoomWorkSections(data.can) : []
  const section = visibleSections.find((item) => item.id === searchParams.get("section")) || visibleSections[0]
  const linenDirection: LinenDirection = section?.id === "linen-receive" ? "Receive" :
    section?.id === "linen-loss" ? "Loss" : "Send"
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [checklists, setChecklists] = useState<Record<string, Record<string, boolean>>>({})
  const [taskNotes, setTaskNotes] = useState<Record<string, string>>({})
  const [cleanRoom, setCleanRoom] = useState("")
  const [cleanKind, setCleanKind] = useState("Stay")
  const [cleanPriority, setCleanPriority] = useState("Normal")
  const [cleanNotes, setCleanNotes] = useState("")
  const [orderRoom, setOrderRoom] = useState("")
  const [orderTitle, setOrderTitle] = useState("")
  const [orderKind, setOrderKind] = useState("Corrective")
  const [orderStart, setOrderStart] = useState("")
  const [orderEnd, setOrderEnd] = useState("")
  const [orderUntil, setOrderUntil] = useState(false)
  const [orderBlocks, setOrderBlocks] = useState(true)
  const [orderNotes, setOrderNotes] = useState("")
  const [blockRoom, setBlockRoom] = useState("")
  const [blockReason, setBlockReason] = useState("House Use")
  const [blockStart, setBlockStart] = useState("")
  const [blockEnd, setBlockEnd] = useState("")
  const [blockNote, setBlockNote] = useState("")
  const [releaseReasons, setReleaseReasons] = useState<Record<string, string>>({})
  const [incidentRoom, setIncidentRoom] = useState("")
  const [incidentKind, setIncidentKind] = useState<Incident["kind"]>("Damage")
  const [incidentDescription, setIncidentDescription] = useState("")
  const [resolutions, setResolutions] = useState<Record<string, string>>({})
  const [incidentPage, setIncidentPage] = useState<IncidentPage | null>(null)
  const [incidentStatus, setIncidentStatus] = useState<"Open" | "Resolved">("Open")
  const [incidentOffset, setIncidentOffset] = useState(0)
  const [incidentRoomFilter, setIncidentRoomFilter] = useState("")
  const [incidentSearchInput, setIncidentSearchInput] = useState("")
  const [incidentSearch, setIncidentSearch] = useState("")
  const [incidentRevision, setIncidentRevision] = useState(0)
  const [partsOrder, setPartsOrder] = useState("")
  const [partsBoard, setPartsBoard] = useState<PartsBoard | null>(null)
  const [partsWarehouse, setPartsWarehouse] = useState("")
  const [partsSearchInput, setPartsSearchInput] = useState("")
  const [partsSearch, setPartsSearch] = useState("")
  const [partsOffset, setPartsOffset] = useState(0)
  const [partsRevision, setPartsRevision] = useState(0)
  const [partItem, setPartItem] = useState("")
  const [partQuantity, setPartQuantity] = useState("1")
  const [partReturnReasons, setPartReturnReasons] = useState<Record<string, string>>({})
  const [linenBoard, setLinenBoard] = useState<LinenBoard | null>(null)
  const [linenRoom, setLinenRoom] = useState("")
  const [linenItem, setLinenItem] = useState("")
  const [linenQuantity, setLinenQuantity] = useState("1")
  const [linenReason, setLinenReason] = useState("")
  const [linenSearchInput, setLinenSearchInput] = useState("")
  const [linenSearch, setLinenSearch] = useState("")
  const [linenOffset, setLinenOffset] = useState(0)
  const [linenHistoryOffset, setLinenHistoryOffset] = useState(0)
  const [linenRevision, setLinenRevision] = useState(0)
  const linenRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const partRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const incidentRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const resolutionRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const evidenceRequest = useRef<{ fingerprint: string; url: string; key: string } | null>(null)
  const canViewIncidents = section?.id === "incidents" && Boolean(data?.can.incident || data?.can.inspect)

  const refresh = useCallback(async () => {
    const result = await call<Snapshot>(provider === "pms" ?
      "pms_room_operations" : "erp_room_operations", { property_name: property.name })
    setData(result)
    setChecklists(Object.fromEntries(result.tasks.map((task) => [task.name, task.checklist])))
    setTaskNotes(Object.fromEntries(result.tasks.map((task) => [task.name, task.notes || ""])))
  }, [property.name, provider])
  useEffect(() => {
    setData(null); setError(""); setNotice("")
    setCleanRoom(preferredRoom); setOrderRoom(preferredRoom); setBlockRoom(preferredRoom)
    setIncidentRoom(preferredRoom); setResolutions({})
    setIncidentPage(null); setIncidentStatus("Open"); setIncidentOffset(0)
    setIncidentRoomFilter(preferredRoom); setIncidentSearchInput(""); setIncidentSearch("")
    setPartsOrder(""); setPartsBoard(null); setPartsWarehouse("")
    setPartsSearchInput(""); setPartsSearch(""); setPartsOffset(0)
    setPartItem(""); setPartQuantity("1"); setPartReturnReasons({})
    setLinenBoard(null); setLinenRoom(preferredRoom)
    setLinenItem(""); setLinenQuantity("1"); setLinenReason("")
    setLinenSearchInput(""); setLinenSearch(""); setLinenOffset(0)
    setLinenHistoryOffset(0); linenRequest.current = null
    partRequest.current = null
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar el trabajo de habitaciones."))
  }, [refresh, preferredRoom])
  useEffect(() => {
    if (!data || !section) return
    const next = new URLSearchParams(searchParams)
    if (preferredRoom && !data.rooms.some((room) => room.name === preferredRoom)) next.delete("room")
    if (next.has("section") && next.get("section") !== section.id) next.set("section", section.id)
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true })
  }, [data, section, preferredRoom, searchParams, setSearchParams])
  useEffect(() => {
    if (data && incidentRoomFilter && !data.rooms.some((room) => room.name === incidentRoomFilter)) {
      setIncidentRoomFilter("")
    }
  }, [data, incidentRoomFilter])
  useEffect(() => {
    if (!canViewIncidents) { setIncidentPage(null); return }
    const controller = new AbortController()
    setIncidentPage(null)
    call<IncidentPage>("room_incident_page", { property_name: property.name,
      status: incidentStatus, offset: String(incidentOffset), page_length: "25",
      search: incidentSearch, room: incidentRoomFilter,
    }, controller.signal).then(setIncidentPage).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las novedades.")
    })
    return () => controller.abort()
  }, [canViewIncidents, property.name, incidentStatus, incidentOffset,
    incidentSearch, incidentRoomFilter, incidentRevision])
  useEffect(() => {
    if (!partsOrder || section?.id !== "maintenance") { setPartsBoard(null); return }
    const controller = new AbortController()
    setPartsBoard(null)
    call<PartsBoard>("maintenance_parts_board", { property_name: property.name,
      order: partsOrder, warehouse: partsWarehouse, search: partsSearch,
      offset: String(partsOffset), page_length: "25" }, controller.signal)
      .then(setPartsBoard).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los repuestos.")
      })
    return () => controller.abort()
  }, [property.name, section?.id, partsOrder, partsWarehouse, partsSearch, partsOffset, partsRevision])
  useEffect(() => {
    if (!data?.can.clean || !section?.id.startsWith("linen")) { setLinenBoard(null); return }
    const controller = new AbortController()
    setLinenBoard(null)
    call<LinenBoard>("linen_board", { property_name: property.name,
      direction: linenDirection, search: linenSearch, offset: String(linenOffset),
      page_length: "25", history_offset: String(linenHistoryOffset),
    }, controller.signal).then(setLinenBoard).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar la ropa del hotel.")
    })
    return () => controller.abort()
  }, [property.name, data?.can.clean, section?.id, linenDirection, linenSearch,
    linenOffset, linenHistoryOffset, linenRevision])
  useEffect(() => {
    if (!section?.id.startsWith("linen")) return
    setLinenItem(""); setLinenQuantity("1"); setLinenReason("")
    setLinenSearchInput(""); setLinenSearch("")
    setLinenOffset(0); setLinenHistoryOffset(0)
    linenRequest.current = null
  }, [section?.id])
  const roomLabel = (name: string | null) => data?.rooms.find((room) => room.name === name)?.room_number || name || "Sin habitación"

  async function schedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "schedule_cleaning", { room: cleanRoom, kind: cleanKind,
        priority: cleanPriority, notes: cleanNotes.trim() }, crypto.randomUUID())
      await refresh(); setCleanNotes(""); setNotice("Tarea de limpieza programada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo programar la limpieza.") }
    finally { setBusy(false) }
  }

  async function updateTask(task: Task, status: "In Progress" | "Inspection" | "Completed") {
    if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "cleaning", { task: task.name, modified: task.modified,
        status, notes: taskNotes[task.name] || "",
        ...(status === "Inspection" || status === "Completed" ? {
          checklist: checklists[task.name] || task.checklist } : {}) }, crypto.randomUUID())
      await refresh(); setNotice(`Limpieza ${task.name}: ${status === "Completed" ? "completada" : status === "Inspection" ? "en inspección" : "en proceso"}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la limpieza.") }
    finally { setBusy(false) }
  }

  async function createOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "maintenance", { room: orderRoom, title: orderTitle.trim(),
        kind: orderKind, starts_at: orderStart, ends_at: orderUntil ? null : orderEnd,
        until_reopened: orderUntil, blocks_room: orderBlocks, notes: orderNotes.trim() },
        crypto.randomUUID())
      await refresh(); setOrderTitle(""); setOrderStart(""); setOrderEnd(""); setOrderNotes("")
      setNotice("Orden de mantenimiento creada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear la orden.") }
    finally { setBusy(false) }
  }

  async function updateOrder(order: Order, status: "In Progress" | "Completed") {
    if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "maintenance", { order: order.name,
        modified: order.modified, status }, crypto.randomUUID())
      await refresh(); setNotice(status === "Completed" ? "Mantenimiento completado; revise la limpieza de reapertura." : "Mantenimiento en proceso.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la orden.") }
    finally { setBusy(false) }
  }

  async function createBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "room_block", { room: blockRoom, reason: blockReason,
        starts_at: blockStart, ends_at: blockEnd, note: blockNote.trim() }, crypto.randomUUID())
      await refresh(); setBlockStart(""); setBlockEnd(""); setBlockNote("")
      setNotice("Habitación bloqueada para el intervalo indicado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo bloquear la habitación.") }
    finally { setBusy(false) }
  }

  async function releaseBlock(block: Block) {
    if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "room_unblock", { block: block.name,
        modified: block.modified, reason: (releaseReasons[block.name] || "").trim() },
        crypto.randomUUID())
      await refresh(); setNotice("Bloqueo liberado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo liberar el bloqueo.") }
    finally { setBusy(false) }
  }

  async function createIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      const payload = { room: incidentRoom, kind: incidentKind,
        description: incidentDescription.trim() }
      const fingerprint = JSON.stringify([property.name, payload])
      if (incidentRequest.current?.fingerprint !== fingerprint) {
        incidentRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "incident", payload, incidentRequest.current.key)
      incidentRequest.current = null
      setIncidentDescription(""); setNotice("Novedad registrada.")
      setIncidentStatus("Open"); setIncidentOffset(0)
      setIncidentRevision((value) => value + 1)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la novedad.") }
    finally { setBusy(false) }
  }

  async function resolveIncident(incident: Incident) {
    const resolution = (resolutions[incident.name] || "").trim()
    if (busy || !resolution) return
    setBusy(true); setError("")
    try {
      const payload = { incident: incident.name, modified: incident.modified,
        resolve: true, resolution }
      const fingerprint = JSON.stringify([property.name, payload])
      if (resolutionRequest.current?.fingerprint !== fingerprint) {
        resolutionRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "incident", payload, resolutionRequest.current.key)
      resolutionRequest.current = null
      setResolutions((current) => { const next = { ...current }; delete next[incident.name]; return next })
      setNotice(`Novedad ${incident.name} resuelta.`)
      setIncidentOffset(0)
      setIncidentRevision((value) => value + 1)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo resolver la novedad.") }
    finally { setBusy(false) }
  }

  async function attachEvidence(kind: "incident" | "maintenance", row: Incident | Order,
    file: File) {
    if (busy) return
    setBusy(true); setError("")
    try {
      const fingerprint = JSON.stringify([property.name, kind, row.name, row.modified,
        file.name, file.size, file.lastModified])
      if (evidenceRequest.current?.fingerprint !== fingerprint) {
        const url = await uploadPrivateEvidence(kind === "incident" ? "HS Incident" :
          "HS Maintenance Order", row.name, file)
        evidenceRequest.current = { fingerprint, url, key: crypto.randomUUID() }
      }
      const request = evidenceRequest.current
      await execute(property.name, kind, kind === "incident" ? {
        incident: row.name, modified: row.modified, evidence: request.url,
      } : { order: row.name, modified: row.modified, evidence: request.url }, request.key)
      evidenceRequest.current = null
      setNotice("Evidencia privada adjuntada.")
      if (kind === "incident") setIncidentRevision((value) => value + 1)
      else await refresh().catch(() => setError("Evidencia adjuntada. Actualice la vista para verla."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo adjuntar la evidencia.") }
    finally { setBusy(false) }
  }

  function openParts(order: Order) {
    setError(""); setPartsBoard(null); setPartsOrder(order.name)
    setPartsWarehouse(""); setPartsSearchInput(""); setPartsSearch("")
    setPartsOffset(0); setPartItem(""); setPartQuantity("1")
    setPartReturnReasons({}); partRequest.current = null
    setPartsRevision((value) => value + 1)
  }

  async function issuePart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !partsBoard || !partItem || !partsBoard.warehouse) return
    setBusy(true); setError("")
    try {
      const payload = { order: partsBoard.order, modified: partsBoard.modified,
        ...(provider === "pms" ? { warehouse: partsBoard.warehouse } : {}),
        parts: [{ item: partItem, quantity: partQuantity }] }
      const fingerprint = JSON.stringify([property.name, payload])
      if (partRequest.current?.fingerprint !== fingerprint) {
        partRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "maintenance_parts", payload, partRequest.current.key)
      partRequest.current = null
      setPartItem(""); setPartQuantity("1")
      setPartsRevision((value) => value + 1)
      setNotice("Repuesto entregado a mantenimiento y costo registrado.")
      await refresh().catch(() => setError("El repuesto se entregó. Actualice la vista para ver la orden."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el repuesto.") }
    finally { setBusy(false) }
  }

  async function returnPart(stockEntry: string) {
    const reason = (partReturnReasons[stockEntry] || "").trim()
    if (busy || !partsBoard || !reason) return
    setBusy(true); setError("")
    try {
      const payload = { order: partsBoard.order, modified: partsBoard.modified,
        return_entry: stockEntry, reason }
      const fingerprint = JSON.stringify([property.name, payload])
      if (partRequest.current?.fingerprint !== fingerprint) {
        partRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "maintenance_parts", payload, partRequest.current.key)
      partRequest.current = null
      setPartReturnReasons((current) => { const next = { ...current }; delete next[stockEntry]; return next })
      setPartsRevision((value) => value + 1)
      setNotice("Repuesto devuelto al inventario y costo revertido.")
      await refresh().catch(() => setError("La devolución se registró. Actualice la vista para ver la orden."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el repuesto.") }
    finally { setBusy(false) }
  }

  async function moveLinen(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !linenBoard?.configured || !linenRoom || !linenItem) return
    setBusy(true); setError("")
    try {
      const payload = { room: linenRoom, item: linenItem,
        quantity: linenQuantity, direction: linenDirection,
        reason: linenReason.trim() }
      const fingerprint = JSON.stringify([property.name, payload])
      if (linenRequest.current?.fingerprint !== fingerprint) {
        linenRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "linen", payload, linenRequest.current.key)
      linenRequest.current = null
      setLinenItem(""); setLinenQuantity("1"); setLinenReason("")
      setLinenOffset(0); setLinenHistoryOffset(0)
      setLinenRevision((value) => value + 1)
      setNotice(linenDirection === "Send" ? "Ropa enviada a lavandería." :
        linenDirection === "Receive" ? "Ropa recibida de lavandería." :
          "Pérdida de ropa registrada con su costo.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el movimiento de ropa.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Trabajo de habitaciones</h1>
      <p className="mt-1 text-sm text-muted-foreground">Limpieza, novedades, mantenimiento y bloqueos del establecimiento. Horas en {data?.time_zone || property.time_zone}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-80 rounded-xl" /> : <>
      {section && <div className="border-b border-border pb-3"><h2 className="text-xl font-semibold">{section.label}</h2><p className="text-sm text-muted-foreground">{section.description}</p></div>}
      {section?.id === "cleaning-new" && data.can.inspect && <Card><CardHeader><CardTitle>Programar limpieza</CardTitle><CardDescription>Una habitación solo puede tener una tarea pendiente.</CardDescription></CardHeader><CardContent><form onSubmit={schedule} className="grid gap-3 sm:grid-cols-4">
        <select required value={cleanRoom} onChange={(event) => setCleanRoom(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Habitación</option>{data.rooms.map((room) => <option key={room.name} value={room.name}>{room.room_number} · {room.cleaning_status}</option>)}</select>
        <select value={cleanKind} onChange={(event) => setCleanKind(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Stay">Durante estancia</option><option value="Departure">Salida</option><option value="Deep">Profunda</option></select>
        <select value={cleanPriority} onChange={(event) => setCleanPriority(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Normal">Normal</option><option value="High">Alta</option><option value="Urgent">Urgente</option></select>
        <Input maxLength={500} placeholder="Indicaciones" value={cleanNotes} onChange={(event) => setCleanNotes(event.target.value)} />
        <Button disabled={busy} className="sm:col-span-4">Crear tarea</Button>
      </form></CardContent></Card>}
      {section?.id === "cleaning" && (data.can.clean || data.can.inspect) && <Card><CardHeader><CardTitle>Limpieza pendiente ({data.tasks.length})</CardTitle><CardDescription>{data.inspection_required ? "La habitación requiere inspección antes de quedar limpia." : "Complete la lista antes de finalizar o enviar a inspección."}</CardDescription></CardHeader><CardContent className="space-y-4">
        {data.tasks.map((task) => { const checks = checklists[task.name] || task.checklist; const complete = Object.keys(checks).length > 0 && Object.values(checks).every(Boolean); return <div key={task.name} className="space-y-3 rounded-lg border border-border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><span><strong>Habitación {roomLabel(task.room)}</strong> · {task.kind} · {taskStatus[task.status]} · Prioridad {task.priority}</span><Link className="text-primary underline" to={`/rooms/${encodeURIComponent(task.room)}`}>Ver habitación</Link></div>
          {task.assigned_to && <p className="text-xs text-muted-foreground">Responsable: {task.assigned_to}</p>}
          {task.status === "In Progress" && <div className="flex flex-wrap gap-3">{Object.keys(checks).map((key) => <label key={key} className="flex items-center gap-2"><input type="checkbox" checked={Boolean(checks[key])} onChange={(event) => setChecklists((current) => ({ ...current, [task.name]: { ...checks, [key]: event.target.checked } }))} />{checklistLabels[key] || key}</label>)}</div>}
          {(task.status === "In Progress" || task.status === "Inspection") && <Input maxLength={500} placeholder={task.status === "Inspection" ? "Motivo de corrección si devuelve la tarea" : "Notas de limpieza"} value={taskNotes[task.name] || ""} onChange={(event) => setTaskNotes((current) => ({ ...current, [task.name]: event.target.value }))} />}
          <div className="flex flex-wrap gap-2">{task.status === "Pending" && data.can.clean && <Button disabled={busy} onClick={() => void updateTask(task, "In Progress")}>Iniciar</Button>}
            {task.status === "In Progress" && data.can.clean && <><Button disabled={busy || !complete} onClick={() => void updateTask(task, "Inspection")}>Enviar a inspección</Button>{!data.inspection_required && <Button variant="outline" disabled={busy || !complete} onClick={() => void updateTask(task, "Completed")}>Completar</Button>}</>}
            {task.status === "Inspection" && data.can.inspect && <><Button disabled={busy} onClick={() => void updateTask(task, "Completed")}>Aprobar limpieza</Button><Button variant="outline" disabled={busy || !(taskNotes[task.name] || "").trim()} onClick={() => void updateTask(task, "In Progress")}>Devolver para corrección</Button></>}
          </div>
        </div> })}
        {!data.tasks.length && <p className="text-sm text-muted-foreground">No hay limpiezas pendientes.</p>}
      </CardContent></Card>}
      {section?.id.startsWith("linen") && data.can.clean && <Card><CardHeader><CardTitle>{section.label}</CardTitle><CardDescription>{section.id === "linen" ? "Cada movimiento conserva su referencia de inventario." : section.description}</CardDescription></CardHeader><CardContent className="space-y-4">
        {!linenBoard ? <Skeleton className="h-36 rounded-lg" /> : <>
          {section.id !== "linen" && !linenBoard.configured && <p role="status" className="text-sm text-muted-foreground">Configure los almacenes de ropa{provider === "pms" ? " y la cuenta temporal en Configuración" : " en Contabilidad ERPNext"} antes de mover existencias.</p>}
          {section.id !== "linen" && linenBoard.configured && <>
            <p className="text-sm text-muted-foreground">Operativo: {linenBoard.operating_warehouse} · Lavandería: {linenBoard.laundry_warehouse}</p>
            <div className="flex flex-wrap gap-3">
              <form onSubmit={(event) => { event.preventDefault(); setLinenOffset(0); setLinenSearch(linenSearchInput.trim()) }} className="flex items-end gap-2"><label className="space-y-1 text-sm"><span>Buscar ropa con existencias</span><Input maxLength={100} value={linenSearchInput} onChange={(event) => setLinenSearchInput(event.target.value)} placeholder="Código o nombre" /></label><Button type="submit" variant="outline">Buscar</Button></form>
            </div>
            <p className="text-xs text-muted-foreground">Existencias en {linenBoard.stock_warehouse}: {linenBoard.total} producto(s)</p>
            <div className="max-h-60 space-y-2 overflow-y-auto">{linenBoard.products.map((product) => <div key={product.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span>{product.product_name} · {product.name}<span className="block text-xs text-muted-foreground">Disponible: {product.quantity}{linenDirection === "Loss" && provider === "pms" && !product.expense_account ? " · Falta cuenta de gasto" : ""}</span></span><Button type="button" size="sm" variant="outline" disabled={linenDirection === "Loss" && provider === "pms" && !product.expense_account} onClick={() => setLinenItem(product.name)}>{linenItem === product.name ? "Seleccionado" : "Seleccionar"}</Button></div>)}{!linenBoard.products.length && <p className="text-sm text-muted-foreground">Sin existencias para este filtro.</p>}</div>
            {linenBoard.total > 25 && <div className="flex items-center justify-between gap-3 text-sm"><span>{linenBoard.offset + 1}–{linenBoard.offset + linenBoard.products.length} de {linenBoard.total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={!linenOffset} onClick={() => setLinenOffset(Math.max(0, linenOffset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!linenBoard.has_more} onClick={() => setLinenOffset(linenOffset + 25)}>Siguiente</Button></div></div>}
            <form onSubmit={moveLinen} className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm"><span>Habitación de referencia</span><select required value={linenRoom} onChange={(event) => setLinenRoom(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione habitación</option>{data.rooms.map((room) => <option key={room.name} value={room.name}>{room.room_number}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.000001" step="0.000001" value={linenQuantity} onChange={(event) => setLinenQuantity(event.target.value)} /></label>
              <p className="text-sm sm:col-span-2">Producto: <strong>{linenItem || "Seleccione uno de la lista"}</strong></p>
              <label className="space-y-1 text-sm sm:col-span-2"><span>{linenDirection === "Loss" ? "Motivo de la pérdida" : "Motivo o referencia (opcional)"}</span><Input required={linenDirection === "Loss"} maxLength={500} value={linenReason} onChange={(event) => setLinenReason(event.target.value)} /></label>
              <Button disabled={busy || !linenItem || (linenDirection === "Loss" && !linenReason.trim())} className="sm:col-span-2">{linenDirection === "Send" ? "Registrar envío" : linenDirection === "Receive" ? "Registrar recepción" : "Registrar pérdida"}</Button>
            </form>
          </>}
          {section.id === "linen" && <div className="space-y-2"><h3 className="font-medium">Historial de ropa ({linenBoard.history_total})</h3>{linenBoard.history.map((row) => <div key={row.name} className="rounded-lg border border-border p-3 text-sm"><p><strong>{row.linen_direction === "Send" ? "Envío" : row.linen_direction === "Receive" ? "Recepción" : row.linen_direction === "Loss" ? "Pérdida" : "Movimiento"}</strong> · Habitación {roomLabel(row.room)} · {row.item} · {row.quantity} unidad(es)</p><p className="text-xs text-muted-foreground">{row.name} · {row.created_at} · Inventario {row.stock_entry}</p><p>{row.description}</p></div>)}{!linenBoard.history.length && <p className="text-sm text-muted-foreground">Aún no hay movimientos de ropa.</p>}</div>}
          {section.id === "linen" && linenBoard.history_total > 25 && <div className="flex items-center justify-between gap-3 text-sm"><span>{linenBoard.history_offset + 1}–{linenBoard.history_offset + linenBoard.history.length} de {linenBoard.history_total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={!linenHistoryOffset} onClick={() => setLinenHistoryOffset(Math.max(0, linenHistoryOffset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!linenBoard.history_has_more} onClick={() => setLinenHistoryOffset(linenHistoryOffset + 25)}>Siguiente</Button></div></div>}
        </>}
      </CardContent></Card>}
      {section?.id === "incidents-new" && data.can.incident && <Card><CardHeader><CardTitle>Registrar novedad</CardTitle><CardDescription>Documente un daño u objeto encontrado en una habitación.</CardDescription></CardHeader><CardContent><form onSubmit={createIncident} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Habitación</span><select required value={incidentRoom} onChange={(event) => setIncidentRoom(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione habitación</option>{data.rooms.map((room) => <option key={room.name} value={room.name}>{room.room_number}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Tipo de novedad</span><select value={incidentKind} onChange={(event) => setIncidentKind(event.target.value as Incident["kind"])} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="Damage">Daño</option><option value="Lost Property">Objeto encontrado</option></select></label>
          <label className="space-y-1 text-sm sm:col-span-2"><span>Descripción</span><Input required maxLength={1000} value={incidentDescription} onChange={(event) => setIncidentDescription(event.target.value)} /></label>
          <Button disabled={busy || !incidentDescription.trim()} className="sm:col-span-2">Registrar novedad</Button>
        </form></CardContent></Card>}
      {section?.id === "incidents" && (data.can.incident || data.can.inspect) && <Card><CardHeader><CardTitle>Daños y objetos encontrados ({incidentPage?.total ?? "…"})</CardTitle><CardDescription>Consulte y resuelva las novedades registradas.</CardDescription></CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <label className="space-y-1 text-sm"><span>Estado</span><select value={incidentStatus} onChange={(event) => { setIncidentStatus(event.target.value as "Open" | "Resolved"); setIncidentOffset(0) }} className="block h-9 rounded-md border border-border bg-white px-2"><option value="Open">Abiertas</option><option value="Resolved">Resueltas</option></select></label>
          <label className="space-y-1 text-sm"><span>Habitación</span><select value={incidentRoomFilter} onChange={(event) => { setIncidentRoomFilter(event.target.value); setIncidentOffset(0) }} className="block h-9 rounded-md border border-border bg-white px-2"><option value="">Todas</option>{data.rooms.map((room) => <option key={room.name} value={room.name}>{room.room_number}</option>)}</select></label>
          <form onSubmit={(event) => { event.preventDefault(); setIncidentOffset(0); setIncidentSearch(incidentSearchInput.trim()) }} className="flex items-end gap-2"><label className="space-y-1 text-sm"><span>Buscar</span><Input maxLength={100} placeholder="Código o descripción" value={incidentSearchInput} onChange={(event) => setIncidentSearchInput(event.target.value)} /></label><Button type="submit" variant="outline">Buscar</Button></form>
        </div>
        {!incidentPage && <Skeleton className="h-24 rounded-lg" />}
        {incidentPage?.rows.map((incident) => <div key={incident.name} className="space-y-2 rounded-lg border border-border p-3 text-sm">
          <p><strong>{incident.kind === "Damage" ? "Daño" : "Objeto encontrado"}</strong> · Habitación {roomLabel(incident.room)} · {incident.name} · {incident.created_at}</p>
          <p className="whitespace-pre-wrap">{incident.description}</p>
          <div className="flex flex-wrap items-center gap-3">{incident.evidence && <a className="text-primary underline" href={incident.evidence} target="_blank" rel="noopener noreferrer">Ver evidencia privada</a>}
            {incident.status === "Open" && data.can.incident && <label className="text-sm">Adjuntar evidencia <input type="file" accept="image/*,.pdf,.txt" disabled={busy} className="ml-2 max-w-60 text-xs" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void attachEvidence("incident", incident, file) }} /></label>}
          </div>
          {incident.status === "Resolved" && <p className="text-muted-foreground">Resuelta {incident.resolved_at || ""} por {incident.resolved_by || "Gerencia"}. {incident.resolution}</p>}
          {incident.status === "Open" && data.can.incident && data.can.inspect && <div className="flex flex-wrap gap-2"><Input maxLength={1000} placeholder="Resolución o constancia de entrega" value={resolutions[incident.name] || ""} onChange={(event) => setResolutions((current) => ({ ...current, [incident.name]: event.target.value }))} className="min-w-64 flex-1" /><Button disabled={busy || !(resolutions[incident.name] || "").trim()} onClick={() => void resolveIncident(incident)}>Resolver</Button></div>}
        </div>)}
        {incidentPage && !incidentPage.rows.length && <p className="text-sm text-muted-foreground">No hay novedades {incidentStatus === "Open" ? "abiertas" : "resueltas"} para estos filtros.</p>}
        {incidentPage && incidentPage.total > 0 && <div className="flex items-center justify-between gap-3 text-sm"><span>{incidentPage.offset + 1}–{incidentPage.offset + incidentPage.rows.length} de {incidentPage.total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={incidentOffset === 0} onClick={() => setIncidentOffset(Math.max(0, incidentOffset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!incidentPage.has_more} onClick={() => setIncidentOffset(incidentOffset + 25)}>Siguiente</Button></div></div>}
      </CardContent></Card>}
      {section?.id === "maintenance-new" && data.can.maintain && <Card><CardHeader><CardTitle>Nueva orden de mantenimiento</CardTitle><CardDescription>Una orden que bloquea habitación reduce la disponibilidad hasta que se complete y se programe la limpieza de reapertura.</CardDescription></CardHeader><CardContent><form onSubmit={createOrder} className="grid gap-3 sm:grid-cols-2">
          <select required value={orderRoom} onChange={(event) => setOrderRoom(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Habitación</option>{data.rooms.map((room) => <option key={room.name} value={room.name}>{room.room_number}</option>)}</select>
          <Input required maxLength={140} placeholder="Título de la orden" value={orderTitle} onChange={(event) => setOrderTitle(event.target.value)} />
          <select value={orderKind} onChange={(event) => setOrderKind(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Corrective">Correctivo</option><option value="Preventive">Preventivo</option></select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={orderBlocks} onChange={(event) => setOrderBlocks(event.target.checked)} />Bloquear disponibilidad</label>
          <label className="space-y-1 text-sm"><span>Inicio</span><Input required type="datetime-local" value={orderStart} onChange={(event) => setOrderStart(event.target.value)} /></label>
          {!orderUntil && <label className="space-y-1 text-sm"><span>Fin previsto</span><Input required type="datetime-local" value={orderEnd} onChange={(event) => setOrderEnd(event.target.value)} /></label>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={orderUntil} onChange={(event) => setOrderUntil(event.target.checked)} />Hasta reapertura autorizada</label>
          <Input maxLength={500} placeholder="Notas" value={orderNotes} onChange={(event) => setOrderNotes(event.target.value)} />
          <Button disabled={busy} className="sm:col-span-2">Crear orden</Button>
        </form></CardContent></Card>}
      {section?.id === "maintenance" && (data.can.maintain || data.can.inspect) && <Card><CardHeader><CardTitle>Mantenimiento ({data.maintenance.length})</CardTitle><CardDescription>Consulte órdenes abiertas, registre repuestos y complete el trabajo autorizado.</CardDescription></CardHeader><CardContent className="space-y-4">
        {data.maintenance.map((order) => <div key={order.name} className="space-y-2 rounded-lg border border-border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3"><span><strong>{order.title}</strong> · Habitación {roomLabel(order.room)} · {order.status === "Open" ? "Abierta" : "En proceso"}<span className="block text-muted-foreground">{order.kind} · {order.blocks_room ? "Bloquea disponibilidad" : "Sin bloqueo"} · {order.until_reopened ? "Hasta reapertura" : `${order.starts_at} → ${order.ends_at}`}</span></span><div className="flex gap-2">{order.status === "Open" && data.can.maintain && <Button variant="outline" disabled={busy} onClick={() => void updateOrder(order, "In Progress")}>Iniciar</Button>}{data.can.maintain && <Button variant="outline" disabled={busy} onClick={() => openParts(order)}>Repuestos</Button>}{data.can.inspect && <Button disabled={busy} onClick={() => void updateOrder(order, "Completed")}>Completar</Button>}</div></div>
          <div className="flex flex-wrap items-center gap-3">{order.evidence && <a className="text-primary underline" href={order.evidence} target="_blank" rel="noopener noreferrer">Ver evidencia privada</a>}
            {data.can.maintain && <label>Adjuntar evidencia <input type="file" accept="image/*,.pdf,.txt" disabled={busy} className="ml-2 max-w-60 text-xs" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void attachEvidence("maintenance", order, file) }} /></label>}
          </div>
        </div>)}
        {!data.maintenance.length && <p className="text-sm text-muted-foreground">No hay órdenes abiertas.</p>}
      </CardContent></Card>}
      {section?.id === "maintenance" && data.can.maintain && partsOrder && <Card><CardHeader><CardTitle>Repuestos de {partsOrder}</CardTitle><CardDescription>Salida de inventario al costo promedio y devolución al costo original.</CardDescription></CardHeader><CardContent className="space-y-4">
        <Button type="button" variant="outline" onClick={() => { setPartsOrder(""); setPartsBoard(null) }}>Cerrar repuestos</Button>
        {!partsBoard ? <Skeleton className="h-28 rounded-lg" /> : <>
          <p className="text-sm">Costo aplicado a la orden: <strong>{property.currency} {partsBoard.cost}</strong></p>
          <div className="space-y-2">{partsBoard.parts.map((part) => <div key={part.stock_entry} className="space-y-2 rounded-lg border border-border p-3 text-sm"><p><strong>{part.item_label}</strong> · {part.quantity} unidad(es) · {property.currency} {part.cost} · {part.status === "Issued" ? "Entregado" : "Devuelto"}</p><p className="text-xs text-muted-foreground">Movimiento {part.stock_entry}</p>{part.status === "Issued" && partsBoard.can_approve && partsBoard.status !== "Completed" && <div className="flex flex-wrap gap-2"><Input maxLength={500} placeholder="Motivo de devolución" value={partReturnReasons[part.stock_entry] || ""} onChange={(event) => setPartReturnReasons((current) => ({ ...current, [part.stock_entry]: event.target.value }))} className="min-w-64 flex-1" /><Button type="button" variant="outline" disabled={busy || !(partReturnReasons[part.stock_entry] || "").trim()} onClick={() => void returnPart(part.stock_entry)}>Devolver a inventario</Button></div>}</div>)}{!partsBoard.parts.length && <p className="text-sm text-muted-foreground">La orden aún no tiene repuestos.</p>}</div>
          {partsBoard.status !== "Completed" && <div className="space-y-3 rounded-lg border border-border p-3">
            <label className="block space-y-1 text-sm"><span>Almacén de salida</span><select value={partsWarehouse || partsBoard.warehouse} onChange={(event) => { setPartsWarehouse(event.target.value); setPartsOffset(0); setPartItem("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione almacén</option>{partsBoard.warehouses.map((warehouse) => <option key={warehouse.name} value={warehouse.name}>{warehouse.warehouse_name}</option>)}</select></label>
            {!partsBoard.warehouses.length && <p className="text-sm text-muted-foreground">Configure un almacén de inventario antes de entregar repuestos.</p>}
            <form onSubmit={(event) => { event.preventDefault(); setPartsOffset(0); setPartsSearch(partsSearchInput.trim()) }} className="flex flex-wrap gap-2"><Input maxLength={100} placeholder="Buscar repuesto" value={partsSearchInput} onChange={(event) => setPartsSearchInput(event.target.value)} className="min-w-64 flex-1" /><Button type="submit" variant="outline">Buscar</Button></form>
            <div className="space-y-2">{partsBoard.products.map((product) => <div key={product.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span>{product.product_name} · {product.name}<span className="block text-xs text-muted-foreground">Existencia: {product.quantity}{partsBoard.provider === "pms" && !product.has_expense_account ? " · Falta cuenta de gasto" : ""}</span></span><Button type="button" size="sm" variant="outline" disabled={partsBoard.provider === "pms" && !product.has_expense_account} onClick={() => setPartItem(product.name)}>{partItem === product.name ? "Seleccionado" : "Seleccionar"}</Button></div>)}{!partsBoard.products.length && <p className="text-sm text-muted-foreground">No hay repuestos con existencias para estos filtros.</p>}</div>
            {partsBoard.total > 25 && <div className="flex items-center justify-between gap-2 text-sm"><span>{partsBoard.offset + 1}–{partsBoard.offset + partsBoard.products.length} de {partsBoard.total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={partsOffset === 0} onClick={() => setPartsOffset(Math.max(0, partsOffset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!partsBoard.has_more} onClick={() => setPartsOffset(partsOffset + 25)}>Siguiente</Button></div></div>}
            <form onSubmit={issuePart} className="flex flex-wrap items-end gap-2"><p className="min-w-48 flex-1 text-sm">Repuesto: <strong>{partItem || "Seleccione uno de la lista"}</strong></p><label className="space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="0.000001" step="0.000001" value={partQuantity} onChange={(event) => setPartQuantity(event.target.value)} className="w-32" /></label><Button disabled={busy || !partItem || !partsBoard.warehouse}>Registrar salida</Button></form>
          </div>}
        </>}
      </CardContent></Card>}
      {section?.id === "blocks-new" && data.can.block && <Card><CardHeader><CardTitle>Nuevo bloqueo de habitación</CardTitle><CardDescription>Reserve una habitación para uso interno, propietario, VIP u otro motivo durante un intervalo.</CardDescription></CardHeader><CardContent><form onSubmit={createBlock} className="grid gap-3 sm:grid-cols-2">
          <select required value={blockRoom} onChange={(event) => setBlockRoom(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Habitación</option>{data.rooms.filter((room) => room.active).map((room) => <option key={room.name} value={room.name}>{room.room_number}</option>)}</select>
          <select value={blockReason} onChange={(event) => setBlockReason(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="House Use">Uso interno</option><option value="VIP Hold">Retención VIP</option><option value="Owner">Propietario</option><option value="Maintenance">Mantenimiento</option><option value="Other">Otro</option></select>
          <label className="space-y-1 text-sm"><span>Inicio</span><Input required type="datetime-local" value={blockStart} onChange={(event) => setBlockStart(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Fin</span><Input required type="datetime-local" value={blockEnd} onChange={(event) => setBlockEnd(event.target.value)} /></label>
          <Input required={blockReason === "Other"} maxLength={500} placeholder="Motivo o indicaciones" value={blockNote} onChange={(event) => setBlockNote(event.target.value)} className="sm:col-span-2" />
          <Button disabled={busy} className="sm:col-span-2">Bloquear habitación</Button>
        </form></CardContent></Card>}
      {section?.id === "blocks" && data.can.block && <Card><CardHeader><CardTitle>Bloqueos de habitación ({data.room_blocks.length})</CardTitle><CardDescription>Consulte los bloqueos activos y libere una habitación con motivo.</CardDescription></CardHeader><CardContent className="space-y-4">
        {data.room_blocks.map((block) => <div key={block.name} className="space-y-2 rounded-lg border border-border p-3 text-sm"><p><strong>Habitación {roomLabel(block.room)}</strong> · {block.reason} · {block.starts_at} → {block.ends_at}</p>{block.note && <p className="text-muted-foreground">{block.note}</p>}<div className="flex flex-wrap gap-2"><Input maxLength={500} placeholder="Motivo de liberación" value={releaseReasons[block.name] || ""} onChange={(event) => setReleaseReasons((current) => ({ ...current, [block.name]: event.target.value }))} className="max-w-sm" /><Button variant="outline" disabled={busy || !(releaseReasons[block.name] || "").trim()} onClick={() => void releaseBlock(block)}>Liberar</Button></div></div>)}
        {!data.room_blocks.length && <p className="text-sm text-muted-foreground">No hay bloqueos activos.</p>}
      </CardContent></Card>}
    </>}
  </div>
}
