"""Frozen source receipt checks; uses private disposable files only."""

import json
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe

from hospitality_suite import erp_to_pms_freeze
from hospitality_suite.service import canonical


def run():
    if not frappe.local.site.startswith("hs-erp-smoke") or "erpnext" not in (
            frappe.get_installed_apps()):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    frappe.set_user("Administrator")
    prior_maintenance = frappe.local.conf.get("maintenance_mode")
    source_hash = "a" * 64
    backup_hash = "b" * 64
    manifest_hash = "c" * 64
    files = []
    exported_names = []

    def fake_export(expected):
        if expected != source_hash:
            frappe.throw("La exportación recibió otra huella")
        name = "hs-erp-fiscal-" + uuid4().hex + ".zip"
        path = Path(frappe.get_site_path("private", "files", name))
        path.write_bytes(b"disposable-source-package-" + name.encode())
        files.append(path)
        exported_names.append(name)
        return {"file_name": name, "manifest_sha256": manifest_hash}

    clean = {"source_sha256": source_hash,
        "blockers": [{"code": "reverse_transfer_not_implemented"}]}
    try:
        with (patch.object(erp_to_pms_freeze, "provider",
                           return_value="erpnext"),
              patch("frappe.utils.doctor.any_job_pending", return_value=False),
              patch.object(erp_to_pms_freeze.pms_cutover_backup, "verify",
                           return_value={"sha256": backup_hash}),
              patch("hospitality_suite.erp_to_pms_preflight.preflight",
                    return_value=clean),
              patch.object(erp_to_pms_freeze.erp_fiscal_history,
                           "export_bundle", side_effect=fake_export)):
            frappe.local.conf.maintenance_mode = 0
            try:
                erp_to_pms_freeze.export_frozen(source_hash, {})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La fuente permitió exportar sin mantenimiento")
            frappe.local.conf.maintenance_mode = 1
            result = erp_to_pms_freeze.export_frozen(source_hash, {})
            receipt_path = Path(frappe.get_site_path("private", "files",
                result["receipt_file"]))
            files.append(receipt_path)
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            checks = {
                "one_bundle": len(exported_names) == 1,
                "receipt_hash": sha256(receipt_bytes).hexdigest() ==
                    result["receipt_sha256"],
                "canonical": receipt_bytes == canonical(receipt).encode(),
                "source": receipt["source_sha256"] == source_hash,
                "backup": receipt["backup_sha256"] == backup_hash,
                "manifest": receipt["manifest_sha256"] == manifest_hash,
                "bundle_name": receipt["bundle_file"] == exported_names[0],
                "bundle_hash": receipt["bundle_sha256"] ==
                    sha256(files[0].read_bytes()).hexdigest()}
            if not all(checks.values()):
                frappe.throw("El recibo no vinculó: " +
                    ", ".join(name for name, passed in checks.items() if not passed))
        with (patch.object(erp_to_pms_freeze, "provider",
                           return_value="erpnext"),
              patch("frappe.utils.doctor.any_job_pending", return_value=False),
              patch.object(erp_to_pms_freeze.pms_cutover_backup, "verify",
                           return_value={"sha256": backup_hash}),
              patch("hospitality_suite.erp_to_pms_preflight.preflight",
                    side_effect=[clean, {**clean, "source_sha256": "e" * 64}]),
              patch.object(erp_to_pms_freeze.erp_fiscal_history,
                           "export_bundle", side_effect=fake_export)):
            try:
                erp_to_pms_freeze.export_frozen(source_hash, {})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La fuente cambió durante una exportación congelada")
            if len(exported_names) != 2 or files[-1].exists():
                frappe.throw("El ZIP rechazado quedó en el sitio")
        return {"frozen_receipt": True, "source_change_rejected": True,
                "unfrozen_source_rejected": True}
    finally:
        frappe.local.conf.maintenance_mode = prior_maintenance
        for path in files:
            path.unlink(missing_ok=True)
