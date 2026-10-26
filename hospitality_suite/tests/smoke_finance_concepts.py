"""Rollback-only concept management check on the local PMS smoke site."""

from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.standalone_accounting import provider


def run():
    if (frappe.local.site not in ("hs-pms-smoke.local", "hs-pms-audit-target.local") or
            provider() != "pms"):
        raise AssertionError("Use exclusivamente el sitio PMS descartable de ensayo")
    frappe.set_user("Administrator")
    try:
        properties = frappe.get_all("HS Property", pluck="name", limit_page_length=1)
        if not properties:
            raise AssertionError("El sitio de ensayo no tiene un establecimiento configurado")
        prop = frappe.get_doc("HS Property", properties[0])
        income = frappe.db.get_value("HS Account", {
            "property": prop.name, "organization": prop.organization,
            "root_type": "Income", "account_currency": prop.currency,
            "active": 1, "is_group": 0})
        if not income:
            raise AssertionError("El sitio de ensayo no tiene cuenta de ingreso activa")
        suffix = uuid4().hex[:10]
        values = {"label": "Ingreso de prueba " + suffix,
            "nature": "Other Income", "account": income}
        created = api.execute(prop.name, "pms_income_concept",
            "concept-create-" + suffix, values)["concept"]
        concept = frappe.get_doc("HS Treasury Concept", created)
        snapshot = api.pms_financing_snapshot(prop.name)
        assert any(row.name == created for row in snapshot["concepts"])
        assert any(row.name == created and row.active for row in
            snapshot["concept_settings"])
        inactive_created = api.execute(prop.name, "pms_income_concept",
            "concept-inactive-" + suffix,
            {**values, "label": "Ingreso inactivo " + suffix,
             "active": 0})["concept"]
        snapshot = api.pms_financing_snapshot(prop.name)
        assert not any(row.name == inactive_created for row in snapshot["concepts"])
        assert any(row.name == inactive_created and not row.active for row in
            snapshot["concept_settings"])
        update = {"concept": created, "modified": str(concept.modified),
            **values, "active": 0}
        result = api.execute(prop.name, "pms_income_concept_update",
            "concept-update-" + suffix, update)
        assert api.execute(prop.name, "pms_income_concept_update",
            "concept-update-" + suffix, update) == result
        snapshot = api.pms_financing_snapshot(prop.name)
        assert not any(row.name == created for row in snapshot["concepts"])
        assert any(row.name == created and not row.active for row in
            snapshot["concept_settings"])
        other_properties = frappe.get_all("HS Property", filters={
            "name": ["!=", prop.name]}, pluck="name", limit_page_length=1)
        if other_properties:
            try:
                api.execute(other_properties[0], "pms_income_concept_update",
                    "concept-foreign-" + suffix, {**update,
                        "modified": str(frappe.db.get_value(
                            "HS Treasury Concept", created, "modified"))})
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("Otro establecimiento editó el concepto")
        try:
            api.execute(prop.name, "pms_income_concept_update",
                "concept-stale-" + suffix, update)
        except frappe.TimestampMismatchError:
            pass
        else:
            raise AssertionError("Se aceptó una versión anterior del concepto")
        return {"created": True, "created_inactive": True, "inactive_hidden": True,
            "inactive_manageable": True, "idempotent": True,
            "stale_rejected": True, "cross_property_rejected": True,
            "rolled_back": True}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
