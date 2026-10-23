import { useEffect, useMemo, useState, type FormEvent } from "react"
import { BookOpen, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type LedgerAccount, type Property } from "./api"

type Line = { account: string; debit: string; credit: string; rate: string; memo: string }
const emptyLine = (): Line => ({ account: "", debit: "", credit: "", rate: "1", memo: "" })

function cents(value: string): bigint | null {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return null
  const [whole, fraction = ""] = value.split(".")
  return BigInt(whole) * 100n + BigInt((fraction + "00").slice(0, 2))
}

function baseCents(value: string, rate: string): bigint | null {
  const amount = cents(value || "0")
  if (amount === null || !/^\d+(?:\.\d{1,9})?$/.test(rate)) return null
  const [whole, fraction = ""] = rate.split(".")
  const scaled = BigInt(whole) * 1000000000n + BigInt((fraction + "000000000").slice(0, 9))
  if (scaled <= 0n || scaled >= 1000000000000000000n) return null
  return (amount * scaled + 500000000n) / 1000000000n
}

function formatted(value: bigint) { return `${value / 100n}.${String(value % 100n).padStart(2, "0")}` }

export function Journal({ property }: { property: Property }) {
  const [accounts, setAccounts] = useState<LedgerAccount[] | null>(null)
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [lines, setLines] = useState<Line[]>([emptyLine(), emptyLine()])
  const [requestKey, setRequestKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [posted, setPosted] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setAccounts(null)
    setError("")
    setPosted("")
    setReference("")
    setReason("")
    setLines([emptyLine(), emptyLine()])
    setRequestKey("")
    call<LedgerAccount[]>("pms_accounts", { property_name: property.name }, controller.signal)
      .then(setAccounts)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudieron cargar las cuentas.") })
    return () => controller.abort()
  }, [property.name])

  const prepared = useMemo(() => lines.map((line) => {
    const account = accounts?.find((item) => item.name === line.account)
    const foreign = !!account && account.account_currency !== property.currency
    const rate = foreign ? line.rate : "1"
    const debit = baseCents(line.debit, rate)
    const credit = baseCents(line.credit, rate)
    return { line, account, foreign, rate, debit, credit }
  }), [lines, accounts, property.currency])
  const totals = useMemo(() => prepared.reduce((sum, item) => ({
    debit: sum.debit + (item.debit || 0n), credit: sum.credit + (item.credit || 0n),
  }), { debit: 0n, credit: 0n }), [prepared])
  const valid = reference.trim() && reason.trim() && lines.length >= 2 &&
    prepared.every((item) => item.account?.manual_enabled && item.debit !== null && item.credit !== null &&
      (item.debit! > 0n) !== (item.credit! > 0n)) &&
    totals.debit > 0n && totals.debit === totals.credit

  function changed() { setRequestKey(""); setPosted(""); setError("") }
  function updateLine(index: number, field: keyof Line, value: string) {
    changed()
    setLines((current) => current.map((line, at) => at === index ? {
      ...line, [field]: value,
      ...(field === "account" ? { debit: "", credit: "", rate: "1" } : {}),
      ...(field === "debit" && value ? { credit: "" } : {}),
      ...(field === "credit" && value ? { debit: "" } : {}),
    } : line))
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid || busy) return
    const key = requestKey || crypto.randomUUID()
    setRequestKey(key)
    setBusy(true)
    setError("")
    try {
      const result = await execute<{ journal: string; total: string }>(property.name, "pms_manual_journal", {
        reference: reference.trim(), reason: reason.trim(),
        lines: prepared.map((item) => ({ account: item.line.account,
          debit: formatted(item.debit!), credit: formatted(item.credit!),
          account_currency: item.account!.account_currency, exchange_rate: item.rate,
          debit_in_account_currency: item.line.debit || "0",
          credit_in_account_currency: item.line.credit || "0", memo: item.line.memo.trim() })),
      }, key)
      setPosted(result.journal)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo publicar el asiento.")
    } finally {
      setBusy(false)
    }
  }

  return <div className="space-y-6">
    <div><div className="flex items-center gap-3"><BookOpen className="text-primary" /><h1 className="text-3xl font-semibold tracking-tight">Asiento contable</h1></div>
      <p className="mt-2 text-sm text-muted-foreground">Ajuste manual del {property.business_date} en {property.currency}. El asiento publicado solo puede corregirse mediante reversión.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {posted && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">Asiento {posted} publicado. Conserve la referencia para su auditoría.</p>}
    {!accounts ? <Skeleton className="h-96 rounded-xl" /> : accounts.length === 0 ?
      <Card><CardHeader><CardTitle>Plan de cuentas pendiente</CardTitle><CardDescription>Configure las cuentas de este establecimiento antes de registrar asientos.</CardDescription></CardHeader></Card> :
      <form onSubmit={submit} className="space-y-5">
        <Card><CardHeader><CardTitle>Justificación</CardTitle><CardDescription>La referencia debe identificar el soporte del ajuste y ser única en este establecimiento.</CardDescription></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm font-medium">Referencia<Input required maxLength={140} value={reference} onChange={(event) => { changed(); setReference(event.target.value) }} placeholder="AJ-2026-001" /></label>
            <label className="space-y-2 text-sm font-medium">Motivo<Input required maxLength={500} value={reason} onChange={(event) => { changed(); setReason(event.target.value) }} placeholder="Motivo y documento de respaldo" /></label>
          </CardContent></Card>
        <Card><CardHeader><CardTitle>Partidas</CardTitle><CardDescription>Los débitos y créditos deben coincidir. Las cuentas de Caja, banco e inventario usan sus movimientos propios.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {lines.map((line, index) => <div key={index} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[minmax(180px,2fr)_minmax(90px,1fr)_minmax(90px,1fr)_minmax(90px,1fr)_minmax(130px,1.5fr)_auto]">
              <label className="space-y-1 text-xs text-muted-foreground">Cuenta<select required value={line.account} onChange={(event) => updateLine(index, "account", event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm text-foreground"><option value="">Seleccione cuenta</option>{accounts.map((account) => <option key={account.name} value={account.name} disabled={!account.manual_enabled}>{account.account_code} · {account.account_name}{account.manual_enabled ? "" : " (cuenta de control)"}</option>)}</select></label>
              <label className="space-y-1 text-xs text-muted-foreground">Débito {prepared[index].account?.account_currency || ""}<Input type="number" min="0" step="0.01" value={line.debit} onChange={(event) => updateLine(index, "debit", event.target.value)} /></label>
              <label className="space-y-1 text-xs text-muted-foreground">Crédito {prepared[index].account?.account_currency || ""}<Input type="number" min="0" step="0.01" value={line.credit} onChange={(event) => updateLine(index, "credit", event.target.value)} /></label>
              <label className="space-y-1 text-xs text-muted-foreground">{prepared[index].foreign ? `Cambio a ${property.currency}` : "Tipo de cambio"}<Input type="number" min="0.000000001" step="any" value={line.rate} disabled={!prepared[index].foreign} onChange={(event) => updateLine(index, "rate", event.target.value)} /></label>
              <label className="space-y-1 text-xs text-muted-foreground">Detalle<Input maxLength={140} value={line.memo} onChange={(event) => updateLine(index, "memo", event.target.value)} /></label>
              <Button type="button" variant="ghost" size="icon" className="self-end" aria-label={`Eliminar partida ${index + 1}`} disabled={lines.length <= 2} onClick={() => { changed(); setLines((current) => current.filter((_, at) => at !== index)) }}><Trash2 size={16} /></Button>
            </div>)}
            <Button type="button" variant="outline" onClick={() => { changed(); setLines((current) => [...current, emptyLine()]) }}><Plus size={16} /> Agregar partida</Button>
          </CardContent></Card>
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl bg-secondary p-4 text-sm"><div>Débitos <strong className="ml-2 tabular-nums">{formatted(totals.debit)}</strong><span className="mx-3 text-muted-foreground">·</span>Créditos <strong className="ml-2 tabular-nums">{formatted(totals.credit)}</strong> {property.currency}</div>
          <Button type="submit" disabled={!valid || busy || !!posted}>{busy ? "Publicando…" : posted ? "Publicado" : "Publicar asiento"}</Button></div>
      </form>}
  </div>
}
