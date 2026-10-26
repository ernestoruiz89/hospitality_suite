import { Component, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Link, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom"
import { Banknote, BarChart3, BedDouble, BookOpen, CalendarDays, CalendarCheck2, ChevronRight, ClipboardList, Coins, Compass, FileText, LayoutDashboard, FolderTree, HandCoins, HeartPulse, Landmark, LogIn, Menu, Package, ReceiptText, RefreshCw, Search, Settings2, ShieldCheck, Shirt, Sun, Tickets as TicketsIcon, UserRound, UsersRound, Wrench, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, type Bootstrap, type HomeQueueSummary, type Property, type Room, type RoomBoard, type RoomDetail } from "./api"
import { chartSections } from "./ChartSections"
import { erpCashSections, pmsCashSections } from "./CashSections"
import { availableReceivableSections } from "./ReceivableSections"
import { availableFolioSections } from "./FolioSections"
import { productSections } from "./ProductSections"
import { availableBillingSections } from "./BillingSections"
import { availableFiscalArchiveSections } from "./FiscalArchiveSections"
import { availableReceptionSections } from "./ReceptionSections"
import { RoomDetailSections } from "./RoomDetailSections"
import { RoomServiceAction } from "./RoomServiceAction"
import { RoomAccountActions } from "./RoomAccountActions"
import { reservationSections } from "./ReservationSections"
import { staySections } from "./StaySections"
import { creditSections } from "./CreditSections"
import { availableErpCreditSections } from "./ErpCreditSections"
import { serviceSections } from "./ServiceSections"
import { erpInventorySections, pmsInventorySections } from "./InventorySections"
import { erpPurchaseSections, purchaseSections } from "./PurchaseSections"
import { financingSections } from "./FinancingSections"
import { pettySections } from "./PettyCashSections"
import { dailyCloseSections } from "./DailyCloseSections"
import { availableRoomWorkSections } from "./RoomWorkSections"
import { availableDayPassSections } from "./DayPassSections"
import { availableLaundrySections } from "./LaundrySections"
import { availableTravelSections } from "./TravelSections"
import { availableCustomerCreditSections } from "./CustomerCreditSections"
import { availableDirectSaleSections } from "./DirectSaleSections"
import { ticketSections } from "./TicketSections"
import { availableSetupSections } from "./SetupSections"
import { erpReportSections, pmsReportSections } from "./ReportSections"
import {
  Journal, Chart, Cash, ErpCash, Receivables, Folios, Products, Billing, FiscalArchive,
  Reception, Availability, RateCalendar, RoomCalendar, Reservations, Stays, BookingDraft,
  Departure, Credit, ErpCredit, ErpInvoicing, ErpAdjustments, ErpDirectSales, Services, ErpServices, Inventory, ErpInventory, Purchases, ErpPurchases,
  Financing, ErpFinancing, DailyClose, ErpDailyClose, Reports, ErpReports, Portfolio, Health,
  PrivacyRetention, RoomOperations, DayPass, ErpDayPass, Laundry, TravelExperiences,
  ErpTravelExperiences, CustomerCredits, PropertyCurrencies, Tickets, Setup, UserManagement,
  Onboarding, PettyCash, MyUserSettings, NewUser,
} from "./LazyPages"

const PROPERTY_KEY = "hospitality-suite-property"
const USER_ACCESS_PROPERTY_KEY = "hospitality-suite-user-access-property"

class RouteLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  render() {
    if (this.state.failed) return <Card><CardHeader><CardTitle>No se pudo abrir esta pantalla</CardTitle>
      <CardDescription>Intente recargar la aplicación para obtener la versión actual.</CardDescription>
    </CardHeader><CardContent><Button onClick={() => window.location.reload()}>Recargar aplicación</Button></CardContent></Card>
    return this.props.children
  }
}

function useBootstrap() {
  const [base, setBase] = useState<Bootstrap | null>(null)
  const [property, setProperty] = useState<string>("")
  const [detail, setDetail] = useState<Bootstrap | null>(null)
  const [error, setError] = useState<string>("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    call<Bootstrap>("bootstrap", {}, controller.signal)
      .then((data) => {
        setBase(data)
        const saved = localStorage.getItem(PROPERTY_KEY)
        setProperty(data.properties.some((item) => item.name === saved) ? saved! : data.properties[0]?.name || "")
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!property) return
    const controller = new AbortController()
    setDetail(null)
    setError("")
    localStorage.setItem(PROPERTY_KEY, property)
    call<Bootstrap>("bootstrap", { property_name: property }, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property])

  return { base, detail, property, setProperty, error, loading }
}

function Shell({ children, properties, property, setProperty, provider, showJournal, showChart, showCurrencies, showCash, showErpCredits, showCashRefund, showPetty, pettyNavigation, showClose, showReports, reportLabel, showProducts, showReception, showStays, canManageGuests, showDeparture, showTravel, canCommission, showServices, showInventory, showInventoryApprove, showPurchases, showRoomWork, roomWorkActions, showLaundry, showTickets, showSetup, showHealth, showRetention, showUsers, showNewProperty }: {
  children: ReactNode
  properties: Property[]
  property: string
  setProperty: (value: string) => void
  provider: "pms" | "erpnext"
  showJournal: boolean
  showChart: boolean
  showCurrencies: boolean
  showCash: boolean
  showErpCredits: boolean
  showCashRefund: boolean
  showPetty: boolean
  pettyNavigation: { propertyName: string; sectionIds: string[]; defaultSection: string } | null
  showClose: boolean
  showReports: boolean
  reportLabel: string
  showProducts: boolean
  showReception: boolean
  showStays: boolean
  canManageGuests: boolean
  showDeparture: boolean
  showTravel: boolean
  canCommission: boolean
  showServices: boolean
  showInventory: boolean
  showInventoryApprove: boolean
  showPurchases: boolean
  showRoomWork: boolean
  roomWorkActions: string[]
  showLaundry: boolean
  showTickets: boolean
  showSetup: boolean
  showHealth: boolean
  showRetention: boolean
  showUsers: boolean
  showNewProperty: boolean
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const [expandedGroup, setExpandedGroup] = useState<{ moduleId: string; path: string;
    group: string | null } | null>(null)
  const selected = properties.find((item) => item.name === property)
  const financingNav = showCash || showErpCredits ? financingSections
    .filter((section) => section.id !== "concepts" || (showCash ? showChart : showSetup))
    .map((section) => ({ to: `/financing?section=${section.id}`, label: section.label,
      icon: Landmark, group: "Movimientos financieros" })) : []
  const cashNav = showCash || showErpCredits ? (showCash ? pmsCashSections
    .filter((section) => section.permission !== "refund" || showCashRefund)
    .filter((section) => section.permission !== "setup" || showChart) : erpCashSections
      .filter((section) => section.permission !== "setup" || showSetup))
    .map((section) => ({ to: `/cash?section=${section.id}`, label: section.label,
      icon: Banknote, group: section.permission === "setup" ? "Configuración de Caja" : "Caja" })) : []
  const customerCreditNav = showErpCredits ? availableCustomerCreditSections(showRetention)
    .map((section) => ({ to: `/customer-credits?section=${section.id}`, label: section.label,
      icon: HandCoins, group: section.id.includes("guarantee") ? "Garantías ERPNext" :
        (section.id.includes("advance") || section.id === "refund-applied") ? "Anticipos ERPNext" :
          (section.id === "credit-note" || section.id === "direct-refund") ? "Correcciones ERPNext" : "Cobros ERPNext" })) : []
  const directSaleNav = showErpCredits ? availableDirectSaleSections(showRetention)
    .map((section) => ({ to: `/direct-sales?section=${section.id}`, label: section.label,
      icon: ReceiptText, group: "Ventas directas" })) : []
  const purchaseNav = showPurchases ? (showCash ? purchaseSections
    .filter((section) => !section.requiresPurchase || showInventory)
    .filter((section) => !section.requiresApprove || showInventoryApprove) : erpPurchaseSections
      .filter((section) => section.permission === "purchase" ? showInventory : showCash || showErpCredits))
    .map((section) => ({ to: `/purchases?section=${section.id}`, label: section.label,
      icon: ReceiptText, group: !showCash ?
        ["suppliers", "supplier-new"].includes(section.id) ? "Proveedores" :
          ["orders", "order-new", "receive"].includes(section.id) ? "Órdenes y recepciones" : "Facturas y pagos" :
        ["suppliers", "supplier-new"].includes(section.id) ? "Proveedores" :
          ["orders", "order-new", "order-receive"].includes(section.id) ? "Órdenes de compra" :
            ["receive", "payables", "supplier-pay", "supplier-payments"].includes(section.id) ? "Facturas y pagos" :
              ["credits", "credit-apply", "credit-refund", "credit-unapply"].includes(section.id) ? "Créditos de proveedor" :
                "Devoluciones" })) : []
  const inventoryNav = showInventory ? (provider === "pms" ? pmsInventorySections : erpInventorySections)
    .filter((section) => section.permission !== "setup" || showSetup)
    .filter((section) => section.permission !== "approve" || showInventoryApprove)
    .map((section) => ({ to: `/inventory?section=${section.id}`, label: section.label,
      icon: Package })) : []
  const pettyNav = showPetty ? (pettyNavigation?.propertyName === property ? pettySections
    .filter((section) => pettyNavigation.sectionIds.includes(section.id))
    .map((section) => ({ to: `/petty-cash?section=${section.id}`, label: section.label,
      icon: HandCoins, group: "Caja Chica" })) :
    [{ to: "/petty-cash", label: "Abrir Caja Chica", icon: HandCoins, group: "Caja Chica" }]) : []
  const setupNav = showSetup ? availableSetupSections(provider)
    .map((section) => ({ to: `/setup?section=${section.id}`, label: section.label,
      icon: Settings2, group: section.group })) : []
  const reportNav = showReports ? (provider === "pms" ? pmsReportSections : erpReportSections)
    .map((section) => ({ to: `/reports?section=${section.id}`, label: section.label,
      icon: BarChart3, group: reportLabel })) : []
  const receptionNav = showReception ? availableReceptionSections(provider, showSetup,
    showStays, canManageGuests)
    .map((section) => ({ to: `/reception?section=${section.id}`, label: section.label,
      icon: CalendarDays, group: section.id === "guests" || section.id === "guest-new" ? "Huéspedes" :
        section.id === "stays" || section.id.startsWith("stay-") ? "Operar estancias" : "Recepción" })) : []
  const reservationNav = showReception ? reservationSections.map((section) => ({
    to: `/reservations?section=${section.id}`, label: section.label,
    icon: BookOpen, group: "Reservas",
  })) : []
  const stayNav = showStays ? staySections.map((section) => ({
    to: `/stays?section=${section.id}`, label: section.label,
    icon: BedDouble, group: "Estancias",
  })) : []
  const roomContext = location.pathname === "/room-work" ? new URLSearchParams(location.search).get("room") : null
  const ticketRoomContext = location.pathname === "/tickets" ? new URLSearchParams(location.search).get("room") : null
  const ticketNav = showTickets ? ticketSections.map((section) => ({
    to: `/tickets?section=${section.id}${section.id === "new" && ticketRoomContext ? `&room=${encodeURIComponent(ticketRoomContext)}` : ""}`,
    label: section.label, icon: TicketsIcon, group: "Tickets",
  })) : []
  const roomWorkNav = showRoomWork ? availableRoomWorkSections({
    clean: roomWorkActions.includes("clean"), inspect: roomWorkActions.includes("inspect"),
    maintain: roomWorkActions.includes("maintain"), block: roomWorkActions.includes("block"),
    incident: roomWorkActions.includes("incident"),
  }).map((section) => ({ to: `/room-work?section=${section.id}${roomContext ? `&room=${encodeURIComponent(roomContext)}` : ""}`,
    label: section.label, icon: Wrench, group: section.id.startsWith("cleaning") ? "Limpieza" :
      section.id.startsWith("linen") ? "Ropa del hotel" :
        section.id.startsWith("incidents") ? "Novedades" :
          section.id.startsWith("maintenance") ? "Mantenimiento" : "Bloqueos" })) : []
  const laundryNav = showLaundry ? availableLaundrySections(showSetup)
    .map((section) => ({ to: `/laundry?section=${section.id}`, label: section.label,
      icon: Shirt, group: "Lavandería" })) : []
  const travelNav = showTravel ? availableTravelSections({ provider, setup: showSetup,
    reserve: showReception, service: showServices, commission: canCommission, finance: showCash || showErpCredits,
    approve: showRetention }).map((section) => ({ to: `/travel-experiences?section=${section.id}`,
      label: section.label, icon: Compass, group: section.id.startsWith("orders") ||
        ["reserve", "direct"].includes(section.id) ? "Órdenes de experiencias" :
        section.id.startsWith("agenc") ? "Agencias" :
          section.id.startsWith("commission") ? "Comisiones de agencias" : "Catálogo de experiencias" })) : []
  const dayPassNav = showCash || showErpCredits ? availableDayPassSections(provider, showSetup, showRetention)
    .map((section) => ({ to: `/day-pass?section=${section.id}`, label: section.label,
      icon: Sun, group: "Day Pass sin habitación" })) : []
  const billingNav = showCash ? availableBillingSections(showSetup, showChart, showRetention)
    .map((section) => ({ to: `/billing?section=${section.id}`, label: section.label,
      icon: FileText, group: "Facturación PMS" })) : []
  const fiscalNav = showCash || showErpCredits ? availableFiscalArchiveSections(provider)
    .map((section) => ({ to: `/fiscal-archive?section=${section.id}`,
      label: section.label, icon: FileText, group: "Archivo fiscal" })) : []
  const folioContext = location.pathname === "/folios" ? new URLSearchParams(location.search).get("folio") : null
  const folioNav = showCash ? availableFolioSections(showRetention)
    .map((section) => ({ to: `/folios?section=${section.id}${folioContext ? `&folio=${encodeURIComponent(folioContext)}` : ""}`,
      label: section.label, icon: ReceiptText, group: "Cuentas de estancia" })) : []
  const receivableNav = showCash ? availableReceivableSections(showChart, showRetention)
    .map((section) => ({ to: `/receivables?section=${section.id}`, label: section.label,
      icon: HandCoins, group: section.group })) : []
  const creditContext = location.pathname === "/credit" ? new URLSearchParams(location.search) : null
  const creditNav = showCash ? creditSections.map((section) => ({
    to: `/credit?section=${section.id}${creditContext?.get("offset") ? `&offset=${encodeURIComponent(creditContext.get("offset") || "")}` : ""}${creditContext?.get("party") ? `&party=${encodeURIComponent(creditContext.get("party") || "")}` : ""}`,
    label: section.label, icon: BookOpen, group: "Crédito PMS",
  })) : []
  const erpCreditNav = showErpCredits ? availableErpCreditSections(showSetup).map((section) => ({
    to: `/erp-credit?section=${section.id}`, label: section.label,
    icon: HandCoins, group: "Crédito empresarial",
  })) : []
  const serviceNav = showServices ? serviceSections.map((section) => ({
    to: `/services?section=${section.id}`, label: section.label,
    icon: ClipboardList, group: "Servicios a huéspedes",
  })) : []
  const chartNav = showChart ? chartSections.map((section) => ({
    to: `/chart?section=${section.id}`, label: section.label,
    icon: FolderTree, group: section.group,
  })) : []
  const productNav = showProducts ? productSections.map((section) => ({
    to: `/products?section=${section.id}`, label: section.label,
    icon: Package, group: "Productos PMS",
  })) : []
  const closeContext = location.pathname === "/daily-close" ? new URLSearchParams(location.search).get("close") : null
  const dailyCloseNav = showClose ? dailyCloseSections.map((section) => ({
    to: `/daily-close?section=${section.id}${closeContext && section.id !== "review" ? `&close=${encodeURIComponent(closeContext)}` : ""}`,
    label: section.label, icon: CalendarCheck2, group: "Cierre diario",
  })) : []
  const nav = [
    { to: "/", label: "Inicio", icon: LayoutDashboard },
    { to: "/rooms", label: "Habitaciones", icon: BedDouble },
    ...roomWorkNav,
    ...ticketNav,
    ...receptionNav,
    ...reservationNav,
    ...stayNav,
    ...(showReception ? [{ to: "/availability", label: "Disponibilidad", icon: CalendarCheck2 }] : []),
    ...(showReception ? [{ to: "/rates", label: "Calendario de tarifas", icon: BarChart3 }] : []),
    ...(showReception ? [{ to: "/room-calendar", label: "Calendario de habitaciones", icon: CalendarDays }] : []),
    ...travelNav,
    ...dayPassNav,
    ...(showDeparture ? [{ to: "/departures", label: "Salidas", icon: ChevronRight }] : []),
    ...folioNav,
    ...billingNav,
    ...(showErpCredits ? [{ to: "/erp-invoicing", label: "Facturar cuenta", icon: FileText, group: "Facturación ERPNext" }] : []),
    ...fiscalNav,
    ...cashNav,
    ...pettyNav,
    ...dailyCloseNav,
    ...(showReports ? [{ to: "/portfolio", label: "Cartera de establecimientos", icon: LayoutDashboard }] : []),
    ...reportNav,
    ...receivableNav,
    ...customerCreditNav,
    ...(provider === "erpnext" && showRetention ? [{ to: "/erp-adjustments", label: "Ajustar cargos", icon: ReceiptText, group: "Correcciones ERPNext" }] : []),
    ...directSaleNav,
    ...creditNav,
    ...erpCreditNav,
    ...financingNav,
    ...(showJournal ? [{ to: "/journal", label: "Asiento contable", icon: BookOpen }] : []),
    ...chartNav,
    ...(showCurrencies ? [{ to: "/currencies", label: "Monedas del establecimiento", icon: Coins }] : []),
    ...productNav,
    ...serviceNav,
    ...laundryNav,
    ...inventoryNav,
    ...purchaseNav,
    ...setupNav,
    ...(showUsers ? [
      { to: "/users", label: "Directorio de usuarios", icon: UsersRound, group: "Administración de usuarios" },
      { to: "/users/new", label: "Nuevo usuario", icon: UserRound, group: "Administración de usuarios" },
      { to: "/users/assign", label: "Conceder acceso", icon: ShieldCheck, group: "Administración de usuarios" },
    ] : []),
    ...(showHealth ? [{ to: "/health", label: "Salud del sistema", icon: HeartPulse }] : []),
    ...(showRetention ? [{ to: "/retention", label: "Retención de datos", icon: ShieldCheck }] : []),
    ...(showNewProperty ? [{ to: "/new-property", label: "Nuevo establecimiento", icon: BedDouble }] : []),
  ]
  const moduleConfig = [
    { id: "home", label: "Inicio", icon: LayoutDashboard, routes: ["/"] },
    { id: "front-desk", label: "Recepción", icon: BedDouble, routes: ["/rooms", ...receptionNav.map((item) => item.to), ...reservationNav.map((item) => item.to), ...stayNav.map((item) => item.to), "/availability", "/room-calendar", ...dayPassNav.map((item) => item.to), "/departures"] },
    { id: "operations", label: "Operaciones", icon: Wrench, routes: [...roomWorkNav.map((item) => item.to), ...ticketNav.map((item) => item.to), ...serviceNav.map((item) => item.to), ...laundryNav.map((item) => item.to), ...productNav.map((item) => item.to)] },
    { id: "inventory", label: "Inventario", icon: Package, routes: inventoryNav.map((item) => item.to) },
    { id: "purchasing", label: "Compras", icon: ReceiptText, routes: purchaseNav.map((item) => item.to) },
    { id: "commercial", label: "Comercial", icon: Compass, routes: ["/rates", ...travelNav.map((item) => item.to)] },
    { id: "finance", label: "Finanzas", icon: Banknote, routes: [...folioNav.map((item) => item.to), ...billingNav.map((item) => item.to), "/erp-invoicing", "/erp-adjustments", ...directSaleNav.map((item) => item.to), ...fiscalNav.map((item) => item.to), ...cashNav.map((item) => item.to), ...pettyNav.map((item) => item.to), ...dailyCloseNav.map((item) => item.to), ...receivableNav.map((item) => item.to), ...customerCreditNav.map((item) => item.to), ...creditNav.map((item) => item.to), ...erpCreditNav.map((item) => item.to), ...financingNav.map((item) => item.to)] },
    { id: "accounting", label: "Contabilidad", icon: BookOpen, routes: ["/journal", ...chartNav.map((item) => item.to), "/currencies"] },
    { id: "management", label: "Gerencia", icon: BarChart3, routes: ["/portfolio", ...reportNav.map((item) => item.to)] },
    { id: "admin", label: "Administración", icon: Settings2, routes: [...setupNav.map((item) => item.to), "/health", "/retention", "/new-property"] },
    { id: "users", label: "Usuarios", icon: UsersRound, routes: ["/users", "/users/new", "/users/assign"] },
  ]
  const assigned = new Set(moduleConfig.flatMap((module) => module.routes))
  const unassigned = nav.filter((item) => !assigned.has(item.to))
  const modules = moduleConfig.map((module) => ({ ...module, items: nav.filter((item) => module.routes.includes(item.to)) }))
    .filter((module) => module.items.length)
  if (unassigned.length) modules.push({ id: "more", label: "Más", icon: Menu, routes: unassigned.map((item) => item.to), items: unassigned })
  const navGroup = (item: typeof nav[number]): string | undefined =>
    "group" in item && typeof item.group === "string" ? item.group : undefined
  const defaultPurchaseRoute = purchaseNav.find((item) => item.to.endsWith("section=orders"))?.to ||
    purchaseNav[0]?.to
  const matchesRoute = (route: string) => {
    const [path, search] = route.split("?")
    if (path === "/users" || path === "/users/new" || path === "/users/assign")
      return location.pathname === path
    if (path === "/reservations" && search && location.pathname.startsWith("/reservations/draft/"))
      return new URLSearchParams(search).get("section") === "draft"
    if (path === "/tickets" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      const selected = current.get("section") || (current.has("room") ? "new" : "board")
      return location.pathname === path && expected.get("section") === selected
    }
    if (path === "/room-work" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      const selectedSection = expected.get("section") === current.get("section") &&
        expected.get("room") === current.get("room")
      const defaultSection = !current.has("section") && route === roomWorkNav[0]?.to
      return location.pathname === path && (selectedSection || defaultSection)
    }
    if (path === "/folios" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      const selectedSection = expected.get("section") === current.get("section") &&
        expected.get("folio") === current.get("folio")
      const defaultSection = !current.has("section") && route === folioNav[0]?.to
      return location.pathname === path && (selectedSection || defaultSection)
    }
    if (path === "/credit" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      return location.pathname === path && (expected.get("section") === current.get("section") ||
        !current.has("section") && route === creditNav[0]?.to)
    }
    if (path === "/daily-close" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      return location.pathname === path && (expected.get("section") === current.get("section") ||
        !current.has("section") && route === dailyCloseNav[0]?.to)
    }
    if (path === "/reports" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      return location.pathname === path && expected.get("section") ===
        (current.get("section") || new URLSearchParams(reportNav[0]?.to.split("?")[1] || "").get("section"))
    }
    if (path === "/travel-experiences" && search) {
      const expected = new URLSearchParams(search)
      const current = new URLSearchParams(location.search)
      return location.pathname === path && (expected.get("section") === current.get("section") ||
        !current.has("section") && route === travelNav[0]?.to)
    }
    if (search) return location.pathname === path && (
      (new URLSearchParams(search).has("section") &&
        new URLSearchParams(search).get("section") === new URLSearchParams(location.search).get("section")) ||
      location.search === `?${search}` ||
      !location.search && (route === financingNav[0]?.to || route === cashNav[0]?.to ||
        route === defaultPurchaseRoute || route === inventoryNav[0]?.to || route === setupNav[0]?.to ||
        route === receptionNav[0]?.to || route === laundryNav[0]?.to || route === travelNav[0]?.to ||
        route === dayPassNav[0]?.to || route === customerCreditNav[0]?.to || route === billingNav[0]?.to ||
        route === directSaleNav[0]?.to ||
        route === fiscalNav[0]?.to || route === productNav[0]?.to ||
        route === reservationNav[0]?.to || route === stayNav[0]?.to ||
        route === receivableNav[0]?.to || route === serviceNav[0]?.to || route === chartNav[0]?.to ||
        route === `/petty-cash?section=${pettyNavigation?.defaultSection}` ||
        route === erpCreditNav[0]?.to ||
        route === reportNav[0]?.to))
    return path === "/" ? location.pathname === "/" : location.pathname === path || location.pathname.startsWith(path + "/")
  }
  const activeModule = modules.find((module) => module.items.some((item) => matchesRoute(item.to)))?.id || modules[0]?.id
  const shownModule = modules.find((module) => module.id === activeModule) || modules[0]
  const menuBlocks: { key: string; group?: string; items: typeof nav }[] = []
  for (const item of shownModule?.items || []) {
    const group = navGroup(item)
    const previous = menuBlocks[menuBlocks.length - 1]
    if (group && previous?.group === group) previous.items.push(item)
    else menuBlocks.push({ key: group ? `${shownModule.id}:${group}` : item.to, group, items: [item] })
  }
  const activeGroup = menuBlocks.find((block) => block.group &&
    block.items.some((item) => matchesRoute(item.to)))?.group || null
  const visibleGroup = expandedGroup?.moduleId === shownModule?.id &&
    expandedGroup.path === location.pathname ? expandedGroup.group : activeGroup
  const menuLink = (item: typeof nav[number]) =>
    <Link key={item.to} to={item.to} aria-current={matchesRoute(item.to) ? "page" : undefined}
      onClick={() => { setMenuOpen(false); setExpandedGroup(null) }}
      className={`flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium ${matchesRoute(item.to) ? "bg-secondary text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
      <item.icon size={17} className="shrink-0" aria-hidden="true" /><span>{item.label}</span>
    </Link>
  return <div className="min-h-screen lg:flex">
    {menuOpen && <button className="fixed inset-0 z-30 bg-black/35 lg:hidden" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)} />}
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-80 border-r border-border bg-white shadow-xl transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:shadow-none ${menuOpen ? "translate-x-0" : "-translate-x-full"}`} aria-label="Navegación de Hospitality">
      <div className="flex w-24 shrink-0 flex-col items-center gap-5 overflow-x-hidden overflow-y-auto bg-primary px-1.5 py-5 text-primary-foreground">
        <Link to="/" className="flex size-11 items-center justify-center rounded-xl border border-white/30" aria-label="Inicio" onClick={() => setMenuOpen(false)}><BedDouble size={22} /></Link>
        <nav className="flex w-full flex-col gap-1" aria-label="Módulos">
          {modules.map(({ id, label, icon: Icon, items }) => <Link key={id} to={items[0].to} aria-label={label} aria-current={shownModule?.id === id ? "page" : undefined} onClick={() => { setMenuOpen(false); setExpandedGroup(null) }}
            className={`flex min-h-14 w-full flex-col items-center justify-center gap-1 rounded-lg px-1 py-1 text-center text-[10px] font-semibold leading-tight ${shownModule?.id === id ? "bg-secondary text-primary" : "text-white/85 hover:bg-white/15 hover:text-white"}`}>
            <Icon size={19} aria-hidden="true" /><span className="max-w-full">{label}</span>
          </Link>)}
        </nav>
        <Link to="/profile" aria-label="Configuración de usuario" title="Configuración de usuario"
          onClick={() => setMenuOpen(false)}
          className="mt-auto flex min-h-14 w-full shrink-0 flex-col items-center justify-center gap-1 rounded-lg border-t border-white/25 px-1 py-2 text-center text-[10px] font-semibold leading-tight text-white/85 hover:bg-white/15 hover:text-white">
          <UserRound size={19} aria-hidden="true" /><span>Mi usuario</span>
        </Link>
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto p-4">
        <div className="mb-6 flex items-start justify-between gap-2">
          <div><strong className="block text-base leading-tight">Hospitality</strong><span className="text-[10px] font-semibold tracking-[0.2em] text-muted-foreground">MÓDULOS</span></div>
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)}><X /></Button>
        </div>
        <h2 className="px-2 text-sm font-semibold">{shownModule?.label}</h2>
        <nav className="mt-3 space-y-1" aria-label={`Menú de ${shownModule?.label || "Hospitality"}`}>
          {menuBlocks.map((block) => block.group ? <div key={block.key}>
            <button type="button" aria-expanded={visibleGroup === block.group}
              onClick={() => setExpandedGroup({ moduleId: shownModule.id, path: location.pathname,
                group: visibleGroup === block.group ? null : block.group || null })}
              className="flex w-full items-center justify-between gap-2 rounded-lg px-2 pb-1 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-primary">
              <span className="min-w-0 flex-1 break-words">{block.group}</span><ChevronRight size={15} className={`shrink-0 transition-transform ${visibleGroup === block.group ? "rotate-90" : ""}`} aria-hidden="true" />
            </button>
            {visibleGroup === block.group && <div className="space-y-1">{block.items.map(menuLink)}</div>}
          </div> : block.items.map(menuLink))}
        </nav>
        <div className="mt-auto rounded-xl border border-border bg-background p-3">
          <p className="text-xs text-muted-foreground">Establecimiento activo</p>
          <p className="mt-1 text-sm font-semibold">{selected?.brand_name || selected?.property_name || "Seleccione uno"}</p>
          <p className="mt-1 text-xs text-muted-foreground">{selected?.mode}</p>
        </div>
      </div>
    </aside>
    <div className="min-w-0 flex-1">
      <header className="sticky top-0 z-20 flex min-h-18 items-center gap-3 border-b border-border bg-white/95 px-4 backdrop-blur lg:px-8">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Abrir menú" onClick={() => setMenuOpen(true)}><Menu /></Button>
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{selected?.brand_name || selected?.property_name || "Hospitality Suite"}</p><p className="text-xs text-muted-foreground">Operación del establecimiento</p></div>
        <label className="sr-only" htmlFor="property-picker">Establecimiento</label>
        <select id="property-picker" className="max-w-48 rounded-md border border-border bg-white px-3 py-2 text-sm" value={property} onChange={(event) => setProperty(event.target.value)}>
          {properties.map((item) => <option key={item.name} value={item.name}>{item.brand_name || item.property_name}</option>)}
        </select>
        <Button asChild variant="outline" title="Configuración de usuario"><Link to="/profile" aria-label="Abrir configuración de usuario"><UserRound size={18} /><span className="hidden sm:inline">Mi usuario</span></Link></Button>
      </header>
      <main className="mx-auto max-w-7xl p-4 lg:p-8">{children}</main>
    </div>
  </div>
}

function StatCard({ label, value, hint, icon: Icon }: { label: string; value: number | string; hint: string; icon: typeof BedDouble }) {
  return <Card className="gap-3"><CardHeader className="flex flex-row items-center justify-between"><CardDescription>{label}</CardDescription><Icon size={18} className="text-primary" /></CardHeader><CardContent><p className="text-3xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-xs text-muted-foreground">{hint}</p></CardContent></Card>
}

function Dashboard({ property, data, actions, provider }: { property: Property; data: Bootstrap | null;
  actions: string[]; provider: "pms" | "erpnext" }) {
  const [board, setBoard] = useState<RoomBoard | null>(null)
  const [error, setError] = useState("")
  const [queues, setQueues] = useState<HomeQueueSummary | null>(null)
  const [queueError, setQueueError] = useState("")
  const [queueRevision, setQueueRevision] = useState(0)
  const canSeeQueues = ["stay", "finance", "report"].some((action) => actions.includes(action))
  useEffect(() => {
    const controller = new AbortController()
    setBoard(null)
    setError("")
    call<RoomBoard>("room_board_snapshot", { property_name: property.name }, controller.signal)
      .then(setBoard)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property.name])
  useEffect(() => {
    if (!canSeeQueues) return
    const controller = new AbortController()
    setQueues(null)
    setQueueError("")
    call<HomeQueueSummary>("home_queue_summary", { property_name: property.name }, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted && result.property === property.name) setQueues(result)
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setQueueError(reason instanceof Error ? reason.message : "No se pudieron consultar las colas.") })
    return () => controller.abort()
  }, [property.name, canSeeQueues, queueRevision])
  useEffect(() => {
    if (!canSeeQueues) return
    const timer = window.setInterval(() => setQueueRevision((value) => value + 1), 60000)
    return () => window.clearInterval(timer)
  }, [property.name, canSeeQueues])
  const occupancy = { occupied: 0, ready: 0, prepare: 0, blocked: 0, inactive: 0 }
  for (const room of board?.rooms || []) {
    if (!room.active) occupancy.inactive++
    else if (room.blocked) occupancy.blocked++
    else if (room.occupied) occupancy.occupied++
    else if (room.cleaning_status === "Clean") occupancy.ready++
    else occupancy.prepare++
  }
  const operable = occupancy.occupied + occupancy.ready + occupancy.prepare
  const occupancySegments = [
    { label: "Ocupadas", count: occupancy.occupied, color: "bg-blue-500" },
    { label: "Listas", count: occupancy.ready, color: "bg-emerald-500" },
    { label: "Por preparar", count: occupancy.prepare, color: "bg-amber-400" },
    { label: "Bloqueadas", count: occupancy.blocked, color: "bg-slate-500" },
    { label: "Inactivas", count: occupancy.inactive, color: "bg-slate-200" },
  ]
  const queueCards = [
    { key: "arrivals", label: "Llegadas pendientes", to: actions.includes("reserve") ? "/reception?section=arrivals" : null },
    { key: "departures", label: "Salidas pendientes", to: actions.includes("stay") ? "/departures" : null },
    { key: "hosted", label: "Alojados ahora", to: actions.includes("stay") ? "/stays?section=active" : null },
    { key: "accounts", label: "Cuentas abiertas", to: actions.includes("finance") ?
      provider === "pms" ? "/folios?section=accounts" : "/erp-invoicing" : null },
  ] as const
  return <div className="space-y-7">
    <div><p className="text-sm font-medium text-primary">{property.business_date}</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Panel del establecimiento</h1><p className="mt-2 text-muted-foreground">Situación operativa de {property.brand_name || property.property_name}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {board ? <>
        <StatCard label="Habitaciones ocupadas" value={occupancy.occupied} hint={`de ${operable} operativas`} icon={BedDouble} />
        <StatCard label="Llegadas" value={board.counts.arrival} hint="Con habitación asignada" icon={CalendarDays} />
        <StatCard label="Salidas" value={board.counts.departure} hint="Previstas para hoy" icon={ChevronRight} />
        <StatCard label="Trabajo pendiente" value={board.counts.work} hint="Habitaciones con tareas" icon={ClipboardList} />
      </> : Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-33 rounded-xl" />)}
    </div>
    <Card><CardHeader className="flex flex-row items-start justify-between gap-4"><div><CardTitle>Ocupación actual</CardTitle><CardDescription className="mt-1">{occupancy.occupied} de {operable} habitaciones operativas ocupadas</CardDescription></div>
      <strong className="text-2xl tabular-nums">{operable ? Math.round(occupancy.occupied / operable * 100) : 0}%</strong></CardHeader>
      <CardContent className="space-y-4">
        {board ? <><div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Distribución de ${board.rooms.length} habitaciones`}>
          {occupancySegments.map((segment) => segment.count > 0 && <span key={segment.label} className={segment.color} style={{ width: `${segment.count / board.rooms.length * 100}%` }} />)}
        </div><div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">{occupancySegments.map((segment) => <span key={segment.label} className="flex items-center gap-2"><i className={`size-2.5 rounded-full ${segment.color}`} aria-hidden="true" />{segment.label} <strong>{segment.count}</strong></span>)}</div>
          <p className="text-xs text-muted-foreground">La ocupación usa habitaciones activas sin bloqueo. Confirme la disponibilidad para el intervalo antes de asignar.</p></> : <Skeleton className="h-16" />}
      </CardContent></Card>
    {canSeeQueues && <Card><CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3"><div><CardTitle>Operación de hoy</CardTitle><CardDescription className="mt-1">{queues ? `Pendientes hasta ${queues.date} · ${queues.time_zone}` : "Llegadas, salidas, estancias y cuentas abiertas."}</CardDescription></div>
      <Button variant="outline" size="sm" onClick={() => setQueueRevision((value) => value + 1)}><RefreshCw size={16} />Actualizar</Button></CardHeader><CardContent className="space-y-4">
        {queueError && <p role="alert" className="text-sm text-destructive">{queueError}</p>}
        {queues ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{queueCards.map(({ key, label, to }) => {
          const content = <><span className="text-sm text-muted-foreground">{label}</span><strong className="text-3xl tabular-nums">{queues.counts[key]}</strong>{to && <span className="text-xs font-medium text-primary">Abrir vista →</span>}</>
          return to ? <Link key={key} to={to} className="flex flex-col gap-2 rounded-lg border border-border p-4 hover:bg-muted">{content}</Link> :
            <div key={key} className="flex flex-col gap-2 rounded-lg border border-border p-4">{content}</div>
        })}</div> : !queueError && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{queueCards.map(({ key }) => <Skeleton key={key} className="h-26 rounded-lg" />)}</div>}
        <p className="text-xs text-muted-foreground">Llegadas y salidas incluyen pendientes anteriores. Las cuentas compartidas se cuentan una vez.</p>
      </CardContent></Card>}
    <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card><CardHeader><CardTitle>Atención inmediata</CardTitle><CardDescription>Habitaciones con llegada, salida o trabajo pendiente.</CardDescription></CardHeader><CardContent className="space-y-2">
        {board?.rooms.filter((room) => room.arrival || room.departure || room.work).slice(0, 8).map((room) => <Link key={room.name} to={`/rooms/${encodeURIComponent(room.name)}`} className="flex items-center justify-between rounded-lg border border-border p-3 hover:bg-muted"><div><strong>Habitación {room.room_number}</strong><p className="text-sm text-muted-foreground">{room.category_label}</p></div><div className="flex gap-1">{room.arrival && <Badge>Entrada</Badge>}{room.departure && <Badge variant="secondary">Salida</Badge>}{room.work && <Badge variant="outline">Trabajo</Badge>}</div></Link>)}
        {board && !board.rooms.some((room) => room.arrival || room.departure || room.work) && <p className="py-8 text-center text-sm text-muted-foreground">No hay habitaciones que requieran atención inmediata.</p>}
        {!board && <Skeleton className="h-20" />}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Fecha operativa</CardTitle><CardDescription>Información del establecimiento seleccionado.</CardDescription></CardHeader><CardContent className="space-y-3 text-sm">
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Fecha</span><strong>{property.business_date}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Modalidad</span><strong>{property.mode}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Moneda</span><strong>{property.currency}</strong></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Zona horaria</span><strong>{property.time_zone}</strong></div>
        {data?.shifts && <div className="flex justify-between gap-3"><span className="text-muted-foreground">Turnos abiertos</span><strong>{data.shifts.filter((shift) => shift.status === "Open").length}</strong></div>}
        <Button asChild className="mt-3 w-full"><Link to="/rooms">Ver habitaciones <ChevronRight /></Link></Button>
      </CardContent></Card>
    </div>
  </div>
}

function status(room: Room) {
  if (!room.active) return { text: "Inactiva", tone: "bg-slate-100 text-slate-700" }
  if (room.blocked) return { text: "Bloqueada", tone: "bg-amber-100 text-amber-800" }
  if (room.occupied) return { text: "Ocupada", tone: "bg-blue-100 text-blue-800" }
  if (room.arrival) return { text: "Llegada", tone: "bg-violet-100 text-violet-800" }
  return { text: "Disponible", tone: "bg-emerald-100 text-emerald-800" }
}

type RoomFilters = { query: string; floor: string; category: string;
  state: string; clean: string; operational: string }
const emptyRoomFilters = (): RoomFilters => ({ query: "", floor: "", category: "",
  state: "", clean: "", operational: "all" })
const roomFilterKey = (user: string, property: string) =>
  `hospitality-suite-room-filters-v1:${JSON.stringify([user, property])}`
const normalizeRoomSearch = (value: string) => value.normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es").trim()

function readRoomFilters(key: string): RoomFilters {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || "null")
    if (!value || typeof value !== "object" || Array.isArray(value)) return emptyRoomFilters()
    const fields = value as Record<string, unknown>
    const field = (name: string) => typeof fields[name] === "string" ?
      (fields[name] as string).slice(0, 120) : ""
    const state = field("state")
    const operational = field("operational")
    return { query: field("query"), floor: field("floor"), category: field("category"),
      clean: field("clean"), state: ["vacant", "occupied", "blocked", "inactive"].includes(state) ? state : "",
      operational: ["all", "arrival", "departure", "work"].includes(operational) ? operational : "all" }
  } catch { return emptyRoomFilters() }
}

function RoomList({ property, user }: { property: Property; user: string }) {
  const [board, setBoard] = useState<RoomBoard | null>(null)
  const storageKey = roomFilterKey(user, property.name)
  const [filters, setFilters] = useState<RoomFilters>(() => readRoomFilters(storageKey))
  const [filtersOpen, setFiltersOpen] = useState(() => {
    const saved = readRoomFilters(storageKey)
    return Boolean(saved.floor || saved.category || saved.state || saved.clean)
  })
  const searchRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState("")
  const refresh = useCallback((signal?: AbortSignal) => {
    setError("")
    call<RoomBoard>("room_board_snapshot", { property_name: property.name }, signal)
      .then((result) => { if (result.property === property.name) setBoard(result) })
      .catch((reason: unknown) => { if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
  }, [property.name])
  useEffect(() => { const controller = new AbortController(); setBoard(null); refresh(controller.signal); return () => controller.abort() }, [refresh])
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(filters)) } catch { /* In-memory filters still work. */ } }, [storageKey, filters])
  const floors = useMemo(() => [...new Set((board?.rooms || []).map((room) => room.floor || "").filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "es", { numeric: true })), [board])
  const categories = useMemo(() => [...new Map((board?.rooms || []).map((room) => [room.category, room.category_label])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], "es")), [board])
  const cleanStates = useMemo(() => [...new Set((board?.rooms || []).map((room) => room.cleaning_status))].sort(), [board])
  useEffect(() => {
    if (!board) return
    setFilters((current) => {
      const next = { ...current, floor: floors.includes(current.floor) ? current.floor : "",
        category: categories.some(([name]) => name === current.category) ? current.category : "",
        clean: cleanStates.includes(current.clean) ? current.clean : "" }
      return next.floor === current.floor && next.category === current.category && next.clean === current.clean ? current : next
    })
  }, [board, floors, categories, cleanStates])
  const filtered = useMemo(() => (board?.rooms || []).filter((room) => {
    const text = `${room.room_number} ${room.category_label} ${room.floor || ""} ${room.zone || ""}`
    const state = !room.active ? "inactive" : room.blocked ? "blocked" : room.occupied ? "occupied" : "vacant"
    return (!filters.query || normalizeRoomSearch(text).includes(normalizeRoomSearch(filters.query))) &&
      (!filters.floor || room.floor === filters.floor) &&
      (!filters.category || room.category === filters.category) &&
      (!filters.state || state === filters.state) &&
      (!filters.clean || room.cleaning_status === filters.clean) &&
      (filters.operational === "all" || Boolean(room[filters.operational as "arrival" | "departure" | "work"]))
  }), [board, filters])
  const activeFilterCount = [filters.floor, filters.category, filters.state, filters.clean].filter(Boolean).length
  const clearFilters = () => { setFilters(emptyRoomFilters()); searchRef.current?.focus() }
  const quickFilters = [
    { id: "all", label: "Todas", count: board?.rooms.length },
    { id: "arrival", label: "Llegan", count: board?.counts.arrival },
    { id: "departure", label: "Salen", count: board?.counts.departure },
    { id: "work", label: "Trabajo pendiente", count: board?.counts.work },
  ]
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-3xl font-semibold tracking-tight">Habitaciones</h1><p className="mt-2 text-sm text-muted-foreground">Estado actual, llegadas y tareas por habitación.</p></div><Button variant="outline" onClick={() => refresh()}><RefreshCw size={16} /> Actualizar</Button></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <div className="relative max-w-sm"><Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input ref={searchRef} aria-label="Buscar habitación" maxLength={120} value={filters.query} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="Buscar número, categoría, piso o zona" className="pl-9" /></div>
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtros operativos">{quickFilters.map(({ id, label, count }) => <Button key={id} type="button" size="sm" variant={filters.operational === id ? "default" : "outline"}
        aria-pressed={filters.operational === id} disabled={!board} onClick={() => setFilters((current) => ({ ...current, operational: id }))}>{label} {count ?? "—"}</Button>)}</div>
      <details open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)} className="rounded-xl border border-border bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold">Filtros de habitaciones · {activeFilterCount || "Todos"}</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-sm"><span>Piso</span><select aria-label="Piso" className="h-9 w-full rounded-md border border-border bg-white px-2" value={filters.floor} onChange={(event) => setFilters((current) => ({ ...current, floor: event.target.value }))}><option value="">Todos los pisos</option>{floors.map((floor) => <option key={floor} value={floor}>{floor}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Categoría</span><select aria-label="Categoría" className="h-9 w-full rounded-md border border-border bg-white px-2" value={filters.category} onChange={(event) => setFilters((current) => ({ ...current, category: event.target.value }))}><option value="">Todas las categorías</option>{categories.map(([name, label]) => <option key={name} value={name}>{label}</option>)}</select></label>
          <label className="space-y-1 text-sm"><span>Estado de la habitación</span><select aria-label="Estado de la habitación" className="h-9 w-full rounded-md border border-border bg-white px-2" value={filters.state} onChange={(event) => setFilters((current) => ({ ...current, state: event.target.value }))}><option value="">Cualquier estado</option><option value="vacant">Sin ocupación</option><option value="occupied">Ocupada</option><option value="blocked">Bloqueada</option><option value="inactive">Inactiva</option></select></label>
          <label className="space-y-1 text-sm"><span>Limpieza</span><select aria-label="Limpieza" className="h-9 w-full rounded-md border border-border bg-white px-2" value={filters.clean} onChange={(event) => setFilters((current) => ({ ...current, clean: event.target.value }))}><option value="">Cualquier estado</option>{cleanStates.map((clean) => <option key={clean} value={clean}>{({ Clean: "Limpia", Dirty: "Sucia", Cleaning: "En limpieza", Inspection: "Pendiente de inspección" } as Record<string, string>)[clean] || clean}</option>)}</select></label>
        </div>
      </details>
      {board && <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-sm text-muted-foreground">Mostrando {filtered.length} de {board.rooms.length} habitaciones</p><Button type="button" variant="ghost" size="sm" onClick={clearFilters}>Restablecer filtros</Button></div>}
    </div>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {!board && Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-43 rounded-xl" />)}
      {filtered.map((room) => { const state = status(room); return <Link to={`/rooms/${encodeURIComponent(room.name)}`} key={room.name} className="group"><Card className="h-full gap-4 transition-shadow hover:shadow-md"><CardHeader><div className="flex items-start justify-between gap-3"><div><CardTitle className="text-xl">{room.room_number}</CardTitle><CardDescription>{room.category_label}{room.floor ? ` · Piso ${room.floor}` : ""}</CardDescription></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${state.tone}`}>{state.text}</span></div></CardHeader><CardContent><p className="min-h-5 truncate text-sm text-muted-foreground">{room.guest_label || room.arrival_label || "Sin huésped activo"}</p><div className="mt-4 flex flex-wrap gap-1.5">{room.cleaning_status !== "Clean" && <Badge variant="outline">Limpieza: {room.cleaning_status}</Badge>}{room.work && <Badge variant="secondary">{room.task_count + room.maintenance_count + room.ticket_count} tareas</Badge>}{room.departure && <Badge variant="outline">Salida</Badge>}</div></CardContent></Card></Link> })}
    </div>
    {board && filtered.length === 0 && <div className="rounded-xl border border-dashed border-border p-10 text-center"><p className="text-sm text-muted-foreground">No hay habitaciones que coincidan con los filtros.</p><Button type="button" variant="outline" className="mt-4" onClick={clearFilters}>Mostrar todas las habitaciones</Button></div>}
    {board && <p className="text-xs text-muted-foreground">Actualizado: {new Date(board.checked_at).toLocaleString("es-NI")}</p>}
  </div>
}

function RoomView({ property, provider, canFinance }: { property: Property;
  provider: "pms" | "erpnext"; canFinance: boolean }) {
  const { room } = useParams()
  const [data, setData] = useState<RoomDetail | null>(null)
  const [error, setError] = useState("")
  const refreshRoom = useCallback(async () => {
    if (room) setData(await call<RoomDetail>("room_snapshot", { property_name: property.name, room }))
  }, [property.name, room])
  useEffect(() => {
    if (!room) return
    const controller = new AbortController()
    setData(null)
    setError("")
    call<RoomDetail>("room_snapshot", { property_name: property.name, room }, controller.signal)
      .then(setData)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Error de conexión") })
    return () => controller.abort()
  }, [property.name, room])
  if (error) return <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>
  if (!data) return <Skeleton className="h-80 rounded-xl" />
  const state = status(data.room)
  return <div className="space-y-6">
    <Link to="/rooms" className="text-sm font-medium text-primary hover:underline">← Habitaciones</Link>
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm text-muted-foreground">{data.room.category_label}</p><h1 className="text-3xl font-semibold">Habitación {data.room.room_number}</h1></div><div className="flex items-center gap-2"><span className={`rounded-full px-3 py-1.5 text-sm font-semibold ${state.tone}`}>{state.text}</span>{(data.can.clean || data.can.maintain || data.can.block) && <Button asChild variant="outline"><Link to={`/room-work?room=${encodeURIComponent(data.room.name)}`}>Gestionar trabajo</Link></Button>}</div></div>
    {data.can.service && data.current?.service_stay && <RoomServiceAction key={`${property.name}:${data.current.service_stay}`}
      property={property} stay={data.current.service_stay} provider={provider} roomNumber={data.room.room_number}
      onAccountChanged={refreshRoom} />}
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Estancia actual</CardTitle></CardHeader><CardContent>
        {data.current ? <div className="space-y-2 text-sm">
          <p className="font-semibold">{data.current.guest_label || "Huésped registrado"}</p>
          <p>Entrada: {data.current.starts_at.slice(0, 16).replace("T", " ")}</p>
          <p>Salida: {data.current.ends_at.slice(0, 16).replace("T", " ")}</p>
          {data.current.account_balances?.map((balance) => <p key={balance.currency}>Saldo: {Number(balance.outstanding).toLocaleString("es-NI", { style: "currency", currency: balance.currency })}</p>)}
          {data.can.stay && data.current.name && <div className="flex flex-wrap gap-2 pt-2">
            <Button asChild variant="outline" size="sm"><Link to="/stays" state={{ stay: { property: property.name, name: data.current.name } }}>Ver estancia</Link></Button>
            <Button asChild variant="outline" size="sm"><Link to="/departures" state={{ stay: { property: property.name, name: data.current.name } }}>Revisar salida</Link></Button>
          </div>}
          {canFinance && <RoomAccountActions accounts={data.current.accounts || []}
            charges={data.current.recent_charges || []} provider={provider} />}
        </div> : <p className="text-sm text-muted-foreground">Sin estancia activa.</p>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Próxima llegada</CardTitle></CardHeader><CardContent>{data.next_arrival ? <div className="space-y-2 text-sm"><p className="font-semibold">{data.next_arrival.guest_label || "Huésped registrado"}</p><p>Entrada: {data.next_arrival.starts_at.slice(0, 16).replace("T", " ")}</p><p>Salida: {data.next_arrival.ends_at.slice(0, 16).replace("T", " ")}</p>{data.can.reserve && data.can.stay && data.next_arrival.booking && <Button asChild size="sm" className="mt-2"><Link to="/reception?section=arrivals" state={{ booking: { property: property.name, name: data.next_arrival.booking, action: "arrival" } }}>Registrar entrada</Link></Button>}</div> : <p className="text-sm text-muted-foreground">Sin llegada asignada.</p>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Trabajo de habitación</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p>Limpieza: <strong>{data.room.cleaning_status}</strong></p>{data.tasks.map((task) => <p key={task.name}>{task.kind} · {task.status}</p>)}{data.maintenance.map((order) => <p key={order.name}>{order.title} · {order.status}</p>)}{data.tickets.map((ticket) => <p key={ticket.name}>{ticket.subject} · {ticket.status}</p>)}{data.can.ticket && <Button asChild variant="outline" size="sm"><Link to={`/tickets?room=${encodeURIComponent(data.room.name)}`}>Crear ticket para esta habitación</Link></Button>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Características</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p>Capacidad: {data.details.capacity ?? "—"} · Camas: {data.details.beds ?? "—"}</p>{data.details.amenities && <p>{data.details.amenities}</p>}{data.details.description && <p className="text-muted-foreground">{data.details.description}</p>}</CardContent></Card>
    </div>
    <RoomDetailSections key={`${property.name}:${data.room.name}`} property={property} detail={data} />
  </div>
}

function PropertyApp() {
  const location = useLocation()
  const { base, detail, property, setProperty, error, loading } = useBootstrap()
  const [pettyNavigation, setPettyNavigation] = useState<{
    propertyName: string; sectionIds: string[]; defaultSection: string
  } | null>(null)
  const updatePettyNavigation = useCallback((propertyName: string, sectionIds: string[], defaultSection: string) => {
    setPettyNavigation((previous) => previous?.propertyName === propertyName &&
      previous.defaultSection === defaultSection && previous.sectionIds.join(",") === sectionIds.join(",")
      ? previous : { propertyName, sectionIds, defaultSection })
  }, [])
  if (loading) return <div className="mx-auto max-w-5xl space-y-6 p-8"><Skeleton className="h-16" /><Skeleton className="h-32" /><Skeleton className="h-64" /></div>
  if (error && !base) return <div className="mx-auto max-w-lg p-8"><Card><CardHeader><CardTitle>No se pudo abrir Hospitality Suite</CardTitle><CardDescription>{error}</CardDescription></CardHeader><CardContent><Button asChild><a href="/login?redirect-to=/hospitality/app"><LogIn /> Iniciar sesión</a></Button></CardContent></Card></div>
  if (!base?.properties.length) return <div className="mx-auto max-w-3xl space-y-6 p-8">
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
      <strong>Hospitality Suite</strong>
      <div className="flex flex-wrap gap-2">
        {base?.can_manage_users && <Button asChild variant="outline"><Link to="/users"><UsersRound size={18} />Administrar usuarios</Link></Button>}
        <Button asChild variant="outline"><Link to="/profile"><UserRound size={18} />Mi usuario</Link></Button>
      </div>
    </header>
    <RouteLoadBoundary key={location.pathname}>
    <Suspense fallback={<Skeleton className="h-72 w-full" />}>
    <Routes>
      <Route path="*" element={base?.can_create_property ? <Onboarding /> : <Card><CardHeader><CardTitle>Sin establecimientos asignados</CardTitle><CardDescription>Solicite acceso a un establecimiento para usar la aplicación. Puede configurar su usuario desde el enlace superior.</CardDescription></CardHeader></Card>} />
    </Routes>
    </Suspense>
    </RouteLoadBoundary>
  </div>
  if (!detail && !error) return <div className="mx-auto max-w-5xl space-y-6 p-8"><Skeleton className="h-16" /><Skeleton className="h-32" /><Skeleton className="h-64" /></div>
  const selected = base.properties.find((item) => item.name === property) || base.properties[0]
  const showJournal = base.accounting_provider === "pms" && base.actions.includes("journal")
  const showChart = base.accounting_provider === "pms" && base.actions.includes("chart")
  const showCurrencies = base.accounting_provider === "erpnext" && base.actions.includes("chart")
  const showCash = base.accounting_provider === "pms" && base.actions.includes("finance")
  const showErpCredits = base.accounting_provider === "erpnext" && base.actions.includes("finance")
  const showPetty = Boolean(detail?.petty_visible)
  const showClose = base.actions.includes("report")
  const showReports = showClose
  const showProducts = base.accounting_provider === "pms" && base.actions.includes("setup")
  const showServices = base.actions.includes("service")
  const showInventory = base.actions.includes("inventory")
  const showPurchases = base.accounting_provider === "pms" ? base.actions.includes("finance") :
    base.actions.includes("inventory") || base.actions.includes("finance")
  const showReception = base.actions.includes("reserve")
  const showStays = base.actions.includes("stay")
  const showDeparture = showStays
  const showTravel = ["reserve", "service", "commission", "finance", "setup", "approve"].some((action) => base.actions.includes(action))
  const showRoomWork = ["clean", "inspect", "maintain", "block", "incident"].some((action) => base.actions.includes(action))
  const showLaundry = base.actions.includes("laundry")
  const showTickets = base.actions.includes("ticket")
  const showSetup = base.actions.includes("setup")
  const showHealth = base.pages.some((page) => page.route === "hospitality-health")
  const showRetention = base.actions.includes("approve")
  return <Shell properties={base.properties} property={selected.name} setProperty={setProperty} provider={base.accounting_provider} showJournal={showJournal} showChart={showChart} showCurrencies={showCurrencies} showCash={showCash} showErpCredits={showErpCredits} showCashRefund={base.actions.includes("approve")} showPetty={showPetty} pettyNavigation={pettyNavigation} showClose={showClose} showReports={showReports} reportLabel={base.accounting_provider === "pms" ? "Reportes PMS" : "Reportes ERPNext"} showProducts={showProducts} showReception={showReception} showStays={showStays} canManageGuests={base.actions.includes("guest")} showDeparture={showDeparture} showTravel={showTravel} canCommission={base.actions.includes("commission")} showServices={showServices} showInventory={showInventory} showInventoryApprove={base.actions.includes("approve")} showPurchases={showPurchases} showRoomWork={showRoomWork} roomWorkActions={base.actions} showLaundry={showLaundry} showTickets={showTickets} showSetup={showSetup} showHealth={showHealth} showRetention={showRetention} showUsers={Boolean(base.can_manage_users)} showNewProperty={Boolean(base.can_create_property)}>
    {error && <p role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    <RouteLoadBoundary key={location.pathname}>
    <Suspense fallback={<Skeleton className="h-72 w-full" />}>
    <Routes>
      <Route path="/" element={<Dashboard property={selected} data={detail}
        actions={base.actions} provider={base.accounting_provider} />} />
      <Route path="/rooms" element={<RoomList key={`${base.user}:${selected.name}`}
        property={selected} user={base.user} />} />
      <Route path="/rooms/:room" element={<RoomView property={selected} provider={base.accounting_provider}
        canFinance={base.actions.includes("finance")} />} />
      {showRoomWork && <Route path="/room-work" element={<RoomOperations property={selected} provider={base.accounting_provider} />} />}
      {showTickets && <Route path="/tickets" element={<Tickets key={selected.name} property={selected} canInspect={base.actions.includes("inspect")} />} />}
      {showSetup && <Route path="/setup" element={<Setup key={selected.name} property={selected} provider={base.accounting_provider} />} />}
      {base.can_create_property && <Route path="/new-property" element={<Onboarding />} />}
      {showReception && <Route path="/reception" element={<Reception property={selected} provider={base.accounting_provider} canApprove={base.actions.includes("approve")} canSetup={base.actions.includes("setup")} canManageGuests={base.actions.includes("guest")} canStay={base.actions.includes("stay")} />} />}
      {showReception && <Route path="/reservations" element={<Reservations key={selected.name} property={selected} canStay={base.actions.includes("stay")} />} />}
      {showStays && <Route path="/stays" element={<Stays key={selected.name} property={selected} provider={base.accounting_provider} canFinance={showCash || showErpCredits} canApprove={showRetention} />} />}
      {showReception && <Route path="/reservations/draft/:booking" element={<BookingDraft key={selected.name} property={selected} provider={base.accounting_provider} />} />}
      {showReception && <Route path="/availability" element={<Availability key={selected.name} property={selected} />} />}
      {showReception && <Route path="/rates" element={<RateCalendar key={selected.name} property={selected} />} />}
      {showReception && <Route path="/room-calendar" element={<RoomCalendar key={selected.name} property={selected} />} />}
      {(showCash || showErpCredits) && <Route path="/day-pass" element={base.accounting_provider === "pms" ? <DayPass property={selected} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} /> : <ErpDayPass property={selected} canApprove={base.actions.includes("approve")} />} />}
      {showDeparture && <Route path="/departures" element={<Departure property={selected} provider={base.accounting_provider} canInspect={base.actions.includes("inspect")} canFinance={showCash || showErpCredits} canApprove={base.actions.includes("approve")} />} />}
      {showCash && <Route path="/folios" element={<Folios key={selected.name} property={selected} canApprove={base.actions.includes("approve")} />} />}
      {showCash && <Route path="/billing" element={<Billing key={selected.name} property={selected} canSetup={base.actions.includes("setup")} canChart={showChart} canApprove={base.actions.includes("approve")} />} />}
      {showErpCredits && <Route path="/erp-invoicing" element={<ErpInvoicing key={`${selected.name}:${location.search}`} property={selected} />} />}
      {base.accounting_provider === "erpnext" && showRetention && <Route path="/erp-adjustments" element={<ErpAdjustments key={`${selected.name}:${location.search}`} property={selected} />} />}
      {showErpCredits && <Route path="/direct-sales" element={<ErpDirectSales key={selected.name} property={selected} canApprove={showRetention} />} />}
      {(showCash || showErpCredits) && <Route path="/fiscal-archive" element={<FiscalArchive key={selected.name} property={selected} provider={base.accounting_provider} />} />}
      {showJournal && <Route path="/journal" element={<Journal property={selected} />} />}
      {showChart && <Route path="/chart" element={<Chart key={selected.name} property={selected} />} />}
      {showCurrencies && <Route path="/currencies" element={<PropertyCurrencies property={selected} />} />}
      {showProducts && <Route path="/products" element={<Products property={selected} />} />}
      {showServices && <Route path="/services" element={base.accounting_provider === "pms" ? <Services key={selected.name} property={selected} canApprove={base.actions.includes("approve")} canSetup={base.actions.includes("setup")} /> : <ErpServices key={selected.name} property={selected} canApprove={base.actions.includes("approve")} canFinance={showErpCredits} />} />}
      {showLaundry && <Route path="/laundry" element={<Laundry property={selected} provider={base.accounting_provider} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} canService={base.actions.includes("service")} canFinance={base.actions.includes("finance")} />} />}
      {showTravel && <Route path="/travel-experiences" element={base.accounting_provider === "pms" ? <TravelExperiences property={selected} canSetup={base.actions.includes("setup")} canReserve={base.actions.includes("reserve")} canService={base.actions.includes("service")} canCommission={base.actions.includes("commission")} canFinance={base.actions.includes("finance")} canApprove={base.actions.includes("approve")} /> : <ErpTravelExperiences property={selected} canSetup={base.actions.includes("setup")} canReserve={base.actions.includes("reserve")} canService={base.actions.includes("service")} canCommission={base.actions.includes("commission")} canFinance={base.actions.includes("finance")} />} />}
      {showInventory && <Route path="/inventory" element={base.accounting_provider === "pms" ? <Inventory property={selected} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} /> : <ErpInventory property={selected} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} />} />}
      {showPurchases && <Route path="/purchases" element={base.accounting_provider === "pms" ? <Purchases key={selected.name} property={selected} canPurchase={base.actions.includes("inventory")} canApprove={base.actions.includes("approve")} /> : <ErpPurchases key={selected.name} property={selected} canPurchase={base.actions.includes("inventory")} canFinance={base.actions.includes("finance")} />} />}
      {showCash && <Route path="/cash" element={<Cash key={selected.name} property={selected} canSetup={showChart} canRefund={base.actions.includes("approve")} />} />}
      {showErpCredits && <Route path="/cash" element={<ErpCash key={selected.name} property={selected} canCashApprove={base.actions.includes("cash_approve")} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} />} />}
      {showPetty && <Route path="/petty-cash" element={<PettyCash key={selected.name} property={selected} provider={base.accounting_provider} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} canFinance={base.actions.includes("finance")} onSectionsChange={updatePettyNavigation} />} />}
      {showClose && <Route path="/daily-close" element={base.accounting_provider === "pms"
        ? <DailyClose key={selected.name} property={selected} canApprove={base.actions.includes("approve")} />
        : <ErpDailyClose key={selected.name} property={selected} canApprove={base.actions.includes("approve")} />} />}
      {showReports && <Route path="/reports" element={base.accounting_provider === "pms" ? <Reports property={selected} /> : <ErpReports property={selected} />} />}
      {showReports && <Route path="/portfolio" element={<Portfolio onOpen={setProperty} />} />}
      {showHealth && <Route path="/health" element={<Health property={selected} />} />}
      {showRetention && <Route path="/retention" element={<PrivacyRetention key={selected.name} property={selected} canSetup={showSetup} />} />}
      {(showCash || showErpCredits) && <Route path="/financing" element={showCash
        ? <Financing key={selected.name} property={selected} canApprove={base.actions.includes("approve")} canChart={showChart} />
        : <ErpFinancing key={selected.name} property={selected} canSetup={base.actions.includes("setup")} canApprove={base.actions.includes("approve")} canFinance={base.actions.includes("finance")} />} />}
      {showCash && <Route path="/receivables" element={<Receivables key={selected.name} property={selected} canCreate={showChart} canCancel={base.actions.includes("approve")} />} />}
      {showErpCredits && <Route path="/customer-credits" element={<CustomerCredits property={selected} canApprove={base.actions.includes("approve")} />} />}
      {showCash && <Route path="/credit" element={<Credit key={selected.name} property={selected} canApprove={base.actions.includes("approve")} />} />}
      {showErpCredits && <Route path="/erp-credit" element={<ErpCredit key={selected.name} property={selected} canSetup={showSetup} />} />}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
    </RouteLoadBoundary>
  </Shell>
}

function UserAccessPage({ section }: { section: "directory" | "assign" }) {
  const [base, setBase] = useState<Bootstrap | null>(null)
  const [propertyName, setPropertyName] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    call<Bootstrap>("bootstrap", {}, controller.signal).then((result) => {
      if (controller.signal.aborted) return
      setBase(result)
      const saved = localStorage.getItem(USER_ACCESS_PROPERTY_KEY)
      setPropertyName(result.properties.some((item) => item.name === saved)
        ? saved! : result.properties[0]?.name || "")
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudo consultar el acceso.")
    })
    return () => controller.abort()
  }, [])

  if (error) return <p role="alert" className="rounded-md border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>
  if (!base) return <Skeleton className="h-72 w-full" />
  if (!base.can_manage_users) return <Card><CardHeader><CardTitle>Acceso restringido</CardTitle>
    <CardDescription>Solo administración del sistema puede gestionar accesos.</CardDescription></CardHeader></Card>
  const property = base.properties.find((item) => item.name === propertyName)
  if (!property) return <Card><CardHeader><CardTitle>Sin establecimientos disponibles</CardTitle>
    <CardDescription>Necesita un establecimiento asignado para consultar y conceder accesos.</CardDescription></CardHeader></Card>
  return <div className="space-y-6">
    <label className="block max-w-md space-y-1 text-sm font-medium"><span>Establecimiento para gestionar accesos</span>
      <select className="h-10 w-full rounded-md border border-border bg-white px-3 text-sm" value={property.name}
        onChange={(event) => { setPropertyName(event.target.value); localStorage.setItem(USER_ACCESS_PROPERTY_KEY, event.target.value) }}>
        {base.properties.map((item) => <option key={item.name} value={item.name}>{item.brand_name || item.property_name}</option>)}
      </select>
    </label>
    <UserManagement key={`${property.name}:${section}`} property={property} section={section} />
  </div>
}

function PersonalSettingsPage() {
  const location = useLocation()
  const section = new URLSearchParams(location.search).get("section") === "preferences"
    ? "preferences" : "profile"
  const links = [
    { to: "/profile", label: "Datos personales", icon: UserRound, section: "profile" },
    { to: "/profile?section=preferences", label: "Preferencias", icon: Settings2, section: "preferences" },
  ] as const
  return <div className="min-h-screen bg-background">
    <header className="border-b border-border bg-white">
      <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-4 lg:px-8">
        <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><UserRound size={21} /></span>
          <div><p className="font-semibold">Mi usuario</p><p className="text-xs text-muted-foreground">Configuración personal</p></div>
        </div>
        <Button asChild variant="outline"><Link to="/">Volver a Hospitality</Link></Button>
      </div>
    </header>
    <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[15rem_minmax(0,1fr)] lg:px-8">
      <aside aria-label="Menú de configuración de usuario" className="h-fit rounded-xl border border-border bg-white p-3">
        <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Configuración de usuario</p>
        <nav className="space-y-1">{links.map(({ to, label, icon: Icon, section: itemSection }) => <Link key={to} to={to}
          aria-current={itemSection === section ? "page" : undefined}
          className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${itemSection === section ? "bg-secondary font-semibold text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
          <Icon size={17} aria-hidden="true" />{label}</Link>)}</nav>
      </aside>
      <main className="min-w-0"><RouteLoadBoundary key={section}><Suspense fallback={<Skeleton className="h-72 w-full" />}>
        <MyUserSettings key={section} section={section} />
      </Suspense></RouteLoadBoundary></main>
    </div>
  </div>
}

function UserAdministrationPage({ kind }: { kind: "new-user" | "directory" | "assign" }) {
  const activePath = kind === "new-user" ? "/users/new" :
    kind === "assign" ? "/users/assign" : "/users"
  const links = [
    { to: "/users", label: "Directorio de usuarios", icon: UsersRound },
    { to: "/users/new", label: "Nuevo usuario", icon: UserRound },
    { to: "/users/assign", label: "Conceder acceso", icon: ShieldCheck },
  ]
  return <div className="min-h-screen bg-background">
    <header className="border-b border-border bg-white">
      <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-4 lg:px-8">
        <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><UsersRound size={21} /></span>
          <div><p className="font-semibold">Usuarios</p><p className="text-xs text-muted-foreground">Administración de usuarios</p></div>
        </div>
        <Button asChild variant="outline"><Link to="/">Volver a Hospitality</Link></Button>
      </div>
    </header>
    <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[15rem_minmax(0,1fr)] lg:px-8">
      <aside aria-label="Menú de usuarios" className="h-fit rounded-xl border border-border bg-white p-3">
        <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Usuarios</p>
        <nav className="space-y-1">{links.map(({ to, label, icon: Icon }) => <Link key={to} to={to}
          aria-current={to === activePath ? "page" : undefined}
          className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${to === activePath ? "bg-secondary font-semibold text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
          <Icon size={17} aria-hidden="true" />{label}</Link>)}</nav>
      </aside>
      <main className="min-w-0"><RouteLoadBoundary><Suspense fallback={<Skeleton className="h-72 w-full" />}>
        {kind === "new-user" ? <NewUser /> : <UserAccessPage section={kind} />}
      </Suspense></RouteLoadBoundary></main>
    </div>
  </div>
}

export default function App() {
  const location = useLocation()
  if (location.pathname === "/users/profile") return <Navigate to="/profile" replace />
  if (location.pathname === "/profile") return <PersonalSettingsPage />
  if (location.pathname === "/users/new") return <UserAdministrationPage kind="new-user" />
  if (location.pathname === "/users") return <UserAdministrationPage kind="directory" />
  if (location.pathname === "/users/assign") return <UserAdministrationPage kind="assign" />
  return <PropertyApp />
}
