"""Property-scoped guest tickets and an append-only operational timeline."""
from datetime import UTC, datetime, timedelta

import frappe
from frappe.utils import now_datetime

from hospitality_suite.security import ACTIONS, allowed_properties, property_document, require
from hospitality_suite.service import assert_version, audit, insert
from hospitality_suite.time import to_site


OPEN = ("Open", "In Progress")
PRIORITIES = {"Normal": 24, "High": 8, "Urgent": 2}
CATEGORIES = ("Guest Request", "Housekeeping", "Maintenance", "Complaint", "Other")


def _text(value, label, *, required=False, limit=2000):
    value = str(value or "").strip()
    if (required and not value) or len(value) > limit:
        frappe.throw(frappe._("Revise {0}; se admiten hasta {1} caracteres").format(label, limit))
    return value


def _assignee(prop, user):
    if not user:
        return None
    row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    if not row or not row.enabled or row.user_type != "System User" or prop.name not in allowed_properties(user):
        frappe.throw(frappe._("El responsable no tiene acceso activo a este establecimiento"), frappe.PermissionError)
    if not set(frappe.get_roles(user)).intersection(ACTIONS["ticket"]):
        frappe.throw(frappe._("El responsable no tiene un rol para gestionar tickets"), frappe.PermissionError)
    return user


def _event(prop, ticket, kind, note="", before="", after=""):
    return insert("HS Ticket Event", prop, ticket=ticket.name, kind=kind, actor=frappe.session.user,
                  occurred_at=now_datetime(), note=note, before_value=before, after_value=after)


def change(prop, data):
    kind = data.get("kind")
    now = now_datetime()
    if kind == "create":
        room = data.get("room") or None
        stay = data.get("stay") or None
        if room:
            property_document(prop, "HS Room", room)
        if stay:
            actual = property_document(prop, "HS Stay", stay)
            if room and actual.room != room:
                frappe.throw(frappe._("La estancia no corresponde a la habitación"))
            room = actual.room
        category = data.get("category") or "Guest Request"
        priority = data.get("priority") or "Normal"
        if category not in CATEGORIES or priority not in PRIORITIES:
            frappe.throw(frappe._("Categoría o prioridad inválida"))
        due = to_site(data.get("due_at"), prop) if data.get("due_at") else to_site(datetime.now(UTC) + timedelta(hours=PRIORITIES[priority]), prop)
        if due <= now:
            frappe.throw(frappe._("El plazo debe ser posterior a la hora actual"))
        assignee = _assignee(prop, data.get("assigned_to"))
        ticket = insert("HS Guest Ticket", prop, room=room, stay=stay,
                        subject=_text(data.get("subject"), "asunto", required=True, limit=140),
                        description=_text(data.get("description"), "descripción", required=True),
                        category=category, priority=priority, status="Open", assigned_to=assignee, due_at=due)
        _event(prop, ticket, "Created", ticket.description)
    else:
        ticket = property_document(prop, "HS Guest Ticket", data.get("ticket"), "ticket")
        assert_version(ticket, data.get("modified"))
        before = ticket.status
        if kind == "assign":
            require(prop.name, "inspect")
            assignee = _assignee(prop, data.get("assigned_to"))
            if ticket.status not in OPEN or not assignee or assignee == ticket.assigned_to:
                frappe.throw(frappe._("Seleccione otro responsable para un ticket pendiente"))
            previous = ticket.assigned_to or ""
            ticket.assigned_to = assignee
            _event(prop, ticket, "Assigned", before=previous, after=assignee)
        elif kind == "due":
            require(prop.name, "inspect")
            if ticket.status not in OPEN:
                frappe.throw(frappe._("Solo se puede cambiar el plazo de un ticket pendiente"))
            if not isinstance(data.get("due_at"), str) or not data["due_at"].strip():
                frappe.throw(frappe._("Indique el nuevo plazo"))
            due = to_site(data.get("due_at"), prop)
            if due <= now:
                frappe.throw(frappe._("El nuevo plazo debe ser posterior a la hora actual"))
            previous = str(ticket.due_at or "")
            ticket.due_at = due
            _event(prop, ticket, "Due Changed", _text(data.get("note"), "motivo", required=True), previous, str(due))
        elif kind == "start":
            if ticket.status != "Open":
                frappe.throw(frappe._("El ticket no está abierto"))
            ticket.status = "In Progress"
            ticket.first_response_at = ticket.first_response_at or now
            _event(prop, ticket, "Started", before=before, after=ticket.status)
        elif kind == "resolve":
            if ticket.status not in OPEN:
                frappe.throw(frappe._("El ticket ya está cerrado"))
            ticket.resolution = _text(data.get("resolution"), "resolución", required=True)
            ticket.status, ticket.resolved_by, ticket.resolved_at = "Resolved", frappe.session.user, now
            ticket.first_response_at = ticket.first_response_at or now
            _event(prop, ticket, "Resolved", ticket.resolution, before, ticket.status)
        elif kind == "reopen":
            require(prop.name, "inspect")
            if ticket.status != "Resolved":
                frappe.throw(frappe._("Solo un ticket resuelto puede reabrirse"))
            ticket.status, ticket.resolved_by, ticket.resolved_at, ticket.resolution = "Open", None, None, None
            ticket.reopened_count = (ticket.reopened_count or 0) + 1
            ticket.due_at = to_site(datetime.now(UTC) + timedelta(hours=PRIORITIES[ticket.priority]), prop)
            _event(prop, ticket, "Reopened", _text(data.get("note"), "motivo", required=True), before, ticket.status)
        elif kind == "note":
            _event(prop, ticket, "Note", _text(data.get("note"), "nota", required=True))
        elif kind == "cancel":
            require(prop.name, "inspect")
            if ticket.status not in OPEN:
                frappe.throw(frappe._("Solo un ticket pendiente puede cancelarse"))
            ticket.status = "Cancelled"
            _event(prop, ticket, "Cancelled", _text(data.get("note"), "motivo", required=True), before, ticket.status)
        else:
            frappe.throw(frappe._("Acción de ticket desconocida"))
        ticket.save()
    audit(prop, "Ticket " + kind, ticket, data.get("note") or data.get("resolution"))
    return {"ticket": ticket.name, "status": ticket.status, "modified": str(ticket.modified)}


def board(property_name, view="open", offset=0, page_length=40):
    prop = require(property_name, "ticket")
    if view not in ("open", "mine", "unassigned", "overdue", "resolved", "all"):
        frappe.throw(frappe._("Vista de tickets desconocida"))
    offset, page_length = int(offset), int(page_length)
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Paginación inválida"))
    conditions = {"property": prop.name, "company": prop.company}
    if view in ("open", "mine", "unassigned", "overdue"):
        conditions["status"] = ["in", list(OPEN)]
    if view == "mine":
        conditions["assigned_to"] = frappe.session.user
    if view == "unassigned":
        conditions["assigned_to"] = ["is", "not set"]
    if view == "overdue":
        conditions["due_at"] = ["<", now_datetime()]
    if view == "resolved":
        conditions["status"] = "Resolved"
    rows = frappe.get_all("HS Guest Ticket", filters=conditions,
                          fields=["name", "room", "stay", "subject", "category", "priority", "status", "assigned_to", "due_at", "modified", "creation", "resolved_at"],
                          order_by="due_at asc, creation desc", start=offset, limit=page_length)
    total = frappe.db.count("HS Guest Ticket", conditions)
    users = frappe.get_all("HS Access", filters={"property": prop.name, "company": prop.company}, pluck="user")
    if frappe.session.user not in users:
        users.append(frappe.session.user)
    assignees = [dict(name=u, full_name=frappe.db.get_value("User", u, "full_name")) for u in sorted(set(users))
                 if frappe.db.get_value("User", u, "enabled") and prop.name in allowed_properties(u)
                 and set(frappe.get_roles(u)).intersection(ACTIONS["ticket"])]
    return dict(property=prop.name, view=view, rows=rows, total=total, offset=offset,
                page_length=page_length, has_more=offset+len(rows)<total, assignees=assignees,
                now=str(now_datetime()))


def detail(name, offset=0, page_length=100):
    ticket = property_document(require(frappe.db.get_value("HS Guest Ticket", name, "property"), "ticket"),
                               "HS Guest Ticket", name, "ticket")
    offset, page_length = int(offset), int(page_length)
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Paginación inválida"))
    total = frappe.db.count("HS Ticket Event", {"property": ticket.property, "ticket": ticket.name})
    events = frappe.get_all("HS Ticket Event", filters={"property": ticket.property, "ticket": ticket.name},
                            fields=["kind", "actor", "occurred_at", "note", "before_value", "after_value"],
                            order_by="occurred_at desc, creation desc", start=offset, limit=page_length)
    return dict(ticket=ticket.as_dict(), events=list(reversed(events)), total_events=total,
                offset=offset, page_length=page_length, has_older=offset+len(events)<total)
