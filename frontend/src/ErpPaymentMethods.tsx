import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"

type Method = { name: string; mode_of_payment: string; account: string; currency: string;
  is_cash: number; reference_required: number; fee_percent: number; fee_fixed: number;
  fee_account?: string | null; refund_fee_percent: number; refund_fee_fixed: number;
  withholding_percent: number; withholding_account?: string | null;
  settlement_account?: string | null; modified: string; core_locked: boolean }
type Account = { name: string; account_number?: string; account_name: string;
  root_type: string; account_type?: string; account_currency: string }
type Settings = { methods: Method[]; accounts: Account[];
  modes: { name: string; type?: string }[]; currencies: string[]; base_currency: string }
type Form = { mode_of_payment: string; account: string; currency: string;
  is_cash: boolean; reference_required: boolean; fee_percent: string;
  fee_fixed: string; fee_account: string; refund_fee_percent: string;
  refund_fee_fixed: string; withholding_percent: string;
  withholding_account: string; settlement_account: string }

const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"
const blank = (currency: string): Form => ({ mode_of_payment: "", account: "", currency,
  is_cash: true, reference_required: false, fee_percent: "0", fee_fixed: "0",
  fee_account: "", refund_fee_percent: "0", refund_fee_fixed: "0",
  withholding_percent: "0", withholding_account: "", settlement_account: "" })
const accountLabel = (row: Account) => `${row.account_number ? `${row.account_number} · ` : ""}${row.account_name} · ${row.account_currency}`

export function ErpPaymentMethods({ property, onSaved }: {
  property: Property; onSaved: () => Promise<unknown> }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [selected, setSelected] = useState("")
  const [form, setForm] = useState<Form>(() => blank(property.currency))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pendingKey = useRef("")
  const original = settings?.methods.find((row) => row.name === selected)

  useEffect(() => {
    const controller = new AbortController()
    setSettings(null); setSelected(""); setForm(blank(property.currency))
    setError(""); setNotice(""); pendingKey.current = ""
    call<Settings>("erp_cash_method_settings", { property_name: property.name },
      controller.signal).then((result) => { if (!controller.signal.aborted) setSettings(result) })
      .catch((issue: unknown) => { if (!controller.signal.aborted) setError(issue instanceof Error
        ? issue.message : "No se pudieron consultar los medios de pago.") })
    return () => controller.abort()
  }, [property.name, property.currency])

  function edit(name: string) {
    const method = settings?.methods.find((row) => row.name === name)
    setSelected(name); setNotice(""); setError(""); pendingKey.current = ""
    setForm(method ? { mode_of_payment: method.mode_of_payment, account: method.account,
      currency: method.currency, is_cash: Boolean(method.is_cash),
      reference_required: Boolean(method.reference_required),
      fee_percent: String(method.fee_percent || 0), fee_fixed: String(method.fee_fixed || 0),
      fee_account: method.fee_account || "", refund_fee_percent: String(method.refund_fee_percent || 0),
      refund_fee_fixed: String(method.refund_fee_fixed || 0),
      withholding_percent: String(method.withholding_percent || 0),
      withholding_account: method.withholding_account || "",
      settlement_account: method.settlement_account || "" } : blank(property.currency))
  }

  function change<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value, ...(key === "currency" || key === "is_cash"
      ? { account: "", settlement_account: "" } : {}) }))
    pendingKey.current = ""; setNotice("")
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!settings || busy || !form.mode_of_payment || !form.account ||
        (!form.is_cash && !form.settlement_account)) return
    setBusy(true); setError(""); setNotice("")
    const policy = form.is_cash ? { fee_percent: 0, fee_fixed: 0, fee_account: "",
      refund_fee_percent: 0, refund_fee_fixed: 0, withholding_percent: 0,
      withholding_account: "", settlement_account: "" } : {
      fee_percent: Number(form.fee_percent), fee_fixed: Number(form.fee_fixed),
      fee_account: form.fee_account, refund_fee_percent: Number(form.refund_fee_percent),
      refund_fee_fixed: Number(form.refund_fee_fixed),
      withholding_percent: Number(form.withholding_percent),
      withholding_account: form.withholding_account,
      settlement_account: form.settlement_account,
    }
    if (!pendingKey.current) pendingKey.current = crypto.randomUUID()
    try {
      await postMethod("save_setup", { property_name: property.name,
        section: "payment_method", request_key: pendingKey.current,
        ...(original ? { expected_modified: original.modified } : {}),
        data: { ...(original ? { name: original.name } : {}),
          mode_of_payment: form.mode_of_payment, account: form.account,
          currency: form.currency, is_cash: form.is_cash ? 1 : 0,
          reference_required: form.reference_required ? 1 : 0, ...policy },
      })
      pendingKey.current = ""
      const updated = await call<Settings>("erp_cash_method_settings", {
        property_name: property.name,
      })
      setSettings(updated); setSelected(""); setForm(blank(property.currency))
      setNotice(original ? "Política actualizada para cobros futuros." : "Medio de pago creado.")
      try { await onSaved() } catch { /* The saved policy remains available after reload. */ }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo guardar el medio de pago.")
    } finally { setBusy(false) }
  }

  const accounts = settings?.accounts || []
  const accountOptions = accounts.filter((row) => row.root_type === "Asset" &&
    row.account_currency === form.currency &&
    (row.name === original?.account ||
      (form.is_cash ? row.account_type === "Cash" : row.account_type === "Bank")))
  const settlementOptions = accounts.filter((row) => row.root_type === "Asset" &&
    row.account_type === "Bank" && row.account_currency === form.currency &&
    row.name !== form.account)
  const expenseOptions = accounts.filter((row) => row.root_type === "Expense" &&
    row.account_currency === settings?.base_currency)
  const withholdingOptions = accounts.filter((row) => row.root_type === "Asset" &&
    row.account_currency === settings?.base_currency &&
    !["Bank", "Cash", "Receivable", "Payable"].includes(row.account_type || ""))

  return <Card><CardHeader><CardTitle>Medios de pago ERPNext</CardTitle>
    <CardDescription>Vincule cada medio con una cuenta de efectivo o compensación. Para tarjeta y transferencia, el banco de liquidación permite conciliar el bruto con el abono neto. Los cobros ya registrados conservan su política original.</CardDescription>
  </CardHeader><CardContent className="space-y-4">
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!settings ? (error ? null : <Skeleton className="h-64" />) : <>
      <label className="block space-y-1 text-sm">Medio a configurar<select className={selectClass} value={selected} onChange={(event) => edit(event.target.value)}>
        <option value="">Nuevo medio</option>{settings.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency} · {row.is_cash ? "Efectivo" : "Banco"}</option>)}
      </select></label>
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        {original?.core_locked && <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm sm:col-span-2">Este medio ya tiene cobros. Conserve su cuenta, moneda y clasificación; puede cambiar la política para cobros futuros. Para otra cuenta, cree un medio nuevo.</p>}
        <label className="space-y-1 text-sm">Modo ERPNext<select required className={selectClass} disabled={original?.core_locked} value={form.mode_of_payment} onChange={(event) => change("mode_of_payment", event.target.value)}>
          <option value="">Seleccione modo</option>{settings.modes.map((row) => <option key={row.name} value={row.name}>{row.name}{row.type ? ` · ${row.type}` : ""}</option>)}
        </select></label>
        <label className="space-y-1 text-sm">Moneda<select required className={selectClass} disabled={original?.core_locked} value={form.currency} onChange={(event) => change("currency", event.target.value)}>
          {settings.currencies.map((code) => <option key={code} value={code}>{code}</option>)}
        </select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={original?.core_locked} checked={form.is_cash} onChange={(event) => change("is_cash", event.target.checked)} /> Medio en efectivo</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.reference_required} onChange={(event) => change("reference_required", event.target.checked)} /> Exigir referencia al cobrar</label>
        <label className="space-y-1 text-sm sm:col-span-2">{form.is_cash ? "Cuenta de efectivo" : "Cuenta de compensación del bruto"}<select required className={selectClass} disabled={original?.core_locked} value={form.account} onChange={(event) => change("account", event.target.value)}>
          <option value="">Seleccione cuenta</option>{accountOptions.map((row) => <option key={row.name} value={row.name}>{accountLabel(row)}</option>)}
        </select></label>
        {!form.is_cash && <>
          <label className="space-y-1 text-sm sm:col-span-2">Banco de liquidación<select required className={selectClass} value={form.settlement_account} onChange={(event) => change("settlement_account", event.target.value)}>
            <option value="">Seleccione cuenta bancaria</option>{settlementOptions.map((row) => <option key={row.name} value={row.name}>{accountLabel(row)}</option>)}
          </select></label>
          <label className="space-y-1 text-sm">Comisión sobre bruto original (%)<Input required type="number" min="0" max="100" step="any" value={form.fee_percent} onChange={(event) => change("fee_percent", event.target.value)} /></label>
          <label className="space-y-1 text-sm">Comisión fija por cobro ({form.currency})<Input required type="number" min="0" step="any" value={form.fee_fixed} onChange={(event) => change("fee_fixed", event.target.value)} /></label>
          <label className="space-y-1 text-sm">Cuenta de comisión ({settings.base_currency})<select className={selectClass} value={form.fee_account} onChange={(event) => change("fee_account", event.target.value)}><option value="">Sin comisión</option>{expenseOptions.map((row) => <option key={row.name} value={row.name}>{accountLabel(row)}</option>)}</select></label>
          <label className="space-y-1 text-sm">Retención (%)<Input required type="number" min="0" max="100" step="any" value={form.withholding_percent} onChange={(event) => change("withholding_percent", event.target.value)} /></label>
          <label className="space-y-1 text-sm">Cuenta de retención ({settings.base_currency})<select className={selectClass} value={form.withholding_account} onChange={(event) => change("withholding_account", event.target.value)}><option value="">Sin retención</option>{withholdingOptions.map((row) => <option key={row.name} value={row.name}>{accountLabel(row)}</option>)}</select></label>
          <label className="space-y-1 text-sm">Comisión de devolución (%)<Input required type="number" min="0" max="100" step="any" value={form.refund_fee_percent} onChange={(event) => change("refund_fee_percent", event.target.value)} /></label>
          <label className="space-y-1 text-sm">Comisión fija por devolución ({form.currency})<Input required type="number" min="0" step="any" value={form.refund_fee_fixed} onChange={(event) => change("refund_fee_fixed", event.target.value)} /></label>
        </>}
        <Button disabled={busy || !form.mode_of_payment || !form.account ||
          (!form.is_cash && !form.settlement_account)} className="sm:col-span-2">{original ? "Guardar política" : "Crear medio de pago"}</Button>
      </form>
    </>}
  </CardContent></Card>
}
