import { useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { availableFiscalArchiveSections } from "./FiscalArchiveSections"

type FiscalDocument = {
  name: string
  document_type: "Invoice" | "Credit Note"
  document_number: string
  business_date: string
  buyer_name: string
  currency: string
  total_amount: number
  historical_source_invoice?: string | null
  historical_day_pass?: string | null
  status: string
}
type Archive = { total: number; offset: number; page_length: number; documents: FiscalDocument[] }
type NativeDocument = { name: string; document_type: "Invoice" | "Credit Note";
  posting_date: string; buyer_name: string; currency: string; total_amount: string;
  source_invoice: string | null; is_opening: boolean; status: "Posted" | "Cancelled";
  can_print: boolean }
type NativeArchive = { total: number; offset: number; page_length: number;
  documents: NativeDocument[] }
type HistoricalDocument = { name: string; document_type: "Invoice" | "Credit Note";
  document_number: string; posting_date: string; buyer_name: string;
  currency: string; total_amount: string; status: "Posted" | "Cancelled";
  source_doctype: string; source_name: string }
type HistoricalArchive = { total: number; offset: number; page_length: number;
  documents: HistoricalDocument[] }
const PAGE_SIZE = 50

function HistoricalFiscalArchive({ property }: { property: Property }) {
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<HistoricalArchive | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError("")
    call<HistoricalArchive>("historical_fiscal_archive", {
      property_name: property.name, offset: String(offset),
      page_length: String(PAGE_SIZE), search,
    }, controller.signal).then(setData).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el archivo trasladado.")
    })
    return () => controller.abort()
  }, [property.name, offset, search])

  return <Card><CardHeader><CardTitle>Documentos trasladados de ERPNext {data && `(${data.total})`}</CardTitle></CardHeader><CardContent className="space-y-3">
    <form onSubmit={(event) => { event.preventDefault(); setOffset(0); setSearch(query.trim()) }} className="flex max-w-xl flex-wrap gap-2">
      <Input aria-label="Buscar documento trasladado" placeholder="Número, cliente o documento de origen" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} className="min-w-48 flex-1" />
      <Button>Buscar</Button>
    </form>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <Skeleton className="h-40 rounded-xl" />}
    {data && <>
      {data.documents.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3 text-sm">
        <div><strong>{row.document_number}</strong> · {row.document_type === "Invoice" ? "Factura" : "Nota de crédito"}{row.status === "Cancelled" && " · Anulada"}
          <p className="text-muted-foreground">{row.posting_date} · {row.buyer_name || "Cliente no indicado"} · {row.source_doctype} {row.source_name}</p></div>
        <span>{row.currency} {row.total_amount}</span>
        <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/api/method/hospitality_suite.api.historical_fiscal_pdf?document=${encodeURIComponent(row.name)}`}>Imprimir copia</a>
      </div>)}
      {!data.documents.length && <p className="text-sm text-muted-foreground">No hay documentos trasladados para esta búsqueda.</p>}
      <div className="flex items-center justify-between pt-3 text-sm text-muted-foreground">
        <span>{data.total ? `${data.offset + 1}–${Math.min(data.offset + data.documents.length, data.total)} de ${data.total}` : "0 documentos"}</span>
        <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button>
          <Button variant="outline" disabled={offset + data.documents.length >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</Button></div>
      </div>
    </>}
  </CardContent></Card>
}

function ErpArchive({ property }: { property: Property }) {
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<NativeArchive | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError("")
    call<NativeArchive>("erp_fiscal_archive", {
      property_name: property.name, offset: String(offset),
      page_length: String(PAGE_SIZE), search,
    }, controller.signal).then(setData).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los documentos ERPNext.")
    })
    return () => controller.abort()
  }, [property.name, offset, search])

  return <Card><CardHeader><CardTitle>Facturas y notas ERPNext {data && `(${data.total})`}</CardTitle></CardHeader><CardContent className="space-y-3">
    <form onSubmit={(event) => { event.preventDefault(); setOffset(0); setSearch(query.trim()) }} className="flex max-w-xl flex-wrap gap-2">
      <Input aria-label="Buscar documento ERPNext" placeholder="Número, cliente o factura original" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} className="min-w-48 flex-1" />
      <Button>Buscar</Button>
    </form>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <Skeleton className="h-48 rounded-xl" />}
    {data && <>
      {data.documents.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3 text-sm">
        <div><strong>{row.name}</strong> · {row.document_type === "Invoice" ? "Factura" : "Nota de crédito"}{row.is_opening && " · Apertura"}{row.status === "Cancelled" && " · Anulada"}
          <p className="text-muted-foreground">{row.posting_date} · {row.buyer_name}{row.source_invoice && ` · Original ${row.source_invoice}`}</p></div>
        <span>{row.currency} {row.total_amount}</span>
        {row.can_print ? <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/printview?doctype=${encodeURIComponent("Sales Invoice")}&name=${encodeURIComponent(row.name)}`}>Imprimir</a>
          : <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/app/sales-invoice/${encodeURIComponent(row.name)}`}>Ver anulada</a>}
      </div>)}
      {!data.documents.length && <p className="text-sm text-muted-foreground">No hay documentos ERPNext para esta búsqueda.</p>}
      <div className="flex items-center justify-between pt-3 text-sm text-muted-foreground">
        <span>{data.total ? `${data.offset + 1}–${Math.min(data.offset + data.documents.length, data.total)} de ${data.total}` : "0 documentos"}</span>
        <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button>
          <Button variant="outline" disabled={offset + data.documents.length >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</Button></div>
      </div>
    </>}
  </CardContent></Card>
}

function PmsArchive({ property, provider }: { property: Property; provider: "pms" | "erpnext" }) {
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<Archive | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError("")
    call<Archive>("pms_fiscal_archive", {
      property_name: property.name, offset: String(offset),
      page_length: String(PAGE_SIZE), search,
    }, controller.signal).then(setData).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el archivo fiscal.")
    })
    return () => controller.abort()
  }, [property.name, offset, search])

  function find(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setOffset(0)
    setSearch(query.trim())
  }

  return <>
    <Card><CardHeader><CardTitle>{provider === "erpnext" ? "Buscar documento PMS histórico" : "Buscar documento PMS"}</CardTitle></CardHeader><CardContent>
      <form onSubmit={find} className="flex max-w-xl flex-wrap gap-2">
        <Input aria-label="Número de documento" placeholder="Número o prefijo" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} className="min-w-48 flex-1" />
        <Button>Buscar</Button>
      </form>
    </CardContent></Card>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {!data && !error && <Skeleton className="h-72 rounded-xl" />}
    {data && <Card><CardHeader><CardTitle>Documentos PMS ({data.total})</CardTitle></CardHeader><CardContent className="space-y-2">
      {data.documents.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3 text-sm">
        <div><strong>{row.document_number}</strong> · {row.document_type === "Invoice" ? "Factura" : "Nota de crédito"}
          <p className="text-muted-foreground">{row.business_date} · {row.buyer_name}{row.historical_day_pass && ` · Devolución Day Pass ${row.historical_day_pass}`}</p></div>
        <span>{row.currency} {row.total_amount}</span>
        <a className="rounded-md border border-border px-3 py-1.5 hover:bg-secondary" target="_blank" rel="noopener noreferrer" href={`/printview?doctype=${encodeURIComponent("HS PMS Fiscal Document")}&name=${encodeURIComponent(row.name)}&format=${encodeURIComponent("HS Documento fiscal PMS")}`}>Imprimir</a>
      </div>)}
      {!data.documents.length && <p className="text-sm text-muted-foreground">No hay documentos para esta búsqueda.</p>}
      <div className="flex items-center justify-between pt-3 text-sm text-muted-foreground">
        <span>{data.total ? `${data.offset + 1}–${Math.min(data.offset + data.documents.length, data.total)} de ${data.total}` : "0 documentos"}</span>
        <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button>
          <Button variant="outline" disabled={offset + data.documents.length >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</Button></div>
      </div>
    </CardContent></Card>}
  </>
}

export function FiscalArchive({ property, provider }: { property: Property; provider: "pms" | "erpnext" }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sections = availableFiscalArchiveSections(provider)
  const requested = searchParams.get("section")
  const section = sections.find((item) => item.id === requested) || sections[0]

  useEffect(() => {
    if (!requested || requested === section.id) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section.id)
    setSearchParams(next, { replace: true })
  }, [requested, section.id, searchParams, setSearchParams])

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Archivo fiscal · {property.property_name}. Consulte e imprima los documentos de esta fuente. El usuario verifica el registro y la autorización que le correspondan.</p></div>
    {section.id === "erp" && <ErpArchive property={property} />}
    {section.id === "pms" && <PmsArchive property={property} provider={provider} />}
    {section.id === "historical" && <HistoricalFiscalArchive property={property} />}
  </div>
}
