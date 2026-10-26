import { useCallback, useEffect, useState } from "react"
import { BedDouble, CalendarDays, LogIn, TicketCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod } from "./api"

type RecordRow = { kind: string; name: string; property_name: string; status: string;
  starts_at: string; ends_at: string; currency: string; amount: number | null }
type Records = { user: string; offset: number; page_length: number; has_more: boolean; records: RecordRow[] }
declare global { interface Window { hs_guest_session?: { logged_in: boolean } } }

const PAGE_SIZE = 20
const loginUrl = `/login?redirect-to=${encodeURIComponent(window.location.pathname + window.location.search)}`

export function GuestPortal() {
  const [data, setData] = useState<Records | null>(null)
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [claimToken, setClaimToken] = useState(new URLSearchParams(window.location.search).get("token"))
  const loggedIn = Boolean(window.hs_guest_session?.logged_in)

  const refresh = useCallback(async (page: number, signal?: AbortSignal) => {
    const result = await call<Records>("guest_portal_records", {
      offset: String(page), page_length: String(PAGE_SIZE),
    }, signal)
    if (!signal?.aborted) { setData(result); setOffset(page) }
  }, [])

  useEffect(() => {
    if (!loggedIn) return
    const controller = new AbortController()
    refresh(0, controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar sus estancias.")
    })
    return () => controller.abort()
  }, [loggedIn, refresh])

  async function claim() {
    if (!claimToken || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("claim_guest_booking", { token: claimToken })
      await refresh(0)
      setNotice("La reserva quedó vinculada a su cuenta.")
      setClaimToken(null)
      window.history.replaceState(null, "", window.location.pathname)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo vincular la reserva.")
    } finally { setBusy(false) }
  }

  return <div className="min-h-screen bg-background">
    <header className="border-b border-border bg-white"><div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-4">
      <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><BedDouble size={22} /></span>
        <span className="font-semibold">Hospitality Suite</span></div>
      <Button asChild variant="outline"><a href="/hospitality-book">Nueva solicitud</a></Button>
    </div></header>
    <main className="mx-auto max-w-5xl space-y-6 px-5 py-8 sm:py-12">
      <div><p className="text-sm font-semibold uppercase tracking-wider text-primary">Portal de huéspedes</p>
        <h1 className="mt-2 text-3xl font-semibold">Mis estancias</h1>
        <p className="mt-2 text-sm text-muted-foreground">Consulte las reservas, estancias y pases vinculados a su cuenta.</p></div>
      {!loggedIn ? <Card><CardHeader><CardTitle>Inicie sesión</CardTitle>
        <CardDescription>Use la cuenta con el mismo correo que consta en su reserva. Después podrá vincularla mediante el enlace que le entregó recepción.</CardDescription>
      </CardHeader><CardContent><Button asChild><a href={loginUrl}><LogIn size={17} />Iniciar sesión</a></Button></CardContent></Card> : <>
        {claimToken && <Card><CardHeader><CardTitle>Vincular reserva</CardTitle>
          <CardDescription>Al confirmar, las reservas de este huésped quedarán visibles en su cuenta. El correo de la cuenta debe coincidir con el de la reserva.</CardDescription>
        </CardHeader><CardContent><Button disabled={busy} onClick={() => void claim()}><TicketCheck size={17} />{busy ? "Vinculando…" : "Vincular a mi cuenta"}</Button></CardContent></Card>}
        {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
        {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
        {!data && !error && <Skeleton className="h-60" />}
        {data?.records.length === 0 && <Card><CardContent className="py-8 text-sm text-muted-foreground">Todavía no hay reservas vinculadas. Abra el enlace de confirmación de recepción e inicie sesión para vincularla.</CardContent></Card>}
        {data && data.records.length > 0 && <div className="space-y-3">{data.records.map((row) => <Card key={`${row.kind}:${row.name}`}><CardHeader className="gap-1"><CardTitle className="text-lg">{row.property_name}</CardTitle>
          <CardDescription>{row.kind} · {row.status}</CardDescription></CardHeader><CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <p className="flex items-center gap-2"><CalendarDays size={16} className="text-primary" />Entrada: {row.starts_at}</p>
          <p className="flex items-center gap-2"><CalendarDays size={16} className="text-primary" />Salida: {row.ends_at}</p>
          {row.amount !== null && <p className="sm:col-span-2">Importe registrado: <strong>{Number(row.amount).toFixed(2)} {row.currency}</strong></p>}
        </CardContent></Card>)}</div>}
        {data && (offset > 0 || data.has_more) && <div className="flex gap-2">
          <Button variant="outline" disabled={busy || offset === 0} onClick={() => void refresh(Math.max(0, offset - PAGE_SIZE)).catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo cambiar de página."))}>Anterior</Button>
          <Button variant="outline" disabled={busy || !data.has_more} onClick={() => void refresh(offset + PAGE_SIZE).catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo cambiar de página."))}>Siguiente</Button>
        </div>}
      </>}
    </main>
  </div>
}
