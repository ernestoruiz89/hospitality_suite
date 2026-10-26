import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"
import { erpCashSections, useErpCashSection } from "./CashSections"
import { ErpSettlement } from "./ErpSettlement"
import { ErpPaymentMethods } from "./ErpPaymentMethods"
import { CommandKeys } from "./idempotentCommand"
import { useIdempotentCommand } from "./useIdempotentCommand"

type Shift = { name: string; cashier: string; currency: string; status: string;
  opened_at: string; closed_at?: string | null; modified: string }
type ShiftDetail = Shift & { opening_amount: string; expected: Record<string, string>;
  counts: Record<string, { value: string; count: string }[]>;
  differences: Record<string, string>; reason?: string | null;
  approved_by?: string | null }
type Movement = { source: string; name: string; creation: string;
  business_date?: string | null; kind: string; amount: string;
  currency: string; method?: string | null; reference?: string | null;
  status: string }
type ExpenseCategory = { name: string; label: string; currency: string;
  account: string; max_amount: number }
type Snapshot = { currencies: string[];
  methods: { name: string; mode_of_payment: string; currency: string; account: string }[];
  categories: ExpenseCategory[]; user: string;
  cash_transfer_configured: boolean; shifts: Shift[]; selected: ShiftDetail | null;
  unmatched: unknown[]; movements: Movement[]; offset: number; has_more: boolean }
type CashSettings = { account: string; base_currency: string;
  property_modified: string; accounts: { name: string; account_number?: string;
    account_name: string; account_type?: string }[];
  expense_accounts: { name: string; account_number?: string; account_name: string }[];
  categories: { name: string; label: string; account: string; max_amount: number;
    active: number; modified: string }[] }
type ExpenseQuote = { acceptance: string; category_label: string;
  amount: string; currency: string; exchange_rate: string;
  base_amount: string; base_currency: string; debit: string; debit_label: string;
  credit: string; credit_label: string; available_before: string;
  available_after: string; category_limit: string }
type Denomination = { value: string; count: string }

const PAGE_LENGTH = 50

export function ErpCash({ property, canCashApprove, canSetup, canApprove }: {
  property: Property; canCashApprove: boolean; canSetup: boolean; canApprove: boolean }) {
  const navigate = useNavigate()
  const section = useErpCashSection(canSetup)
  const sectionInfo = erpCashSections.find((item) => item.id === section)!
  const [data, setData] = useState<Snapshot | null>(null)
  const [settings, setSettings] = useState<CashSettings | null>(null)
  const [transferAccount, setTransferAccount] = useState("")
  const [shift, setShift] = useState("")
  const [currency, setCurrency] = useState(property.currency)
  const [opening, setOpening] = useState("0")
  const [counts, setCounts] = useState<Record<string, Denomination[]>>({})
  const [closeReason, setCloseReason] = useState("")
  const [approveDifference, setApproveDifference] = useState(false)
  const [method, setMethod] = useState("")
  const [withdrawAmount, setWithdrawAmount] = useState("")
  const [withdrawReason, setWithdrawReason] = useState("")
  const [expenseMethod, setExpenseMethod] = useState("")
  const [expenseCategory, setExpenseCategory] = useState("")
  const [expenseAmount, setExpenseAmount] = useState("")
  const [expenseReason, setExpenseReason] = useState("")
  const [expenseQuote, setExpenseQuote] = useState<ExpenseQuote | null>(null)
  const [categoryName, setCategoryName] = useState("")
  const [categoryLabel, setCategoryLabel] = useState("")
  const [categoryAccount, setCategoryAccount] = useState("")
  const [categoryLimit, setCategoryLimit] = useState("0")
  const [categoryActive, setCategoryActive] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const setupKeys = useRef(new CommandKeys())
  const send = useIdempotentCommand(property.name)

  const refresh = useCallback(async (name = "", offset = 0) => {
    const result = await call<Snapshot>("erp_cash_snapshot", {
      property_name: property.name, shift_name: name,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    })
    setData(result)
    setShift(result.selected?.name || "")
    return result
  }, [property.name])

  useEffect(() => {
    setData(null); setSettings(null); setTransferAccount("")
    setShift(""); setCurrency(property.currency); setOpening("0")
    setCounts({}); setCloseReason(""); setApproveDifference(false)
    setMethod(""); setWithdrawAmount(""); setWithdrawReason("")
    setExpenseMethod(""); setExpenseCategory(""); setExpenseAmount("")
    setExpenseReason(""); setExpenseQuote(null)
    setCategoryName(""); setCategoryLabel(""); setCategoryAccount("")
    setCategoryLimit("0"); setCategoryActive(true)
    setError(""); setNotice("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error
      ? issue.message : "No se pudo consultar la Caja."))
    if (canSetup) call<CashSettings>("erp_cash_settings", {
      property_name: property.name,
    }).then((result) => { setSettings(result); setTransferAccount(result.account) })
      .catch((issue: unknown) => setError(issue instanceof Error
        ? issue.message : "No se pudo consultar la configuración de Caja."))
  }, [refresh, property.currency, property.name, canSetup])

  useEffect(() => {
    setExpenseQuote(null)
  }, [section])

  async function command<T>(action: string, payload: Record<string, unknown>): Promise<T | null> {
    if (busy) return null
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await send<T>(action, payload)
      return result
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo registrar la operación.")
      return null
    } finally { setBusy(false) }
  }

  async function openShift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const result = await command<{ shift: string }>("open_shift", {
      currency, opening_amount: opening,
    })
    if (!result) return
    try {
      await refresh(result.shift)
      setOpening("0")
      setNotice(`Turno ${result.shift} abierto.`)
    } catch { setNotice(`Turno ${result.shift} abierto. Actualice la vista para consultar su saldo.`) }
    navigate("/cash?section=shift-overview")
  }

  async function closeShift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!data?.selected || data.selected.status === "Closed") return
    const denominations = Object.fromEntries(Object.keys(data.selected.expected)
      .map((code) => [code, (counts[code] || []).filter((row) => Number(row.count) > 0)
        .map((row) => ({ value: row.value, count: row.count }))]))
    const result = await command<{ shift: string; status: string;
      differences: Record<string, string> }>("close_shift", {
        shift: data.selected.name, modified: data.selected.modified,
        denominations, reason: closeReason.trim(),
        approve: approveDifference && canCashApprove,
      })
    if (!result) return
    try {
      await refresh(result.shift)
      setCounts({}); setCloseReason(""); setApproveDifference(false)
      setNotice(`Turno ${result.shift}: ${result.status}. Diferencias: ${Object.entries(result.differences).map(([code, value]) => `${code} ${value}`).join(" · ")}.`)
    } catch { setNotice(`Arqueo ${result.shift} registrado. Actualice la vista.`) }
  }

  async function withdraw(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!data?.selected || !method) return
    const result = await command<{ payment: string }>("withdrawal", {
      shift: data.selected.name, method, amount: withdrawAmount,
      reason: withdrawReason.trim(),
    })
    if (!result) return
    try {
      await refresh(data.selected.name)
      setWithdrawAmount(""); setWithdrawReason("")
      setNotice(`Retiro ${result.payment} registrado.`)
    } catch { setNotice(`Retiro ${result.payment} registrado. Actualice la vista.`) }
  }

  function invalidateExpense() {
    setExpenseQuote(null)
  }

  async function registerExpense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!data?.selected || !expenseMethod || !expenseCategory || busy) return
    const values = { shift: data.selected.name, method: expenseMethod,
      category: expenseCategory, amount: expenseAmount, reason: expenseReason.trim() }
    if (!expenseQuote) {
      setBusy(true); setError(""); setNotice("")
      try {
        setExpenseQuote(await call<ExpenseQuote>("preview", {
          property_name: property.name, action: "cash_expense_reviewed",
          data: JSON.stringify(values),
        }))
      } catch (issue) {
        setError(issue instanceof Error ? issue.message : "No se pudo revisar el gasto.")
      } finally { setBusy(false) }
      return
    }
    const result = await command<{ payment: string; journal_entry: string }>(
      "cash_expense_reviewed", { ...values, acceptance: expenseQuote.acceptance })
    if (!result) return
    setExpenseAmount(""); setExpenseReason(""); setExpenseQuote(null)
    try {
      await refresh(data.selected.name)
      setNotice(`Gasto ${result.payment} registrado. Asiento ${result.journal_entry}.`)
    } catch { setNotice(`Gasto ${result.payment} registrado. Actualice Caja para consultar el saldo.`) }
  }

  async function saveExpenseCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !settings) return
    const original = settings.categories.find((row) => row.name === categoryName)
    const values = { ...(original ? { name: original.name } : {}),
      label: categoryLabel.trim(), account: categoryAccount,
      max_amount: categoryLimit, active: categoryActive ? 1 : 0 }
    setBusy(true); setError(""); setNotice("")
    try {
      const saveData = { ...values,
        ...(original ? { expected_modified: original.modified } : {}) }
      await setupKeys.current.run(property.name, "expense_category", saveData,
        (key) => postMethod("save_setup", { property_name: property.name,
          section: "expense_category", data: values,
          request_key: key,
          ...(original ? { expected_modified: original.modified } : {}) }))
      setCategoryName(""); setCategoryLabel(""); setCategoryAccount("")
      setCategoryLimit("0"); setCategoryActive(true)
      setNotice(original ? "Categoría actualizada para gastos futuros." : "Categoría de gasto creada.")
      try {
        const [updated] = await Promise.all([
          call<CashSettings>("erp_cash_settings", { property_name: property.name }),
          refresh(shift),
        ])
        setSettings(updated)
      } catch { setNotice("Categoría guardada. Actualice la vista para consultar el cambio.") }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo guardar la categoría.")
    } finally { setBusy(false) }
  }

  async function saveTransfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !settings || !transferAccount) return
    setBusy(true); setError(""); setNotice("")
    try {
      const saveData = { cash_transfer_account: transferAccount,
        expected_modified: settings.property_modified }
      await setupKeys.current.run(property.name, "property", saveData,
        (key) => postMethod("save_setup", { property_name: property.name,
          section: "property", data: { cash_transfer_account: transferAccount },
          request_key: key, expected_modified: settings.property_modified }))
      try {
        const [updated] = await Promise.all([
          call<CashSettings>("erp_cash_settings", { property_name: property.name }),
          refresh(shift),
        ])
        setSettings(updated); setTransferAccount(updated.account)
        setNotice("Cuenta de traslado de efectivo guardada.")
      } catch { setNotice("Cuenta de traslado guardada. Actualice la vista para consultar el cambio.") }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo guardar la cuenta de traslado.")
    } finally { setBusy(false) }
  }

  async function load(name: string, offset: number) {
    if (busy) return
    setBusy(true); setError(""); invalidateExpense()
    try { await refresh(name, offset) }
    catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo consultar el turno.") }
    finally { setBusy(false) }
  }

  const selected = data?.selected
  const cashMethod = data?.methods.find((row) => row.name === method)
  const expenseCashMethod = data?.methods.find((row) => row.name === expenseMethod)
  const canSpendShift = Boolean(selected && data &&
    (selected.cashier === data.user || canApprove))
  const statusLabel: Record<string, string> = { Open: "Abierto", Review: "En revisión", Closed: "Cerrado" }

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Caja ERPNext</p><h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{`${sectionInfo.description}.`} Los cobros y devoluciones se registran en <Link to="/customer-credits" className="text-primary underline">Cobros y créditos</Link>.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-72 rounded-xl" /> : <>
      {section === "shift-open" && <Card><CardHeader><CardTitle>Abrir turno</CardTitle><CardDescription>Seleccione una moneda habilitada y declare el fondo inicial.</CardDescription></CardHeader><CardContent><form onSubmit={openShift} className="space-y-3">
          <label className="block space-y-1 text-sm">Moneda<select required value={currency} onChange={(event) => setCurrency(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">{data.currencies.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>
          <label className="block space-y-1 text-sm">Fondo inicial<Input required type="number" min="0" step="0.01" value={opening} onChange={(event) => setOpening(event.target.value)} /></label>
          <Button disabled={busy}>Abrir turno</Button>
        </form></CardContent></Card>}
      {section !== "setup" && section !== "method-settings" && section !== "expense-categories" && section !== "shift-open" && <Card><CardHeader><CardTitle>{section === "shift-overview" ? "Consultar turnos" : "Turno seleccionado"}</CardTitle><CardDescription>{section === "shift-overview" ? "Consulte un turno activo o uno de los últimos cerrados." : "Seleccione el turno para esta operación."}</CardDescription></CardHeader><CardContent>
        <div className="space-y-3">
          <select value={shift} onChange={(event) => { setCounts({}); setCloseReason(""); setApproveDifference(false); void load(event.target.value, 0) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Sin turno</option>{data.shifts.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier} · {statusLabel[row.status] || row.status}</option>)}</select>
          {selected && <div className="space-y-2 text-sm"><p>{selected.name} · {statusLabel[selected.status] || selected.status} · {selected.currency} {selected.opening_amount} de apertura</p>
            <div className="flex flex-wrap gap-2">{Object.entries(selected.expected).map(([code, value]) => <span key={code} className="rounded-md bg-secondary px-3 py-2">Esperado {code} {value}</span>)}</div>
            {selected.status !== "Open" && <p>Conteo: {Object.entries(selected.counts).map(([code, rows]) => `${code} ${rows.reduce((total, row) => total + Number(row.value) * Number(row.count), 0).toFixed(2)}`).join(" · ") || "0"} · Diferencia: {Object.entries(selected.differences).map(([code, value]) => `${code} ${value}`).join(" · ") || "0"}</p>}
            {selected.reason && <p>Motivo: {selected.reason}</p>}
          </div>}
        </div>
      </CardContent></Card>}
      {section !== "shift-overview" && section !== "shift-open" && section !== "setup" && section !== "method-settings" && section !== "expense-categories" && !selected &&
        <p className="rounded-lg border border-border bg-white p-4 text-sm text-muted-foreground">Seleccione un turno para continuar.</p>}
      {section === "method-settings" && canSetup && <ErpPaymentMethods key={property.name}
        property={property} onSaved={() => refresh(shift)} />}
      {section === "settlement" && <ErpSettlement key={property.name} property={property}
        shift={selected?.status === "Open" ? selected.name : ""}
        canOperate={Boolean(selected?.status === "Open" && canSpendShift)}
        onPosted={() => refresh(selected?.name || "")} />}
      {section === "setup" && canSetup && settings && <Card><CardHeader><CardTitle>Cuenta de traslado</CardTitle><CardDescription>Gerencia configura la cuenta de activo en {settings.base_currency} que recibirá los retiros del turno.</CardDescription></CardHeader><CardContent><form onSubmit={saveTransfer} className="flex flex-wrap items-end gap-3"><label className="min-w-64 flex-1 space-y-1 text-sm">Cuenta<select required value={transferAccount} onChange={(event) => setTransferAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{settings.accounts.map((row) => <option key={row.name} value={row.name}>{row.account_number || ""} · {row.account_name} · {row.account_type || "Activo"}</option>)}</select></label><Button disabled={busy || !transferAccount || transferAccount === settings.account}>Guardar cuenta</Button></form></CardContent></Card>}
      {section === "expense-categories" && canSetup && settings && <Card><CardHeader><CardTitle>Categorías de gasto de Caja</CardTitle><CardDescription>Comparten las cuentas y límites con Caja Chica. Los cambios se aplican a desembolsos futuros.</CardDescription></CardHeader><CardContent className="space-y-4">
        <label className="block space-y-1 text-sm">Categoría a editar<select value={categoryName} onChange={(event) => {
          const row = settings.categories.find((item) => item.name === event.target.value)
          setCategoryName(row?.name || ""); setCategoryLabel(row?.label || "")
          setCategoryAccount(row?.account || ""); setCategoryLimit(String(row?.max_amount || 0))
          setCategoryActive(row ? Boolean(row.active) : true)
        }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Nueva categoría</option>{settings.categories.map((row) => <option key={row.name} value={row.name}>{row.label}{row.active ? "" : " · Inactiva"}</option>)}</select></label>
        <form onSubmit={saveExpenseCategory} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">Nombre<Input required maxLength={140} value={categoryLabel} onChange={(event) => setCategoryLabel(event.target.value)} /></label>
          <label className="space-y-1 text-sm">Cuenta de gasto<select required value={categoryAccount} onChange={(event) => setCategoryAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{settings.expense_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_number ? `${row.account_number} · ` : ""}{row.account_name}</option>)}</select></label>
          <label className="space-y-1 text-sm">Límite por gasto ({settings.base_currency}; cero sin límite)<Input required type="number" min="0" step="any" value={categoryLimit} onChange={(event) => setCategoryLimit(event.target.value)} /></label>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={categoryActive} onChange={(event) => setCategoryActive(event.target.checked)} /> Categoría activa</label>
          <Button disabled={busy || !categoryLabel.trim() || !categoryAccount} className="sm:col-span-2">{categoryName ? "Guardar cambios" : "Crear categoría"}</Button>
        </form>
      </CardContent></Card>}
      {selected && section !== "setup" && section !== "method-settings" && section !== "expense-categories" && section !== "shift-open" && <>
        {section === "close" && data.unmatched.length > 0 && <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">Hay {data.unmatched.length} movimientos nativos sin conciliación operativa en este turno. Revise <Link to={`/reports?${new URLSearchParams({ section: "revenue", report: "Conciliación" })}`} className="underline">Conciliación</Link> antes del cierre.</p>}
        {selected.status !== "Closed" && (section === "close" || section === "withdraw") && <div className="space-y-4">
          {section === "close" && <Card><CardHeader><CardTitle>Arqueo y cierre</CardTitle><CardDescription>Cuente físicamente cada denominación. Una diferencia exige motivo y aprobación de Gerencia para cerrar.</CardDescription></CardHeader><CardContent><form onSubmit={closeShift} className="space-y-3">
            {Object.entries(selected.expected).map(([code, expected]) => <div key={code} className="space-y-2 rounded-md border p-3 text-sm"><p className="font-medium">{code} · Esperado {expected}</p>
              {(counts[code] || []).map((row, index) => <div key={index} className="flex gap-2"><Input required type="number" min="0.01" step="0.01" aria-label={`Denominación ${code}`} placeholder="Valor" value={row.value} onChange={(event) => setCounts((current) => ({ ...current, [code]: current[code].map((item, at) => at === index ? { ...item, value: event.target.value } : item) }))} /><Input required type="number" min="0" step="1" aria-label={`Cantidad ${code}`} placeholder="Cantidad" value={row.count} onChange={(event) => setCounts((current) => ({ ...current, [code]: current[code].map((item, at) => at === index ? { ...item, count: event.target.value } : item) }))} /><Button type="button" variant="outline" onClick={() => setCounts((current) => ({ ...current, [code]: current[code].filter((_, at) => at !== index) }))}>Quitar</Button></div>)}
              <Button type="button" size="sm" variant="outline" onClick={() => setCounts((current) => ({ ...current, [code]: [...(current[code] || []), { value: "", count: "" }] }))}>Añadir denominación</Button>
              <p>Contado {code} {(counts[code] || []).reduce((total, row) => total + Number(row.value || 0) * Number(row.count || 0), 0).toFixed(2)}</p>
            </div>)}
            <Input maxLength={500} placeholder="Motivo de diferencia, si existe" value={closeReason} onChange={(event) => setCloseReason(event.target.value)} />
            {canCashApprove && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={approveDifference} onChange={(event) => setApproveDifference(event.target.checked)} /> Aprobar diferencia con permiso de Gerencia</label>}
            <Button disabled={busy || data.unmatched.length > 0}>Arquear turno</Button>
          </form></CardContent></Card>}
          {section === "withdraw" && selected.status === "Open" && <Card><CardHeader><CardTitle>Retiro de efectivo</CardTitle><CardDescription>Traspase efectivo del turno a la cuenta de traslado configurada. El asiento queda vinculado al turno.</CardDescription></CardHeader><CardContent><form onSubmit={withdraw} className="space-y-3">
            <label className="block space-y-1 text-sm">Medio de efectivo<select required value={method} onChange={(event) => setMethod(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
            {cashMethod && <p className="text-sm text-muted-foreground">Disponible {cashMethod.currency} {selected.expected[cashMethod.currency] || "0"}</p>}
            <Input required type="number" min="0.01" step="0.01" placeholder="Importe" value={withdrawAmount} onChange={(event) => setWithdrawAmount(event.target.value)} />
            <Input required maxLength={500} placeholder="Motivo del retiro" value={withdrawReason} onChange={(event) => setWithdrawReason(event.target.value)} />
            {!data.cash_transfer_configured && <p className="text-sm text-amber-800">Gerencia debe configurar la cuenta de traslado de efectivo.</p>}
            <Button disabled={busy || !data.cash_transfer_configured || !method}>Registrar retiro</Button>
          </form></CardContent></Card>}
        </div>}
        {section === "expense" && <Card><CardHeader><CardTitle>Gasto de Caja</CardTitle><CardDescription>Seleccione una categoría compartida con Caja Chica. El gasto se contabiliza al entregar el efectivo.</CardDescription></CardHeader><CardContent className="space-y-3">
          {selected.status !== "Open" && <p className="text-sm text-muted-foreground">Seleccione un turno abierto para registrar el gasto.</p>}
          {!canSpendShift && <p className="text-sm text-amber-800">Solo puede desembolsar desde su turno. Gerencia puede operar otros turnos autorizados.</p>}
          {!data.categories.length && <p className="text-sm text-muted-foreground">No hay categorías activas. {canSetup && <Link className="text-primary underline" to="/cash?section=expense-categories">Configurar categorías</Link>}</p>}
          {selected.status === "Open" && canSpendShift && data.categories.length > 0 && <form onSubmit={registerExpense} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">Categoría<select required value={expenseCategory} onChange={(event) => { invalidateExpense(); setExpenseCategory(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione categoría</option>{data.categories.map((row) => <option key={row.name} value={row.name}>{row.label}{row.max_amount ? ` · Máximo ${row.currency} ${row.max_amount}` : ""}</option>)}</select></label>
            <label className="space-y-1 text-sm">Medio en efectivo<select required value={expenseMethod} onChange={(event) => { invalidateExpense(); setExpenseMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency} · Disponible {selected.expected[row.currency] || "0"}</option>)}</select></label>
            <label className="space-y-1 text-sm">Importe ({expenseCashMethod?.currency || "moneda del medio"})<Input required type="number" min="0.001" step="any" value={expenseAmount} onChange={(event) => { invalidateExpense(); setExpenseAmount(event.target.value) }} /></label>
            <label className="space-y-1 text-sm">Motivo y comprobante<Input required maxLength={500} value={expenseReason} onChange={(event) => { invalidateExpense(); setExpenseReason(event.target.value) }} /></label>
            {expenseQuote && <div className="rounded-md border border-primary/30 bg-secondary p-3 text-sm sm:col-span-2"><p><strong>{expenseQuote.category_label}</strong> · {expenseQuote.currency} {expenseQuote.amount} · Base {expenseQuote.base_currency} {expenseQuote.base_amount} · Cambio {expenseQuote.exchange_rate}</p><p>Débito: {expenseQuote.debit_label} · Crédito: {expenseQuote.credit_label}</p><p>Efectivo esperado: {expenseQuote.currency} {expenseQuote.available_before} → {expenseQuote.available_after}</p><p>Límite de categoría: {expenseQuote.base_currency} {Number(expenseQuote.category_limit) === 0 ? "sin límite" : expenseQuote.category_limit}</p></div>}
            <Button disabled={busy || !expenseCategory || !expenseMethod} className="sm:col-span-2">{expenseQuote ? "Confirmar gasto" : "Revisar asiento"}</Button>
          </form>}
        </CardContent></Card>}
        {section === "close" && selected.status === "Closed" &&
          <p className="rounded-lg border border-border bg-white p-4 text-sm text-muted-foreground">Este turno ya está cerrado. El conteo y la diferencia se muestran arriba.</p>}
        {section === "withdraw" && selected.status !== "Open" &&
          <p className="rounded-lg border border-border bg-white p-4 text-sm text-muted-foreground">Solo un turno abierto permite retirar efectivo.</p>}
        {section === "history" && <Card><CardHeader><CardTitle>Movimientos del turno</CardTitle><CardDescription>Cobros, egresos, financiación y ventas POS. Consulte <Link to="/reports?section=treasury" className="text-primary underline">Reportes</Link> para el historial completo.</CardDescription></CardHeader><CardContent className="space-y-3">
          <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-sm"><thead><tr className="border-b text-left"><th className="py-2">Registro</th><th>Fecha</th><th>Tipo</th><th>Importe</th><th>Estado</th></tr></thead><tbody>{data.movements.map((row, index) => <tr key={`${row.source}-${row.name}-${index}`} className="border-b"><td className="py-2">{row.name}<span className="block text-xs text-muted-foreground">{row.source}{row.reference ? ` · ${row.reference}` : ""}</span></td><td>{row.business_date || row.creation}</td><td>{row.kind}</td><td>{row.currency} {row.amount}</td><td>{row.status}</td></tr>)}</tbody></table>{!data.movements.length && <p className="py-5 text-sm text-muted-foreground">Sin movimientos registrados.</p>}</div>
          <div className="flex items-center justify-between text-sm"><span>Desde {data.offset + (data.movements.length ? 1 : 0)} · {data.movements.length} registros</span><div className="flex gap-2"><Button variant="outline" disabled={busy || data.offset === 0} onClick={() => void load(selected.name, Math.max(0, data.offset - PAGE_LENGTH))}>Anterior</Button><Button variant="outline" disabled={busy || !data.has_more} onClick={() => void load(selected.name, data.offset + PAGE_LENGTH)}>Siguiente</Button></div></div>
        </CardContent></Card>}
      </>}
    </>}
  </div>
}
