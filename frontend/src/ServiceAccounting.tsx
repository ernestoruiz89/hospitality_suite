import { useCallback, useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { FinancialLookup } from "./FinancialLookup"

type Service = { item: string; item_name?: string | null;
  income_account: string | null; expense_account: string | null;
  cost_center: string | null }
type Config = { modified: string; company: string;
  defaults: Record<string, string | null>; services: Service[] }
type Row = { key: string; item: string; income_account: string;
  expense_account: string; cost_center: string }

const toRow = (item: Service): Row => ({ key: crypto.randomUUID(),
  item: item.item, income_account: item.income_account || "",
  expense_account: item.expense_account || "", cost_center: item.cost_center || "" })

export function ServiceAccounting({ property }: { property: Property }) {
  const [config, setConfig] = useState<Config | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await call<Config>("service_accounting_configuration",
      { property_name: property.name }, signal)
    if (signal?.aborted) return
    setConfig(result)
    setRows(result.services.map(toRow))
  }, [property.name])

  useEffect(() => {
    const controller = new AbortController()
    setConfig(null); setRows([]); setError(""); setNotice("")
    pending.current = null
    load(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error
        ? issue.message : "No se pudo consultar la contabilidad de servicios.")
    })
    return () => controller.abort()
  }, [load])

  function change(key: string, field: keyof Omit<Row, "key">, value: string) {
    setRows((current) => current.map((row) => row.key === key
      ? { ...row, [field]: value } : row))
  }

  async function save() {
    if (!config || busy) return
    const services = rows.map((row) => ({ item: row.item.trim(),
      income_account: row.income_account.trim(),
      expense_account: row.expense_account.trim(),
      cost_center: row.cost_center.trim() }))
    if (services.some((row) => !row.item || !row.income_account &&
        !row.expense_account && !row.cost_center) ||
        new Set(services.map((row) => row.item)).size !== services.length) {
      setError("Seleccione artículos distintos y al menos una cuenta o centro de costo por fila.")
      return
    }
    setBusy(true); setError(""); setNotice("")
    const data = { modified: config.modified, defaults: {}, services }
    const signature = JSON.stringify([property.name, "service_accounting", data])
    if (pending.current?.signature !== signature) pending.current = {
      signature, key: crypto.randomUUID(),
    }
    try {
      await execute(property.name, "service_accounting", data, pending.current.key)
      await load()
      pending.current = null
      setNotice("Cuentas por servicio guardadas.")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudieron guardar las cuentas por servicio.")
    } finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Contabilidad por servicio</CardTitle>
    <CardDescription>Asigne cuentas o centro de costo a artículos concretos. Los campos vacíos heredan los valores generales del establecimiento.</CardDescription>
  </CardHeader><CardContent className="space-y-4">
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!config ? <Skeleton className="h-32" /> : <>
      <p className="text-xs text-muted-foreground">Compañía: {config.company}. Se admiten hasta 500 servicios; el servidor comprueba compañía, tipo y moneda de cada cuenta.</p>
      <div className="space-y-3">{rows.map((row) => <div key={row.key} className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2 lg:grid-cols-4">
        <FinancialLookup propertyName={property.name} field="service_accounting_item" label="Artículo o servicio" idSuffix={row.key}
          value={row.item} onChange={(value) => change(row.key, "item", value)} />
        <FinancialLookup propertyName={property.name} field="income_account" label="Ingreso" idSuffix={row.key}
          value={row.income_account} onChange={(value) => change(row.key, "income_account", value)} />
        <FinancialLookup propertyName={property.name} field="expense_account" label="Gasto" idSuffix={row.key}
          value={row.expense_account} onChange={(value) => change(row.key, "expense_account", value)} />
        <FinancialLookup propertyName={property.name} field="cost_center" label="Centro de costo" idSuffix={row.key}
          value={row.cost_center} onChange={(value) => change(row.key, "cost_center", value)} />
        <Button type="button" variant="outline" size="sm" disabled={busy} className="lg:col-span-4"
          onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}>Quitar fila</Button>
      </div>)}</div>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={busy || rows.length >= 500}
        onClick={() => setRows((current) => [...current, {
          key: crypto.randomUUID(), item: "", income_account: "",
          expense_account: "", cost_center: "",
        }])}>Añadir servicio</Button>
        <Button type="button" disabled={busy} onClick={() => void save()}>Guardar contabilidad por servicio</Button>
      </div>
    </>}
  </CardContent></Card>
}
