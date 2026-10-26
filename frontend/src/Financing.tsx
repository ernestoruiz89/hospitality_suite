import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { FinanceConcepts, type FinanceConcept, type FinanceConceptDraft } from "./FinanceConcepts"
import { financingRequestKind, financingSections, useFinancingSection, type FinancingRequestKind } from "./FinancingSections"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Kind = FinancingRequestKind
type Movement = { name: string; kind: string; concept_label: string;
  source_movement?: string; currency: string; amount: number; base_amount: number;
  status: string; requested_by: string; approved_by?: string; reference?: string;
  available?: string; principal_outstanding?: string }
type Snapshot = { currency: string; user: string;
  concepts: { name: string; label: string; nature: string; account: string }[];
  concept_settings: FinanceConcept[];
  accounts: { name: string; account_code: string; account_name: string; root_type: string }[];
  methods: { name: string; mode_of_payment: string; currency: string; is_cash: boolean }[];
  shifts: { name: string; opened_at: string }[];
  movements: Movement[]; sources: Movement[] }
type Quote = { acceptance: string; kind: string; currency: string; amount: string;
  base_currency: string; base_amount: string; exchange_rate: string;
  debit: string; credit: string; concept_label: string }

const labels: Record<string, string> = {
  "Other Income": "Otro ingreso", "Loan Received": "Préstamo recibido",
  "Loan Repayment": "Devolución de préstamo",
  "Capital Contribution": "Aporte de capital", "Capital Withdrawal": "Retiro de capital",
}
const nature: Record<Kind, string> = {
  "Loan Received": "Loan", "Loan Repayment": "Loan",
  "Capital Contribution": "Capital", "Capital Withdrawal": "Capital",
}
const sourceKind: Partial<Record<Kind, string>> = {
  "Loan Repayment": "Loan Received", "Capital Withdrawal": "Capital Contribution",
}
export function Financing({ property, canApprove, canChart }: {
  property: Property; canApprove: boolean; canChart: boolean }) {
  const section = useFinancingSection(canChart)
  const kind: Kind = financingRequestKind(section) || "Loan Received"
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [concept, setConcept] = useState("")
  const [source, setSource] = useState("")
  const [requestAmount, setRequestAmount] = useState("")
  const [requestReason, setRequestReason] = useState("")
  const [approvalReason, setApprovalReason] = useState("")
  const [selected, setSelected] = useState("")
  const [incomeConcept, setIncomeConcept] = useState("")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const send = useIdempotentCommand(property.name)
  const refresh = useCallback(async () => setData(await call<Snapshot>(
    "pms_financing_snapshot", { property_name: property.name })), [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice("");
    setConcept(""); setSource(""); setRequestAmount(""); setRequestReason("");
    setApprovalReason(""); setSelected(""); setIncomeConcept(""); setMethod("");
    setShift(""); setAmount(""); setReference(""); setReason("");
    setQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los movimientos."))
  }, [refresh])
  useEffect(() => {
    setSelected(""); setIncomeConcept(""); setQuote(null)
    setConcept(""); setSource(""); setRequestAmount(""); setRequestReason("")
  }, [section])
  const changePost = () => setQuote(null)
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la pantalla para consultar el movimiento.`) }
  }
  const selectedMethod = data?.methods.find((row) => row.name === method)
  const activeSelected = section === "post" ? selected : ""
  const postData = { movement: activeSelected || null,
    concept: section === "income" ? incomeConcept : null,
    method, shift: selectedMethod?.is_cash ? shift : null,
    amount, reference: reference.trim(), reason: reason.trim() }
  async function saveConcept(values: FinanceConceptDraft): Promise<boolean> {
    if (busy) return false
    setBusy(true); setError(""); setNotice("")
    try {
      await send(values.name ? "pms_income_concept_update" : "pms_income_concept",
        values.name ? { concept: values.name, modified: values.modified,
          label: values.label, nature: values.nature, account: values.account,
          active: values.active } : { label: values.label, nature: values.nature,
          account: values.account, active: values.active })
      await refreshAfter(values.name ? "Concepto financiero actualizado." : "Concepto financiero registrado.")
      return true
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar el concepto."); return false }
    finally { setBusy(false) }
  }
  async function request(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_financing_request", {
        kind, concept: sourceKind[kind] ? null : concept,
        source_movement: sourceKind[kind] ? source : null,
        amount: requestAmount, reason: requestReason.trim(),
      })
      setRequestAmount(""); setRequestReason(""); setSource("");
      await refreshAfter("Solicitud enviada a Gerencia para aprobación.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo solicitar el movimiento.") }
    finally { setBusy(false) }
  }
  async function approve(movement: string) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_financing_approve", {
        movement, reason: approvalReason.trim(),
      })
      setApprovalReason(""); await refreshAfter("Solicitud aprobada.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aprobar la solicitud.") }
    finally { setBusy(false) }
  }
  async function cancel(movement: string) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_financing_cancel", {
        movement, reason: "Solicitud cancelada antes de contabilizar",
      })
      if (selected === movement) { setSelected(""); changePost() }
      await refreshAfter("Solicitud cancelada sin asiento.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cancelar la solicitud.") }
    finally { setBusy(false) }
  }
  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      if (!quote) {
        setQuote(await call<Quote>("pms_financing_quote", {
          property_name: property.name, data: JSON.stringify(postData),
        }))
      } else {
        await send("pms_financing_post", { ...postData, acceptance: quote.acceptance })
        setSelected(""); setIncomeConcept(""); setMethod(""); setShift("");
        setAmount(""); setReference(""); setReason("");
        setQuote(null)
        await refreshAfter("Movimiento contabilizado en el mayor PMS.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el movimiento.") }
    finally { setBusy(false) }
  }
  const eligible = data?.sources.filter((row) => row.kind === sourceKind[kind] && Number(row.available) > 0) || []
  const currentSection = financingSections.find((item) => item.id === section)!
  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Movimientos financieros</p>
      <h1 className="mt-1 text-3xl font-semibold">{currentSection.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{currentSection.description}. Seleccione otra operación desde el menú de Finanzas.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section === "concepts" && canChart && <FinanceConcepts key={property.name}
        concepts={data.concept_settings} accounts={data.accounts} busy={busy} onSave={saveConcept} />}
      {financingRequestKind(section) && <Card><CardHeader><CardTitle>{currentSection.label}</CardTitle><CardDescription>{sourceKind[kind] ? "Vincule esta salida a su entrada original. El importe no puede exceder el principal disponible." : "Indique el concepto y el principal que desea registrar. Gerencia debe aprobar la solicitud antes del asiento."}</CardDescription></CardHeader><CardContent><form onSubmit={request} className="space-y-3">
          {!sourceKind[kind] && !data.concepts.some((row) => row.nature === nature[kind]) && <p className="text-sm text-muted-foreground">Aún no hay conceptos de {nature[kind] === "Loan" ? "préstamo" : "capital"}. {canChart && <Link className="font-medium text-primary underline" to="/financing?section=concepts">Crear concepto</Link>}</p>}
          {sourceKind[kind] && !eligible.length && <p className="text-sm text-muted-foreground">No hay entradas originales con principal disponible para esta operación.</p>}
          {sourceKind[kind] ? <select required value={source} onChange={(event) => setSource(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Entrada original</option>{eligible.map((row) => <option key={row.name} value={row.name}>{row.concept_label} · Principal disponible {data.currency} {row.available}</option>)}</select> : <select required value={concept} onChange={(event) => setConcept(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Concepto</option>{data.concepts.filter((row) => row.nature === nature[kind]).map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select>}
          <Input required type="number" min="0.01" step="0.01" placeholder={`Principal (${data.currency})`} value={requestAmount} onChange={(event) => setRequestAmount(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={requestReason} onChange={(event) => setRequestReason(event.target.value)} />
          <Button disabled={busy || (sourceKind[kind] ? !source : !concept)}>Solicitar aprobación</Button>
        </form></CardContent></Card>}
      {section === "approvals" && <Card><CardHeader><CardTitle>Solicitudes</CardTitle><CardDescription>Gerencia revisa solicitudes ajenas. Se puede cancelar una solicitud antes del asiento.</CardDescription></CardHeader><CardContent className="space-y-3">
          {canApprove && <Input maxLength={500} placeholder="Motivo de aprobación" value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} />}
          {data.movements.filter((row) => row.status === "Pending Approval" || row.status === "Approved").map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span><strong>{labels[row.kind]}</strong> · {row.concept_label}<span className="block text-xs text-muted-foreground">{data.currency} {row.base_amount} · {row.status === "Approved" ? "Aprobado" : "Pendiente"} · {row.requested_by}</span></span><span className="flex gap-2">{canApprove && row.status === "Pending Approval" && row.requested_by !== data.user && <Button size="sm" disabled={busy || !approvalReason.trim()} onClick={() => approve(row.name)}>Aprobar</Button>}{(canApprove || row.status === "Pending Approval" && row.requested_by === data.user) && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => cancel(row.name)}>Cancelar</Button>}</span></div>)}
          {!data.movements.some((row) => row.status === "Pending Approval" || row.status === "Approved") && <p className="text-sm text-muted-foreground">Sin solicitudes abiertas.</p>}
        </CardContent></Card>}
      {(section === "income" || section === "post") && <Card><CardHeader><CardTitle>{section === "income" ? "Registrar otro ingreso" : "Contabilizar solicitud aprobada"}</CardTitle><CardDescription>Revise las cuentas y el tipo de cambio antes de confirmar el asiento.</CardDescription></CardHeader><CardContent>
        {section === "income" && !data.concepts.some((row) => row.nature === "Other Income") && <p className="text-sm text-muted-foreground">Aún no hay conceptos de otros ingresos. {canChart && <Link className="font-medium text-primary underline" to="/financing?section=concepts">Crear concepto</Link>}</p>}
        {section === "post" && !data.movements.some((row) => row.status === "Approved") && <p className="text-sm text-muted-foreground">No hay solicitudes aprobadas. <Link className="font-medium text-primary underline" to="/financing?section=approvals">Ver solicitudes</Link></p>}
        {(section === "income" && data.concepts.some((row) => row.nature === "Other Income") || section === "post" && data.movements.some((row) => row.status === "Approved")) && <form onSubmit={register} className="grid gap-3 md:grid-cols-2">
        {section === "post" ? <select required value={selected} onChange={(event) => { changePost(); setSelected(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Solicitud aprobada</option>{data.movements.filter((row) => row.status === "Approved").map((row) => <option key={row.name} value={row.name}>{labels[row.kind]} · {row.concept_label} · {data.currency} {row.base_amount}</option>)}</select>
          : <select required value={incomeConcept} onChange={(event) => { changePost(); setIncomeConcept(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Concepto de otro ingreso</option>{data.concepts.filter((row) => row.nature === "Other Income").map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select>}
        <select required value={method} onChange={(event) => { changePost(); setMethod(event.target.value); setShift("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de Caja o banco</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select>
        {selectedMethod?.is_cash && <select required value={shift} onChange={(event) => { changePost(); setShift(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno propio abierto</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>}
        <Input required aria-label="Importe del movimiento" type="number" min="0.01" step="0.01" placeholder={`Importe (${selectedMethod?.currency || data.currency})`} value={amount} onChange={(event) => { changePost(); setAmount(event.target.value) }} />
        <Input required maxLength={140} placeholder="Referencia" value={reference} onChange={(event) => { changePost(); setReference(event.target.value) }} />
        <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { changePost(); setReason(event.target.value) }} />
        {quote && <div className="rounded-lg bg-secondary p-3 text-sm md:col-span-2"><strong>{labels[quote.kind]} · {quote.concept_label}</strong><p>{quote.currency} {quote.amount} · Cambio {quote.exchange_rate} · Base {quote.base_currency} {quote.base_amount}</p><p>Débito {data.accounts.find((row) => row.name === quote.debit)?.account_name || quote.debit} · Crédito {data.accounts.find((row) => row.name === quote.credit)?.account_name || quote.credit}</p></div>}
        <Button disabled={busy || !method || (section === "post" ? !selected : !incomeConcept)} className="md:col-span-2">{quote ? "Confirmar asiento" : "Revisar asiento"}</Button>
      </form>}
      </CardContent></Card>}
      {section === "history" && <Card><CardHeader><CardTitle>Principal y movimientos</CardTitle></CardHeader><CardContent className="space-y-2">{data.sources.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.concept_label}</strong> · {labels[row.kind]} · Principal {data.currency} {row.base_amount} · Pendiente {data.currency} {row.principal_outstanding} · Disponible {data.currency} {row.available}</p>)}{data.movements.filter((row) => row.status === "Posted").map((row) => <p key={row.name + "-posted"} className="border-b border-border py-2 text-sm">{labels[row.kind]} · {row.concept_label} · {row.currency} {row.amount} · Base {data.currency} {row.base_amount} · {row.reference}</p>)}{!data.movements.some((row) => row.status === "Posted") && <p className="text-sm text-muted-foreground">Sin movimientos contabilizados.</p>}</CardContent></Card>}
    </>}
  </div>
}
