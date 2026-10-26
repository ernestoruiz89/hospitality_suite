import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"
import { FinanceConcepts, type FinanceConcept, type FinanceConceptDraft } from "./FinanceConcepts"
import { financingRequestKind, financingSections, useFinancingSection, type FinancingRequestKind } from "./FinancingSections"
import { CommandKeys } from "./idempotentCommand"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Kind = FinancingRequestKind
type Movement = { name: string; kind: string; concept?: string; concept_label: string;
  source_movement?: string; currency: string; amount: number; status: string;
  requested_by: string; approved_by?: string; reference?: string; business_date: string;
  available?: string; principal_outstanding?: string }
type Account = { name: string; account_code: string; account_name: string;
  root_type: string; account_type: string }
type Snapshot = { currency: string; user: string;
  concepts: { name: string; label: string; nature: string; account: string }[];
  concept_settings: FinanceConcept[];
  accounts: Account[]; methods: { name: string; mode_of_payment: string }[];
  shifts: { name: string; opened_at: string }[];
  movements: Movement[]; sources: Movement[] }
type Quote = { acceptance: string; kind: string; amount: string; currency: string;
  debit: string; credit: string; channel: string; shift?: string; method?: string }

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
export function ErpFinancing({ property, canSetup, canApprove, canFinance }: {
  property: Property; canSetup: boolean; canApprove: boolean; canFinance: boolean }) {
  const section = useFinancingSection(canSetup)
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
  const [cancelReason, setCancelReason] = useState("")
  const [selected, setSelected] = useState("")
  const [incomeConcept, setIncomeConcept] = useState("")
  const [channel, setChannel] = useState<"Cash" | "Bank">("Cash")
  const [method, setMethod] = useState("")
  const [shift, setShift] = useState("")
  const [bankAccount, setBankAccount] = useState("")
  const [amount, setAmount] = useState("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [reverseReason, setReverseReason] = useState("")
  const setupKeys = useRef(new CommandKeys())
  const send = useIdempotentCommand(property.name)

  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("erp_financing_snapshot", { property_name: property.name }))
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setQuote(null)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los movimientos financieros."))
  }, [refresh])
  useEffect(() => {
    setSelected(""); setIncomeConcept(""); setQuote(null)
    setConcept(""); setSource(""); setRequestAmount(""); setRequestReason("")
  }, [section])
  const clearQuote = () => setQuote(null)
  const run = async (action: string, payload: Record<string, unknown>, success: string) => {
    if (busy) return false
    setBusy(true); setError(""); setNotice("")
    try {
      await send(action, payload)
      try { await refresh(); setNotice(success) }
      catch { setNotice(`${success} Actualice la pantalla para consultar el movimiento.`) }
      return true
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo registrar el movimiento.")
      return false
    } finally { setBusy(false) }
  }
  const saveConcept = async (values: FinanceConceptDraft): Promise<boolean> => {
    if (busy) return false
    setBusy(true); setError(""); setNotice("")
    try {
      if (values.name) {
        await send("finance_concept", { concept: values.name,
          modified: values.modified, label: values.label,
          nature: values.nature, account: values.account, active: values.active })
      } else {
        const payload = { label: values.label, nature: values.nature,
          account: values.account, active: values.active }
        await setupKeys.current.run(property.name, "treasury_concept", payload,
          (key) => postMethod("save_setup", { property_name: property.name,
            section: "treasury_concept", data: payload, request_key: key }))
      }
      const notice = values.name ? "Concepto financiero actualizado." : "Concepto financiero registrado."
      try { await refresh(); setNotice(notice) }
      catch { setNotice(`${notice} Actualice la pantalla para consultarlo.`) }
      return true
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo guardar el concepto.")
      return false
    } finally { setBusy(false) }
  }
  const request = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("finance_request", { kind, concept: sourceKind[kind] ? null : concept,
      source_movement: sourceKind[kind] ? source : null, amount: requestAmount,
      reason: requestReason.trim() }, "Solicitud enviada a Gerencia.")) {
      setRequestAmount(""); setRequestReason(""); setSource("")
    }
  }
  const activeSelected = section === "post" ? selected : ""
  const selectedMovement = data?.movements.find((row) => row.name === activeSelected)
  const postData = { movement: activeSelected || null,
    kind: selectedMovement?.kind || "Other Income",
    concept: selectedMovement?.concept || (section === "income" ? incomeConcept : null),
    source_movement: selectedMovement?.source_movement || null,
    channel, method: channel === "Cash" ? method : null,
    shift: channel === "Cash" ? shift : null,
    bank_account: channel === "Bank" ? bankAccount : null,
    amount: selectedMovement ? String(selectedMovement.amount) : amount,
    reference: reference.trim(), reason: reason.trim() }
  const register = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return
    if (!quote) {
      setBusy(true); setError(""); setNotice("")
      try {
        setQuote(await call<Quote>("preview", { property_name: property.name,
          action: "finance_post", data: JSON.stringify(postData) }))
      } catch (issue) {
        setError(issue instanceof Error ? issue.message : "No se pudo revisar el asiento.")
      } finally { setBusy(false) }
      return
    }
    if (await run("finance_post", { ...postData, acceptance: quote.acceptance },
      "Movimiento contabilizado en ERPNext.")) {
      setSelected(""); setIncomeConcept(""); setMethod(""); setShift("")
      setBankAccount(""); setAmount(""); setReference(""); setReason(""); setQuote(null)
    }
  }
  const availableSources = data?.sources.filter((row) =>
    row.kind === sourceKind[kind] && Number(row.available) > 0) || []
  const bankAccounts = data?.accounts.filter((row) =>
    row.root_type === "Asset" && row.account_type === "Bank") || []
  const accountName = (name: string) => data?.accounts.find((row) => row.name === name)?.account_name || name
  const currentSection = financingSections.find((item) => item.id === section)!

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Movimientos financieros</p>
      <h1 className="mt-1 text-3xl font-semibold">{currentSection.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{currentSection.description}. Seleccione otra operación desde el menú de Finanzas.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      {section === "concepts" && canSetup && <FinanceConcepts key={property.name}
        concepts={data.concept_settings} accounts={data.accounts} busy={busy} onSave={saveConcept} />}
      {financingRequestKind(section) && canFinance && <Card><CardHeader><CardTitle>{currentSection.label}</CardTitle><CardDescription>{sourceKind[kind] ? "Vincule esta salida a su entrada original. El importe no puede exceder el principal disponible." : "Indique el concepto y el principal que desea registrar. Gerencia debe aprobar la solicitud antes del asiento."}</CardDescription></CardHeader><CardContent><form onSubmit={request} className="space-y-3">
          {!sourceKind[kind] && !data.concepts.some((row) => row.nature === nature[kind]) && <p className="text-sm text-muted-foreground">Aún no hay conceptos de {nature[kind] === "Loan" ? "préstamo" : "capital"}. {canSetup && <Link className="font-medium text-primary underline" to="/financing?section=concepts">Crear concepto</Link>}</p>}
          {sourceKind[kind] && !availableSources.length && <p className="text-sm text-muted-foreground">No hay entradas originales con principal disponible para esta operación.</p>}
          {sourceKind[kind] ? <select required value={source} onChange={(event) => setSource(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Entrada original</option>{availableSources.map((row) => <option key={row.name} value={row.name}>{row.concept_label} · Disponible {data.currency} {row.available}</option>)}</select> : <select required value={concept} onChange={(event) => setConcept(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Concepto</option>{data.concepts.filter((row) => row.nature === nature[kind]).map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select>}
          <Input required type="number" min="0.01" step="0.01" placeholder={`Principal (${data.currency})`} value={requestAmount} onChange={(event) => setRequestAmount(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={requestReason} onChange={(event) => setRequestReason(event.target.value)} />
          <Button disabled={busy || (sourceKind[kind] ? !source : !concept)}>Solicitar aprobación</Button>
        </form></CardContent></Card>}
      {section === "approvals" && <Card><CardHeader><CardTitle>Solicitudes</CardTitle><CardDescription>Gerencia aprueba solicitudes ajenas. El solicitante puede cancelar una pendiente antes del asiento.</CardDescription></CardHeader><CardContent className="space-y-3">
          {canApprove && <Input maxLength={500} placeholder="Motivo de aprobación" value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} />}
          <Input maxLength={500} placeholder="Motivo para cancelar una solicitud" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} />
          {data.movements.filter((row) => row.status === "Pending Approval" || row.status === "Approved").map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span><strong>{labels[row.kind]}</strong> · {row.concept_label}<span className="block text-xs text-muted-foreground">{data.currency} {row.amount} · {row.status === "Approved" ? "Aprobado" : "Pendiente"} · {row.requested_by}</span></span><span className="flex gap-2">{canApprove && row.status === "Pending Approval" && row.requested_by !== data.user && <Button size="sm" disabled={busy || !approvalReason.trim()} onClick={async () => { if (await run("finance_approve", { movement: row.name, reason: approvalReason.trim() }, "Solicitud aprobada.")) setApprovalReason("") }}>Aprobar</Button>}{(canApprove || row.status === "Pending Approval" && row.requested_by === data.user) && <Button size="sm" variant="outline" disabled={busy || !cancelReason.trim()} onClick={async () => { if (await run("finance_cancel_request", { movement: row.name, reason: cancelReason.trim() }, "Solicitud cancelada.")) { setCancelReason(""); if (selected === row.name) { setSelected(""); clearQuote() } } }}>Cancelar</Button>}</span></div>)}
          {!data.movements.some((row) => row.status === "Pending Approval" || row.status === "Approved") && <p className="text-sm text-muted-foreground">Sin solicitudes abiertas.</p>}
        </CardContent></Card>}
      {(section === "income" || section === "post") && canFinance && <Card><CardHeader><CardTitle>{section === "income" ? "Registrar otro ingreso" : "Contabilizar solicitud aprobada"}</CardTitle><CardDescription>Revise el débito y crédito antes de confirmar. Si cambian los datos, la revisión anterior se descarta.</CardDescription></CardHeader><CardContent>
        {section === "income" && !data.concepts.some((row) => row.nature === "Other Income") && <p className="text-sm text-muted-foreground">Aún no hay conceptos de otros ingresos. {canSetup && <Link className="font-medium text-primary underline" to="/financing?section=concepts">Crear concepto</Link>}</p>}
        {section === "post" && !data.movements.some((row) => row.status === "Approved") && <p className="text-sm text-muted-foreground">No hay solicitudes aprobadas. <Link className="font-medium text-primary underline" to="/financing?section=approvals">Ver solicitudes</Link></p>}
        {(section === "income" && data.concepts.some((row) => row.nature === "Other Income") || section === "post" && data.movements.some((row) => row.status === "Approved")) && <form onSubmit={register} className="grid gap-3 md:grid-cols-2">
        {section === "post" ? <select required value={selected} onChange={(event) => { clearQuote(); setSelected(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Solicitud aprobada</option>{data.movements.filter((row) => row.status === "Approved").map((row) => <option key={row.name} value={row.name}>{labels[row.kind]} · {row.concept_label} · {data.currency} {row.amount}</option>)}</select>
          : <select required value={incomeConcept} onChange={(event) => { clearQuote(); setIncomeConcept(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Concepto de otro ingreso</option>{data.concepts.filter((row) => row.nature === "Other Income").map((row) => <option key={row.name} value={row.name}>{row.label}</option>)}</select>}
        <select value={channel} onChange={(event) => { clearQuote(); setChannel(event.target.value as "Cash" | "Bank") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Cash">Caja</option><option value="Bank">Banco</option></select>
        {channel === "Cash" ? <><select required value={method} onChange={(event) => { clearQuote(); setMethod(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de efectivo</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment}</option>)}</select><select required value={shift} onChange={(event) => { clearQuote(); setShift(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno propio abierto</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></> : <select required value={bankAccount} onChange={(event) => { clearQuote(); setBankAccount(event.target.value) }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta bancaria ERPNext</option>{bankAccounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>}
        <Input required={section === "income"} disabled={section === "post"} aria-label="Importe del movimiento" type="number" min="0.01" step="0.01" placeholder={`Importe (${data.currency})`} value={selectedMovement ? String(selectedMovement.amount) : amount} onChange={(event) => { clearQuote(); setAmount(event.target.value) }} />
        <Input required maxLength={140} placeholder="Referencia" value={reference} onChange={(event) => { clearQuote(); setReference(event.target.value) }} />
        <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => { clearQuote(); setReason(event.target.value) }} />
        {quote && <div className="rounded-lg bg-secondary p-3 text-sm md:col-span-2"><strong>{labels[quote.kind]} · {quote.currency} {quote.amount}</strong><p>Débito: {accountName(quote.debit)}</p><p>Crédito: {accountName(quote.credit)}</p><p>{quote.channel === "Cash" ? `Turno ${quote.shift}` : "Cuenta bancaria"}</p></div>}
        <Button disabled={busy || (channel === "Cash" ? !method || !shift : !bankAccount) || (section === "post" ? !selected : !incomeConcept)} className="md:col-span-2">{quote ? "Confirmar asiento" : "Revisar asiento"}</Button>
      </form>}
      </CardContent></Card>}
      {section === "history" && <Card><CardHeader><CardTitle>Principal y movimientos</CardTitle></CardHeader><CardContent className="space-y-3">
        {data.sources.map((row) => <p key={row.name} className="border-b border-border pb-2 text-sm"><strong>{row.concept_label}</strong> · {labels[row.kind]} · Principal {data.currency} {row.amount} · Pendiente {data.currency} {row.principal_outstanding} · Disponible {data.currency} {row.available}</p>)}
        {canApprove && <Input maxLength={500} placeholder="Motivo para revertir un asiento de hoy" value={reverseReason} onChange={(event) => setReverseReason(event.target.value)} />}
        {data.movements.filter((row) => row.status === "Posted").map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span>{labels[row.kind]} · {row.concept_label} · {data.currency} {row.amount} · {row.reference || row.name}</span>{canApprove && row.business_date === property.business_date && <Button size="sm" variant="outline" disabled={busy || !reverseReason.trim()} onClick={async () => { if (await run("finance_reverse", { doctype: "HS Treasury Movement", name: row.name, reason: reverseReason.trim() }, "Asiento revertido.")) setReverseReason("") }}>Revertir</Button>}</div>)}
        {!data.sources.length && !data.movements.some((row) => row.status === "Posted") && <p className="text-sm text-muted-foreground">Sin movimientos contabilizados.</p>}
      </CardContent></Card>}
    </>}
  </div>
}
