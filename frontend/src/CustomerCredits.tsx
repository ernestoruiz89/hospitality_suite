import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { call, execute, type Property } from "./api"
import { Guarantees, type GuaranteeData } from "./Guarantees"
import { AdvanceRefunds, type AdvanceRefundData } from "./AdvanceRefunds"
import { AppliedRefunds, type AppliedRefundData } from "./AppliedRefunds"
import { availableCustomerCreditSections } from "./CustomerCreditSections"

type Snapshot = GuaranteeData & AdvanceRefundData & AppliedRefundData & {
  currency: string
  advance_page: { search: string; offset: number; has_more: boolean }
  guarantee_page: { search: string; offset: number; has_more: boolean }
  invoice_page: { search: string; offset: number; has_more: boolean }
  folio_page: { search: string; offset: number; has_more: boolean }
  advances: { name: string; customer: string; reference: string; source_currency: string; available: string }[]
  invoices: { name: string; customer: string; posting_date: string; currency: string; outstanding: string; direct: boolean }[]
  folios: { name: string; label: string; customer: string; stay: string | null;
    booking: string | null; currency: string; status: string;
    balance: { pending: string; scheduled: string; outstanding: string } }[]
  advance_bookings: { name: string; customer: string; status: string; starts_at: string }[]
  advance_stays: { name: string; booking: string | null; customer: string;
    status: string; room: string | null }[]
  methods: { name: string; mode_of_payment: string; currency: string; is_cash: boolean; reference_required: boolean }[]
  shifts: { name: string; cashier: string; currency: string; status: string;
    modified: string; expected: Record<string, string> }[]
}
type PaymentQuote = { amount: string; currency: string; property_amount: string;
  base_currency: string;
  property_currency: string; exchange_rate: string; acceptance: string;
  invoice?: { name: string; outstanding: string };
  folio?: { name: string; customer: string; outstanding: string;
    pending: string; scheduled: string };
  origin?: { stay: string | null; booking: string | null; customer: string };
  refund?: { invoice: string; allocated: string; credit_outstanding: string;
    party_amount: string; party_currency: string; exchange_difference: string } }
type CreditItem = { invoice_item: string; item_name: string; quantity: string; amount: string }
type CreditQuote = { invoice: string; currency: string; total: string;
  items: CreditItem[]; acceptance: string }
type DirectInvoice = { name: string; customer: string; posting_date: string }
type DirectNote = { name: string; customer: string; invoice: string; available: string }
type DirectPayment = { name: string; customer: string; invoice: string; amount: string; currency: string; method: string }
type DirectPage<T> = { rows: T[]; offset: number; has_more: boolean }
const FUNDS_PAGE_LENGTH = 50
const RECEIVABLE_PAGE_LENGTH = 50
const DIRECT_PAGE_LENGTH = 50
function directPage<T>(property: string, mode: "invoices" | "notes" | "payments",
  search: string, offset: number, creditNote = "") {
  return call<DirectPage<T>>("erp_direct_credit_search", {
    property_name: property, mode, search, offset: String(offset),
    page_length: String(DIRECT_PAGE_LENGTH), credit_note: creditNote,
  })
}

export function CustomerCredits({ property, canApprove }: {
  property: Property; canApprove: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedFolio = searchParams.get("folio") || ""
  const requestedInvoice = searchParams.get("invoice") || ""
  const visibleSections = availableCustomerCreditSections(canApprove)
  const requestedSection = searchParams.get("section")
  const legacySection = requestedSection === "guarantees" ? "receive-guarantee" :
    requestedSection === "corrections" ? "credit-note" : requestedSection
  const sectionInfo = visibleSections.find((item) => item.id === legacySection) || visibleSections[0]
  const section = sectionInfo.id
  useEffect(() => {
    if (!requestedSection || requestedSection === section) return
    const next = new URLSearchParams(searchParams)
    next.set("section", section)
    setSearchParams(next, { replace: true })
  }, [requestedSection, section, searchParams, setSearchParams])
  const [data, setData] = useState<Snapshot | null>(null)
  const [invoice, setInvoice] = useState("")
  const [advance, setAdvance] = useState("")
  const [amount, setAmount] = useState("")
  const [applyKey, setApplyKey] = useState("")
  const [collectInvoice, setCollectInvoice] = useState("")
  const [collectMethod, setCollectMethod] = useState("")
  const [collectShift, setCollectShift] = useState("")
  const [collectAmount, setCollectAmount] = useState("")
  const [collectReference, setCollectReference] = useState("")
  const [collectTendered, setCollectTendered] = useState("")
  const [collectQuote, setCollectQuote] = useState<PaymentQuote | null>(null)
  const [collectKey, setCollectKey] = useState("")
  const [folio, setFolio] = useState("")
  const [folioMethod, setFolioMethod] = useState("")
  const [folioShift, setFolioShift] = useState("")
  const [folioAmount, setFolioAmount] = useState("")
  const [folioTendered, setFolioTendered] = useState("")
  const [folioReference, setFolioReference] = useState("")
  const [folioQuote, setFolioQuote] = useState<PaymentQuote | null>(null)
  const [folioKey, setFolioKey] = useState("")
  const [advanceOrigin, setAdvanceOrigin] = useState("")
  const [advanceMethod, setAdvanceMethod] = useState("")
  const [advanceShift, setAdvanceShift] = useState("")
  const [advanceAmount, setAdvanceAmount] = useState("")
  const [advanceTendered, setAdvanceTendered] = useState("")
  const [advanceReference, setAdvanceReference] = useState("")
  const [advanceQuote, setAdvanceQuote] = useState<PaymentQuote | null>(null)
  const [advanceKey, setAdvanceKey] = useState("")
  const [folioSearch, setFolioSearch] = useState("")
  const appliedFolioSearch = useRef("")
  const appliedRoomFolio = useRef("")
  const appliedRoomInvoice = useRef("")
  const folioOffset = useRef(0)
  const [invoiceSearch, setInvoiceSearch] = useState("")
  const appliedInvoiceSearch = useRef("")
  const invoiceOffset = useRef(0)
  const [advanceSearch, setAdvanceSearch] = useState("")
  const appliedAdvanceSearch = useRef("")
  const advanceOffset = useRef(0)
  const [guaranteeSearch, setGuaranteeSearch] = useState("")
  const appliedGuaranteeSearch = useRef("")
  const guaranteeOffset = useRef(0)
  const [creditInvoice, setCreditInvoice] = useState("")
  const [creditReason, setCreditReason] = useState("")
  const [creditOptions, setCreditOptions] = useState<CreditItem[]>([])
  const [creditItems, setCreditItems] = useState<Record<string, string> | null>(null)
  const [creditQuote, setCreditQuote] = useState<CreditQuote | null>(null)
  const [creditKey, setCreditKey] = useState("")
  const [creditInvoiceSearch, setCreditInvoiceSearch] = useState("")
  const [directInvoicePage, setDirectInvoicePage] = useState<DirectPage<DirectInvoice> | null>(null)
  const appliedCreditInvoiceSearch = useRef("")
  const [refundCredit, setRefundCredit] = useState("")
  const [refundCreditSearch, setRefundCreditSearch] = useState("")
  const [refundSourceSearch, setRefundSourceSearch] = useState("")
  const [directNotePage, setDirectNotePage] = useState<DirectPage<DirectNote> | null>(null)
  const [directPaymentPage, setDirectPaymentPage] = useState<DirectPage<DirectPayment> | null>(null)
  const appliedRefundCreditSearch = useRef("")
  const appliedRefundSourceSearch = useRef("")
  const [refundSource, setRefundSource] = useState("")
  const [refundShift, setRefundShift] = useState("")
  const [refundAmount, setRefundAmount] = useState("")
  const [refundReference, setRefundReference] = useState("")
  const [refundReason, setRefundReason] = useState("")
  const [refundQuote, setRefundQuote] = useState<PaymentQuote | null>(null)
  const [refundKey, setRefundKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const refresh = useCallback(async () => {
    setData(await call<Snapshot>("erp_customer_credits_snapshot", {
      property_name: property.name, folio_search: appliedFolioSearch.current,
      folio_offset: String(folioOffset.current),
      invoice_search: appliedInvoiceSearch.current,
      invoice_offset: String(invoiceOffset.current),
      receivable_page_length: String(RECEIVABLE_PAGE_LENGTH),
      advance_search: appliedAdvanceSearch.current,
      guarantee_search: appliedGuaranteeSearch.current,
      advance_offset: String(advanceOffset.current),
      guarantee_offset: String(guaranteeOffset.current),
      funds_page_length: String(FUNDS_PAGE_LENGTH),
    }))
  }, [property.name])
  useEffect(() => {
    appliedFolioSearch.current = requestedFolio
    appliedRoomFolio.current = ""
    folioOffset.current = 0
    appliedInvoiceSearch.current = requestedInvoice; invoiceOffset.current = 0
    appliedRoomInvoice.current = ""
    appliedAdvanceSearch.current = ""; advanceOffset.current = 0
    appliedGuaranteeSearch.current = ""; guaranteeOffset.current = 0
    setData(null); setInvoice(""); setAdvance(""); setAmount(""); setApplyKey(""); setError(""); setNotice("")
    setCollectInvoice(""); setCollectMethod(""); setCollectShift("")
    setCollectAmount(""); setCollectReference(""); setCollectTendered("")
    setCollectQuote(null); setCollectKey("")
    setFolio(""); setFolioMethod(""); setFolioShift("")
    setFolioAmount(""); setFolioTendered(""); setFolioReference("")
    setFolioQuote(null); setFolioKey("")
    setAdvanceOrigin(""); setAdvanceMethod(""); setAdvanceShift("")
    setAdvanceAmount(""); setAdvanceTendered(""); setAdvanceReference("")
    setAdvanceQuote(null); setAdvanceKey("")
    setFolioSearch(requestedFolio); setInvoiceSearch(requestedInvoice)
    setAdvanceSearch(""); setGuaranteeSearch("")
    setCreditInvoice(""); setCreditReason(""); setCreditOptions([])
    setCreditItems(null); setCreditQuote(null); setCreditKey("")
    setCreditInvoiceSearch(""); setDirectInvoicePage(null)
    appliedCreditInvoiceSearch.current = ""
    setRefundCredit(""); setRefundSource(""); setRefundShift("")
    setRefundAmount(""); setRefundReference(""); setRefundReason("")
    setRefundQuote(null); setRefundKey("")
    setRefundCreditSearch(""); setRefundSourceSearch("")
    setDirectNotePage(null); setDirectPaymentPage(null)
    appliedRefundCreditSearch.current = ""
    appliedRefundSourceSearch.current = ""
    refresh().catch((issue: unknown) => setError(issue instanceof Error ? issue.message : "No se pudieron consultar los créditos."))
  }, [refresh, requestedFolio, requestedInvoice])
  useEffect(() => {
    if (!data || !requestedFolio || section !== "folios" ||
        appliedRoomFolio.current === requestedFolio) return
    const match = data.folios.find((row) => row.name === requestedFolio)
    if (!match) return
    appliedRoomFolio.current = requestedFolio
    setFolio(match.name)
  }, [data, requestedFolio, section])
  useEffect(() => {
    if (!data || !requestedInvoice || section !== "invoices" ||
        appliedRoomInvoice.current === requestedInvoice) return
    const match = data.invoices.find((row) =>
      row.name === requestedInvoice && row.direct)
    if (!match) return
    appliedRoomInvoice.current = requestedInvoice
    setCollectInvoice(match.name)
  }, [data, requestedInvoice, section])
  useEffect(() => {
    if (!canApprove) return
    let active = true
    Promise.all([
      directPage<DirectInvoice>(property.name, "invoices", "", 0),
      directPage<DirectNote>(property.name, "notes", "", 0),
    ]).then(([invoices, notes]) => {
      if (active) { setDirectInvoicePage(invoices); setDirectNotePage(notes) }
    }).catch((issue: unknown) => {
      if (active) setError(issue instanceof Error ? issue.message : "No se pudieron consultar los documentos directos.")
    })
    return () => { active = false }
  }, [property.name, canApprove])
  const selectedInvoice = data?.invoices.find((row) => row.name === invoice)
  const matching = data?.advances.filter((row) => row.customer === selectedInvoice?.customer) || []
  const selectedAdvance = matching.find((row) => row.name === advance)
  const selectedMethod = data?.methods.find((row) => row.name === collectMethod)
  const directInvoices = data?.invoices.filter((row) =>
    row.direct && (!requestedInvoice || row.name === requestedInvoice)) || []
  const selectedFolio = data?.folios.find((row) => row.name === folio &&
    (!requestedFolio || row.name === requestedFolio))
  const availableFolios = data?.folios.filter((row) =>
    !requestedFolio || row.name === requestedFolio) || []
  const selectedFolioMethod = data?.methods.find((row) => row.name === folioMethod)
  const advanceTargets = [
    ...(data?.advance_bookings.map((row) => ({
      key: `booking:${row.name}`, kind: "booking" as const,
      name: row.name, customer: row.customer,
      label: `Reserva ${row.name} · ${row.customer} · ${row.status}` })) || []),
    ...(data?.advance_stays.map((row) => ({
      key: `stay:${row.name}`, kind: "stay" as const,
      name: row.name, customer: row.customer,
      label: `Estancia ${row.name} · ${row.customer}` })) || []),
  ]
  const selectedAdvanceTarget = advanceTargets.find((row) => row.key === advanceOrigin)
  const selectedAdvanceMethod = data?.methods.find((row) => row.name === advanceMethod)
  const chosenRefundCredit = directNotePage?.rows.find((row) => row.name === refundCredit)
  const matchingRefundSources = directPaymentPage?.rows.filter((row) =>
    row.invoice === chosenRefundCredit?.invoice && row.customer === chosenRefundCredit.customer) || []
  const chosenRefundSource = matchingRefundSources.find((row) => row.name === refundSource)
  const refundMethod = data?.methods.find((row) => row.name === chosenRefundSource?.method)
  function changeCollection() { setCollectQuote(null); setCollectKey(""); setError("") }
  function changeFolio() { setFolioQuote(null); setFolioKey(""); setError("") }
  function changeAdvance() { setAdvanceQuote(null); setAdvanceKey(""); setError("") }
  function changeCredit() { setCreditQuote(null); setCreditKey(""); setError("") }
  function changeRefund() { setRefundQuote(null); setRefundKey(""); setError("") }

  async function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !selectedInvoice || !selectedAdvance) return
    setBusy(true); setError(""); setNotice("")
    try {
      const key = applyKey || crypto.randomUUID(); setApplyKey(key)
      const result = await execute<{ amount: string; currency: string; remaining_advance: string; invoice_outstanding: string }>(
        property.name, "apply_customer_advance", { invoice, advance, amount }, key)
      await refresh()
      setAdvance(""); setAmount(""); setApplyKey("")
      setNotice(`Aplicados ${result.currency} ${result.amount}. Crédito restante: ${result.remaining_advance}; saldo de factura: ${result.invoice_outstanding}.`)
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo aplicar el anticipo.") }
    finally { setBusy(false) }
  }

  async function collect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !collectInvoice || !collectMethod || !collectShift) return
    const payload = { kind: "Payment", invoice: collectInvoice,
      method: collectMethod, shift: collectShift, amount: collectAmount,
      reference: collectReference.trim(),
      ...(selectedMethod?.is_cash && collectTendered ? { tendered: collectTendered } : {}) }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!collectQuote) {
        setCollectQuote(await call<PaymentQuote>("preview", {
          property_name: property.name, action: "payment",
          data: JSON.stringify(payload),
        }))
      } else {
        const key = collectKey || crypto.randomUUID(); setCollectKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: collectQuote.acceptance }, key)
        await refresh()
        setCollectQuote(null); setCollectKey(""); setCollectAmount("")
        setCollectReference(""); setCollectTendered("")
        setNotice(`Cobro ${result.payment} registrado para la factura ${collectInvoice}.`)
        setCollectInvoice("")
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cobrar la factura.") }
    finally { setBusy(false) }
  }

  async function collectFolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !selectedFolio || !folioMethod || !folioShift) return
    const payload = { kind: "Payment", folio: selectedFolio.name,
      ...(selectedFolio.stay ? { stay: selectedFolio.stay } : {}),
      ...(selectedFolio.booking ? { booking: selectedFolio.booking } : {}),
      method: folioMethod, shift: folioShift, amount: folioAmount,
      reference: folioReference.trim(),
      ...(selectedFolioMethod?.is_cash && folioTendered ? { tendered: folioTendered } : {}) }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!folioQuote) {
        setFolioQuote(await call<PaymentQuote>("preview", {
          property_name: property.name, action: "payment",
          data: JSON.stringify(payload),
        }))
      } else {
        const key = folioKey || crypto.randomUUID(); setFolioKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: folioQuote.acceptance }, key)
        await refresh()
        setFolio(""); setFolioAmount(""); setFolioTendered("")
        setFolioReference(""); setFolioQuote(null); setFolioKey("")
        setNotice(`Cobro ${result.payment} registrado para la cuenta ${selectedFolio.name}.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo cobrar la cuenta.") }
    finally { setBusy(false) }
  }

  async function receiveAdvance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !selectedAdvanceTarget || !advanceMethod || !advanceShift) return
    const payload = { kind: "Advance", [selectedAdvanceTarget.kind]: selectedAdvanceTarget.name,
      method: advanceMethod, shift: advanceShift, amount: advanceAmount,
      reference: advanceReference.trim(),
      ...(selectedAdvanceMethod?.is_cash && advanceTendered ? { tendered: advanceTendered } : {}) }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!advanceQuote) {
        setAdvanceQuote(await call<PaymentQuote>("preview", {
          property_name: property.name, action: "payment",
          data: JSON.stringify(payload),
        }))
      } else {
        const key = advanceKey || crypto.randomUUID(); setAdvanceKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: advanceQuote.acceptance }, key)
        await refresh()
        setAdvanceOrigin(""); setAdvanceAmount(""); setAdvanceTendered("")
        setAdvanceReference(""); setAdvanceQuote(null); setAdvanceKey("")
        setNotice(`Anticipo ${result.payment} recibido para ${selectedAdvanceTarget.name}.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo recibir el anticipo.") }
    finally { setBusy(false) }
  }

  async function searchFolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError("")
    try {
      appliedFolioSearch.current = folioSearch.trim()
      folioOffset.current = 0
      await refresh()
      setFolio(""); setFolioQuote(null); setFolioKey("")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron buscar cuentas.") }
    finally { setBusy(false) }
  }

  async function pageFolio(offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      folioOffset.current = offset
      await refresh()
      setFolio(""); setFolioQuote(null); setFolioKey("")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron paginar las cuentas.") }
    finally { setBusy(false) }
  }

  async function findInvoices(search: string, offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      appliedInvoiceSearch.current = search
      invoiceOffset.current = offset
      await refresh()
      setCollectInvoice(""); setCollectQuote(null); setCollectKey("")
      setInvoice(""); setAdvance(""); setAmount(""); setApplyKey("")
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron buscar las facturas pendientes.") }
    finally { setBusy(false) }
  }

  async function findFunds(kind: "advance" | "guarantee", search: string,
    offset: number) {
    if (busy) return
    setBusy(true); setError("")
    try {
      if (kind === "advance") {
        appliedAdvanceSearch.current = search
        advanceOffset.current = offset
        setAdvance(""); setAmount(""); setApplyKey("")
      } else {
        appliedGuaranteeSearch.current = search
        guaranteeOffset.current = offset
      }
      await refresh()
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron buscar los fondos.") }
    finally { setBusy(false) }
  }

  async function findDirect(mode: "invoices" | "notes" | "payments", search: string,
    offset: number, creditNote = refundCredit) {
    if (busy) return
    setBusy(true); setError("")
    try {
      if (mode === "invoices") {
        const page = await directPage<DirectInvoice>(property.name, mode, search, offset)
        appliedCreditInvoiceSearch.current = search
        setDirectInvoicePage(page)
        setCreditInvoice(""); setCreditOptions([]); setCreditItems(null)
        changeCredit()
      } else if (mode === "notes") {
        const page = await directPage<DirectNote>(property.name, mode, search, offset)
        appliedRefundCreditSearch.current = search
        setDirectNotePage(page)
        setRefundCredit(""); setRefundSource(""); setDirectPaymentPage(null)
        setRefundAmount(""); changeRefund()
      } else {
        const page = await directPage<DirectPayment>(property.name, mode, search, offset, creditNote)
        appliedRefundSourceSearch.current = search
        setDirectPaymentPage(page)
        setRefundSource(""); setRefundAmount(""); changeRefund()
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudieron buscar los documentos directos.") }
    finally { setBusy(false) }
  }

  async function credit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canApprove || !creditInvoice || !creditReason.trim()) return
    const items = creditItems === null ? undefined : Object.entries(creditItems)
      .filter(([, quantity]) => Number(quantity) > 0)
      .map(([invoice_item, quantity]) => ({ invoice_item, quantity }))
    if (items && !items.length) { setError("Seleccione al menos una línea para acreditar."); return }
    const payload = { invoice: creditInvoice, reason: creditReason.trim(),
      ...(items ? { items } : {}) }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!creditQuote) {
        const result = await call<CreditQuote>("preview", {
          property_name: property.name, action: "credit_note", data: JSON.stringify(payload),
        })
        setCreditOptions((current) => current.length ? current : result.items)
        setCreditQuote(result)
      } else {
        const key = creditKey || crypto.randomUUID(); setCreditKey(key)
        const result = await execute<{ credit_note: string }>(property.name,
          "credit_note", { ...payload, acceptance: creditQuote.acceptance }, key)
        await refresh()
        setDirectNotePage(await directPage<DirectNote>(property.name, "notes",
          appliedRefundCreditSearch.current, directNotePage?.offset || 0))
        setCreditInvoice(""); setCreditReason(""); setCreditOptions([])
        setCreditItems(null); setCreditQuote(null); setCreditKey("")
        setNotice(`Nota de crédito ${result.credit_note} registrada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo registrar la nota.") }
    finally { setBusy(false) }
  }

  async function refund(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canApprove || !chosenRefundSource || !refundMethod || !refundCredit || !refundShift) return
    const payload = { kind: "Refund", source_payment: chosenRefundSource.name,
      credit_note: refundCredit, method: refundMethod.name, shift: refundShift,
      amount: refundAmount, reference: refundReference.trim(), reason: refundReason.trim() }
    setBusy(true); setError(""); setNotice("")
    try {
      if (!refundQuote) {
        setRefundQuote(await call<PaymentQuote>("preview", {
          property_name: property.name, action: "payment", data: JSON.stringify(payload),
        }))
      } else {
        const key = refundKey || crypto.randomUUID(); setRefundKey(key)
        const result = await execute<{ payment: string }>(property.name,
          "payment", { ...payload, fx_acceptance: refundQuote.acceptance }, key)
        await refresh()
        setDirectNotePage(await directPage<DirectNote>(property.name, "notes",
          appliedRefundCreditSearch.current, directNotePage?.offset || 0))
        setRefundCredit(""); setRefundSource(""); setRefundShift("")
        setDirectPaymentPage(null)
        setRefundAmount(""); setRefundReason(""); setRefundReference("")
        setRefundQuote(null); setRefundKey("")
        setNotice(`Devolución ${result.payment} registrada.`)
      }
    } catch (issue) { setError(issue instanceof Error ? issue.message : "No se pudo devolver el cobro.") }
    finally { setBusy(false) }
  }

  return <div className="space-y-6">
    <div><h1 className="text-3xl font-semibold">{sectionInfo.label}</h1><p className="mt-2 text-sm text-muted-foreground">Cobros y créditos ERPNext · {sectionInfo.description}.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-red-50 p-4 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    {!data ? <Skeleton className="h-64 rounded-xl" /> : <>
    <p className="text-sm text-muted-foreground">Abra y arquee turnos en <Link to="/cash" className="text-primary underline">Caja ERPNext</Link>.</p>
    {section === "folios" && <Card><CardHeader><CardTitle>Registrar pago de estancia</CardTitle><CardDescription>Revise el saldo antes de cobrar. Los cargos pendientes de la cuenta se facturan al confirmar el pago y el cobro se aplica a sus facturas.</CardDescription></CardHeader><CardContent className="space-y-3">{requestedFolio ? <div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>Cuenta de estancia: <strong>{requestedFolio}</strong></span><Link className="text-primary underline" to="/customer-credits?section=folios">Cambiar cuenta</Link></div> : <form onSubmit={searchFolio} className="flex gap-2"><Input maxLength={100} aria-label="Buscar cuenta o cliente" placeholder="Buscar cuenta o cliente" value={folioSearch} onChange={(event) => setFolioSearch(event.target.value)} /><Button type="submit" variant="outline" disabled={busy}>Buscar</Button></form>}
      {requestedFolio && data.folio_page.search === requestedFolio && !availableFolios.length && <p className="text-sm text-muted-foreground">Esta cuenta ya no tiene saldo pendiente por cobrar.</p>}
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Página {Math.floor(data.folio_page.offset / RECEIVABLE_PAGE_LENGTH) + 1} · {data.folios.length} cuenta(s) con saldo</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !data.folio_page.offset} onClick={() => void pageFolio(Math.max(0, data.folio_page.offset - RECEIVABLE_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !data.folio_page.has_more} onClick={() => void pageFolio(data.folio_page.offset + RECEIVABLE_PAGE_LENGTH)}>Siguiente</Button></div></div>
      <form onSubmit={collectFolio} className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-sm sm:col-span-2">Cuenta con saldo<select required value={folio} onChange={(event) => { changeFolio(); setFolio(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione cuenta</option>{availableFolios.map((row) => <option key={row.name} value={row.name}>{row.label || row.name} · {row.customer} · Saldo {row.currency} {row.balance.outstanding}</option>)}</select></label>
      {selectedFolio && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">{selectedFolio.name} · pendiente de facturar {data.currency} {selectedFolio.balance.pending} · programado {data.currency} {selectedFolio.balance.scheduled} · saldo total {data.currency} {selectedFolio.balance.outstanding}</p>}
      <label className="space-y-1 text-sm">Medio<select required value={folioMethod} onChange={(event) => { changeFolio(); setFolioMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
      <label className="space-y-1 text-sm">Turno<select required value={folioShift} onChange={(event) => { changeFolio(); setFolioShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
      <label className="space-y-1 text-sm">Importe {selectedFolioMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={folioAmount} onChange={(event) => { changeFolio(); setFolioAmount(event.target.value) }} /></label>
      {selectedFolioMethod?.is_cash && <label className="space-y-1 text-sm">Efectivo recibido {selectedFolioMethod.currency}<Input type="number" min={folioAmount || "0"} step="0.01" value={folioTendered} onChange={(event) => { changeFolio(); setFolioTendered(event.target.value) }} placeholder="Igual al importe" /></label>}
      <label className="space-y-1 text-sm sm:col-span-2">Referencia<Input required={!!selectedFolioMethod?.reference_required} maxLength={140} value={folioReference} onChange={(event) => { changeFolio(); setFolioReference(event.target.value) }} /></label>
      {folioQuote?.folio && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">{folioQuote.currency} {folioQuote.amount} × {folioQuote.exchange_rate} = {folioQuote.property_currency} {folioQuote.property_amount} · saldo anterior {folioQuote.folio.outstanding}</p>}
      <Button disabled={busy || !data.folios.length} className="sm:col-span-2">{folioQuote ? "Confirmar cobro" : "Revisar cobro"}</Button>
    </form></CardContent></Card>}
    {section === "receive-advance" && <Card><CardHeader><CardTitle>Recibir anticipo</CardTitle><CardDescription>Vincule el dinero recibido a una reserva vigente o estancia activa. Quedará disponible para aplicarlo a facturas del mismo cliente.</CardDescription></CardHeader><CardContent><form onSubmit={receiveAdvance} className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-sm sm:col-span-2">Origen<select required value={advanceOrigin} onChange={(event) => { changeAdvance(); setAdvanceOrigin(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione reserva o estancia</option>{advanceTargets.map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}</select></label>
      <label className="space-y-1 text-sm">Medio<select required value={advanceMethod} onChange={(event) => { changeAdvance(); setAdvanceMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
      <label className="space-y-1 text-sm">Turno<select required value={advanceShift} onChange={(event) => { changeAdvance(); setAdvanceShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
      <label className="space-y-1 text-sm">Importe {selectedAdvanceMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={advanceAmount} onChange={(event) => { changeAdvance(); setAdvanceAmount(event.target.value) }} /></label>
      {selectedAdvanceMethod?.is_cash && <label className="space-y-1 text-sm">Efectivo recibido {selectedAdvanceMethod.currency}<Input type="number" min={advanceAmount || "0"} step="0.01" value={advanceTendered} onChange={(event) => { changeAdvance(); setAdvanceTendered(event.target.value) }} placeholder="Igual al importe" /></label>}
      <label className="space-y-1 text-sm sm:col-span-2">Referencia<Input required={!!selectedAdvanceMethod?.reference_required} maxLength={140} value={advanceReference} onChange={(event) => { changeAdvance(); setAdvanceReference(event.target.value) }} /></label>
      {advanceQuote?.origin && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Cliente {advanceQuote.origin.customer} · {advanceQuote.currency} {advanceQuote.amount} × {advanceQuote.exchange_rate} = {advanceQuote.property_currency} {advanceQuote.property_amount}</p>}
      <Button disabled={busy || !advanceTargets.length} className="sm:col-span-2">{advanceQuote ? "Confirmar anticipo" : "Revisar anticipo"}</Button>
    </form></CardContent></Card>}
    {(section === "apply-guarantee" || section === "refund-guarantee") && <Card><CardHeader><CardTitle>Buscar garantías vigentes</CardTitle><CardDescription>Busque por número, referencia o cliente antes de aplicar o devolver una garantía.</CardDescription></CardHeader><CardContent className="space-y-3">
      <form onSubmit={(event) => { event.preventDefault(); void findFunds("guarantee", guaranteeSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar garantía, referencia o cliente" placeholder="Garantía, referencia o cliente" value={guaranteeSearch} onChange={(event) => setGuaranteeSearch(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Página {Math.floor(data.guarantee_page.offset / FUNDS_PAGE_LENGTH) + 1} · {data.guarantees.length} garantía(s) con saldo</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !data.guarantee_page.offset} onClick={() => void findFunds("guarantee", appliedGuaranteeSearch.current, Math.max(0, data.guarantee_page.offset - FUNDS_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !data.guarantee_page.has_more} onClick={() => void findFunds("guarantee", appliedGuaranteeSearch.current, data.guarantee_page.offset + FUNDS_PAGE_LENGTH)}>Siguiente</Button></div></div>
    </CardContent></Card>}
    {(section === "receive-guarantee" || section === "apply-guarantee" || section === "refund-guarantee") && <Guarantees property={property} data={data}
      mode={section === "receive-guarantee" ? "receive" : section === "apply-guarantee" ? "apply" : "refund"} canApprove={canApprove}
      refresh={refresh} onNotice={setNotice} onError={setError} />}
    {(section === "apply-advance" || section === "refund-advance") && <Card><CardHeader><CardTitle>Buscar anticipos vigentes</CardTitle><CardDescription>La búsqueda afecta los anticipos para aplicar y devolver. Puede buscar por número, referencia o cliente.</CardDescription></CardHeader><CardContent className="space-y-3">
      <form onSubmit={(event) => { event.preventDefault(); void findFunds("advance", advanceSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar anticipo, referencia o cliente" placeholder="Anticipo, referencia o cliente" value={advanceSearch} onChange={(event) => setAdvanceSearch(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Página {Math.floor(data.advance_page.offset / FUNDS_PAGE_LENGTH) + 1} · {data.advances.length} anticipo(s) con saldo</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !data.advance_page.offset} onClick={() => void findFunds("advance", appliedAdvanceSearch.current, Math.max(0, data.advance_page.offset - FUNDS_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !data.advance_page.has_more} onClick={() => void findFunds("advance", appliedAdvanceSearch.current, data.advance_page.offset + FUNDS_PAGE_LENGTH)}>Siguiente</Button></div></div>
    </CardContent></Card>}
    {section === "refund-advance" && canApprove && <AdvanceRefunds property={property} data={data}
      refresh={refresh} onNotice={setNotice} onError={setError} />}
    {section === "refund-applied" && canApprove && <AppliedRefunds property={property} data={data}
      refresh={refresh} onNotice={setNotice} onError={setError} />}
    {(section === "invoices" || section === "apply-advance") && <Card><CardHeader><CardTitle>Buscar facturas pendientes</CardTitle><CardDescription>La búsqueda afecta el cobro de facturas directas y la aplicación de anticipos. Busque por número o cliente para localizar saldos anteriores.</CardDescription></CardHeader><CardContent className="space-y-3">
      <form onSubmit={(event) => { event.preventDefault(); void findInvoices(invoiceSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar factura o cliente" placeholder="Factura o cliente" value={invoiceSearch} onChange={(event) => setInvoiceSearch(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>Página {Math.floor(data.invoice_page.offset / RECEIVABLE_PAGE_LENGTH) + 1} · {data.invoices.length} factura(s) pendiente(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !data.invoice_page.offset} onClick={() => void findInvoices(appliedInvoiceSearch.current, Math.max(0, data.invoice_page.offset - RECEIVABLE_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !data.invoice_page.has_more} onClick={() => void findInvoices(appliedInvoiceSearch.current, data.invoice_page.offset + RECEIVABLE_PAGE_LENGTH)}>Siguiente</Button></div></div>
    </CardContent></Card>}
    {section === "invoices" && <Card><CardHeader><CardTitle>Cobrar factura directa</CardTitle><CardDescription>Facturas sin cuenta de estancia, incluidas cuentas trasladadas desde PMS. El cobro queda vinculado a una sola factura y al turno seleccionado.</CardDescription></CardHeader><CardContent><form onSubmit={collect} className="grid gap-3 sm:grid-cols-2">
      {requestedInvoice && <p className="text-sm sm:col-span-2">Saldo trasladado: <strong>{requestedInvoice}</strong> · <Link className="text-primary underline" to="/customer-credits?section=invoices">Cambiar factura</Link></p>}
      <label className="space-y-1 text-sm sm:col-span-2">Factura pendiente<select required value={collectInvoice} onChange={(event) => { changeCollection(); setCollectInvoice(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione factura directa</option>{directInvoices.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.customer} · Pendiente {data.currency} {row.outstanding}</option>)}</select></label>
      {!directInvoices.length && <p className="text-sm text-muted-foreground sm:col-span-2">{requestedInvoice ? "Esta factura ya no tiene saldo pendiente o no pertenece al establecimiento." : "Esta página no contiene facturas directas. Busque por número o cliente en el cuadro anterior."}</p>}
      <label className="space-y-1 text-sm">Medio<select required value={collectMethod} onChange={(event) => { changeCollection(); setCollectMethod(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione medio</option>{data.methods.map((row) => <option key={row.name} value={row.name}>{row.mode_of_payment} · {row.currency}</option>)}</select></label>
      <label className="space-y-1 text-sm">Turno<select required value={collectShift} onChange={(event) => { changeCollection(); setCollectShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select></label>
      <label className="space-y-1 text-sm">Importe {selectedMethod?.currency || ""}<Input required type="number" min="0.01" step="0.01" value={collectAmount} onChange={(event) => { changeCollection(); setCollectAmount(event.target.value) }} /></label>
      {selectedMethod?.is_cash && <label className="space-y-1 text-sm">Efectivo recibido {selectedMethod.currency}<Input type="number" min={collectAmount || "0"} step="0.01" value={collectTendered} onChange={(event) => { changeCollection(); setCollectTendered(event.target.value) }} placeholder="Igual al importe" /></label>}
      <label className="space-y-1 text-sm sm:col-span-2">Referencia<Input required={!!selectedMethod?.reference_required} maxLength={140} value={collectReference} onChange={(event) => { changeCollection(); setCollectReference(event.target.value) }} /></label>
      {collectQuote?.invoice && <p className="rounded-lg bg-secondary p-3 text-sm sm:col-span-2">Factura {collectQuote.invoice.name} · {collectQuote.currency} {collectQuote.amount} × {collectQuote.exchange_rate} = {collectQuote.property_currency} {collectQuote.property_amount} · Saldo anterior {collectQuote.invoice.outstanding}</p>}
      <Button disabled={busy || !directInvoices.length} className="sm:col-span-2">{collectQuote ? "Confirmar cobro" : "Revisar cobro"}</Button>
    </form></CardContent></Card>}
    {(section === "credit-note" || section === "direct-refund") && canApprove && <div className="max-w-3xl">
      {section === "credit-note" && <Card><CardHeader><CardTitle>Nota de crédito de factura directa</CardTitle><CardDescription>Revise las líneas y el total antes de acreditar. La devolución de un cobro se registra aparte contra esta nota.</CardDescription></CardHeader><CardContent className="space-y-3">
        <form onSubmit={(event) => { event.preventDefault(); void findDirect("invoices", creditInvoiceSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar factura directa" placeholder="Factura o cliente" value={creditInvoiceSearch} onChange={(event) => setCreditInvoiceSearch(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
        {directInvoicePage && <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Página {Math.floor(directInvoicePage.offset / DIRECT_PAGE_LENGTH) + 1} · {directInvoicePage.rows.length} factura(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !directInvoicePage.offset} onClick={() => void findDirect("invoices", appliedCreditInvoiceSearch.current, Math.max(0, directInvoicePage.offset - DIRECT_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !directInvoicePage.has_more} onClick={() => void findDirect("invoices", appliedCreditInvoiceSearch.current, directInvoicePage.offset + DIRECT_PAGE_LENGTH)}>Siguiente</Button></div></div>}
        <form onSubmit={credit} className="space-y-3">
        <select required value={creditInvoice} onChange={(event) => { changeCredit(); setCreditInvoice(event.target.value); setCreditOptions([]); setCreditItems(null) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Factura directa</option>{directInvoicePage?.rows.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.customer} · {row.posting_date}</option>)}</select>
        <Input required minLength={8} maxLength={500} placeholder="Motivo de la nota" value={creditReason} onChange={(event) => { changeCredit(); setCreditReason(event.target.value) }} />
        {creditOptions.length > 0 && <div className="space-y-2 rounded-lg border p-3 text-sm"><p>Líneas acreditables</p>{creditOptions.map((row) => <label key={row.invoice_item} className="flex items-center justify-between gap-3"><span>{row.item_name} · máximo {row.quantity} · {data.currency} {row.amount}</span><Input aria-label={`Cantidad a acreditar de ${row.item_name}`} className="w-28" type="number" min="0" max={row.quantity} step="any" value={creditItems?.[row.invoice_item] ?? row.quantity} onChange={(event) => { changeCredit(); setCreditItems((current) => ({ ...Object.fromEntries(creditOptions.map((item) => [item.invoice_item, item.quantity])), ...current, [row.invoice_item]: event.target.value })) }} /></label>)}</div>}
        {creditQuote && <p className="rounded-lg bg-secondary p-3 text-sm">Total de la nota: {creditQuote.currency} {creditQuote.total} · {creditQuote.items.length} línea(s).</p>}
        <Button disabled={busy || !creditInvoice} className="w-full">{creditQuote ? "Confirmar nota" : "Revisar nota"}</Button>
      </form></CardContent></Card>}
      {section === "direct-refund" && <Card><CardHeader><CardTitle>Devolver cobro directo</CardTitle><CardDescription>Seleccione una nota con saldo a favor y el cobro original. La revisión limita la devolución a ambos saldos.</CardDescription></CardHeader><CardContent className="space-y-3">
        <form onSubmit={(event) => { event.preventDefault(); void findDirect("notes", refundCreditSearch.trim(), 0) }} className="flex gap-2"><Input maxLength={100} aria-label="Buscar nota de crédito directa" placeholder="Nota, factura o cliente" value={refundCreditSearch} onChange={(event) => setRefundCreditSearch(event.target.value)} /><Button disabled={busy} variant="outline">Buscar</Button></form>
        {directNotePage && <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Página {Math.floor(directNotePage.offset / DIRECT_PAGE_LENGTH) + 1} · {directNotePage.rows.length} nota(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !directNotePage.offset} onClick={() => void findDirect("notes", appliedRefundCreditSearch.current, Math.max(0, directNotePage.offset - DIRECT_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !directNotePage.has_more} onClick={() => void findDirect("notes", appliedRefundCreditSearch.current, directNotePage.offset + DIRECT_PAGE_LENGTH)}>Siguiente</Button></div></div>}
        <form onSubmit={refund} className="space-y-3">
        <select required value={refundCredit} onChange={(event) => { changeRefund(); setRefundCredit(event.target.value); setRefundSource(""); setRefundAmount(""); setDirectPaymentPage(null); setRefundSourceSearch(""); if (event.target.value) void findDirect("payments", "", 0, event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Nota de crédito disponible</option>{directNotePage?.rows.map((row) => <option key={row.name} value={row.name}>{row.name} · factura {row.invoice} · Disponible {data.currency} {row.available}</option>)}</select>
        {refundCredit && <><div className="flex gap-2"><Input maxLength={100} aria-label="Buscar cobro directo" placeholder="Cobro o referencia" value={refundSourceSearch} onChange={(event) => setRefundSourceSearch(event.target.value)} /><Button type="button" disabled={busy} variant="outline" onClick={() => void findDirect("payments", refundSourceSearch.trim(), 0)}>Buscar</Button></div>{directPaymentPage && <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Página {Math.floor(directPaymentPage.offset / DIRECT_PAGE_LENGTH) + 1} · {directPaymentPage.rows.length} cobro(s)</span><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !directPaymentPage.offset} onClick={() => void findDirect("payments", appliedRefundSourceSearch.current, Math.max(0, directPaymentPage.offset - DIRECT_PAGE_LENGTH))}>Anterior</Button><Button type="button" size="sm" variant="outline" disabled={busy || !directPaymentPage.has_more} onClick={() => void findDirect("payments", appliedRefundSourceSearch.current, directPaymentPage.offset + DIRECT_PAGE_LENGTH)}>Siguiente</Button></div></div>}</>}
        <select required value={refundSource} onChange={(event) => { changeRefund(); setRefundSource(event.target.value); setRefundAmount("") }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Cobro original de la factura</option>{matchingRefundSources.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.currency} {row.amount}</option>)}</select>
        {chosenRefundSource && <p className="text-sm text-muted-foreground">Medio original: {refundMethod?.mode_of_payment || chosenRefundSource.method} · {chosenRefundSource.currency}</p>}
        <select required value={refundShift} onChange={(event) => { changeRefund(); setRefundShift(event.target.value) }} className="h-9 w-full rounded-md border border-border bg-white px-2 text-sm"><option value="">Turno abierto</option>{data.shifts.filter((row) => row.status === "Open").map((row) => <option key={row.name} value={row.name}>{row.name} · {row.cashier}</option>)}</select>
        <Input required type="number" min="0.01" step="0.01" placeholder={`Importe ${chosenRefundSource?.currency || ""}`} value={refundAmount} onChange={(event) => { changeRefund(); setRefundAmount(event.target.value) }} />
        <Input maxLength={140} placeholder="Referencia de devolución" required={!!refundMethod?.reference_required} value={refundReference} onChange={(event) => { changeRefund(); setRefundReference(event.target.value) }} />
        <Input required minLength={8} maxLength={500} placeholder="Motivo de devolución" value={refundReason} onChange={(event) => { changeRefund(); setRefundReason(event.target.value) }} />
        {refundQuote && <p className="rounded-lg bg-secondary p-3 text-sm">Salida {refundQuote.currency} {refundQuote.amount} · crédito original {refundQuote.refund?.party_currency} {refundQuote.refund?.party_amount} · diferencia cambiaria {refundQuote.base_currency} {refundQuote.refund?.exchange_difference} · factura {refundQuote.refund?.invoice}</p>}
        <Button disabled={busy || !chosenRefundSource || !refundMethod} className="w-full">{refundQuote ? "Confirmar devolución" : "Revisar devolución"}</Button>
      </form></CardContent></Card>}
    </div>}
    {section === "apply-advance" && <Card>
      <CardHeader><CardTitle>Aplicar anticipo</CardTitle><CardDescription>Importe en {data.currency}, moneda de la cuenta por cobrar. Las devoluciones de un importe aplicado requieren una nota de crédito vinculada a la factura.</CardDescription></CardHeader>
      <CardContent><form onSubmit={apply} className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2">Factura pendiente<select required value={invoice} onChange={(event) => { setInvoice(event.target.value); setAdvance(""); setAmount(""); setApplyKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione factura</option>{data.invoices.map((row) => <option key={row.name} value={row.name}>{row.name} · {row.customer} · {row.posting_date} · Pendiente {data.currency} {row.outstanding}</option>)}</select></label>
        <label className="space-y-1 text-sm sm:col-span-2">Anticipo del cliente<select required value={advance} onChange={(event) => { setAdvance(event.target.value); setAmount(""); setApplyKey("") }} className="h-9 w-full rounded-md border border-border bg-white px-2"><option value="">Seleccione anticipo</option>{matching.map((row) => <option key={row.name} value={row.name}>{row.reference} · Disponible {data.currency} {row.available}</option>)}</select></label>
        <Input required type="number" min="0.01" step="0.01" max={Math.min(Number(selectedInvoice?.outstanding || 0), Number(selectedAdvance?.available || 0)) || undefined} placeholder={`Importe ${data.currency}`} value={amount} onChange={(event) => { setAmount(event.target.value); setApplyKey("") }} />
        <Button disabled={busy || !selectedInvoice || !selectedAdvance}>Aplicar a factura</Button>
      </form></CardContent>
    </Card>}</>}
  </div>
}
