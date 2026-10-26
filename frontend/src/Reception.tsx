import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, postMethod, type Property } from "./api"
import { PortalRequests } from "./PortalRequests"
import { FolioWork } from "./FolioWork"
import { GuestProfiles } from "./GuestProfiles"
import type { AvailabilityPrefill } from "./Availability"
import { availableReceptionSections } from "./ReceptionSections"

type ReceptionData = {
  currency: string; mode: string; guest_id_required: boolean; portal_enabled: boolean
  parties: { name: string; party_name: string }[]
  guests: { name: string; full_name: string; customer: string }[]
  categories: { name: string; category_name: string; capacity: number; max_extra_beds: number }[]
  rooms: { name: string; room_number: string; category: string; cleaning_status: string }[]
  rates: { name: string; title: string; category: string; mode: string;
    day_pass: boolean; amount: number; currency: string; customer: string | null }[]
  agents: { name: string; agent_name: string; commission_pct: number }[]
  experiences: { name: string; experience_name: string; pms_product: string | null }[]
  bookings: { name: string; status: string; customer: string; guest: string | null;
    starts_at_local: string; ends_at_local: string; amount: number; modified: string;
    mode: string; modifiable: boolean; travel_agent: string | null;
    agent_commission_pct: number; agent_commission_estimate: number }[]
  booking_lines: { parent: string; category: string; room: string | null;
    people: number; extra_beds: number; rate: string | null; idx: number }[]
  allocations: { name: string; booking: string; category: string; room: string | null }[]
  stays: { name: string; booking: string | null; guest: string; customer: string;
    room: string; starts_at_local: string; ends_at_local: string; modified: string }[]
  folios: { name: string; stay: string | null; booking: string | null;
    customer: string; label: string | null }[]
}
type Reservation = { customer: string; guest: string; starts_at: string; ends_at: string;
  travel_agent?: string | null; experiences?: { experience: string; quantity: number }[];
  mode: string; rooms: { category: string; room: string | null; people: number;
    extra_beds: number; rate: string | null }[] }
type ReservationRequest = Reservation & { booking?: string; modified?: string; reason?: string }
type ReservationQuote = { amount: string; estimated_total: string; currency: string;
  experiences_total: string; experiences: { experience: string; name: string;
    quantity: number; total_amount?: string; amount: string; tax_amount?: string }[];
  agent: { travel_agent: string | null; agent_commission_pct: number;
    agent_commission_estimate: number };
  acceptance: string; lines: { amount: string; explanation: string[];
    rules: { title: string } }[] }
type ArrivalQuote = { early: string; late: string; acceptance: string; explanation?: string }
type MoveRequest = { stay: string; modified: string; room: string; reason: string; folio?: string }
type MoveQuote = { quote: { amount: string; rules: { title: string } };
  difference: string; explanation: string; valid_until: string; acceptance: string }
type ExtensionRequest = { stay: string; modified: string; ends_at: string;
  folio: string; reason: string }
type ExtensionQuote = { amount: string; difference: string; currency: string;
  explanation: string[]; service_start: string; service_end: string; acceptance: string }
type CompanionGuest = { name: string; full_name: string; has_identity: boolean }
type CompanionPage = { stay: string; modified: string; principal: string;
  capacity: number; guest_id_required: boolean; selected: CompanionGuest[];
  candidates: CompanionGuest[]; total: number; offset: number; has_more: boolean }
type FeeMode = "None" | "Fixed" | "Percent" | "First Night"
type FeeSettings = { modified: string; cancellation_fee_mode: FeeMode;
  cancellation_fee_value: string; no_show_fee_mode: FeeMode; no_show_fee_value: string;
  receivable_account: string | null; penalty_item: string | null;
  receivable_accounts: { name: string; account_code: string; account_name: string }[] }
type FeeQuote = { amount: string; currency: string; mode: FeeMode; status: "Cancelled" | "No Show";
  net_amount?: string; tax_amount?: string; total_amount?: string; acceptance: string }
type RoomDraft = { id: string; category: string; room: string; people: string;
  extraBeds: string; rate: string }
type BookingContext = { booking: { name: string; property: string; status: string };
  summary: { guest_label: string; customer_label: string;
    rooms: { room_label: string }[] };
  workflow: ReceptionData["bookings"][number] & { can_arrive: boolean;
    can_cancel: boolean; rooms: (ReceptionData["booking_lines"][number] & { idx: number })[] };
  allocations: (ReceptionData["allocations"][number] & { booking_room: string })[] }
const newRoom = (): RoomDraft => ({ id: crypto.randomUUID(), category: "", room: "",
  people: "1", extraBeds: "0", rate: "" })

export function Reception({ property, provider, canApprove, canSetup, canManageGuests, canStay,
  embeddedSection, initialRoomChoice, initialBooking, onChanged }: {
  property: Property; provider: "pms" | "erpnext"; canApprove: boolean;
  canSetup: boolean; canManageGuests: boolean; canStay: boolean;
  embeddedSection?: "reservation" | "arrivals";
  initialRoomChoice?: { property: string; room: string; category: string };
  initialBooking?: { property: string; name: string; action: "edit" | "arrival" | "cancel" };
  onChanged?: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const visibleSections = availableReceptionSections(provider, canSetup, canStay, canManageGuests)
  const section = visibleSections.find((item) => item.id === (embeddedSection || searchParams.get("section"))) || visibleSections[0]
  const embeddedRoomLoaded = useRef(false)
  const embeddedBookingLoaded = useRef(false)
  const [data, setData] = useState<ReceptionData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [guestName, setGuestName] = useState("")
  const [guestIdentity, setGuestIdentity] = useState("")
  const [guestIdentityType, setGuestIdentityType] = useState("")
  const [guestEmail, setGuestEmail] = useState("")
  const [guestPhone, setGuestPhone] = useState("")
  const [guestNationality, setGuestNationality] = useState("")
  const [guestParty, setGuestParty] = useState("")
  const [guest, setGuest] = useState("")
  const [payer, setPayer] = useState("")
  const [travelAgent, setTravelAgent] = useState("")
  const [experienceRows, setExperienceRows] = useState<
    { id: string; experience: string; quantity: string }[]>([])
  const [mode, setMode] = useState(property.mode === "Mixed" ? "Hotel" : property.mode)
  const [startsAt, setStartsAt] = useState("")
  const [endsAt, setEndsAt] = useState("")
  const [rooms, setRooms] = useState<RoomDraft[]>([newRoom()])
  const [reservationQuote, setReservationQuote] = useState<
    (ReservationQuote & { request: ReservationRequest; requestKey: string }) | null>(null)
  const [editingBooking, setEditingBooking] = useState<{
    name: string; modified: string } | null>(null)
  const [editingReason, setEditingReason] = useState("")
  const [arrivalBooking, setArrivalBooking] = useState("")
  const [arrivalAllocation, setArrivalAllocation] = useState("")
  const [arrivalRoom, setArrivalRoom] = useState("")
  const [arrivalGuest, setArrivalGuest] = useState("")
  const [arrivalQuote, setArrivalQuote] = useState<(ArrivalQuote & { requestKey: string }) | null>(null)
  const [moveStay, setMoveStay] = useState("")
  const [moveRoom, setMoveRoom] = useState("")
  const [moveFolio, setMoveFolio] = useState("")
  const [moveReason, setMoveReason] = useState("")
  const [moveQuote, setMoveQuote] = useState<(MoveQuote & { request: MoveRequest; requestKey: string }) | null>(null)
  const [extendStay, setExtendStay] = useState("")
  const [extendEnd, setExtendEnd] = useState("")
  const [extendFolio, setExtendFolio] = useState("")
  const [extendReason, setExtendReason] = useState("")
  const [extendQuote, setExtendQuote] = useState<(ExtensionQuote & {
    request: ExtensionRequest; requestKey: string }) | null>(null)
  const [feeSettings, setFeeSettings] = useState<FeeSettings | null>(null)
  const [feePolicy, setFeePolicy] = useState({ cancellation_fee_mode: "None" as FeeMode,
    cancellation_fee_value: "0", no_show_fee_mode: "None" as FeeMode,
    no_show_fee_value: "0", receivable_account: "" })
  const [cancelBooking, setCancelBooking] = useState("")
  const [cancelStatus, setCancelStatus] = useState<"Cancelled" | "No Show">("Cancelled")
  const [cancelReason, setCancelReason] = useState("")
  const [cancelQuote, setCancelQuote] = useState<(FeeQuote & { requestKey: string }) | null>(null)
  const [confirmationLink, setConfirmationLink] = useState<{ booking: string; url: string } | null>(null)
  const linkRequest = useRef<{ booking: string; key: string } | null>(null)
  const [companionStay, setCompanionStay] = useState("")
  const [companionPage, setCompanionPage] = useState<CompanionPage | null>(null)
  const [companionSelected, setCompanionSelected] = useState<CompanionGuest[]>([])
  const [companionSearchInput, setCompanionSearchInput] = useState("")
  const [companionSearch, setCompanionSearch] = useState("")
  const [companionOffset, setCompanionOffset] = useState(0)
  const companionSelectedFor = useRef("")
  const companionRequest = useRef<{ fingerprint: string; key: string } | null>(null)

  const refresh = useCallback(async () => {
    setData(await call<ReceptionData>(provider === "pms" ? "pms_reception_snapshot" :
      "erp_reception_snapshot", { property_name: property.name }))
  }, [property.name, provider])
  const refreshFeeSettings = useCallback(async () => {
    if (!canSetup || provider !== "pms") return
    const settings = await call<FeeSettings>("pms_booking_fee_settings",
      { property_name: property.name })
    setFeeSettings(settings)
    setFeePolicy({ cancellation_fee_mode: settings.cancellation_fee_mode,
      cancellation_fee_value: settings.cancellation_fee_value,
      no_show_fee_mode: settings.no_show_fee_mode,
      no_show_fee_value: settings.no_show_fee_value,
      receivable_account: settings.receivable_account || "" })
  }, [canSetup, property.name, provider])
  useEffect(() => {
    setData(null); setError(""); setNotice(""); setReservationQuote(null); setArrivalQuote(null)
    setMoveStay(""); setMoveRoom(""); setMoveFolio(""); setMoveReason(""); setMoveQuote(null)
    setExtendStay(""); setExtendEnd(""); setExtendFolio(""); setExtendReason(""); setExtendQuote(null)
    setGuest(""); setPayer(""); setTravelAgent(""); setExperienceRows([]); setRooms([newRoom()])
    setEditingBooking(null); setEditingReason("")
    setFeeSettings(null); setCancelBooking(""); setCancelQuote(null); setCancelReason("")
    setConfirmationLink(null); linkRequest.current = null
    setCompanionStay(""); setCompanionPage(null); setCompanionSelected([])
    setCompanionSearchInput(""); setCompanionSearch(""); setCompanionOffset(0)
    companionSelectedFor.current = ""; companionRequest.current = null
    setMode(property.mode === "Mixed" ? "Hotel" : property.mode)
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar recepción."))
    refreshFeeSettings().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudo consultar la política de penalización."))
  }, [property.mode, refresh, refreshFeeSettings])
  useEffect(() => {
    if (!data || !location.state) return
    const value = (location.state as { availability?: AvailabilityPrefill }).availability
    if (!value) return
    const category = data.categories.find((item) => item.name === value?.category)
    const room = value?.room ? data.rooms.find((item) =>
      item.name === value.room && item.category === category?.name)
      : undefined
    const validDate = (candidate: unknown): candidate is string =>
      typeof candidate === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(candidate)
    if (value?.property === property.name && category &&
        (value.mode === "Hotel" || value.mode === "Por tiempo") &&
        (property.mode === "Mixed" || value.mode === property.mode) &&
        Number.isInteger(value.quantity) && value.quantity >= 1 && value.quantity <= 1000 &&
        Number.isInteger(value.people) && value.people >= 1 && value.people <= category.capacity &&
        validDate(value.starts_at) && validDate(value.ends_at) &&
        value.ends_at > value.starts_at && (!value.room || room)) {
      setMode(value.mode)
      setStartsAt(value.starts_at); setEndsAt(value.ends_at)
      setRooms(Array.from({ length: value.quantity }, (_, index) => ({
        id: crypto.randomUUID(), category: category.name,
        room: index === 0 ? room?.name || "" : "", people: String(value.people),
        extraBeds: "0", rate: "",
      })))
      setReservationQuote(null)
      setNotice("Datos de disponibilidad cargados. Seleccione huésped, pagador y tarifa; la disponibilidad se comprobará otra vez al cotizar.")
      requestAnimationFrame(() => document.getElementById("reservation-form")?.scrollIntoView({ behavior: "smooth" }))
    }
    navigate("/reception?section=reservation", { replace: true, state: null })
  }, [data, location.state, navigate, property.mode, property.name])
  useEffect(() => {
    if (!data || (!location.state && !initialRoomChoice)) return
    const choice = initialRoomChoice ? (!embeddedRoomLoaded.current ? initialRoomChoice : undefined) :
      (location.state as { roomChoice?: {
        property: string; room: string; category: string } } | null)?.roomChoice
    if (!choice) return
    if (choice === initialRoomChoice) embeddedRoomLoaded.current = true
    const room = data.rooms.find((entry) => entry.name === choice.room &&
      entry.category === choice.category)
    if (choice.property === property.name && room) {
      setRooms([{ ...newRoom(), category: room.category, room: room.name }])
      setReservationQuote(null)
      setNotice(`Habitación ${room.room_number} preseleccionada. Indique fechas y huésped; el cupo se comprobará al cotizar.`)
      requestAnimationFrame(() => document.getElementById("reservation-form")?.scrollIntoView({ behavior: "smooth" }))
    }
    if (!embeddedSection) navigate("/reception?section=reservation", { replace: true, state: null })
  }, [data, location.state, navigate, property.name, initialRoomChoice, embeddedSection])
  useEffect(() => {
    if (!data || (!location.state && !initialBooking)) return
    const target = initialBooking ? (!embeddedBookingLoaded.current ? initialBooking : undefined) :
      (location.state as { booking?: { property: string; name: string;
        action: "edit" | "arrival" | "cancel" } } | null)?.booking
    if (!target) return
    if (target === initialBooking) embeddedBookingLoaded.current = true
    if (target.property !== property.name || !target.name ||
        !["edit", "arrival", "cancel"].includes(target.action)) {
      setError("La reserva solicitada no pertenece a este establecimiento.")
      if (!embeddedSection) navigate("/reception?section=arrivals", { replace: true, state: null })
      return
    }
    const controller = new AbortController()
    call<BookingContext>("booking_detail", { name: target.name }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        const source = result.workflow
        if (result.booking.property !== property.name || source.name !== target.name ||
            (target.action === "edit" && !source.modifiable) ||
            (target.action === "arrival" && (!canStay || !source.can_arrive)) ||
            (target.action === "cancel" && !source.can_cancel))
          throw new Error("Esta reserva ya no admite la acción solicitada. Actualice su estado.")
        const bookingRow: ReceptionData["bookings"][number] = {
          name: source.name, status: source.status, customer: source.customer,
          guest: source.guest, starts_at_local: source.starts_at_local,
          ends_at_local: source.ends_at_local, amount: Number(source.amount),
          modified: source.modified, mode: source.mode,
          modifiable: source.modifiable, travel_agent: source.travel_agent,
          agent_commission_pct: Number(source.agent_commission_pct || 0),
          agent_commission_estimate: Number(source.agent_commission_estimate || 0),
        }
        const lines = source.rooms.map((line) => ({ ...line, parent: source.name }))
        setData((current) => current && ({ ...current,
          bookings: [bookingRow, ...current.bookings.filter((row) => row.name !== source.name)],
          booking_lines: [...lines, ...current.booking_lines.filter((row) => row.parent !== source.name)],
          allocations: [...result.allocations,
            ...current.allocations.filter((row) => row.booking !== source.name)],
          parties: source.customer && !current.parties.some((row) => row.name === source.customer)
            ? [{ name: source.customer, party_name: result.summary.customer_label }, ...current.parties]
            : current.parties,
          guests: source.guest && !current.guests.some((row) => row.name === source.guest)
            ? [{ name: source.guest, full_name: result.summary.guest_label,
                customer: source.customer }, ...current.guests]
            : current.guests,
          rooms: [...source.rooms.flatMap((line, index) => line.room &&
            !current.rooms.some((row) => row.name === line.room) ? [{
              name: line.room, room_number: result.summary.rooms[index]?.room_label || line.room,
              category: line.category, cleaning_status: "—",
            }] : []), ...current.rooms],
        }))
        setError(""); setNotice(embeddedSection ? `Reserva ${source.name} lista para ${target.action === "edit" ? "modificar" : target.action === "cancel" ? "cancelar" : "registrar entrada"}.` :
          `Reserva ${source.name} cargada desde el historial.`)
        if (target.action === "edit") {
          setEditingBooking({ name: source.name, modified: source.modified })
          setEditingReason(""); setGuest(source.guest || ""); setPayer(source.customer)
          setTravelAgent(source.travel_agent || ""); setExperienceRows([])
          setMode(source.mode)
          setStartsAt(source.starts_at_local.replace(" ", "T"))
          setEndsAt(source.ends_at_local.replace(" ", "T"))
          setRooms(lines.map((line) => ({ id: crypto.randomUUID(),
            category: line.category, room: line.room || "",
            people: String(line.people), extraBeds: String(line.extra_beds || 0),
            rate: data.rates.some((row) => row.name === line.rate) ? line.rate || "" : "",
          })))
          setReservationQuote(null)
        } else if (target.action === "arrival") {
          const allocation = result.allocations[0]
          setArrivalBooking(source.name); setArrivalAllocation(allocation?.name || "")
          setArrivalRoom(allocation?.room || ""); setArrivalGuest(source.guest || "")
          setArrivalQuote(null)
        } else {
          setCancelBooking(source.name); setCancelStatus("Cancelled")
          setCancelReason(""); setCancelQuote(null)
        }
        if (!embeddedSection) {
          navigate(`/reception?section=${target.action === "edit" ? "reservation" : "arrivals"}`, { replace: true, state: null })
          requestAnimationFrame(() => document.getElementById(
            target.action === "edit" ? "reservation-form" : "reception-arrivals")
            ?.scrollIntoView({ behavior: "smooth" }))
        }
      }).catch((issue: unknown) => {
        if (controller.signal.aborted) return
        setError(issue instanceof Error ? issue.message : "No se pudo cargar la reserva.")
        if (!embeddedSection) navigate("/reception?section=arrivals", { replace: true, state: null })
      })
    return () => controller.abort()
  }, [canStay, data, location.state, navigate, property.name, initialBooking, embeddedSection])
  useEffect(() => {
    if (!companionStay || !canManageGuests) return
    const controller = new AbortController()
    setCompanionPage(null)
    call<CompanionPage>("stay_companions", { property_name: property.name,
      stay: companionStay, search: companionSearch, offset: String(companionOffset),
      page_length: "25" }, controller.signal).then((page) => {
      setCompanionPage(page)
      if (companionSelectedFor.current !== page.stay) {
        setCompanionSelected(page.selected)
        companionSelectedFor.current = page.stay
      }
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los huéspedes.")
    })
    return () => controller.abort()
  }, [property.name, canManageGuests, companionStay, companionSearch, companionOffset])

  const matchingRooms = (category: string) => (data?.rooms || []).filter((row) => row.category === category)
  const matchingRates = (category: string) => (data?.rates || []).filter((row) => row.category === category &&
    row.mode === (mode === "Day Pass" ? "Por tiempo" : mode) && Boolean(row.day_pass) === (mode === "Day Pass") &&
    (!row.customer || row.customer === payer))
  const selectedBooking = data?.bookings.find((row) => row.name === arrivalBooking)
  const selectedAllocation = data?.allocations.find((row) => row.name === arrivalAllocation)
  const arrivalRooms = data?.rooms.filter((row) => row.category === selectedAllocation?.category) || []
  const arrivalAllocations = data?.allocations.filter((row) => row.booking === arrivalBooking) || []
  const selectedMoveStay = data?.stays.find((row) => row.name === moveStay)
  const selectedExtendStay = data?.stays.find((row) => row.name === extendStay)
  const selectedCancelBooking = data?.bookings.find((row) => row.name === cancelBooking)
  const moveFolios = data?.folios.filter((row) => selectedMoveStay && row.customer === selectedMoveStay.customer &&
    (row.stay === selectedMoveStay.name || !row.stay && !!selectedMoveStay.booking &&
      row.booking === selectedMoveStay.booking)) || []
  const moveCandidates = data?.rooms.filter((row) => row.name !== selectedMoveStay?.room &&
    row.cleaning_status === "Clean" && !data.stays.some((stay) => stay.room === row.name)) || []
  const extensionFolios = data?.folios.filter((row) => selectedExtendStay &&
    row.customer === selectedExtendStay.customer &&
    (row.stay === selectedExtendStay.name || !row.stay && !!selectedExtendStay.booking &&
      row.booking === selectedExtendStay.booking)) || []
  const guestLabel = (name: string | null) => data?.guests.find((row) => row.name === name)?.full_name || name || "Sin huésped"
  const payerLabel = (name: string) => data?.parties.find((row) => row.name === name)?.party_name || name
  const roomLabel = (name: string | null) => data?.rooms.find((row) => row.name === name)?.room_number || "Por asignar"
  function updateRoom(id: string, changes: Partial<RoomDraft>) {
    setRooms((current) => current.map((row) => row.id === id ? { ...row, ...changes } : row))
    setReservationQuote(null)
  }

  async function createGuest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const details = { full_name: guestName.trim(), identity_type: guestIdentityType.trim(),
        identity_number: guestIdentity.trim(), email: guestEmail.trim(),
        phone: guestPhone.trim(), nationality: guestNationality.trim() }
      let registeredGuest: string
      let registeredPayer: string
      if (provider === "pms") {
        const result = await execute<{ guest: string; party: string }>(property.name,
          "pms_create_guest", { ...details, party: guestParty || undefined }, crypto.randomUUID())
        registeredGuest = result.guest; registeredPayer = result.party
      } else {
        const result = await postMethod<{ guest: string; customer: string }>("create_guest", {
          property_name: property.name, data: { ...details, customer: guestParty || undefined },
          request_key: crypto.randomUUID(),
        })
        registeredGuest = result.guest; registeredPayer = result.customer
      }
      await refresh(); setGuest(registeredGuest); setPayer(registeredPayer)
      setGuestName(""); setGuestIdentity(""); setGuestIdentityType(""); setGuestParty("")
      setGuestEmail(""); setGuestPhone(""); setGuestNationality("")
      setRooms((current) => current.map((row) => ({ ...row, rate: "" })))
      setReservationQuote(null); setNotice("Huésped registrado; ya puede crear su reserva.")
      navigate("/reception?section=reservation")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar el huésped.") }
    finally { setBusy(false) }
  }

  function openCompanions(stay: ReceptionData["stays"][number]) {
    setError(""); setCompanionPage(null); setCompanionStay(stay.name)
    setCompanionSelected([]); setCompanionSearchInput(""); setCompanionSearch("")
    setCompanionOffset(0); companionSelectedFor.current = ""
    companionRequest.current = null
    navigate("/reception?section=stay-companions")
  }

  async function saveCompanions() {
    if (busy || !companionPage) return
    setBusy(true); setError(""); setNotice("")
    try {
      const payload = { stay: companionPage.stay, modified: companionPage.modified,
        guests: companionSelected.map((row) => row.name) }
      const fingerprint = JSON.stringify([property.name, payload])
      if (companionRequest.current?.fingerprint !== fingerprint) {
        companionRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await execute(property.name, "companions", payload, companionRequest.current.key)
      companionRequest.current = null
      setCompanionStay(""); setCompanionPage(null)
      setNotice("Acompañantes actualizados.")
      await refresh().catch(() => setError("Los acompañantes se guardaron. Actualice Recepción para verlos."))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron actualizar los acompañantes.") }
    finally { setBusy(false) }
  }

  function reservation(): Reservation {
    return { customer: payer, guest, starts_at: startsAt, ends_at: endsAt, mode,
      travel_agent: travelAgent || null,
      ...(!editingBooking ? { experiences: experienceRows.map((row) => ({
        experience: row.experience, quantity: Number(row.quantity) })) } : {}),
      rooms: rooms.map((row) => ({ category: row.category, room: row.room || null,
        people: Number(row.people), extra_beds: Number(row.extraBeds), rate: row.rate || null })) }
  }

  function editBooking(booking: ReceptionData["bookings"][number]) {
    if (!data || !booking.modifiable) return
    const lines = data.booking_lines.filter((row) => row.parent === booking.name)
      .sort((a, b) => a.idx - b.idx)
    if (!lines.length) { setError("La reserva no conserva sus habitaciones originales."); return }
    setEditingBooking({ name: booking.name, modified: booking.modified })
    setEditingReason(""); setGuest(booking.guest || ""); setPayer(booking.customer)
    setTravelAgent(booking.travel_agent || ""); setExperienceRows([])
    setMode(booking.mode); setStartsAt(booking.starts_at_local.replace(" ", "T"))
    setEndsAt(booking.ends_at_local.replace(" ", "T"))
    setRooms(lines.map((line) => ({ id: crypto.randomUUID(), category: line.category,
      room: line.room || "", people: String(line.people),
      extraBeds: String(line.extra_beds || 0),
      rate: data.rates.some((item) => item.name === line.rate) ? line.rate || "" : "" })))
    setReservationQuote(null); setError(""); setNotice("")
    navigate("/reception?section=reservation")
    requestAnimationFrame(() => document.getElementById("reservation-form")?.scrollIntoView({ behavior: "smooth" }))
  }

  function stopEditing() {
    setEditingBooking(null); setEditingReason(""); setGuest(""); setPayer("")
    setTravelAgent(""); setExperienceRows([])
    setStartsAt(""); setEndsAt(""); setRooms([newRoom()]); setReservationQuote(null)
    setMode(property.mode === "Mixed" ? "Hotel" : property.mode)
  }

  async function previewReservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setNotice(""); setReservationQuote(null)
    try {
      const request: ReservationRequest = { ...reservation(),
        ...(editingBooking ? { booking: editingBooking.name, modified: editingBooking.modified,
          reason: editingReason.trim() } : {}) }
      const result = await call<ReservationQuote>("preview", { property_name: property.name,
        action: editingBooking ? "modify_reservation" : "reserve", data: JSON.stringify(request) })
      setReservationQuote({ ...result, request, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la reserva.") }
    finally { setBusy(false) }
  }

  async function confirmReservation(directEntry: boolean) {
    if (!reservationQuote || busy) return
    setBusy(true); setError("")
    try {
      const wasEditing = !!reservationQuote.request.booking
      const result = await execute<{ booking?: string; stay?: string; folio?: string }>(
        property.name, wasEditing ? "modify_reservation" : directEntry ? "walk_in" : "reserve",
        { ...reservationQuote.request, acceptance: reservationQuote.acceptance },
        reservationQuote.requestKey)
      if (wasEditing) stopEditing(); else setReservationQuote(null)
      await refresh()
      onChanged?.()
      setNotice(wasEditing ? `Reserva ${result.booking} modificada.` :
        directEntry ? `Entrada registrada: ${result.stay}. Cuenta de estancia ${result.folio}.` :
        `Reserva ${result.booking} confirmada con ${reservationQuote.request.rooms.length} habitación(es).`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo confirmar la reserva.") }
    finally { setBusy(false) }
  }

  function selectArrival(booking: ReceptionData["bookings"][number]) {
    const allocation = data?.allocations.find((row) => row.booking === booking.name)
    setArrivalBooking(booking.name); setArrivalAllocation(allocation?.name || "")
    setArrivalRoom(allocation?.room || ""); setArrivalGuest(booking.guest || "")
    setArrivalQuote(null); setError("")
  }

  async function confirmHold(booking: ReceptionData["bookings"][number]) {
    if (busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "booking_status", { booking: booking.name,
        modified: booking.modified, status: "Confirmed" }, crypto.randomUUID())
      await refresh(); setNotice(`Reserva ${booking.name} confirmada.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo confirmar la retención.") }
    finally { setBusy(false) }
  }

  async function prepareConfirmationLink(booking: string) {
    if (busy || !data?.portal_enabled) return
    setBusy(true); setError(""); setConfirmationLink(null)
    if (linkRequest.current?.booking !== booking) {
      linkRequest.current = { booking, key: crypto.randomUUID() }
    }
    try {
      const result = await execute<{ url: string }>(property.name, "portal_link",
        { booking }, linkRequest.current.key)
      const url = new URL(result.url, window.location.origin)
      if (url.origin !== window.location.origin || url.pathname !== "/hospitality-confirmation" ||
          !url.searchParams.get("token")) throw new Error("El servidor devolvió un enlace inválido.")
      setConfirmationLink({ booking, url: url.toString() })
      linkRequest.current = null
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo preparar el enlace.") }
    finally { setBusy(false) }
  }

  async function copyConfirmationLink() {
    if (!confirmationLink) return
    try {
      await navigator.clipboard.writeText(confirmationLink.url)
      setNotice("Enlace copiado. Compártalo únicamente con el huésped correspondiente.")
    } catch { setError("Seleccione y copie el enlace manualmente.") }
  }

  async function saveFeePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !canSetup || !feeSettings) return
    setBusy(true); setError("")
    try {
      await postMethod("save_setup", { property_name: property.name, section: "property",
        request_key: crypto.randomUUID(), expected_modified: feeSettings.modified,
        data: { ...feePolicy, cancellation_fee_value: Number(feePolicy.cancellation_fee_value),
          no_show_fee_value: Number(feePolicy.no_show_fee_value),
          receivable_account: feePolicy.receivable_account || null } })
      await refreshFeeSettings(); setCancelQuote(null)
      setNotice("Política de penalización actualizada para futuras cancelaciones.")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo guardar la política.") }
    finally { setBusy(false) }
  }

  function selectCancellation(booking: ReceptionData["bookings"][number]) {
    setCancelBooking(booking.name); setCancelStatus("Cancelled"); setCancelReason("")
    setCancelQuote(null); setError("")
    setArrivalBooking(""); setArrivalQuote(null)
  }

  async function previewCancellation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !selectedCancelBooking) return
    setBusy(true); setError(""); setCancelQuote(null)
    try {
      const result = await call<FeeQuote>("preview", { property_name: property.name,
        action: "booking_status", data: JSON.stringify({ booking: selectedCancelBooking.name,
          status: cancelStatus }) })
      setCancelQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la penalización.") }
    finally { setBusy(false) }
  }

  async function confirmCancellation() {
    if (!cancelQuote || !selectedCancelBooking || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ fee_receivable?: string; fee_invoice?: string }>(property.name,
        "booking_status", { booking: selectedCancelBooking.name,
          modified: selectedCancelBooking.modified, status: cancelQuote.status,
          reason: cancelReason.trim(), fee_acceptance: cancelQuote.acceptance },
        cancelQuote.requestKey)
      await refresh(); onChanged?.(); setCancelBooking(""); setCancelReason(""); setCancelQuote(null)
      setNotice(`${cancelQuote.status === "No Show" ? "No presentación" : "Cancelación"} registrada.` +
        (result.fee_receivable || result.fee_invoice ?
          ` Cargo ${result.fee_receivable || result.fee_invoice} contabilizado.` : ""))
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo actualizar la reserva. Revise el cargo de nuevo.") }
    finally { setBusy(false) }
  }

  async function previewArrival(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setError(""); setArrivalQuote(null)
    try {
      const result = await call<ArrivalQuote>("preview", { property_name: property.name,
        action: "check_in", data: JSON.stringify({ booking: arrivalBooking,
          allocation: arrivalAllocation }) })
      setArrivalQuote({ ...result, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar la entrada.") }
    finally { setBusy(false) }
  }

  async function checkIn() {
    if (!arrivalQuote || !selectedBooking || busy) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ stay: string; folio: string }>(property.name, "check_in",
        { booking: selectedBooking.name, modified: selectedBooking.modified,
          allocation: arrivalAllocation, room: arrivalRoom, guest: arrivalGuest,
          timing_acceptance: arrivalQuote.acceptance }, arrivalQuote.requestKey)
      setArrivalQuote(null); setArrivalBooking(""); setArrivalAllocation("")
      await refresh(); onChanged?.(); setNotice(`Entrada ${result.stay} registrada. Cuenta de estancia ${result.folio}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la entrada.") }
    finally { setBusy(false) }
  }

  function selectMove(stay: ReceptionData["stays"][number]) {
    const folio = data?.folios.find((row) => row.customer === stay.customer &&
      (row.stay === stay.name || !row.stay && !!stay.booking && row.booking === stay.booking))
    setMoveStay(stay.name); setMoveRoom(""); setMoveFolio(folio?.name || "")
    setMoveReason(""); setMoveQuote(null); setError("")
    setExtendStay(""); setExtendQuote(null)
    navigate("/reception?section=stay-move")
  }

  async function previewMove(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !selectedMoveStay) return
    setBusy(true); setError(""); setMoveQuote(null)
    const request: MoveRequest = { stay: selectedMoveStay.name, modified: selectedMoveStay.modified,
      room: moveRoom, folio: moveFolio || undefined, reason: moveReason.trim() }
    try {
      const result = await call<MoveQuote>("preview", { property_name: property.name,
        action: "change_room", data: JSON.stringify(request) })
      setMoveQuote({ ...result, request, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo revisar el cambio de habitación.") }
    finally { setBusy(false) }
  }

  async function confirmMove() {
    if (!moveQuote || busy || Number(moveQuote.difference) < 0 && !canApprove ||
        Number(moveQuote.difference) !== 0 && !moveQuote.request.folio) return
    setBusy(true); setError("")
    try {
      const result = await execute<{ room: string }>(property.name, "change_room",
        { ...moveQuote.request, acceptance: moveQuote.acceptance }, moveQuote.requestKey)
      await refresh(); setMoveStay(""); setMoveRoom(""); setMoveFolio("")
      setMoveReason(""); setMoveQuote(null)
      setNotice(`Cambio a habitación ${roomLabel(result.room)} registrado. La anterior quedó pendiente de limpieza.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cambiar la habitación. Revise la cotización de nuevo.") }
    finally { setBusy(false) }
  }

  function selectExtension(stay: ReceptionData["stays"][number]) {
    const folio = data?.folios.find((row) => row.customer === stay.customer &&
      (row.stay === stay.name || !row.stay && !!stay.booking && row.booking === stay.booking))
    setExtendStay(stay.name); setExtendEnd(stay.ends_at_local.replace(" ", "T"))
    setExtendFolio(folio?.name || ""); setExtendReason(""); setExtendQuote(null)
    setMoveStay(""); setMoveQuote(null); setError("")
    navigate("/reception?section=stay-extend")
  }

  async function previewExtension(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !selectedExtendStay) return
    setBusy(true); setError(""); setExtendQuote(null)
    const request: ExtensionRequest = { stay: selectedExtendStay.name,
      modified: selectedExtendStay.modified, ends_at: extendEnd,
      folio: extendFolio, reason: extendReason.trim() }
    try {
      const result = await call<ExtensionQuote>("preview", { property_name: property.name,
        action: "extend", data: JSON.stringify(request) })
      setExtendQuote({ ...result, request, requestKey: crypto.randomUUID() })
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cotizar la extensión.") }
    finally { setBusy(false) }
  }

  async function confirmExtension() {
    if (!extendQuote || busy) return
    setBusy(true); setError("")
    try {
      await execute(property.name, "extend", { ...extendQuote.request,
        acceptance: extendQuote.acceptance }, extendQuote.requestKey)
      await refresh(); setExtendStay(""); setExtendEnd(""); setExtendFolio("")
      setExtendReason(""); setExtendQuote(null)
      setNotice(`Estancia extendida. Nuevo total aceptado: ${property.currency} ${extendQuote.amount}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo extender la estancia. Revise la cotización de nuevo.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    {!embeddedSection && <div><h1 className="text-3xl font-semibold">Recepción</h1><p className="mt-1 text-sm text-muted-foreground">Registre huéspedes, revise tarifas, confirme reservas y abra estancias.</p></div>}
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
    {!data ? <Skeleton className="h-96 w-full" /> : <>
      <div className="border-b border-border pb-3"><h2 className="text-xl font-semibold">{embeddedSection === "arrivals" ?
        initialBooking?.action === "cancel" ? "Cancelar reserva" : "Registrar entrada" : section.label}</h2>
        <p className="text-sm text-muted-foreground">{embeddedSection === "arrivals" ?
          initialBooking?.action === "cancel" ? "Revise la política y el motivo antes de confirmar." :
            "Revise la asignación y los cargos antes de confirmar." : section.description}</p></div>
      {section.id === "arrivals" && !embeddedSection && <PortalRequests key={property.name} property={property} parties={data.parties}
        guests={data.guests} categories={data.categories} onChanged={refresh} />}
      {section.id === "folios" && <FolioWork key={`folios-${property.name}`} property={property} stays={data.stays}
        folios={data.folios} parties={data.parties} onChanged={refresh} />}
      {section.id === "guest-new" && <Card><CardHeader><CardTitle>Nuevo huésped</CardTitle><CardDescription>Puede crear un pagador nuevo o asociarlo a uno existente del establecimiento.</CardDescription></CardHeader><CardContent>
          <form onSubmit={createGuest} className="space-y-3">
            <label className="block space-y-1 text-sm"><span>Nombre completo</span><Input required maxLength={140} value={guestName} onChange={(event) => setGuestName(event.target.value)} /></label>
            <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Tipo de identificación</span><Input maxLength={140} value={guestIdentityType} onChange={(event) => setGuestIdentityType(event.target.value)} /></label><label className="space-y-1 text-sm"><span>Número de identificación</span><Input required={data.guest_id_required} maxLength={140} value={guestIdentity} onChange={(event) => setGuestIdentity(event.target.value)} /></label></div>
            <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Correo</span><Input type="email" maxLength={140} value={guestEmail} onChange={(event) => setGuestEmail(event.target.value)} /></label><label className="space-y-1 text-sm"><span>Teléfono</span><Input maxLength={140} value={guestPhone} onChange={(event) => setGuestPhone(event.target.value)} /></label></div>
            <label className="block space-y-1 text-sm"><span>Nacionalidad</span><Input maxLength={140} value={guestNationality} onChange={(event) => setGuestNationality(event.target.value)} /></label>
            <label className="block space-y-1 text-sm"><span>Pagador existente (opcional)</span><select value={guestParty} onChange={(event) => setGuestParty(event.target.value)} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Crear pagador con el nombre del huésped</option>{data.parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label>
            <Button disabled={busy}>Registrar huésped</Button>
          </form>
        </CardContent></Card>}
      {section.id === "reservation" && <Card><CardHeader><CardTitle>{editingBooking ? `Modificar reserva ${editingBooking.name}` : "Nueva reserva"}</CardTitle><CardDescription>La cotización comprueba tarifa y disponibilidad antes de confirmar.</CardDescription></CardHeader><CardContent className="space-y-3">
          <form id="reservation-form" onSubmit={previewReservation} className="space-y-3">
            {editingBooking && <p className="rounded-md bg-secondary p-3 text-sm">Los cambios se permiten antes de la primera entrada. Revise de nuevo la tarifa y las habitaciones.</p>}
            <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Huésped principal</span><select required value={guest} onChange={(event) => { const value = event.target.value; setGuest(value); setPayer(data.guests.find((row) => row.name === value)?.customer || ""); setRooms((current) => current.map((row) => ({ ...row, rate: "" }))); setReservationQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione un huésped</option>{data.guests.map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}</select></label><label className="space-y-1 text-sm"><span>Pagador</span><select required value={payer} onChange={(event) => { setPayer(event.target.value); setRooms((current) => current.map((row) => ({ ...row, rate: "" }))); setReservationQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione un pagador</option>{data.parties.map((row) => <option key={row.name} value={row.name}>{row.party_name}</option>)}</select></label></div>
            <div className="grid gap-3 sm:grid-cols-3"><label className="space-y-1 text-sm"><span>Modalidad</span><select value={mode} onChange={(event) => { setMode(event.target.value); setRooms((current) => current.map((row) => ({ ...row, rate: "" }))); setReservationQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2">{(property.mode === "Mixed" ? ["Hotel", "Por tiempo", "Day Pass"] : property.mode === "Por tiempo" ? ["Por tiempo", "Day Pass"] : ["Hotel"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="space-y-1 text-sm"><span>Entrada prevista</span><Input required type="datetime-local" value={startsAt} onChange={(event) => { setStartsAt(event.target.value); setReservationQuote(null) }} /></label><label className="space-y-1 text-sm"><span>Salida prevista</span><Input required type="datetime-local" value={endsAt} onChange={(event) => { setEndsAt(event.target.value); setReservationQuote(null) }} /></label></div>
            <label className="block space-y-1 text-sm"><span>Agencia de viajes (opcional)</span><select value={travelAgent} onChange={(event) => { setTravelAgent(event.target.value); setReservationQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Reserva directa</option>{data.agents.map((row) => <option key={row.name} value={row.name}>{row.agent_name} · comisión {row.commission_pct}%</option>)}</select></label>
            {!editingBooking && <div className="space-y-2 rounded-lg border border-border p-3"><strong className="text-sm">Experiencias de la reserva</strong>{experienceRows.map((row) => <div key={row.id} className="flex flex-wrap items-end gap-2"><label className="min-w-48 flex-1 space-y-1 text-sm"><span>Experiencia</span><select required value={row.experience} onChange={(event) => { setExperienceRows((current) => current.map((entry) => entry.id === row.id ? { ...entry, experience: event.target.value } : entry)); setReservationQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione experiencia</option>{data.experiences.filter((entry) => entry.name === row.experience || !experienceRows.some((chosen) => chosen.experience === entry.name)).map((entry) => <option key={entry.name} value={entry.name}>{entry.experience_name}</option>)}</select></label><label className="w-28 space-y-1 text-sm"><span>Cantidad</span><Input required type="number" min="1" max="1000" step="1" value={row.quantity} onChange={(event) => { setExperienceRows((current) => current.map((entry) => entry.id === row.id ? { ...entry, quantity: event.target.value } : entry)); setReservationQuote(null) }} /></label><Button type="button" variant="outline" onClick={() => { setExperienceRows((current) => current.filter((entry) => entry.id !== row.id)); setReservationQuote(null) }}>Quitar</Button></div>)}<Button type="button" variant="outline" disabled={experienceRows.length >= 20 || experienceRows.length >= data.experiences.length} onClick={() => { setExperienceRows((current) => [...current, { id: crypto.randomUUID(), experience: "", quantity: "1" }]); setReservationQuote(null) }}>Añadir experiencia</Button></div>}
            <div className="space-y-3">{rooms.map((entry, index) => <div key={entry.id} className="rounded-lg border border-border p-3"><div className="mb-3 flex items-center justify-between"><strong className="text-sm">Habitación {index + 1}</strong>{rooms.length > 1 && <Button type="button" variant="outline" size="sm" onClick={() => { setRooms((current) => current.filter((row) => row.id !== entry.id)); setReservationQuote(null) }}>Quitar</Button>}</div><div className="grid gap-3 sm:grid-cols-5"><label className="space-y-1 text-sm"><span>Categoría</span><select required value={entry.category} onChange={(event) => updateRoom(entry.id, { category: event.target.value, room: "", rate: "", extraBeds: "0" })} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione categoría</option>{data.categories.map((row) => <option key={row.name} value={row.name}>{row.category_name}</option>)}</select></label><label className="space-y-1 text-sm"><span>Habitación</span><select value={entry.room} onChange={(event) => updateRoom(entry.id, { room: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Asignar después</option>{matchingRooms(entry.category).filter((row) => row.name === entry.room || !rooms.some((other) => other.id !== entry.id && other.room === row.name)).map((row) => <option key={row.name} value={row.name}>{row.room_number} · {row.cleaning_status}</option>)}</select></label><label className="space-y-1 text-sm"><span>Personas</span><Input required type="number" min="1" max={data.categories.find((row) => row.name === entry.category)?.capacity || 20} value={entry.people} onChange={(event) => updateRoom(entry.id, { people: event.target.value })} /></label><label className="space-y-1 text-sm"><span>Camas extra</span><Input required type="number" min="0" max={data.categories.find((row) => row.name === entry.category)?.max_extra_beds || 0} value={entry.extraBeds} onChange={(event) => updateRoom(entry.id, { extraBeds: event.target.value })} /></label><label className="space-y-1 text-sm"><span>Tarifa</span><select value={entry.rate} onChange={(event) => updateRoom(entry.id, { rate: event.target.value })} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Automática</option>{matchingRates(entry.category).map((row) => <option key={row.name} value={row.name}>{row.title} · {row.currency} {row.amount}</option>)}</select></label></div></div>)}<Button type="button" variant="outline" disabled={rooms.length >= 20} onClick={() => { setRooms((current) => [...current, newRoom()]); setReservationQuote(null) }}>Añadir habitación</Button></div>
            {editingBooking && <label className="block space-y-1 text-sm"><span>Motivo de modificación</span><Input required maxLength={500} value={editingReason} onChange={(event) => { setEditingReason(event.target.value); setReservationQuote(null) }} /></label>}
            <div className="flex flex-wrap gap-2"><Button disabled={busy || !data.categories.length}>Revisar tarifa y disponibilidad</Button>{editingBooking && <Button type="button" variant="outline" onClick={stopEditing}>Dejar de editar</Button>}</div>
          </form>
          {reservationQuote && <div className="space-y-2 rounded-lg border border-border p-3 text-sm"><p><strong>Tarifa de {reservationQuote.lines.length} habitación(es):</strong> {reservationQuote.currency} {reservationQuote.amount}</p><p><strong>Total estimado:</strong> {reservationQuote.currency} {reservationQuote.estimated_total}</p>{reservationQuote.agent.travel_agent && <p>Agencia: {data.agents.find((row) => row.name === reservationQuote.agent.travel_agent)?.agent_name || reservationQuote.agent.travel_agent} · comisión estimada {reservationQuote.currency} {reservationQuote.agent.agent_commission_estimate} ({reservationQuote.agent.agent_commission_pct}%)</p>}{reservationQuote.experiences.map((row) => <p key={row.experience}>Experiencia {row.name} × {row.quantity}: {reservationQuote.currency} {row.total_amount || row.amount}{row.tax_amount && ` · impuesto ${row.tax_amount}`}</p>)}{reservationQuote.lines.map((line, index) => <p key={index}><strong>Habitación {index + 1}: {reservationQuote.currency} {line.amount}</strong> · {line.rules.title} · {line.explanation.join(" · ")}</p>)}<div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => confirmReservation(false)}>{reservationQuote.request.booking ? "Guardar modificación" : "Confirmar reserva"}</Button>{!reservationQuote.request.booking && reservationQuote.request.rooms.length === 1 && reservationQuote.request.rooms[0].room && <Button disabled={busy} variant="outline" onClick={() => confirmReservation(true)}>Entrada directa</Button>}</div></div>}
        </CardContent></Card>}
      {section.id === "guests" && canManageGuests && <GuestProfiles key={property.name} property={property} provider={provider} onChanged={refresh} />}
      {section.id === "policies" && canSetup && feeSettings && <Card>
        <CardHeader><CardTitle>Penalizaciones de reservas</CardTitle><CardDescription>Configure los importes para futuras cancelaciones y no presentaciones. Asigne el producto de penalización y su perfil tributario en Productos PMS.</CardDescription></CardHeader>
        <CardContent><form onSubmit={saveFeePolicy} className="grid gap-3 sm:grid-cols-2">
          {(["cancellation", "no_show"] as const).map((kind) => {
            const modeField = `${kind}_fee_mode` as const
            const valueField = `${kind}_fee_value` as const
            return <div key={kind} className="space-y-2 rounded-lg border border-border p-3">
              <strong className="text-sm">{kind === "cancellation" ? "Cancelación" : "No presentación"}</strong>
              <select value={feePolicy[modeField]} onChange={(event) => setFeePolicy((current) => ({ ...current,
                [modeField]: event.target.value as FeeMode }))} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm">
                <option value="None">Sin penalización</option><option value="Fixed">Importe fijo</option>
                <option value="Percent">Porcentaje de la reserva</option><option value="First Night">Primera noche o bloque</option>
              </select>
              {(feePolicy[modeField] === "Fixed" || feePolicy[modeField] === "Percent") &&
                <Input required type="number" min="0" max={feePolicy[modeField] === "Percent" ? "100" : undefined}
                  step="0.01" value={feePolicy[valueField]} onChange={(event) => setFeePolicy((current) => ({
                    ...current, [valueField]: event.target.value }))}
                  placeholder={feePolicy[modeField] === "Percent" ? "Porcentaje" : `Importe en ${property.currency}`} />}
            </div>
          })}
          <label className="space-y-1 text-sm sm:col-span-2"><span>Cuenta por cobrar de penalizaciones</span>
            <select value={feePolicy.receivable_account} onChange={(event) => setFeePolicy((current) => ({
              ...current, receivable_account: event.target.value }))} className="h-9 w-full rounded-md border border-border bg-white px-2">
              <option value="">Sin configurar</option>{feeSettings.receivable_accounts.map((row) =>
                <option key={row.name} value={row.name}>{row.account_code} · {row.account_name}</option>)}
            </select>
          </label>
          <p className="text-xs text-muted-foreground sm:col-span-2">Producto: {feeSettings.penalty_item || "sin asignar"}. Si la penalización es mayor que cero, necesita producto activo, perfil tributario y cuenta por cobrar.</p>
          <Button disabled={busy} className="sm:col-span-2">Guardar política</Button>
        </form></CardContent>
      </Card>}
      {section.id === "arrivals" && <Card id="reception-arrivals"><CardHeader><CardTitle>{embeddedSection ?
        initialBooking?.action === "cancel" ? "Revisar cancelación" : "Registrar entrada" : "Llegadas pendientes"}</CardTitle>
        <CardDescription>{embeddedSection ? initialBooking?.action === "cancel" ?
          "Calcule la penalización antes de registrar la cancelación o no presentación." :
          "Revise la asignación, el huésped y los cargos antes de confirmar." :
          "Confirme retenciones y registre cada habitación de una reserva."}</CardDescription></CardHeader><CardContent className="space-y-3">
        {!embeddedSection && data.bookings.filter((row) => data.allocations.some((item) => item.booking === row.name)).map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3 text-sm"><span><strong>{row.name}</strong> · {guestLabel(row.guest)} · {payerLabel(row.customer)}<span className="block text-muted-foreground">{row.starts_at_local} → {row.ends_at_local} · {row.status} · {data.currency} {row.amount} · {data.allocations.filter((item) => item.booking === row.name).length} habitación(es) pendientes</span></span>{row.status === "Hold" ? <Button type="button" variant="outline" disabled={busy} onClick={() => confirmHold(row)}>Confirmar retención</Button> : canStay && <Button type="button" variant="outline" disabled={busy} onClick={() => selectArrival(row)}>Preparar entrada</Button>}{row.modifiable && <Button type="button" variant="outline" disabled={busy} onClick={() => editBooking(row)}>Modificar</Button>}{row.status !== "Checked In" && <Button type="button" variant="outline" disabled={busy} onClick={() => selectCancellation(row)}>Cancelar / no presentación</Button>}</div>)}
        {embeddedSection && initialBooking && !selectedBooking && !error && <Skeleton className="h-24 rounded-lg" />}
        {!embeddedSection && data.portal_enabled && data.bookings.some((row) => row.status === "Confirmed" || row.status === "Checked In") &&
          <div className="space-y-2 rounded-lg border border-border p-3"><p className="text-sm font-semibold">Enlaces de confirmación</p><p className="text-xs text-muted-foreground">El enlace firmado dura siete días. Compártalo con el huésped correspondiente.</p><div className="flex flex-wrap gap-2">{data.bookings.filter((row) => row.status === "Confirmed" || row.status === "Checked In").map((row) => <Button key={row.name} type="button" variant="outline" size="sm" disabled={busy} onClick={() => void prepareConfirmationLink(row.name)}>Preparar enlace · {row.name}</Button>)}</div>
            {confirmationLink && <div className="flex flex-wrap gap-2"><Input readOnly aria-label={`Enlace de confirmación de ${confirmationLink.booking}`} value={confirmationLink.url} onFocus={(event) => event.target.select()} className="min-w-64 flex-1" /><Button type="button" variant="outline" onClick={() => void copyConfirmationLink()}>Copiar</Button><a className="inline-flex h-9 items-center rounded-md border border-border px-3 text-sm hover:bg-secondary" href={confirmationLink.url} target="_blank" rel="noopener noreferrer">Abrir</a></div>}
          </div>}
        {!data.allocations.length && <p className="text-sm text-muted-foreground">No hay llegadas pendientes.</p>}
        {selectedCancelBooking && <form onSubmit={previewCancellation} className="space-y-3 rounded-lg border border-border p-3">
          <p className="text-sm font-semibold">Reserva {selectedCancelBooking.name}</p>
          <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Acción</span>
            <select value={cancelStatus} onChange={(event) => { setCancelStatus(event.target.value as "Cancelled" | "No Show"); setCancelQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="Cancelled">Cancelar reserva</option><option value="No Show">No presentación</option></select>
          </label><label className="space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={cancelReason} onChange={(event) => { setCancelReason(event.target.value); setCancelQuote(null) }} /></label></div>
          <div className="flex flex-wrap gap-2"><Button disabled={busy}>Revisar penalización</Button><Button type="button" variant="outline" onClick={() => { setCancelBooking(""); setCancelQuote(null) }}>Volver</Button></div>
          {cancelQuote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p><strong>Cargo: {cancelQuote.currency} {cancelQuote.total_amount || cancelQuote.amount}</strong>{cancelQuote.total_amount && <> · Base {cancelQuote.net_amount} · Impuesto {cancelQuote.tax_amount}</>}</p><p>{cancelQuote.mode === "None" ? "Sin penalización" : `Política: ${cancelQuote.mode}`}. El cargo se contabilizará al confirmar{provider === "pms" ? " y podrá facturarse desde Facturación PMS" : " en ERPNext"}.</p><Button type="button" disabled={busy} onClick={() => void confirmCancellation()}>Confirmar {cancelQuote.status === "No Show" ? "no presentación" : "cancelación"}</Button></div>}
        </form>}
        {selectedBooking && <form onSubmit={previewArrival} className="space-y-3 rounded-lg border border-border p-3"><p className="text-sm font-semibold">Entrada de {selectedBooking.name}</p><div className="grid gap-3 sm:grid-cols-3"><label className="space-y-1 text-sm"><span>Asignación</span><select required value={arrivalAllocation} onChange={(event) => { const value = event.target.value; setArrivalAllocation(value); setArrivalRoom(data.allocations.find((row) => row.name === value)?.room || ""); setArrivalQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2">{arrivalAllocations.map((row, index) => <option key={row.name} value={row.name}>{index + 1}. {data.categories.find((item) => item.name === row.category)?.category_name} · {roomLabel(row.room)}</option>)}</select></label><label className="space-y-1 text-sm"><span>Habitación</span><select required value={arrivalRoom} onChange={(event) => { setArrivalRoom(event.target.value); setArrivalQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione habitación</option>{arrivalRooms.map((row) => <option key={row.name} value={row.name}>{row.room_number} · {row.cleaning_status}</option>)}</select></label><label className="space-y-1 text-sm"><span>Huésped principal</span><select required value={arrivalGuest} onChange={(event) => { setArrivalGuest(event.target.value); setArrivalQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione huésped</option>{data.guests.map((row) => <option key={row.name} value={row.name}>{row.full_name}</option>)}</select></label></div><Button disabled={busy}>Revisar entrada</Button>{arrivalQuote && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-secondary p-3 text-sm"><span>Cargos de horario: entrada {data.currency} {arrivalQuote.early} · salida {data.currency} {arrivalQuote.late}</span><Button type="button" disabled={busy} onClick={checkIn}>Registrar entrada</Button></div>}</form>}
      </CardContent></Card>}
      {(["stays", "stay-extend", "stay-move", "stay-companions"] as string[]).includes(section.id) && <Card>
        <CardHeader><CardTitle>{section.id === "stays" ? "Estancias activas" : `Seleccione una estancia para ${section.label.toLowerCase()}`}</CardTitle></CardHeader>
        <CardContent className="space-y-2">{data.stays.map((row) => <div key={row.name} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 text-sm">
          <span><strong>Habitación {roomLabel(row.room)}</strong> · {guestLabel(row.guest)}<span className="block text-muted-foreground">{row.name} · {row.starts_at_local} → {row.ends_at_local}</span></span>
          <div className="flex flex-wrap gap-2">
            {canStay && (section.id === "stays" || section.id === "stay-extend") && <Button type="button" variant="outline" disabled={busy} onClick={() => selectExtension(row)}>Extender estancia</Button>}
            {canStay && (section.id === "stays" || section.id === "stay-move") && <Button type="button" variant="outline" disabled={busy} onClick={() => selectMove(row)}>Cambiar habitación</Button>}
            {canManageGuests && (section.id === "stays" || section.id === "stay-companions") && <Button type="button" variant="outline" disabled={busy} onClick={() => openCompanions(row)}>Acompañantes</Button>}
            {section.id === "stays" && provider === "pms" && <Button asChild variant="outline"><Link to="/folios">Ver cuentas</Link></Button>}
          </div>
        </div>)}{!data.stays.length && <p className="text-sm text-muted-foreground">No hay estancias activas.</p>}</CardContent>
      </Card>}
      {section.id === "stay-companions" && canManageGuests && companionStay && <Card><CardHeader><CardTitle>Acompañantes de {companionStay}</CardTitle><CardDescription>La ocupación aceptada incluye al huésped principal. Registre a cada acompañante antes de guardar.</CardDescription></CardHeader><CardContent className="space-y-4">
        {!companionPage ? <Skeleton className="h-24 rounded-lg" /> : <>
          <p className="text-sm">Huésped principal: <strong>{guestLabel(companionPage.principal)}</strong> · Ocupación: {companionSelected.length + 1} de {companionPage.capacity}</p>
          {companionPage.guest_id_required && <p className="text-xs text-muted-foreground">Cada acompañante debe tener identificación registrada.</p>}
          <div className="flex flex-wrap gap-2">{companionSelected.map((guest) => <span key={guest.name} className="inline-flex items-center gap-2 rounded-md bg-secondary px-2 py-1 text-sm">{guest.full_name}<Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setCompanionSelected((current) => current.filter((row) => row.name !== guest.name))}>Quitar</Button></span>)}{!companionSelected.length && <span className="text-sm text-muted-foreground">Sin acompañantes.</span>}</div>
          <form onSubmit={(event) => { event.preventDefault(); setCompanionOffset(0); setCompanionSearch(companionSearchInput.trim()) }} className="flex flex-wrap gap-2"><Input maxLength={100} placeholder="Buscar huésped por nombre o código" value={companionSearchInput} onChange={(event) => setCompanionSearchInput(event.target.value)} className="min-w-64 flex-1" /><Button type="submit" variant="outline">Buscar</Button></form>
          <div className="space-y-2">{companionPage.candidates.map((guest) => { const added = companionSelected.some((row) => row.name === guest.name); const needsIdentity = companionPage.guest_id_required && !guest.has_identity; return <div key={guest.name} className="flex items-center justify-between gap-2 border-b border-border pb-2 text-sm"><span>{guest.full_name} · {guest.name}{needsIdentity && <span className="block text-xs text-destructive">Falta identificación</span>}</span><Button type="button" size="sm" variant="outline" disabled={busy || added || needsIdentity || companionSelected.length + 1 >= companionPage.capacity} onClick={() => setCompanionSelected((current) => [...current, guest])}>{added ? "Agregado" : "Agregar"}</Button></div> })}{!companionPage.candidates.length && <p className="text-sm text-muted-foreground">No se encontraron huéspedes.</p>}</div>
          {companionPage.total > 25 && <div className="flex items-center justify-between gap-2 text-sm"><span>{companionPage.offset + 1}–{companionPage.offset + companionPage.candidates.length} de {companionPage.total}</span><div className="flex gap-2"><Button type="button" variant="outline" disabled={companionOffset === 0} onClick={() => setCompanionOffset(Math.max(0, companionOffset - 25))}>Anterior</Button><Button type="button" variant="outline" disabled={!companionPage.has_more} onClick={() => setCompanionOffset(companionOffset + 25)}>Siguiente</Button></div></div>}
          <div className="flex gap-2"><Button type="button" disabled={busy} onClick={() => void saveCompanions()}>Guardar acompañantes</Button><Button type="button" variant="outline" onClick={() => { setCompanionStay(""); setCompanionPage(null) }}>Cancelar</Button></div>
        </>}
      </CardContent></Card>}
      {section.id === "stay-move" && selectedMoveStay && <Card><CardHeader><CardTitle>Cambio de habitación</CardTitle><CardDescription>Revise disponibilidad y diferencia de tarifa antes de confirmar. La habitación anterior pasará a limpieza.</CardDescription></CardHeader><CardContent><form onSubmit={previewMove} className="space-y-3"><p className="text-sm">Estancia {selectedMoveStay.name} · Habitación actual {roomLabel(selectedMoveStay.room)}</p><div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Habitación de destino</span><select required value={moveRoom} onChange={(event) => { setMoveRoom(event.target.value); setMoveQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione habitación limpia</option>{moveCandidates.map((row) => <option key={row.name} value={row.name}>{row.room_number} · {data.categories.find((item) => item.name === row.category)?.category_name}</option>)}</select></label><label className="space-y-1 text-sm"><span>Cuenta para diferencia de tarifa</span><select value={moveFolio} onChange={(event) => { setMoveFolio(event.target.value); setMoveQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Sin cuenta seleccionada</option>{moveFolios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name}</option>)}</select></label></div><label className="block space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={moveReason} onChange={(event) => { setMoveReason(event.target.value); setMoveQuote(null) }} /></label><div className="flex flex-wrap gap-2"><Button disabled={busy || !moveRoom}>Revisar cambio</Button><Button type="button" variant="outline" onClick={() => { setMoveStay(""); setMoveQuote(null) }}>Cancelar</Button></div>{moveQuote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p><strong>{moveQuote.quote.rules.title}</strong> · Importe de destino {property.currency} {moveQuote.quote.amount}</p><p>Diferencia {property.currency} {moveQuote.difference}. {moveQuote.explanation}</p>{Number(moveQuote.difference) < 0 && !canApprove && <p role="alert">Un crédito de tarifa requiere autorización de Gerencia.</p>}{Number(moveQuote.difference) !== 0 && !moveQuote.request.folio && <p role="alert">Seleccione una cuenta abierta para registrar la diferencia.</p>}<p className="text-xs text-muted-foreground">Cotización válida hasta {moveQuote.valid_until}. Si cambia el importe, revise nuevamente.</p><Button type="button" disabled={busy || Number(moveQuote.difference) < 0 && !canApprove || Number(moveQuote.difference) !== 0 && !moveQuote.request.folio} onClick={() => void confirmMove()}>Confirmar cambio</Button></div>}</form></CardContent></Card>}
      {section.id === "stay-extend" && selectedExtendStay && <Card>
        <CardHeader><CardTitle>Extender estancia</CardTitle><CardDescription>Cotice el tiempo adicional y seleccione la cuenta que recibirá el cargo.</CardDescription></CardHeader>
        <CardContent><form onSubmit={previewExtension} className="space-y-3">
          <p className="text-sm">Estancia {selectedExtendStay.name} · Salida actual {selectedExtendStay.ends_at_local}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm"><span>Nueva salida</span><Input required type="datetime-local" value={extendEnd} onChange={(event) => { setExtendEnd(event.target.value); setExtendQuote(null) }} /></label>
            <label className="space-y-1 text-sm"><span>Cuenta abierta</span><select required value={extendFolio} onChange={(event) => { setExtendFolio(event.target.value); setExtendQuote(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{extensionFolios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.name}</option>)}</select></label>
          </div>
          <label className="block space-y-1 text-sm"><span>Motivo</span><Input required maxLength={500} value={extendReason} onChange={(event) => { setExtendReason(event.target.value); setExtendQuote(null) }} /></label>
          <div className="flex flex-wrap gap-2"><Button disabled={busy || !extendFolio}>Revisar extensión</Button><Button type="button" variant="outline" onClick={() => { setExtendStay(""); setExtendQuote(null) }}>Cancelar</Button></div>
          {extendQuote && <div className="space-y-2 rounded-lg bg-secondary p-3 text-sm"><p>Tiempo adicional: {extendQuote.service_start} → {extendQuote.service_end}</p><p><strong>Cargo adicional {extendQuote.currency} {extendQuote.difference}</strong> · Nuevo total aceptado {extendQuote.currency} {extendQuote.amount}</p>{extendQuote.explanation.map((line, index) => <p key={index}>{line}</p>)}<Button type="button" disabled={busy} onClick={() => void confirmExtension()}>Confirmar extensión</Button></div>}
        </form></CardContent>
      </Card>}
    </>}
  </div>
}
