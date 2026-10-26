"""Serve the React shell through Frappe, keeping API requests on the same origin."""

import json
from pathlib import Path

import frappe

no_cache = 1


def get_context(context):
    index = Path(frappe.get_app_path("hospitality_suite", "public", "frontend", "index.html"))
    if not index.is_file():
        frappe.throw(frappe._("Compile la interfaz con npm run build en frontend antes de abrirla."))
    html = index.read_text(encoding="utf-8")
    csrf = json.dumps(frappe.sessions.get_csrf_token()).replace("<", "\\u003c")
    html = html.replace("</head>", f"<script>window.csrf_token = {csrf};</script></head>", 1)
    context.spa_html = html
    context.no_cache = 1
    return context
