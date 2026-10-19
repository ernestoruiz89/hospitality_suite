import frappe
from hospitality_suite.portal import confirmation

no_cache=1


def get_context(context):
    context.title="Confirmación de alojamiento"
    context.confirmation=confirmation(frappe.form_dict.get("token") or "")
