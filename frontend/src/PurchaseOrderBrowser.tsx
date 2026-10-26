import { useEffect, useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

export type PurchaseOrder = { name: string; supplier: string; party_name?: string | null;
  reference: string; currency: string; payable_account: string;
  tax_account: string | null; amount: number; recoverable_tax: number;
  expected_date: string | null; requested_by: string; approved_by: string | null;
  status: string; progress: string; modified: string; close_reason: string | null;
  lines: { name: string; product: string; warehouse: string; quantity: string;
    received_quantity: string; remaining_quantity: string; amount: string;
    recoverable_tax: string }[] }
type Page = { rows: PurchaseOrder[]; offset: number; has_more: boolean }

export function PurchaseOrderBrowser({ property, receivableOnly = false,
  selected = null, onSelect, actionLabel, renderOrder, refreshToken }: {
  property: Property; receivableOnly?: boolean
  selected?: PurchaseOrder | null; onSelect?: (value: PurchaseOrder | null) => void
  actionLabel?: string; renderOrder?: (order: PurchaseOrder) => ReactNode
  refreshToken?: object
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
  }, [property.name, receivableOnly])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_purchase_order_page", {
      property_name: property.name, search: appliedSearch,
      receivable_only: receivableOnly ? "1" : "0",
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las órdenes.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, receivableOnly, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar orden de compra"
        placeholder="Buscar por referencia o proveedor" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" variant="outline" onClick={find} disabled={loading}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando órdenes…</p>}
    {actionLabel && onSelect && selected && !page?.rows.some((row) => row.name === selected.name) &&
      <div className="flex items-center justify-between gap-2 rounded-md bg-secondary p-2 text-sm">
        <span>Seleccionada: {selected.reference}</span>
        <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar</Button>
      </div>}
    {page && <>
      <div className="space-y-2">{page.rows.map((row) => <div key={row.name}>
        {renderOrder ? renderOrder(row) : <div
          className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
          <div><strong>{row.reference}</strong><span className="ml-2 text-muted-foreground">
            {row.party_name || row.supplier} · {row.currency} {row.amount}</span>
            <small className="block text-muted-foreground">
              {row.lines.filter((line) => Number(line.remaining_quantity) > 0).length} línea(s) pendiente(s)
            </small>
          </div>
          {actionLabel && onSelect && (selected?.name === row.name ?
            <Button type="button" size="sm" variant="outline" onClick={() => onSelect(null)}>Quitar</Button> :
            <Button type="button" size="sm" variant="outline" onClick={() => onSelect(row)}>{actionLabel}</Button>)}
        </div>}
      </div>)}{!page.rows.length &&
        <p className="text-sm text-muted-foreground">No hay órdenes con ese criterio.</p>}</div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
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
