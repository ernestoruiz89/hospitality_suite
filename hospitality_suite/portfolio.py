"""Cross-property operational and receivables dashboard, without FX assumptions."""
from collections import defaultdict

import frappe
from frappe.utils import getdate, get_datetime, nowdate, now_datetime

from hospitality_suite.pricing import decimal
from hospitality_suite.security import allowed_properties, require


def snapshot():
    names = allowed_properties()
    if not names:
        frappe.throw(frappe._("No tiene establecimientos autorizados"), frappe.PermissionError)
    require(names[0], "report")
    properties = frappe.get_all("HS Property", filters={"name": ["in", names]},
                                fields=["name", "property_name", "company", "mode", "currency", "business_date", "time_zone"],
                                order_by="property_name asc")
    rows = []
    totals = defaultdict(lambda: {"receivable": decimal(0), "overdue": decimal(0), "unbilled": decimal(0)})
    today = getdate(nowdate())
    instant = now_datetime()
    for prop in properties:
        active_rooms = set(frappe.get_all("HS Room", filters={"property": prop.name, "active": 1}, pluck="name"))
        occupied = {r.room for r in frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"}, fields=["room"])} & active_rooms
        blocked = {r.room for r in frappe.get_all("HS Allocation", filters={"property": prop.name,
                                                    "kind": ["in", ["Maintenance", "Room Block"]], "status": "Active"},
                                                    fields=["room", "starts_at", "ends_at"])
                   if get_datetime(r.starts_at) <= instant and (not r.ends_at or get_datetime(r.ends_at) > instant)} & active_rooms
        tickets = frappe.db.count("HS Guest Ticket", {"property": prop.name, "status": ["in", ["Open", "In Progress"]]})
        overdue_tickets = frappe.db.count("HS Guest Ticket", {"property": prop.name, "status": ["in", ["Open", "In Progress"]], "due_at": ["<", instant]})
        invoices = frappe.db.sql("""SELECT COALESCE(NULLIF(party_account_currency,''),currency) AS account_currency,
            SUM(outstanding_amount) AS receivable,
            SUM(CASE WHEN due_date < %s THEN outstanding_amount ELSE 0 END) AS overdue
            FROM `tabSales Invoice`
            WHERE hs_property=%s AND company=%s AND docstatus=1 AND outstanding_amount>0
            GROUP BY account_currency""", (today, prop.name, prop.company), as_dict=True)
        amounts = defaultdict(lambda: {"receivable": decimal(0), "overdue": decimal(0), "unbilled": decimal(0)})
        for inv in invoices:
            amounts[inv.account_currency]["receivable"] += decimal(inv.receivable)
            amounts[inv.account_currency]["overdue"] += decimal(inv.overdue)
        pending = frappe.db.sql("""SELECT f.currency, SUM(c.amount) AS amount
            FROM `tabHS Folio` f JOIN `tabHS Charge` c ON c.folio=f.name
            WHERE f.property=%s AND f.company=%s AND c.status='Pending'
            GROUP BY f.currency""", (prop.name, prop.company), as_dict=True)
        for item in pending:
            amounts[item.currency]["unbilled"] += decimal(item.amount)
        for currency, values in amounts.items():
            for key, amount in values.items():
                totals[currency][key] += amount
        rows.append(dict(property=prop.name, property_name=prop.property_name, company=prop.company,
                         mode=prop.mode, currency=prop.currency, business_date=str(prop.business_date), time_zone=prop.time_zone,
                         rooms=len(active_rooms), occupied=len(occupied), blocked=len(blocked),
                         cleaning=frappe.db.count("HS Cleaning Task", {"property": prop.name, "status": ["!=", "Completed"]}),
                         maintenance=frappe.db.count("HS Maintenance Order", {"property": prop.name, "status": ["!=", "Completed"]}),
                         tickets=tickets, overdue_tickets=overdue_tickets,
                         amounts={currency: {key: str(value) for key, value in values.items()} for currency, values in amounts.items()}))
    return dict(checked_at=str(now_datetime()), properties=rows,
                totals={currency: {key: str(value) for key, value in values.items()} for currency, values in sorted(totals.items())},
                counts=dict(properties=len(rows), rooms=sum(r["rooms"] for r in rows), occupied=sum(r["occupied"] for r in rows),
                            open_tickets=sum(r["tickets"] for r in rows), overdue_tickets=sum(r["overdue_tickets"] for r in rows)))
