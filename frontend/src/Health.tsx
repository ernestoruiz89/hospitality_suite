import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"

type Status = "OK" | "Warning" | "Error" | "Unknown"
type Check = { key: string; title: string; status: Status; detail: string }
type HealthSnapshot = { property: string; accounting_provider: "pms" | "erpnext";
  checked_at: string; status: Status; checks: Check[] }

const label: Record<Status, string> = {
  OK: "Correcto", Warning: "Revisar", Error: "Error", Unknown: "Sin verificar",
}
const badge: Record<Status, string> = {
  OK: "bg-emerald-50 text-emerald-800", Warning: "bg-amber-50 text-amber-800",
  Error: "bg-red-50 text-red-800", Unknown: "bg-secondary text-muted-foreground",
}

export function Health({ property }: { property: Property }) {
  const [data, setData] = useState<HealthSnapshot | null>(null)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError("")
    call<HealthSnapshot>("health_snapshot", { property_name: property.name }, controller.signal)
      .then(setData)
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo comprobar la salud del sistema.")
      })
    return () => controller.abort()
  }, [property.name, refresh])

  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-3xl font-semibold">Salud del sistema</h1>
        <p className="mt-2 text-sm text-muted-foreground">Comprobaciones de solo lectura del sitio y de {property.property_name}.</p></div>
      <Button variant="outline" onClick={() => setRefresh((value) => value + 1)}>Volver a comprobar</Button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {!data && !error && <Skeleton className="h-64 rounded-xl" />}
    {data && <>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={`rounded-full px-3 py-1 font-medium ${badge[data.status]}`}>{label[data.status]}</span>
        <span className="text-muted-foreground">{data.accounting_provider === "pms" ? "Contabilidad PMS" : "ERPNext"} · Comprobado: {data.checked_at}</span>
      </div>
      <Card><CardHeader><CardTitle>Comprobaciones</CardTitle></CardHeader><CardContent className="space-y-0">
        {data.checks.map((check) => <div key={check.key} className="flex flex-wrap items-start justify-between gap-3 border-b border-border py-3 text-sm last:border-0">
          <div className="min-w-0 flex-1"><strong>{check.title}</strong><p className="mt-1 text-muted-foreground">{check.detail}</p></div>
          <span className={`rounded-full px-3 py-1 text-xs font-medium ${badge[check.status]}`}>{label[check.status]}</span>
        </div>)}
      </CardContent></Card>
    </>}
  </div>
}
