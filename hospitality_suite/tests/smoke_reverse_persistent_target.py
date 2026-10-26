"""Read-only verification of an actual committed ERPNext to PMS smoke opening."""

from pathlib import Path

import frappe

from hospitality_suite.erp_to_pms_activation import DOCTYPE


def verify(reference):
    if frappe.local.site != "hs-pms-smoke-reverse.local":
        frappe.throw("Use únicamente el clon PMS aislado")
    frappe.set_user("Administrator")
    mode = frappe.get_single("HS Site Mode")
    name = frappe.db.get_value(DOCTYPE,
        {"migration_reference": reference}, "name")
    if mode.provider != "PMS" or mode.migration_reference != reference or not name:
        frappe.throw("El corte confirmado no conserva proveedor y acta")
    record = frappe.get_doc(DOCTYPE, name)
    result = frappe.parse_json(record.result_json)
    if (not isinstance(result, dict) or not result.get("cutover_performed") or
            not result.get("reconciled") or result.get("provider_changed") or
            result.get("source_sha256") != record.source_sha256 or
            result.get("plan_sha256") != record.plan_sha256 or
            not result.get("properties")):
        frappe.throw("El acta persistida no concilia la apertura")
    references = result["properties"]
    evidence = []
    for row in references:
        prop = frappe.get_doc("HS Property", row["property"])
        if (not row.get("residual_journal") or
                not frappe.db.exists("HS Journal", row["residual_journal"]) or
                not row.get("receivables") or
                not all(frappe.db.exists("HS PMS Receivable", name)
                        for name in row["receivables"])):
            frappe.throw("El libro de apertura perdió documentos")
        operations = row.get("operations") or {}
        if (not operations.get("folios") or
                not all(frappe.db.exists("HS Folio", name)
                        for name in operations["folios"])):
            frappe.throw("El corte perdió folios operativos")
        for source_name, doctype in (("INC-EVIDENCE-ORIGEN-", "HS Incident"),
                                     ("MAINT-ORIGEN-", "HS Maintenance Order")):
            names = [entry for entry in operations.get(
                "incidents" if doctype == "HS Incident" else "maintenance_orders", [])
                if entry.startswith(source_name)]
            for doc_name in names:
                doc = frappe.get_doc(doctype, doc_name)
                file_url = doc.evidence
                file_row = frappe.db.get_value("File", {
                    "file_url": file_url, "attached_to_doctype": doctype,
                    "attached_to_name": doc_name}, "name")
                if not file_row:
                    frappe.throw("La evidencia privada perdió su vínculo")
                path = Path(frappe.get_doc("File", file_row).get_full_path())
                if not path.is_file() or not path.read_bytes():
                    frappe.throw("La evidencia privada desapareció")
                evidence.append(file_row)
        if not prop.organization:
            frappe.throw("La apertura perdió la entidad legal")
    if len(evidence) != 2 or frappe.db.count(DOCTYPE,
            {"migration_reference": reference}) != 1:
        frappe.throw("El corte duplicó actas o perdió adjuntos")
    return {"cutover_run": name, "property_count": len(references),
        "reconciled": True, "private_evidence_files": len(evidence),
        "source_sha256": record.source_sha256,
        "manifest_sha256": record.manifest_sha256,
        "receipt_sha256": record.receipt_sha256,
        "mapping_sha256": record.mapping_sha256,
        "plan_sha256": record.plan_sha256,
        "source_backup_sha256": record.source_backup_sha256,
        "target_backup_sha256": record.target_backup_sha256,
        "folio_count": sum(len(row["operations"]["folios"])
                           for row in references)}
