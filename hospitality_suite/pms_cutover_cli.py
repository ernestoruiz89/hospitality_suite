"""Operator-only Bench entry point for a reviewed PMS to ERPNext cutover.

Place the mapping and backup manifest JSON in the site's private/files folder.
Run ``review_file`` before freezing the site, then use the returned hashes as
explicit arguments to ``activate_file`` after maintenance and backup.
Neither function is whitelisted for HTTP access.
"""

import json
import re
from hashlib import sha256
from pathlib import Path

import frappe
from frappe import _

from hospitality_suite import pms_cutover_activation, pms_cutover_backup, pms_cutover_plan
from hospitality_suite.security import is_system
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,140}\.json\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _private_root():
    return Path(frappe.get_site_path("private", "files")).resolve()


def _json_file(name):
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        frappe.throw(_("Indique el nombre de un JSON en private/files"))
    root = _private_root()
    path = root / name
    if (path.is_symlink() or path.resolve().parent != root or
            not path.is_file() or not 0 < path.stat().st_size <= 5_000_000):
        frappe.throw(_("El archivo JSON privado falta o excede 5 MB"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        frappe.throw(_("El archivo privado no contiene JSON válido"))
    if not isinstance(value, dict):
        frappe.throw(_("El archivo privado debe contener un objeto JSON"))
    return value


def prepare_backup_file(name):
    """Save the verified native backup manifest without overwriting a review."""
    _administrator()
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        frappe.throw(_("Indique el nombre de un JSON en private/files"))
    manifest = pms_cutover_backup.prepare()
    digest = pms_cutover_backup.verify(manifest)["sha256"]
    path = _private_root() / name
    if path.is_symlink() or path.exists() or path.resolve().parent != _private_root():
        frappe.throw(_("El manifiesto privado ya existe o su ruta no es válida"))
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(canonical(manifest) + "\n")
    except OSError:
        frappe.throw(_("No se pudo guardar el manifiesto privado"))
    return {"backup_file": name, "backup_sha256": digest}


def _administrator():
    if not is_system() or frappe.session.user != "Administrator":
        frappe.throw(_("Ejecute el corte desde Bench como Administrator"),
                     frappe.PermissionError)
    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw(_("Instale ERPNext antes del corte"))


def _fresh_transaction():
    """Discard any pre-lock read snapshot before reviewing committed state."""
    frappe.db.rollback()


def review_file(mapping_file):
    """Read a private mapping and return hashes for an explicit cutover review."""
    _administrator()
    if provider() != "pms":
        frappe.throw(_("La revisión requiere el libro PMS activo"))
    mapping = _json_file(mapping_file)
    pms_cutover_activation._settings(mapping)
    reviewed = pms_cutover_plan.review(mapping)
    plan = reviewed.get("plan") or {}
    links = reviewed.get("link_manifest") or {}
    return {"ready": bool(reviewed["cutover_inputs_consistent"]),
        "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
        "source_sha256": plan.get("source_sha256"),
        "plan_sha256": plan.get("plan_sha256"),
        "link_sha256": links.get("link_sha256"),
        "mapping_blockers": reviewed["mapping_review"].get("mapping_blockers", []),
        "source_blockers": reviewed["mapping_review"].get("source_blockers", []),
        "plan_blockers": plan.get("blockers", []),
        "link_blockers": links.get("blockers", [])}


def activate_file(mapping_file, backup_file, *, source_sha256,
                  mapping_sha256, plan_sha256, link_sha256,
                  backup_sha256, migration_reference):
    """Commit one validated cutover; a matching retry returns the saved acta."""
    _administrator()
    expected = (source_sha256, mapping_sha256, plan_sha256,
                link_sha256, backup_sha256)
    if any(not isinstance(value, str) or not _HASH.fullmatch(value)
           for value in expected):
        frappe.throw(_("Indique las cinco huellas revisadas del corte"))
    if (not isinstance(migration_reference, str) or
            not migration_reference.strip() or
            migration_reference != migration_reference.strip()):
        frappe.throw(_("Indique una referencia de corte sin espacios externos"))
    # A waiting SELECT FOR UPDATE on the Single provider row can deadlock with
    # Frappe's delete-and-insert implementation of Single.save(). Serialize
    # before touching that row, including the acta replay path.
    lock_name = "hs-cutover-" + sha256(frappe.local.site.encode()).hexdigest()[:48]
    acquired = frappe.db.sql("SELECT GET_LOCK(%s, 600)", lock_name)[0][0]
    if acquired != 1:
        frappe.throw(_("No se pudo reservar el corte del sitio"))
    try:
        # The waiter may have opened a repeatable-read snapshot before the
        # first process committed. Start a fresh transaction under the lock.
        _fresh_transaction()
        mapping = _json_file(mapping_file)
        manifest = _json_file(backup_file)
        if sha256(canonical(mapping).encode()).hexdigest() != mapping_sha256:
            frappe.throw(_("Cambió el archivo de mapeo revisado"))
        savepoint = "hs_cutover_cli_" + frappe.generate_hash(length=12)
        frappe.db.savepoint(savepoint)
        try:
            mode = pms_cutover_activation._locked_mode()
            if mode.provider == "PMS":
                backup = pms_cutover_backup.verify(manifest)
                if backup["sha256"] != backup_sha256:
                    frappe.throw(_("Cambió el respaldo revisado"))
                pms_cutover_activation._settings(mapping)
                reviewed = pms_cutover_plan.review(mapping)
                plan = reviewed.get("plan") or {}
                links = reviewed.get("link_manifest") or {}
                if (not reviewed["cutover_inputs_consistent"] or
                        (plan.get("source_sha256"), plan.get("plan_sha256"),
                         links.get("link_sha256")) !=
                            (source_sha256, plan_sha256, link_sha256)):
                    frappe.throw(_("La fuente, el plan o los enlaces cambiaron; repita el ensayo"))
            elif mode.provider != "ERPNext":
                frappe.throw(_("El sitio ya registra un corte o cambió de proveedor"))
            result = pms_cutover_activation.activate_validated(mapping,
                source_sha256=source_sha256, plan_sha256=plan_sha256,
                link_sha256=link_sha256,
                migration_reference=migration_reference,
                backup_manifest=manifest)
            saved_backup = result.get("backup") or {}
            if (not result.get("cutover_performed") or
                    saved_backup.get("sha256") != backup_sha256 or
                    provider() != "erpnext"):
                frappe.throw(_("El corte no conservó su acta y respaldo verificados"))
            acta = frappe.db.get_value("HS Cutover Run",
                {"migration_reference": migration_reference}, "name")
            if not acta:
                frappe.throw(_("El corte no conservó su acta"))
            response = {"cutover_performed": True,
                    "migration_reference": migration_reference,
                    "cutover_run": acta,
                    "property_count": len(result.get("properties") or [])}
        except Exception:
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                # MariaDB has already discarded savepoints after a deadlock.
                frappe.db.rollback()
            pms_cutover_activation._clear_cutover_metadata()
            raise
        try:
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            pms_cutover_activation._clear_cutover_metadata()
            raise
        return response
    finally:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)
