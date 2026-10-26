"""Bench-only review and persistent ERPNext to PMS cutover on the target.

The operator transfers the frozen source ZIP and receipt, reviews an explicit
mapping, freezes and backs up the empty PMS target, then calls activate_file.
No function in this module is whitelisted for HTTP requests.
"""

import re
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite import (erp_to_pms_activation, erp_to_pms_freeze,
                               erp_to_pms_transfer_plan, pms_cutover_backup)
from hospitality_suite.pms_cutover_cli import _json_file, _private_root
from hospitality_suite.service import canonical


_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,140}\.json\Z")


def prepare_backup_file(name):
    """Save the newest verified complete backup of the frozen PMS target."""
    erp_to_pms_activation._administrator()
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        frappe.throw(_("Indique un nombre JSON en private/files"))
    manifest = pms_cutover_backup.prepare()
    digest = pms_cutover_backup.verify(manifest)["sha256"]
    root = _private_root()
    path = root / name
    if path.is_symlink() or path.exists() or path.resolve().parent != root:
        frappe.throw(_("El manifiesto privado ya existe o su ruta no es válida"))
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(canonical(manifest) + "\n")
    except OSError:
        frappe.throw(_("No se pudo guardar el manifiesto privado"))
    return {"backup_file": name, "backup_sha256": digest}


def review_file(mapping_file, receipt_file, bundle_file, *,
                source_sha256, manifest_sha256, receipt_sha256,
                source_backup_sha256):
    """Review copied evidence and report the exact hashes required at cutover."""
    erp_to_pms_activation._administrator()
    receipt = erp_to_pms_freeze.verify_on_target(receipt_file,
        receipt_sha256, bundle_file, source_sha256,
        manifest_sha256, source_backup_sha256)
    mapping = _json_file(mapping_file)
    plan = erp_to_pms_transfer_plan.review(bundle_file, source_sha256,
        manifest_sha256, mapping)
    return {"ready": bool(plan["arithmetically_balanced"]),
        "source_site": receipt["source_site"],
        "source_sha256": source_sha256,
        "manifest_sha256": manifest_sha256,
        "receipt_sha256": receipt_sha256,
        "source_backup_sha256": source_backup_sha256,
        "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
        "plan_sha256": plan.get("plan_sha256"),
        "blockers": plan["blockers"]}


def activate_file(mapping_file, receipt_file, bundle_file,
                  target_backup_file, *, source_sha256, manifest_sha256,
                  receipt_sha256, source_backup_sha256, mapping_sha256,
                  plan_sha256, target_backup_sha256, migration_reference):
    """Commit one opening and its acta; matching retries return the same acta."""
    erp_to_pms_activation._administrator()
    hashes = (source_sha256, manifest_sha256, receipt_sha256,
        source_backup_sha256, mapping_sha256, plan_sha256,
        target_backup_sha256)
    if any(not isinstance(value, str) or
           not erp_to_pms_freeze.HEX64.fullmatch(value) for value in hashes):
        frappe.throw(_("Indique las siete huellas revisadas del corte"))
    if (not isinstance(migration_reference, str) or
            not migration_reference.strip() or
            migration_reference != migration_reference.strip() or
            len(migration_reference) > 140):
        frappe.throw(_("Indique una referencia de corte válida"))
    lock_name = "hs-cutover-" + sha256(frappe.local.site.encode()).hexdigest()[:48]
    if frappe.db.sql("SELECT GET_LOCK(%s, 600)", lock_name)[0][0] != 1:
        frappe.throw(_("No se pudo reservar el corte del sitio"))
    created_files = []
    try:
        # A waiter must discard its older repeatable-read snapshot under the
        # advisory lock before it checks the sitewide migration reference.
        frappe.db.rollback()
        mapping = _json_file(mapping_file)
        target_backup = _json_file(target_backup_file)
        savepoint = "hs_erp_to_pms_cli_" + frappe.generate_hash(length=12)
        frappe.db.savepoint(savepoint)
        try:
            result = erp_to_pms_activation.activate_validated(bundle_file,
                receipt_file, mapping, source_sha256=source_sha256,
                manifest_sha256=manifest_sha256,
                receipt_sha256=receipt_sha256,
                source_backup_sha256=source_backup_sha256,
                mapping_sha256=mapping_sha256,
                plan_sha256=plan_sha256,
                target_backup_sha256=target_backup_sha256,
                target_backup_manifest=target_backup,
                migration_reference=migration_reference,
                created_files=created_files)
            record = frappe.db.get_value(
                erp_to_pms_activation.DOCTYPE,
                {"migration_reference": migration_reference}, "name")
            if (not result.get("cutover_performed") or
                    not result.get("reconciled") or
                    not record or
                    frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                    frappe.db.get_single_value("HS Site Mode", "migration_reference") !=
                        migration_reference):
                frappe.throw(_("El corte no conservó su acta y conciliación"))
        except Exception:
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                frappe.db.rollback()
            frappe.clear_document_cache("HS Site Mode")
            erp_to_pms_activation._clean_created_files(created_files)
            raise
        try:
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.clear_document_cache("HS Site Mode")
            erp_to_pms_activation._clean_created_files(created_files)
            raise
        return {"cutover_performed": True,
            "migration_reference": migration_reference,
            "cutover_run": record,
            "property_count": len(result["properties"])}
    finally:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)
