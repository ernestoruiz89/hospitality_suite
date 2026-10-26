"""Internal, transactional PMS to ERPNext authority switch and rollback rehearsal.

No public HTTP API calls this module. A caller that persists the result must own
the transaction and operate the native maintenance and backup procedure.
"""

from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite import pms_cutover_rehearsal
from hospitality_suite.pms_cutover_mapping import TARGET_FIELDS, REQUIRED_SETTINGS
from hospitality_suite.security import is_system
from hospitality_suite.service import audit, canonical, operation
from hospitality_suite.standalone_accounting import provider


def _require_frozen_site(backup_manifest):
    """The live authority switch runs only after native site maintenance."""
    if getattr(frappe.local, "hs_cutover_rehearsal", False):
        return None
    if not frappe.local.conf.get("maintenance_mode"):
        frappe.throw(_("Active el modo mantenimiento antes del corte contable"),
                     frappe.PermissionError)
    from frappe.utils.doctor import any_job_pending

    if any_job_pending(site=frappe.local.site):
        frappe.throw(_("Espere a que terminen los trabajos pendientes antes del corte"))
    from hospitality_suite.pms_cutover_backup import verify

    backup = verify(backup_manifest)
    if any_job_pending(site=frappe.local.site):
        frappe.throw(_("Se inició un trabajo mientras se verificaba el respaldo"))
    return backup


def _clear_cutover_metadata():
    from hospitality_suite.schema import ERP_LINK_TARGETS

    frappe.clear_document_cache("HS Site Mode")
    for doctype in {name for name, _field in ERP_LINK_TARGETS}:
        frappe.clear_cache(doctype=doctype)


def _settings(mapping):
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if not isinstance(mapping, dict) or not isinstance(mapping.get("properties"), dict):
        frappe.throw(_("Indique un mapa de migración válido"))
    for property_name, cfg in mapping["properties"].items():
        settings = cfg.get("target_settings") if isinstance(cfg, dict) else None
        if (not isinstance(settings, dict) or
                set(settings) - set(TARGET_FIELDS) - {"tax_policy_confirmed"} or
                ("tax_policy_confirmed" in settings and
                 not isinstance(settings["tax_policy_confirmed"], bool)) or
                any(not isinstance(settings.get(field), str) or
                    not settings[field].strip() for field in REQUIRED_SETTINGS)):
            frappe.throw(_("Complete los ajustes ERPNext de {0}").format(property_name))
        company = cfg.get("company")
        for field, doctype in TARGET_FIELDS.items():
            target = settings.get(field)
            if target in (None, ""):
                continue
            if not isinstance(target, str) or target != target.strip():
                frappe.throw(_("Revise el destino ERPNext de {0}").format(field))
            meta = frappe.get_meta(doctype)
            row = frappe.db.get_value(doctype, target,
                [field for field in ("name", "company", "is_group", "disabled")
                 if field == "name" or meta.has_field(field)], as_dict=True)
            if (not row or (row.get("company") and row.company != company) or
                    row.get("is_group") or row.get("disabled")):
                frappe.throw(_("El destino ERPNext de {0} no pertenece a la compañía o no admite movimientos").format(field))
            if field == "price_list":
                details = frappe.db.get_value("Price List", target,
                    ["enabled", "selling", "currency"], as_dict=True)
                if (not details or not details.enabled or not details.selling or
                        details.currency != frappe.db.get_value(
                            "HS Property", property_name, "currency")):
                    frappe.throw(_("Seleccione una lista de precios de venta activa en la moneda del establecimiento"))
    return mapping


def _locked_mode():
    # All cutover attempts serialize on the one sitewide authority row. A
    # property lock alone cannot protect the retry path after activation.
    rows = frappe.db.sql(
        "SELECT value FROM `tabSingles` WHERE doctype='HS Site Mode' "
        "AND field='provider' FOR UPDATE", as_list=True)
    if not rows:
        frappe.throw(_("Configure el proveedor contable del sitio antes del corte"))
    frappe.clear_document_cache("HS Site Mode")
    mode = frappe.get_single("HS Site Mode")
    if mode.provider != rows[0][0]:
        frappe.throw(_("El proveedor contable cambió durante el corte"))
    return mode


def _replayed_result(mode, reference, hashes, backup_sha256):
    if mode.provider != "ERPNext" or mode.migration_reference != reference:
        frappe.throw(_("El sitio ya registra un corte o cambió de proveedor"))
    record_name = frappe.db.get_value("HS Cutover Run",
        {"migration_reference": reference}, "name")
    if not record_name:
        frappe.throw(_("El corte activo no conserva un acta verificable"))
    record = frappe.get_doc("HS Cutover Run", record_name)
    if any(record.get(field) != value for field, value in hashes.items()):
        frappe.throw(_("El reintento no coincide con los datos del corte aplicado"))
    result = frappe.parse_json(record.result_json)
    if not isinstance(result, dict) or not result.get("cutover_performed"):
        frappe.throw(_("El acta del corte no conserva un resultado válido"))
    saved_backup = result.get("backup")
    if (saved_backup.get("sha256") if isinstance(saved_backup, dict) else None) != backup_sha256:
        frappe.throw(_("El reintento no coincide con el respaldo del corte aplicado"))
    return result


def activate_validated(mapping, *, source_sha256, plan_sha256,
                       link_sha256, migration_reference, backup_manifest=None):
    """Apply one reviewed transfer and switch the provider in the same DB transaction.

    This helper never commits and is not whitelisted. It rolls back its own
    changes on failure so a caller may inspect the database safely afterward.
    """
    if not is_system() or "erpnext" not in frappe.get_installed_apps():
        frappe.throw(_("El corte requiere administración y ERPNext instalado"),
                     frappe.PermissionError)
    if (not isinstance(migration_reference, str) or not migration_reference.strip() or
            len(migration_reference.strip()) > 140):
        frappe.throw(_("Identifique el respaldo y acta del corte"))
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if not isinstance(mapping, dict):
        frappe.throw(_("Indique un mapa de migración válido"))
    reference = migration_reference.strip()
    hashes = {"source_sha256": source_sha256,
              "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
              "plan_sha256": plan_sha256, "link_sha256": link_sha256}
    backup_sha256 = (sha256(canonical(backup_manifest).encode()).hexdigest()
                     if isinstance(backup_manifest, dict) else None)
    savepoint = "hs_cutover_activation_" + frappe.generate_hash(length=12)
    frappe.db.savepoint(savepoint)
    try:
        mode = _locked_mode()
        if mode.provider == "ERPNext":
            return _replayed_result(mode, reference, hashes, backup_sha256)
        if mode.provider != "PMS" or mode.migration_reference or provider() != "pms":
            frappe.throw(_("El sitio ya registra un corte o cambió de proveedor"))
        backup = _require_frozen_site(backup_manifest)
        if frappe.db.exists("HS Cutover Run", {"migration_reference": reference}):
            frappe.throw(_("La referencia del corte ya fue utilizada"))
        mapping = _settings(mapping)
        transferred = pms_cutover_rehearsal.transfer_validated(mapping,
            source_sha256=source_sha256, plan_sha256=plan_sha256,
            link_sha256=link_sha256)
        if mode.provider != "PMS" or mode.migration_reference:
            frappe.throw(_("El sitio ya registra un corte o cambió de proveedor"))
        previous_flag = getattr(frappe.local, "hs_provider_cutover", False)
        frappe.local.hs_provider_cutover = True
        try:
            mode.provider = "ERPNext"
            mode.cutover_date = frappe.utils.today()
            mode.migration_reference = reference
            mode.save(ignore_permissions=True)
        finally:
            frappe.local.hs_provider_cutover = previous_flag
        from hospitality_suite.install import restore_erp_links
        restore_erp_links()
        from hospitality_suite.install import validate_financial_configuration
        for property_name, cfg in mapping["properties"].items():
            prop = frappe.get_doc("HS Property", property_name, for_update=True)
            if prop.company != cfg["company"]:
                frappe.throw(_("La compañía del establecimiento cambió durante el corte"))
            prop.cost_center = cfg["cost_center"]
            prop.update({key: value for key, value in cfg["target_settings"].items()
                         if key in TARGET_FIELDS and value})
            prop.financial_enabled = 1
            with operation(prop):
                prop.save(ignore_permissions=True)
                validate_financial_configuration(prop)
                audit(prop, "PMS to ERPNext cutover", prop,
                    details={"migration_reference": mode.migration_reference,
                             "source_sha256": source_sha256,
                             "plan_sha256": plan_sha256,
                             "link_sha256": link_sha256,
                             "vouchers": next(row["vouchers"] for row in
                                 transferred["properties"] if row["property"] == property_name)})
        if provider() != "erpnext":
            frappe.throw(_("El proveedor ERPNext no quedó activo"))
        result = frappe.parse_json(canonical({**transferred,
            "migration_reference": reference, "cutover_performed": True,
            **({"backup": backup} if backup else {})}))
        previous_flag = getattr(frappe.local, "hs_provider_cutover", False)
        frappe.local.hs_provider_cutover = True
        try:
            frappe.get_doc({"doctype": "HS Cutover Run",
                "migration_reference": reference, **hashes,
                "performed_by": frappe.session.user,
                "performed_at": frappe.utils.now_datetime(),
                "result_json": canonical(result)}).insert(ignore_permissions=True)
        finally:
            frappe.local.hs_provider_cutover = previous_flag
        return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        _clear_cutover_metadata()
        raise


def rehearse_activation(mapping, *, source_sha256, plan_sha256,
                        link_sha256, migration_reference):
    """Exercise the authority switch and post-transfer configuration, then undo it."""
    savepoint = "hs_cutover_activation_test_" + frappe.generate_hash(length=12)
    frappe.db.savepoint(savepoint)
    previous_flag = getattr(frappe.local, "hs_cutover_rehearsal", False)
    frappe.local.hs_cutover_rehearsal = True
    try:
        result = activate_validated(mapping, source_sha256=source_sha256,
            plan_sha256=plan_sha256, link_sha256=link_sha256,
            migration_reference=migration_reference)
        return {**result, "activation_rehearsed": True,
                "cutover_performed": False}
    finally:
        frappe.db.rollback(save_point=savepoint)
        _clear_cutover_metadata()
        frappe.local.hs_cutover_rehearsal = previous_flag
