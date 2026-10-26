import { useEffect, useRef, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"

type Folio = { name: string; label: string | null; customer_name: string; currency: string }
type FolioPage = { rows: Folio[]; has_more: boolean }
type Charge = { name: string; description: string; amount: string; current_amount: string;
  currency: string; status: string; stay: string }
type ChargePage = { folio: string; rows: Charge[]; has_more: boolean }
type Kind = "Discount" | "Courtesy" | "Surcharge"
type Quote = { folio: string; charge: string; description: string; currency: string;
  adjustment_type: Kind; original_amount: string; available_amount: string;
  amount: string; signed_amount: string; new_amount: string; reason: string;
  acceptance: string }

const PAGE_LENGTH = 25
const errorText = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo completar la operación."

export function ErpAdjustments({ property }: { property: Property }) {
  const [params] = useSearchParams()
  const initialFolio = params.get("folio") || ""
  const [search, setSearch] = useState(initialFolio)
  const [appliedSearch, setAppliedSearch] = useState(initialFolio)
  const [folioOffset, setFolioOffset] = useState(0)
  const [folioPage, setFolioPage] = useState<FolioPage | null>(null)
  const [folio, setFolio] = useState(initialFolio)
  const [chargeOffset, setChargeOffset] = useState(0)
  const [chargePage, setChargePage] = useState<ChargePage | null>(null)
  const [charge, setCharge] = useState("")
  const [kind, setKind] = useState<Kind>("Discount")
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [quote, setQuote] = useState<Quote | null>(null)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setFolioPage(null); setError("")
    call<FolioPage>("erp_adjustment_folios", { property_name: property.name,
      search: appliedSearch, offset: String(folioOffset), page_length: String(PAGE_LENGTH),
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setFolioPage(result)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(errorText(issue))
    })
    return () => controller.abort()
  }, [property.name, appliedSearch, folioOffset])

  const selectedFolio = folioPage?.rows.find((row) => row.name === folio)
  useEffect(() => {
    if (!selectedFolio) { setChargePage(null); return }
    const controller = new AbortController()
    setChargePage(null)
    call<ChargePage>("erp_adjustment_charges", { property_name: property.name,
      folio: selectedFolio.name, offset: String(chargeOffset), page_length: String(PAGE_LENGTH),
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted && result.folio === selectedFolio.name) setChargePage(result)
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(errorText(issue))
    })
    return () => controller.abort()
  }, [property.name, selectedFolio?.name, chargeOffset, revision])

  const selectedCharge = chargePage?.rows.find((row) => row.name === charge)
  function clearReview() { setQuote(null); setError(""); setNotice(""); pending.current = null }
  function selectFolio(name: string) {
    setFolio(name); setCharge(""); setChargeOffset(0); setChargePage(null)
    setAmount(""); setReason(""); clearReview()
  }
  function searchFolios(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); selectFolio(""); setFolioOffset(0); setAppliedSearch(search.trim())
  }
  function selectCharge(row: Charge) {
    setCharge(row.name); setKind("Discount"); setAmount(""); setReason(""); clearReview()
  }
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedCharge || !selectedFolio || busy || !reason.trim()) return
    setBusy(true); setError(""); setNotice(""); setQuote(null)
    try {
      const result = await postMethod<Quote>("erp_adjustment_quote", {
        property_name: property.name,
        data: { charge: selectedCharge.name, adjustment_type: kind,
          amount: kind === "Courtesy" ? selectedCharge.current_amount : amount,
          reason: reason.trim() },
      })
      if (result.folio !== selectedFolio.name || result.charge !== selectedCharge.name)
        throw new Error("La revisión no coincide con el cargo seleccionado.")
      setQuote(result); pending.current = null
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }
  async function confirm() {
    if (!quote || !selectedCharge || quote.charge !== selectedCharge.name || busy) return
    const signature = JSON.stringify([property.name, quote.charge, quote.acceptance])
    if (pending.current?.signature !== signature) pending.current = {
      signature, key: crypto.randomUUID(),
    }
    setBusy(true); setError(""); setNotice("")
    try {
      await execute(property.name, "adjustment", {
        charge: quote.charge, adjustment_type: quote.adjustment_type,
        amount: quote.amount, reason: quote.reason, acceptance: quote.acceptance,
      }, pending.current.key)
      pending.current = null
      setQuote(null); setCharge(""); setAmount(""); setReason("")
      setNotice("Ajuste registrado. Revise el cargo actualizado antes de otro cambio.")
      setRevision((value) => value + 1)
    } catch (issue) { setError(errorText(issue)) }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Ajustar cargos de la cuenta</h1>
      <p className="mt-1 text-sm text-muted-foreground">{property.brand_name || property.property_name} · Gerencia puede aplicar descuentos, cortesías y recargos a cargos pendientes de facturar.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <Card><CardHeader><CardTitle>Cuentas abiertas</CardTitle><CardDescription>Busque la cuenta antes de elegir un cargo.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={searchFolios} className="flex flex-wrap gap-2"><Input aria-label="Buscar cuentas" maxLength={80} value={search}
          onChange={(event) => setSearch(event.target.value)} className="min-w-48 flex-1" /><Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>
        {!folioPage && !error ? <Skeleton className="h-36" /> : folioPage && <>
          <div className="space-y-2">{folioPage.rows.map((row) => <button type="button" key={row.name}
            onClick={() => selectFolio(row.name)} className={`block w-full rounded-md border p-3 text-left text-sm hover:bg-secondary ${folio === row.name ? "border-primary bg-secondary/50" : "border-border"}`}>
            <strong>{row.label || row.name}</strong> · {row.currency}<span className="block text-xs text-muted-foreground">{row.name} · {row.customer_name}</span>
          </button>)}{!folioPage.rows.length && <p className="text-sm text-muted-foreground">No hay cuentas abiertas con ese criterio.</p>}</div>
          <div className="flex gap-2"><Button variant="outline" disabled={busy || !folioOffset} onClick={() => { selectFolio(""); setFolioOffset(Math.max(0, folioOffset - PAGE_LENGTH)) }}>Anterior</Button>
            <Button variant="outline" disabled={busy || !folioPage.has_more} onClick={() => { selectFolio(""); setFolioOffset(folioOffset + PAGE_LENGTH) }}>Siguiente</Button></div>
        </>}
      </CardContent></Card>
    {selectedFolio && <Card><CardHeader><CardTitle>Cargos pendientes</CardTitle><CardDescription>{selectedFolio.label || selectedFolio.name} · Seleccione un cargo principal. Los cargos facturados se corrigen mediante nota de crédito.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        {!chargePage && !error ? <Skeleton className="h-36" /> : chargePage && <>
          <div className="space-y-2">{chargePage.rows.map((row) => <button type="button" key={row.name} disabled={Number(row.current_amount) <= 0}
            onClick={() => selectCharge(row)} className={`block w-full rounded-md border p-3 text-left text-sm hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60 ${charge === row.name ? "border-primary bg-secondary/50" : "border-border"}`}>
            <strong>{row.description}</strong><span className="block text-xs text-muted-foreground">{row.name} · {row.status} · Original {row.currency} {row.amount} · Disponible {row.currency} {row.current_amount}</span>
          </button>)}{!chargePage.rows.length && <p className="text-sm text-muted-foreground">Esta cuenta no tiene cargos pendientes ajustables.</p>}</div>
          <div className="flex gap-2"><Button variant="outline" disabled={busy || !chargeOffset} onClick={() => { setCharge(""); clearReview(); setChargeOffset(Math.max(0, chargeOffset - PAGE_LENGTH)) }}>Anterior</Button>
            <Button variant="outline" disabled={busy || !chargePage.has_more} onClick={() => { setCharge(""); clearReview(); setChargeOffset(chargeOffset + PAGE_LENGTH) }}>Siguiente</Button></div>
        </>}
      </CardContent></Card>}
    {selectedCharge && <Card><CardHeader><CardTitle>Preparar ajuste</CardTitle><CardDescription>{selectedCharge.description} · Disponible {selectedCharge.currency} {selectedCharge.current_amount}</CardDescription></CardHeader>
      <CardContent><form onSubmit={(event) => void review(event)} className="grid max-w-xl gap-4">
        <label className="space-y-1 text-sm"><span>Tipo</span><select className="h-9 w-full rounded-md border border-border bg-white px-2" value={kind}
          onChange={(event) => { setKind(event.target.value as Kind); clearReview() }}>
          <option value="Discount">Descuento</option><option value="Courtesy">Cortesía total</option><option value="Surcharge">Recargo</option>
        </select></label>
        {kind !== "Courtesy" && <label className="space-y-1 text-sm"><span>Importe ({selectedCharge.currency})</span><Input required type="number" min="0.01" step="0.01" value={amount}
          onChange={(event) => { setAmount(event.target.value); clearReview() }} /></label>}
        <label className="space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={reason} onChange={(event) => { setReason(event.target.value); clearReview() }} /></label>
        <Button type="submit" variant="outline" disabled={busy || !reason.trim() || kind !== "Courtesy" && !(Number(amount) > 0)}>Revisar ajuste</Button>
      </form></CardContent></Card>}
    {quote && selectedCharge?.name === quote.charge && <Card><CardHeader><CardTitle>Revisión de ajuste</CardTitle>
      <CardDescription>{quote.description} · {quote.adjustment_type === "Discount" ? "Descuento" : quote.adjustment_type === "Courtesy" ? "Cortesía" : "Recargo"}</CardDescription></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>Importe original: <strong>{quote.currency} {quote.original_amount}</strong></p>
        <p>Disponible antes del ajuste: <strong>{quote.currency} {quote.available_amount}</strong></p>
        <p>Ajuste: <strong>{quote.currency} {quote.signed_amount}</strong></p>
        <p>Nuevo importe pendiente: <strong>{quote.currency} {quote.new_amount}</strong></p>
        <p>Motivo: {quote.reason}</p>
        <Button type="button" disabled={busy} onClick={() => void confirm()}>Confirmar ajuste</Button>
      </CardContent></Card>}
  </div>
}
