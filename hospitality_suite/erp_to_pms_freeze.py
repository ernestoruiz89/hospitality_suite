"""Private source-freeze receipt for an ERPNext to PMS transfer.

The source operator keeps ERPNext in maintenance after exporting. The target
verifies the copied bundle and receipt before a future persistent transfer.
"""

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import frappe
from frappe import _

from hospitality_suite import erp_fiscal_history, pms_cutover_backup
from hospitality_suite.security import is_system
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


HEX64 = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_NAME = re.compile(r"hs-erp-freeze-[0-9a-f]{32}\.json\Z")
BUNDLE_NAME = re.compile(r"hs-erp-fiscal-[0-9a-f]{32}\.zip\Z")
FIELDS = frozenset({"schema_version", "source_site", "source_sha256",
    "manifest_sha256", "bundle_file", "bundle_sha256", "backup_sha256"})
POLICY_BLOCKER = "reverse_transfer_not_implemented"


def _administrator():
    if not is_system() or frappe.session.user != "Administrator":
        frappe.throw(_("Ejecute la congelación desde Bench como Administrator"),
                     frappe.PermissionError)


def _root():
    return Path(frappe.get_site_path("private", "files")).resolve()


def _private_file(name, pattern):
    if not isinstance(name, str) or not pattern.fullmatch(name):
        frappe.throw(_("Revise el nombre del archivo privado del corte"))
    root = _root()
    path = root / name
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        frappe.throw(_("El archivo privado del corte no está disponible"))
    return path


def _file_hash(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_source():
    if (provider() != "erpnext" or
            "erpnext" not in frappe.get_installed_apps() or
            not frappe.local.conf.get("maintenance_mode")):
        frappe.throw(_("Congele el sitio ERPNext en mantenimiento antes de exportar"))
    from frappe.utils.doctor import any_job_pending

    if any_job_pending(site=frappe.local.site):
        frappe.throw(_("Espere los trabajos pendientes antes de exportar"))


def _source_blockers(rows):
    return [row for row in rows if not (isinstance(row, dict) and
        row.get("code") == POLICY_BLOCKER and len(row) == 1)]


def export_frozen(expected_source_sha256, backup_manifest,
                  preview_bundle_file=None, preview_manifest_sha256=None):
    """Seal the reviewed bundle, or render one, after a verified native backup."""
    _administrator()
    _frozen_source()
    if not isinstance(expected_source_sha256, str) or not HEX64.fullmatch(
            expected_source_sha256):
        frappe.throw(_("Indique la huella revisada de la fuente ERPNext"))
    backup = pms_cutover_backup.verify(backup_manifest)
    if not isinstance(backup.get("sha256"), str) or not HEX64.fullmatch(
            backup["sha256"]):
        frappe.throw(_("El respaldo no conserva una huella válida"))
    from hospitality_suite.erp_to_pms_preflight import preflight

    source = preflight()
    if (source["source_sha256"] != expected_source_sha256 or
            _source_blockers(source["blockers"])):
        frappe.throw(_("La fuente cambió o conserva bloqueos; repita el diagnóstico"))
    if (preview_bundle_file is None) != (preview_manifest_sha256 is None):
        frappe.throw(_("Indique juntos el ZIP revisado y su huella de manifiesto"))
    exported = None
    created_bundle = False
    receipt_path = None
    try:
        if preview_bundle_file is None:
            exported = erp_fiscal_history.export_bundle(expected_source_sha256)
            created_bundle = True
        else:
            if (not isinstance(preview_manifest_sha256, str) or
                    not HEX64.fullmatch(preview_manifest_sha256)):
                frappe.throw(_("La huella del manifiesto revisado no es válida"))
            preview_path = _private_file(preview_bundle_file, BUNDLE_NAME)
            with ZipFile(preview_path) as bundle:
                manifest, _inventory = erp_fiscal_history._manifest(bundle,
                    expected_source_sha256, preview_manifest_sha256)
                if manifest["source_site"] != frappe.local.site:
                    frappe.throw(_("El paquete revisado pertenece a otro sitio"))
                for row in manifest["documents"]:
                    pdf = bundle.read("pdf/" + row["source_key"] + ".pdf")
                    if (not pdf.startswith(b"%PDF") or
                            len(pdf) > erp_fiscal_history.MAX_PDF_BYTES or
                            _file_hash_bytes(pdf) != row["pdf_sha256"]):
                        frappe.throw(_("El PDF revisado ya no coincide con su huella"))
            exported = {"file_name": preview_bundle_file,
                "manifest_sha256": preview_manifest_sha256}
        bundle_path = _private_file(exported["file_name"], BUNDLE_NAME)
        _frozen_source()
        if (preflight()["source_sha256"] != expected_source_sha256 or
                pms_cutover_backup.verify(backup_manifest)["sha256"] !=
                    backup["sha256"]):
            frappe.throw(_("La fuente o el respaldo cambió durante la exportación"))
        receipt = {"schema_version": 1, "source_site": str(frappe.local.site),
            "source_sha256": expected_source_sha256,
            "manifest_sha256": exported["manifest_sha256"],
            "bundle_file": exported["file_name"],
            "bundle_sha256": _file_hash(bundle_path),
            "backup_sha256": backup["sha256"]}
        if not all(HEX64.fullmatch(receipt[field]) for field in (
                "manifest_sha256", "bundle_sha256", "backup_sha256")):
            frappe.throw(_("El paquete no conserva huellas completas"))
        receipt_path = _root() / ("hs-erp-freeze-" + uuid4().hex + ".json")
        encoded = canonical(receipt).encode("utf-8")
        with receipt_path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return {"receipt_file": receipt_path.name,
            "receipt_sha256": sha256(encoded).hexdigest(), **receipt}
    except Exception:
        if receipt_path is not None:
            receipt_path.unlink(missing_ok=True)
        if created_bundle and exported is not None:
            (_root() / exported["file_name"]).unlink(missing_ok=True)
        raise


def _file_hash_bytes(content):
    return sha256(content).hexdigest()


def export_frozen_file(backup_file, expected_source_sha256,
                       preview_bundle_file=None, preview_manifest_sha256=None):
    """Bench entry point using a backup manifest in private/files."""
    _administrator()
    from hospitality_suite.pms_cutover_cli import _json_file

    return export_frozen(expected_source_sha256, _json_file(backup_file),
        preview_bundle_file, preview_manifest_sha256)


def verify_on_target(receipt_file, receipt_sha256, bundle_file,
                     source_sha256, manifest_sha256, backup_sha256):
    """Verify copied freeze evidence and all bundle contents without writing."""
    _administrator()
    if provider() != "pms" or "erpnext" in frappe.get_installed_apps():
        frappe.throw(_("Verifique el recibo en el sitio PMS sin ERPNext"))
    if any(not isinstance(value, str) or not HEX64.fullmatch(value)
           for value in (receipt_sha256, source_sha256, manifest_sha256,
                         backup_sha256)):
        frappe.throw(_("Indique las cuatro huellas revisadas"))
    path = _private_file(receipt_file, RECEIPT_NAME)
    if path.stat().st_size > 4096:
        frappe.throw(_("El recibo de congelación es demasiado grande"))
    encoded = path.read_bytes()
    if sha256(encoded).hexdigest() != receipt_sha256:
        frappe.throw(_("El recibo de congelación cambió"))
    try:
        receipt = json.loads(encoded)
    except (UnicodeError, ValueError):
        frappe.throw(_("El recibo de congelación no es JSON válido"))
    if (not isinstance(receipt, dict) or set(receipt) != FIELDS or
            canonical(receipt).encode("utf-8") != encoded or
            receipt["schema_version"] != 1 or
            not isinstance(receipt["source_site"], str) or
            not receipt["source_site"] or
            receipt["source_site"] == frappe.local.site or
            receipt["source_sha256"] != source_sha256 or
            receipt["manifest_sha256"] != manifest_sha256 or
            receipt["backup_sha256"] != backup_sha256 or
            receipt["bundle_file"] != bundle_file or
            not isinstance(receipt["bundle_sha256"], str) or
            not HEX64.fullmatch(receipt["bundle_sha256"])):
        frappe.throw(_("El recibo no corresponde a la fuente y respaldo revisados"))
    bundle_path = _private_file(bundle_file, BUNDLE_NAME)
    if _file_hash(bundle_path) != receipt["bundle_sha256"]:
        frappe.throw(_("El ZIP cambió durante el traslado"))
    manifest, inventory = erp_fiscal_history.load_source_inventory(
        bundle_file, source_sha256, manifest_sha256)
    if (manifest["source_site"] != receipt["source_site"] or
            _source_blockers(inventory["blockers"])):
        frappe.throw(_("El paquete congelado no corresponde a una fuente lista"))
    return {"verified": True, **receipt,
        "receipt_sha256": receipt_sha256}
