import frappe

no_cache=1


def get_context(context):
    context.title=frappe._("Solicitar una reserva")
