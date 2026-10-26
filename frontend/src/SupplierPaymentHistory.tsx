import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

type Payment = { name: string; kind: "Supplier Payment" | "Supplier Refund";
  reference: string; business_date: string; currency: string; amount: number;
  base_amount: number; source_reference: string | null; supplier_name: string | null;
  pms_settlement_currency: string | null; pms_settled_amount: number | null;
  pms_released_base_amount: number | null }
type Page = { rows: Payment[]; offset: number; has_more: boolean }

export function SupplierPaymentHistory({ property, refreshToken }: {
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
    setSearch(""); setAppliedSearch(""); setOffset(0); setPage(null)
  }, [property.name])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_supplier_payment_page", {
      property_name: property.name, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los pagos.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar pago o reintegro"
        placeholder="Buscar por referencia o proveedor" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" variant="outline" onClick={find} disabled={loading}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando movimientos…</p>}
    {page && <>
      <div className="space-y-2">{page.rows.map((row) => <div key={row.name}
        className="flex flex-wrap items-start justify-between gap-2 border-b border-border py-2 text-sm">
        <div><strong>{row.kind === "Supplier Refund" ? "Reintegro" : "Pago"} · {row.reference}</strong>
          <span className="ml-2 text-muted-foreground">{row.source_reference || row.name}
            {row.supplier_name && ` · ${row.supplier_name}`}</span>
          <small className="block text-muted-foreground">{row.business_date} · {row.name}</small>
          {row.pms_settlement_currency && <small className="block text-muted-foreground">
            Principal liquidado {row.pms_settlement_currency} {row.pms_settled_amount} ·
            Valor base liberado {property.currency} {row.pms_released_base_amount}
          </small>}
        </div>
        <strong>{row.currency} {row.amount} · Base {property.currency} {row.base_amount}</strong>
      </div>)}{!page.rows.length &&
        <p className="text-sm text-muted-foreground">Sin movimientos de proveedores con ese criterio.</p>}</div>
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
