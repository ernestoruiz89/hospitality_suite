import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25
type Cancelled = { name: string; party: string; party_name: string | null;
  reference: string; amount: number; currency: string; reversal_journal: string }
type Page = { rows: Cancelled[]; offset: number; has_more: boolean }

export function CancelledReceivables({ property, refreshToken }: {
  property: Property; refreshToken?: object
}) {
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_cancelled_receivables_page", {
      property_name: property.name, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ?
          issue.message : "No se pudieron consultar los cargos cancelados.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input aria-label="Buscar cargos cancelados" maxLength={100}
        placeholder="Buscar por referencia o cliente" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-48 flex-1" />
      <Button type="button" variant="outline" disabled={loading} onClick={find}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando cargos…</p>}
    {page && <>
      <div className="space-y-2">
        {page.rows.map((row) => <div key={row.name}
          className="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm">
          <span>{row.reference} · {row.party_name || row.party}
            <small className="block text-muted-foreground">{row.name}</small></span>
          <span>{row.currency} {row.amount} · Asiento {row.reversal_journal}</span>
        </div>)}
        {!page.rows.length && <p className="text-sm text-muted-foreground">No hay cargos cancelados con ese criterio.</p>}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} cargo(s)</span>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" disabled={loading || !page.offset}
            onClick={() => setOffset(Math.max(0, page.offset - PAGE_LENGTH))}>Anterior</Button>
          <Button type="button" size="sm" variant="outline" disabled={loading || !page.has_more}
            onClick={() => setOffset(page.offset + PAGE_LENGTH)}>Siguiente</Button>
        </div>
      </div>
    </>}
  </div>
}
