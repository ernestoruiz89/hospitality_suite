"""Render the authenticated guest portal with Frappe session and CSRF."""

import json
from pathlib import Path

import frappe

no_cache = 1


def get_context(context):
    page = Path(frappe.get_app_path("hospitality_suite", "public", "frontend", "guest.html"))
    if not page.is_file():
        frappe.throw(frappe._("Compile la interfaz con npm run build en frontend antes de abrir el portal."))
    csrf = json.dumps(frappe.sessions.get_csrf_token()).replace("<", "\\u003c")
    session = json.dumps({"logged_in": frappe.session.user != "Guest"})
    script = f"<script>window.csrf_token = {csrf}; window.hs_guest_session = {session};</script>"
    context.spa_html = page.read_text(encoding="utf-8").replace("</head>", script + "</head>", 1)
    context.no_cache = 1
    return context
