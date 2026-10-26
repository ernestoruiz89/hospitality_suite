import { useEffect, useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Property } from "./api"
import { staySections } from "./StaySections"

type View = "active" | "history"
type Stay = { name: string; status: string; booking: string | null;
  guest_label: string; room_label: string; starts_at_local: string | null;
  ends_at_local: string | null; actual_check_in_local: string | null;
  actual_check_out_local: string | null; currency: string; amount: string }
type Page = { property: string; status: View; search: string; offset: number;
  page_length: number; has_more: boolean; rows: Stay[] }
type Balance = { pending: string; scheduled: string; outstanding: string; currency: string }
type Overview = { property: string; stay: string; status: string; booking: string | null;
  guest_label: string; customer_label: string; room_label: string;
  starts_at_local: string | null; ends_at_local: string | null;
  actual_check_in_local: string | null; actual_check_out_local: string | null;
  currency: string; amount: string;
  folios: { name: string; label: string | null; shared: boolean;
    status: string; balance: Balance }[] }
type ChargePage = { property: string; stay: string; offset: number;
  page_length: number; has_more: boolean;
  rows: { name: string; folio: string; kind: string;
    description: string; status: string; amount: string;
    currency: string; business_date: string | null }[] }

const PAGE_LENGTH = 25
const dateLabel = (value: string | null) => value ? value.slice(0, 16).replace("T", " ") : "Por definir"

export function Stays({ property, provider, canFinance, canApprove }: {
  property: Property; provider: "pms" | "erpnext"; canFinance: boolean; canApprove: boolean
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get("section")
  const section = staySections.find((item) => item.id === requested) || staySections[0]
  const view: View = section.id
  const [input, setInput] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [selected, setSelected] = useState("")
  const [overview, setOverview] = useState<Overview | null>(null)
  const [charges, setCharges] = useState<ChargePage | null>(null)
  const [chargeOffset, setChargeOffset] = useState(0)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")

  useEffect(() => {
    if (!requested || requested === section.id) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section.id)
    setSearchParams(next, { replace: true })
  }, [requested, section.id, searchParams, setSearchParams])

  useEffect(() => {
    setOffset(0); setSearch(""); setInput(""); setSelected(""); setOverview(null); setCharges(null)
  }, [view])

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setError(""); setSelected(""); setOverview(null); setCharges(null)
    call<Page>("stay_page", { property_name: property.name, status: view,
      search, offset: String(offset), page_length: String(PAGE_LENGTH) }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.status !== view ||
            result.search !== search || result.offset !== offset || !Array.isArray(result.rows))
          throw new Error("La lista de estancias no coincide con la consulta solicitada.")
        setPage(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar las estancias.")
      })
    return () => controller.abort()
  }, [property.name, view, search, offset, revision])

  useEffect(() => {
    if (!location.state) return
    const target = (location.state as { stay?: { property: string; name: string } }).stay
    if (!target) return
    if (target.property !== property.name || !target.name) {
      setError("La estancia solicitada no pertenece a este establecimiento.")
    } else {
      setSelected(target.name)
      setChargeOffset(0)
    }
    navigate({ pathname: "/stays", search: location.search }, { replace: true, state: null })
  }, [location.state, location.search, navigate, property.name])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setOverview(null); setDetailError(""); setChargeOffset(0)
    call<Overview>("stay_overview", { property_name: property.name, stay: selected }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.stay !== selected)
          throw new Error("La estancia no pertenece al establecimiento seleccionado.")
        setOverview(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setDetailError(issue instanceof Error ? issue.message : "No se pudo consultar la estancia.")
      })
    return () => controller.abort()
  }, [property.name, selected])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setCharges(null)
    call<ChargePage>("stay_charge_page", { property_name: property.name,
      stay: selected, offset: String(chargeOffset),
      page_length: String(PAGE_LENGTH) }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result.property !== property.name || result.stay !== selected ||
            result.offset !== chargeOffset || !Array.isArray(result.rows))
          throw new Error("Los cargos no corresponden a la estancia seleccionada.")
        setCharges(result)
      }).catch((issue: unknown) => {
        if (!controller.signal.aborted) setDetailError(issue instanceof Error ? issue.message : "No se pudieron consultar los cargos.")
      })
    return () => controller.abort()
  }, [property.name, selected, chargeOffset])

  function searchStays(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setOffset(0); setSearch(input.trim());
    setRevision((value) => value + 1)
  }
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div>
      <h1 className="text-3xl font-semibold">{section.label}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Alojados, salidas e historial del establecimiento.</p>
    </div><div className="flex gap-2"><Button asChild variant="outline"><Link to="/reception?section=arrivals">Registrar entrada</Link></Button>
      <Button variant="outline" onClick={() => setRevision((value) => value + 1)}>Actualizar</Button></div></div>
    <Card><CardHeader><CardTitle>{view === "active" ? "Estancias activas" : "Estancias finalizadas"}</CardTitle>
      <CardDescription>Busque por código de estancia, reserva o habitación. También admite el nombre del huésped cuando el modo discreto está desactivado.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={searchStays} className="flex max-w-xl gap-2"><Input maxLength={80}
          aria-label="Buscar estancia" placeholder="Estancia, reserva, habitación o huésped"
          value={input} onChange={(event) => setInput(event.target.value)} /><Button>Buscar</Button></form>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {!page && !error && <Skeleton className="h-52 rounded-lg" />}
        {page && <><div className="space-y-2">{page.rows.map((row) => <div key={row.name}
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
          <div><strong>Habitación {row.room_label}</strong> · {row.guest_label}
            <p className="text-xs text-muted-foreground">{row.name} · {row.status} · {dateLabel(row.actual_check_in_local || row.starts_at_local)} → {dateLabel(row.actual_check_out_local || row.ends_at_local)}</p>
            {row.booking && <p className="text-xs text-muted-foreground">Reserva {row.booking}</p>}</div>
          <Button type="button" variant="outline" size="sm" onClick={() => { setSelected(row.name); setChargeOffset(0) }}>Ver estancia</Button>
        </div>)}{!page.rows.length && <p className="py-8 text-center text-sm text-muted-foreground">Sin estancias para estos filtros.</p>}</div>
          <div className="flex items-center justify-between text-sm"><span>Mostrando {page.rows.length ? page.offset + 1 : 0}–{page.offset + page.rows.length}</span>
            <div className="flex gap-2"><Button variant="outline" disabled={page.offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_LENGTH))}>Anterior</Button>
              <Button variant="outline" disabled={!page.has_more} onClick={() => setOffset(offset + PAGE_LENGTH)}>Siguiente</Button></div></div>
        </>}
      </CardContent></Card>
    {selected && <Card><CardHeader><CardTitle>Estancia {selected}</CardTitle>
      <CardDescription>Detalle operativo y cargos de la cuenta.</CardDescription></CardHeader><CardContent className="space-y-5 text-sm">
      {detailError && <p role="alert" className="text-destructive">{detailError}</p>}
      {!overview && !detailError && <Skeleton className="h-32 rounded-lg" />}
      {overview && <><div className="space-y-1"><p><strong>Habitación {overview.room_label}</strong> · {overview.guest_label}</p>
        <p>Pagador: {overview.customer_label}</p>
        <p>Entrada: {dateLabel(overview.actual_check_in_local || overview.starts_at_local)} · Salida: {dateLabel(overview.actual_check_out_local || overview.ends_at_local)}</p>
        {overview.booking && <p>Reserva {overview.booking}</p>}
        <p>Alojamiento aceptado: {overview.currency} {overview.amount}</p></div>
        <div className="flex flex-wrap gap-2"><a className="inline-flex h-9 items-center rounded-md border border-border px-3 hover:bg-secondary"
          href={`/printview?doctype=${encodeURIComponent("HS Stay")}&name=${encodeURIComponent(selected)}&format=${encodeURIComponent("HS Cuenta de estancia")}`}
          target="_blank" rel="noopener noreferrer">Imprimir cuenta</a>
          {overview.status === "Active" && <Button asChild variant="outline"><Link to="/departures" state={{ stay: { property: property.name, name: selected } }}>Revisar salida</Link></Button>}
          {provider === "pms" && canFinance && <Button asChild variant="outline"><Link to="/folios">Abrir cuentas</Link></Button>}
        </div>
        <div><strong>Cuentas</strong><div className="mt-2 space-y-2">{overview.folios.map((folio) => <div key={folio.name} className="rounded-md bg-muted p-3">
          <p>{folio.label || folio.name} · {folio.name}{folio.shared && " · Compartido con la reserva"} · {folio.status}</p>
          <p className="text-xs text-muted-foreground">Pendiente {folio.balance.currency} {folio.balance.pending} · Programado {folio.balance.scheduled} · Saldo {folio.balance.outstanding}</p>
          {provider === "erpnext" && canFinance && folio.status === "Open" && <Button asChild size="sm" variant="outline" className="mt-2"><Link to={`/erp-invoicing?folio=${encodeURIComponent(folio.name)}`}>Revisar factura</Link></Button>}
          {provider === "erpnext" && canApprove && folio.status === "Open" && <Button asChild size="sm" variant="outline" className="ml-2 mt-2"><Link to={`/erp-adjustments?folio=${encodeURIComponent(folio.name)}`}>Ajustar cargos</Link></Button>}
        </div>)}{!overview.folios.length && <p className="text-muted-foreground">Sin cuentas vinculadas.</p>}</div></div>
        <div><strong>Cargos de esta estancia</strong>{!charges ? <Skeleton className="mt-2 h-20 rounded-lg" /> :
          <><div className="mt-2 space-y-2">{charges.rows.map((charge) => <div key={charge.name} className="rounded-md border border-border p-3">
            <p>{charge.description} · {charge.status} · {charge.currency} {charge.amount}</p>
            <p className="text-xs text-muted-foreground">{charge.name} · Cuenta {charge.folio} · {charge.business_date || "Sin fecha operativa"}</p>
          </div>)}{!charges.rows.length && <p className="text-muted-foreground">Sin cargos registrados.</p>}</div>
          <div className="mt-3 flex justify-end gap-2"><Button variant="outline" disabled={charges.offset === 0}
            onClick={() => setChargeOffset(Math.max(0, chargeOffset - PAGE_LENGTH))}>Anterior</Button>
            <Button variant="outline" disabled={!charges.has_more}
              onClick={() => setChargeOffset(chargeOffset + PAGE_LENGTH)}>Siguiente</Button></div></>}
        </div>
      </>}
    </CardContent></Card>}
  </div>
}
