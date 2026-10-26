"""Portable fiscal PDFs and private operational evidence for ERPNext to PMS.

The bundle is prepared on the source site and imported on the target site by a
System Manager. It never posts an accounting entry or switches the provider.
"""

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.security import is_system, require
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


DOCTYPE = "HS Historical Fiscal Document"
SOURCE_TYPES = ("Sales Invoice", "HS PMS Fiscal Document")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_DOCUMENTS = 100000
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_EVIDENCE_BYTES = 25 * 1024 * 1024
MAX_MANIFEST_BYTES = 100 * 1024 * 1024


def _admin():
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede trasladar el archivo fiscal"),
                     frappe.PermissionError)


def _hash(value):
    return sha256(value).hexdigest()


def _source_key(site, doctype, name):
    return _hash((site + "|" + doctype + "|" + name).encode())


def _pdf(source_doctype, name, status):
    from frappe.utils.pdf import get_pdf
    from frappe.www.printview import get_html_and_style

    print_format = ("HS Documento fiscal PMS" if source_doctype ==
                    "HS PMS Fiscal Document" else "Standard")
    # Frappe's normal print policy may prohibit printing cancelled invoices.
    # A System Manager still needs an accurately marked archival copy at cutover.
    settings = {"allow_print_for_cancelled": 1} if status == "Cancelled" else None
    rendered = get_html_and_style(source_doctype, name,
                                  print_format=print_format, settings=settings)
    if not rendered.get("html"):
        frappe.throw(_("No se pudo preparar la copia imprimible de {0}").format(name))
    heading = ('<div style="font: bold 28px sans-serif; color: #900; '
               'border: 3px solid #900; padding: 8px; text-align: center">'
               'ANULADA</div>') if status == "Cancelled" else ""
    html = ("<html><head><meta charset='utf-8'><style>" +
            (rendered.get("style") or "") +
            "</style></head><body>" + heading + rendered["html"] + "</body></html>")
    content = get_pdf(html)
    if not isinstance(content, bytes) or not content.startswith(b"%PDF") or len(content) > MAX_PDF_BYTES:
        frappe.throw(_("La copia PDF de {0} no es válida").format(name))
    return content


def export_bundle(expected_source_sha256):
    """Write the verified ERP-source bundle under this site's private/files."""
    _admin()
    if provider() != "erpnext" or "erpnext" not in frappe.get_installed_apps():
        frappe.throw(_("La exportación fiscal requiere una fuente ERPNext activa"))
    if not isinstance(expected_source_sha256, str) or not HEX64.fullmatch(expected_source_sha256):
        frappe.throw(_("Indique la huella del diagnóstico ERPNext → PMS"))
    from hospitality_suite.erp_to_pms_preflight import (
        _private_evidence, preflight)

    source = preflight()
    if source["source_sha256"] != expected_source_sha256:
        frappe.throw(_("La fuente ERPNext cambió; repita el diagnóstico"))
    inventory = {key: source[key] for key in
                 ("schema_version", "provider", "properties", "gl_coverage", "blockers")}
    inventory_data = canonical(inventory).encode()
    if _hash(inventory_data) != expected_source_sha256 or len(inventory_data) > MAX_MANIFEST_BYTES:
        frappe.throw(_("El diagnóstico ERPNext no se puede trasladar íntegramente"))
    site = str(frappe.local.site)
    documents = []
    evidence = []
    filename = "hs-erp-fiscal-" + uuid4().hex + ".zip"
    destination = Path(frappe.get_site_path("private", "files", filename))
    temporary = destination.with_suffix(".tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as bundle:
            for prop in source["properties"]:
                for source_doctype, key in (("Sales Invoice", "native_documents"),
                                            ("HS PMS Fiscal Document", "pms_documents")):
                    for item in prop["fiscal_history"][key]:
                        if len(documents) >= MAX_DOCUMENTS:
                            frappe.throw(_("El archivo fiscal supera el límite de documentos"))
                        document = frappe.get_doc(source_doctype, item["name"])
                        if _hash(canonical(document.as_dict()).encode()) != item["snapshot_sha256"]:
                            frappe.throw(_("Cambió el documento fiscal {0}").format(item["name"]))
                        pdf = _pdf(source_doctype, item["name"], item["status"])
                        source_key = _source_key(site, source_doctype, item["name"])
                        documents.append({"source_key": source_key,
                            "property": prop["property"],
                            "source_company": prop["company"],
                            "source_doctype": source_doctype,
                            "source_name": item["name"],
                            "document_type": item["document_type"],
                            "document_number": item.get("document_number") or item["name"],
                            "posting_date": item.get("posting_date") or item.get("business_date"),
                            "buyer_name": (item.get("customer_name") or
                                           item.get("buyer_name") or ""),
                            "currency": item["currency"],
                            "total_amount": item["total_amount"],
                            "source_invoice": item.get("source_invoice") or "",
                            "status": item["status"],
                            "snapshot_sha256": item["snapshot_sha256"],
                            "pdf_sha256": _hash(pdf)})
                        bundle.writestr("pdf/" + source_key + ".pdf", pdf)
                for operation_key, doctype in (("incidents", "HS Incident"),
                        ("maintenance_orders", "HS Maintenance Order")):
                    for record in prop["open_operations"][operation_key]:
                        if not record.get("evidence"):
                            continue
                        if len(evidence) >= MAX_DOCUMENTS:
                            frappe.throw(_("El paquete supera el límite de evidencias"))
                        try:
                            metadata, content = _private_evidence(doctype,
                                record["name"], record["evidence"])
                        except (OSError, ValueError):
                            frappe.throw(_("La evidencia de {0} no está disponible").format(
                                record["name"]))
                        if any(metadata[key] != record.get(key) for key in metadata):
                            frappe.throw(_("Cambió la evidencia de {0}").format(
                                record["name"]))
                        source_key = _source_key(site, doctype, record["name"])
                        evidence.append({"source_key": source_key,
                            "property": prop["property"],
                            "source_company": prop["company"],
                            "source_doctype": doctype,
                            "source_name": record["name"],
                            "source_url": record["evidence"],
                            "file_name": metadata["evidence_file_name"],
                            "size": metadata["evidence_size"],
                            "sha256": metadata["evidence_sha256"]})
                        bundle.writestr("evidence/" + source_key, content)
            documents.sort(key=lambda row: row["source_key"])
            evidence.sort(key=lambda row: row["source_key"])
            manifest = {"schema_version": 4, "source_site": site,
                        "source_sha256": expected_source_sha256,
                        "inventory_sha256": _hash(inventory_data),
                        "documents": documents, "evidence": evidence}
            encoded = canonical(manifest).encode()
            if len(encoded) > MAX_MANIFEST_BYTES:
                frappe.throw(_("El manifiesto fiscal supera el límite permitido"))
            bundle.writestr("manifest.json", encoded)
            bundle.writestr("inventory.json", inventory_data)
        # Recheck after rendering. A changed source cannot produce a usable
        # bundle; the actual cutover still requires its own source freeze.
        if preflight()["source_sha256"] != expected_source_sha256:
            frappe.throw(_("La fuente ERPNext cambió mientras se preparaba el archivo"))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"file_name": filename, "source_sha256": expected_source_sha256,
            "manifest_sha256": _hash(encoded), "documents": len(documents),
            "evidence": len(evidence)}


def _manifest(bundle, expected_source_sha256, expected_manifest_sha256):
    names = bundle.namelist()
    if (names.count("manifest.json") != 1 or
            names.count("inventory.json") != 1 or
            len(names) > MAX_DOCUMENTS * 2 + 2):
        frappe.throw(_("El paquete fiscal tiene entradas inesperadas"))
    info = bundle.getinfo("manifest.json")
    if info.file_size > MAX_MANIFEST_BYTES:
        frappe.throw(_("El manifiesto fiscal supera el límite permitido"))
    encoded = bundle.read("manifest.json")
    if _hash(encoded) != expected_manifest_sha256:
        frappe.throw(_("La huella del manifiesto fiscal no coincide"))
    try:
        manifest = json.loads(encoded)
    except (ValueError, UnicodeDecodeError):
        frappe.throw(_("El manifiesto fiscal no es JSON válido"))
    if (not isinstance(manifest, dict) or manifest.get("schema_version") not in
            (2, 3, 4) or
            manifest.get("source_sha256") != expected_source_sha256 or
            manifest.get("inventory_sha256") != expected_source_sha256 or
            not isinstance(manifest.get("source_site"), str) or
            not manifest["source_site"] or
            not isinstance(manifest.get("documents"), list) or
            (manifest["schema_version"] >= 3 and
                not isinstance(manifest.get("evidence"), list)) or
            (manifest["schema_version"] == 2 and "evidence" in manifest)):
        frappe.throw(_("El manifiesto fiscal no corresponde al diagnóstico"))
    documents = manifest["documents"]
    evidence = manifest.get("evidence", [])
    if len(documents) > MAX_DOCUMENTS or len(evidence) > MAX_DOCUMENTS:
        frappe.throw(_("El paquete fiscal contiene demasiados documentos"))
    if bundle.getinfo("inventory.json").file_size > MAX_MANIFEST_BYTES:
        frappe.throw(_("El diagnóstico de origen supera el límite permitido"))
    inventory_data = bundle.read("inventory.json")
    if _hash(inventory_data) != expected_source_sha256:
        frappe.throw(_("La huella del diagnóstico de origen no coincide"))
    try:
        inventory = json.loads(inventory_data)
    except (ValueError, UnicodeDecodeError):
        frappe.throw(_("El diagnóstico de origen no es JSON válido"))
    if (not isinstance(inventory, dict) or
            set(inventory) != {"schema_version", "provider", "properties",
                               "gl_coverage", "blockers"} or
            inventory["schema_version"] != 1 or
            inventory["provider"] != "ERPNext" or
            not isinstance(inventory["properties"], list) or
            not isinstance(inventory["gl_coverage"], list) or
            not isinstance(inventory["blockers"], list) or
            canonical(inventory).encode() != inventory_data):
        frappe.throw(_("El diagnóstico de origen no corresponde a este paquete"))
    expected = {}
    expected_evidence = {}
    properties = set()
    for prop in inventory["properties"]:
        if (not isinstance(prop, dict) or
                not isinstance(prop.get("property"), str) or
                not isinstance(prop.get("company"), str) or
                not isinstance(prop.get("fiscal_history"), dict) or
                prop["property"] in properties):
            frappe.throw(_("El diagnóstico tiene hoteles o documentos fiscales inválidos"))
        properties.add(prop["property"])
        operations = prop.get("open_operations")
        evidence_kinds = [("incidents", "HS Incident")]
        if manifest["schema_version"] >= 4:
            evidence_kinds.append(("maintenance_orders", "HS Maintenance Order"))
        for operation_key, doctype in evidence_kinds:
            records = (operations.get(operation_key)
                if isinstance(operations, dict) else None)
            if not isinstance(records, list):
                frappe.throw(_("El diagnóstico no incluye operaciones con evidencia"))
            for record in records:
                if not isinstance(record, dict) or not isinstance(
                        record.get("name"), str):
                    frappe.throw(_("El diagnóstico contiene una operación inválida"))
                if not record.get("evidence"):
                    continue
                source_key = _source_key(manifest["source_site"], doctype,
                                         record["name"])
                if source_key in expected_evidence:
                    frappe.throw(_("El diagnóstico repite una evidencia"))
                row = {"source_key": source_key,
                    "property": prop["property"],
                    "source_company": prop["company"],
                    "source_url": record["evidence"],
                    "file_name": record.get("evidence_file_name"),
                    "size": record.get("evidence_size"),
                    "sha256": record.get("evidence_sha256")}
                if manifest["schema_version"] >= 4:
                    row.update(source_doctype=doctype,
                               source_name=record["name"])
                else:
                    row["source_incident"] = record["name"]
                expected_evidence[source_key] = row
        for doctype, key in (("Sales Invoice", "native_documents"),
                             ("HS PMS Fiscal Document", "pms_documents")):
            items = prop["fiscal_history"].get(key)
            if not isinstance(items, list):
                frappe.throw(_("El diagnóstico fiscal está incompleto"))
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    frappe.throw(_("El diagnóstico fiscal contiene un documento inválido"))
                source_key = _source_key(manifest["source_site"], doctype, item["name"])
                if source_key in expected:
                    frappe.throw(_("El diagnóstico fiscal repite un documento"))
                expected[source_key] = {"source_key": source_key,
                    "property": prop["property"], "source_company": prop["company"],
                    "source_doctype": doctype, "source_name": item["name"],
                    "document_type": item.get("document_type"),
                    "document_number": item.get("document_number") or item["name"],
                    "posting_date": item.get("posting_date") or item.get("business_date"),
                    "buyer_name": (item.get("customer_name") or item.get("buyer_name") or ""),
                    "currency": item.get("currency"), "total_amount": item.get("total_amount"),
                    "source_invoice": item.get("source_invoice") or "",
                    "status": item.get("status"),
                    "snapshot_sha256": item.get("snapshot_sha256")}
    if len(expected) != len(documents):
        frappe.throw(_("El paquete omite documentos fiscales del diagnóstico"))
    keys = set()
    for row in documents:
        if not isinstance(row, dict) or set(row) != {
                "source_key", "property", "source_company", "source_doctype",
                "source_name", "document_type", "document_number", "posting_date",
                "buyer_name", "currency", "total_amount", "source_invoice",
                "status", "snapshot_sha256", "pdf_sha256"}:
            frappe.throw(_("Revise los datos del documento fiscal importado"))
        if (row["source_doctype"] not in SOURCE_TYPES or
                row["document_type"] not in ("Invoice", "Credit Note") or
                row["status"] not in ("Posted", "Cancelled") or
                any(not isinstance(row[field], str) or not row[field] for field in
                    ("property", "source_company", "source_name", "document_number",
                     "posting_date", "currency", "total_amount")) or
                any(not isinstance(row[field], str) for field in
                    ("buyer_name", "source_invoice")) or
                row["source_key"] != _source_key(manifest["source_site"],
                    row["source_doctype"], row["source_name"]) or
                any(not isinstance(row[field], str) or not HEX64.fullmatch(row[field])
                    for field in ("source_key", "snapshot_sha256", "pdf_sha256")) or
                row["source_key"] in keys or
                {key: value for key, value in row.items() if key != "pdf_sha256"} !=
                    expected.get(row["source_key"])):
            frappe.throw(_("El documento fiscal del paquete es inválido"))
        keys.add(row["source_key"])
        pdf_name = "pdf/" + row["source_key"] + ".pdf"
        if names.count(pdf_name) != 1 or bundle.getinfo(pdf_name).file_size > MAX_PDF_BYTES:
            frappe.throw(_("Falta una copia PDF válida en el paquete fiscal"))
    if len(expected_evidence) != len(evidence):
        frappe.throw(_("El paquete omite evidencias de incidencias abiertas"))
    evidence_keys = set()
    for row in evidence:
        expected_fields = ({"source_key", "property", "source_company",
            "source_doctype", "source_name", "source_url", "file_name",
            "size", "sha256"} if manifest["schema_version"] >= 4 else
            {"source_key", "property", "source_company", "source_incident",
             "source_url", "file_name", "size", "sha256"})
        if (not isinstance(row, dict) or set(row) != expected_fields or
                row.get("source_key") in evidence_keys or
                row != expected_evidence.get(row.get("source_key")) or
                not isinstance(row.get("file_name"), str) or
                not row["file_name"] or len(row["file_name"]) > 180 or
                any(char in row["file_name"] for char in ("/", "\\")) or
                not isinstance(row.get("size"), int) or
                not 0 < row["size"] <= MAX_EVIDENCE_BYTES or
                not isinstance(row.get("sha256"), str) or
                not HEX64.fullmatch(row["sha256"])):
            frappe.throw(_("La evidencia del paquete es inválida"))
        evidence_keys.add(row["source_key"])
        entry = "evidence/" + row["source_key"]
        if (names.count(entry) != 1 or
                bundle.getinfo(entry).file_size != row["size"] or
                _hash(bundle.read(entry)) != row["sha256"]):
            frappe.throw(_("La evidencia del paquete no coincide con su huella"))
    if set(names) != {"manifest.json", "inventory.json"} | {
            "pdf/" + key + ".pdf" for key in keys} | {
            "evidence/" + key for key in evidence_keys}:
        frappe.throw(_("El paquete fiscal contiene archivos ajenos al manifiesto"))
    return manifest, inventory


def _target_bundle_path(file_name, expected_source_sha256,
                        expected_manifest_sha256):
    _admin()
    if provider() != "pms":
        frappe.throw(_("El paquete de origen se consulta en un sitio PMS"))
    if (not isinstance(file_name, str) or not re.fullmatch(
            r"hs-erp-fiscal-[0-9a-f]{32}\.zip", file_name) or
            not isinstance(expected_source_sha256, str) or
            not HEX64.fullmatch(expected_source_sha256) or
            not isinstance(expected_manifest_sha256, str) or
            not HEX64.fullmatch(expected_manifest_sha256)):
        frappe.throw(_("Revise el archivo y las huellas de la importación"))
    path = Path(frappe.get_site_path("private", "files", file_name))
    if not path.is_file():
        frappe.throw(_("No se encontró el paquete en los archivos privados del sitio"))
    return path


def load_source_inventory(file_name, expected_source_sha256,
                          expected_manifest_sha256):
    """Read a verified source inventory on the PMS target without writing."""
    path = _target_bundle_path(file_name, expected_source_sha256,
                               expected_manifest_sha256)
    with ZipFile(path) as bundle:
        return _manifest(bundle, expected_source_sha256,
                         expected_manifest_sha256)


def evidence_payloads(file_name, expected_source_sha256,
                      expected_manifest_sha256):
    """Read verified private evidence for rollback-only operational opening."""
    path = _target_bundle_path(file_name, expected_source_sha256,
                               expected_manifest_sha256)
    with ZipFile(path) as bundle:
        manifest, _ = _manifest(bundle, expected_source_sha256,
                                expected_manifest_sha256)
        return {(row["property"],
                 row.get("source_doctype") or "HS Incident",
                 row.get("source_name") or row.get("source_incident")): {
            "file_name": row["file_name"], "sha256": row["sha256"],
            "content": bundle.read("evidence/" + row["source_key"])}
            for row in manifest.get("evidence", [])}


def import_bundle(file_name, expected_source_sha256, expected_manifest_sha256,
                  property_mapping):
    """Import a verified bundle placed in the target site's private/files."""
    path = _target_bundle_path(file_name, expected_source_sha256,
                               expected_manifest_sha256)
    if isinstance(property_mapping, str):
        property_mapping = frappe.parse_json(property_mapping)
    if not isinstance(property_mapping, dict):
        frappe.throw(_("Indique el mapa de establecimientos de destino"))
    from frappe.utils.file_manager import save_file

    with ZipFile(path) as bundle:
        manifest, inventory = _manifest(bundle, expected_source_sha256,
                                        expected_manifest_sha256)
        source_properties = {row["property"] for row in inventory["properties"]}
        if set(property_mapping) != source_properties or any(
                not isinstance(name, str) or not name for name in property_mapping.values()):
            frappe.throw(_("El mapa no cubre exactamente los hoteles del archivo"))
        if len(set(property_mapping.values())) != len(property_mapping):
            frappe.throw(_("Dos hoteles de origen no pueden compartir un destino"))
        targets = {name: frappe.get_doc("HS Property", name)
                   for name in property_mapping.values()}
        if any(not prop.organization for prop in targets.values()):
            frappe.throw(_("Configure la entidad legal de cada hotel de destino"))
        # Verify the whole package before creating any destination record.
        for row in manifest["documents"]:
            pdf = bundle.read("pdf/" + row["source_key"] + ".pdf")
            if (not pdf.startswith(b"%PDF") or len(pdf) > MAX_PDF_BYTES or
                    _hash(pdf) != row["pdf_sha256"]):
                frappe.throw(_("La copia PDF de {0} no coincide").format(
                    row["source_name"]))
        imported = skipped = 0
        created_files = []
        before_operation = getattr(frappe.local, "hs_operation", False)
        before_import = getattr(frappe.local, "hs_fiscal_archive_import", False)
        frappe.local.hs_operation = True
        frappe.local.hs_fiscal_archive_import = True
        frappe.db.savepoint("hs_fiscal_archive_import")
        try:
            for row in manifest["documents"]:
                pdf = bundle.read("pdf/" + row["source_key"] + ".pdf")
                prop = targets[property_mapping[row["property"]]]
                current_name = frappe.db.get_value(DOCTYPE,
                    {"source_key": row["source_key"]}, "name")
                if current_name:
                    current = frappe.get_doc(DOCTYPE, current_name)
                    if (current.property != prop.name or
                            current.snapshot_sha256 != row["snapshot_sha256"] or
                            current.pdf_sha256 != row["pdf_sha256"]):
                        frappe.throw(_("El documento histórico ya existe con otros datos"))
                    _verified_content(current)
                    skipped += 1
                    continue
                doc = frappe.get_doc({"doctype": DOCTYPE, "company": prop.company,
                    "property": prop.name, "organization": prop.organization,
                    "source_key": row["source_key"],
                    "source_site": manifest["source_site"],
                    "source_company": row["source_company"],
                    "source_doctype": row["source_doctype"],
                    "source_name": row["source_name"],
                    "document_type": row["document_type"],
                    "document_number": row["document_number"],
                    "posting_date": row["posting_date"],
                    "buyer_name": row["buyer_name"],
                    "currency": row["currency"],
                    "total_amount": row["total_amount"],
                    "source_invoice": row["source_invoice"],
                    "status": row["status"],
                    "snapshot_sha256": row["snapshot_sha256"],
                    "pdf_sha256": row["pdf_sha256"],
                    "package_sha256": expected_manifest_sha256,
                    "archived_at": now_datetime()})
                doc.insert(ignore_permissions=True)
                attachment = save_file(row["source_key"] + ".pdf", pdf,
                    DOCTYPE, doc.name, is_private=1, df="pdf_file")
                created_files.append((attachment.file_url,
                    Path(attachment.get_full_path())))
                frappe.db.set_value(DOCTYPE, doc.name, "pdf_file",
                                    attachment.file_url, update_modified=False)
                imported += 1
        except Exception:
            frappe.db.rollback(save_point="hs_fiscal_archive_import")
            for url, file_path in created_files:
                if not frappe.db.exists("File", {"file_url": url}):
                    file_path.unlink(missing_ok=True)
            raise
        finally:
            frappe.local.hs_operation = before_operation
            frappe.local.hs_fiscal_archive_import = before_import
    return {"imported": imported, "already_present": skipped,
            "documents": imported + skipped,
            "verified_evidence": len(manifest.get("evidence", [])),
            "manifest_sha256": expected_manifest_sha256,
            "provider_changed": False}


def _verified_content(doc):
    if not doc.pdf_file or not doc.pdf_file.startswith("/private/files/"):
        frappe.throw(_("Falta el PDF privado del documento histórico"))
    name = frappe.db.get_value("File", {"file_url": doc.pdf_file,
        "attached_to_doctype": DOCTYPE, "attached_to_name": doc.name,
        "is_private": 1}, "name")
    if not name:
        frappe.throw(_("El PDF histórico perdió su vínculo privado"))
    file_doc = frappe.get_doc("File", name)
    content = file_doc.get_content()
    if not isinstance(content, bytes) or _hash(content) != doc.pdf_sha256:
        frappe.throw(_("La copia PDF histórica no coincide con su huella"))
    return content


def archive(property_name, offset=0, page_length=50, search=""):
    prop = require(property_name, "finance")
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación del archivo fiscal"))
    if offset < 0 or not 1 <= page_length <= 100 or not isinstance(search, str) or len(search) > 100:
        frappe.throw(_("Revise la búsqueda del archivo fiscal"))
    where = "property=%s AND company=%s"
    values = [prop.name, prop.company]
    if search.strip():
        where += " AND (document_number LIKE %s OR buyer_name LIKE %s OR source_name LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 3)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tab" + DOCTYPE + "` WHERE " + where,
                          values, as_list=True)[0][0]
    rows = frappe.db.sql("SELECT name,document_type,document_number,posting_date,"
        "buyer_name,currency,total_amount,status,source_doctype,source_name "
        "FROM `tab" + DOCTYPE + "` WHERE " + where +
        " ORDER BY posting_date DESC,creation DESC,name DESC LIMIT %s OFFSET %s",
        [*values, page_length, offset], as_dict=True)
    return {"property": prop.name, "total": int(total), "offset": offset,
            "page_length": page_length, "documents": rows}


def pdf_response(document):
    if not isinstance(document, str) or len(document) > 140:
        frappe.throw(_("Seleccione un documento histórico"))
    doc = frappe.get_doc(DOCTYPE, document)
    require(doc.property, "finance")
    doc.check_permission("read")
    content = _verified_content(doc)
    frappe.response["type"] = "download"
    frappe.response["filename"] = doc.source_key + ".pdf"
    frappe.response["filecontent"] = content
    frappe.response["content_type"] = "application/pdf"
    frappe.response["display_content_as"] = "inline"
