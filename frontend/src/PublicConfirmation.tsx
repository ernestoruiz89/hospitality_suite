import { useState } from "react"
import { BedDouble, CalendarDays, CheckCircle2, Clock3, Mail, MapPin } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { postMethod } from "./api"

type Confirmation = { property_name: string; status: string; starts_at: string;
  ends_at: string; hold_until?: string | null; request_until?: string | null;
  currency: string; amount: string; time_zone: string;
  experiences_total: string; estimated_total: string; can_link_guest?: boolean }

declare global { interface Window { hs_confirmation?: Confirmation } }

const statusLabels: Record<string, string> = {
  Hold: "Solicitud recibida; pendiente de confirmación manual",
  Requested: "Solicitud recibida sin cupo reservado",
  Confirmed: "Reserva confirmada",
  Converted: "Solicitud convertida en reserva",
  Expired: "Solicitud vencida",
  Cancelled: "Cancelada",
  Rejected: "Solicitud rechazada",
  "Checked In": "Entrada registrada",
  Completed: "Completada",
  "No Show": "Reserva sin presentación",
  Draft: "Borrador",
}

function localDate(value?: string | null) {
  return value ? value.replace("T", " ").slice(0, 16) : "—"
}

export function PublicConfirmation() {
  const data = window.hs_confirmation
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const token = new URLSearchParams(window.location.search).get("token")

  async function requestAccess() {
    if (!token || busy) return
    setBusy(true); setError(""); setMessage("")
    try {
      await postMethod("request_guest_portal_account", { token })
      setMessage("Si su cuenta es nueva, recibirá un correo para activarla. Después inicie sesión y vincule la reserva.")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo solicitar el acceso.")
    } finally { setBusy(false) }
  }
  if (!data) return <main className="mx-auto max-w-xl p-8"><Card><CardContent className="py-8">No se pudo mostrar la confirmación.</CardContent></Card></main>
  return <div className="min-h-screen bg-background">
    <header className="border-b border-border bg-white"><div className="mx-auto flex max-w-4xl items-center gap-3 px-5 py-4"><span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><BedDouble size={22} /></span><span className="text-lg font-semibold">Hospitality Suite</span></div></header>
    <main className="mx-auto max-w-4xl space-y-6 px-5 py-10 sm:py-16">
      <div><p className="text-sm font-semibold uppercase tracking-wider text-primary">Confirmación de alojamiento</p><h1 className="mt-2 text-3xl font-semibold">{data.property_name}</h1></div>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CheckCircle2 size={22} className="text-primary" /> {statusLabels[data.status] || data.status}</CardTitle><CardDescription>Conserve este enlace para consultar el estado de su solicitud.</CardDescription></CardHeader>
        <CardContent className="space-y-5 text-sm"><div className="grid gap-4 sm:grid-cols-2"><p className="flex items-center gap-2"><CalendarDays size={17} className="text-primary" /><span>Entrada: <strong>{localDate(data.starts_at)}</strong></span></p><p className="flex items-center gap-2"><CalendarDays size={17} className="text-primary" /><span>Salida: <strong>{localDate(data.ends_at)}</strong></span></p></div>
          <p className="flex items-center gap-2 text-muted-foreground"><MapPin size={17} /> Zona horaria: {data.time_zone}</p>
          {data.status === "Hold" && data.hold_until && <p className="flex items-center gap-2"><Clock3 size={17} className="text-primary" /> Cupo conservado hasta: <strong>{localDate(data.hold_until)}</strong></p>}
          {data.status === "Requested" && data.request_until && <p className="flex items-center gap-2"><Clock3 size={17} className="text-primary" /> Sin cupo reservado. Recepción debe confirmar antes de: <strong>{localDate(data.request_until)}</strong></p>}
          <div className="rounded-lg bg-secondary p-4"><p>Alojamiento: <strong>{data.amount} {data.currency}</strong></p>{Number(data.experiences_total) > 0 && <><p className="mt-2">Experiencias adicionales: {data.experiences_total} {data.currency}</p><p className="mt-2">Total estimado: <strong>{data.estimated_total} {data.currency}</strong></p></>}</div>
          <p className="flex items-start gap-2 text-muted-foreground"><Mail size={17} className="mt-0.5 shrink-0" /> Esta página no acredita un pago. {data.status === "Hold" || data.status === "Requested" ? "Recepción debe confirmar disponibilidad, precio e impuestos aplicables." : "Para cambios o consultas, contacte con recepción."}</p>
        </CardContent></Card>
      <div className="flex flex-wrap gap-3">
        {data.can_link_guest && <Button asChild><a href={`/hospitality-guest${window.location.search}`}>Vincular a mi cuenta</a></Button>}
        <Button asChild variant="outline"><a href="/hospitality">Solicitar otra estancia</a></Button>
      </div>
      {data.can_link_guest && <Card><CardHeader><CardTitle className="text-lg">¿Aún no tiene cuenta?</CardTitle>
        <CardDescription>Solicite el acceso al correo registrado en la reserva. El enlace de activación llega allí; la reserva solo se vincula después de iniciar sesión.</CardDescription>
      </CardHeader><CardContent className="space-y-3">
        <Button variant="outline" disabled={busy || !token} onClick={() => void requestAccess()}>{busy ? "Solicitando…" : "Solicitar cuenta de huésped"}</Button>
        {message && <p role="status" className="text-sm text-emerald-800">{message}</p>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent></Card>}
    </main>
  </div>
}
