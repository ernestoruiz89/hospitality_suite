import { useEffect, useState } from "react"
import { Input } from "@/components/ui/input"
import { call } from "./api"

export function FinancialLookup({ propertyName, field, label, value, onChange, idSuffix }: {
  propertyName: string; field: string; label: string; value: string;
  onChange: (value: string) => void; idSuffix?: string
}) {
  const [focused, setFocused] = useState(false)
  const [options, setOptions] = useState<{ name: string; label: string }[]>([])
  useEffect(() => {
    if (!focused) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      call<{ name: string; label: string }[]>("financial_setup_options", {
        property_name: propertyName, field, search: value,
      }, controller.signal).then(setOptions).catch(() => { if (!controller.signal.aborted) setOptions([]) })
    }, 180)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [propertyName, field, focused, value])
  const listId = `financial-${field}-${idSuffix || "property"}`
  return <label className="space-y-1 text-sm"><span>{label}</span>
    <Input list={listId} value={value} autoComplete="off" onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)} onChange={(event) => onChange(event.target.value)}
      placeholder="Buscar por nombre o código" />
    <datalist id={listId}>{options.map((option) =>
      <option key={option.name} value={option.name}>{option.label}</option>)}</datalist>
  </label>
}
