import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { creditSections } from "./CreditSections"

type PartyCredit = { party: string; party_name: string; active: boolean;
  status: string; credit_authorized: boolean; limit: string;
  receivable: string; unbilled: string; overdue: string; exposure: string;
  available: string; credit_days: number; credit_valid_until: string | null;
  credit_reason: string; modified: string }
type Overview = { currency: string; property_credit_enabled: boolean;
  property_modified: string; total: number; offset: number; page_length: number;
  rows: PartyCredit[] }

const labels: Record<string, string> = {
  "Not Authorized": "Sin autorización vigente", Overdue: "Vencido",
  "Over Limit": "Sobre el límite", Available: "Disponible",
}

export function Credit({ property, canApprove }: { property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = creditSections.find((item) => item.id === searchParams.get("section")) || creditSections[0]
  const requestedOffset = Number(searchParams.get("offset") || 0)
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0
  const selected = searchParams.get("party") || ""
  const [data, setData] = useState<Overview | null>(null)
  const [authorized, setAuthorized] = useState(false)
  const [limit, setLimit] = useState("")
  const [days, setDays] = useState("30")
  const [validUntil, setValidUntil] = useState("")
  const [reason, setReason] = useState("")
  const [policyReason, setPolicyReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const refresh = useCallback(async () => {
    setData(await call<Overview>("pms_credit_overview",
      { property_name: property.name, offset: String(offset), page_length: "50" }))
  }, [property.name, offset])
  useEffect(() => {
    if (!searchParams.has("section") || creditSections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", creditSections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  useEffect(() => {
    setData(null); setError(""); setNotice("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar el crédito."))
  }, [refresh])
  const party = data?.rows.find((row) => row.party === selected)

  useEffect(() => {
    if (!party) return
    setAuthorized(Boolean(party.credit_authorized))
    setLimit(party.limit || "0.00")
    setDays(String(party.credit_days ?? 30))
    setValidUntil(party.credit_valid_until || "")
    setReason("")
  }, [party?.party, party?.modified])

  function selectParty(name: string) {
    const next = new URLSearchParams(searchParams)
    next.set("section", "terms")
    if (name) next.set("party", name)
    else next.delete("party")
    setSearchParams(next)
    setError("")
  }

  function changePage(nextOffset: number) {
    const next = new URLSearchParams(searchParams)
    next.set("section", "payers")
    next.delete("party")
    if (nextOffset) next.set("offset", String(nextOffset))
    else next.delete("offset")
    setSearchParams(next)
  }

  async function updatePolicy() {
    if (!data || !canApprove || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_credit_policy", {
        allow_credit: !data.property_credit_enabled, modified: data.property_modified,
        reason: policyReason.trim(),
      }, crypto.randomUUID())
      await refresh(); setPolicyReason("")
      setNotice("Política de crédito actualizada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la política.") }
    finally { setBusy(false) }
  }

  async function updateTerms(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!party || !canApprove || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "pms_credit_terms", {
        party: party.party, modified: party.modified, credit_authorized: authorized,
        credit_limit: limit, credit_days: Number(days),
        credit_valid_until: validUntil || null, reason: reason.trim(),
      }, crypto.randomUUID())
      await refresh(); setReason("")
      setNotice(`Condiciones de ${party.party_name} actualizadas.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron guardar las condiciones.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1><p className="mt-1 text-sm text-muted-foreground">Crédito PMS · La exposición suma cuentas abiertas y cargos pendientes del establecimiento.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data && !error && <Skeleton className="h-96 w-full" />}
    {data && <>
      {section.id === "policy" && <Card><CardHeader><CardTitle>Política del establecimiento</CardTitle><CardDescription>{data.property_credit_enabled ? "Salidas a crédito habilitadas" : "Salidas a crédito deshabilitadas"}</CardDescription></CardHeader><CardContent className="space-y-3">
        {canApprove && <><Input minLength={8} maxLength={500} value={policyReason} onChange={(event) => setPolicyReason(event.target.value)} placeholder="Motivo del cambio de política (8 a 500 caracteres)" /><Button disabled={busy || policyReason.trim().length < 8} onClick={updatePolicy}>{data.property_credit_enabled ? "Deshabilitar crédito" : "Habilitar crédito"}</Button></>}
      </CardContent></Card>}
      {section.id === "payers" && <Card><CardHeader><CardTitle>Pagadores</CardTitle><CardDescription>{data.total} registrados · {data.currency}</CardDescription></CardHeader><CardContent className="space-y-2">
          {data.rows.map((row) => <button key={row.party} type="button" disabled={busy} onClick={() => selectParty(row.party)} className={`w-full rounded-lg border p-3 text-left text-sm hover:bg-muted ${selected === row.party ? "border-primary bg-secondary" : "border-border"}`}><strong>{row.party_name}</strong><span className="block text-muted-foreground">{labels[row.status] || row.status} · Exposición {data.currency} {row.exposure} / límite {row.limit}</span></button>)}
          {!data.rows.length && <p className="text-sm text-muted-foreground">No hay pagadores en esta página.</p>}
          <div className="flex items-center justify-between pt-2"><Button variant="outline" disabled={busy || offset === 0} onClick={() => changePage(Math.max(0, offset - data.page_length))}>Anterior</Button><span className="text-xs text-muted-foreground">{data.total ? offset + 1 : 0}–{Math.min(offset + data.rows.length, data.total)} de {data.total}</span><Button variant="outline" disabled={busy || offset + data.page_length >= data.total} onClick={() => changePage(offset + data.page_length)}>Siguiente</Button></div>
        </CardContent></Card>}
      {section.id === "terms" && <><Card><CardHeader><CardTitle>Seleccionar pagador</CardTitle><CardDescription>Seleccione un pagador de esta página para revisar o editar sus condiciones.</CardDescription></CardHeader><CardContent><select value={party?.party || ""} onChange={(event) => selectParty(event.target.value)} className="h-9 w-full max-w-2xl rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione un pagador</option>{data.rows.map((row) => <option key={row.party} value={row.party}>{row.party_name} · {labels[row.status] || row.status}</option>)}</select></CardContent></Card>
        {party ? <Card><CardHeader><CardTitle>{party.party_name}</CardTitle><CardDescription>{party.active ? labels[party.status] || party.status : "Pagador inactivo"}</CardDescription></CardHeader><CardContent className="space-y-4 text-sm">
          <div className="grid gap-2 sm:grid-cols-2"><p>Cuentas por cobrar: {data.currency} {party.receivable}</p><p>Cargos pendientes: {data.currency} {party.unbilled}</p><p>Vencido: {data.currency} {party.overdue}</p><p>Disponible: {data.currency} {party.available}</p></div>
          {canApprove && <form onSubmit={updateTerms} className="grid gap-3 sm:grid-cols-2"><label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} /> Autorizar crédito para este pagador</label><label className="space-y-1"><span>Límite ({data.currency})</span><Input required type="number" min={authorized ? "0.01" : "0"} step="0.01" value={limit} onChange={(event) => setLimit(event.target.value)} /></label><label className="space-y-1"><span>Plazo de pago (días)</span><Input required type="number" min="0" max="365" step="1" value={days} onChange={(event) => setDays(event.target.value)} /></label><label className="space-y-1 sm:col-span-2"><span>Autorización válida hasta (opcional)</span><Input type="date" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} /></label><label className="space-y-1 sm:col-span-2"><span>Motivo</span><Input required minLength={8} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label><Button className="sm:col-span-2" disabled={busy || !party.active}>Guardar condiciones</Button></form>}
          {party.credit_reason && <p className="text-muted-foreground">Último motivo registrado: {party.credit_reason}</p>}
        </CardContent></Card> : <Card><CardContent className="py-8 text-sm text-muted-foreground">Seleccione un pagador para revisar sus condiciones.</CardContent></Card>}</>}
    </>}
  </div>
}
