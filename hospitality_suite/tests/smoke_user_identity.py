"""Check that user creation and hotel access are separate on a synthetic PMS site.

Run with ``bench --site hs-pms-smoke-reverse.local execute
hospitality_suite.tests.smoke_user_identity.run``. The transaction is rolled back.
"""

import uuid

import frappe

from hospitality_suite import api
from hospitality_suite.schema import ROLES


def run():
    if not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente un sitio sintético de pruebas")
    frappe.set_user("Administrator")
    email = f"identity-{uuid.uuid4().hex[:10]}@example.invalid"
    try:
        properties = api.bootstrap()["properties"]
        assert len(properties) >= 2
        created = api.create_operational_user({"email": email, "first_name": "Prueba de usuario"})
        assert created["user"] == email
        assert not frappe.db.exists("HS Access", {"user": email})
        assert not set(frappe.get_roles(email)).intersection(ROLES)

        frappe.set_user(email)
        assert api.bootstrap()["properties"] == []
        assert api.my_user_settings()["user"] == email
        try:
            api.create_operational_user({"email": "unauthorized@example.invalid",
                "first_name": "Sin permiso"})
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Un usuario operativo creó otra identidad")

        frappe.set_user("Administrator")
        api.execute(properties[0]["name"], "assign_user", uuid.uuid4().hex,
            {"email": email, "roles": ["HS Receptionist"], "reason": "Prueba de separación"})
        assert frappe.db.exists("HS Access", {"user": email,
            "property": properties[0]["name"]})
        assert not frappe.db.exists("HS Access", {"user": email,
            "property": properties[1]["name"]})
        frappe.set_user(email)
        assert [row["name"] for row in api.bootstrap()["properties"]] == [properties[0]["name"]]
        print("User identity separation OK: creation, permission, hotel grant")
    finally:
        frappe.set_user("Administrator")
        frappe.db.rollback()
