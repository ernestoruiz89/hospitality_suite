import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

type BaseBalance = {
  name: string; customer: string; party_name: string | null
  opening_source_name: string; currency: string; amount: number
  available: string
}
export type OpeningCreditBalance = BaseBalance & {
  kind: "Credit"; credit_kind: string; base_amount: number
  base_available: string; receivable_account: string
  historical_document: string | null
}
export type OpeningGuaranteeBalance = BaseBalance & {
  kind: "Guarantee"; source_booking: string | null
  source_stay: string | null; source_folio: string | null
  liability_account: string
}
export type OpeningBalance = OpeningCreditBalance | OpeningGuaranteeBalance
type Page = { rows: OpeningBalance[]; offset: number; has_more: boolean }

export function OpeningBalanceBrowser({ property, kind, selected, onSelect,
  actionLabel, refreshToken }: {
  property: Property; kind: "Credit" | "Guarantee"
  selected: OpeningBalance | null; onSelect: (value: OpeningBalance | null) => void
  actionLabel?: string; refreshToken?: object
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
    call<Page>("pms_opening_balances_page", {
      property_name: property.name, kind, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los saldos de apertura.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, kind, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar saldo de apertura"
        placeholder="Buscar por origen o cliente" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" variant="outline" onClick={find} disabled={loading}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando saldos…</p>}
    {actionLabel && selected && !page?.rows.some((row) => row.name === selected.name) &&
      <div className="flex items-center justify-between gap-2 rounded-md bg-secondary p-2 text-sm">
        <span>Seleccionado: {selected.opening_source_name} · {selected.currency} {selected.available}</span>
        <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar</Button>
      </div>}
    {page && <>
      <div className="space-y-2">{page.rows.map((row) => <div key={row.name}
        className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
        <div><strong>{row.opening_source_name}</strong>
          <span className="ml-2 text-muted-foreground">
            {row.kind === "Credit" ? row.credit_kind === "Credit Note" ? "Nota de crédito" : "Anticipo" : "Garantía"}
            {" · "}{row.party_name || row.customer}
            {row.kind === "Guarantee" && (row.source_folio || row.source_stay || row.source_booking) &&
              <> · {row.source_folio || row.source_stay || row.source_booking}</>}
          </span>
          {row.kind === "Credit" && row.historical_document &&
            <a className="ml-2 text-primary underline" target="_blank" rel="noopener noreferrer"
              href={`/api/method/hospitality_suite.api.historical_fiscal_pdf?document=${encodeURIComponent(row.historical_document)}`}>Imprimir copia fiscal</a>}
        </div>
        <div className="flex items-center gap-3"><span>Disponible {row.currency} {row.available} / {row.amount}
          {row.kind === "Credit" && row.currency !== property.currency &&
            <small className="block text-muted-foreground">Valor base {property.currency} {row.base_available} / {row.base_amount}</small>}
        </span>
          {actionLabel && (selected?.name === row.name ?
            <Button type="button" size="sm" variant="outline" onClick={() => onSelect(null)}>Quitar</Button> :
            <Button type="button" size="sm" variant="outline" disabled={Number(row.available) <= 0}
              onClick={() => onSelect(row)}>{actionLabel}</Button>)}
        </div>
      </div>)}{!page.rows.length &&
        <p className="text-sm text-muted-foreground">No hay saldos de apertura con ese criterio.</p>}</div>
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
