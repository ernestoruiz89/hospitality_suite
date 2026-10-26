import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

export type FinanceConcept = {
  name: string; label: string; nature: string; account: string;
  active: number; modified: string
}
export type FinanceConceptDraft = {
  name?: string; modified?: string; label: string; nature: string;
  account: string; active: number
}
type Account = { name: string; account_code: string; account_name: string; root_type: string }

const roots: Record<string, string> = {
  "Other Income": "Income", Loan: "Liability", Capital: "Equity",
}
const labels: Record<string, string> = {
  "Other Income": "Otro ingreso", Loan: "Préstamo", Capital: "Capital",
}
const blank = (): FinanceConceptDraft => ({ label: "", nature: "Other Income", account: "", active: 1 })
const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"

export function FinanceConcepts({ concepts, accounts, busy, onSave }: {
  concepts: FinanceConcept[]; accounts: Account[]; busy: boolean;
  onSave: (draft: FinanceConceptDraft) => Promise<boolean>
}) {
  const [draft, setDraft] = useState<FinanceConceptDraft>(blank)
  const [editing, setEditing] = useState(false)
  const accountName = (name: string) => accounts.find((row) => row.name === name)?.account_name || name

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (await onSave({ ...draft, label: draft.label.trim() })) {
      setDraft(blank()); setEditing(false)
    }
  }

  return <div className="space-y-5">
    <Card><CardHeader><CardTitle>{editing ? "Editar concepto" : "Nuevo concepto"}</CardTitle>
      <CardDescription>La cuenta debe corresponder a ingreso, pasivo o patrimonio en moneda base. Los movimientos existentes conservan la cuenta con que se contabilizaron.</CardDescription>
    </CardHeader><CardContent><form onSubmit={save} className="grid gap-3 md:grid-cols-2">
      <label className="space-y-1 text-sm"><span>Nombre</span><Input required maxLength={140} value={draft.label}
        onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))} /></label>
      <label className="space-y-1 text-sm"><span>Naturaleza</span><select className={selectClass} value={draft.nature}
        onChange={(event) => setDraft((current) => ({ ...current, nature: event.target.value, account: "" }))}>
        {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label className="space-y-1 text-sm"><span>Cuenta contable</span><select required className={selectClass} value={draft.account}
        onChange={(event) => setDraft((current) => ({ ...current, account: event.target.value }))}>
        <option value="">Seleccione una cuenta</option>
        {accounts.filter((row) => row.root_type === roots[draft.nature]).map((row) =>
          <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}
      </select></label>
      <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={Boolean(draft.active)}
        onChange={(event) => setDraft((current) => ({ ...current, active: event.target.checked ? 1 : 0 }))} />Activo</label>
      <div className="flex flex-wrap gap-2 md:col-span-2"><Button disabled={busy}>{editing ? "Guardar cambios" : "Crear concepto"}</Button>
        {editing && <Button type="button" variant="outline" disabled={busy}
          onClick={() => { setDraft(blank()); setEditing(false) }}>Cancelar edición</Button>}</div>
    </form></CardContent></Card>
    <Card><CardHeader><CardTitle>Conceptos existentes</CardTitle>
      <CardDescription>Los inactivos dejan de aparecer en operaciones nuevas.</CardDescription>
    </CardHeader><CardContent className="space-y-2">
      {concepts.map((concept) => <div key={concept.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-2 text-sm">
        <div><p className="font-medium">{concept.label} <span className="text-muted-foreground">· {labels[concept.nature] || concept.nature}</span></p>
          <p className="text-xs text-muted-foreground">{accountName(concept.account)} · {concept.active ? "Activo" : "Inactivo"}</p></div>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => {
          setDraft({ name: concept.name, modified: concept.modified, label: concept.label,
            nature: concept.nature, account: concept.account, active: Number(concept.active) })
          setEditing(true)
        }}>Editar</Button>
      </div>)}
      {!concepts.length && <p className="text-sm text-muted-foreground">Todavía no hay conceptos financieros.</p>}
    </CardContent></Card>
  </div>
}
