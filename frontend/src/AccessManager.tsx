import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"

type Access = { name: string; user: string; full_name: string; enabled: boolean;
  user_type: string | null; roles: string[] }
type Board = { property: string; roles: string[]; users: Access[];
  offset: number; has_more: boolean }
const ROLE_LABELS: Record<string, string> = {
  "HS Administrator": "Administrador HS", "HS Manager": "Gerencia",
  "HS Supervisor": "Supervisión", "HS Receptionist": "Recepción",
  "HS Cashier": "Caja", "HS Housekeeping": "Limpieza",
  "HS Maintenance": "Mantenimiento", "HS Accountant": "Contabilidad",
  "HS Auditor": "Auditoría",
}

export function AccessManager({ property, section }: { property: Property; section: "directory" | "assign" }) {
  const [board, setBoard] = useState<Board | null>(null)
  const [users, setUsers] = useState<Access[]>([])
  const [email, setEmail] = useState("")
  const [roles, setRoles] = useState<string[]>([])
  const [reason, setReason] = useState("")
  const [revokeUser, setRevokeUser] = useState("")
  const [revokeReason, setRevokeReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const pending = useRef<{ signature: string; key: string } | null>(null)

  const load = useCallback(async (offset = 0, signal?: AbortSignal) => {
    const result = await call<Board>("user_access_board", {
      property_name: property.name, offset: String(offset), page_length: "50",
    }, signal)
    if (signal?.aborted) return
    setBoard(result)
    setUsers((current) => offset ? [...current, ...result.users] : result.users)
  }, [property.name])

  useEffect(() => {
    const controller = new AbortController()
    setBoard(null); setUsers([]); setError(""); setNotice("")
    setEmail(""); setRoles([]); setReason("")
    setRevokeUser(""); setRevokeReason(""); pending.current = null
    load(0, controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los accesos.")
    })
    return () => controller.abort()
  }, [load])

  function toggle(role: string) {
    setRoles((current) => current.includes(role)
      ? current.filter((entry) => entry !== role) : [...current, role])
  }

  async function submit(action: "assign_user" | "revoke_user_access",
    data: Record<string, unknown>) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    const signature = JSON.stringify([property.name, action, data])
    if (pending.current?.signature !== signature) pending.current = {
      signature, key: crypto.randomUUID(),
    }
    try {
      await execute(property.name, action, data, pending.current.key)
      await load()
      pending.current = null
      if (action === "assign_user") {
        setNotice(`Acceso registrado para ${email.trim()}.`)
        setEmail(""); setRoles([]); setReason("")
      } else {
        setNotice(`Acceso retirado para ${revokeUser}.`)
        setRevokeUser(""); setRevokeReason("")
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo actualizar el acceso.")
    } finally { setBusy(false) }
  }

  function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!roles.length) { setError("Seleccione al menos un rol."); return }
    void submit("assign_user", { email: email.trim(), roles, reason: reason.trim() })
  }

  function revoke(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!revokeUser || !revokeReason.trim()) return
    void submit("revoke_user_access", { user: revokeUser,
      reason: revokeReason.trim() })
  }

  return <Card><CardHeader><CardTitle>{section === "assign" ? "Asignar usuario" : "Personal con acceso"}</CardTitle>
    <CardDescription>{section === "assign"
      ? "Solo administración del sistema concede acceso. Los roles de Frappe son globales para el usuario y se aplican en todos sus establecimientos asignados."
      : "Consulte los usuarios del establecimiento y retire su acceso cuando corresponda. El retiro conserva los roles globales y el acceso a otros hoteles."}</CardDescription>
  </CardHeader><CardContent className="space-y-5">
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!board ? <Skeleton className="h-40" /> : <>
      {section === "assign" && <form onSubmit={grant} className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2"><span>Correo de un usuario existente</span><Input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <div className="grid gap-2 sm:col-span-2 sm:grid-cols-3">{board.roles.map((role) =>
          <label key={role} className="flex items-center gap-2 text-sm"><input type="checkbox"
            checked={roles.includes(role)} onChange={() => toggle(role)} />{ROLE_LABELS[role] || role}</label>)}</div>
        <label className="space-y-1 text-sm sm:col-span-2"><span>Motivo</span><Input maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <p className="text-xs text-muted-foreground sm:col-span-2">Si la persona aún no tiene cuenta, <Link className="underline" to="/users/new">cree el usuario</Link> primero. Incluya todos los roles HS que ya posee. Si tiene acceso a otro hotel, no se pueden agregar roles globales desde aquí.</p>
        <Button disabled={busy || !roles.length} className="sm:col-span-2">Conceder acceso</Button>
      </form>}
      {section === "assign" && notice && <Button asChild variant="outline"><Link to="/users">Ver directorio de usuarios</Link></Button>}
      {section === "directory" && <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-medium">Usuarios asignados ({users.length}{board.has_more ? "+" : ""})</h3><Button asChild size="sm"><Link to="/users/assign">Conceder acceso</Link></Button></div>
        {users.map((entry) => <div key={entry.name} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm">
          <div><strong>{entry.full_name}</strong><p className="text-muted-foreground">{entry.user} · {entry.roles.map((role) => ROLE_LABELS[role] || role).join(", ") || "Sin rol HS"}{!entry.enabled && " · Deshabilitado"}</p></div>
          <Button type="button" variant="outline" size="sm" onClick={() => { setRevokeUser(entry.user); setRevokeReason("") }}>Retirar acceso</Button>
        </div>)}
        {!users.length && <p className="text-sm text-muted-foreground">No hay usuarios asignados directamente.</p>}
        {board.has_more && <Button type="button" variant="outline" disabled={busy}
          onClick={() => { setBusy(true); setError(""); load(users.length)
            .catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron cargar más usuarios."))
            .finally(() => setBusy(false)) }}>Cargar más</Button>}
      </div>}
      {section === "directory" && revokeUser && <form onSubmit={revoke} className="space-y-3 rounded-lg border bg-muted/30 p-4">
        <h3 className="font-medium">Retirar acceso de {revokeUser}</h3>
        <p className="text-sm text-muted-foreground">Se retira este establecimiento. Los roles globales y accesos a otros hoteles se conservan.</p>
        <label className="block space-y-1 text-sm"><span>Motivo del retiro</span><Input required maxLength={1000} value={revokeReason} onChange={(event) => setRevokeReason(event.target.value)} /></label>
        <div className="flex gap-2"><Button disabled={busy}>Retirar acceso</Button><Button type="button" variant="outline" onClick={() => setRevokeUser("")}>Cancelar</Button></div>
      </form>}
    </>}
  </CardContent></Card>
}
