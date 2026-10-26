"""Verify a complete native Bench backup before a persistent PMS cutover.

The operator enables site maintenance, drains jobs, runs ``bench backup
--with-files`` and calls ``prepare`` to obtain a manifest. Only files in the
site's private backup directory are accepted. No backup contents are returned.
"""

import json
import re
from hashlib import sha256
from pathlib import Path

import frappe
from frappe import _

from hospitality_suite.security import is_system
from hospitality_suite.service import canonical


ROLES = ("database", "public_files", "private_files", "site_config")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _backup_root():
    return Path(frappe.get_site_path("private", "backups")).resolve()


def _live_config():
    return Path(frappe.get_site_path("site_config.json")).resolve()


def _expected_names(database_name):
    slug = re.escape(frappe.local.site.replace(".", "_"))
    match = re.fullmatch(
        rf"(?P<stamp>\d{{8}}_\d{{6}})-{slug}-database(?P<enc>-enc)?\.sql\.gz",
        database_name)
    if not match:
        frappe.throw(_("El respaldo de base de datos no corresponde a este sitio"))
    prefix = f"{match['stamp']}-{frappe.local.site.replace('.', '_')}"
    enc = match["enc"] or ""
    return {
        "database": {database_name},
        "site_config": {f"{prefix}-site_config_backup{enc}.json"},
        "public_files": {f"{prefix}-files{enc}.{ext}" for ext in ("tar", "tgz")},
        "private_files": {f"{prefix}-private-files{enc}.{ext}" for ext in ("tar", "tgz")},
    }


def _hash_file(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest):
    """Return a normalized manifest and its digest after checking every file."""
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede verificar respaldos"),
                     frappe.PermissionError)
    if not isinstance(manifest, dict) or set(manifest) != set(ROLES):
        frappe.throw(_("Indique los cuatro archivos del respaldo completo"))
    database = manifest.get("database")
    if not isinstance(database, dict) or not isinstance(database.get("name"), str):
        frappe.throw(_("Revise el manifiesto del respaldo"))
    expected = _expected_names(database["name"])
    root = _backup_root()
    config_time = _live_config().stat().st_mtime_ns
    normalized = {}
    for role in ROLES:
        entry = manifest.get(role)
        if (not isinstance(entry, dict) or set(entry) != {"name", "sha256"} or
                not isinstance(entry["name"], str) or
                entry["name"] not in expected[role] or
                not isinstance(entry["sha256"], str) or
                not HEX64.fullmatch(entry["sha256"])):
            frappe.throw(_("El archivo {0} no coincide con el respaldo completo").format(role))
        path = root / entry["name"]
        if (path.is_symlink() or path.resolve().parent != root or
                not path.is_file() or path.stat().st_size == 0 or
                path.stat().st_mtime_ns < config_time):
            frappe.throw(_("El archivo {0} falta o precede al modo mantenimiento").format(role))
        if _hash_file(path) != entry["sha256"]:
            frappe.throw(_("Cambió el contenido del respaldo {0}").format(role))
        normalized[role] = {"name": entry["name"], "sha256": entry["sha256"]}
    if (normalized["public_files"]["name"].rsplit(".", 1)[-1] !=
            normalized["private_files"]["name"].rsplit(".", 1)[-1]):
        frappe.throw(_("Los archivos públicos y privados usan formatos distintos"))
    config_path = root / normalized["site_config"]["name"]
    try:
        saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        frappe.throw(_("El respaldo de configuración no se puede leer"))
    if (saved_config.get("maintenance_mode") not in (1, True, "1") or
            saved_config.get("db_name") != frappe.local.conf.get("db_name")):
        frappe.throw(_("La configuración respaldada no corresponde al sitio congelado"))
    return {"files": normalized,
            "sha256": sha256(canonical(normalized).encode()).hexdigest()}


def prepare():
    """Find and hash the newest complete native backup on a frozen site."""
    if not is_system() or not frappe.local.conf.get("maintenance_mode"):
        frappe.throw(_("Prepare el respaldo con el sitio en mantenimiento"),
                     frappe.PermissionError)
    root = _backup_root()
    slug = frappe.local.site.replace(".", "_")
    candidates = sorted(root.glob(f"????????_??????-{slug}-database*.sql.gz"),
                        reverse=True)
    for database in candidates:
        try:
            expected = _expected_names(database.name)
        except frappe.ValidationError:
            continue
        names = {"database": database.name}
        for role in ROLES[1:]:
            found = sorted(name for name in expected[role] if
                           (root / name).is_file())
            if not found:
                break
            names[role] = found[0]
        if len(names) != len(ROLES):
            continue
        manifest = {role: {"name": names[role],
                           "sha256": _hash_file(root / names[role])}
                    for role in ROLES}
        verify(manifest)
        return manifest
    frappe.throw(_("No hay un respaldo completo y reciente de este sitio"))
