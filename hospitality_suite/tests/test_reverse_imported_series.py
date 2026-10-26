"""Imported operation names must leave Frappe's next series number usable."""

import unittest

import frappe
from frappe.model.naming import NamingSeries, make_autoname

from hospitality_suite.erp_to_pms_operations import _advance_imported_series


class TestReverseImportedSeries(unittest.TestCase):
    def test_current_and_neighboring_years_advance_without_lowering_counters(self):
        if not (frappe.conf.get("allow_tests") and
                frappe.conf.get("hospitality_integration_test_site") and
                frappe.conf.get("pause_scheduler")):
            self.skipTest("Requires an isolated paused test site")
        current_year = int(frappe.utils.nowdate()[:4])
        years = (current_year - 1, current_year, current_year + 1)
        series = {year: NamingSeries(f"CAR-.{year}.-.#####")
                  for year in years}
        original = {year: item.get_current_value()
                    for year, item in series.items()}
        expected = {year: original[year] + 3 for year in years}
        names = [f"CAR-{year}-{expected[year]:05d}" for year in years]
        frappe.db.savepoint("hs_reverse_imported_series_test")
        try:
            _advance_imported_series({"charges": names})
            self.assertEqual({year: item.get_current_value()
                              for year, item in series.items()}, expected)

            _advance_imported_series({"charges": [
                f"CAR-{year}-{original[year] + 1:05d}" for year in years]})
            self.assertEqual({year: item.get_current_value()
                              for year, item in series.items()}, expected)

            next_name = make_autoname("CAR-.YYYY.-.#####")
            self.assertEqual(next_name,
                             f"CAR-{current_year}-{expected[current_year] + 1:05d}")
        finally:
            frappe.db.rollback(save_point="hs_reverse_imported_series_test")
        self.assertEqual({year: item.get_current_value()
                          for year, item in series.items()}, original)
