"""Open the staff React application for either accounting provider."""

import frappe

no_cache = 1


def get_context(context):
    frappe.local.flags.redirect_location = "/hospitality/app"
    raise frappe.Redirect
