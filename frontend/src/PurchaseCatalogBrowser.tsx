import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

export type PurchaseCatalogRow = { name: string; party_name?: string; tax_id?: string;
  product_code?: string; product_name?: string }
type Page = { rows: PurchaseCatalogRow[]; offset: number; has_more: boolean }

function label(row: PurchaseCatalogRow) {
  return row.party_name || [row.product_code, row.product_name].filter(Boolean).join(" · ") || row.name
}

export function PurchaseCatalogBrowser({ property, kind, selected = null, onSelect,
  refreshToken }: {
  property: Property; kind: "Supplier" | "Product";
  selected?: PurchaseCatalogRow | null;
  onSelect?: (row: PurchaseCatalogRow | null) => void;
  refreshToken?: object
}) {
  const [open, setOpen] = useState(!onSelect)
  const [search, setSearch] = useState("")
  const [appliedSearch, setAppliedSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const selectable = !!onSelect
  const name = kind === "Supplier" ? "proveedor" : "producto"
  const plural = kind === "Supplier" ? "proveedores" : "productos"

  useEffect(() => {
    setOpen(!selectable); setSearch(""); setAppliedSearch(""); setOffset(0); setPage(null)
  }, [property.name, kind, selectable])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_purchase_catalog_page", {
      property_name: property.name, kind, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ?
          issue.message : `No se pudo consultar el catálogo de ${plural}.`)
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, kind, open, appliedSearch, offset, reload, refreshToken, plural])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  if (onSelect && !open) return <div className="flex flex-wrap items-center gap-2 text-sm">
    <span className="min-w-0 flex-1">{selected ? label(selected) : `Ningún ${name} seleccionado`}</span>
    <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
      {selected ? "Cambiar" : `Seleccionar ${name}`}
    </Button>
    {selected && <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar</Button>}
  </div>

  return <div className="space-y-2 rounded-md border border-border p-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label={`Buscar ${name}`} placeholder={`Buscar ${name} por nombre o código`}
        value={search} onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" size="sm" variant="outline" disabled={loading} onClick={find}>Buscar</Button>
      {onSelect && <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>Cerrar</Button>}
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando {plural}…</p>}
    {page && <>
      <div className="max-h-64 overflow-y-auto">
        {page.rows.map((row) => <div key={row.name} className="flex items-center justify-between gap-2 border-b py-2 text-sm">
          <span>{label(row)}{row.tax_id && <small className="block text-muted-foreground">{row.tax_id}</small>}</span>
          {onSelect && <Button type="button" size="sm" variant="outline"
            onClick={() => { onSelect(row); setOpen(false) }}>Elegir</Button>}
        </div>)}
        {!page.rows.length && <p className="py-2 text-sm text-muted-foreground">No hay {plural} con ese criterio.</p>}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} registro(s)</span>
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
