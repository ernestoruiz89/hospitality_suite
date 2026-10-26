"""Transactional ERPNext to PMS opening, callable only from an operator CLI.

The source remains frozen on its ERPNext site. This target keeps the immutable
opening receipt and its own verified pre-cutover backup before it can reopen.
"""

from hashlib import sha256
from pathlib import Path

import frappe
from frappe import _

from hospitality_suite import (erp_to_pms_freeze, erp_to_pms_transfer_rehearsal,
                               pms_cutover_backup, standalone_accounting)
from hospitality_suite.security import is_system
from hospitality_suite.service import audit, canonical, operation


DOCTYPE = "HS ERP to PMS Cutover Run"


def _administrator():
    if not is_system() or frappe.session.user != "Administrator":
        frappe.throw(_("Ejecute el corte desde Bench como Administrator"),
                     frappe.PermissionError)
    if (standalone_accounting.provider() != "pms" or
            "erpnext" in frappe.get_installed_apps()):
        frappe.throw(_("El destino debe ser un sitio PMS sin ERPNext"))


def _target_backup(manifest):
    if getattr(frappe.local, "hs_reverse_cutover_rehearsal", False):
        return None
    if not frappe.local.conf.get("maintenance_mode"):
        frappe.throw(_("Active mantenimiento en el destino antes del corte"),
                     frappe.PermissionError)
    from frappe.utils.doctor import any_job_pending

    if any_job_pending(site=frappe.local.site):
        frappe.throw(_("Espere los trabajos pendientes en el destino"))
    backup = pms_cutover_backup.verify(manifest)
    if any_job_pending(site=frappe.local.site):
        frappe.throw(_("Se inició un trabajo durante la verificación del respaldo"))
    return backup


def _locked_mode():
    rows = frappe.db.sql(
        "SELECT value FROM `tabSingles` WHERE doctype='HS Site Mode' "
        "AND field='provider' FOR UPDATE", as_list=True)
    if not rows or rows[0][0] != "PMS":
        frappe.throw(_("El destino no conserva el libro PMS activo"))
    frappe.clear_document_cache("HS Site Mode")
    mode = frappe.get_single("HS Site Mode")
    if mode.provider != "PMS":
        frappe.throw(_("El proveedor contable cambió durante el corte"))
    return mode


def _replayed_result(mode, reference, hashes):
    if mode.migration_reference != reference:
        frappe.throw(_("El sitio ya registra otro corte"))
    name = frappe.db.get_value(DOCTYPE,
        {"migration_reference": reference}, "name")
    if not name:
        frappe.throw(_("El corte activo no conserva un acta verificable"))
    record = frappe.get_doc(DOCTYPE, name)
    if any(record.get(field) != value for field, value in hashes.items()):
        frappe.throw(_("El reintento no coincide con el corte aplicado"))
    result = frappe.parse_json(record.result_json)
    saved_backup = result.get("target_backup") if isinstance(result, dict) else None
    if (not isinstance(result, dict) or
            not result.get("cutover_performed") or
            not result.get("reconciled") or result.get("provider_changed") or
            result.get("migration_reference") != reference or
            result.get("source_site") != record.source_site or
            result.get("source_sha256") != hashes["source_sha256"] or
            result.get("plan_sha256") != hashes["plan_sha256"] or
            result.get("receipt_sha256") != hashes["receipt_sha256"] or
            not erp_to_pms_freeze.HEX64.fullmatch(
                str(result.get("bundle_sha256") or "")) or
            not isinstance(saved_backup, dict) or
            saved_backup.get("sha256") !=
                hashes["target_backup_sha256"]):
        frappe.throw(_("El acta no conserva un resultado válido"))
    return result


def _clean_created_files(created_files):
    for url, path in created_files:
        if not frappe.db.exists("File", {"file_url": url}):
            Path(path).unlink(missing_ok=True)


def activate_validated(bundle_file, receipt_file, mapping, *,
                       source_sha256, manifest_sha256, receipt_sha256,
                       source_backup_sha256, mapping_sha256, plan_sha256,
                       target_backup_sha256, target_backup_manifest,
                       migration_reference, created_files):
    """Stage one verified opening and acta in the caller's DB transaction.

    Never commits. The caller holds a sitewide advisory lock through commit.
    """
    _administrator()
    if (not isinstance(migration_reference, str) or
            not migration_reference.strip() or
            migration_reference != migration_reference.strip() or
            len(migration_reference) > 140 or
            not isinstance(created_files, list)):
        frappe.throw(_("Indique una referencia y registro de archivos válidos"))
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if (not isinstance(mapping, dict) or
            sha256(canonical(mapping).encode()).hexdigest() != mapping_sha256):
        frappe.throw(_("Cambió el mapa de migración revisado"))
    hashes = {"source_sha256": source_sha256,
        "manifest_sha256": manifest_sha256,
        "receipt_sha256": receipt_sha256,
        "mapping_sha256": mapping_sha256,
        "plan_sha256": plan_sha256,
        "source_backup_sha256": source_backup_sha256,
        "target_backup_sha256": target_backup_sha256}
    if any(not isinstance(value, str) or not erp_to_pms_freeze.HEX64.fullmatch(value)
           for value in hashes.values()):
        frappe.throw(_("Indique las huellas revisadas del corte"))
    savepoint = "hs_erp_to_pms_activation_" + frappe.generate_hash(length=12)
    frappe.db.savepoint(savepoint)
    try:
        mode = _locked_mode()
        if mode.migration_reference:
            return _replayed_result(mode, migration_reference, hashes)
        if frappe.db.exists(DOCTYPE, {"migration_reference": migration_reference}):
            frappe.throw(_("La referencia del corte ya fue utilizada"))
        backup = _target_backup(target_backup_manifest)
        if (backup is not None and
                backup["sha256"] != target_backup_sha256):
            frappe.throw(_("Cambió el respaldo del destino"))
        receipt = erp_to_pms_freeze.verify_on_target(receipt_file,
            receipt_sha256, bundle_file, source_sha256,
            manifest_sha256, source_backup_sha256)
        opened = erp_to_pms_transfer_rehearsal._publish_validated(bundle_file,
            source_sha256, manifest_sha256, mapping, plan_sha256,
            created_files)
        if not opened.get("reconciled") or opened.get("provider_changed"):
            frappe.throw(_("La apertura PMS no quedó conciliada"))
        for row in opened["properties"]:
            prop = frappe.get_doc("HS Property", row["property"])
            with operation(prop):
                audit(prop, "ERPNext to PMS cutover", prop,
                    details={"migration_reference": migration_reference,
                             "source_site": receipt["source_site"],
                             "source_sha256": source_sha256,
                             "plan_sha256": plan_sha256})
        result = frappe.parse_json(canonical({**opened,
            "cutover_performed": True,
            "migration_reference": migration_reference,
            "source_site": receipt["source_site"],
            "bundle_file": bundle_file,
            "bundle_sha256": receipt["bundle_sha256"],
            "receipt_file": receipt_file,
            "receipt_sha256": receipt_sha256,
            "source_backup_sha256": source_backup_sha256,
            "target_backup": backup or {"sha256": target_backup_sha256}}))
        previous_flag = getattr(frappe.local, "hs_provider_cutover", False)
        frappe.local.hs_provider_cutover = True
        try:
            mode.cutover_date = frappe.utils.today()
            mode.migration_reference = migration_reference
            mode.save(ignore_permissions=True)
            frappe.get_doc({"doctype": DOCTYPE,
                "migration_reference": migration_reference,
                "source_site": receipt["source_site"], **hashes,
                "performed_by": frappe.session.user,
                "performed_at": frappe.utils.now_datetime(),
                "result_json": canonical(result)}).insert(ignore_permissions=True)
        finally:
            frappe.local.hs_provider_cutover = previous_flag
        return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        frappe.clear_document_cache("HS Site Mode")
        _clean_created_files(created_files)
        raise


def rehearse_activation(bundle_file, receipt_file, mapping, *,
                        source_sha256, manifest_sha256, receipt_sha256,
                        source_backup_sha256, mapping_sha256, plan_sha256,
                        migration_reference):
    """Run the full publication and acta writer, then undo the transaction."""
    savepoint = "hs_erp_to_pms_rehearsal_" + frappe.generate_hash(length=12)
    created_files = []
    frappe.db.savepoint(savepoint)
    old_flag = getattr(frappe.local, "hs_reverse_cutover_rehearsal", False)
    frappe.local.hs_reverse_cutover_rehearsal = True
    try:
        result = activate_validated(bundle_file, receipt_file, mapping,
            source_sha256=source_sha256, manifest_sha256=manifest_sha256,
            receipt_sha256=receipt_sha256,
            source_backup_sha256=source_backup_sha256,
            mapping_sha256=mapping_sha256, plan_sha256=plan_sha256,
            target_backup_sha256="0" * 64, target_backup_manifest=None,
            migration_reference=migration_reference,
            created_files=created_files)
        return {**result, "cutover_performed": False, "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
        frappe.clear_document_cache("HS Site Mode")
        _clean_created_files(created_files)
        frappe.local.hs_reverse_cutover_rehearsal = old_flag
