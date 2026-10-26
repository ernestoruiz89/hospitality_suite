import { useEffect, useState } from "react"
import { Coins } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type Settings = { base_currency: string; accepted_currencies: string[];
  available_currencies: string[] }

export function PropertyCurrencies({ property }: { property: Property }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [search, setSearch] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setSettings(null); setSelected([]); setSearch(""); setError(""); setNotice("")
    call<Settings>("erp_property_currency_settings", {
      property_name: property.name,
    }, controller.signal).then((result) => {
      setSettings(result); setSelected(result.accepted_currencies)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las monedas.")
    })
    return () => controller.abort()
  }, [property.name])

  function toggle(currency: string) {
    if (currency === settings?.base_currency) return
    setSelected((current) => current.includes(currency)
      ? current.filter((code) => code !== currency)
      : [...current, currency])
    setNotice("")
  }

  async function save() {
    if (!settings || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "erp_property_currencies", {
        currencies: [...new Set([...selected, settings.base_currency])].sort(),
      }, crypto.randomUUID())
      const result = await call<Settings>("erp_property_currency_settings", {
        property_name: property.name,
      })
      setSettings(result); setSelected(result.accepted_currencies)
      setNotice("Monedas habilitadas actualizadas para el establecimiento.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron guardar las monedas.") }
    finally { setBusy(false) }
  }

  const visible = settings?.available_currencies.filter((code) =>
    code.toLowerCase().includes(search.trim().toLowerCase())) || []
  return <div className="space-y-6">
    <div className="flex items-center gap-3"><Coins className="text-primary" /><div><h1 className="text-3xl font-semibold">Monedas del establecimiento</h1><p className="mt-1 text-sm text-muted-foreground">Habilite las monedas que este hotel acepta después del corte a ERPNext. La moneda base permanece activa.</p></div></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!settings ? <Skeleton className="h-64 rounded-xl" /> : <Card><CardHeader><CardTitle>Monedas aceptadas</CardTitle><CardDescription>Base: {settings.base_currency}. Seleccione hasta 12 monedas. Las monedas utilizadas por medios o movimientos de Suite no pueden retirarse.</CardDescription></CardHeader><CardContent className="space-y-4">
      <Input aria-label="Buscar código de moneda" placeholder="Buscar moneda" value={search} onChange={(event) => setSearch(event.target.value)} className="max-w-sm" />
      <div className="grid max-h-80 gap-2 overflow-y-auto sm:grid-cols-3 lg:grid-cols-4">{visible.map((code) => <label key={code} className="flex items-center gap-2 rounded-md border p-2 text-sm"><input type="checkbox" checked={selected.includes(code)} disabled={code === settings.base_currency || busy || !selected.includes(code) && selected.length >= 12} onChange={() => toggle(code)} />{code}{code === settings.base_currency && <span className="text-xs text-muted-foreground">base</span>}</label>)}</div>
      <p className="text-sm text-muted-foreground">Seleccionadas: {selected.slice().sort().join(", ")} ({selected.length}/12). Los tipos de cambio de ERPNext se aplican al registrar cobros y devoluciones.</p>
      <Button disabled={busy} onClick={() => void save()}>Guardar monedas</Button>
    </CardContent></Card>}
  </div>
}
