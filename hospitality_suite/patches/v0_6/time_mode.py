"""Rename the persisted operating mode without rewriting accepted snapshots."""

import frappe

from hospitality_suite.mode import LEGACY_TIME_MODE, TIME_MODE


def execute():
    for doctype in ("HS Property", "HS Rate", "HS Portal Request"):
        if frappe.db.table_exists(doctype):
            frappe.db.sql(
                f"UPDATE `tab{doctype}` SET mode=%s WHERE mode=%s",
                (TIME_MODE, LEGACY_TIME_MODE),
            )
    frappe.db.sql(
        "UPDATE `tabHS Property` SET property_name=%s WHERE property_name=%s",
        ("Luna Demo · Por tiempo", "Motel Luna Demo"),
    )
    frappe.db.sql(
        "UPDATE `tabHS Property` SET brand_name=%s WHERE brand_name=%s",
        ("Luna Demo · Por tiempo", "Motel Luna Demo"),
    )
    frappe.db.sql(
        "UPDATE `tabItem` SET item_name=%s WHERE item_code=%s AND item_name=%s",
        ("Hora adicional por tiempo", "HS-DEMO-EXTRA-HOUR", "Hora adicional de motel"),
    )
