import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type Target = { doctype: string; name: string; modified: string; label: string;
  fields: string[]; file_count: number }
type Candidates = { enabled: boolean; retention_days?: number; cutoff?: string;
  targets: Target[]; more_possible?: boolean }
type Preview = { acceptance: string; retention_days: number; cutoff: string;
  targets: { doctype: string; name: string; fields: string[]; file_count: number }[] }
type FileCounts = { Pending: number; Deleted: number; Shared: number; Failed: number }
type Run = { name: string; status: string; approved_by: string;
  approved_at: string; attempts: number; last_error: string | null;
  modified: string; file_counts: FileCounts }
type History = { total: number; offset: number; page_length: number; runs: Run[] }

const PAGE_SIZE = 25
const documentLabel: Record<string, string> = {
  "HS Guest": "Identificación de huésped",
  "HS Maintenance Order": "Evidencia de mantenimiento",
  "HS Incident": "Evidencia de novedad",
}
const fieldLabel: Record<string, string> = {
  identity_type: "Tipo de identificación", identity_number: "Número de identificación",
  identity_file: "Copia de identificación", evidence: "Evidencia",
}
const problem = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo completar la operación."

export function PrivacyRetention({ property, canSetup }: { property: Property; canSetup: boolean }) {
  const [revision, setRevision] = useState(0)
  const [offset, setOffset] = useState(0)
  const [candidates, setCandidates] = useState<Candidates | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  const [selected, setSelected] = useState("")
  const [reason, setReason] = useState("")
  const [preview, setPreview] = useState<Preview | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [retireKey, setRetireKey] = useState(() => crypto.randomUUID())
  const [retryRun, setRetryRun] = useState("")
  const [retryReason, setRetryReason] = useState("")
  const [retryKey, setRetryKey] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setCandidates(null)
    call<Candidates>("retention_candidates", { property_name: property.name }, controller.signal)
      .then(setCandidates).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(problem(issue))
      })
    return () => controller.abort()
  }, [property.name, revision])

  useEffect(() => {
    const controller = new AbortController()
    setHistory(null)
    call<History>("retention_history", { property_name: property.name,
      offset: String(offset), page_length: String(PAGE_SIZE) }, controller.signal)
      .then(setHistory).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(problem(issue))
      })
    return () => controller.abort()
  }, [property.name, offset, revision])

  const target = candidates?.targets.find((item) => `${item.doctype}:${item.name}` === selected)
  function changeReview() {
    setPreview(null); setConfirmed(false); setRetireKey(crypto.randomUUID())
  }
  async function review() {
    if (!target || !reason.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await call<Preview>("preview", { property_name: property.name,
        action: "retire_sensitive", data: JSON.stringify({ targets: [{
          doctype: target.doctype, name: target.name, modified: target.modified,
        }] }) })
      setPreview(result); setConfirmed(false)
    } catch (issue) { setError(problem(issue)) }
    finally { setBusy(false) }
  }
  async function retire() {
    if (!target || !preview || !confirmed || !reason.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ status: string }>(property.name, "retire_sensitive", {
        targets: [{ doctype: target.doctype, name: target.name, modified: target.modified }],
        reason: reason.trim(), acceptance: preview.acceptance, confirm: true,
      }, retireKey)
      setNotice(result.status === "Completed" ? "Datos sensibles retirados; la ejecución quedó registrada." :
        "Datos sensibles retirados. Los archivos quedaron en la cola de eliminación; consulte su estado abajo.")
      setSelected(""); setReason(""); changeReview(); setRevision((value) => value + 1)
    } catch (issue) { setError(problem(issue)) }
    finally { setBusy(false) }
  }
  async function retry() {
    const run = history?.runs.find((item) => item.name === retryRun)
    if (!run || run.status !== "Failed" || !retryReason.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "retry_retention", {
        run: run.name, modified: run.modified, reason: retryReason.trim(),
      }, retryKey)
      setNotice("Reintento de eliminación enviado a la cola.")
      setRetryRun(""); setRetryReason(""); setRetryKey(crypto.randomUUID())
      setRevision((value) => value + 1)
    } catch (issue) { setError(problem(issue)) }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div>
      <h1 className="text-3xl font-semibold">Retención de datos sensibles</h1>
      <p className="mt-2 text-sm text-muted-foreground">Revise identificaciones y evidencias vencidas del establecimiento antes de retirarlas.</p>
    </div><Button variant="outline" disabled={busy} onClick={() => { setError(""); setRevision((value) => value + 1) }}>Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!candidates ? <Skeleton className="h-48 rounded-xl" /> :
      <Card><CardHeader><CardTitle>Documentos elegibles</CardTitle>
        <CardDescription>{candidates.enabled ? `Conservación: ${candidates.retention_days} días · Corte: ${candidates.cutoff}` :
          "La política está desactivada. Configure los días de conservación antes de revisar."}</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        {!candidates.enabled && canSetup && <Link to="/setup?section=privacy" className="text-sm text-primary underline">Abrir Configuración</Link>}
        {candidates.enabled && <>
          <p className="text-sm text-muted-foreground">Se muestran hasta 50 candidatos. Los documentos con actividad vigente y los adjuntos recientes se conservan. Nombres, contactos y documentos contables permanecen.</p>
          {candidates.more_possible && <p className="text-sm text-amber-800">Hay más candidatos posibles. Actualice la lista después de procesar estos documentos.</p>}
          {!candidates.targets.length ? <p className="text-sm text-muted-foreground">No hay documentos elegibles.</p> : <>
            <label className="block space-y-1 text-sm"><span>Documento a revisar</span>
              <select className="h-9 w-full rounded-md border border-border bg-white px-2" value={selected}
                onChange={(event) => { setSelected(event.target.value); changeReview() }}>
                <option value="">Seleccione un documento</option>
                {candidates.targets.map((item) => <option key={`${item.doctype}:${item.name}`} value={`${item.doctype}:${item.name}`}>
                  {documentLabel[item.doctype] || item.doctype} · {item.label} · {item.file_count} adjunto(s)
                </option>)}
              </select></label>
            <label className="block space-y-1 text-sm"><span>Motivo de la revisión</span>
              <Input maxLength={500} value={reason} onChange={(event) => { setReason(event.target.value); changeReview() }} />
            </label>
            <Button disabled={busy || !target || !reason.trim()} onClick={() => void review()}>Revisar alcance</Button>
            {preview && <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">
              <strong>{documentLabel[preview.targets[0].doctype] || preview.targets[0].doctype} · {target?.label}</strong>
              <p>Referencia: {preview.targets[0].name}</p>
              <p>Campos que se retirarán: {preview.targets[0].fields.map((field) => fieldLabel[field] || field).join(", ") || "ninguno"}.</p>
              <p>Adjuntos privados: {preview.targets[0].file_count}. También se retirarán las versiones de esos campos y los comentarios automáticos de adjuntos. Esta eliminación no se puede deshacer desde la aplicación.</p>
              <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> Confirmo la eliminación de estos datos sensibles.</label>
              <Button variant="destructive" disabled={busy || !confirmed} onClick={() => void retire()}>Eliminar datos revisados</Button>
            </div>}
          </>}
        </>}
      </CardContent></Card>}
    <Card><CardHeader><CardTitle>Historial de ejecuciones {history && `(${history.total})`}</CardTitle>
      <CardDescription>Estado de la eliminación de archivos por establecimiento.</CardDescription></CardHeader>
      <CardContent className="space-y-3">
        {!history ? <Skeleton className="h-32" /> : <>
          {history.runs.map((run) => <div key={run.name} className="space-y-1 border-b border-border py-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2"><strong>{run.name}</strong><span>{run.status}</span></div>
            <p className="text-muted-foreground">{run.approved_at} · {run.approved_by} · Intentos: {run.attempts}</p>
            <p>Pendientes: {run.file_counts.Pending} · Eliminados: {run.file_counts.Deleted} · Compartidos: {run.file_counts.Shared} · Fallidos: {run.file_counts.Failed}</p>
            {run.last_error && <p className="text-destructive">{run.last_error}</p>}
            {run.status === "Failed" && <Button size="sm" variant="outline" onClick={() => {
              setRetryRun(run.name); setRetryReason(""); setRetryKey(crypto.randomUUID())
            }}>Reintentar eliminación</Button>}
            {retryRun === run.name && <div className="flex flex-wrap gap-2 pt-2">
              <Input aria-label="Corrección realizada o motivo" placeholder="Corrección realizada o motivo" maxLength={500}
                value={retryReason} onChange={(event) => { setRetryReason(event.target.value); setRetryKey(crypto.randomUUID()) }} className="min-w-48 flex-1" />
              <Button disabled={busy || !retryReason.trim()} onClick={() => void retry()}>Enviar reintento</Button>
              <Button variant="ghost" onClick={() => setRetryRun("")}>Cancelar</Button>
            </div>}
          </div>)}
          {!history.runs.length && <p className="text-sm text-muted-foreground">Sin ejecuciones registradas.</p>}
          <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground">
            <span>{history.total ? `${history.offset + 1}–${Math.min(history.offset + history.runs.length, history.total)} de ${history.total}` : "0 ejecuciones"}</span>
            <div className="flex gap-2"><Button variant="outline" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button>
              <Button variant="outline" disabled={offset + history.runs.length >= history.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</Button></div>
          </div>
        </>}
      </CardContent></Card>
  </div>
}
