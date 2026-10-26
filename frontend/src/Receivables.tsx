import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { OpeningCreditsPms } from "./OpeningCreditsPms"
import { OpeningGuaranteesPms } from "./OpeningGuaranteesPms"
import { availableReceivableSections } from "./ReceivableSections"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Snapshot = {
  currency: string
  accounts: { name: string; account_code: string; account_name: string; root_type: string; account_type: string;
    is_cash: boolean; is_bank: boolean }[]
  customers: { name: string; party_name: string }[]
  tax_profiles: { name: string; label: string; treatment: string; rate: number;
    included_in_price: boolean }[]
  receivables: { name: string; party: string; folio: string | null; folio_stay: string | null; booking: string | null;
    reference: string; description: string;
    amount: number; currency: string; base_amount: number | null;
    outstanding: string; receivable_account: string;
    opening_source_name: string | null; historical_document: string | null }[]
  advances: { name: string; pms_party: string; reference: string; currency: string;
    amount: number; available: string; pms_counter_account: string;
    folio: string | null; booking: string | null }[]
  guarantees: { name: string; pms_party: string; reference: string; currency: string;
    amount: number; available: string; pms_counter_account: string;
    folio: string | null; booking: string | null }[]
  applied_advances: { name: string; receivable: string; payment: string; remaining: string }[]
  applied_guarantees: { name: string; receivable: string; payment: string; remaining: string }[]
  cancelled: { name: string; party: string; reference: string; amount: number;
    currency: string; reversal_journal: string }[]
  opening_credits: { credits: { name: string; credit_kind: string; customer: string;
    opening_source_name: string; currency: string; amount: number; available: string;
    base_amount: number; base_available: string;
    receivable_account: string; historical_document: string | null }[];
    applications: { name: string; opening_credit: string; receivable: string;
      remaining: string }[] }
  opening_guarantees: { name: string; customer: string; opening_source_name: string;
    source_booking: string | null; source_stay: string | null; source_folio: string | null;
    amount: number; available: string; liability_account: string }[]
  opening_guarantee_applications: { name: string; opening_guarantee: string;
    receivable: string; remaining: number }[]
  refund_methods: { name: string; mode_of_payment: string; currency: string;
    is_cash: boolean }[]
  refund_shifts: { name: string; opened_at: string }[]
}

export function Receivables({ property, canCreate, canCancel }: { property: Property; canCreate: boolean; canCancel: boolean }) {
  const send = useIdempotentCommand(property.name)
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = useMemo(() => availableReceivableSections(canCreate, canCancel), [canCreate, canCancel])
  const section = sections.find((item) => item.id === searchParams.get("section")) || sections[0]
  const [data, setData] = useState<Snapshot | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [party, setParty] = useState("")
  const [newCustomer, setNewCustomer] = useState("")
  const [reference, setReference] = useState("")
  const [description, setDescription] = useState("")
  const [amount, setAmount] = useState("")
  const [receivableAccount, setReceivableAccount] = useState("")
  const [incomeAccount, setIncomeAccount] = useState("")
  const [taxProfile, setTaxProfile] = useState("")
  const [receivable, setReceivable] = useState("")
  const [advance, setAdvance] = useState("")
  const [depositKind, setDepositKind] = useState<"Advance" | "Guarantee">("Advance")
  const [applyAmount, setApplyAmount] = useState("")
  const [reason, setReason] = useState("")
  const [cancelId, setCancelId] = useState("")
  const [cancelReason, setCancelReason] = useState("")
  const [unapplyId, setUnapplyId] = useState("")
  const [unapplyKind, setUnapplyKind] = useState<"Advance" | "Guarantee">("Advance")
  const [unapplyAmount, setUnapplyAmount] = useState("")
  const [unapplyReason, setUnapplyReason] = useState("")
  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("pms_receivables", { property_name: property.name }))
  }, [property.name])
  async function refreshAfter(success: string) {
    try { await refresh(); setNotice(success) }
    catch { setNotice(`${success} Actualice la vista para consultar el saldo.`) }
  }
  useEffect(() => {
    if (!searchParams.has("section") || sections.some((item) => item.id === searchParams.get("section"))) return
    const next = new URLSearchParams(searchParams)
    next.set("section", sections[0].id)
    setSearchParams(next, { replace: true })
  }, [searchParams, sections, setSearchParams])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setParty(""); setReceivable(""); setAdvance(""); setDepositKind("Advance"); setUnapplyKind("Advance"); setCancelId(""); setTaxProfile("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar las cuentas."))
  }, [refresh])
  async function createCustomer() {
    if (!newCustomer.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<{ party: string }>("pms_customer", { party_name: newCustomer.trim() })
      setParty(result.party); setNewCustomer("")
      await refreshAfter("Cliente registrado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el cliente.") }
    finally { setBusy(false) }
  }
  async function createReceivable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<{ receivable: string }>("pms_receivable",
        { party, reference, description, amount, receivable_account: receivableAccount,
          income_account: incomeAccount, tax_profile: taxProfile || null })
      setReference(""); setDescription(""); setAmount("")
      await refreshAfter(`Cuenta ${result.receivable} registrada. No es una factura fiscal.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la cuenta.") }
    finally { setBusy(false) }
  }
  async function applyAdvance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send(depositKind === "Guarantee" ? "pms_apply_guarantee" : "pms_apply_advance",
        { receivable, [depositKind === "Guarantee" ? "guarantee" : "advance"]: advance,
          amount: applyAmount, reason })
      setApplyAmount(""); setReason("")
      await refreshAfter("Depósito aplicado y contabilizado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aplicar el depósito.") }
    finally { setBusy(false) }
  }
  async function cancelReceivable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canCancel) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_cancel_receivable", { receivable: cancelId, reason: cancelReason })
      setCancelId(""); setCancelReason("")
      await refreshAfter("Cargo cancelado mediante asiento inverso.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cancelar el cargo.") }
    finally { setBusy(false) }
  }
  async function unapplyAdvance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canCancel) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send(unapplyKind === "Guarantee" ? "pms_unapply_guarantee" : "pms_unapply_advance",
        { allocation: unapplyId, amount: unapplyAmount, reason: unapplyReason })
      setUnapplyId(""); setUnapplyAmount(""); setUnapplyReason("")
      await refreshAfter("Aplicación revertida mediante un asiento nuevo.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revertir la aplicación.") }
    finally { setBusy(false) }
  }
  const selected = data?.receivables.find((item) => item.name === receivable)
  const deposits = depositKind === "Guarantee" ? data?.guarantees : data?.advances
  const matchingDeposits = deposits?.filter((item) => item.pms_party === selected?.party &&
    (depositKind !== "Guarantee" || (!!selected?.folio && item.folio === selected.folio) ||
      (!!selected?.booking && item.booking === selected.booking)) &&
    Number(item.available) > 0) || []
  const selectedDeposit = matchingDeposits.find((item) => item.name === advance)
  const appliedDeposits = unapplyKind === "Guarantee" ? data?.applied_guarantees : data?.applied_advances
  const customerName = (id: string) => data?.customers.find((item) => item.name === id)?.party_name || id
  const accountName = (id: string) => data?.accounts.find((item) => item.name === id)?.account_name || id
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1><p className="mt-2 text-sm text-muted-foreground">Cuentas por cobrar · {property.property_name}. Los saldos trasladados de ERPNext conservan su moneda y copia fiscal; no se emiten otra vez.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data && !error && <Skeleton className="h-72 rounded-xl" />}
    {data && <>
      {section.id === "create" && canCreate && <Card><CardHeader><CardTitle>Registrar cargo interno</CardTitle><CardDescription>Débito a cuentas por cobrar y crédito a ingreso. Use el flujo fiscal correspondiente antes de entregar una factura al cliente.</CardDescription></CardHeader><CardContent><form onSubmit={createReceivable} className="grid max-w-2xl gap-3">
          <select required value={party} onChange={(event) => setParty(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione cliente</option>{data.customers.map((item) => <option key={item.name} value={item.name}>{item.party_name}</option>)}</select>
          <div className="flex gap-2"><Input aria-label="Nuevo cliente" maxLength={140} placeholder="Nuevo cliente" value={newCustomer} onChange={(event) => setNewCustomer(event.target.value)} /><Button type="button" variant="outline" disabled={busy || !newCustomer.trim()} onClick={createCustomer}>Crear</Button></div>
          <Input required maxLength={140} placeholder="Referencia del cargo" value={reference} onChange={(event) => setReference(event.target.value)} />
          <Input required maxLength={500} placeholder="Descripción" value={description} onChange={(event) => setDescription(event.target.value)} />
          <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${property.currency}`} value={amount} onChange={(event) => setAmount(event.target.value)} />
          <select required value={receivableAccount} onChange={(event) => setReceivableAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por cobrar</option>{data.accounts.filter((item) => item.account_type === "Receivable" && !item.is_cash && !item.is_bank).map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select>
          <select required value={incomeAccount} onChange={(event) => setIncomeAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de ingreso</option>{data.accounts.filter((item) => item.root_type === "Income").map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select>
          <select value={taxProfile} onChange={(event) => setTaxProfile(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Sin clasificación tributaria</option>{data.tax_profiles.map((item) => <option key={item.name} value={item.name}>{item.label} · {item.rate}%{item.included_in_price ? " incluido" : " adicional"}</option>)}</select>
          <Button disabled={busy}>Registrar cargo</Button>
        </form></CardContent></Card>}
      {section.id === "apply" && <Card><CardHeader><CardTitle>Aplicar depósito</CardTitle><CardDescription>El anticipo o la garantía reduce el saldo por cobrar sin mover efectivo del turno. La garantía solo se aplica a su cuenta de estancia y requiere Gerencia.</CardDescription></CardHeader><CardContent><form onSubmit={applyAdvance} className="grid max-w-2xl gap-3">
          <select value={depositKind} onChange={(event) => { setDepositKind(event.target.value as "Advance" | "Guarantee"); setAdvance("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="Advance">Anticipo</option>{canCancel && <option value="Guarantee">Garantía</option>}</select>
          <select required value={receivable} onChange={(event) => { setReceivable(event.target.value); setAdvance("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta pendiente</option>{data.receivables.filter((item) => item.currency === property.currency && Number(item.outstanding) > 0).map((item) => <option key={item.name} value={item.name}>{item.reference} · {customerName(item.party)} · {item.currency} {item.outstanding}</option>)}</select>
          <select required value={advance} onChange={(event) => setAdvance(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">{depositKind === "Guarantee" ? "Garantía de la cuenta" : "Anticipo del cliente"}</option>{matchingDeposits.map((item) => <option key={item.name} value={item.name}>{item.reference} · {item.currency} {item.amount} · Disponible {property.currency} {item.available}</option>)}</select>
          <Input required type="number" min="0.01" step="0.01" placeholder={`Aplicar ${property.currency}`} value={applyAmount} onChange={(event) => setApplyAmount(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => setReason(event.target.value)} />
          {selected && selectedDeposit && applyAmount && <p className="rounded-lg bg-secondary p-3 text-sm">Asiento: débito {accountName(selectedDeposit.pms_counter_account)} · crédito {accountName(selected.receivable_account)} · {property.currency} {applyAmount}</p>}
          <Button disabled={busy || !matchingDeposits.length}>Aplicar y contabilizar</Button>
        </form></CardContent></Card>}
      {section.id === "opening-credits" && <OpeningCreditsPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="apply" />}
      {section.id === "opening-credit-refunds" && <OpeningCreditsPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="refund" />}
      {section.id === "opening-credit-reversals" && <OpeningCreditsPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="reverse" />}
      {section.id === "opening-guarantees" && <OpeningGuaranteesPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="apply" />}
      {section.id === "opening-guarantee-refunds" && <OpeningGuaranteesPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="refund" />}
      {section.id === "opening-guarantee-reversals" && <OpeningGuaranteesPms property={property} data={data} refresh={refresh} send={send} canApprove={canCancel} mode="reverse" />}
      {section.id === "balances" && <Card><CardHeader><CardTitle>Saldos pendientes</CardTitle><CardDescription>Las cuentas extranjeras muestran el saldo original y su valor inicial en moneda base.</CardDescription></CardHeader><CardContent className="space-y-2">{data.receivables.map((item) => <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm"><div><strong>{item.reference}</strong><span className="ml-2 text-muted-foreground">{customerName(item.party)} · {item.description}</span>{item.opening_source_name && <p className="text-xs text-muted-foreground">Saldo trasladado de ERPNext · {item.historical_document ? <a className="text-primary underline" target="_blank" rel="noopener noreferrer" href={`/api/method/hospitality_suite.api.historical_fiscal_pdf?document=${encodeURIComponent(item.historical_document)}`}>Imprimir copia fiscal</a> : "Consulte el archivo fiscal"}</p>}</div><div className="flex items-center gap-3"><span>{item.currency} {item.outstanding} / {item.amount}{item.currency !== property.currency && item.base_amount != null && <small className="block text-muted-foreground">Valor inicial {property.currency} {item.base_amount}</small>}</span>{Number(item.outstanding) > 0 && <Button asChild size="sm" variant="outline"><Link to="/cash?section=collect">Cobrar</Link></Button>}{canCancel && !item.opening_source_name && Number(item.outstanding) === Number(item.amount) && <Button size="sm" variant="outline" onClick={() => { setCancelId(item.name); setCancelReason("") }}>Cancelar</Button>}</div></div>)}{!data.receivables.length && <p className="text-sm text-muted-foreground">Sin cuentas registradas.</p>}{cancelId && <form onSubmit={cancelReceivable} className="flex flex-wrap gap-2 rounded-lg border border-border p-3"><Input required maxLength={500} placeholder="Motivo de cancelación" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} className="min-w-48 flex-1" /><Button disabled={busy}>Confirmar cancelación</Button><Button type="button" variant="ghost" onClick={() => setCancelId("")}>Volver</Button></form>}</CardContent></Card>}
      {section.id === "unapply" && canCancel && <Card><CardHeader><CardTitle>Revertir depósito aplicado</CardTitle><CardDescription>Restituye la cuenta por cobrar y la obligación con el cliente mediante un asiento nuevo.</CardDescription></CardHeader><CardContent><form onSubmit={unapplyAdvance} className="grid max-w-2xl gap-3 sm:grid-cols-3"><select value={unapplyKind} onChange={(event) => { setUnapplyKind(event.target.value as "Advance" | "Guarantee"); setUnapplyId("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm sm:col-span-3"><option value="Advance">Anticipo</option><option value="Guarantee">Garantía</option></select><select required value={unapplyId} onChange={(event) => { setUnapplyId(event.target.value); setUnapplyAmount("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm sm:col-span-3"><option value="">Aplicación original</option>{appliedDeposits?.map((item) => <option key={item.name} value={item.name}>{data.receivables.find((row) => row.name === item.receivable)?.reference || item.receivable} · {data.advances.concat(data.guarantees).find((row) => row.name === item.payment)?.reference || item.payment} · Pendiente {property.currency} {item.remaining}</option>)}</select><Input required type="number" min="0.01" step="0.01" max={appliedDeposits?.find((item) => item.name === unapplyId)?.remaining} placeholder={`Importe ${property.currency}`} value={unapplyAmount} onChange={(event) => setUnapplyAmount(event.target.value)} /><Input required maxLength={500} placeholder="Motivo" value={unapplyReason} onChange={(event) => setUnapplyReason(event.target.value)} /><Button disabled={busy || !unapplyId}>Revertir</Button></form>{!data.applied_advances.length && !data.applied_guarantees.length && <p className="mt-4 text-sm text-muted-foreground">No hay depósitos aplicados para revertir.</p>}</CardContent></Card>}
      {section.id === "cancelled" && canCancel && <Card><CardHeader><CardTitle>Cargos cancelados</CardTitle><CardDescription>Conservan su asiento inverso para auditoría.</CardDescription></CardHeader><CardContent className="space-y-2">{data.cancelled.map((item) => <div key={item.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span>{item.reference} · {customerName(item.party)}</span><span>{item.currency} {item.amount} · Asiento {item.reversal_journal}</span></div>)}{!data.cancelled.length && <p className="text-sm text-muted-foreground">No hay cargos cancelados.</p>}</CardContent></Card>}
    </>}
  </div>
}
