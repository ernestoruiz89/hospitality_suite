import json
from pathlib import Path

import frappe
from hospitality_suite.portal import confirmation

no_cache=1


def get_context(context):
    data = confirmation(frappe.form_dict.get("token") or "")
    page = Path(frappe.get_app_path("hospitality_suite", "public", "frontend", "confirmation.html"))
    if not page.is_file():
        frappe.throw(frappe._("Compile la interfaz con npm run build en frontend antes de abrir la confirmación."))
    serialized = frappe.as_json(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    csrf = json.dumps(frappe.sessions.get_csrf_token()).replace("<", "\\u003c")
    context.spa_html = page.read_text(encoding="utf-8").replace(
        "</head>", f"<script>window.hs_confirmation = {serialized}; window.csrf_token = {csrf};</script></head>", 1)
    context.no_cache = 1
    return context
