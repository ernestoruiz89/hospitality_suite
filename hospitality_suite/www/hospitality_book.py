"""Render the public React booking flow on the same origin as Frappe."""

import json
from pathlib import Path

import frappe

no_cache = 1


def get_context(context):
    portal = Path(frappe.get_app_path("hospitality_suite", "public", "frontend", "portal.html"))
    if not portal.is_file():
        frappe.throw(frappe._("Compile la interfaz con npm run build en frontend antes de abrir las reservas."))
    html = portal.read_text(encoding="utf-8")
    csrf = json.dumps(frappe.sessions.get_csrf_token()).replace("<", "\\u003c")
    context.spa_html = html.replace("</head>", f"<script>window.csrf_token = {csrf};</script></head>", 1)
    context.no_cache = 1
    return context
