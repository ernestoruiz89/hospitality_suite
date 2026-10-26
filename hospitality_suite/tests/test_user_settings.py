"""The personal profile is scoped to the session, not to a hotel."""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import user_settings


class TestUserSettings(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("manager@hospitality.example.invalid")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_self_service_profile_does_not_change_access(self):
        original = user_settings.read()
        self.assertEqual(original["user"], "manager@hospitality.example.invalid")
        before_access = frappe.db.count("HS Access", {"user": original["user"]})
        before_roles = set(frappe.get_roles(original["user"]))
        values = {field: original[field] for field in
            ("first_name", "last_name", "language", "time_zone")}
        values.update(first_name="Gerencia perfil", time_zone="America/Managua",
            expected_modified=original["modified"])
        changed = user_settings.save(values)
        self.assertEqual(changed["first_name"], "Gerencia perfil")
        self.assertEqual(changed["time_zone"], "America/Managua")
        self.assertEqual(frappe.db.count("HS Access", {"user": original["user"]}), before_access)
        self.assertEqual(set(frappe.get_roles(original["user"])), before_roles)
        with self.assertRaises(frappe.ValidationError):
            user_settings.save(values)
        with self.assertRaises(frappe.ValidationError):
            user_settings.save({**values, "expected_modified": changed["modified"],
                "roles": ["System Manager"]})
        with self.assertRaises(frappe.ValidationError):
            user_settings.save({**values, "expected_modified": changed["modified"],
                "time_zone": "Invalid/Zone"})

    def test_guest_cannot_read_or_save(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            user_settings.read()
        with self.assertRaises(frappe.PermissionError):
            user_settings.save({})
