import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

type Request = {
  name: string; full_name: string; email: string; phone: string | null
  category: string; mode: string; rooms: number; people: number
  starts_at: string; ends_at: string; status: "Hold" | "Requested"
  hold_until: string | null; request_until: string | null
  amount: number; currency: string; expired: boolean
}
type Queue = { total: number; has_more: boolean; rows: Request[] }
type Quote = { amount: string; currency: string; acceptance: string }
type Review = { request: string; guest: string; customer: string; quote: Quote; key: string }

export function PortalRequests({ property, parties, guests, categories, onChanged }: {
  property: Property
  parties: { name: string; party_name: string }[]
  guests: { name: string; full_name: string; customer: string }[]
  categories: { name: string; category_name: string }[]
  onChanged: () => Promise<void>
}) {
  const [queue, setQueue] = useState<Queue | null>(null)
  const [offset, setOffset] = useState(0)
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [revision, setRevision] = useState(0)
  const [selected, setSelected] = useState("")
  const [guest, setGuest] = useState("")
  const [customer, setCustomer] = useState("")
  const [quote, setQuote] = useState<Review | null>(null)
  const [reason, setReason] = useState("")
  const [rejectKey, setRejectKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pageLength = 25

  const reload = useCallback(() => setRevision((value) => value + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    setQueue(null)
    call<Queue>("portal_request_queue", {
      property_name: property.name, offset: String(offset), page_length: String(pageLength), search,
    }, controller.signal).then(setQueue).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las solicitudes web.")
    })
    return () => controller.abort()
  }, [property.name, offset, search, revision])

  const request = queue?.rows.find((row) => row.name === selected)
  const categoryLabel = (name: string) => categories.find((row) => row.name === name)?.category_name || name
  const resetReview = () => { setQuote(null); setGuest(""); setCustomer(""); setReason(""); setRejectKey("") }
  const select = (name: string) => { setSelected(name); resetReview(); setError(""); setNotice("") }

  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!request || !guest || !customer || busy) return
    setBusy(true); setError(""); setQuote(null)
    try {
      const result = await call<Quote>("preview", { property_name: property.name,
        action: "convert_portal", data: JSON.stringify({ portal_request: request.name, guest, customer }) })
      setQuote({ request: request.name, guest, customer, quote: result, key: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la reserva.") }
    finally { setBusy(false) }
  }

  async function confirm() {
    if (!quote || quote.request !== selected || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ booking: string }>(property.name, "convert_portal", {
        portal_request: quote.request, guest: quote.guest, customer: quote.customer,
        acceptance: quote.quote.acceptance,
      }, quote.key)
      setNotice(`Solicitud convertida en reserva ${result.booking}.`)
      setSelected(""); resetReview(); setOffset(0); reload()
      await onChanged().catch(() => setError("Reserva creada. Actualice Recepción para ver los datos nuevos."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo confirmar la solicitud.") }
    finally { setBusy(false) }
  }

  async function reject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!request || !reason.trim() || busy) return
    const key = rejectKey || crypto.randomUUID()
    setRejectKey(key); setBusy(true); setError("")
    try {
      await execute(property.name, "reject_portal", { portal_request: request.name, reason: reason.trim() }, key)
      setNotice(`Solicitud ${request.name} rechazada.`)
      setSelected(""); resetReview(); setOffset(0); reload()
      await onChanged().catch(() => setError("Solicitud rechazada. Actualice Recepción para ver los datos nuevos."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo rechazar la solicitud.") }
    finally { setBusy(false) }
  }

  return <Card>
    <CardHeader><CardTitle>Solicitudes web pendientes</CardTitle><CardDescription>Revise la solicitud, asóciela a un huésped y pagador registrados y confirme la tarifa antes de crear la reserva. Horarios del establecimiento: {property.time_zone}.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
      <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); setSelected(""); resetReview(); setOffset(0); setSearch(searchInput.trim()); reload() }}>
        <Input aria-label="Buscar solicitud web" placeholder="Nombre, correo o número de solicitud" maxLength={100} value={searchInput} onChange={(event) => setSearchInput(event.target.value)} className="min-w-56 flex-1" />
        <Button type="submit" variant="outline">Buscar</Button><Button type="button" variant="outline" onClick={reload}>Actualizar</Button>
      </form>
      {!queue ? <p className="text-sm text-muted-foreground">Consultando solicitudes…</p> : <>
        <p className="text-sm text-muted-foreground">{queue.total} solicitudes pendientes · mostrando {queue.rows.length ? offset + 1 : 0}–{offset + queue.rows.length}</p>
        <div className="space-y-2">{queue.rows.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
          <div><strong>{row.full_name}</strong> · {row.name}<p>{categoryLabel(row.category)} · {row.rooms} habitación{Number(row.rooms) === 1 ? "" : "es"} · {row.people} persona{Number(row.people) === 1 ? "" : "s"} por habitación · {row.mode}</p><p>{row.starts_at} → {row.ends_at}</p><p>{row.status === "Hold" ? "Cupo retenido" : "Sin cupo reservado"} hasta {row.status === "Hold" ? row.hold_until : row.request_until}{row.expired ? " · Vencida" : ""} · {row.currency} {row.amount}</p></div>
          <Button type="button" variant="outline" onClick={() => select(row.name)}>{selected === row.name ? "Revisando" : "Revisar"}</Button>
        </div>)}{!queue.rows.length && <p className="text-sm text-muted-foreground">No hay solicitudes que coincidan.</p>}</div>
        <div className="flex gap-2"><Button type="button" variant="outline" disabled={!offset || busy} onClick={() => { setSelected(""); resetReview(); setOffset(Math.max(0, offset - pageLength)) }}>Anterior</Button><Button type="button" variant="outline" disabled={!queue.has_more || busy} onClick={() => { setSelected(""); resetReview(); setOffset(offset + pageLength) }}>Siguiente</Button></div>
      </>}
      {request && <div className="space-y-4 rounded-md border border-border p-4">
        <div><h3 className="font-semibold">{request.full_name}</h3><p className="text-sm">{request.email}{request.phone ? ` · ${request.phone}` : ""}</p><p className="text-sm text-muted-foreground">{request.status === "Hold" ? "La retención se liberará al rechazar." : "La solicitud requiere disponibilidad al confirmar."}</p></div>
        {request.expired ? <p role="alert" className="text-sm text-destructive">El plazo venció. Actualice la cola; esta solicitud no se puede convertir.</p> : <form onSubmit={preview} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Huésped registrado</span><select required value={guest} onChange={(event) => { const value = event.target.value; setGuest(value); setCustomer(guests.find((row) => row.name === value)?.customer || ""); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione un huésped</option>{guests.map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}</select></label><label className="space-y-1 text-sm"><span>Pagador</span><select required value={customer} onChange={(event) => { setCustomer(event.target.value); setQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione un pagador</option>{parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label></div>
          <Button disabled={busy}>Revisar disponibilidad y tarifa</Button>
          {quote && <div className="space-y-2 rounded-md bg-secondary p-3 text-sm"><p>Total a confirmar: <strong>{quote.quote.currency} {quote.quote.amount}</strong></p><p>La reserva se creará con habitación por asignar. No se registra cobro ni entrada.</p><Button type="button" disabled={busy} onClick={() => void confirm()}>Confirmar reserva</Button></div>}
        </form>}
        <form onSubmit={reject} className="space-y-2 border-t border-border pt-3"><label className="block space-y-1 text-sm"><span>Motivo de rechazo</span><Input required maxLength={500} value={reason} onChange={(event) => { setReason(event.target.value); setRejectKey("") }} /></label><Button variant="outline" disabled={busy || !reason.trim()}>Rechazar solicitud</Button></form>
      </div>}
    </CardContent>
  </Card>
}
