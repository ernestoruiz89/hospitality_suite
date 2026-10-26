import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { call } from "./api"

type Amounts = Record<string, { receivable: string; overdue: string; unbilled: string }>
type Hotel = {
  property: string; property_name: string; mode: string; business_date: string
  rooms: number; occupied: number; blocked: number; cleaning: number
  maintenance: number; tickets: number; overdue_tickets: number; amounts: Amounts
}
type PortfolioSnapshot = {
  checked_at: string
  properties: Hotel[]
  totals: Amounts
  counts: { properties: number; rooms: number; occupied: number;
    open_tickets: number; overdue_tickets: number }
}

const modeLabel: Record<string, string> = {
  Hotel: "Hotel", "Por tiempo": "Por tiempo", Mixed: "Hotel y por tiempo",
}

export function Portfolio({ onOpen }: { onOpen: (property: string) => void }) {
  const [data, setData] = useState<PortfolioSnapshot | null>(null)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError("")
    call<PortfolioSnapshot>("portfolio_snapshot", {}, controller.signal)
      .then(setData)
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar la cartera.")
      })
    return () => controller.abort()
  }, [refresh])

  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-3xl font-semibold">Cartera de establecimientos</h1>
        <p className="mt-2 text-sm text-muted-foreground">Situación operativa y saldos de los hoteles autorizados.</p></div>
      <Button variant="outline" onClick={() => setRefresh((value) => value + 1)}>Actualizar</Button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {!data && !error && <Skeleton className="h-72 rounded-xl" />}
    {data && <>
      <p className="text-xs text-muted-foreground">Comprobado: {data.checked_at}</p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {([
          ["Establecimientos", data.counts.properties], ["Habitaciones activas", data.counts.rooms],
          ["Ocupadas", data.counts.occupied], ["Tickets abiertos", data.counts.open_tickets],
          ["Tickets vencidos", data.counts.overdue_tickets],
        ] as const).map(([label, value]) => <Card key={label}><CardContent className="pt-5">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        </CardContent></Card>)}
      </div>
      <Card><CardHeader><CardTitle>Saldos por moneda</CardTitle>
        <p className="text-sm text-muted-foreground">Las monedas distintas se presentan por separado.</p>
      </CardHeader><CardContent className="overflow-x-auto">
        <table className="w-full min-w-lg text-left text-sm"><thead><tr className="border-b border-border text-muted-foreground">
          <th className="py-2 pr-4">Moneda</th><th className="py-2 pr-4 text-right">Por cobrar</th>
          <th className="py-2 pr-4 text-right">Sin facturar</th><th className="py-2 text-right">Vencido</th>
        </tr></thead><tbody>{Object.entries(data.totals).map(([currency, value]) =>
          <tr key={currency} className="border-b border-border last:border-0"><th className="py-2 pr-4">{currency}</th>
            <td className="py-2 pr-4 text-right tabular-nums">{value.receivable}</td>
            <td className="py-2 pr-4 text-right tabular-nums">{value.unbilled}</td>
            <td className="py-2 text-right tabular-nums">{value.overdue}</td></tr>)}
        </tbody></table>
        {!Object.keys(data.totals).length && <p className="py-3 text-sm text-muted-foreground">Sin saldos pendientes.</p>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Por establecimiento</CardTitle></CardHeader><CardContent className="overflow-x-auto">
        <table className="w-full min-w-4xl text-left text-sm"><thead><tr className="border-b border-border text-muted-foreground">
          <th className="py-2 pr-4">Hotel</th><th className="py-2 pr-4">Modalidad</th>
          <th className="py-2 pr-4">Fecha operativa</th><th className="py-2 pr-4">Ocupadas</th>
          <th className="py-2 pr-4">Bloqueadas</th><th className="py-2 pr-4">Limpieza</th>
          <th className="py-2 pr-4">Mantenimiento</th><th className="py-2 pr-4">Tickets</th>
          <th className="py-2 pr-4">Vencidos</th><th className="py-2">Acción</th>
        </tr></thead><tbody>{data.properties.map((hotel) =>
          <tr key={hotel.property} className="border-b border-border last:border-0">
            <th className="py-2 pr-4 font-medium">{hotel.property_name}</th>
            <td className="py-2 pr-4">{modeLabel[hotel.mode] || hotel.mode}</td>
            <td className="py-2 pr-4">{hotel.business_date}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.occupied}/{hotel.rooms}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.blocked}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.cleaning}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.maintenance}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.tickets}</td>
            <td className="py-2 pr-4 tabular-nums">{hotel.overdue_tickets}</td>
            <td className="py-2"><Link className="text-primary underline" to="/" onClick={() => onOpen(hotel.property)}>Abrir sede</Link></td>
          </tr>)}
        </tbody></table>
      </CardContent></Card>
    </>}
  </div>
}
