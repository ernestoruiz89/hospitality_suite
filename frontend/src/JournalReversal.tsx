import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { createLatestRequest } from "./latestRequest"

type JournalLine = { account: string; account_code: string; account_name: string;
  account_currency: string; debit: string; credit: string;
  debit_in_account_currency: string; credit_in_account_currency: string }
type JournalRow = { name: string; posting_date: string; source_doctype: string;
  source_name: string; memo: string | null; total_debit: string;
  total_credit: string; lines: JournalLine[] }
type JournalPage = { rows: JournalRow[]; total: number; offset: number; page_length: number }

export function JournalReversal({ property }: { property: Property }) {
  const requests = useRef(createLatestRequest())
  const [query, setQuery] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<JournalPage | null>(null)
  const [selected, setSelected] = useState("")
  const [reason, setReason] = useState("")
  const [requestKey, setRequestKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const load = useCallback((term: string, start: number, errorMessage: string) => {
    return requests.current.run((signal) => call<JournalPage>("pms_reversible_journals", {
      property_name: property.name, search: term, offset: String(start),
      page_length: "25",
    }, signal), setPage, (issue) => setError(issue instanceof Error ? issue.message : errorMessage))
  }, [property.name])

  useEffect(() => {
    setPage(null); setSelected(""); setReason(""); setRequestKey("")
    setQuery(""); setSearch(""); setOffset(0); setError(""); setNotice("")
    void load("", 0, "No se pudieron consultar los asientos.")
    return () => requests.current.abort()
  }, [load])

  const current = page?.rows.find((row) => row.name === selected)
  function find(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setSearch(query.trim()); setOffset(0); setSelected(""); setReason(""); setRequestKey("")
    setError(""); setNotice(""); setPage(null)
    void load(query.trim(), 0, "No se pudieron buscar los asientos.")
  }
  async function changePage(next: number) {
    setOffset(next); setSelected(""); setReason(""); setRequestKey("")
    setError(""); setPage(null)
    await load(search, next, "No se pudo cargar la página.")
  }
  async function reverse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!current || !reason.trim() || busy) return
    const key = requestKey || crypto.randomUUID()
    setRequestKey(key); setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ journal: string; reversed: string }>(
        property.name, "pms_reverse_journal",
        { journal: current.name, reason: reason.trim() }, key)
      setNotice(`Asiento ${result.reversed} revertido mediante ${result.journal}.`)
      setSelected(""); setReason(""); setRequestKey("")
      await load(search, offset, "No se pudo actualizar la lista de asientos.")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo revertir el asiento.")
    } finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div className="flex items-center gap-3"><RotateCcw className="text-primary" /><div><h1 className="text-3xl font-semibold">Revertir asiento</h1>
      <p className="mt-1 text-sm text-muted-foreground">Seleccione un asiento manual o saldo inicial del establecimiento. Las operaciones con saldos vinculados se corrigen desde su propio flujo.</p></div></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <Card><CardHeader><CardTitle>Asientos disponibles</CardTitle><CardDescription>Busque por número, referencia o descripción.</CardDescription></CardHeader><CardContent className="space-y-4">
      <form onSubmit={find} className="flex flex-wrap gap-2"><Input maxLength={100} className="max-w-md flex-1" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar asiento" aria-label="Buscar asiento" /><Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>
      {!page && !error ? <Skeleton className="h-52 w-full" /> : page && <>
        <div className="space-y-2">{page.rows.map((row) => <button key={row.name} type="button" onClick={() => { setSelected(row.name); setReason(""); setRequestKey("") }} className={`block w-full rounded-md border p-3 text-left text-sm hover:bg-secondary ${selected === row.name ? "border-primary" : "border-border"}`}>
          <strong>{row.name}</strong> · {row.source_doctype === "HS Opening Balance" ? "Saldo inicial" : "Asiento manual"} · {row.posting_date} · {property.currency} {row.total_debit}
          <span className="block text-xs text-muted-foreground">Referencia {row.source_name}{row.memo ? ` · ${row.memo}` : ""}</span>
        </button>)}{!page.rows.length && <p className="text-sm text-muted-foreground">No hay asientos disponibles para esta búsqueda.</p>}</div>
        <div className="flex items-center justify-between text-sm"><span>{page.total} asiento(s) · página {Math.floor(page.offset / page.page_length) + 1}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={busy || page.offset === 0} onClick={() => void changePage(Math.max(0, page.offset - page.page_length))}>Anterior</Button><Button type="button" variant="outline" disabled={busy || page.offset + page.rows.length >= page.total} onClick={() => void changePage(page.offset + page.page_length)}>Siguiente</Button></div></div>
      </>}
    </CardContent></Card>
    {current && <Card><CardHeader><CardTitle>Revisión de {current.name}</CardTitle><CardDescription>Se publicará un asiento inverso. Los importes de la tabla están en {property.currency}; el original y su referencia permanecerán en el mayor.</CardDescription></CardHeader><CardContent><form onSubmit={(event) => void reverse(event)} className="space-y-4">
      <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead><tr><th className="border-b p-2">Cuenta</th><th className="border-b p-2">Débito original</th><th className="border-b p-2">Crédito original</th><th className="border-b p-2">Débito reversión</th><th className="border-b p-2">Crédito reversión</th></tr></thead><tbody>{current.lines.map((line, index) => <tr key={`${line.account}-${index}`}><td className="border-b p-2">{line.account_code} · {line.account_name}{line.account_currency !== property.currency && <span className="block text-xs text-muted-foreground">{line.account_currency} · original {line.debit_in_account_currency} débito / {line.credit_in_account_currency} crédito</span>}</td><td className="border-b p-2">{line.debit}</td><td className="border-b p-2">{line.credit}</td><td className="border-b p-2">{line.credit}</td><td className="border-b p-2">{line.debit}</td></tr>)}</tbody></table></div>
      <label className="block space-y-1 text-sm">Motivo de reversión<Input required maxLength={500} value={reason} onChange={(event) => { setReason(event.target.value); setRequestKey("") }} placeholder="Explique el error y su soporte" /></label>
      <Button type="submit" disabled={busy || !reason.trim()}>{busy ? "Revirtiendo…" : "Confirmar reversión"}</Button>
    </form></CardContent></Card>}
  </div>
}
