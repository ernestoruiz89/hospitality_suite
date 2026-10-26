export type FiscalArchiveSection = { id: "erp" | "pms" | "historical"; label: string }

export function availableFiscalArchiveSections(provider: "pms" | "erpnext"): FiscalArchiveSection[] {
  return provider === "erpnext" ? [
    { id: "erp", label: "Documentos ERPNext" },
    { id: "pms", label: "Documentos PMS" },
    { id: "historical", label: "Copias trasladadas" },
  ] : [
    { id: "pms", label: "Documentos PMS" },
    { id: "historical", label: "Copias trasladadas" },
  ]
}
