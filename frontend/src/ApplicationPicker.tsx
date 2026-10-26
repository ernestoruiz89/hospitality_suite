import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

export type ReversibleApplication = {
  name: string; kind: string; receivable: string
  receivable_reference: string; source_reference: string
  currency: string; remaining: string
}
type Page = { rows: ReversibleApplication[]; offset: number; has_more: boolean }
export type ApplicationKind = "Advance" | "Guarantee" | "Opening Credit" | "Opening Guarantee"

export function ApplicationPicker({ property, kind, selected, onSelect, refreshToken }: {
  property: Property; kind: ApplicationKind; selected: ReversibleApplication | null
  onSelect: (value: ReversibleApplication | null) => void; refreshToken?: object
}) {
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    setSearch(""); setAppliedSearch(""); setOffset(0); setPage(null)
  }, [property.name, kind])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_applications_page", {
      property_name: property.name, kind, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron buscar las aplicaciones.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, kind, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  const options = page?.rows || []
  const visible = selected && !options.some((row) => row.name === selected.name)
    ? [selected, ...options] : options

  return <div className="space-y-2 sm:col-span-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar aplicación"
        placeholder="Buscar aplicación, origen o cuenta" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" onClick={find} variant="outline" disabled={loading}>Buscar</Button>
    </div>
    <select required value={selected?.name || ""}
      onChange={(event) => onSelect(visible.find((row) => row.name === event.target.value) || null)}
      disabled={loading} aria-label="Aplicación original"
      className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">
      <option value="">Aplicación original con saldo</option>
      {visible.map((row) => <option key={row.name} value={row.name}>
        {row.source_reference} → {row.receivable_reference || row.receivable} · Pendiente {row.currency} {row.remaining} · {row.name}
      </option>)}
    </select>
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando aplicaciones…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {page && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} aplicación(es)
        {!page.rows.length && " con ese criterio"}</span>
      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline" disabled={loading || !page.offset}
          onClick={() => setOffset(Math.max(0, page.offset - PAGE_LENGTH))}>Anterior</Button>
        <Button type="button" size="sm" variant="outline" disabled={loading || !page.has_more}
          onClick={() => setOffset(page.offset + PAGE_LENGTH)}>Siguiente</Button>
      </div>
    </div>}
  </div>
}
