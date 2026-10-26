import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { type Property } from "./api"
import { ApplicationPicker, type ReversibleApplication } from "./ApplicationPicker"
import { useIdempotentCommand } from "./useIdempotentCommand"

export function UnapplyDepositPms({ property, refresh, refreshToken }: {
  property: Property; refresh: () => Promise<void>; refreshToken: object
}) {
  const send = useIdempotentCommand(property.name)
  const [kind, setKind] = useState<"Advance" | "Guarantee">("Advance")
  const [selected, setSelected] = useState<ReversibleApplication | null>(null)
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  async function unapply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !selected) return
    setBusy(true); setError(""); setNotice("")
    try {
      await send(kind === "Guarantee" ? "pms_unapply_guarantee" : "pms_unapply_advance",
        { allocation: selected.name, amount, reason: reason.trim() })
      setSelected(null); setAmount(""); setReason("")
      try { await refresh(); setNotice("Aplicación revertida mediante un asiento nuevo.") }
      catch { setNotice("Aplicación revertida. Actualice la vista para consultar el saldo.") }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "No se pudo revertir la aplicación.")
    } finally { setBusy(false) }
  }

  return <Card><CardHeader><CardTitle>Revertir depósito aplicado</CardTitle>
    <CardDescription>Restituye la cuenta por cobrar y la obligación con el cliente mediante un asiento nuevo.</CardDescription>
  </CardHeader><CardContent className="space-y-3">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
    <form onSubmit={unapply} className="grid max-w-2xl gap-3 sm:grid-cols-3">
      <select value={kind} onChange={(event) => {
        setKind(event.target.value as "Advance" | "Guarantee")
        setSelected(null); setAmount("")
      }} className="h-9 rounded-md border border-border bg-white px-2 text-sm sm:col-span-3">
        <option value="Advance">Anticipo</option><option value="Guarantee">Garantía</option>
      </select>
      <ApplicationPicker property={property} kind={kind} selected={selected}
        refreshToken={refreshToken} onSelect={(row) => { setSelected(row); setAmount("") }} />
      <Input required type="number" min="0.01" step="0.01" max={selected?.remaining}
        placeholder={`Importe ${selected?.currency || property.currency}`}
        value={amount} onChange={(event) => setAmount(event.target.value)} />
      <Input required maxLength={500} placeholder="Motivo" value={reason}
        onChange={(event) => setReason(event.target.value)} />
      <Button disabled={busy || !selected}>Revertir y contabilizar</Button>
    </form>
  </CardContent></Card>
}
