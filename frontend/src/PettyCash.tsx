import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"
import { CommandKeys } from "./idempotentCommand"
import { pettySections } from "./PettyCashSections"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Account = { name: string; account_code: string; account_name: string; root_type: string }
type Expense = { name: string; category_label: string; responsible: string; beneficiary: string;
  concept: string; receipt_reference: string; amount: number; business_date: string;
  rendition?: string; status: string }
type Rendition = { name: string; responsible: string; expense_total: number;
  expected_cash: number; counted_cash: number; variance: number; explanation: string;
  status: string; submitted_by: string; reviewed_by?: string; review_note?: string;
  approved_business_date?: string;
  pms_variance_journal?: string; variance_journal?: string }
type Handover = { name: string; outgoing: string; incoming: string; expected_cash: number;
  counted_cash: number; status: string; outgoing_accepted: boolean; incoming_accepted: boolean }
type Fund = { name: string; kind: string; rendition?: string; amount: number;
  reference: string; status: string; shift: string; business_date: string }
type Snapshot = { active: boolean; currency: string; user: string; responsible?: string;
  property_modified?: string;
  account?: string; overage_account?: string; shortage_account?: string;
  balance: string; expected_cash: string; pending_expenses: string; reconciled: boolean;
  initial_fund_exists: boolean;
  accounts: Account[]; categories: { name: string; label: string; max_amount: number }[];
  methods: { name: string; mode_of_payment: string; currency: string }[];
  shifts: { name: string; opened_at: string }[]; expenses: Expense[];
  renditions: Rendition[]; handovers: Handover[]; funds: Fund[];
  users: { name: string; full_name: string }[] }

const stateLabel: Record<string, string> = {
  Submitted: "Presentada", Returned: "Devuelta", Approved: "Aprobada",
  "Partially Reimbursed": "Repuesta parcialmente", Reimbursed: "Repuesta",
}

const userLabel = (row: { name: string; full_name: string }) =>
  row.full_name && row.full_name !== row.name ? `${row.full_name} · ${row.name}` : row.name

const erpActions: Record<string, string> = {
  pms_petty_fund: "petty_fund", pms_petty_expense: "petty_expense",
  pms_petty_correct: "petty_correct", pms_petty_submit: "petty_rendition",
  pms_petty_review: "petty_review", pms_petty_handover: "petty_handover",
  pms_petty_accept: "petty_accept",
  pms_petty_handover_cancel: "petty_handover_cancel",
  pms_petty_reverse: "finance_reverse",
}

export function PettyCash({ property, provider, canSetup, canApprove, canFinance, onSectionsChange }: {
  property: Property; provider: "pms" | "erpnext";
  canSetup: boolean; canApprove: boolean; canFinance: boolean;
  onSectionsChange?: (propertyName: string, sectionIds: string[], defaultSection: string) => void }) {
  const send = useIdempotentCommand(property.name)
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [pettyAccount, setPettyAccount] = useState("")
  const [responsible, setResponsible] = useState("")
  const [overage, setOverage] = useState("")
  const [shortage, setShortage] = useState("")
  const [fundRendition, setFundRendition] = useState("")
  const [fundMethod, setFundMethod] = useState("")
  const [fundShift, setFundShift] = useState("")
  const [fundAmount, setFundAmount] = useState("")
  const [fundReference, setFundReference] = useState("")
  const [fundReason, setFundReason] = useState("")
  const [category, setCategory] = useState("")
  const [beneficiary, setBeneficiary] = useState("")
  const [concept, setConcept] = useState("")
  const [receiptReference, setReceiptReference] = useState("")
  const [expenseAmount, setExpenseAmount] = useState("")
  const [returnedExpense, setReturnedExpense] = useState("")
  const [correctReference, setCorrectReference] = useState("")
  const [rendition, setRendition] = useState("")
  const [countedCash, setCountedCash] = useState("")
  const [explanation, setExplanation] = useState("")
  const [reviewNote, setReviewNote] = useState("")
  const [incoming, setIncoming] = useState("")
  const [handoverCount, setHandoverCount] = useState("")
  const [handoverReason, setHandoverReason] = useState("")
  const [handoverCancelName, setHandoverCancelName] = useState("")
  const [handoverCancelReason, setHandoverCancelReason] = useState("")
  const [reverseType, setReverseType] = useState("HS Petty Cash Expense")
  const [reverseName, setReverseName] = useState("")
  const [reverseReason, setReverseReason] = useState("")
  const setupKeys = useRef(new CommandKeys())
  const refresh = useCallback(async () => {
    const result = await call<Snapshot>(provider === "pms" ? "pms_petty_snapshot" : "erp_petty_snapshot", { property_name: property.name })
    setData(result)
    setPettyAccount(result.account || "")
    setResponsible(result.responsible || "")
    setOverage(result.overage_account || "")
    setShortage(result.shortage_account || "")
  }, [property.name, provider])
  useEffect(() => {
    setFundRendition(""); setFundMethod(""); setFundShift("")
    setFundAmount(""); setFundReference(""); setFundReason("")
    setRendition(""); setCountedCash(""); setExplanation("")
    setReturnedExpense(""); setCorrectReference("")
    setIncoming(""); setHandoverCount(""); setHandoverReason("")
    setHandoverCancelName(""); setHandoverCancelReason("")
  }, [property.name, provider])
  useEffect(() => {
    setData(null); setError(""); setNotice("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar Caja Chica."))
  }, [refresh])
  const run = async (action: string, payload: Record<string, unknown>, success: string) => {
    if (busy) return false
    setBusy(true); setError(""); setNotice("")
    const command = provider === "pms" ? action : erpActions[action]
    if (!command) { setBusy(false); setError("Esta operación aún no está disponible con ERPNext."); return false }
    try {
      await send(command, payload)
      try { await refresh(); setNotice(success) }
      catch { setNotice(`${success} Actualice la pantalla para consultar el saldo.`) }
      return true
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo completar la operación.")
      return false
    }
    finally { setBusy(false) }
  }
  const submitConfig = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const values = {
      petty_cash_account: pettyAccount, petty_cash_responsible: responsible,
      petty_cash_overage_account: overage, petty_cash_shortage_account: shortage,
    }
    if (provider === "pms") {
      await run("pms_petty_configure", values, "Caja Chica configurada para este establecimiento.")
      return
    }
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await setupKeys.current.run(property.name, "save_setup",
        { section: "property", data: values, expected_modified: data?.property_modified },
        (key) => postMethod("save_setup", { property_name: property.name, section: "property",
          data: values, expected_modified: data?.property_modified, request_key: key }))
      try { await refresh(); setNotice("Caja Chica configurada para este establecimiento.") }
      catch { setNotice("Caja Chica configurada. Actualice la pantalla para consultar el saldo.") }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo configurar Caja Chica.")
    } finally { setBusy(false) }
  }
  const submitFund = async (event: FormEvent<HTMLFormElement>, kind: "Initial Fund" | "Replenishment") => {
    event.preventDefault()
    if (await run("pms_petty_fund", { kind,
      rendition: kind === "Replenishment" ? fundRendition : null,
      method: fundMethod, shift: fundShift, amount: fundAmount,
      reference: fundReference.trim(), reason: fundReason.trim(),
    }, kind === "Initial Fund" ? "Fondo inicial entregado." : "Reposición registrada.")) {
      setFundAmount(""); setFundReference(""); setFundReason("")
    }
  }
  const submitExpense = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("pms_petty_expense", { category, beneficiary: beneficiary.trim(),
      concept: concept.trim(), receipt_reference: receiptReference.trim(),
      amount: expenseAmount }, "Desembolso contabilizado en Caja Chica.")) {
      setExpenseAmount(""); setReceiptReference("")
    }
  }
  const submitCorrection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("pms_petty_correct", { expense: returnedExpense,
      receipt_reference: correctReference.trim() }, "Referencia del comprobante corregida.")) {
      setReturnedExpense(""); setCorrectReference("")
    }
  }
  const submitRendition = async (event: FormEvent<HTMLFormElement>, returnedRendition: string | null) => {
    event.preventDefault()
    if (await run("pms_petty_submit", { rendition: returnedRendition,
      counted_cash: countedCash, explanation: explanation.trim(),
    }, "Rendición presentada a Gerencia.")) {
      setRendition(""); setCountedCash(""); setExplanation("")
    }
  }
  const submitHandover = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("pms_petty_handover", { incoming, counted_cash: handoverCount,
      reason: handoverReason.trim() }, "Traspaso enviado a ambos responsables.")) {
      setHandoverCount(""); setHandoverReason("")
    }
  }
  const submitHandoverCancel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("pms_petty_handover_cancel", { handover: handoverCancelName,
      reason: handoverCancelReason.trim() }, "Traspaso cancelado.")) {
      setHandoverCancelName(""); setHandoverCancelReason("")
    }
  }
  const submitReverse = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (await run("pms_petty_reverse", { doctype: reverseType, name: reverseName,
      reason: reverseReason.trim() }, "Reversión contable registrada.")) {
      setReverseName(""); setReverseReason("")
    }
  }
  const accountOptions = (type: string) => data?.accounts.filter((row) => row.root_type === type) || []
  const canSpend = data?.active && data.responsible === data.user
  const returned = data?.renditions.filter((row) => row.status === "Returned" && row.responsible === data.user) || []
  const reimbursable = data?.renditions.filter((row) => row.status === "Approved" || row.status === "Partially Reimbursed") || []
  const pendingHandovers = data?.handovers.filter((row) => row.status === "Awaiting Acceptance") || []
  const handoversToAccept = pendingHandovers.filter((row) =>
    row.outgoing === data?.user && !row.outgoing_accepted ||
    row.incoming === data?.user && !row.incoming_accepted)
  const availableSections = pettySections.filter((item) => {
    if (item.id === "config") return canSetup
    if (item.id === "history") return true
    if (!data?.active) return false
    if (item.id === "initial-fund" || item.id === "replenishment") return canFinance
    if (item.id === "expense" || item.id === "rendition-new") return Boolean(canSpend)
    if (item.id === "rendition-correct" || item.id === "rendition-resubmit") return Boolean(canSpend && returned.length)
    if (item.id === "handover-request") return canApprove
    if (item.id === "handover-accept") return handoversToAccept.length > 0
    if (item.id === "handover-cancel") return canApprove && pendingHandovers.length > 0
    return canApprove
  })
  const defaultSection = (data?.active ? availableSections.find((item) => item.id === "expense")?.id ||
    availableSections.find((item) => item.id === (data.initial_fund_exists ? "replenishment" : "initial-fund"))?.id : undefined) || availableSections[0]?.id
  const requestedSection = searchParams.get("section")
  const resolvedSection = requestedSection === "fund" ? "initial-fund" :
    requestedSection === "rendition" ? "rendition-new" :
      requestedSection === "handover" ? (canApprove ? "handover-request" : "handover-accept") : requestedSection
  const section = availableSections.find((item) => item.id === resolvedSection)?.id || defaultSection
  useEffect(() => {
    if (!data || !requestedSection || requestedSection === section) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section)
    setSearchParams(next, { replace: true })
  }, [data, requestedSection, section, searchParams, setSearchParams])
  const sectionIds = availableSections.map((item) => item.id).join(",")
  useEffect(() => {
    if (data && defaultSection) onSectionsChange?.(property.name, sectionIds.split(","), defaultSection)
  }, [data, defaultSection, onSectionsChange, property.name, sectionIds])
  const sectionDetails = availableSections.find((item) => item.id === section)
  const reverseOptions = reverseType === "HS Petty Cash Expense" ? data?.expenses.filter((row) =>
      row.status === "Posted" && row.business_date === property.business_date &&
      (!row.rendition || data?.renditions.find((item) => item.name === row.rendition)?.status === "Returned")) || []
    : reverseType === "HS Treasury Movement" ? data?.funds.filter((row) =>
        row.status === "Posted" && row.business_date === property.business_date &&
        (row.kind !== "Initial Fund" || !data?.expenses.some((item) => item.status === "Posted") &&
          !data?.funds.some((item) => item.kind === "Replenishment" && item.status === "Posted"))) || []
      : data?.renditions.filter((row) => row.status === "Approved" &&
          row.approved_business_date === property.business_date &&
          (provider === "pms" ? row.pms_variance_journal : row.variance_journal)) || []
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Caja Chica</h1><p className="mt-1 text-sm text-muted-foreground">Un fondo por establecimiento, en {data?.currency || property.currency}. Los desembolsos afectan el gasto al entregar dinero; la rendición documenta el arqueo y la reposición cubre solo gastos aprobados.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 w-full" /> : <>
      <div className="grid gap-4 md:grid-cols-4">
        {[ ["Responsable", data.responsible || "Sin asignar"], ["Saldo contable", `${data.currency} ${data.balance}`], ["Efectivo esperado", `${data.currency} ${data.expected_cash}`], ["Sin rendir", `${data.currency} ${data.pending_expenses}`] ].map(([label, value]) => <Card key={label}><CardContent className="pt-5"><p className="text-xs text-muted-foreground">{label}</p><strong className="mt-2 block text-lg">{value}</strong></CardContent></Card>)}
      </div>
      {!data.reconciled && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">El saldo operativo y el mayor no coinciden. Concilie antes de operar.</p>}
      {sectionDetails && <div className="border-b border-border pb-3">
        <h2 className="text-xl font-semibold">{sectionDetails.label}</h2>
        <p className="text-sm text-muted-foreground">{sectionDetails.description}</p>
      </div>}
      {section === "config" && canSetup && <Card><CardHeader><CardTitle>Configuración</CardTitle><CardDescription>Cuenta exclusiva, responsable activo y cuentas de sobrante y faltante. Con saldo, el responsable cambia mediante traspaso.</CardDescription></CardHeader><CardContent><form onSubmit={submitConfig} className="grid gap-3 md:grid-cols-2">
        <select required value={pettyAccount} onChange={(event) => setPettyAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de Caja Chica</option>{accountOptions("Asset").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
        <select required value={responsible} onChange={(event) => setResponsible(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Responsable</option>{data.users.map((row) => <option key={row.name} value={row.name}>{userLabel(row)}</option>)}</select>
        <select required value={overage} onChange={(event) => setOverage(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Ingreso por sobrante</option>{accountOptions("Income").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
        <select required value={shortage} onChange={(event) => setShortage(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Gasto por faltante</option>{accountOptions("Expense").map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select>
        <Button disabled={busy} className="md:col-span-2">Guardar configuración</Button>
      </form></CardContent></Card>}
      {data.active && <>
        {(section === "initial-fund" || section === "replenishment") && canFinance && <Card><CardHeader><CardTitle>{section === "initial-fund" ? "Fondo inicial" : "Reposición"}</CardTitle><CardDescription>{section === "initial-fund" ? "Caja entrega el fondo una sola vez desde un turno propio abierto." : "Caja entrega todo o parte de los gastos aprobados pendientes contra una rendición."}</CardDescription></CardHeader><CardContent>
          {section === "initial-fund" && data.initial_fund_exists ? <p className="text-sm text-muted-foreground">El fondo inicial de este establecimiento ya fue entregado. Consulte Historial para ver el movimiento.</p> : <form onSubmit={(event) => void submitFund(event, section === "initial-fund" ? "Initial Fund" : "Replenishment")} className="space-y-3">
          {section === "replenishment" && <select required value={fundRendition} onChange={(event) => setFundRendition(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Rendición aprobada</option>{reimbursable.map((row) => <option key={row.name} value={row.name}>{row.name} · Gastos {data.currency} {row.expense_total}</option>)}</select>}
          {section === "replenishment" && !reimbursable.length && <p className="text-sm text-muted-foreground">No hay gastos aprobados pendientes de reposición.</p>}
          <select required value={fundMethod} onChange={(event) => setFundMethod(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Medio de efectivo {data.currency}</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment}</option>)}</select>
          <select required value={fundShift} onChange={(event) => setFundShift(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno propio abierto</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select>
          {(!data.methods.length || !data.shifts.length) && <p className="text-sm text-muted-foreground">Se necesita un medio de efectivo en {data.currency} y un turno propio abierto para entregar dinero.</p>}
          <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${data.currency}`} value={fundAmount} onChange={(event) => setFundAmount(event.target.value)} />
          <Input required maxLength={140} placeholder="Referencia de entrega" value={fundReference} onChange={(event) => setFundReference(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={fundReason} onChange={(event) => setFundReason(event.target.value)} />
          <Button disabled={busy || !fundMethod || !fundShift || (section === "replenishment" && !fundRendition)}>{section === "initial-fund" ? "Entregar fondo inicial" : "Registrar reposición"}</Button>
        </form>}</CardContent></Card>}
        {section === "expense" && canSpend && <Card><CardHeader><CardTitle>Desembolso menor</CardTitle><CardDescription>Use las categorías de gasto de Caja. La referencia escrita del comprobante es obligatoria; el archivo es opcional.</CardDescription></CardHeader><CardContent><form onSubmit={submitExpense} className="space-y-3">
          <select required value={category} onChange={(event) => setCategory(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Categoría</option>{data.categories.map((row) => <option key={row.name} value={row.name}>{row.label}{row.max_amount ? ` · Límite ${data.currency} ${row.max_amount}` : ""}</option>)}</select>
          <Input required maxLength={140} placeholder="Beneficiario" value={beneficiary} onChange={(event) => setBeneficiary(event.target.value)} />
          <Input required maxLength={500} placeholder="Concepto" value={concept} onChange={(event) => setConcept(event.target.value)} />
          <Input required maxLength={140} placeholder="Referencia del comprobante" value={receiptReference} onChange={(event) => setReceiptReference(event.target.value)} />
          <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${data.currency}`} value={expenseAmount} onChange={(event) => setExpenseAmount(event.target.value)} />
          <Button disabled={busy || !category}>Registrar desembolso</Button>
        </form></CardContent></Card>}
      </>}
      {data.active && <>
        {section === "rendition-new" && canSpend && <Card><CardHeader><CardTitle>Presentar rendición</CardTitle><CardDescription>Agrupa los gastos aún no rendidos y congela el efectivo contado, esperado y la diferencia.</CardDescription></CardHeader><CardContent><form onSubmit={(event) => void submitRendition(event, null)} className="space-y-3">
          <Input required type="number" min="0" step="0.01" placeholder={`Efectivo contado (${data.currency})`} value={countedCash} onChange={(event) => setCountedCash(event.target.value)} />
          <Input maxLength={500} placeholder="Explicación de diferencia, si existe" value={explanation} onChange={(event) => setExplanation(event.target.value)} />
          <Button disabled={busy}>Presentar a Gerencia</Button>
        </form></CardContent></Card>}
        {section === "rendition-correct" && canSpend && <Card><CardHeader><CardTitle>Corregir comprobante devuelto</CardTitle><CardDescription>Actualice la referencia escrita antes de reenviar la rendición. Un cambio de importe requiere reversión autorizada.</CardDescription></CardHeader><CardContent><form onSubmit={submitCorrection} className="space-y-3">
          <select required value={returnedExpense} onChange={(event) => setReturnedExpense(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Desembolso</option>{data.expenses.filter((row) => row.status === "Posted" && returned.some((item) => item.name === row.rendition)).map((row) => <option key={row.name} value={row.name}>{row.beneficiary} · {row.receipt_reference}</option>)}</select>
          <Input required maxLength={140} placeholder="Referencia corregida" value={correctReference} onChange={(event) => setCorrectReference(event.target.value)} />
          <Button disabled={busy || !returnedExpense}>Guardar corrección</Button>
        </form></CardContent></Card>}
        {section === "rendition-resubmit" && canSpend && <Card><CardHeader><CardTitle>Reenviar rendición</CardTitle><CardDescription>Confirme de nuevo el efectivo contado y explique cualquier diferencia de una rendición devuelta.</CardDescription></CardHeader><CardContent><form onSubmit={(event) => void submitRendition(event, rendition)} className="space-y-3">
          <select required value={rendition} onChange={(event) => setRendition(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Rendición devuelta</option>{returned.map((row) => <option key={row.name} value={row.name}>{row.name} · Gastos {data.currency} {row.expense_total}</option>)}</select>
          <Input required type="number" min="0" step="0.01" placeholder={`Efectivo contado (${data.currency})`} value={countedCash} onChange={(event) => setCountedCash(event.target.value)} />
          <Input maxLength={500} placeholder="Explicación de diferencia, si existe" value={explanation} onChange={(event) => setExplanation(event.target.value)} />
          <Button disabled={busy || !rendition}>Reenviar a Gerencia</Button>
        </form></CardContent></Card>}
        {section === "review" && canApprove && <Card><CardHeader><CardTitle>Revisar rendiciones</CardTitle><CardDescription>Un usuario distinto del responsable aprueba o devuelve. La diferencia aprobada publica su asiento antes de quedar aprobada.</CardDescription></CardHeader><CardContent className="space-y-3"><Input maxLength={500} placeholder="Nota de revisión" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />{data.renditions.filter((row) => row.status === "Submitted").map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span><strong>{row.name}</strong> · {row.responsible}<span className="block text-xs text-muted-foreground">Gastos {data.currency} {row.expense_total} · Conteo {row.counted_cash} · Diferencia {row.variance}</span></span><span className="flex gap-2"><Button size="sm" disabled={busy || !reviewNote.trim() || row.submitted_by === data.user} onClick={() => void run("pms_petty_review", { rendition: row.name, approve: 1, note: reviewNote.trim() }, "Rendición aprobada.")}>Aprobar</Button><Button size="sm" variant="outline" disabled={busy || !reviewNote.trim() || row.submitted_by === data.user} onClick={() => void run("pms_petty_review", { rendition: row.name, approve: 0, note: reviewNote.trim() }, "Rendición devuelta.")}>Devolver</Button></span></div>)}{!data.renditions.some((row) => row.status === "Submitted") && <p className="text-sm text-muted-foreground">Sin rendiciones por revisar.</p>}</CardContent></Card>}
        {section === "handover-request" && canApprove && <Card><CardHeader><CardTitle>Solicitar traspaso</CardTitle><CardDescription>Gerencia solicita el cambio con arqueo exacto. Los responsables saliente y entrante deben aceptarlo.</CardDescription></CardHeader><CardContent>
          {pendingHandovers.length > 0 ? <p className="text-sm text-muted-foreground">Ya existe un traspaso pendiente. Espere las aceptaciones o cancélelo antes de solicitar otro.</p> : <form onSubmit={submitHandover} className="space-y-3"><select required value={incoming} onChange={(event) => setIncoming(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Responsable entrante</option>{data.users.filter((row) => row.name !== data.responsible).map((row) => <option key={row.name} value={row.name}>{userLabel(row)}</option>)}</select><Input required type="number" min="0" step="0.01" placeholder={`Efectivo contado (${data.currency})`} value={handoverCount} onChange={(event) => setHandoverCount(event.target.value)} /><Input required maxLength={500} placeholder="Motivo del traspaso" value={handoverReason} onChange={(event) => setHandoverReason(event.target.value)} /><Button disabled={busy || !incoming}>Solicitar traspaso</Button></form>}
        </CardContent></Card>}
        {section === "reverse" && canApprove && <Card><CardHeader><CardTitle>Reversión autorizada</CardTitle><CardDescription>Solo movimientos sin dependencias y dentro de la fecha operativa abierta.</CardDescription></CardHeader><CardContent><form onSubmit={submitReverse} className="space-y-3"><select value={reverseType} onChange={(event) => { setReverseType(event.target.value); setReverseName("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="HS Petty Cash Expense">Desembolso</option><option value="HS Treasury Movement">Fondo o reposición</option><option value="HS Petty Cash Rendition">Diferencia aprobada</option></select><select required value={reverseName} onChange={(event) => setReverseName(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Movimiento</option>{reverseOptions.map((row) => <option key={row.name} value={row.name}>{"reference" in row ? row.reference : "beneficiary" in row ? row.beneficiary : row.name}</option>)}</select><Input required maxLength={500} placeholder="Motivo de reversión" value={reverseReason} onChange={(event) => setReverseReason(event.target.value)} /><Button disabled={busy || !reverseName}>Publicar reversión</Button></form></CardContent></Card>}
      </>}
      {section === "handover-accept" && handoversToAccept.map((row) => <Card key={row.name}><CardHeader><CardTitle>Traspaso {row.outgoing} → {row.incoming}</CardTitle><CardDescription>Arqueo {data.currency} {row.counted_cash} · {row.outgoing_accepted ? "Saliente aceptó" : "Saliente pendiente"} · {row.incoming_accepted ? "Entrante aceptó" : "Entrante pendiente"}</CardDescription></CardHeader><CardContent><Button disabled={busy} onClick={() => void run("pms_petty_accept", { handover: row.name }, "Traspaso aceptado.")}>Aceptar traspaso</Button></CardContent></Card>)}
      {section === "handover-cancel" && canApprove && pendingHandovers.length > 0 && <Card><CardHeader><CardTitle>Cancelar traspaso</CardTitle><CardDescription>Anule una solicitud pendiente con un motivo. El responsable actual permanecerá asignado.</CardDescription></CardHeader><CardContent><form onSubmit={submitHandoverCancel} className="space-y-3">
        <select required value={handoverCancelName} onChange={(event) => setHandoverCancelName(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Traspaso pendiente</option>{pendingHandovers.map((row) => <option key={row.name} value={row.name}>{row.outgoing} → {row.incoming} · {row.name}</option>)}</select>
        <Input required maxLength={500} placeholder="Motivo de cancelación" value={handoverCancelReason} onChange={(event) => setHandoverCancelReason(event.target.value)} />
        <Button variant="outline" disabled={busy || !handoverCancelName || !handoverCancelReason.trim()}>Cancelar traspaso</Button>
      </form></CardContent></Card>}
      {section === "history" && <div className="grid gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle>Desembolsos</CardTitle></CardHeader><CardContent className="space-y-2">{data.expenses.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.beneficiary}</strong> · {row.concept} · {row.category_label}<span className="block text-xs text-muted-foreground">{data.currency} {row.amount} · {row.receipt_reference} · {row.status}{row.rendition && ` · ${row.rendition}`}</span></p>)}{!data.expenses.length && <p className="text-sm text-muted-foreground">Sin desembolsos.</p>}</CardContent></Card><Card><CardHeader><CardTitle>Rendiciones y reposiciones</CardTitle></CardHeader><CardContent className="space-y-2">{data.renditions.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm"><strong>{row.name}</strong> · {stateLabel[row.status] || row.status}<span className="block text-xs text-muted-foreground">Gastos {data.currency} {row.expense_total} · Diferencia {row.variance}</span></p>)}{data.funds.map((row) => <p key={row.name} className="border-b border-border py-2 text-sm">{row.kind === "Initial Fund" ? "Fondo inicial" : "Reposición"} · {row.reference} · {data.currency} {row.amount} · {row.status}</p>)}{!data.renditions.length && !data.funds.length && <p className="text-sm text-muted-foreground">Sin rendiciones ni entregas.</p>}</CardContent></Card></div>}
    </>}
  </div>
}
