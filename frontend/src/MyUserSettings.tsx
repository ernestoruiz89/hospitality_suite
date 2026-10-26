import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod } from "./api"

type Settings = {
  user: string
  email: string
  first_name: string
  last_name: string
  language: string
  time_zone: string
  modified: string
  languages: { name: string; language_name: string }[]
}

const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"

export function MyUserSettings({ section }: { section: "profile" | "preferences" }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [form, setForm] = useState({ first_name: "", last_name: "", language: "", time_zone: "" })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    call<Settings>("my_user_settings", {}, controller.signal).then((data) => {
      if (controller.signal.aborted) return
      setSettings(data)
      setForm({ first_name: data.first_name, last_name: data.last_name,
        language: data.language, time_zone: data.time_zone })
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar su usuario.")
    })
    return () => controller.abort()
  }, [])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!settings || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const values = section === "profile"
        ? { first_name: form.first_name, last_name: form.last_name,
          language: settings.language, time_zone: settings.time_zone }
        : { first_name: settings.first_name, last_name: settings.last_name,
          language: form.language, time_zone: form.time_zone }
      const updated = await postMethod<Settings>("save_my_user_settings", {
        data: { ...values, expected_modified: settings.modified },
      })
      setSettings(updated)
      setForm({ first_name: updated.first_name, last_name: updated.last_name,
        language: updated.language, time_zone: updated.time_zone })
      setNotice(section === "profile" ? "Datos personales guardados." : "Preferencias guardadas.")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo guardar su usuario.")
    } finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{section === "profile" ? "Datos personales" : "Preferencias"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">Esta configuración pertenece a su cuenta y se aplica en todos los establecimientos a los que tiene acceso.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!settings ? (error ? null : <Skeleton className="h-72" />) : <Card><CardHeader><CardTitle>{section === "profile" ? "Perfil" : "Idioma y zona horaria"}</CardTitle>
      <CardDescription>{section === "profile" ? `Cuenta de acceso: ${settings.email || settings.user}. Los roles y establecimientos los gestiona administración.` : "Estas preferencias personales se aplican a todas sus sedes."}</CardDescription>
    </CardHeader><CardContent><form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
      {section === "profile" ? <>
      <label className="space-y-1 text-sm"><span>Nombre</span><Input required maxLength={140} value={form.first_name} onChange={(event) => setForm((current) => ({ ...current, first_name: event.target.value }))} /></label>
      <label className="space-y-1 text-sm"><span>Apellido</span><Input maxLength={140} value={form.last_name} onChange={(event) => setForm((current) => ({ ...current, last_name: event.target.value }))} /></label>
      </> : <>
      <label className="space-y-1 text-sm"><span>Idioma</span><select className={selectClass} value={form.language} onChange={(event) => setForm((current) => ({ ...current, language: event.target.value }))}>
        <option value="">Predeterminado del sitio</option>{settings.languages.map((row) => <option key={row.name} value={row.name}>{row.language_name || row.name}</option>)}
      </select></label>
      <label className="space-y-1 text-sm"><span>Zona horaria IANA</span><Input placeholder="America/Managua" value={form.time_zone} onChange={(event) => setForm((current) => ({ ...current, time_zone: event.target.value }))} /></label>
      <p className="text-xs text-muted-foreground sm:col-span-2">El idioma y la zona horaria se aplicarán por completo al iniciar una sesión nueva.</p>
      </>}
      <div className="sm:col-span-2"><Button disabled={busy}>{section === "profile" ? "Guardar datos personales" : "Guardar preferencias"}</Button></div>
    </form></CardContent></Card>}
  </div>
}
