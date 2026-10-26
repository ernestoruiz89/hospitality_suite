import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"
import { type OpenReceivable } from "./ReceivablePicker"

const PAGE_LENGTH = 25

export type EligibleDeposit = {
  name: string; kind: "Advance" | "Guarantee"; pms_party: string
  reference: string; amount: number; currency: string; base_amount: number
  available: string; pms_counter_account: string
  folio: string | null; booking: string | null
}
type Page = { rows: EligibleDeposit[]; offset: number; has_more: boolean }

export function DepositPicker({ property, receivable, kind, selected, onSelect, refreshToken }: {
  property: Property; receivable: OpenReceivable | null
  kind: "Advance" | "Guarantee"; selected: EligibleDeposit | null
  onSelect: (value: EligibleDeposit | null) => void; refreshToken?: object
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
  }, [property.name, receivable?.name, kind])

  useEffect(() => {
    if (!receivable) { setPage(null); setLoading(false); return }
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_deposits_page", {
      property_name: property.name, receivable: receivable.name, kind,
      search: appliedSearch, offset: String(offset),
      page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron buscar los depósitos.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, receivable?.name, kind, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  const options = page?.rows || []
  const visible = selected && !options.some((row) => row.name === selected.name)
    ? [selected, ...options] : options
  const label = kind === "Guarantee" ? "Garantía de la cuenta" : "Anticipo del cliente"

  return <div className="space-y-2">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label={`Buscar ${label.toLowerCase()}`}
        placeholder="Buscar depósito por referencia" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" disabled={!receivable} />
      <Button type="button" onClick={find} variant="outline"
        disabled={!receivable || loading}>Buscar</Button>
    </div>
    <select required value={selected?.name || ""}
      onChange={(event) => onSelect(visible.find((row) => row.name === event.target.value) || null)}
      disabled={!receivable || loading} aria-label={label}
      className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">
      <option value="">{receivable ? label : "Seleccione primero la cuenta"}</option>
      {visible.map((row) => <option key={row.name} value={row.name}>
        {row.reference} · {row.currency} {row.amount} · Disponible {property.currency} {row.available}
      </option>)}
    </select>
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando depósitos…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {receivable && page && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} depósito(s)
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
