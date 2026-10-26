import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { call, execute, type Property } from "./api"

type Stay = { name: string; booking: string | null; customer: string }
type Folio = { name: string; label: string | null; customer: string;
  stay: string | null; booking: string | null }
type Charge = { name: string; stay: string; description: string;
  amount: number; currency: string; status: string; modified: string }
type ChargePage = { total: number; offset: number; has_more: boolean; rows: Charge[] }
type Targets = { charge: string; source_folio: string; targets: Folio[] }

export function FolioWork({ property, stays, folios, parties, onChanged }: {
  property: Property; stays: Stay[]; folios: Folio[]
  parties: { name: string; party_name: string }[]
  onChanged: () => Promise<void>
}) {
  const [stay, setStay] = useState("")
  const [customer, setCustomer] = useState("")
  const [group, setGroup] = useState(false)
  const [label, setLabel] = useState("")
  const [source, setSource] = useState("")
  const [page, setPage] = useState<ChargePage | null>(null)
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [charge, setCharge] = useState("")
  const [targets, setTargets] = useState<Targets | null>(null)
  const [destination, setDestination] = useState("")
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const createRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const moveRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const pageLength = 25

  useEffect(() => {
    if (!source) { setPage(null); return }
    const controller = new AbortController()
    setPage(null)
    call<ChargePage>("folio_pending_charges", {
      property_name: property.name, folio: source, offset: String(offset),
      page_length: String(pageLength),
    }, controller.signal).then(setPage).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los cargos pendientes.")
    })
    return () => controller.abort()
  }, [property.name, source, offset, revision])
  useEffect(() => {
    if (!charge) { setTargets(null); return }
    const controller = new AbortController()
    setTargets(null)
    call<Targets>("folio_transfer_targets", {
      property_name: property.name, charge,
    }, controller.signal).then(setTargets).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las cuentas de destino.")
    })
    return () => controller.abort()
  }, [property.name, charge])

  const selectedStay = stays.find((row) => row.name === stay)
  const selectedCharge = page?.rows.find((row) => row.name === charge)
  const payerName = (name: string) => parties.find((row) => row.name === name)?.party_name || name
  const resetTransfer = () => { setCharge(""); setTargets(null); setDestination(""); setReason("") }
  const requestKey = (reference: { current: { fingerprint: string; key: string } | null },
    payload: object) => {
    const fingerprint = JSON.stringify([property.name, payload])
    if (reference.current?.fingerprint !== fingerprint) reference.current = {
      fingerprint, key: crypto.randomUUID(),
    }
    return reference.current.key
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedStay || !customer || group && !selectedStay.booking || busy) return
    const payload = { stay, customer, group, label: label.trim() }
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await execute<{ folio: string }>(property.name, "create_folio",
        payload, requestKey(createRequest, payload))
      createRequest.current = null
      setLabel(""); setGroup(false)
      setNotice(`Cuenta ${result.folio} creada.`)
      await onChanged().catch(() => setError("Cuenta creada. Actualice Recepción para ver la lista nueva."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo crear la cuenta.") }
    finally { setBusy(false) }
  }

  async function move(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedCharge || !targets || targets.charge !== charge ||
        !targets.targets.some((row) => row.name === destination) || !reason.trim() || busy) return
    const payload = { charge, folio: destination, reason: reason.trim() }
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "move_charge", payload, requestKey(moveRequest, payload))
      moveRequest.current = null
      resetTransfer(); setOffset(0); setRevision((value) => value + 1)
      setNotice(`Cargo ${charge} trasladado a la cuenta ${destination}.`)
      await onChanged().catch(() => setError("Cargo trasladado. Actualice Recepción para ver los datos nuevos."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo trasladar el cargo.") }
    finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Cuentas y distribución de cargos</CardTitle><CardDescription>Abra cuentas adicionales para una estancia o reserva grupal. Puede trasladar cargos pendientes; los ajustes vinculados se trasladan con el cargo principal.</CardDescription></CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    <form onSubmit={create} className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
      <h3 className="font-semibold sm:col-span-2">Abrir cuenta</h3>
      <label className="space-y-1 text-sm"><span>Estancia activa</span><select required value={stay} onChange={(event) => { const value = event.target.value; setStay(value); setCustomer(stays.find((row) => row.name === value)?.customer || ""); setGroup(false) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione estancia</option>{stays.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></label>
      <label className="space-y-1 text-sm"><span>Pagador</span><select required value={customer} onChange={(event) => setCustomer(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione pagador</option>{parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label>
      <label className="space-y-1 text-sm"><span>Etiqueta</span><Input maxLength={140} placeholder="Ej.: empresa, extras o grupo" value={label} onChange={(event) => setLabel(event.target.value)} /></label>
      <label className="flex items-center gap-2 self-end text-sm"><input type="checkbox" checked={group} disabled={!selectedStay?.booking} onChange={(event) => setGroup(event.target.checked)} />Cuenta compartida por la reserva grupal</label>
      <Button disabled={busy || !selectedStay || !customer || group && !selectedStay.booking} className="sm:col-span-2">Crear cuenta</Button>
    </form>
    <div className="space-y-3 rounded-md border border-border p-3"><h3 className="font-semibold">Trasladar cargo pendiente</h3>
      <label className="block space-y-1 text-sm"><span>Cuenta de origen</span><select value={source} onChange={(event) => { setSource(event.target.value); setOffset(0); resetTransfer() }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{folios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name} · {payerName(row.customer)}</option>)}</select></label>
      {source && (!page ? <p className="text-sm text-muted-foreground">Consultando cargos…</p> : <>
        <p className="text-xs text-muted-foreground">{page.total} cargos principales pendientes</p>
        <div className="space-y-2">{page.rows.map((row) => <button type="button" key={row.name} onClick={() => { setCharge(row.name); setDestination(""); setReason("") }} className={`block w-full rounded-md border p-3 text-left text-sm hover:bg-secondary ${charge === row.name ? "border-primary" : "border-border"}`}><strong>{row.description || row.name}</strong> · {row.currency} {row.amount}<span className="block text-xs text-muted-foreground">{row.name} · {row.status} · estancia {row.stay}</span></button>)}{!page.rows.length && <p className="text-sm text-muted-foreground">No hay cargos pendientes en esta cuenta.</p>}</div>
        <div className="flex gap-2"><Button type="button" variant="outline" disabled={!offset || busy} onClick={() => { resetTransfer(); setOffset(Math.max(0, offset - pageLength)) }}>Anterior</Button><Button type="button" variant="outline" disabled={!page.has_more || busy} onClick={() => { resetTransfer(); setOffset(offset + pageLength) }}>Siguiente</Button></div>
      </>)}
      {selectedCharge && targets?.charge === selectedCharge.name && <form onSubmit={move} className="space-y-3 border-t border-border pt-3"><p className="text-sm">Cargo {selectedCharge.name} · {selectedCharge.currency} {selectedCharge.amount}</p><label className="block space-y-1 text-sm"><span>Cuenta de destino</span><select required value={destination} onChange={(event) => setDestination(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione destino</option>{targets.targets.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name} · {payerName(row.customer)}</option>)}</select></label><label className="block space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label><Button disabled={busy || !destination || !reason.trim()}>Trasladar cargo</Button>{!targets.targets.length && <p className="text-sm text-muted-foreground">Abra otra cuenta de esta estancia o reserva para trasladar el cargo.</p>}</form>}
    </div>
  </CardContent></Card>
}
