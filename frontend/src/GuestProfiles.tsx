import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"

type Field = "full_name" | "email" | "phone" | "identity_type" |
  "identity_number" | "nationality" | "address_line1" | "city" | "country"
type Values = Record<Field, string>
type Directory = { total: number; offset: number; has_more: boolean;
  rows: { name: string; full_name: string }[] }
type Profile = { guest: string; property: string; customer_label: string;
  modified: string; guest_id_required: boolean;
  related_versions: Record<string, string | null>; values: Partial<Values> }
const fields: Field[] = ["full_name", "email", "phone", "identity_type",
  "identity_number", "nationality"]
const addressFields: Field[] = ["address_line1", "city", "country"]
const emptyValues: Values = { full_name: "", email: "", phone: "",
  identity_type: "", identity_number: "", nationality: "",
  address_line1: "", city: "", country: "" }

export function GuestProfiles({ property, provider, onChanged }: {
  property: Property; provider: "pms" | "erpnext"; onChanged: () => Promise<void> }) {
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [directory, setDirectory] = useState<Directory | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [values, setValues] = useState<Values>(emptyValues)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const propertyVersion = useRef(0)
  const selectionVersion = useRef(0)
  const saveRequest = useRef<{ fingerprint: string; key: string } | null>(null)

  useEffect(() => {
    propertyVersion.current += 1
    selectionVersion.current += 1
    setSearchInput(""); setSearch(""); setOffset(0); setDirectory(null)
    setProfile(null); setValues(emptyValues); setReason("")
    setError(""); setNotice(""); saveRequest.current = null
  }, [property.name])
  useEffect(() => {
    const controller = new AbortController()
    setDirectory(null)
    call<Directory>("guest_directory", { property_name: property.name,
      search, offset: String(offset), page_length: "25" }, controller.signal)
      .then(setDirectory).catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los huéspedes.")
      })
    return () => controller.abort()
  }, [property.name, search, offset, revision])

  async function selectGuest(name: string) {
    const version = propertyVersion.current
    const selection = ++selectionVersion.current
    setError(""); setNotice(""); setProfile(null)
    try {
      const detail = await call<Profile>("guest_detail", { name })
      if (version !== propertyVersion.current || selection !== selectionVersion.current) return
      if (detail.property !== property.name) throw new Error("El huésped no pertenece al establecimiento seleccionado.")
      setProfile(detail); setValues({ ...emptyValues, ...detail.values })
      setReason(""); saveRequest.current = null
    } catch (issue) { if (version === propertyVersion.current && selection === selectionVersion.current) setError(issue instanceof Error ? issue.message : "No se pudo abrir la ficha.") }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!profile || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const editable = provider === "pms" ? fields : [...fields, ...addressFields]
      const data = Object.fromEntries(editable.map((field) => [field, values[field].trim()]))
      const payload = { property_name: property.name, name: profile.guest,
        modified: profile.modified, data, reason: reason.trim(),
        related_versions: profile.related_versions }
      const fingerprint = JSON.stringify(payload)
      if (saveRequest.current?.fingerprint !== fingerprint) {
        saveRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await postMethod("update_guest", { ...payload, request_key: saveRequest.current.key })
      saveRequest.current = null
      setReason(""); setRevision((current) => current + 1)
      setNotice("Ficha del huésped corregida.")
      try {
        await onChanged()
        await selectGuest(profile.guest)
        setNotice("Ficha del huésped corregida.")
      } catch {
        setError("La ficha se guardó. Actualice la vista para cargar los datos nuevos.")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo corregir la ficha.") }
    finally { setBusy(false) }
  }

  const editable = provider === "pms" ? fields : [...fields, ...addressFields]
  const changed = Boolean(profile && editable.some((field) =>
    (profile.values[field] || "") !== values[field].trim()))
  const field = (name: Field, label: string, type = "text") =>
    <label key={name} className="block space-y-1 text-sm"><span>{label}</span>
      <Input type={type} required={name === "full_name" || name === "identity_number" && profile?.guest_id_required}
        maxLength={140} value={values[name]} onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.value }))} />
    </label>

  return <Card><CardHeader><CardTitle>Fichas de huéspedes</CardTitle><CardDescription>Corrija datos del huésped con un motivo. El pagador permanece vinculado a su ficha.</CardDescription></CardHeader><CardContent className="space-y-4">
    {error && <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-800">{notice}</p>}
    <form onSubmit={(event) => { event.preventDefault(); setOffset(0); setSearch(searchInput.trim()) }} className="flex flex-wrap gap-2"><Input maxLength={100} placeholder="Nombre o código del huésped" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} className="min-w-64 flex-1" /><Button type="submit" variant="outline">Buscar</Button></form>
    <div className="grid gap-4 lg:grid-cols-2"><div className="space-y-2">
      {!directory ? <Skeleton className="h-28 rounded-lg" /> : <>
        {directory.rows.map((guest) => <Button key={guest.name} type="button" variant={profile?.guest === guest.name ? "secondary" : "outline"} disabled={busy} className="h-auto w-full justify-start py-2 text-left" onClick={() => void selectGuest(guest.name)}>{guest.full_name} · {guest.name}</Button>)}
        {!directory.rows.length && <p className="text-sm text-muted-foreground">No se encontraron huéspedes.</p>}
        {directory.total > 25 && <div className="flex items-center justify-between gap-2 text-sm"><span>{directory.offset + 1}–{directory.offset + directory.rows.length} de {directory.total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!directory.has_more} onClick={() => setOffset(offset + 25)}>Siguiente</Button></div></div>}
      </>}
    </div>
    <div>{profile && <form onSubmit={save} className="space-y-3 rounded-lg border border-border p-3">
      <p className="text-sm"><strong>{profile.guest}</strong> · Pagador: {profile.customer_label || "Sin pagador"}</p>
      {field("full_name", "Nombre completo")}
      <div className="grid gap-3 sm:grid-cols-2">{field("email", "Correo", "email")}{field("phone", "Teléfono")}{field("identity_type", "Tipo de identificación")}{field("identity_number", "Número de identificación")}</div>
      {field("nationality", "Nacionalidad")}
      {provider === "erpnext" && <div className="grid gap-3 sm:grid-cols-3">{field("address_line1", "Dirección")}{field("city", "Ciudad")}{field("country", "País")}</div>}
      <label className="block space-y-1 text-sm"><span>Motivo de corrección</span><Input required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <Button disabled={busy || !changed || !reason.trim()}>Guardar corrección</Button>
    </form>}</div></div>
  </CardContent></Card>
}
