import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { call, type Property } from "./api"

const PAGE_LENGTH = 25

type SupplierBase = { name: string; supplier: string; party_name: string | null;
  currency: string }
export type SupplierCredit = SupplierBase & { kind: "Credit";
  opening_source_name: string; amount: number; base_amount: number;
  available: string; base_available: string; payable_account: string }
export type SupplierTarget = SupplierBase & {
  kind: "Opening Payable" | "Purchase"; reference: string;
  amount: number; base_amount: number; due_date: string | null;
  invoice_currency: string | null; invoice_amount: number | null;
  outstanding: string; base_outstanding: string }
export type SupplierApplication = SupplierBase & { kind: "Application";
  opening_credit: string; target_type: string; opening_payable: string | null;
  purchase: string | null; credit_reference: string; target_reference: string;
  amount: number; remaining: string }
export type SupplierDocument = SupplierCredit | SupplierTarget | SupplierApplication
type Page = { rows: SupplierDocument[]; offset: number; has_more: boolean }

function label(row: SupplierDocument) {
  if (row.kind === "Credit") return row.opening_source_name
  if (row.kind === "Application") return `${row.credit_reference} → ${row.target_reference}`
  return row.reference
}

export function SupplierDocumentBrowser({ property, kind, supplier = "", currency = "",
  selected, onSelect, actionLabel, refreshToken }: {
  property: Property; kind: "Target" | "Credit" | "Application"
  supplier?: string; currency?: string
  selected: SupplierDocument | null; onSelect: (value: SupplierDocument | null) => void
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
  }, [property.name, kind, supplier, currency])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setLoading(true)
    call<Page>("pms_supplier_document_page", {
      property_name: property.name, kind, search: appliedSearch,
      supplier, currency, offset: String(offset), page_length: String(PAGE_LENGTH),
    }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setPage(result) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los documentos.")
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [property.name, kind, supplier, currency, appliedSearch, offset, reload, refreshToken])

  function find() {
    setOffset(0); setAppliedSearch(search.trim()); setReload((value) => value + 1)
  }

  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Input maxLength={100} aria-label="Buscar documento de proveedor"
        placeholder="Buscar por referencia o proveedor" value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); find() } }}
        className="min-w-44 flex-1" />
      <Button type="button" variant="outline" onClick={find} disabled={loading}>Buscar</Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">Buscando documentos…</p>}
    {actionLabel && selected && !page?.rows.some((row) => row.name === selected.name) &&
      <div className="flex items-center justify-between gap-2 rounded-md bg-secondary p-2 text-sm">
        <span>Seleccionado: {label(selected)} · {selected.currency}</span>
        <Button type="button" size="sm" variant="ghost" onClick={() => onSelect(null)}>Quitar</Button>
      </div>}
    {page && <>
      <div className="space-y-2">{page.rows.map((row) => {
        const balance = row.kind === "Credit" ? row.available :
          row.kind === "Application" ? row.remaining : row.outstanding
        return <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
          <div><strong>{label(row)}</strong><span className="ml-2 text-muted-foreground">
            {row.kind === "Credit" ? "Crédito de apertura" :
              row.kind === "Application" ? "Aplicación" :
                row.kind === "Opening Payable" ? "Deuda de apertura" : "Compra PMS"}
            {" · "}{row.party_name || row.supplier}</span>
            {row.kind === "Opening Payable" && row.due_date &&
              <small className="block text-muted-foreground">Vence {row.due_date}</small>}
            {row.kind === "Purchase" && row.invoice_currency &&
              <small className="block text-muted-foreground">Factura {row.invoice_currency} {row.invoice_amount}</small>}
          </div>
          <div className="flex items-center gap-3"><span>
            {row.kind === "Application" ? "Reversible" : row.kind === "Credit" ? "Disponible" : "Pendiente"} {row.currency} {balance}
            {row.kind !== "Application" && <> / {row.amount}</>}
            {row.kind === "Credit" && row.currency !== property.currency &&
              <small className="block text-muted-foreground">Valor base {property.currency} {row.base_available} / {row.base_amount}</small>}
            {row.kind === "Opening Payable" && row.currency !== property.currency &&
              <small className="block text-muted-foreground">Deuda base {property.currency} {row.base_outstanding} / {row.base_amount}</small>}
          </span>
          {actionLabel && (selected?.name === row.name ?
            <Button type="button" size="sm" variant="outline" onClick={() => onSelect(null)}>Quitar</Button> :
            <Button type="button" size="sm" variant="outline" disabled={Number(balance) <= 0}
              onClick={() => onSelect(row)}>{actionLabel}</Button>)}
          </div>
        </div>
      })}{!page.rows.length &&
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
