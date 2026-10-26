import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { AuditDetailPanel } from "./AuditDetailPanel"

export type AuditReview = { business_date: string; rows: {
  name: string; category: string; occurred_at: string; action: string;
  actor: string; document: string; reason: string | null }[] }

const PAGE_LENGTH = 25

export function AuditReviewPanel({ propertyName, review }: {
  propertyName: string; review: AuditReview }) {
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  useEffect(() => { setOffset(0); setSelected(null) }, [propertyName, review])
  const counts = Object.entries(review.rows.reduce<Record<string, number>>((result, row) => {
    result[row.category] = (result[row.category] || 0) + 1
    return result
  }, {}))
  return <div className="space-y-4"><Card><CardHeader><CardTitle>Registros para revisar · {review.rows.length}</CardTitle><CardDescription>Fecha operativa {review.business_date}. Un cambio puede tener varios registros vinculados; estos conteos no suman importes.</CardDescription></CardHeader><CardContent className="space-y-4">
    {!!counts.length && <div className="flex flex-wrap gap-2 text-xs">{counts.map(([label, count]) => <span key={label} className="rounded-full border px-3 py-1">{label}: {count}</span>)}</div>}
    {review.rows.length ? <><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead><tr className="border-b"><th className="p-2">Momento</th><th className="p-2">Acción</th><th className="p-2">Registrado por</th><th className="p-2">Documento</th><th className="p-2">Motivo</th><th className="p-2">Detalle</th></tr></thead><tbody>{review.rows.slice(offset, offset + PAGE_LENGTH).map((row) => <tr key={row.name} className="border-b"><td className="p-2">{row.occurred_at}</td><td className="p-2">{row.action}</td><td className="p-2">{row.actor}</td><td className="p-2">{row.document}</td><td className="max-w-64 p-2">{row.reason || "—"}</td><td className="p-2"><Button size="sm" variant="outline" onClick={() => setSelected(row.name)}>Ver cambio</Button></td></tr>)}</tbody></table></div>
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><span role="status">{offset + 1}–{Math.min(offset + PAGE_LENGTH, review.rows.length)} de {review.rows.length}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_LENGTH))}>Anterior</Button><Button size="sm" variant="outline" disabled={offset + PAGE_LENGTH >= review.rows.length} onClick={() => setOffset(offset + PAGE_LENGTH)}>Siguiente</Button></div></div></> : <p className="text-sm text-muted-foreground">Sin registros excepcionales en esta fecha.</p>}
  </CardContent></Card>
    {selected && <AuditDetailPanel key={`${propertyName}:${selected}`} propertyName={propertyName} selection={{ name: selected }} onClose={() => setSelected(null)} />}
  </div>
}
