"""ERPNext report routes must stay out of a Frappe-only PMS site."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api


class TestReportProviderGate(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.set_user, frappe.session.user)
        frappe.set_user("Administrator")
        self.property_name = frappe.db.get_value("HS Property", {}, "name")
        self.assertTrue(self.property_name)

    def test_erp_report_routes_reject_pms_before_loading_report_queries(self):
        with patch.object(api.standalone_accounting, "provider", return_value="pms"), \
                patch("hospitality_suite.report_queries.scopes",
                    side_effect=AssertionError("ERP report scope was queried")):
            routes = (
                lambda: api.report(self.property_name, "Auditoría"),
                lambda: api.report_options(self.property_name, "Auditoría"),
                lambda: api.report_page(self.property_name, "Auditoría"),
                lambda: api.export_report(self.property_name, "Auditoría"),
                lambda: api.erp_report_catalog(self.property_name),
            )
            for route in routes:
                with self.subTest(route=route.__code__.co_firstlineno):
                    with self.assertRaisesRegex(frappe.ValidationError,
                            "Use los reportes PMS"):
                        route()
