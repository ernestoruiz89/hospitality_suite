"""Rollback-only profile check on an already configured local smoke site."""

import frappe
from uuid import uuid4

from hospitality_suite import user_settings


def run():
    account = f"profile-smoke-{uuid4().hex[:12]}@example.invalid"
    frappe.get_doc({"doctype": "User", "email": account, "first_name": "Profile",
        "user_type": "System User", "send_welcome_email": 0}).insert(ignore_permissions=True)
    frappe.set_user(account)
    try:
        original = user_settings.read()
        access_count = frappe.db.count("HS Access", {"user": account})
        roles = set(frappe.get_roles(account))
        values = {field: original[field] for field in
            ("first_name", "last_name", "language", "time_zone")}
        values.update(first_name="Perfil de prueba", expected_modified=original["modified"])
        changed = user_settings.save(values)
        assert changed["user"] == account and changed["first_name"] == "Perfil de prueba"
        assert frappe.db.count("HS Access", {"user": account}) == access_count
        assert set(frappe.get_roles(account)) == roles
        for invalid in (values, {**values, "expected_modified": changed["modified"],
                                   "roles": ["System Manager"]},
                        {**values, "expected_modified": changed["modified"],
                                   "time_zone": "Invalid/Zone"}):
            try:
                user_settings.save(invalid)
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("El perfil aceptó una actualización inválida")
        frappe.set_user("Guest")
        try:
            user_settings.read()
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Guest pudo consultar el perfil")
        return {"user": account, "saved": True, "roles_unchanged": True,
                "access_unchanged": True, "rolled_back": True}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
