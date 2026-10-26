import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type StayRow = { name: string; guest_label: string; room_label: string;
  ends_at_local: string; modified: string }
type Balance = { pending: string; scheduled: string; outstanding: string; currency: string }
type Credit = { status: "Not Authorized" | "Overdue" | "Over Limit" | "Currency Review" | "Available";
  party_name: string; limit: string; exposure: string; overdue: string;
  property_credit_enabled: boolean; credit_authorized: boolean }
type Detail = { stay: string; modified: string; currency: string;
  folios: { name: string; label: string; customer: string; balance: Balance; credit: Credit | null }[];
  guarantees: { payment: string; available: string; currency: string }[];
  laundry_pending: number; services_pending: number; experiences_pending: number;
  inspection_required: boolean; inspected: boolean;
  timing: { amount: string; acceptance: string; explanation: string[]; kind: string } }

export function Departure({ property, provider, canInspect, canFinance, canApprove }: {
  property: Property; provider: "pms" | "erpnext"; canInspect: boolean; canFinance: boolean; canApprove: boolean
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [stays, setStays] = useState<StayRow[] | null>(null)
  const [selected, setSelected] = useState("")
  const [detail, setDetail] = useState<Detail | null>(null)
  const [folio, setFolio] = useState("")
  const [inspectionNotes, setInspectionNotes] = useState("")
  const [creditReason, setCreditReason] = useState("")
  const [overrideReason, setOverrideReason] = useState("")
  const [checkoutKey, setCheckoutKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const refresh = useCallback(async () => {
    const result = await call<{ stays: StayRow[] }>(provider === "pms" ?
      "pms_departure_snapshot" : "erp_departure_snapshot",
      { property_name: property.name })
    setStays(result.stays)
  }, [property.name, provider])
  const refreshDetail = useCallback(async (name: string, signal?: AbortSignal) => {
    const result = await call<Detail>(provider === "pms" ?
      "pms_departure_detail" : "erp_departure_detail",
      { property_name: property.name, stay: name }, signal)
    setDetail(result)
    setFolio((current) => result.folios.some((row) => row.name === current) ? current :
      result.folios.find((row) => row.name)?.name || "")
  }, [property.name, provider])
  useEffect(() => {
    setStays(null); setSelected(""); setDetail(null); setFolio("")
    setError(""); setNotice(""); setCheckoutKey(""); setCreditReason(""); setOverrideReason("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar las salidas."))
  }, [refresh])
  useEffect(() => {
    if (!stays || !location.state) return
    const target = (location.state as { stay?: { property: string; name: string } }).stay
    if (!target) return
    if (target.property !== property.name || !target.name) {
      setError("La estancia solicitada no pertenece a este establecimiento.")
      navigate("/departures", { replace: true, state: null })
      return
    }
    const controller = new AbortController()
    call<{ property: string; stay: string; status: string; guest_label: string;
      room_label: string; ends_at_local: string | null; modified: string }>(
      "stay_overview", { property_name: property.name, stay: target.name }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.stay !== target.name ||
            result.status !== "Active")
          throw new Error("La estancia ya no está activa. Actualice el historial.")
        setStays((current) => current && current.some((row) => row.name === result.stay)
          ? current : [{ name: result.stay, guest_label: result.guest_label,
              room_label: result.room_label, ends_at_local: result.ends_at_local || "",
              modified: result.modified }, ...(current || [])])
        setSelected(result.stay)
        navigate("/departures", { replace: true, state: null })
      }).catch((issue: unknown) => {
        if (controller.signal.aborted) return
        setError(issue instanceof Error ? issue.message : "No se pudo cargar la estancia.")
        navigate("/departures", { replace: true, state: null })
      })
    return () => controller.abort()
  }, [location.state, navigate, property.name, stays])
  useEffect(() => {
    if (!selected) { setDetail(null); return }
    const controller = new AbortController()
    setDetail(null); setCheckoutKey(""); setCreditReason(""); setOverrideReason("")
    refreshDetail(selected, controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo revisar la salida.")
    })
    return () => controller.abort()
  }, [selected, refreshDetail])

  async function prepare() {
    if (!detail || detail.stay !== selected || !folio || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ amount: string }>(property.name, "prepare_departure",
        { stay: selected, folio, acceptance: detail.timing.acceptance }, crypto.randomUUID())
      await refreshDetail(selected)
      setNotice(`Liquidación de tiempo preparada por ${detail.currency} ${result.amount}. Revise y contabilice la cuenta.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo preparar la salida.") }
    finally { setBusy(false) }
  }

  async function inspect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!detail || detail.stay !== selected || !canInspect || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "inspect_departure",
        { stay: selected, notes: inspectionNotes.trim() }, crypto.randomUUID())
      setInspectionNotes(""); await refreshDetail(selected)
      setNotice("Inspección de salida registrada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la inspección.") }
    finally { setBusy(false) }
  }

  async function checkOut() {
    if (!detail || detail.stay !== selected || busy) return
    setBusy(true); setError(""); setNotice("")
    const key = checkoutKey || crypto.randomUUID(); setCheckoutKey(key)
    try {
      const result = await execute<{ stay: string; cleaning_task: string }>(property.name,
        "check_out", { stay: selected, modified: detail.modified,
          ...(due > 0 ? { credit_reason: creditReason.trim(),
            credit_override_reason: overrideReason.trim() || undefined } : {}) }, key)
      setSelected(""); setDetail(null); setCheckoutKey("")
      setCreditReason(""); setOverrideReason("")
      await refresh()
      setNotice(`Salida ${result.stay} registrada. Se creó la tarea de limpieza ${result.cleaning_task}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la salida.") }
    finally { setBusy(false) }
  }

  const pending = detail?.folios.reduce((sum, row) => sum + Number(row.balance.pending) + Number(row.balance.scheduled), 0) || 0
  const due = detail?.folios.reduce((sum, row) => sum + Number(row.balance.outstanding), 0) || 0
  const guarantees = detail?.guarantees.reduce((sum, row) => sum + Number(row.available), 0) || 0
  const unpaidFolios = detail?.folios.filter((row) => Number(row.balance.outstanding) > 0) || []
  const needsOverride = unpaidFolios.some((row) => row.credit?.status === "Overdue" || row.credit?.status === "Over Limit")
  const creditReady = canApprove && creditReason.trim().length >= (provider === "pms" ? 8 : 1) &&
    creditReason.trim().length <= 500 &&
    (!needsOverride || (overrideReason.trim().length >= 8 && overrideReason.trim().length <= 500)) &&
    unpaidFolios.every((row) => row.credit && row.credit.status !== "Not Authorized" &&
      row.credit.status !== "Currency Review")
  const ready = detail && detail.stay === selected &&
    (provider !== "pms" || detail.folios.length > 0) &&
    (provider !== "pms" || !pending) &&
    (!due || creditReady) && !guarantees && !Number(detail.timing.amount) &&
    (!detail.inspection_required || detail.inspected) && !detail.laundry_pending &&
    !detail.services_pending && !detail.experiences_pending

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Salidas</h1><p className="mt-1 text-sm text-muted-foreground">Revise tiempo, cuentas, depósitos e inspección antes de liberar la habitación.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!stays ? <Skeleton className="h-72 w-full" /> : <div className="grid gap-5 lg:grid-cols-[1fr_1.5fr]">
      <Card><CardHeader><CardTitle>Estancias activas</CardTitle><CardDescription>Seleccione la habitación que va a salir.</CardDescription></CardHeader><CardContent className="space-y-2">
        {stays.map((row) => <button key={row.name} type="button" disabled={busy} onClick={() => { setSelected(row.name); setError(""); setNotice("") }} className={`w-full rounded-lg border p-3 text-left text-sm hover:bg-muted ${selected === row.name ? "border-primary bg-secondary" : "border-border"}`}>
          <strong>Habitación {row.room_label}</strong> · {row.guest_label}<span className="block text-muted-foreground">{row.name} · prevista {row.ends_at_local}</span>
        </button>)}
        {!stays.length && <p className="text-sm text-muted-foreground">No hay estancias activas.</p>}
      </CardContent></Card>
      {selected && (!detail || detail.stay !== selected) ? <Skeleton className="h-96 w-full" /> : detail ? <div className="space-y-5">
        <Card><CardHeader><CardTitle>Liquidación de tiempo</CardTitle><CardDescription>{detail.timing.explanation.join(" · ")}</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
          <p>Importe adicional: <strong>{detail.currency} {detail.timing.amount}</strong></p>
          {Number(detail.timing.amount) > 0 && <><label className="block space-y-1"><span>Cuenta para el cargo</span><select value={folio} onChange={(event) => setFolio(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">{detail.folios.map((row) => <option key={row.name} value={row.name}>{row.label} · {row.name}</option>)}</select></label><Button disabled={busy || !folio} onClick={prepare}>Preparar liquidación</Button></>}
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Cuentas y garantías</CardTitle><CardDescription>{provider === "pms" ? "Contabilice los cargos, cobre o autorice crédito y resuelva las garantías antes de salir." : "Los cargos pendientes se facturan en ERPNext al registrar la salida. Cobre, autorice crédito y resuelva las garantías antes de salir."}</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
          {detail.folios.map((row) => <div key={row.name} className="rounded-lg border border-border p-3"><strong>{row.label} · {row.name}</strong><p>{provider === "pms" ? "Pendiente de contabilizar" : "Pendiente de facturar"}: {detail.currency} {row.balance.pending} · Noches programadas: {detail.currency} {row.balance.scheduled}</p><p>Saldo total estimado: {detail.currency} {row.balance.outstanding}</p>{provider === "erpnext" && canFinance && <Button asChild size="sm" variant="outline" className="mt-2"><Link to={`/erp-invoicing?folio=${encodeURIComponent(row.name)}`}>Revisar factura</Link></Button>}</div>)}
          {!detail.folios.length && <p>Esta estancia no tiene cuenta abierta.</p>}
          {detail.guarantees.map((row) => <p key={row.payment}>Garantía {row.payment}: {row.currency} {row.available} sin aplicar ni devolver.</p>)}
          {canFinance ? provider === "pms" ? <div className="flex flex-wrap gap-2"><Button asChild variant="outline"><Link to="/folios">Revisar cuentas</Link></Button><Button asChild variant="outline"><Link to="/cash?section=refunds">Caja y devoluciones</Link></Button><Button asChild variant="outline"><Link to="/receivables?section=apply">Aplicar depósitos</Link></Button></div> : <Button asChild variant="outline"><Link to="/customer-credits?section=folios">Cobros y créditos ERPNext</Link></Button> : <p>Solicite a Caja que liquide cuentas y garantías pendientes.</p>}
          {due > 0 && <div className="space-y-2 rounded-lg border border-border p-3"><strong>Salida con saldo pendiente</strong>
            {unpaidFolios.map((row) => <p key={row.name}>{row.label}: {detail.currency} {row.balance.outstanding} · {row.credit?.party_name || row.customer} · Crédito {row.credit?.status || "Sin evaluar"} · Exposición {detail.currency} {row.credit?.exposure || "—"} / límite {row.credit?.limit || "—"}</p>)}
            {canApprove ? <><p>{provider === "pms" ? <>La autorización de crédito del pagador se administra en <Link className="text-primary underline" to="/credit?section=payers">Crédito PMS</Link>.</> : <>La autorización de crédito del pagador se administra en <Link className="text-primary underline" to="/erp-credit?section=payers">Crédito empresarial</Link>.</>}</p><Input required minLength={provider === "pms" ? 8 : 1} maxLength={500} value={creditReason} onChange={(event) => { setCreditReason(event.target.value); setCheckoutKey("") }} placeholder={provider === "pms" ? "Motivo de salida a crédito (8 a 500 caracteres)" : "Motivo de salida a crédito"} />
              {needsOverride && <Input required minLength={8} maxLength={500} value={overrideReason} onChange={(event) => { setOverrideReason(event.target.value); setCheckoutKey("") }} placeholder="Motivo de excepción por límite o vencimiento" />}
            </> : <p>Solo Gerencia puede autorizar una salida a crédito.</p>}
          </div>}
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Inspección y entrega</CardTitle><CardDescription>Lavandería, servicios y experiencias pendientes deben resolverse.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
          <p>Inspección: {detail.inspection_required ? detail.inspected ? "Realizada" : "Pendiente" : "No requerida"}</p>
          <p>Lavandería: {detail.laundry_pending} · Servicios: {detail.services_pending} · Experiencias: {detail.experiences_pending}</p>
          {canInspect && detail.inspection_required && !detail.inspected && <form onSubmit={inspect} className="flex flex-wrap gap-2"><Input required maxLength={500} value={inspectionNotes} onChange={(event) => setInspectionNotes(event.target.value)} placeholder="Notas de la inspección" className="min-w-56 flex-1" /><Button disabled={busy}>Registrar inspección</Button></form>}
          <Button disabled={busy || !ready} onClick={checkOut}>Registrar salida y enviar a limpieza</Button>
          {!ready && <p className="text-muted-foreground">La salida se habilita cuando el tiempo adicional, las garantías y las tareas pendientes quedan resueltos, y el saldo se cobra o Gerencia autoriza crédito vigente{provider === "pms" ? ", después de contabilizar los cargos PMS" : ""}.</p>}
        </CardContent></Card>
      </div> : <Card><CardContent className="py-8 text-sm text-muted-foreground">Seleccione una estancia para revisar su salida.</CardContent></Card>}
    </div>}
  </div>
}
