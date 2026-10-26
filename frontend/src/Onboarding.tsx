import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod } from "./api"

type Options = { provider: "pms" | "erpnext"; currencies: string[];
  organizations: { name: string; legal_name: string; base_currency: string; tax_regime: string }[];
  companies: { name: string; default_currency: string }[] }
type Created = { property: string }
const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"

export function Onboarding() {
  const [options, setOptions] = useState<Options | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [propertyName, setPropertyName] = useState("")
  const [entityChoice, setEntityChoice] = useState("new")
  const [legalName, setLegalName] = useState("")
  const [taxId, setTaxId] = useState("")
  const [taxRegime, setTaxRegime] = useState("General")
  const [company, setCompany] = useState("")
  const [currency, setCurrency] = useState("")
  const [mode, setMode] = useState("Hotel")
  const [timeZone, setTimeZone] = useState("America/Managua")
  const [closeTime, setCloseTime] = useState("06:00")
  const [businessDate, setBusinessDate] = useState("")
  const pending = useRef<{ payload: string; key: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    call<Options>("onboarding_options", {}, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setOptions(result)
        setCurrency((current) => current || (result.currencies.includes("NIO") ? "NIO" : result.currencies[0] || ""))
        if (result.provider === "erpnext" && result.companies.length) {
          setCompany(result.companies[0].name)
          setCurrency(result.companies[0].default_currency)
        }
      })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el alta inicial.")
      })
    return () => controller.abort()
  }, [])

  function chooseEntity(value: string) {
    setEntityChoice(value)
    const existing = options?.organizations.find((item) => item.name === value)
    if (existing) setCurrency(existing.base_currency)
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!options || busy) return
    setBusy(true); setError("")
    const data = { property_name: propertyName.trim(), mode, currency,
      time_zone: timeZone.trim(), close_time: closeTime,
      ...(businessDate ? { business_date: businessDate } : {}),
      ...(options.provider === "erpnext" ? { company } :
        entityChoice === "new" ? { new_organization: {
          legal_name: legalName.trim(), tax_id: taxId.trim(), tax_regime: taxRegime } } :
          { organization: entityChoice }),
    }
    const payload = JSON.stringify(data)
    if (pending.current?.payload !== payload) pending.current = { payload, key: crypto.randomUUID() }
    try {
      const result = await postMethod<Created>("create_property", {
        data, request_key: pending.current.key })
      localStorage.setItem("hospitality-suite-property", result.property)
      window.location.assign(`${import.meta.env.DEV ? "" : "/hospitality/app"}/setup`)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo crear el establecimiento.")
      setBusy(false)
    }
  }

  return <div className="mx-auto max-w-3xl space-y-6 p-4 lg:p-8">
    <div><h1 className="text-3xl font-semibold">Nuevo establecimiento</h1>
      <p className="mt-1 text-sm text-muted-foreground">Configure la entidad y la fecha operativa. Las cuentas y medios de cobro se añaden después.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {!options ? <Skeleton className="h-96" /> : <Card><CardHeader><CardTitle>Datos iniciales</CardTitle><CardDescription>{options.provider === "pms" ? "Libro contable propio de Hospitality Suite" : "Contabilidad de ERPNext"}</CardDescription></CardHeader><CardContent>
      <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2"><span>Nombre del establecimiento</span><Input required maxLength={140} value={propertyName} onChange={(event) => setPropertyName(event.target.value)} /></label>
        {options.provider === "pms" ? <>
          <label className="space-y-1 text-sm sm:col-span-2"><span>Entidad legal</span><select className={selectClass} value={entityChoice} onChange={(event) => chooseEntity(event.target.value)}><option value="new">Crear una entidad legal</option>{options.organizations.map((item) => <option key={item.name} value={item.name}>{item.legal_name} · {item.base_currency}</option>)}</select></label>
          {entityChoice === "new" && <>
            <label className="space-y-1 text-sm"><span>Nombre legal</span><Input required maxLength={140} value={legalName} onChange={(event) => setLegalName(event.target.value)} /></label>
            <label className="space-y-1 text-sm"><span>RUC o registro (opcional)</span><Input maxLength={140} value={taxId} onChange={(event) => setTaxId(event.target.value)} /></label>
            <label className="space-y-1 text-sm"><span>Régimen indicado por el usuario</span><select className={selectClass} value={taxRegime} onChange={(event) => setTaxRegime(event.target.value)}><option value="General">General</option><option value="Cuota Fija">Cuota fija</option></select></label>
          </>}
        </> : <label className="space-y-1 text-sm sm:col-span-2"><span>Compañía ERPNext</span><select required className={selectClass} value={company} onChange={(event) => { const selected = options.companies.find((item) => item.name === event.target.value); setCompany(event.target.value); if (selected) setCurrency(selected.default_currency) }}><option value="">Seleccione</option>{options.companies.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.default_currency}</option>)}</select></label>}
        <label className="space-y-1 text-sm"><span>Moneda base del establecimiento</span><select required className={selectClass} disabled={options.provider === "pms" && entityChoice !== "new"} value={currency} onChange={(event) => setCurrency(event.target.value)}>{options.currencies.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="space-y-1 text-sm"><span>Modalidad</span><select className={selectClass} value={mode} onChange={(event) => setMode(event.target.value)}><option value="Hotel">Por noche</option><option value="Por tiempo">Por tiempo</option><option value="Mixed">Mixta</option></select></label>
        <label className="space-y-1 text-sm"><span>Zona horaria IANA</span><Input required value={timeZone} onChange={(event) => setTimeZone(event.target.value)} /></label>
        <label className="space-y-1 text-sm"><span>Hora de corte diario</span><Input required type="time" value={closeTime} onChange={(event) => setCloseTime(event.target.value)} /></label>
        <label className="space-y-1 text-sm sm:col-span-2"><span>Fecha operativa inicial (opcional)</span><Input type="date" value={businessDate} onChange={(event) => setBusinessDate(event.target.value)} /><span className="text-xs text-muted-foreground">Si se omite, se calcula según la zona horaria y la hora de corte.</span></label>
        <Button disabled={busy || !currency || options.provider === "erpnext" && !company} className="sm:col-span-2">Crear establecimiento</Button>
      </form>
    </CardContent></Card>}
  </div>
}
