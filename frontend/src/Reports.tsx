import { useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { pmsReportSections } from "./ReportSections"

type Options = { reports: { name: string; label: string }[];
  accounts: { name: string; account_code: string; account_name: string }[];
  parties: { name: string; party_name: string }[] }
type Report = { report: string; label: string; base_currency: string;
  from_date: string; to_date: string; offset: number; page_length: number;
  total_rows: number; columns: { key: string; label: string }[];
  rows: Record<string, unknown>[]; totals: Record<string, unknown> | Record<string, unknown>[] }
type Selection = { report_name: string; filters: Record<string, string> }

function summaryValues(totals: Report["totals"]) {
  if (Array.isArray(totals)) return totals.map((row) => Object.entries(row)
    .map(([key, value]) => `${key}: ${String(value)}`).join(" · "))
  return Object.entries(totals).map(([key, value]) => `${key}: ${String(value)}`)
}

export function Reports({ property }: { property: Property }) {
  const [searchParams] = useSearchParams()
  const report = pmsReportSections.find((item) => item.id === searchParams.get("section")) ||
    pmsReportSections[0]
  const reportName = report.id
  const [options, setOptions] = useState<Options | null>(null)
  const [fromDate, setFromDate] = useState(property.business_date)
  const [toDate, setToDate] = useState(property.business_date)
  const [account, setAccount] = useState("")
  const [party, setParty] = useState("")
  const [applied, setApplied] = useState<Selection | null>(null)
  const [data, setData] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => {
    setOptions(null); setData(null); setApplied(null); setError("")
    setFromDate(property.business_date); setToDate(property.business_date)
    call<Options>("pms_report_options", { property_name: property.name })
      .then(setOptions)
      .catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron cargar los reportes."))
  }, [property.name, property.business_date])
  useEffect(() => {
    setData(null); setApplied(null); setAccount(""); setParty("")
  }, [reportName])
  function selection(): Selection {
    const filters: Record<string, string> = { from_date: fromDate, to_date: toDate }
    if (account && ["trial_balance", "general_ledger", "sales"].includes(reportName)) filters.account = account
    if (party && ["general_ledger", "receivables", "sales"].includes(reportName)) filters.party = party
    return { report_name: reportName, filters }
  }
  async function load(chosen: Selection, offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      const result = await call<Report>("pms_report", {
        property_name: property.name, report_name: chosen.report_name,
        filters: JSON.stringify(chosen.filters), offset: String(offset), page_length: "100",
      })
      setApplied(chosen); setData(result)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo consultar el reporte.")
    } finally { setBusy(false) }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); void load(selection(), 0)
  }
  const exportUrl = applied ? `/api/method/hospitality_suite.api.pms_report_csv?${new URLSearchParams({
    property_name: property.name, report_name: applied.report_name,
    filters: JSON.stringify(applied.filters),
  })}` : ""
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Reportes PMS</p><h1 className="mt-1 text-3xl font-semibold">{report.label}</h1><p className="mt-2 text-sm text-muted-foreground">{report.description}. Los saldos en moneda original se muestran junto a sus importes en {property.currency}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {!options ? <Skeleton className="h-72 rounded-xl" /> : <>
      <Card><CardHeader><CardTitle>Consulta</CardTitle><CardDescription>El mayor conserva saldo acumulado anterior al período; la cartera calcula el pendiente a la fecha final.</CardDescription></CardHeader><CardContent><form onSubmit={submit} className="grid gap-3 md:grid-cols-3">
        <label className="space-y-1 text-sm">Desde<Input required type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} disabled={["trial_balance", "receivables"].includes(reportName)} /></label>
        <label className="space-y-1 text-sm">Hasta / fecha de corte<Input required type="date" min={["trial_balance", "receivables"].includes(reportName) ? undefined : fromDate} value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
        {["trial_balance", "general_ledger", "sales"].includes(reportName) && <label className="space-y-1 text-sm">Cuenta<select value={account} onChange={(event) => setAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Todas las cuentas</option>{options.accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select></label>}
        {["general_ledger", "receivables", "sales"].includes(reportName) && <label className="space-y-1 text-sm">Cliente<select value={party} onChange={(event) => setParty(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Todos los clientes</option>{options.parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label>}
        <div className="flex items-end gap-2"><Button disabled={busy}>Consultar</Button>{applied && <Button asChild variant="outline"><a href={exportUrl}>Descargar CSV</a></Button>}</div>
      </form></CardContent></Card>
      {data && <>
        <Card><CardHeader><CardTitle>{data.label}</CardTitle><CardDescription>{data.from_date} a {data.to_date} · {data.total_rows} filas · Establecimiento {property.property_name}</CardDescription></CardHeader><CardContent><div className="mb-4 flex flex-wrap gap-2">{summaryValues(data.totals).map((item) => <span key={item} className="rounded-md bg-secondary px-3 py-2 text-xs">{item}</span>)}</div><div className="overflow-x-auto"><table className="w-full min-w-max border-collapse text-left text-sm"><thead><tr>{data.columns.map((column) => <th key={column.key} className="border-b px-3 py-2 font-semibold">{column.label}</th>)}</tr></thead><tbody>{data.rows.map((row, index) => <tr key={`${String(row.name || row.journal || row.account || index)}-${index}`} className="border-b">{data.columns.map((column) => <td key={column.key} className="px-3 py-2 align-top">{row[column.key] == null ? "—" : String(row[column.key])}</td>)}</tr>)}</tbody></table>{!data.rows.length && <p className="py-6 text-sm text-muted-foreground">Sin registros para estos filtros.</p>}</div><div className="mt-4 flex items-center justify-between text-sm"><span>Mostrando {data.total_rows ? data.offset + 1 : 0}–{Math.min(data.offset + data.rows.length, data.total_rows)} de {data.total_rows}</span><span className="flex gap-2"><Button variant="outline" disabled={busy || data.offset === 0 || !applied} onClick={() => applied && void load(applied, Math.max(0, data.offset - 100))}>Anterior</Button><Button variant="outline" disabled={busy || data.offset + data.rows.length >= data.total_rows || !applied} onClick={() => applied && void load(applied, data.offset + 100)}>Siguiente</Button></span></div></CardContent></Card>
      </>}
    </>}
  </div>
}
