import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

export type OpenReceivable = {
  name: string; party: string; party_name: string | null; reference: string
  currency: string; outstanding: string; receivable_account: string
  folio: string | null; folio_stay: string | null; booking: string | null
}
type Page = { rows: OpenReceivable[]; offset: number; has_more: boolean }

export function ReceivablePicker({ property, selected, onSelect, party = "", currency = "",
  folio = "", stay = "", booking = "", enabled = true, refreshToken, label = "Cuenta pendiente" }: {
  property: Property; selected: OpenReceivable | null
  onSelect: (value: OpenReceivable | null) => void
  party?: string; currency?: string; folio?: string; stay?: string; booking?: string
  enabled?: boolean; refreshToken?: object; label?: string
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
  }, [property.name, party, currency, folio, stay, booking])

  useEffect(() => {
    if (!enabled) { setPage(null); setLoading(false); return }
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_receivables_page", {
      property_name: property.name, search: appliedSearch,
      offset: String(offset), page_length: String(PAGE_LENGTH),
      party, currency, folio, stay, booking,
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron buscar las cuentas.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, party, currency, folio, stay, booking, enabled,
    appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  const options = page?.rows || []
  const visible = selected && !options.some((row) => row.name === selected.name)
    ? [selected, ...options] : options

  return <div className="space-y-2">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label={`Buscar ${label.toLowerCase()}`}
        placeholder="Buscar por cuenta, referencia o cliente" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1"
        disabled={!enabled} />
      <Button type="button" onClick={find} variant="outline" disabled={!enabled || loading}>Buscar</Button>
    </div>
    <select required value={selected?.name || ""}
      onChange={(event) => onSelect(visible.find((row) => row.name === event.target.value) || null)}
      disabled={!enabled || loading}
      aria-label={label} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">
      <option value="">{enabled ? label : "Seleccione primero el saldo a aplicar"}</option>
      {visible.map((row) => <option key={row.name} value={row.name}>
        {row.reference} · {row.party_name || row.party} · {row.currency} {row.outstanding}
      </option>)}
    </select>
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando cuentas…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {enabled && page && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Página {Math.floor(page.offset / PAGE_LENGTH) + 1} · {page.rows.length} cuenta(s)
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
