"""Take each site to the UI supported by its current ledger authority."""

import frappe

from hospitality_suite.standalone_accounting import provider

no_cache = 1


def get_context(context):
    frappe.local.flags.redirect_location = (
        "/hospitality/app" if provider() == "pms" else "/desk/hospitality-suite/hospitality-home"
    )
    raise frappe.Redirect
