import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Download, FolderTree, Plus, Upload } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type ChartAccount, type ChartData, type CurrencySettings, type Property } from "./api"
import { chartSections } from "./ChartSections"

type Preview = { count: number; sha256: string; root_types: string[]; foreign_currencies: string[];
  sample: { account_code: string; account_name: string; account_currency: string }[] }
const ROOTS = ["Asset", "Liability", "Equity", "Income", "Expense"]
const ROOT_LABELS: Record<string, string> = { Asset: "Activo", Liability: "Pasivo", Equity: "Patrimonio", Income: "Ingreso", Expense: "Gasto" }

function orderedTree(accounts: ChartAccount[]) {
  const children = new Map<string, ChartAccount[]>()
  const known = new Set(accounts.map((account) => account.name))
  for (const account of accounts) {
    const parent = account.parent_account && known.has(account.parent_account) ? account.parent_account : ""
    children.set(parent, [...(children.get(parent) || []), account])
  }
  for (const list of children.values()) list.sort((a, b) => a.account_code.localeCompare(b.account_code, "es", { numeric: true }))
  const result: { account: ChartAccount; depth: number }[] = []
  const seen = new Set<string>()
  function walk(parent: string, depth: number) {
    for (const account of children.get(parent) || []) {
      if (seen.has(account.name)) continue
      seen.add(account.name)
      result.push({ account, depth })
      walk(account.name, depth + 1)
    }
  }
  walk("", 0)
  return result
}

async function base64File(file: File) {
  if (file.size > 1048576) throw new Error("El archivo debe tener hasta 1 MB.")
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ""
  for (let start = 0; start < bytes.length; start += 8192) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 8192))
  }
  return btoa(binary)
}

export function Chart({ property }: { property: Property }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = chartSections.find((item) => item.id === searchParams.get("section")) || chartSections[0]
  const [data, setData] = useState<ChartData | null>(null)
  const [settings, setSettings] = useState<CurrencySettings | null>(null)
  const [currencyCodes, setCurrencyCodes] = useState(property.currency)
  const [rateCurrency, setRateCurrency] = useState("")
  const [rateValue, setRateValue] = useState("")
  const [rateSource, setRateSource] = useState("")
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [accountCode, setAccountCode] = useState("")
  const [accountName, setAccountName] = useState("")
  const [root, setRoot] = useState("Asset")
  const [accountType, setAccountType] = useState("General")
  const [currency, setCurrency] = useState(property.currency)
  const [parent, setParent] = useState("")
  const [group, setGroup] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [encoded, setEncoded] = useState("")
  const [preview, setPreview] = useState<Preview | null>(null)

  const refresh = useCallback((signal?: AbortSignal) => call<ChartData>("pms_chart", { property_name: property.name }, signal).then(setData), [property.name])
  const refreshSettings = useCallback(async (signal?: AbortSignal) => {
    const result = await call<CurrencySettings>("pms_currency_settings", { property_name: property.name }, signal)
    setSettings(result)
    setCurrencyCodes(result.accepted_currencies.join(", "))
  }, [property.name])
  useEffect(() => {
    if (!searchParams.has("section") || chartSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", chartSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(""); setNotice(""); setCurrency(property.currency)
    setFile(null); setEncoded(""); setPreview(null)
    Promise.all([refresh(controller.signal), refreshSettings(controller.signal)])
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo consultar el catálogo.") })
    return () => controller.abort()
  }, [refresh, refreshSettings, property.currency])

  const tree = useMemo(() => orderedTree(data?.accounts || []), [data])
  const parentOptions = useMemo(() => (data?.accounts || []).filter((account) => account.root_type === root && account.is_group && account.active), [data, root])

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_account", {
        account_code: accountCode.trim(), account_name: accountName.trim(), root_type: root,
        account_type: accountType, account_currency: currency, parent_account: parent || null,
        is_group: group ? 1 : 0, active: 1,
      }, crypto.randomUUID())
      await refresh()
      setAccountCode(""); setAccountName(""); setAccountType("General"); setParent(""); setGroup(false)
      setNotice("Cuenta creada.")
      setSearchParams({ section: "accounts" })
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo crear la cuenta.") }
    finally { setBusy(false) }
  }

  async function inspectFile() {
    if (!file || busy) return
    setBusy(true); setError(""); setNotice(""); setPreview(null)
    try {
      const content = await base64File(file)
      const result = await postMethod<Preview>("pms_coa_preview", {
        property_name: property.name, file_name: file.name, content_base64: content,
      })
      setEncoded(content); setPreview(result)
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo leer el archivo.") }
    finally { setBusy(false) }
  }

  async function importFile() {
    if (!file || !preview || !encoded || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ count: number }>(property.name, "pms_coa_import", {
        file_name: file.name, content_base64: encoded, sha256: preview.sha256,
      }, crypto.randomUUID())
      await refresh()
      setFile(null); setEncoded(""); setPreview(null)
      setNotice(`${result.count} cuentas importadas.`)
      setSearchParams({ section: "accounts" })
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo importar el catálogo.") }
    finally { setBusy(false) }
  }

  async function exportFile() {
    setBusy(true); setError("")
    try {
      const result = await call<{ file_name: string; content_base64: string }>("pms_coa_export", { property_name: property.name })
      const binary = atob(result.content_base64)
      const blob = new Blob([Uint8Array.from(binary, (char) => char.charCodeAt(0))], { type: "text/csv;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url; link.download = result.file_name; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo exportar el catálogo.") }
    finally { setBusy(false) }
  }

  async function saveCurrencies() {
    if (busy) return
    const currencies = currencyCodes.split(",").map((code) => code.trim().toUpperCase()).filter(Boolean)
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_currencies", { currencies }, crypto.randomUUID())
      await refreshSettings()
      if (rateCurrency && !currencies.includes(rateCurrency)) setRateCurrency("")
      setNotice("Monedas habilitadas actualizadas.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudieron guardar las monedas.") }
    finally { setBusy(false) }
  }

  async function recordRate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_exchange_rate", {
        from_currency: rateCurrency, rate: rateValue, source: rateSource.trim(),
      }, crypto.randomUUID())
      await refreshSettings()
      setRateValue(""); setRateSource("")
      setNotice("Tipo de cambio registrado.")
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo guardar el tipo de cambio.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="flex items-center gap-3"><FolderTree className="text-primary" /><h1 className="text-3xl font-semibold tracking-tight">{section.label}</h1></div><p className="mt-2 text-sm text-muted-foreground">Contabilidad PMS · Cuentas del establecimiento y su moneda. Los asientos se reportan también en {property.currency}.</p></div>{section.id === "transfer" && <Button variant="outline" onClick={exportFile} disabled={busy || !data}><Download size={16} /> Exportar CSV ERPNext</Button>}</div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {((["accounts", "transfer"].includes(section.id) && !data) ||
      (section.id === "new" && (!data || !settings))) && !error && <Skeleton className="h-60 rounded-xl" />}
    {["currencies", "rates"].includes(section.id) && !settings && !error && <Skeleton className="h-60 rounded-xl" />}
    {section.id === "accounts" && data && <Card><CardHeader><CardTitle>Árbol contable</CardTitle><CardDescription>{data.accounts.length} cuentas. Las cuentas agrupadoras organizan el plan; solo las cuentas de movimiento reciben asientos.</CardDescription></CardHeader><CardContent className="space-y-1">
      {tree.map(({ account, depth }) => <div key={account.name} className="flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted" style={{ paddingLeft: `${12 + depth * 20}px` }}><span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">{account.account_code}</span><strong className={account.is_group ? "font-semibold" : "font-normal"}>{account.account_name}</strong>{account.is_group && <Badge variant="secondary">Grupo</Badge>}{!account.active && <Badge variant="outline">Inactiva</Badge>}<span className="ml-auto text-xs text-muted-foreground">{account.account_type === "General" ? ROOT_LABELS[account.root_type] : account.account_type} · {account.account_currency}</span></div>)}
      {tree.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">Cree las cuentas raíz o importe un catálogo de ERPNext.</p>}
    </CardContent></Card>}
    {section.id === "currencies" && settings && <Card><CardHeader><CardTitle>Monedas del establecimiento</CardTitle><CardDescription>La moneda base {property.currency} debe permanecer habilitada.</CardDescription></CardHeader><CardContent className="max-w-2xl space-y-3"><label className="block space-y-1 text-sm font-medium">Códigos separados por coma<Input value={currencyCodes} onChange={(event) => setCurrencyCodes(event.target.value)} placeholder={`${property.currency}, USD`} /></label><p className="text-xs text-muted-foreground">Disponibles: {settings.available_currencies.join(", ")}</p><Button type="button" variant="outline" disabled={busy} onClick={saveCurrencies}>Guardar monedas</Button></CardContent></Card>}
    {section.id === "rates" && settings && <Card><CardHeader><CardTitle>Tipos de cambio</CardTitle><CardDescription>Una unidad de la moneda seleccionada equivale al importe indicado en {property.currency}.</CardDescription></CardHeader><CardContent><form onSubmit={recordRate} className="grid max-w-2xl gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm font-medium">Moneda<select required value={rateCurrency} onChange={(event) => setRateCurrency(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione moneda</option>{settings.accepted_currencies.filter((code) => code !== property.currency).map((code) => <option key={code} value={code}>{code}</option>)}</select></label><label className="space-y-1 text-sm font-medium">Tipo de cambio<Input required type="number" min="0.000000001" step="any" value={rateValue} onChange={(event) => setRateValue(event.target.value)} /></label><label className="space-y-1 text-sm font-medium sm:col-span-2">Fuente aprobada<Input required maxLength={140} value={rateSource} onChange={(event) => setRateSource(event.target.value)} placeholder="Banco / tasa acordada" /></label><Button type="submit" disabled={busy || !rateCurrency} className="sm:col-span-2">Registrar tipo de cambio</Button>{settings.rates.slice(0, 5).map((rate) => <p key={rate.name} className="text-xs text-muted-foreground sm:col-span-2">{rate.from_currency} → {rate.to_currency}: {rate.rate} · {rate.effective_at} · {rate.source}</p>)}</form></CardContent></Card>}
      {section.id === "new" && data && settings && <Card><CardHeader><CardTitle>Nueva cuenta</CardTitle><CardDescription>Código único, naturaleza, cuenta superior y moneda fija. El código se exporta como Account Number.</CardDescription></CardHeader><CardContent><form onSubmit={createAccount} className="grid max-w-2xl gap-4 sm:grid-cols-2">
        <label className="space-y-1 text-sm font-medium">Código<Input required maxLength={40} value={accountCode} onChange={(event) => setAccountCode(event.target.value)} /></label>
        <label className="space-y-1 text-sm font-medium">Nombre<Input required maxLength={140} value={accountName} onChange={(event) => setAccountName(event.target.value)} /></label>
        <label className="space-y-1 text-sm font-medium">Naturaleza<select value={root} onChange={(event) => { setRoot(event.target.value); setParent("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{ROOTS.map((value) => <option key={value} value={value}>{ROOT_LABELS[value]}</option>)}</select></label>
        <label className="space-y-1 text-sm font-medium">Tipo<select value={accountType} onChange={(event) => setAccountType(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{(data?.account_types || ["General"]).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="space-y-1 text-sm font-medium">Cuenta superior<select value={parent} onChange={(event) => setParent(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta raíz</option>{parentOptions.map((account) => <option key={account.name} value={account.name}>{account.account_code} · {account.account_name}</option>)}</select></label>
        <label className="space-y-1 text-sm font-medium">Moneda<select value={currency} onChange={(event) => setCurrency(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">{(settings?.accepted_currencies || [property.currency]).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={group} onChange={(event) => setGroup(event.target.checked)} /> Cuenta agrupadora</label>
        <Button type="submit" disabled={busy || !data} className="sm:justify-self-end"><Plus size={16} /> Crear cuenta</Button>
      </form></CardContent></Card>}
      {section.id === "transfer" && data && <Card><CardHeader><CardTitle>Importar catálogo ERPNext</CardTitle><CardDescription>Acepta el archivo CSV, XLSX o XLS de ocho columnas del CoA Importer. La importación crea el catálogo inicial tras revisar la vista previa.</CardDescription></CardHeader><CardContent className="max-w-2xl space-y-4">
        <Input type="file" accept=".csv,.xlsx,.xls" onChange={(event) => { setFile(event.target.files?.[0] || null); setPreview(null); setEncoded("") }} />
        {file && <p className="text-xs text-muted-foreground">Archivo seleccionado: {file.name}</p>}
        <Button type="button" variant="outline" onClick={inspectFile} disabled={!file || busy}><Upload size={16} /> Revisar archivo</Button>
        {preview && <div className="space-y-2 rounded-lg border border-border p-4 text-sm"><p><strong>{preview.count} cuentas</strong> · {preview.root_types.map((item) => ROOT_LABELS[item]).join(", ")}</p><p>Monedas adicionales: {preview.foreign_currencies.join(", ") || "ninguna"}</p><div className="max-h-36 overflow-auto text-xs text-muted-foreground">{preview.sample.map((item) => <p key={item.account_code}>{item.account_code} · {item.account_name} · {item.account_currency}</p>)}</div><Button type="button" onClick={importFile} disabled={busy || !!data?.accounts.length}>Importar catálogo</Button>{!!data?.accounts.length && <p>La importación inicial requiere un catálogo vacío.</p>}</div>}
      </CardContent></Card>}
  </div>
}
