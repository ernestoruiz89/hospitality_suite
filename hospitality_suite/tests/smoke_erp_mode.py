"""Read-only checks on a disposable Frappe + ERPNext + Suite site."""

import frappe

from hospitality_suite.schema import ERP_LINK_TARGETS
from hospitality_suite.standalone_accounting import provider


def run():
    if not frappe.local.site.startswith("hs-erp-smoke"):
        frappe.throw("Use únicamente el sitio de ensayo ERPNext")
    assert "erpnext" in frappe.get_installed_apps()
    assert provider() == "erpnext"
    for (doctype, field), target in ERP_LINK_TARGETS.items():
        if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("DocType", target):
            continue
        actual = frappe.get_meta(doctype).get_field(field)
        assert actual and (actual.fieldtype, actual.options) == ("Link", target), (doctype, field)
    assert frappe.db.get_single_value("HS Site Mode", "provider") == "ERPNext"
    return {"provider": "erpnext", "restored_links": len(ERP_LINK_TARGETS)}
