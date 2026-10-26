import frappe

no_cache=1


def get_context(context):
    frappe.local.flags.redirect_location = "/hospitality-book"
    raise frappe.Redirect
