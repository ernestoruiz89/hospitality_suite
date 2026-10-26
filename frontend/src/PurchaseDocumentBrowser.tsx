import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

type Base = { name: string; supplier: string; party_name: string | null;
  business_date: string }
export type PurchaseCandidate = Base & { kind: "Purchase";
  supplier_reference: string; invoice_currency: string; invoice_amount: number;
  base_amount: number; can_cancel: boolean;
  lines: { product: string; product_name: string; warehouse: string; quantity: number;
    stock_movement: string | null }[] }
export type SupplierReturn = Base & { kind: "Return";
  purchase: string; supplier_reference: string; return_kind: string;
  reference: string; invoice_currency: string; credit_amount: number;
  base_credit: number; supplier_credit: number; refund_available: string }
export type PurchaseDocument = PurchaseCandidate | SupplierReturn
type Page = { rows: PurchaseDocument[]; offset: number; has_more: boolean }

function label(row: PurchaseDocument) {
  return row.kind === "Purchase" ? row.supplier_reference : row.reference
}

export function PurchaseDocumentBrowser({ property, kind, selected = null,
  onSelect, actionLabel, availableOnly = false, refreshToken }: {
  property: Property; kind: "Purchase" | "Return"
  selected?: PurchaseDocument | null
  onSelect?: (value: PurchaseDocument | null) => void
  actionLabel?: string; availableOnly?: boolean; refreshToken?: object
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
  }, [property.name, kind, availableOnly])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_purchase_document_page", {
      property_name: property.name, kind, search: appliedSearch,
      available_only: availableOnly ? "1" : "0",
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las compras.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, kind, availableOnly, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar compra o devolución"
        placeholder="Buscar por referencia o proveedor" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" variant="outline" onClick={find} disabled={loading}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando documentos…</p>}
    {actionLabel && onSelect && selected && !page?.rows.some((row) => row.name === selected.name) &&
      <div className="flex items-center justify-between gap-2 rounded-md bg-secondary p-2 text-sm">
        <span>Seleccionado: {label(selected)}</span>
        <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar</Button>
      </div>}
    {page && <>
      <div className="space-y-2">{page.rows.map((row) => <div key={row.name}
        className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
        <div><strong>{label(row)}</strong><span className="ml-2 text-muted-foreground">
          {row.party_name || row.supplier} · {row.business_date}</span>
          {row.kind === "Return" && <small className="block text-muted-foreground">
            {row.supplier_reference} · {row.return_kind === "Full Cancellation" ? "Cancelación completa" : "Devolución"}
          </small>}
          {row.kind === "Purchase" && <small className="block text-muted-foreground">
            {row.lines.length} línea(s){!row.can_cancel && " · Ya tiene pago o devolución"}
          </small>}
        </div>
        <div className="flex items-center gap-3"><span>
          {row.kind === "Purchase" ? <>{row.invoice_currency} {row.invoice_amount}</> :
            <>{row.invoice_currency} {row.credit_amount}<small className="block text-muted-foreground">
              Crédito pendiente {property.currency} {row.refund_available}</small></>}
        </span>
          {actionLabel && onSelect && (selected?.name === row.name ?
            <Button type="button" size="sm" variant="outline" onClick={() => onSelect(null)}>Quitar</Button> :
            <Button type="button" size="sm" variant="outline"
              disabled={row.kind === "Return" && Number(row.refund_available) <= 0}
              onClick={() => onSelect(row)}>{actionLabel}</Button>)}
        </div>
      </div>)}{!page.rows.length &&
        <p className="text-sm text-muted-foreground">No hay documentos con ese criterio.</p>}</div>
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
