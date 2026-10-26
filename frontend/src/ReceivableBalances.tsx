import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { useIdempotentCommand } from "./useIdempotentCommand"

const PAGE_LENGTH = 25

type Receivable = {
  name: string; party: string; party_name: string | null; reference: string
  description: string; amount: number; currency: string; base_amount: number | null
  outstanding: string; opening_source_name: string | null
  historical_document: string | null
}
type Page = { rows: Receivable[]; search: string; offset: number; has_more: boolean }

export function ReceivableBalances({ property, canCancel, onChanged }: {
  property: Property; canCancel: boolean; onChanged: () => Promise<void>
}) {
  const send = useIdempotentCommand(property.name)
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [cancelId, setCancelId] = useState("")
  const [cancelReason, setCancelReason] = useState("")

  const refreshPage = useCallback(async (signal?: AbortSignal) => {
    const result = await call<Page>("pms_receivables_page", {
      property_name: property.name, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, signal)
    if (!signal?.aborted) setPage(result)
  }, [property.name, appliedSearch, offset])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    refreshPage(controller.signal)
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron buscar los saldos.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [refreshPage])

  function find(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCancelId(""); setOffset(0); setAppliedSearch(search.trim())
    if (!search.trim() && !appliedSearch && offset === 0) void refreshPage()
  }

  async function cancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canCancel || !cancelId || !cancelReason.trim() || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send("pms_cancel_receivable", { receivable: cancelId, reason: cancelReason.trim() })
      setCancelId(""); setCancelReason("")
      try {
        await Promise.all([refreshPage(), onChanged()])
        setNotice("Cargo cancelado mediante asiento inverso.")
      } catch {
        setNotice("Cargo cancelado. Actualice la vista para consultar el saldo.")
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo cancelar el cargo.")
    } finally { setBusy(false) }
  }

  return <Card>
    <CardHeader><CardTitle>Saldos pendientes</CardTitle><CardDescription>Busque por cuenta, referencia o cliente. Las cuentas extranjeras muestran el saldo original y su valor inicial en moneda base.</CardDescription></CardHeader>
    <CardContent className="space-y-3">
      <form onSubmit={find} className="flex flex-wrap gap-2">
        <Input maxLength={100} aria-label="Buscar cuenta por cobrar" placeholder="Cuenta, referencia o cliente"
          value={search} onChange={(event) => setSearch(event.target.value)} className="min-w-48 flex-1" />
        <Button type="submit" variant="outline" disabled={loading || busy}>Buscar</Button>
      </form>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
      {loading && !page && <Skeleton className="h-36" />}
      {page && <>
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} cuenta(s) con saldo</span>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" disabled={loading || busy || !page.offset}
              onClick={() => setOffset(Math.max(0, page.offset - PAGE_LENGTH))}>Anterior</Button>
            <Button type="button" size="sm" variant="outline" disabled={loading || busy || !page.has_more}
              onClick={() => setOffset(page.offset + PAGE_LENGTH)}>Siguiente</Button>
          </div>
        </div>
        <div className="space-y-2">{page.rows.map((item) => <div key={item.name}
          className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
          <div><strong>{item.reference}</strong><span className="ml-2 text-muted-foreground">{item.party_name || item.party} · {item.description}</span>
            {item.opening_source_name && <p className="text-xs text-muted-foreground">Saldo trasladado de ERPNext · {item.historical_document ?
              <a className="text-primary underline" target="_blank" rel="noopener noreferrer"
                href={`/api/method/hospitality_suite.api.historical_fiscal_pdf?document=${encodeURIComponent(item.historical_document)}`}>Imprimir copia fiscal</a> :
              "Consulte el archivo fiscal"}</p>}
          </div>
          <div className="flex items-center gap-3"><span>{item.currency} {item.outstanding} / {item.amount}
            {item.currency !== property.currency && item.base_amount != null &&
              <small className="block text-muted-foreground">Valor inicial {property.currency} {item.base_amount}</small>}</span>
            <Button asChild size="sm" variant="outline"><Link to={`/cash?section=collect&receivable=${encodeURIComponent(item.name)}`}>Cobrar</Link></Button>
            {canCancel && !item.opening_source_name && Number(item.outstanding) === Number(item.amount) &&
              <Button size="sm" variant="outline" disabled={busy} onClick={() => { setCancelId(item.name); setCancelReason("") }}>Cancelar</Button>}
          </div>
        </div>)}{!page.rows.length && <p className="text-sm text-muted-foreground">No hay cuentas pendientes con ese criterio.</p>}</div>
      </>}
      {cancelId && <form onSubmit={cancel} className="flex flex-wrap gap-2 rounded-lg border border-border p-3">
        <Input required maxLength={500} placeholder="Motivo de cancelación" value={cancelReason}
          onChange={(event) => setCancelReason(event.target.value)} className="min-w-48 flex-1" />
        <Button disabled={busy}>Confirmar cancelación</Button>
        <Button type="button" variant="ghost" onClick={() => setCancelId("")}>Volver</Button>
      </form>}
    </CardContent>
  </Card>
}
