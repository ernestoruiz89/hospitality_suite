"""Personal settings for the authenticated user, independent of a property."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe


def _current_user():
    name = frappe.session.user
    if not name or name == "Guest":
        frappe.throw(frappe._("Inicie sesión para configurar su usuario"), frappe.PermissionError)
    return frappe.get_doc("User", name)


def read():
    user = _current_user()
    languages = frappe.get_all("Language", filters={"enabled": 1},
        fields=["name", "language_name"], order_by="language_name asc")
    return {
        "user": user.name,
        "email": user.email,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "language": user.language or "",
        "time_zone": user.time_zone or "",
        "modified": str(user.modified),
        "languages": languages,
    }


def save(data):
    user = _current_user()
    if not isinstance(data, dict) or set(data) != {
        "first_name", "last_name", "language", "time_zone", "expected_modified"
    }:
        frappe.throw(frappe._("Revise los datos de su usuario"))
    if not data["expected_modified"] or str(user.modified) != str(data["expected_modified"]):
        frappe.throw(frappe._("Su usuario cambió; recargue la configuración antes de guardar"))
    first, last = data["first_name"], data["last_name"]
    language, time_zone = data["language"], data["time_zone"]
    if any(not isinstance(value, str) for value in (first, last, language, time_zone)):
        frappe.throw(frappe._("Revise los datos de su usuario"))
    first, last, language, time_zone = (value.strip() for value in
        (first, last, language, time_zone))
    if not first or len(first) > 140 or len(last) > 140:
        frappe.throw(frappe._("Indique un nombre de hasta 140 caracteres"))
    if language and not frappe.db.exists("Language", {"name": language, "enabled": 1}):
        frappe.throw(frappe._("Seleccione un idioma habilitado"))
    if time_zone:
        try:
            ZoneInfo(time_zone)
        except (ValueError, ZoneInfoNotFoundError):
            frappe.throw(frappe._("Indique una zona horaria IANA válida"))
    user.first_name, user.last_name = first, last
    user.language, user.time_zone = language, time_zone
    user.save(ignore_permissions=True)
    return read()
