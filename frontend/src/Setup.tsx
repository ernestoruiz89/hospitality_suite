import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, postMethod, type Property } from "./api"
import { FinancialLookup } from "./FinancialLookup"
import { ServiceAccounting } from "./ServiceAccounting"
import { setupSections, useSetupSection } from "./SetupSections"

type Config = { modified: string; property_name: string; brand_name: string | null;
  mode: string; lodging_charge_policy: string; time_zone: string;
  check_in_time: string; check_out_time: string; close_time: string;
  cleaning_minutes: number; hold_minutes: number; inspection_required: number;
  discreet_mode: number; guest_id_required: number; allow_credit: number;
  retention_days: number;
  portal_enabled: number; checkout_inspection_required: number;
  checkout_quote_minutes: number; schedule_grace_minutes: number;
  schedule_rounding_minutes: number; financial_enabled: number;
  tax_policy_confirmed: number; cost_center: string | null;
  warehouse: string | null; laundry_warehouse: string | null;
  pms_linen_operating_warehouse: string | null;
  pms_linen_laundry_warehouse: string | null;
  pms_linen_clearing_account: string | null;
  pms_exchange_variance_account: string | null;
  income_account: string | null; expense_account: string | null;
  receivable_account: string | null; guarantee_account: string | null;
  cash_transfer_account: string | null; lodging_item: string | null;
  extra_hour_item: string | null; day_pass_item: string | null;
  penalty_item: string | null; timing_item: string | null;
  agent_commission_item: string | null; tax_template: string | null;
  price_list: string | null; invoice_series: string | null;
  payment_series: string | null; invoice_print_format: string | null;
  receipt_print_format: string | null }
type Category = { name: string; modified: string; category_name: string; capacity: number;
  amenities: string | null; max_extra_beds: number }
type Room = { name: string; modified: string; room_number: string; category: string;
  floor: string | null; zone: string | null; beds: number; parking: string | null;
  active: number }
type Rate = { name: string; modified: string; title: string; category: string; mode: string;
  day_pass: number; currency: string; amount: number; block_hours: number;
  priority: number; active: number }
type Board = { property: Config; categories: Category[]; rooms: Room[];
  rates: Rate[]; currencies: string[];
  pms_variance_accounts: { name: string; account_code: string;
    account_name: string; root_type: string }[] }
type DocumentOptions = { series: Record<string, string[]>;
  formats: Record<string, string[]> }
type LinenOptions = { warehouses: { name: string; warehouse_name: string }[];
  accounts: { name: string; account_code: string; account_name: string }[] }
type Editing = { section: "category" | "room" | "rate"; name: string;
  modified: string; fields: Record<string, string | number> }

const selectClass = "h-9 w-full rounded-md border border-border bg-white px-2 text-sm"
const issueText = (issue: unknown) => issue instanceof Error ? issue.message : "No se pudo guardar la configuración."
const timeValue = (value: string | null | undefined) => (value || "").slice(0, 5)

const financialGroups = [
  { id: "accounts", fields: [
    ["cost_center", "Centro de costo"],
    ["income_account", "Ingresos del establecimiento"],
    ["expense_account", "Gastos del establecimiento"],
    ["receivable_account", "Cuentas por cobrar"],
    ["guarantee_account", "Garantías recibidas"],
    ["cash_transfer_account", "Traslado de efectivo"],
  ] },
  { id: "warehouses", fields: [
    ["warehouse", "Almacén principal"],
    ["laundry_warehouse", "Almacén de lavandería"],
  ] },
  { id: "sales", fields: [
    ["lodging_item", "Alojamiento"], ["extra_hour_item", "Hora adicional"],
    ["day_pass_item", "Day Pass sin habitación"],
    ["penalty_item", "Penalizaciones"], ["timing_item", "Cargos por horario"],
    ["agent_commission_item", "Comisión de agencias"],
  ] },
  { id: "pricing-taxes", fields: [
    ["price_list", "Lista de precios"], ["tax_template", "Plantilla de impuestos"],
  ] },
  { id: "finance-enable", fields: [] },
] as const

export function Setup({ property, provider }: {
  property: Property; provider: "pms" | "erpnext"
}) {
  const navigate = useNavigate()
  const section = useSetupSection(provider)
  const sectionInfo = setupSections.find((item) => item.id === section)!
  const activeFinancialGroup = financialGroups.find((group) => group.id === section)
  const [board, setBoard] = useState<Board | null>(null)
  const [general, setGeneral] = useState<Record<string, string | number>>({})
  const [retentionDays, setRetentionDays] = useState("0")
  const [schedule, setSchedule] = useState<Record<string, string | number>>({})
  const [finance, setFinance] = useState<Record<string, string | number>>({})
  const [documentOptions, setDocumentOptions] = useState<DocumentOptions | null>(null)
  const [linenOptions, setLinenOptions] = useState<LinenOptions | null>(null)
  const [linen, setLinen] = useState<Record<string, string>>({})
  const [exchangeAccount, setExchangeAccount] = useState("")
  const [documents, setDocuments] = useState<Record<string, string>>({})
  const [categoryName, setCategoryName] = useState("")
  const [categoryCapacity, setCategoryCapacity] = useState("2")
  const [categoryAmenities, setCategoryAmenities] = useState("")
  const [roomNumber, setRoomNumber] = useState("")
  const [roomCategory, setRoomCategory] = useState("")
  const [roomFloor, setRoomFloor] = useState("")
  const [roomZone, setRoomZone] = useState("")
  const [roomBeds, setRoomBeds] = useState("1")
  const [rateTitle, setRateTitle] = useState("")
  const [rateCategory, setRateCategory] = useState("")
  const [rateMode, setRateMode] = useState("Hotel")
  const [rateDayPass, setRateDayPass] = useState(false)
  const [rateCurrency, setRateCurrency] = useState(property.currency)
  const [rateAmount, setRateAmount] = useState("")
  const [rateHours, setRateHours] = useState("3")
  const [ratePriority, setRatePriority] = useState("10")
  const [editing, setEditing] = useState<Editing | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => { setEditing(null) }, [section])

  const load = useCallback(async (signal?: AbortSignal) => {
    const [result, options, pmsLinenOptions] = await Promise.all([
      call<Board>("setup_board", { property_name: property.name }, signal),
      provider === "erpnext" ? call<DocumentOptions>("setup_options",
        { property_name: property.name }, signal) : Promise.resolve(null),
      provider === "pms" ? call<LinenOptions>("pms_linen_setup_options",
        { property_name: property.name }, signal) : Promise.resolve(null),
    ])
    if (signal?.aborted) return
    setBoard(result)
    const config = result.property
    setRetentionDays(String(config.retention_days || 0))
    setGeneral({ brand_name: config.brand_name || "", mode: config.mode,
      lodging_charge_policy: config.lodging_charge_policy || "Arrival",
      time_zone: config.time_zone, cleaning_minutes: config.cleaning_minutes,
      hold_minutes: config.hold_minutes, inspection_required: config.inspection_required,
      discreet_mode: config.discreet_mode, guest_id_required: config.guest_id_required,
      allow_credit: config.allow_credit, portal_enabled: config.portal_enabled })
    setSchedule({ check_in_time: timeValue(config.check_in_time),
      check_out_time: timeValue(config.check_out_time), close_time: timeValue(config.close_time),
      checkout_inspection_required: config.checkout_inspection_required,
      checkout_quote_minutes: config.checkout_quote_minutes,
      schedule_grace_minutes: config.schedule_grace_minutes,
      schedule_rounding_minutes: config.schedule_rounding_minutes })
    if (provider === "erpnext") {
      setDocumentOptions(options)
      setDocuments({ invoice_series: config.invoice_series || "",
        payment_series: config.payment_series || "",
        invoice_print_format: config.invoice_print_format || "",
        receipt_print_format: config.receipt_print_format || "" })
      const financial: Record<string, string | number> = {
        financial_enabled: config.financial_enabled || 0,
        tax_policy_confirmed: config.tax_policy_confirmed || 0,
      }
      for (const group of financialGroups) {
        for (const [field] of group.fields) financial[field] = config[field] || ""
      }
      setFinance(financial)
    } else {
      setExchangeAccount(config.pms_exchange_variance_account || "")
      setLinenOptions(pmsLinenOptions)
      setLinen({ pms_linen_operating_warehouse: config.pms_linen_operating_warehouse || "",
        pms_linen_laundry_warehouse: config.pms_linen_laundry_warehouse || "",
        pms_linen_clearing_account: config.pms_linen_clearing_account || "" })
    }
    setRateCurrency((current) => result.currencies.includes(current) ? current : property.currency)
  }, [property.name, property.currency, provider])

  useEffect(() => {
    const controller = new AbortController()
    setBoard(null); setError(""); setNotice("")
    load(controller.signal).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issueText(issue))
    })
    return () => controller.abort()
  }, [load])

  async function save(section: string, values: object, label: string,
    after?: () => void, expectedModified?: string) {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await postMethod("save_setup", { property_name: property.name, section,
        data: values, request_key: crypto.randomUUID(),
        ...((section === "property" || expectedModified) ? {
          expected_modified: expectedModified || board?.property.modified } : {}) })
      if (section === "property") { window.location.reload(); return }
      await load(); after?.(); setNotice(`${label} guardado.`)
    } catch (issue) { setError(issueText(issue)) }
    finally { setBusy(false) }
  }

  const setGeneralField = (name: string, value: string | number) =>
    setGeneral((current) => ({ ...current, [name]: value }))
  const setScheduleField = (name: string, value: string | number) =>
    setSchedule((current) => ({ ...current, [name]: value }))
  const setEditField = (name: string, value: string | number) =>
    setEditing((current) => current ? { ...current,
      fields: { ...current.fields, [name]: value } } : null)
  const check = (name: string, value: number | string, setter: (name: string, value: number) => void,
    label: string) => <label key={name} className="flex items-center gap-2 text-sm"><input type="checkbox"
      checked={Boolean(Number(value))} onChange={(event) => setter(name, event.target.checked ? 1 : 0)} />{label}</label>
  const documentFields: [string, string, string[], string][] = documentOptions ? [
    ["invoice_series", "Serie de facturas", documentOptions.series["Sales Invoice"] || [], "Automática de ERPNext"],
    ["payment_series", "Serie de pagos", documentOptions.series["Payment Entry"] || [], "Automática de ERPNext"],
    ["invoice_print_format", "Formato de factura", documentOptions.formats["Sales Invoice"] || [], "Predeterminado de Suite"],
    ["receipt_print_format", "Formato de recibo", documentOptions.formats["HS Payment"] || [], "Predeterminado de Suite"],
  ] : []
  const visibleDocumentFields = documentFields.filter(([field]) => section === "document-series" ?
    field.endsWith("_series") : field.endsWith("_print_format"))

  return <div className="space-y-6">
    <div><p className="text-sm font-medium text-primary">Configuración del establecimiento</p>
      <h1 className="mt-1 text-3xl font-semibold">{sectionInfo.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{sectionInfo.description} · {property.brand_name || property.property_name}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {!board ? <Skeleton className="h-96" /> : <>
      {section === "identity" && <Card><CardHeader><CardTitle>Identidad y modalidad</CardTitle><CardDescription>La modalidad y zona horaria se aplican a las operaciones futuras del establecimiento.</CardDescription></CardHeader><CardContent>
        <form onSubmit={(event: FormEvent) => { event.preventDefault(); void save("property", {
          brand_name: general.brand_name, mode: general.mode,
          time_zone: general.time_zone }, "Identidad y modalidad") }} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Nombre comercial</span><Input value={general.brand_name ?? ""} onChange={(event) => setGeneralField("brand_name", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Modalidad</span><select className={selectClass} value={general.mode ?? "Hotel"} onChange={(event) => setGeneralField("mode", event.target.value)}><option value="Hotel">Por noche</option><option value="Por tiempo">Por tiempo</option><option value="Mixed">Mixta</option></select></label>
          <label className="space-y-1 text-sm"><span>Zona horaria IANA</span><Input required value={general.time_zone ?? ""} onChange={(event) => setGeneralField("time_zone", event.target.value)} /></label>
          <Button disabled={busy} className="sm:col-span-2">Guardar identidad</Button>
        </form>
      </CardContent></Card>}
      {section === "reservations" && <Card><CardHeader><CardTitle>Reservas y huéspedes</CardTitle><CardDescription>Estas políticas se aplican a nuevas reservas, estancias y solicitudes del portal.</CardDescription></CardHeader><CardContent>
        <form onSubmit={(event: FormEvent) => { event.preventDefault(); void save("property", {
          lodging_charge_policy: general.lodging_charge_policy,
          hold_minutes: Number(general.hold_minutes),
          guest_id_required: general.guest_id_required,
          allow_credit: general.allow_credit,
          portal_enabled: general.portal_enabled }, "Reservas y huéspedes") }} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Generar alojamiento</span><select className={selectClass} value={general.lodging_charge_policy ?? "Arrival"} onChange={(event) => setGeneralField("lodging_charge_policy", event.target.value)}><option value="Arrival">Al ingresar</option><option value="Nightly">Por noche en el cierre</option></select></label>
          <label className="space-y-1 text-sm"><span>Retención de reserva (minutos)</span><Input required type="number" min="1" max="1440" value={general.hold_minutes ?? 15} onChange={(event) => setGeneralField("hold_minutes", event.target.value)} /></label>
          <div className="flex flex-wrap gap-4 sm:col-span-2">{[
            ["guest_id_required", "Identificación de huésped"],
            ["allow_credit", "Permitir crédito autorizado"],
            ["portal_enabled", "Mostrar en portal de reservas"],
          ].map(([name, label]) => check(name, general[name] ?? 0, setGeneralField, label))}</div>
          <Button disabled={busy} className="sm:col-span-2">Guardar reservas</Button>
        </form>
      </CardContent></Card>}
      {section === "housekeeping" && <Card><CardHeader><CardTitle>Limpieza</CardTitle><CardDescription>Defina el tiempo entre estancias y el control de inspección de habitaciones.</CardDescription></CardHeader><CardContent>
        <form onSubmit={(event: FormEvent) => { event.preventDefault(); void save("property", {
          cleaning_minutes: Number(general.cleaning_minutes),
          inspection_required: general.inspection_required }, "Limpieza") }} className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm"><span>Limpieza entre estancias (minutos)</span><Input required type="number" min="0" value={general.cleaning_minutes ?? 0} onChange={(event) => setGeneralField("cleaning_minutes", event.target.value)} /></label>
          {check("inspection_required", general.inspection_required ?? 0, setGeneralField, "Inspección de limpieza")}
          <Button disabled={busy} className="sm:col-span-2">Guardar limpieza</Button>
        </form>
      </CardContent></Card>}
      {section === "privacy" && <Card><CardHeader><CardTitle>Privacidad</CardTitle>
        <CardDescription>Gerencia revisa identificaciones y evidencias de documentos cerrados cuando vence este plazo. Cero desactiva la revisión.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => { event.preventDefault(); void save("property", {
        retention_days: Number(retentionDays),
        discreet_mode: general.discreet_mode }, "Privacidad") }} className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-sm"><span>Días de conservación</span>
          <Input required type="number" min="0" max="36500" step="1" value={retentionDays}
            onChange={(event) => setRetentionDays(event.target.value)} className="w-48" /></label>
        {check("discreet_mode", general.discreet_mode ?? 0, setGeneralField, "Modo discreto")}
        <Button disabled={busy}>Guardar privacidad</Button>
      </form></CardContent></Card>}
      {activeFinancialGroup && provider === "erpnext" && <Card><CardHeader><CardTitle>{sectionInfo.label}</CardTitle>
        <CardDescription>{section === "finance-enable" ?
          "Active las operaciones financieras después de configurar las cuentas, almacenes y artículos requeridos." :
          `${sectionInfo.description}. Los cambios se aplican a las operaciones futuras.`}</CardDescription>
      </CardHeader><CardContent>
        <form onSubmit={(event) => {
          event.preventDefault()
          const values: Record<string, string | number> = Object.fromEntries(
            activeFinancialGroup.fields.map(([field]) => [field, finance[field] || ""]))
          if (section === "pricing-taxes") values.tax_policy_confirmed = finance.tax_policy_confirmed || 0
          if (section === "finance-enable") values.financial_enabled = finance.financial_enabled || 0
          void save("property", values, sectionInfo.label)
        }} className="space-y-5">
          {!!activeFinancialGroup.fields.length && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {activeFinancialGroup.fields.map(([field, label]) =>
              <FinancialLookup key={field} propertyName={property.name} field={field} label={label}
                value={String(finance[field] || "")}
                onChange={(value) => setFinance((current) => ({ ...current, [field]: value }))} />)}
          </div>}
          {section === "pricing-taxes" && check("tax_policy_confirmed", finance.tax_policy_confirmed || 0,
            (field, value) => setFinance((current) => ({ ...current, [field]: value })),
            "Registrar que revisé el tratamiento tributario (opcional)")}
          {section === "finance-enable" && <div className="space-y-3">
            {check("financial_enabled", finance.financial_enabled || 0,
              (field, value) => setFinance((current) => ({ ...current, [field]: value })),
              "Habilitar operaciones financieras")}
            <p className="text-xs text-muted-foreground">Se requieren centro de costo, almacén, cuentas por cobrar, garantías y artículo de alojamiento. Las cuentas deben ser válidas para la compañía y su moneda.</p>
          </div>}
          <Button disabled={busy}>{section === "finance-enable" ? "Guardar estado financiero" : `Guardar ${sectionInfo.label.toLowerCase()}`}</Button>
        </form>
      </CardContent></Card>}
      {section === "linen" && provider === "pms" && <Card><CardHeader><CardTitle>Ropa del hotel</CardTitle>
        <CardDescription>Seleccione almacenes distintos y una cuenta temporal de activo en moneda base. Los movimientos de lavandería conservarán los almacenes y cuentas usados al registrarse.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => { event.preventDefault(); void save("property", linen, "Ropa del hotel") }} className="grid gap-3 sm:grid-cols-3">
        {([ ["pms_linen_operating_warehouse", "Ropa operativa"],
          ["pms_linen_laundry_warehouse", "En lavandería"] ] as const).map(([field, label]) =>
          <label key={field} className="space-y-1 text-sm"><span>{label}</span><select className={selectClass} value={linen[field] || ""} onChange={(event) => setLinen((current) => ({ ...current, [field]: event.target.value }))}><option value="">Sin configurar</option>{linenOptions?.warehouses.map((row) => <option key={row.name} value={row.name}>{row.warehouse_name}</option>)}</select></label>)}
        <label className="space-y-1 text-sm"><span>Cuenta temporal para traslado</span><select className={selectClass} value={linen.pms_linen_clearing_account || ""} onChange={(event) => setLinen((current) => ({ ...current, pms_linen_clearing_account: event.target.value }))}><option value="">Sin configurar</option>{linenOptions?.accounts.map((row) => <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}</select></label>
        <Button disabled={busy} className="sm:col-span-3">Guardar almacenes de ropa</Button>
      </form></CardContent></Card>}
      {section === "exchange" && provider === "pms" && <Card><CardHeader><CardTitle>Diferencia cambiaria</CardTitle>
        <CardDescription>Seleccione una cuenta activa de ingresos o gastos en moneda base. Los pagos de deudas extranjeras conservarán la cuenta usada al contabilizar.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => { event.preventDefault(); void save("property", {
        pms_exchange_variance_account: exchangeAccount || null }, "Diferencia cambiaria") }} className="flex flex-wrap items-end gap-3">
        <label className="min-w-72 flex-1 space-y-1 text-sm"><span>Cuenta de diferencia cambiaria</span>
          <select className={selectClass} value={exchangeAccount} onChange={(event) => setExchangeAccount(event.target.value)}>
            <option value="">Sin configurar</option>{board.pms_variance_accounts.map((row) =>
              <option key={row.name} value={row.name}>{row.account_code} · {row.account_name} · {row.root_type === "Income" ? "Ingreso" : "Gasto"}</option>)}
          </select></label>
        <Button disabled={busy}>Guardar cuenta</Button>
      </form></CardContent></Card>}
      {section === "service-accounts" && provider === "erpnext" && <ServiceAccounting property={property} />}
      {(section === "document-series" || section === "print-formats") && provider === "erpnext" && documentOptions && <Card><CardHeader><CardTitle>{sectionInfo.label}</CardTitle>
        <CardDescription>Seleccione opciones ya configuradas en ERPNext para los próximos documentos.</CardDescription>
      </CardHeader><CardContent><form onSubmit={(event) => { event.preventDefault(); void save("property",
        Object.fromEntries(visibleDocumentFields.map(([field]) => [field, documents[field] || ""])), sectionInfo.label) }} className="grid gap-3 sm:grid-cols-2">
        {visibleDocumentFields.map(([field, label, choices, defaultLabel]) =>
          <label key={field} className="space-y-1 text-sm"><span>{label}</span><select className={selectClass}
            value={documents[field] || ""} onChange={(event) => setDocuments((current) => ({ ...current, [field]: event.target.value }))}>
            <option value="">{defaultLabel}</option>{choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
          </select></label>)}
        <Button disabled={busy} className="sm:col-span-2">Guardar {section === "document-series" ? "series" : "formatos"}</Button>
      </form></CardContent></Card>}
      {section === "schedules" && <Card><CardHeader><CardTitle>Horarios</CardTitle><CardDescription>Horas locales de {general.time_zone}; revise los cargos de horario en Contabilidad antes de habilitarlos.</CardDescription></CardHeader><CardContent>
        <form onSubmit={(event: FormEvent) => { event.preventDefault(); void save("property", {
          ...schedule, schedule_grace_minutes: Number(schedule.schedule_grace_minutes),
          schedule_rounding_minutes: Number(schedule.schedule_rounding_minutes),
          checkout_quote_minutes: Number(schedule.checkout_quote_minutes) }, "Horarios") }} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[["check_in_time", "Entrada habitual"], ["check_out_time", "Salida habitual"], ["close_time", "Corte del día operativo"]].map(([name, label]) => <label key={name} className="space-y-1 text-sm"><span>{label}</span><Input required type="time" value={schedule[name] ?? ""} onChange={(event) => setScheduleField(name, event.target.value)} /></label>)}
          {[["schedule_grace_minutes", "Tolerancia (min)"], ["schedule_rounding_minutes", "Fracción de cobro (min)"], ["checkout_quote_minutes", "Plazo para liquidar salida (min)"]].map(([name, label]) => <label key={name} className="space-y-1 text-sm"><span>{label}</span><Input required type="number" min="0" value={schedule[name] ?? 0} onChange={(event) => setScheduleField(name, event.target.value)} /></label>)}
          {check("checkout_inspection_required", schedule.checkout_inspection_required ?? 0, setScheduleField, "Exigir inspección antes de la salida")}
          <Button disabled={busy} className="sm:col-span-2 lg:col-span-3">Guardar horarios</Button>
        </form>
      </CardContent></Card>}
      {(section === "categories" || section === "categories-new") && <Card><CardHeader><CardTitle>{section === "categories-new" ? "Nueva categoría" : `Categorías (${board.categories.length})`}</CardTitle><CardDescription>Cree la categoría antes de registrar habitaciones y tarifas.</CardDescription></CardHeader><CardContent className="space-y-4">
        {section === "categories-new" && <form onSubmit={(event) => { event.preventDefault(); void save("category", { category_name: categoryName.trim(), capacity: Number(categoryCapacity), amenities: categoryAmenities.trim() }, "Categoría", () => { setCategoryName(""); setCategoryAmenities(""); navigate("/setup?section=categories") }) }} className="grid gap-3 sm:grid-cols-3">
          <label className="space-y-1 text-sm"><span>Nombre</span><Input required value={categoryName} onChange={(event) => setCategoryName(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Capacidad</span><Input required type="number" min="1" value={categoryCapacity} onChange={(event) => setCategoryCapacity(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Comodidades</span><Input value={categoryAmenities} onChange={(event) => setCategoryAmenities(event.target.value)} /></label>
          <Button disabled={busy} className="sm:col-span-3">Crear categoría</Button>
        </form>}
        {section === "categories" && <Button asChild variant="outline"><Link to="/setup?section=categories-new">Nueva categoría</Link></Button>}
        {section === "categories" && !board.categories.length && <p className="text-sm text-muted-foreground">Todavía no hay categorías registradas.</p>}
        {section === "categories" && <div className="flex flex-wrap gap-2 text-sm">{board.categories.map((item) => <div key={item.name} className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
          <span>{item.category_name} · {item.capacity} personas</span><Button type="button" variant="outline" size="sm"
            onClick={() => setEditing({ section: "category", name: item.name, modified: item.modified,
              fields: { category_name: item.category_name, capacity: String(item.capacity),
                amenities: item.amenities || "", max_extra_beds: String(item.max_extra_beds || 0) } })}>Editar</Button>
        </div>)}</div>}
        {section === "categories" && editing?.section === "category" && <form onSubmit={(event) => { event.preventDefault(); const fields = editing.fields;
          void save("category", { name: editing.name, category_name: String(fields.category_name).trim(),
            capacity: Number(fields.capacity), amenities: String(fields.amenities).trim(),
            max_extra_beds: Number(fields.max_extra_beds) }, "Categoría", () => setEditing(null), editing.modified)
        }} className="grid gap-3 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2">
          <h3 className="font-medium sm:col-span-2">Editar categoría</h3>
          <label className="space-y-1 text-sm"><span>Nombre</span><Input required value={editing.fields.category_name} onChange={(event) => setEditField("category_name", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Capacidad</span><Input required type="number" min="1" value={editing.fields.capacity} onChange={(event) => setEditField("capacity", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Camas extra máximas</span><Input required type="number" min="0" value={editing.fields.max_extra_beds} onChange={(event) => setEditField("max_extra_beds", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Comodidades</span><Input value={editing.fields.amenities} onChange={(event) => setEditField("amenities", event.target.value)} /></label>
          <div className="flex gap-2 sm:col-span-2"><Button disabled={busy}>Guardar categoría</Button><Button type="button" variant="outline" onClick={() => setEditing(null)}>Cancelar</Button></div>
        </form>}
      </CardContent></Card>}
      {(section === "rooms" || section === "rooms-new") && <Card><CardHeader><CardTitle>{section === "rooms-new" ? "Nueva habitación" : `Habitaciones (${board.rooms.length})`}</CardTitle><CardDescription>La disponibilidad usa la categoría y el estado activo de cada habitación.</CardDescription></CardHeader><CardContent className="space-y-4">
        {section === "rooms-new" && <form onSubmit={(event) => { event.preventDefault(); void save("room", { room_number: roomNumber.trim(), category: roomCategory, floor: roomFloor.trim(), zone: roomZone.trim(), beds: Number(roomBeds), active: 1 }, "Habitación", () => { setRoomNumber(""); navigate("/setup?section=rooms") }) }} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="space-y-1 text-sm"><span>Número</span><Input required value={roomNumber} onChange={(event) => setRoomNumber(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Categoría</span><select required className={selectClass} value={roomCategory} onChange={(event) => setRoomCategory(event.target.value)}><option value="">Seleccione</option>{board.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Piso</span><Input value={roomFloor} onChange={(event) => setRoomFloor(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Zona</span><Input value={roomZone} onChange={(event) => setRoomZone(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Camas</span><Input required type="number" min="1" value={roomBeds} onChange={(event) => setRoomBeds(event.target.value)} /></label>
          <Button disabled={busy || !board.categories.length} className="sm:col-span-2 lg:col-span-5">Crear habitación</Button>
        </form>}
        {section === "rooms" && <Button asChild variant="outline"><Link to="/setup?section=rooms-new">Nueva habitación</Link></Button>}
        {section === "rooms" && !board.rooms.length && <p className="text-sm text-muted-foreground">Todavía no hay habitaciones registradas.</p>}
        {section === "rooms" && <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">{board.rooms.map((item) => <div key={item.name} className="rounded-md border border-border p-3 text-sm"><strong>{item.room_number}</strong><p className="text-muted-foreground">{board.categories.find((entry) => entry.name === item.category)?.category_name || item.category}{!item.active && " · Inactiva"}</p>
          <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => setEditing({
            section: "room", name: item.name, modified: item.modified,
            fields: { room_number: item.room_number, category: item.category,
              floor: item.floor || "", zone: item.zone || "", beds: String(item.beds),
              parking: item.parking || "", active: item.active },
          })}>Editar</Button></div>)}</div>}
        {section === "rooms" && editing?.section === "room" && <form onSubmit={(event) => { event.preventDefault(); const fields = editing.fields;
          void save("room", { name: editing.name, room_number: String(fields.room_number).trim(),
            category: fields.category, floor: String(fields.floor).trim(),
            zone: String(fields.zone).trim(), beds: Number(fields.beds),
            parking: String(fields.parking).trim(), active: Number(fields.active) },
          "Habitación", () => setEditing(null), editing.modified)
        }} className="grid gap-3 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <h3 className="font-medium sm:col-span-2 lg:col-span-3">Editar habitación</h3>
          <label className="space-y-1 text-sm"><span>Número</span><Input required value={editing.fields.room_number} onChange={(event) => setEditField("room_number", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Categoría</span><select required className={selectClass} value={editing.fields.category} onChange={(event) => setEditField("category", event.target.value)}>{board.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Camas</span><Input required type="number" min="1" value={editing.fields.beds} onChange={(event) => setEditField("beds", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Piso</span><Input value={editing.fields.floor} onChange={(event) => setEditField("floor", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Zona</span><Input value={editing.fields.zone} onChange={(event) => setEditField("zone", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Estacionamiento</span><Input value={editing.fields.parking} onChange={(event) => setEditField("parking", event.target.value)} /></label>
          {check("active", editing.fields.active, setEditField, "Habitación activa")}
          <p className="text-xs text-muted-foreground sm:col-span-2">Si tiene una asignación activa, no se puede cambiar su categoría ni desactivarla.</p>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-3"><Button disabled={busy}>Guardar habitación</Button><Button type="button" variant="outline" onClick={() => setEditing(null)}>Cancelar</Button></div>
        </form>}
      </CardContent></Card>}
      {(section === "rates" || section === "rates-new") && <Card><CardHeader><CardTitle>{section === "rates-new" ? "Nueva tarifa" : `Tarifas (${board.rates.length})`}</CardTitle><CardDescription>La tarifa conserva moneda y modalidad; Day Pass con habitación usa una tarifa marcada para ese uso.</CardDescription></CardHeader><CardContent className="space-y-4">
        {section === "rates-new" && <form onSubmit={(event) => { event.preventDefault(); void save("rate", { title: rateTitle.trim(), category: rateCategory, mode: rateMode, day_pass: rateDayPass ? 1 : 0, currency: rateCurrency, amount: Number(rateAmount), block_hours: Number(rateHours), priority: Number(ratePriority), active: 1 }, "Tarifa", () => { setRateTitle(""); setRateAmount(""); navigate("/setup?section=rates") }) }} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="space-y-1 text-sm"><span>Nombre</span><Input required value={rateTitle} onChange={(event) => setRateTitle(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Categoría</span><select required className={selectClass} value={rateCategory} onChange={(event) => setRateCategory(event.target.value)}><option value="">Seleccione</option>{board.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Modalidad</span><select className={selectClass} value={rateMode} onChange={(event) => { setRateMode(event.target.value); if (event.target.value !== "Por tiempo") setRateDayPass(false) }}><option value="Hotel">Por noche</option><option value="Por tiempo">Por tiempo</option></select></label>
          <label className="space-y-1 text-sm"><span>Moneda</span><select className={selectClass} value={rateCurrency} onChange={(event) => setRateCurrency(event.target.value)}>{board.currencies.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Precio</span><Input required type="number" min="0.01" step="0.01" value={rateAmount} onChange={(event) => setRateAmount(event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Horas por bloque</span><Input required type="number" min="0.5" step="0.5" value={rateHours} onChange={(event) => setRateHours(event.target.value)} disabled={rateMode !== "Por tiempo"} /></label>
          <label className="space-y-1 text-sm"><span>Prioridad</span><Input required type="number" value={ratePriority} onChange={(event) => setRatePriority(event.target.value)} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rateDayPass} disabled={rateMode !== "Por tiempo"} onChange={(event) => setRateDayPass(event.target.checked)} />Tarifa Day Pass</label>
          <Button disabled={busy || !board.categories.length} className="sm:col-span-2 lg:col-span-4">Crear tarifa</Button>
        </form>}
        {section === "rates" && <Button asChild variant="outline"><Link to="/setup?section=rates-new">Nueva tarifa</Link></Button>}
        {section === "rates" && !board.rates.length && <p className="text-sm text-muted-foreground">Todavía no hay tarifas registradas.</p>}
        {section === "rates" && <div className="space-y-2 text-sm">{board.rates.map((item) => <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"><span><strong>{item.title}</strong> · {board.categories.find((entry) => entry.name === item.category)?.category_name || item.category} · {item.mode}{item.day_pass ? " · Day Pass" : ""}{!item.active ? " · Inactiva" : ""}</span><span>{item.currency} {item.amount}</span>
          <Button type="button" variant="outline" size="sm" onClick={() => setEditing({
            section: "rate", name: item.name, modified: item.modified,
            fields: { title: item.title, category: item.category, mode: item.mode,
              day_pass: item.day_pass, currency: item.currency, amount: String(item.amount),
              block_hours: String(item.block_hours), priority: String(item.priority),
              active: item.active, change_reason: "" },
          })}>Editar</Button></div>)}</div>}
        {section === "rates" && editing?.section === "rate" && <form onSubmit={(event) => { event.preventDefault(); const fields = editing.fields;
          void save("rate", { name: editing.name, title: String(fields.title).trim(),
            category: fields.category, mode: fields.mode, day_pass: Number(fields.day_pass),
            currency: fields.currency, amount: Number(fields.amount),
            block_hours: Number(fields.block_hours), priority: Number(fields.priority),
            active: Number(fields.active), change_reason: String(fields.change_reason).trim() },
          "Tarifa", () => setEditing(null), editing.modified)
        }} className="grid gap-3 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <h3 className="font-medium sm:col-span-2 lg:col-span-4">Editar tarifa</h3>
          <label className="space-y-1 text-sm"><span>Nombre</span><Input required value={editing.fields.title} onChange={(event) => setEditField("title", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Categoría</span><select required className={selectClass} value={editing.fields.category} onChange={(event) => setEditField("category", event.target.value)}>{board.categories.map((item) => <option key={item.name} value={item.name}>{item.category_name}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Modalidad</span><select className={selectClass} value={editing.fields.mode} onChange={(event) => { setEditField("mode", event.target.value); if (event.target.value !== "Por tiempo") setEditField("day_pass", 0) }}><option value="Hotel">Por noche</option><option value="Por tiempo">Por tiempo</option></select></label>
          <label className="space-y-1 text-sm"><span>Moneda</span><select className={selectClass} value={editing.fields.currency} onChange={(event) => setEditField("currency", event.target.value)}>{board.currencies.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Precio</span><Input required type="number" min="0.01" step="0.01" value={editing.fields.amount} onChange={(event) => setEditField("amount", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Horas por bloque</span><Input required type="number" min="0.5" step="0.5" disabled={editing.fields.mode !== "Por tiempo"} value={editing.fields.block_hours} onChange={(event) => setEditField("block_hours", event.target.value)} /></label>
          <label className="space-y-1 text-sm"><span>Prioridad</span><Input required type="number" value={editing.fields.priority} onChange={(event) => setEditField("priority", event.target.value)} /></label>
          <div className="flex flex-wrap items-center gap-4"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(Number(editing.fields.day_pass))} disabled={editing.fields.mode !== "Por tiempo"} onChange={(event) => setEditField("day_pass", event.target.checked ? 1 : 0)} />Day Pass</label>{check("active", editing.fields.active, setEditField, "Tarifa activa")}</div>
          <label className="space-y-1 text-sm sm:col-span-2 lg:col-span-4"><span>Motivo del cambio</span><Input required maxLength={1000} value={editing.fields.change_reason} onChange={(event) => setEditField("change_reason", event.target.value)} /></label>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-4"><Button disabled={busy}>Guardar tarifa</Button><Button type="button" variant="outline" onClick={() => setEditing(null)}>Cancelar</Button></div>
        </form>}
      </CardContent></Card>}
    </>}
  </div>
}
