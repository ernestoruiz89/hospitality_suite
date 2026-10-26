import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { call } from "./api"

export type AuditSelection = { name: string }
type AuditValue = { field: string; label: string; before: string; after: string; changed: boolean }
type AuditDetail = { name: string; action: string; actor: string; occurred_at: string;
  business_date: string; document_type: string; document: string; reason: string | null;
  source_doctype: string; source_name: string;
  values: AuditValue[]; historical_values_available: boolean; values_document: string | null;
  close_snapshot: unknown | null }

function ValuesTable({ values }: { values: AuditValue[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[540px] text-left text-sm"><thead><tr className="border-b"><th className="p-2">Dato</th><th className="p-2">Antes</th><th className="p-2">Después</th></tr></thead><tbody>{values.map((value) => <tr key={value.field} className="border-b"><th scope="row" className="p-2 font-medium">{value.label}</th><td className="whitespace-pre-wrap p-2">{value.before || "—"}</td><td className="whitespace-pre-wrap p-2">{value.after || "—"}</td></tr>)}</tbody></table></div>
}

export function AuditDetailPanel({ propertyName, selection, onClose }: {
  propertyName: string; selection: AuditSelection; onClose: () => void }) {
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    const controller = new AbortController()
    setAudit(null); setError("")
    call<AuditDetail>("audit_detail", {
      property_name: propertyName, name: selection.name,
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setAudit(result)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error
        ? issue.message : "No se pudo consultar el cambio.")
    })
    return () => controller.abort()
  }, [propertyName, selection.name])
  const changed = audit?.values.filter((value) => value.changed) || []
  const retained = audit?.values.filter((value) => !value.changed) || []
  return <Card aria-label="Detalle de auditoría"><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><CardTitle>{audit?.action || "Detalle del cambio"}</CardTitle><CardDescription>Registro {selection.name}</CardDescription></div><Button size="sm" variant="outline" onClick={onClose}>Cerrar detalle</Button></div></CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {!audit && !error && <Skeleton className="h-52" />}
    {audit && <><div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3"><p><span className="block text-xs text-muted-foreground">Realizado por</span>{audit.actor}</p><p><span className="block text-xs text-muted-foreground">Momento</span>{audit.occurred_at}</p><p><span className="block text-xs text-muted-foreground">Fecha operativa</span>{audit.business_date}</p><p><span className="block text-xs text-muted-foreground">{audit.document_type}</span>{audit.document}</p><p className="sm:col-span-2"><span className="block text-xs text-muted-foreground">Motivo</span>{audit.reason || "No se registró un motivo adicional."}</p></div>
      {audit.close_snapshot && audit.source_doctype === "HS Daily Close" && audit.source_name && <Button asChild size="sm" variant="outline"><Link to={`/daily-close?section=snapshot&close=${encodeURIComponent(audit.source_name)}`}>Ver resumen de esta ejecución</Link></Button>}
      <div><h3 className="font-semibold">Valores registrados</h3>{audit.values_document && <p className="mt-1 text-sm text-muted-foreground">{audit.values_document}</p>}
        {audit.historical_values_available ? <><div className="mt-3">{changed.length ? <ValuesTable values={changed} /> : <p className="text-sm text-muted-foreground">No cambiaron los valores registrados.</p>}</div>
          {!!retained.length && <details className="mt-3 rounded-md border p-3 text-sm"><summary className="cursor-pointer">Datos que se conservaron ({retained.length})</summary><div className="mt-3"><ValuesTable values={retained} /></div></details>}
        </> : <p className="mt-2 text-sm text-muted-foreground">Este registro no conserva el desglose de valores. Consulte el documento de origen y su historial.</p>}</div></>}
  </CardContent></Card>
}
