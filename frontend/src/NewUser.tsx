import { useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Bootstrap } from "./api"

export function NewUser() {
  const [canManage, setCanManage] = useState<boolean | null>(null)
  const [email, setEmail] = useState("")
  const [firstName, setFirstName] = useState("")
  const [created, setCreated] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    call<Bootstrap>("bootstrap", {}, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setCanManage(Boolean(result.can_manage_users)) })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo comprobar el acceso.")
      })
    return () => controller.abort()
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canManage) return
    setBusy(true); setError(""); setCreated("")
    try {
      const result = await postMethod<{ user: string }>("create_operational_user", {
        data: { email: email.trim(), first_name: firstName.trim() },
      })
      setCreated(result.user)
      setEmail(""); setFirstName("")
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo crear el usuario.")
    } finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">Nuevo usuario</h1>
      <p className="mt-1 text-sm text-muted-foreground">Cree la cuenta de la persona. Sus accesos a establecimientos se conceden por separado.</p></div>
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {canManage === null && !error && <Skeleton className="h-64" />}
    {canManage === false && <Card><CardHeader><CardTitle>Acceso restringido</CardTitle><CardDescription>Solo administración del sistema puede crear usuarios.</CardDescription></CardHeader></Card>}
    {canManage && <>
    {created && <div role="status" className="space-y-2 rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">
      <p>Usuario {created} creado sin acceso a establecimientos.</p>
      <Button asChild variant="outline"><Link to="/users/assign">Conceder acceso</Link></Button>
    </div>}
    <Card><CardHeader><CardTitle>Cuenta de usuario</CardTitle>
      <CardDescription>El inicio de sesión se administra con los mecanismos de Frappe. La persona podrá cambiar sus propias preferencias desde Mi usuario.</CardDescription>
    </CardHeader><CardContent><form onSubmit={submit} className="grid max-w-xl gap-4">
      <label className="space-y-1 text-sm"><span>Correo electrónico</span><Input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label className="space-y-1 text-sm"><span>Nombre</span><Input required maxLength={140} value={firstName} onChange={(event) => setFirstName(event.target.value)} /></label>
      <Button disabled={busy}>Crear usuario</Button>
    </form></CardContent></Card>
    </>}
  </div>
}
