import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type Snapshot = {
  currency: string
  accounts: { name: string; account_code: string; account_name: string; root_type: string; account_type: string;
    is_cash: boolean; is_bank: boolean }[]
  customers: { name: string; party_name: string }[]
  receivables: { name: string; party: string; reference: string; description: string;
    amount: number; outstanding: string; receivable_account: string }[]
  advances: { name: string; pms_party: string; reference: string; currency: string;
    amount: number; available: string; pms_counter_account: string }[]
  cancelled: { name: string; party: string; reference: string; amount: number;
    currency: string; reversal_journal: string }[]
}

export function Receivables({ property, canCreate, canCancel }: { property: Property; canCreate: boolean; canCancel: boolean }) {
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
  const [receivable, setReceivable] = useState("")
  const [advance, setAdvance] = useState("")
  const [applyAmount, setApplyAmount] = useState("")
  const [reason, setReason] = useState("")
  const [cancelId, setCancelId] = useState("")
  const [cancelReason, setCancelReason] = useState("")
  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("pms_receivables", { property_name: property.name }))
  }, [property.name])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setParty(""); setReceivable(""); setAdvance(""); setCancelId("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar las cuentas."))
  }, [refresh])
  async function createCustomer() {
    if (!newCustomer.trim() || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ party: string }>(property.name, "pms_customer",
        { party_name: newCustomer.trim() }, crypto.randomUUID())
      await refresh(); setParty(result.party); setNewCustomer(""); setNotice("Cliente registrado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el cliente.") }
    finally { setBusy(false) }
  }
  async function createReceivable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ receivable: string }>(property.name, "pms_receivable",
        { party, reference, description, amount, receivable_account: receivableAccount,
          income_account: incomeAccount }, crypto.randomUUID())
      await refresh(); setReference(""); setDescription(""); setAmount("");
      setNotice(`Cuenta ${result.receivable} registrada. No es una factura fiscal.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la cuenta.") }
    finally { setBusy(false) }
  }
  async function applyAdvance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_apply_advance",
        { receivable, advance, amount: applyAmount, reason }, crypto.randomUUID())
      await refresh(); setApplyAmount(""); setReason(""); setNotice("Anticipo aplicado y contabilizado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aplicar el anticipo.") }
    finally { setBusy(false) }
  }
  async function cancelReceivable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canCancel) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "pms_cancel_receivable",
        { receivable: cancelId, reason: cancelReason }, crypto.randomUUID())
      await refresh(); setCancelId(""); setCancelReason("");
      setNotice("Cargo cancelado mediante asiento inverso.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cancelar el cargo.") }
    finally { setBusy(false) }
  }
  const selected = data?.receivables.find((item) => item.name === receivable)
  const matchingAdvances = data?.advances.filter((item) => item.pms_party === selected?.party && Number(item.available) > 0) || []
  const selectedAdvance = matchingAdvances.find((item) => item.name === advance)
  const customerName = (id: string) => data?.customers.find((item) => item.name === id)?.party_name || id
  const accountName = (id: string) => data?.accounts.find((item) => item.name === id)?.account_name || id
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Cuentas por cobrar</h1><p className="mt-2 text-sm text-muted-foreground">Cargos internos en {property.currency}, cobros parciales y aplicación de anticipos. La factura fiscal se emite por separado.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-72 rounded-xl" /> : <>
      <div className="grid gap-5 lg:grid-cols-2">
        {canCreate && <Card><CardHeader><CardTitle>Registrar cargo interno</CardTitle><CardDescription>Débito a cuentas por cobrar y crédito a ingreso. Use el flujo fiscal correspondiente antes de entregar una factura al cliente.</CardDescription></CardHeader><CardContent><form onSubmit={createReceivable} className="grid gap-3">
          <select required value={party} onChange={(event) => setParty(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Seleccione cliente</option>{data.customers.map((item) => <option key={item.name} value={item.name}>{item.party_name}</option>)}</select>
          <div className="flex gap-2"><Input aria-label="Nuevo cliente" maxLength={140} placeholder="Nuevo cliente" value={newCustomer} onChange={(event) => setNewCustomer(event.target.value)} /><Button type="button" variant="outline" disabled={busy || !newCustomer.trim()} onClick={createCustomer}>Crear</Button></div>
          <Input required maxLength={140} placeholder="Referencia del cargo" value={reference} onChange={(event) => setReference(event.target.value)} />
          <Input required maxLength={500} placeholder="Descripción" value={description} onChange={(event) => setDescription(event.target.value)} />
          <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${property.currency}`} value={amount} onChange={(event) => setAmount(event.target.value)} />
          <select required value={receivableAccount} onChange={(event) => setReceivableAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta por cobrar</option>{data.accounts.filter((item) => item.account_type === "Receivable" && !item.is_cash && !item.is_bank).map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select>
          <select required value={incomeAccount} onChange={(event) => setIncomeAccount(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta de ingreso</option>{data.accounts.filter((item) => item.root_type === "Income").map((item) => <option key={item.name} value={item.name}>{item.account_code} · {item.account_name}</option>)}</select>
          <Button disabled={busy}>Registrar cargo</Button>
        </form></CardContent></Card>}
        <Card><CardHeader><CardTitle>Aplicar anticipo</CardTitle><CardDescription>El anticipo reduce el saldo por cobrar; no mueve efectivo del turno.</CardDescription></CardHeader><CardContent><form onSubmit={applyAdvance} className="grid gap-3">
          <select required value={receivable} onChange={(event) => { setReceivable(event.target.value); setAdvance("") }} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Cuenta pendiente</option>{data.receivables.filter((item) => Number(item.outstanding) > 0).map((item) => <option key={item.name} value={item.name}>{item.reference} · {customerName(item.party)} · {property.currency} {item.outstanding}</option>)}</select>
          <select required value={advance} onChange={(event) => setAdvance(event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Anticipo del cliente</option>{matchingAdvances.map((item) => <option key={item.name} value={item.name}>{item.reference} · {item.currency} {item.amount} · Disponible {property.currency} {item.available}</option>)}</select>
          <Input required type="number" min="0.01" step="0.01" placeholder={`Aplicar ${property.currency}`} value={applyAmount} onChange={(event) => setApplyAmount(event.target.value)} />
          <Input required maxLength={500} placeholder="Motivo" value={reason} onChange={(event) => setReason(event.target.value)} />
          {selected && selectedAdvance && applyAmount && <p className="rounded-lg bg-secondary p-3 text-sm">Asiento: débito {accountName(selectedAdvance.pms_counter_account)} · crédito {accountName(selected.receivable_account)} · {property.currency} {applyAmount}</p>}
          <Button disabled={busy || !matchingAdvances.length}>Aplicar y contabilizar</Button>
        </form></CardContent></Card>
      </div>
      <Card><CardHeader><CardTitle>Saldos pendientes</CardTitle><CardDescription>Puede cobrar una misma cuenta en varios medios desde Caja.</CardDescription></CardHeader><CardContent className="space-y-2">{data.receivables.map((item) => <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm"><div><strong>{item.reference}</strong><span className="ml-2 text-muted-foreground">{customerName(item.party)} · {item.description}</span></div><div className="flex items-center gap-3"><span>{property.currency} {item.outstanding} / {item.amount}</span>{Number(item.outstanding) > 0 && <Button asChild size="sm" variant="outline"><Link to="/cash">Cobrar</Link></Button>}{canCancel && Number(item.outstanding) === Number(item.amount) && <Button size="sm" variant="outline" onClick={() => { setCancelId(item.name); setCancelReason("") }}>Cancelar</Button>}</div></div>)}{!data.receivables.length && <p className="text-sm text-muted-foreground">Sin cuentas registradas.</p>}{cancelId && <form onSubmit={cancelReceivable} className="flex flex-wrap gap-2 rounded-lg border border-border p-3"><Input required maxLength={500} placeholder="Motivo de cancelación" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} className="min-w-48 flex-1" /><Button disabled={busy}>Confirmar cancelación</Button><Button type="button" variant="ghost" onClick={() => setCancelId("")}>Volver</Button></form>}</CardContent></Card>
      {!!data.cancelled.length && <Card><CardHeader><CardTitle>Cargos cancelados</CardTitle><CardDescription>Conservan su asiento inverso para auditoría.</CardDescription></CardHeader><CardContent className="space-y-2">{data.cancelled.map((item) => <div key={item.name} className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm"><span>{item.reference} · {customerName(item.party)}</span><span>{item.currency} {item.amount} · Asiento {item.reversal_journal}</span></div>)}</CardContent></Card>}
    </>}
  </div>
}
