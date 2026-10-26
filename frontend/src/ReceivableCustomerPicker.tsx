import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25
export type ReceivableCustomer = { name: string; customer_name: string }
type Page = { rows: ReceivableCustomer[]; offset: number; has_more: boolean }

export function ReceivableCustomerPicker({ property, selected, onSelect, refreshToken }: {
  property: Property; selected: ReceivableCustomer | null;
  onSelect: (customer: ReceivableCustomer | null) => void; refreshToken?: object
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
    call<Page>("pms_direct_sale_customers", {
      property_name: property.name, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ?
          issue.message : "No se pudieron buscar los clientes.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-2 rounded-lg border border-border p-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <strong>Cliente</strong>
      {selected && <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar selección</Button>}
    </div>
    {selected && <p className="rounded-md bg-secondary p-2 text-sm">
      Seleccionado: {selected.customer_name} · {selected.name}
    </p>}
    <div className="flex flex-wrap gap-2">
      <Input aria-label="Buscar cliente" maxLength={100} placeholder="Buscar cliente por nombre o código"
        value={search} onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-48 flex-1" />
      <Button type="button" variant="outline" disabled={loading} onClick={find}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando clientes…</p>}
    {page && <>
      <div className="max-h-48 overflow-y-auto">
        {page.rows.map((row) => <div key={row.name}
          className="flex flex-wrap items-center justify-between gap-2 border-b py-2 text-sm">
          <span>{row.customer_name}<small className="block text-muted-foreground">{row.name}</small></span>
          <Button type="button" size="sm" variant={selected?.name === row.name ? "secondary" : "outline"}
            onClick={() => onSelect(row)}>{selected?.name === row.name ? "Seleccionado" : "Elegir"}</Button>
        </div>)}
        {!page.rows.length && <p className="py-2 text-sm text-muted-foreground">No hay clientes con ese criterio.</p>}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} cliente(s)</span>
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
