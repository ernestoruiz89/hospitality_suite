import { useEffect, useRef, useState, type FormEvent } from "react"
import { BedDouble, CalendarDays, CheckCircle2, Clock3, MapPin, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"

type Category = { name: string; category_name: string; capacity: number;
  amenities?: string | null; portal_description?: string | null; portal_image?: string | null }
type Experience = { name: string; experience_name: string; duration?: string | null;
  description?: string | null; price: string; currency: string }
type Property = { name: string; property_name: string; mode: string; time_zone: string;
  currency: string; categories: Category[]; experiences: Experience[] }
type Quote = { amount: string; currency: string; acceptance: string;
  estimated_total: string; experiences_total: string; explanation: string[] }
type RequestResult = { confirmation_url: string }
type ServerResponse<T> = { message?: T; exc_type?: string }
type Form = { property: string; category: string; mode: string; request_mode: "Hold" | "Requested";
  starts_at: string; ends_at: string; quantity: string; people: string;
  full_name: string; email: string; phone: string;
  experiences: Record<string, { selected: boolean; quantity: string }> }
type Accepted = { quote: Quote; property: string; data: ReturnType<typeof payload>; requestKey: string }

const selectClass = "h-10 w-full rounded-md border border-input bg-white px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
class PortalError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

async function portalCall<T>(method: "catalog" | "quote" | "request", args: Record<string, string>, signal?: AbortSignal): Promise<T> {
  const endpoint = `/api/method/hospitality_suite.portal.${method}`
  const csrf = (window as Window & { csrf_token?: string }).csrf_token || ""
  let response: Response
  try {
    response = await fetch(method === "request" ? endpoint : `${endpoint}?${new URLSearchParams(args)}`, {
      method: method === "request" ? "POST" : "GET",
      credentials: "same-origin",
      headers: method === "request"
        ? { Accept: "application/json", "Content-Type": "application/json", "X-Frappe-CSRF-Token": csrf }
        : { Accept: "application/json" },
      body: method === "request" ? JSON.stringify(args) : undefined,
      signal,
    })
  } catch {
    throw new PortalError("Sin respuesta del servidor. Revise la conexión y reintente.", 0)
  }
  const result = (await response.json().catch(() => ({}))) as ServerResponse<T>
  if (!response.ok || result.exc_type || result.message === undefined) {
    throw new PortalError(method === "catalog" ? "No se pudieron consultar los establecimientos. Recargue la página." :
      method === "quote" ? "No se encontró disponibilidad o no se pudo calcular el precio. Revise los datos." :
      "La solicitud no fue aceptada. Revise los datos y consulte nuevamente.", response.status)
  }
  return result.message
}

function stayModes(mode: string) {
  return mode === "Mixed" ? ["Hotel", "Por tiempo", "Day Pass"] :
    mode === "Por tiempo" ? ["Por tiempo", "Day Pass"] : ["Hotel"]
}

function initialForm(prop: Property): Form {
  return { property: prop.name, category: prop.categories[0]?.name || "",
    mode: stayModes(prop.mode)[0], request_mode: "Hold", starts_at: "", ends_at: "",
    quantity: "1", people: "1", full_name: "", email: "", phone: "", experiences: {} }
}

function dayPassEnd(start: string) {
  if (!start.includes("T")) return ""
  const [date, time] = start.split("T")
  const [hour, minute] = time.split(":").map(Number)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return ""
  const end = Math.min(hour * 60 + minute + 480, 1439)
  return `${date}T${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`
}

function payload(form: Form) {
  return { category: form.category, mode: form.mode, starts_at: form.starts_at,
    ends_at: form.ends_at, quantity: Number(form.quantity), people: Number(form.people),
    full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone.trim(),
    request_mode: form.request_mode,
    experiences: Object.entries(form.experiences).filter(([, value]) => value.selected)
      .map(([experience, value]) => ({ experience, quantity: Number(value.quantity) })) }
}

export function PublicBooking() {
  const [catalog, setCatalog] = useState<Property[] | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [accepted, setAccepted] = useState<Accepted | null>(null)
  const [busy, setBusy] = useState<"quote" | "request" | null>(null)
  const [message, setMessage] = useState("")
  const revision = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    portalCall<Property[]>("catalog", {}, controller.signal).then((properties) => {
      setCatalog(properties)
      if (properties.length) setForm(initialForm(properties[0]))
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "No se pudo cargar el catálogo.")
    })
    return () => controller.abort()
  }, [])

  const property = catalog?.find((row) => row.name === form?.property)
  const category = property?.categories.find((row) => row.name === form?.category)

  function change(values: Partial<Form>) {
    revision.current += 1
    setForm((old) => old ? { ...old, ...values } : old)
    setAccepted(null)
    setMessage("")
  }

  function chooseProperty(name: string) {
    const selected = catalog?.find((row) => row.name === name)
    if (!selected) return
    revision.current += 1
    setForm((old) => ({ ...initialForm(selected), starts_at: old?.starts_at || "",
      ends_at: old?.ends_at || "", full_name: old?.full_name || "",
      email: old?.email || "", phone: old?.phone || "" }))
    setAccepted(null)
    setMessage("")
  }

  async function quote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form?.property || !form.category || busy) return
    const current = ++revision.current
    const data = payload(form)
    setBusy("quote"); setAccepted(null); setMessage("")
    try {
      const result = await portalCall<Quote>("quote", {
        property_name: form.property, data: JSON.stringify(data),
      })
      if (revision.current !== current) return
      setAccepted({ quote: result, property: form.property, data,
        requestKey: crypto.randomUUID() })
      setMessage(form.request_mode === "Hold" ?
        "Precio consultado. Revise el resumen y solicite confirmación a recepción." :
        "Precio consultado. Recepción confirmará precio y disponibilidad antes de reservar.")
    } catch (error) {
      if (revision.current === current) setMessage(error instanceof Error ? error.message : "No se pudo consultar el precio.")
    } finally { setBusy(null) }
  }

  async function request() {
    if (!accepted || busy) return
    setBusy("request"); setMessage("")
    try {
      const result = await portalCall<RequestResult>("request", {
        property_name: accepted.property,
        data: JSON.stringify({ ...accepted.data, acceptance: accepted.quote.acceptance }),
        request_key: accepted.requestKey,
      })
      const destination = new URL(result.confirmation_url, window.location.origin)
      if (destination.origin !== window.location.origin || destination.pathname !== "/hospitality-confirmation") {
        throw new Error("La confirmación devolvió una dirección inválida.")
      }
      window.location.assign(destination.pathname + destination.search)
    } catch (error) {
      if (error instanceof PortalError && error.status >= 400 && error.status < 500 && error.status !== 429) {
        revision.current += 1
        setAccepted(null)
      }
      setMessage(error instanceof Error ? error.message : "Sin confirmación del servidor. Reintente con la misma solicitud.")
    } finally { setBusy(null) }
  }

  return <div className="min-h-screen bg-background">
    <header className="border-b border-border bg-white"><div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
      <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><BedDouble size={22} /></span>
        <span className="text-lg font-semibold">Hospitality Suite</span></div>
      <div className="flex items-center gap-3"><a className="text-sm font-medium text-primary hover:underline" href="/hospitality-guest">Mis estancias</a>
        <span className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex"><ShieldCheck size={16} /> Sin cobros en línea</span></div>
    </div></header>
    <main className="mx-auto grid max-w-6xl gap-8 px-5 py-10 lg:grid-cols-[minmax(0,1fr)_22rem] lg:py-14">
      <div className="space-y-6">
        <div><p className="text-sm font-semibold uppercase tracking-wider text-primary">Reservas en línea</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Prepare su próxima estancia</h1>
          <p className="mt-3 max-w-2xl text-muted-foreground">Consulte disponibilidad y solicite confirmación a recepción. Esta página no recibe pagos.</p></div>
        {message && <p role="status" className="rounded-lg border border-border bg-white p-4 text-sm">{message}</p>}
        {!catalog && !message && <Skeleton className="h-96 rounded-xl" />}
        {catalog?.length === 0 && <Card><CardContent className="py-8">Las reservas en línea todavía no están habilitadas. Consulte directamente con recepción.</CardContent></Card>}
        {form && property && <Card><CardHeader><CardTitle>Datos de la solicitud</CardTitle><CardDescription>Las horas corresponden a {property.time_zone}.</CardDescription></CardHeader>
          <CardContent><form onSubmit={(event) => void quote(event)} className="space-y-5"><fieldset disabled={busy !== null} className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1 text-sm"><span>Establecimiento</span><select className={selectClass} value={form.property} onChange={(event) => chooseProperty(event.target.value)} required>{catalog?.map((row) => <option key={row.name} value={row.name}>{row.property_name}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Categoría</span><select className={selectClass} value={form.category} onChange={(event) => change({ category: event.target.value })} required>{property.categories.map((row) => <option key={row.name} value={row.name}>{row.category_name}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Tipo de estancia</span><select className={selectClass} value={form.mode} onChange={(event) => change({ mode: event.target.value, ends_at: event.target.value === "Day Pass" ? dayPassEnd(form.starts_at) : form.ends_at })} required>{stayModes(property.mode).map((mode) => <option key={mode} value={mode}>{mode === "Hotel" ? "Por noche" : mode}</option>)}</select></label>
              <label className="space-y-1 text-sm"><span>Tipo de solicitud</span><select className={selectClass} value={form.request_mode} onChange={(event) => change({ request_mode: event.target.value as Form["request_mode"] })}><option value="Hold">Conservar cupo temporalmente</option><option value="Requested">Solicitar sin retener cupo</option></select></label>
            </div>
            {category && <div className="rounded-lg bg-secondary p-4 text-sm"><strong>{category.category_name}</strong><p className="mt-1">{category.portal_description || `Capacidad: ${category.capacity} personas por habitación.`}</p>{category.amenities && <p className="mt-1 text-muted-foreground">{category.amenities}</p>}{category.portal_image && <img className="mt-3 max-h-64 w-full rounded-lg object-cover" src={category.portal_image} alt={`Habitación de categoría ${category.category_name}`} />}</div>}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1 text-sm"><span>Entrada</span><Input required type="datetime-local" value={form.starts_at} onChange={(event) => change({ starts_at: event.target.value, ...(form.mode === "Day Pass" ? { ends_at: dayPassEnd(event.target.value) } : {}) })} /></label>
              <label className="space-y-1 text-sm"><span>Salida</span><Input required type="datetime-local" value={form.ends_at} onChange={(event) => change({ ends_at: event.target.value })} /></label>
              <label className="space-y-1 text-sm"><span>Habitaciones</span><Input required type="number" min="1" max="10" step="1" value={form.quantity} onChange={(event) => change({ quantity: event.target.value })} /></label>
              <label className="space-y-1 text-sm"><span>Personas por habitación</span><Input required type="number" min="1" max="20" step="1" value={form.people} onChange={(event) => change({ people: event.target.value })} /></label>
            </div>
            {property.experiences.length > 0 && <fieldset className="space-y-3 rounded-lg border border-border p-4"><legend className="px-1 text-sm font-semibold">Experiencias adicionales</legend>{property.experiences.map((experience) => {
              const choice = form.experiences[experience.name] || { selected: false, quantity: "1" }
              return <div key={experience.name} className="flex flex-wrap items-center justify-between gap-3 text-sm"><label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={choice.selected} onChange={(event) => change({ experiences: { ...form.experiences, [experience.name]: { ...choice, selected: event.target.checked } } })} /><span><strong>{experience.experience_name}</strong><span className="block text-muted-foreground">{experience.price} {experience.currency}{experience.duration ? ` · ${experience.duration}` : ""}</span></span></label><Input aria-label={`Cantidad de ${experience.experience_name}`} type="number" min="1" max="20" step="1" value={choice.quantity} onChange={(event) => change({ experiences: { ...form.experiences, [experience.name]: { ...choice, quantity: event.target.value } } })} className="w-20" /></div>
            })}</fieldset>}
            <div className="grid gap-4 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Nombre</span><Input required maxLength={120} autoComplete="name" value={form.full_name} onChange={(event) => change({ full_name: event.target.value })} /></label><label className="space-y-1 text-sm"><span>Correo para la confirmación</span><Input required type="email" maxLength={140} autoComplete="email" value={form.email} onChange={(event) => change({ email: event.target.value })} /></label></div>
            <label className="block space-y-1 text-sm"><span>Teléfono (opcional)</span><Input type="tel" maxLength={140} autoComplete="tel" value={form.phone} onChange={(event) => change({ phone: event.target.value })} /></label>
            <Button disabled={!property.categories.length || busy !== null}>{busy === "quote" ? "Consultando…" : "Consultar disponibilidad y precio"}</Button>
          </fieldset></form></CardContent></Card>}
      </div>
      <aside className="space-y-5"><Card><CardHeader><CardTitle className="flex items-center gap-2"><CalendarDays size={19} /> Resumen</CardTitle><CardDescription>Recepción confirmará los detalles de su estancia.</CardDescription></CardHeader><CardContent className="space-y-4 text-sm">
        {accepted ? <><div><span className="text-muted-foreground">Alojamiento</span><p className="text-2xl font-semibold">{accepted.quote.amount} {accepted.quote.currency}</p></div>
          {Number(accepted.quote.experiences_total) > 0 && <p>Experiencias: {accepted.quote.experiences_total} {accepted.quote.currency}</p>}
          {accepted.quote.estimated_total !== accepted.quote.amount && <p>Estimado con cargos de horario: {accepted.quote.estimated_total} {accepted.quote.currency}</p>}
          {accepted.quote.explanation?.slice(0, 8).map((line, index) => <p key={index} className="border-t border-border pt-2 text-muted-foreground">{line}</p>)}
          <Button type="button" className="w-full" disabled={busy !== null} onClick={() => void request()}>{busy === "request" ? "Enviando…" : accepted.data.request_mode === "Requested" ? "Enviar solicitud sin retención" : "Solicitar confirmación"}</Button>
          <p className="text-xs text-muted-foreground">La solicitud no acredita un pago. Recepción confirmará disponibilidad, precio e impuestos aplicables.</p></>
          : <p className="text-muted-foreground">Complete los datos y consulte el precio para continuar.</p>}
      </CardContent></Card>
      <div className="space-y-3 rounded-xl border border-border bg-white p-5 text-sm text-muted-foreground"><p className="flex items-center gap-2"><MapPin size={17} /> Horario local del establecimiento</p><p className="flex items-center gap-2"><Clock3 size={17} /> {form?.request_mode === "Requested" ? "Sin cupo retenido hasta que recepción confirme." : "El cupo se conserva temporalmente al enviar la solicitud."}</p><p className="flex items-center gap-2"><CheckCircle2 size={17} /> Confirmación manual de recepción</p>{form?.mode === "Day Pass" && <p>Day Pass en esta página incluye habitación y salida el mismo día.</p>}</div>
      </aside>
    </main>
  </div>
}
