import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"
import { productSections } from "./ProductSections"

type Product = { name: string; modified: string; product_code: string; product_name: string;
  product_type: string; income_account: string; expense_account?: string; inventory_account?: string;
  tax_profile: string | null;
  sales_rate: number; active: boolean }
type Account = { name: string; account_code: string; account_name: string }
type Binding = "lodging_item" | "extra_hour_item" | "timing_item" | "day_pass_item" | "penalty_item"
type Snapshot = { products: Product[];
  tax_profiles: { name: string; label: string; treatment: string; rate: number;
    included_in_price: boolean }[];
  income_accounts: Account[]; asset_accounts: Account[]; expense_accounts: Account[];
  bindings: Record<Binding, string | null>; property_modified: string }
const bindingLabels: [Binding, string][] = [
  ["lodging_item", "Alojamiento"], ["extra_hour_item", "Hora adicional"],
  ["timing_item", "Entrada o salida fuera de horario"],
  ["day_pass_item", "Day pass sin habitación"],
  ["penalty_item", "Penalización por cancelación o no presentación"],
]

export function Products({ property }: { property: Property }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get("section")
  const section = productSections.find((item) => item.id === requested) || productSections[0]
  const [data, setData] = useState<Snapshot | null>(null)
  const [bindings, setBindings] = useState<Record<Binding, string | null>>({
    lodging_item: null, extra_hour_item: null, timing_item: null, day_pass_item: null,
    penalty_item: null,
  })
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [productType, setProductType] = useState<"Service" | "Stock">("Service")
  const [account, setAccount] = useState("")
  const [inventoryAccount, setInventoryAccount] = useState("")
  const [expenseAccount, setExpenseAccount] = useState("")
  const [taxProfile, setTaxProfile] = useState("")
  const [rate, setRate] = useState("")
  const [rates, setRates] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const refresh = useCallback(async () => {
    const snapshot = await call<Snapshot>("pms_products", { property_name: property.name })
    setData(snapshot)
    setBindings(snapshot.bindings)
    setRates(Object.fromEntries(snapshot.products.map((row) => [row.name, String(row.sales_rate || "")])))
  }, [property.name])
  useEffect(() => {
    setData(null); setCode(""); setName(""); setProductType("Service"); setAccount("");
    setInventoryAccount(""); setExpenseAccount(""); setTaxProfile(""); setRate(""); setRates({}); setError(""); setNotice("")
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los productos."))
  }, [refresh])
  useEffect(() => {
    if (!requested || requested === section.id) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section.id)
    setSearchParams(next, { replace: true })
  }, [requested, section.id, searchParams, setSearchParams])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "product",
        request_key: crypto.randomUUID(),
        data: { product_code: code.trim(), product_name: name.trim(),
          product_type: productType, income_account: account,
          ...(productType === "Stock" ? { inventory_account: inventoryAccount,
            expense_account: expenseAccount } : {}),
          tax_profile: taxProfile || null, sales_rate: rate, active: 1 } })
      setCode(""); setName(""); setAccount(""); setInventoryAccount(""); setExpenseAccount("");
      setTaxProfile(""); setRate("")
      await refresh(); setNotice("Producto PMS creado.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear el servicio.") }
    finally { setBusy(false) }
  }

  async function saveBindings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !data) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "property",
        request_key: crypto.randomUUID(), expected_modified: data.property_modified,
        data: Object.fromEntries(bindingLabels.map(([field]) => [field, bindings[field] || null])) })
      await refresh(); setNotice("Productos de alojamiento y tiempo actualizados.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la configuración.") }
    finally { setBusy(false) }
  }
  async function assignTax(product: Product, profile: string) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "product",
        request_key: crypto.randomUUID(), expected_modified: product.modified,
        data: { name: product.name, tax_profile: profile || null } })
      await refresh(); setNotice(`Perfil tributario actualizado para ${product.product_name}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar el producto.") }
    finally { setBusy(false) }
  }
  async function saveRate(product: Product) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "product",
        request_key: crypto.randomUUID(), expected_modified: product.modified,
        data: { name: product.name, sales_rate: rates[product.name] } })
      await refresh(); setNotice(`Precio actualizado para ${product.product_name}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar el precio.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">Configure servicios y productos de inventario con sus cuentas, precio e impuesto.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-64 w-full" /> : <div className="max-w-5xl space-y-5">
      {section.id === "new" && <Card><CardHeader><CardTitle>Nuevo producto</CardTitle><CardDescription>Las cuentas deben estar activas en la moneda base.</CardDescription></CardHeader>
        <CardContent><form onSubmit={create} className="space-y-3">
          <label className="block space-y-1 text-sm"><span>Tipo</span><select value={productType} onChange={(event) => setProductType(event.target.value as "Service" | "Stock")} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="Service">Servicio</option><option value="Stock">Inventario</option></select></label>
          <label className="block space-y-1 text-sm"><span>Código</span><Input required maxLength={40} value={code} onChange={(event) => setCode(event.target.value)} /></label>
          <label className="block space-y-1 text-sm"><span>Nombre</span><Input required maxLength={140} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="block space-y-1 text-sm"><span>Precio por unidad ({property.currency})</span><Input required type="number" min="0.01" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} /></label>
          <label className="block space-y-1 text-sm"><span>Cuenta de ingresos</span>
            <select required value={account} onChange={(event) => setAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">
              <option value="">Seleccione una cuenta</option>{data.income_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}
            </select></label>
          {productType === "Stock" && <>
            <label className="block space-y-1 text-sm"><span>Cuenta de inventario</span><select required value={inventoryAccount} onChange={(event) => setInventoryAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione activo</option>{data.asset_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select></label>
            <label className="block space-y-1 text-sm"><span>Cuenta de costo</span><select required value={expenseAccount} onChange={(event) => setExpenseAccount(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione gasto</option>{data.expense_accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select></label>
          </>}
          <label className="block space-y-1 text-sm"><span>Perfil tributario</span>
            <select value={taxProfile} onChange={(event) => setTaxProfile(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2">
              <option value="">Sin clasificar</option>{data.tax_profiles.map((row) => <option key={row.name} value={row.name}>{row.label} · {row.rate}%{row.included_in_price ? " incluido" : " adicional"}</option>)}
            </select></label>
          <Button disabled={busy}>Crear producto</Button>
        </form></CardContent></Card>}
      {section.id === "bindings" && <Card><CardHeader><CardTitle>Productos de la estancia</CardTitle><CardDescription>Las nuevas reservas conservan el producto aceptado en su cotización.</CardDescription></CardHeader>
        <CardContent><form onSubmit={saveBindings} className="space-y-3">
          {bindingLabels.map(([field, label]) => <label key={field} className="block space-y-1 text-sm"><span>{label}</span>
            <select value={bindings[field] || ""} onChange={(event) => setBindings((current) => ({ ...current, [field]: event.target.value || null }))}
              className="h-9 w-full rounded-md border border-border bg-white px-2">
              <option value="">Sin configurar</option>{data.products.filter((row) => row.active && row.product_type === "Service" && row.income_account).map((row) =>
                <option key={row.name} value={row.name}>{row.product_code} · {row.product_name}</option>)}
            </select></label>)}
          <Button disabled={busy}>Guardar asignaciones</Button>
        </form></CardContent></Card>}
      {section.id === "catalog" && <Card><CardHeader><CardTitle>Catálogo</CardTitle></CardHeader><CardContent className="space-y-2">
        {data.products.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
          <span><strong>{row.product_code}</strong> · {row.product_name}<span className="block text-xs text-muted-foreground">{row.active ? "Activo" : "Inactivo"} · {row.product_type} · Ingreso: {row.income_account || "Sin configurar"}{!row.tax_profile ? " · Sin perfil tributario" : ""}</span></span>
          <span className="flex items-center gap-2"><Input aria-label={`Precio de ${row.product_name}`} type="number" min="0" step="0.01" value={rates[row.name] ?? ""} onChange={(event) => setRates((current) => ({ ...current, [row.name]: event.target.value }))} className="w-28" /><Button type="button" variant="outline" disabled={busy || rates[row.name] === String(row.sales_rate || "")} onClick={() => saveRate(row)}>Guardar precio</Button></span>
          <select aria-label={`Perfil tributario de ${row.product_name}`} disabled={busy} value={row.tax_profile || ""} onChange={(event) => assignTax(row, event.target.value)} className="h-9 rounded-md border border-border bg-white px-2 text-sm"><option value="">Sin clasificar</option>{data.tax_profiles.map((item) => <option key={item.name} value={item.name}>{item.label} · {item.rate}%</option>)}</select>
        </div>)}{!data.products.length && <p className="text-sm text-muted-foreground">No hay productos propios aún.</p>}
      </CardContent></Card>}
    </div>}
  </div>
}
