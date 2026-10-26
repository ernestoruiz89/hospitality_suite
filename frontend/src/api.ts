export type Property = {
  name: string
  property_name: string
  brand_name?: string | null
  mode: string
  currency: string
  business_date: string
  time_zone: string
}

export type Bootstrap = {
  user: string
  properties: Property[]
  can_create_property?: boolean
  can_manage_users?: boolean
  pages: { route: string; title: string; icon: string }[]
  actions: string[]
  accounting_provider: "pms" | "erpnext"
  petty_visible?: boolean
  accepted_currencies?: string[]
  server_time: string
  summary?: Record<string, unknown>
  shifts?: { name: string; status: string; current_expected?: Record<string, string> }[]
  bookings?: { name: string; status: string; starts_at: string }[]
  stays?: { name: string; status: string }[]
  cleaning?: { name: string; status: string }[]
}

export type LedgerAccount = {
  name: string
  account_code: string
  account_name: string
  root_type: string
  account_currency: string
  is_cash: boolean
  is_bank: boolean
  manual_enabled: boolean
}

export type ChartAccount = LedgerAccount & {
  modified: string
  account_number: string
  account_type: string
  account_currency: string
  parent_account: string | null
  is_group: boolean
  active: boolean
}

export type ChartData = { accounts: ChartAccount[]; account_types: string[]; currencies: string[] }
export type CurrencySettings = { base_currency: string; accepted_currencies: string[];
  available_currencies: string[]; rates: { name: string; from_currency: string; to_currency: string;
    rate: number; effective_at: string; source: string }[] }

export type Room = {
  name: string
  room_number: string
  category: string
  category_label: string
  floor?: string | null
  zone?: string | null
  active: boolean
  cleaning_status: string
  occupied: boolean
  blocked: boolean
  block_kind?: string | null
  arrival: boolean
  departure: boolean
  overdue_arrival: boolean
  overdue_departure: boolean
  work: boolean
  task_count: number
  maintenance_count: number
  ticket_count: number
  guest_label?: string | null
  arrival_label?: string | null
  stay_start?: string | null
  stay_end?: string | null
  arrival_start?: string | null
  arrival_end?: string | null
  stay?: string | null
  booking?: string | null
}

export type RoomBoard = {
  property: string
  time_zone: string
  checked_at: string
  rooms: Room[]
  counts: Record<"occupied" | "arrival" | "departure" | "work" | "blocked", number>
}

export type HomeQueueSummary = {
  property: string
  date: string
  time_zone: string
  server_time: string
  counts: Record<"arrivals" | "departures" | "hosted" | "accounts", number>
}

export type RoomDetail = {
  property: string
  room: Room
  checked_at: string
  time_zone: string
  mode: string
  can: Record<string, boolean>
  current?: {
    name?: string | null
    service_stay?: string | null
    guest_label?: string | null
    starts_at: string
    ends_at: string
    account_balances?: { currency: string; outstanding: number }[]
    accounts?: { name: string; label: string | null; shared: boolean;
      currency: string; pending: string; scheduled: string; outstanding: string }[]
    recent_charges?: { name: string; folio: string; description: string | null;
      amount: string; currency: string; status: string }[]
  } | null
  next_arrival?: {
    booking?: string | null
    guest_label?: string | null
    starts_at: string
    ends_at: string
  } | null
  tasks: { name: string; kind: string; status: string; priority: string }[]
  maintenance: { name: string; title: string; status: string }[]
  tickets: { name: string; subject: string; status: string }[]
  details: {
    beds?: number
    parking?: string | null
    capacity?: number
    amenities?: string | null
    description?: string | null
    image?: string | null
  }
}

type FrappeResponse<T> = { message?: T; exc_type?: string; exception?: string; _server_messages?: string }

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function call<T>(method: string, params: Record<string, string> = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams(params)
  const response = await fetch(`/api/method/hospitality_suite.api.${method}?${query}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  })
  const body = (await response.json().catch(() => ({}))) as FrappeResponse<T>
  if (!response.ok || body.exc_type) {
    throw new ApiError(response.status === 403 ? "No tiene permiso para consultar esta vista." :
      response.status === 401 ? "Inicie sesión para continuar." :
      "No se pudo obtener la información. Intente nuevamente.", response.status)
  }
  if (body.message === undefined) throw new ApiError("El servidor devolvió una respuesta incompleta.", response.status)
  return body.message
}

export async function postMethod<T>(method: string, data: object): Promise<T> {
  const csrf = (window as Window & { csrf_token?: string }).csrf_token
  const response = await fetch(`/api/method/hospitality_suite.api.${method}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Frappe-CSRF-Token": csrf || "" },
    body: JSON.stringify(data),
  })
  const body = (await response.json().catch(() => ({}))) as FrappeResponse<T>
  if (!response.ok || body.exc_type) {
    let message = "No se pudo completar la operación. Intente nuevamente."
    if (response.status === 403) message = "No tiene permiso para realizar esta operación."
    if (response.status === 401) message = "Inicie sesión para continuar."
    if (body._server_messages) {
      try {
        const entries = JSON.parse(body._server_messages) as string[]
        const last = JSON.parse(entries.at(-1) || "{}") as { message?: string }
        if (last.message) message = last.message.replace(/<[^>]*>/g, "")
      } catch { /* Keep the generic error. */ }
    }
    throw new ApiError(message, response.status)
  }
  if (body.message === undefined) throw new ApiError("El servidor devolvió una respuesta incompleta.", response.status)
  return body.message
}

export async function uploadPrivateEvidence(doctype: "HS Incident" | "HS Maintenance Order",
  docname: string, file: File): Promise<string> {
  const extension = file.name.toLowerCase().split(".").at(-1)
  if (file.size > 5 * 1024 * 1024 || file.size === 0 ||
      !(file.type.startsWith("image/") || extension === "pdf" || extension === "txt")) {
    throw new Error("Seleccione una imagen, PDF o TXT de hasta 5 MB.")
  }
  const form = new FormData()
  form.append("file", file)
  form.append("doctype", doctype)
  form.append("docname", docname)
  form.append("is_private", "1")
  const csrf = (window as Window & { csrf_token?: string }).csrf_token
  const response = await fetch("/api/method/upload_file", {
    method: "POST", credentials: "same-origin",
    headers: { "X-Frappe-CSRF-Token": csrf || "" }, body: form,
  })
  const body = (await response.json().catch(() => ({}))) as FrappeResponse<{ file_url: string }>
  if (!response.ok || body.exc_type || !body.message?.file_url?.startsWith("/private/files/")) {
    throw new ApiError(response.status === 403 ? "No tiene permiso para adjuntar evidencia a este registro." :
      "No se pudo adjuntar el archivo privado.", response.status)
  }
  return body.message.file_url
}

export async function execute<T>(property: string, action: string, data: object, requestKey: string): Promise<T> {
  return postMethod<T>("execute", { property_name: property, action, request_key: requestKey, data })
}
