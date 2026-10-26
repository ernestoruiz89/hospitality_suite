"""Give historical PMS receivables their original operational date as due date."""

import frappe


def execute():
    if frappe.db.table_exists("HS PMS Receivable"):
        frappe.db.sql(
            "UPDATE `tabHS PMS Receivable` SET due_date=business_date "
            "WHERE due_date IS NULL"
        )
