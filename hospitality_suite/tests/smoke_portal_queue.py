"""Rollback-only check of the scoped reception queue on an installed site."""

from datetime import timedelta
import time
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from hospitality_suite import api, pms_cutover, portal
from hospitality_suite.security import has_scope_permission, scope_query


def run():
    previous_user = frappe.session.user
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_portal_queue_probe")
    suffix = uuid4().hex[:16]
    prop = frappe.get_doc({"doctype": "HS Property",
        "name": "SMOKE-PORTAL-PROPERTY-" + suffix,
        "property_name": "Hotel de cola " + suffix,
        "company": "SMOKE-PORTAL-COMPANY-" + suffix,
        "organization": "SMOKE-PORTAL-COMPANY-" + suffix,
        "currency": "NIO", "mode": "Hotel", "portal_enabled": 1,
        "time_zone": "America/Managua"})
    prop.db_insert()
    now = now_datetime()
    names = ["SMOKE-PORTAL-" + uuid4().hex[:16] for _ in range(4)]
    try:
        for index, name in enumerate(names):
            frappe.db.sql(
                "INSERT INTO `tabHS Portal Request` "
                "(name,creation,modified,modified_by,owner,docstatus,idx,property,company,"
                "full_name,email,category,mode,rooms,people,starts_at,ends_at,status,"
                "hold_until,request_until,amount,currency) "
                "VALUES (%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s,%s,%s,1,1,%s,%s,%s,%s,%s,100,%s)",
                (name, now, now, "Administrator", "Administrator",
                 prop.name if index < 3 else "MISSING-PROPERTY-" + suffix,
                 prop.company if index != 2 else "OTHER-COMPANY-" + name,
                 "Queue Test Guest", f"queue{index}@example.invalid", "SMOKE-CATEGORY",
                 prop.mode if prop.mode != "Mixed" else "Hotel", now + timedelta(days=1),
                 now + timedelta(days=2), "Hold" if index == 0 else "Requested",
                 now + timedelta(minutes=30) if index == 0 else None,
                 now - timedelta(minutes=1) if index else None, prop.currency))
        page = api.portal_request_queue(prop.name, 0, 1, "Queue Test Guest")
        assert page["total"] == 2 and page["has_more"] and len(page["rows"]) == 1
        other = api.portal_request_queue(prop.name, 1, 1, "Queue Test Guest")
        rows = page["rows"] + other["rows"]
        assert {row["name"] for row in rows} == set(names[:2])
        assert {row["expired"] for row in rows} == {True, False}
        assert all(row["starts_at"] and row["ends_at"] for row in rows)
        assert api.portal_request_queue(prop.name, 0, 25, "absent@example.invalid")["total"] == 0
        scoped = frappe.db.sql("SELECT name FROM `tabHS Portal Request` WHERE " +
            scope_query("HS Portal Request") + " AND property=%s ORDER BY name",
            prop.name, as_list=True)
        assert {row[0] for row in scoped} == set(names[:2])
        assert has_scope_permission(frappe.get_doc("HS Portal Request", names[0]))
        assert not has_scope_permission(frappe.get_doc("HS Portal Request", names[2]))
        mismatched = pms_cutover._scope_integrity()
        assert any(row["code"] == "scoped_company_mismatch" and
                   row["source"] == names[2] for row in mismatched)
        assert any(row["code"] == "scoped_property_missing" and
                   row["source"] == names[3] for row in mismatched)
        good_token = portal.sign({"doctype": "HS Portal Request", "name": names[0],
                                  "expires": int(time.time()) + 60})
        assert portal.confirmation(good_token)["status"] == "Hold"
        wrong_company_token = portal.sign({"doctype": "HS Portal Request", "name": names[2],
                                           "expires": int(time.time()) + 60})
        try:
            portal.confirmation(wrong_company_token)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Confirmation exposed a request from another company")
        staff = "hs-portal-scope-" + suffix + "@example.invalid"
        with patch("frappe.enqueue", return_value=None):
            frappe.get_doc({"doctype": "User", "email": staff,
                "first_name": "Reception scope", "enabled": 1,
                "send_welcome_email": 0, "roles": [{"role": "HS Receptionist"}]}).insert(
                    ignore_permissions=True)
        frappe.db.sql("INSERT INTO `tabHS Access` "
            "(name,creation,modified,modified_by,owner,docstatus,idx,user,property,company) "
            "VALUES (%s,%s,%s,%s,%s,0,0,%s,%s,%s)",
            ("SMOKE-PORTAL-ACCESS-" + suffix, now, now, "Administrator",
             "Administrator", staff, prop.name, prop.company))
        frappe.set_user(staff)
        listed = frappe.get_list("HS Portal Request", filters={"property": prop.name},
                                  fields=["name"], limit_page_length=10)
        assert {row.name for row in listed} == set(names[:2])
        frappe.get_doc("HS Portal Request", names[0]).check_permission("read")
        try:
            frappe.get_doc("HS Portal Request", names[2]).check_permission("read")
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Receptionist read a mismatched-company request")
        frappe.set_user("Guest")
        try:
            api.portal_request_queue(prop.name)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Guest accessed the staff portal queue")
        return {"property": prop.name, "scoped_rows": len(rows), "guest_denied": True}
    finally:
        frappe.db.rollback(save_point="hs_portal_queue_probe")
        frappe.set_user(previous_user)
