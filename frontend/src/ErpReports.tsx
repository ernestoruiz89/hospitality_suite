import { useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { erpReportSections, erpReportsInSection } from "./ReportSections"
import { AuditDetailPanel, type AuditSelection } from "./AuditDetailPanel"

type Catalog = { reports: string[]; labels: Record<string, string>;
  values: Record<string, string>; can_export: boolean }
type Choice = { name: string; label?: string; room_number?: string;
  category_name?: string; mode_of_payment?: string; currency?: string;
  warehouse_name?: string; full_name?: string; property_label?: string }
type Options = { filters: string[]; date_fields: { value: string; label: string }[];
  date_field: string; note: string; statuses: string[]; kinds: string[];
  rooms: Choice[]; categories: Choice[]; shifts: Choice[]; stays: Choice[];
  methods: Choice[]; warehouses: Choice[]; users: Choice[]; channels: string[] }
type ReportPage = { rows: (Record<string, unknown> & { _display?: Record<string, string> })[];
  columns: string[]; offset: number; page_length: number; total: number; has_more: boolean }
type Applied = { name: string; filters: Record<string, string> }

const PAGE_LENGTH = 50
const FILTER_LABELS: Record<string, string> = {
  room: "Habitación", category: "Categoría", shift: "Turno", stay: "Estancia",
  method: "Medio de pago", warehouse: "Almacén", user: "Usuario",
  assigned_to: "Responsable", channel: "Canal", status: "Estado",
  kind: "Tipo", item: "Artículo", purpose: "Propósito de inventario",
  adjustment_type: "Tipo de ajuste", group_by: "Agrupar por",
}
const GROUPS = ["room", "category", "item", "channel", "property"]
const PURPOSES = ["Stock", "Purchase", "Adjustment", "Sale"]

function choices(key: string, options: Options): { value: string; label: string }[] | null {
  const fromRows = (rows: Choice[], label: (row: Choice) => string) =>
    rows.map((row) => ({ value: row.name, label: label(row) }))
  if (key === "room") return fromRows(options.rooms, (row) => row.room_number || row.name)
  if (key === "category") return fromRows(options.categories, (row) => row.category_name || row.name)
  if (key === "shift") return fromRows(options.shifts, (row) => row.label || row.name)
  if (key === "stay") return fromRows(options.stays, (row) => row.label || row.name)
  if (key === "method") return fromRows(options.methods, (row) =>
    `${row.mode_of_payment || row.name} · ${row.currency || ""}`)
  if (key === "warehouse") return fromRows(options.warehouses, (row) => row.warehouse_name || row.name)
  if (key === "user" || key === "assigned_to") return fromRows(options.users,
    (row) => row.full_name || row.name)
  if (key === "channel") return options.channels.map((value) => ({ value, label: value }))
  if (key === "status") return options.statuses.filter(Boolean).map((value) => ({ value, label: value }))
  if (key === "kind") return options.kinds.filter(Boolean).map((value) => ({ value, label: value }))
  if (key === "purpose") return PURPOSES.map((value) => ({ value, label: value }))
  if (key === "group_by") return GROUPS.map((value) => ({ value, label: FILTER_LABELS[value] || value }))
  return null
}

function shown(row: ReportPage["rows"][number], key: string, catalog: Catalog): string {
  const display = row._display?.[key]
  if (display !== undefined && display !== null) return String(display)
  const value = row[key]
  if (value === undefined || value === null || value === "") return "—"
  if (typeof value === "object") return JSON.stringify(value)
  return catalog.values[String(value)] || String(value)
}

export function ErpReports({ property }: { property: Property }) {
  const [searchParams] = useSearchParams()
  const section = erpReportSections.find((item) => item.id === searchParams.get("section")) ||
    erpReportSections[0]
  const requestedReport = searchParams.get("report")
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [name, setName] = useState("")
  const [options, setOptions] = useState<Options | null>(null)
  const [fromDate, setFromDate] = useState(property.business_date)
  const [toDate, setToDate] = useState(property.business_date)
  const [fromTime, setFromTime] = useState(`${property.business_date}T00:00`)
  const [toTime, setToTime] = useState(`${property.business_date}T23:59`)
  const [dateField, setDateField] = useState("")
  const [detailLevel, setDetailLevel] = useState("operational")
  const [values, setValues] = useState<Record<string, string>>({})
  const [applied, setApplied] = useState<Applied | null>(null)
  const [page, setPage] = useState<ReportPage | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [auditSelection, setAuditSelection] = useState<AuditSelection | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setCatalog(null); setName(""); setOptions(null); setPage(null); setApplied(null)
    setError(""); setFromDate(property.business_date); setToDate(property.business_date)
    setFromTime(`${property.business_date}T00:00`)
    setToTime(`${property.business_date}T23:59`)
    call<Catalog>("erp_report_catalog", { property_name: property.name }, controller.signal)
      .then(setCatalog)
      .catch((issue: unknown) => { if (!controller.signal.aborted)
        setError(issue instanceof Error ? issue.message : "No se pudieron cargar los reportes.") })
    return () => controller.abort()
  }, [property.name, property.business_date])

  useEffect(() => {
    if (!catalog) return
    const reports = erpReportsInSection(catalog.reports, section.id)
    setName((current) => requestedReport && reports.includes(requestedReport)
      ? requestedReport : reports.includes(current) ? current : reports[0] || "")
  }, [catalog, section.id, requestedReport])

  useEffect(() => {
    if (!name) return
    const controller = new AbortController()
    setOptions(null); setPage(null); setApplied(null); setValues({})
    setDetailLevel("operational"); setError("")
    call<Options>("report_options", { property_name: property.name, report_name: name },
      controller.signal)
      .then((result) => { setOptions(result); setDateField(result.date_field) })
      .catch((issue: unknown) => { if (!controller.signal.aborted)
        setError(issue instanceof Error ? issue.message : "No se pudieron cargar los filtros.") })
    return () => controller.abort()
  }, [property.name, name])

  useEffect(() => {
    setAuditSelection(null)
  }, [property.name, name])


  function selection(): Applied {
    const filters: Record<string, string> = { detail_level: detailLevel }
    if (name === "Disponibilidad") {
      filters.starts_at = fromTime.replace("T", " ")
      filters.ends_at = toTime.replace("T", " ")
    } else {
      filters.from_date = fromDate
      filters.to_date = toDate
      filters.date_field = dateField || options?.date_field || "creation"
    }
    for (const [key, value] of Object.entries(values)) if (value.trim()) filters[key] = value.trim()
    return { name, filters }
  }

  async function load(chosen: Applied, offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      const result = await call<ReportPage>("report_page", {
        property_name: property.name, report_name: chosen.name,
        filters: JSON.stringify(chosen.filters), offset: String(offset),
        page_length: String(PAGE_LENGTH),
      })
      setApplied(chosen); setPage(result)
      setAuditSelection(null)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo consultar el reporte.")
    } finally { setBusy(false) }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (name === "Disponibilidad" && fromTime >= toTime) {
      setError("La hora final debe ser posterior a la inicial."); return
    }
    if (name !== "Disponibilidad" && fromDate > toDate) {
      setError("La fecha final debe ser igual o posterior a la inicial."); return
    }
    void load(selection(), 0)
  }

  const exportUrl = (format: "xlsx" | "pdf") => applied
    ? `/api/method/hospitality_suite.api.export_report?${new URLSearchParams({
        property_name: property.name, report_name: applied.name,
        filters: JSON.stringify(applied.filters), file_format: format,
      })}` : ""

  const availableReports = catalog ? erpReportsInSection(catalog.reports, section.id) : []
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Reportes ERPNext</p><h1 className="mt-1 text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Operación y contabilidad del establecimiento {property.property_name}. Los reportes respetan su ámbito y las monedas registradas.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {!catalog ? <Skeleton className="h-72 rounded-xl" /> : <>
      <Card><CardHeader><CardTitle>Consulta</CardTitle><CardDescription>{options?.note || "Seleccione un reporte y ajuste sus filtros."}</CardDescription></CardHeader><CardContent>
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-3">
          <label className="space-y-1 text-sm">Reporte<select value={name} onChange={(event) => setName(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">{availableReports.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          {options && <>
            {name === "Disponibilidad" ? <>
              <label className="space-y-1 text-sm">Desde<Input required type="datetime-local" value={fromTime} onChange={(event) => setFromTime(event.target.value)} /></label>
              <label className="space-y-1 text-sm">Hasta<Input required type="datetime-local" value={toTime} onChange={(event) => setToTime(event.target.value)} /></label>
            </> : <>
              <label className="space-y-1 text-sm">Desde<Input required type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
              <label className="space-y-1 text-sm">Hasta<Input required type="date" min={fromDate} value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
              <label className="space-y-1 text-sm">Fecha usada<select value={dateField || options.date_field} onChange={(event) => setDateField(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">{options.date_fields.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            </>}
            {options.filters.filter((key) => key !== "detail_level").map((key) => {
              const listed = choices(key, options)
              return <label key={key} className="space-y-1 text-sm">{FILTER_LABELS[key] || catalog.labels[key] || key}{listed
                ? <select value={values[key] || ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Todos</option>{listed.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
                : <Input value={values[key] || ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} placeholder="Filtrar por referencia" />}</label>
            })}
            <label className="space-y-1 text-sm">Presentación<select value={detailLevel} onChange={(event) => setDetailLevel(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="operational">Operativa</option><option value="technical">Referencias técnicas</option></select></label>
            <div className="flex items-end gap-2"><Button disabled={busy || !name}>Consultar</Button>{catalog.can_export && applied && <><Button asChild variant="outline"><a href={exportUrl("xlsx")}>Excel</a></Button><Button asChild variant="outline"><a href={exportUrl("pdf")}>PDF</a></Button></>}</div>
          </>}
        </form>
        {!availableReports.length && <p className="mt-3 text-sm text-muted-foreground">No hay reportes disponibles en este grupo.</p>}
      </CardContent></Card>
      {page && <Card><CardHeader><CardTitle>{applied?.name}</CardTitle><CardDescription>{page.total} registros · Página de {PAGE_LENGTH} · {property.property_name}</CardDescription></CardHeader><CardContent>
        <div className="overflow-x-auto"><table className="w-full min-w-max border-collapse text-left text-sm"><thead><tr>{page.columns.map((key) => <th key={key} className="border-b px-3 py-2 font-semibold">{catalog.labels[key] || key}</th>)}{applied?.name === "Auditoría" && <th className="border-b px-3 py-2 font-semibold">Detalle</th>}</tr></thead><tbody>{page.rows.map((row, index) => <tr key={`${String(row.name || index)}-${index}`} className="border-b">{page.columns.map((key) => <td key={key} className="max-w-96 px-3 py-2 align-top">{shown(row, key, catalog)}</td>)}{applied?.name === "Auditoría" && <td className="px-3 py-2 align-top"><Button size="sm" variant="outline" disabled={typeof row.name !== "string"} onClick={() => setAuditSelection({ name: String(row.name) })}>Ver cambio</Button></td>}</tr>)}</tbody></table>{!page.rows.length && <p className="py-6 text-sm text-muted-foreground">Sin registros para estos filtros.</p>}</div>
        <div className="mt-4 flex items-center justify-between text-sm"><span>Mostrando {page.total ? page.offset + 1 : 0}–{page.offset + page.rows.length} de {page.total}</span><div className="flex gap-2"><Button variant="outline" disabled={busy || page.offset === 0 || !applied} onClick={() => applied && void load(applied, Math.max(0, page.offset - PAGE_LENGTH))}>Anterior</Button><Button variant="outline" disabled={busy || !page.has_more || !applied} onClick={() => applied && void load(applied, page.offset + PAGE_LENGTH)}>Siguiente</Button></div></div>
      </CardContent></Card>}
      {applied?.name === "Auditoría" && auditSelection && <AuditDetailPanel key={`${property.name}:${auditSelection.name}`} propertyName={property.name} selection={auditSelection} onClose={() => setAuditSelection(null)} />}
    </>}
  </div>
}
