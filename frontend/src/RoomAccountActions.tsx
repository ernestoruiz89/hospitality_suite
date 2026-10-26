import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"

type Account = {
  name: string; label: string | null; shared: boolean; currency: string
  pending: string; scheduled: string; outstanding: string
}
type Charge = { name: string; folio: string; description: string | null;
  amount: string; currency: string; status: string }

const chargeStates: Record<string, string> = {
  Pending: "Pendiente", Scheduled: "Programado", Invoiced: "Facturado", Posted: "Contabilizado",
}
const moneyAmount = (currency: string, amount: string | number) => {
  const value = Number(amount)
  return Number.isFinite(value) ? value.toLocaleString("es-NI", {
    style: "currency", currency,
  }) : `${currency} ${amount}`
}

export function RoomAccountActions({ accounts, charges, provider, canFinance = true }: {
  accounts: Account[]; charges: Charge[]; provider: "pms" | "erpnext"; canFinance?: boolean
}) {
  if (!accounts.length) return <p className="text-muted-foreground">Sin cuentas de estancia abiertas.</p>
  const labels = new Map(accounts.map((account) => [account.name, account.label || account.name]))

  return <div className="space-y-3 border-t pt-3">
    <p className="font-medium">Cuentas de estancia</p>
    {accounts.map((account) => {
      const pending = Number(account.pending)
      const scheduled = Number(account.scheduled)
      const outstanding = Number(account.outstanding)
      const billable = pending + scheduled
      const billed = Math.max(0, outstanding - billable)
      const payable = provider === "pms" ? outstanding - pending - scheduled : outstanding - scheduled
      const encoded = encodeURIComponent(account.name)
      const invoiceUrl = provider === "pms" ? "/folios?section=post&folio=" + encoded :
        "/erp-invoicing?folio=" + encoded
      const paymentUrl = provider === "pms" ? "/cash?section=collect&folio=" + encoded :
        "/customer-credits?section=folios&folio=" + encoded
      return <div key={account.name} className="rounded-md border p-3">
        <p className="font-medium">{account.label || account.name}{account.shared &&
          <span className="ml-2 text-xs font-normal text-muted-foreground">Compartida</span>}</p>
        <p className="text-xs text-muted-foreground">{account.name} · Saldo {moneyAmount(account.currency, account.outstanding)}</p>
        <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
          <p>Programado<span className="block font-medium">{moneyAmount(account.currency, account.scheduled)}</span></p>
          <p>{provider === "pms" ? "Sin contabilizar" : "Sin facturar"}
            <span className="block font-medium">{moneyAmount(account.currency, account.pending)}</span></p>
          <p>{provider === "pms" ? "Por cobrar contabilizado" : "Por cobrar facturado"}
            <span className="block font-medium">{moneyAmount(account.currency, billed)}</span></p>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {canFinance && billable > 0.005 && <Button asChild variant="outline" size="sm"><Link to={invoiceUrl}>
            {provider === "pms" ? "Contabilizar cargos" : "Facturar cuenta"}</Link></Button>}
          {canFinance && payable > 0.005 && <Button asChild variant="outline" size="sm"><Link to={paymentUrl}>Registrar pago</Link></Button>}
        </div>
        {provider === "pms" && billable > 0.005 && payable <= 0.005 &&
          <p className="mt-2 text-xs text-muted-foreground">Contabilice los cargos antes de registrar el pago.</p>}
      </div>
    })}
    {!!charges.length && <div className="border-t pt-3">
      <p className="font-medium">Últimos cargos de esta habitación</p>
      <ul className="mt-2 space-y-2 text-sm">{charges.map((charge) => <li key={charge.name}
        className="flex flex-wrap items-start justify-between gap-x-3 border-b pb-2 last:border-0">
        <span><strong>{charge.description || charge.name}</strong>
          <span className="block text-xs text-muted-foreground">{labels.get(charge.folio) || charge.folio} · {chargeStates[charge.status] || charge.status}</span></span>
        <span className="font-medium">{moneyAmount(charge.currency, charge.amount)}</span>
      </li>)}</ul>
      <p className="mt-1 text-xs text-muted-foreground">El saldo puede reflejar impuestos y pagos. Las cuentas compartidas pueden incluir cargos de otras habitaciones.</p>
    </div>}
  </div>
}
