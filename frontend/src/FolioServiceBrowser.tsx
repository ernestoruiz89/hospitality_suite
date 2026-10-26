import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

export type FolioServiceProduct = { name: string; product_code: string;
  product_name: string; sales_rate: number }
type Page = { rows: FolioServiceProduct[]; offset: number; has_more: boolean }

export function FolioServiceBrowser({ property, folio, selected, onSelect }: {
  property: Property; folio: string; selected: FolioServiceProduct | null;
  onSelect: (product: FolioServiceProduct | null) => void
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
  }, [property.name, folio])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_folio_service_products", {
      property_name: property.name, folio, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ?
          issue.message : "No se pudieron consultar los servicios.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, folio, appliedSearch, offset, reload])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-2 rounded-lg border border-border p-3 sm:col-span-2 lg:col-span-4">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <strong>Servicio para cargar a la cuenta</strong>
      {selected && <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar selección</Button>}
    </div>
    {selected && <p className="rounded-md bg-secondary p-2 text-sm">
      Seleccionado: {selected.product_code} · {selected.product_name} · {property.currency} {selected.sales_rate}
    </p>}
    <div className="flex flex-wrap gap-2">
      <Input aria-label="Buscar servicio" maxLength={100}
        placeholder="Buscar servicio por nombre o código" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-48 flex-1" />
      <Button type="button" variant="outline" disabled={loading} onClick={find}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando servicios…</p>}
    {page && <>
      <div className="max-h-56 overflow-y-auto">
        {page.rows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 text-sm">
          <span>{row.product_code} · {row.product_name} · {property.currency} {row.sales_rate}</span>
          <Button type="button" size="sm" variant={selected?.name === row.name ? "secondary" : "outline"}
            onClick={() => onSelect(row)}>{selected?.name === row.name ? "Seleccionado" : "Elegir"}</Button>
        </div>)}
        {!page.rows.length && <p className="py-2 text-sm text-muted-foreground">
          No hay servicios con ese criterio. Configure un servicio activo con precio, cuenta de ingresos y perfil tributario.
        </p>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} servicio(s)</span>
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
