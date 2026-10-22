"""Tickets, credit control, portfolio isolation and administrator diagnostics."""
import uuid
from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, nowdate, now_datetime

from hospitality_suite import api
from hospitality_suite.credit import invoice_due_date, snapshot as credit_snapshot
from hospitality_suite.security import allowed_properties
from hospitality_suite.service import operation
from hospitality_suite.time import to_site


class TestOperationalDashboard(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop = frappe.get_doc("HS Property", {"property_name": "Hotel Jardín Demo"})
        self.room = frappe.db.get_value("HS Room", {"property": self.prop.name}, "name")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def ticket(self, data, key=None):
        return api.execute(self.prop.name, "ticket", key or uuid.uuid4().hex, data)

    def test_ticket_scope_roles_history_and_idempotency(self):
        payload = dict(kind="create", room=self.room, subject="Fuga de agua", description="Revisar ducha",
                       category="Maintenance", priority="Urgent")
        key = uuid.uuid4().hex
        created = self.ticket(payload, key)
        self.assertEqual(created, self.ticket(payload, key))
        detail = api.ticket_detail(created["ticket"])
        self.assertEqual(detail["ticket"]["room"], self.room)
        self.assertEqual([event["kind"] for event in detail["events"]], ["Created"])
        self.assertEqual(api.ticket_board(self.prop.name, "open")["rows"][0]["name"], created["ticket"])
        room_view = api.room_snapshot(self.prop.name, self.room)
        self.assertEqual(room_view["tickets"][0]["name"], created["ticket"])
        self.assertTrue(room_view["room"]["work"])
        with self.assertRaises(frappe.PermissionError):
            self.ticket(dict(kind="assign", ticket=created["ticket"], modified=created["modified"], assigned_to="Guest"))
        frappe.set_user("housekeeping@hospitality.example.invalid")
        started = self.ticket(dict(kind="start", ticket=created["ticket"], modified=created["modified"]))
        self.assertEqual(started["status"], "In Progress")
        with self.assertRaises(frappe.PermissionError):
            self.ticket(dict(kind="assign", ticket=created["ticket"], modified=started["modified"],
                             assigned_to="housekeeping@hospitality.example.invalid"))
        frappe.set_user("Administrator")
        resolved = self.ticket(dict(kind="resolve", ticket=created["ticket"], modified=started["modified"],
                                    resolution="Se reparó la ducha"))
        self.assertEqual(resolved["status"], "Resolved")
        self.assertEqual([event["kind"] for event in api.ticket_detail(created["ticket"])["events"]],
                         ["Created", "Started", "Resolved"])
        other = frappe.db.get_value("HS Room", {"property": ["!=", self.prop.name]}, "name")
        with self.assertRaises(frappe.PermissionError):
            self.ticket(dict(payload, room=other))
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.ticket_board(self.prop.name)

    def test_ticket_deadline_uses_property_zone_and_rejects_ambiguous_hour(self):
        with operation():
            self.prop.time_zone = "America/New_York"
            self.prop.save()
        values = dict(kind="create", room=self.room, subject="Horario de atención",
                      description="Prueba de plazo local", category="Guest Request", priority="Normal")
        with self.assertRaises(frappe.ValidationError):
            self.ticket(dict(values, due_at="2026-11-01T01:30:00"))
        local_time = "2026-11-01T01:30:00-04:00"
        created = self.ticket(dict(values, due_at=local_time))
        self.assertEqual(frappe.db.get_value("HS Guest Ticket", created["ticket"], "due_at"),
                         to_site(local_time, self.prop))

    def test_credit_terms_and_portfolio_currency_groups(self):
        guest = frappe.get_doc("HS Guest", {"property": self.prop.name})
        party = frappe.db.get_value("HS Billing Party", {"property": self.prop.name, "customer": guest.customer}, "name")
        if party:
            doc = frappe.get_doc("HS Billing Party", party)
            with operation():
                doc.credit_authorized, doc.credit_limit, doc.credit_days = 1, 1000000, 45
                doc.valid_until = getdate(nowdate()) + timedelta(days=30)
                doc.save()
        else:
            api.save_setup(self.prop.name, "billing_party",
                           dict(customer=guest.customer, kind="Company", credit_authorized=1,
                                credit_limit=1000000, credit_days=45,
                                valid_until=str(getdate(nowdate()) + timedelta(days=30)), reason="Prueba sintética"),
                           uuid.uuid4().hex)
        with operation():
            self.prop.allow_credit = 1
            self.prop.save()
        credit = credit_snapshot(self.prop, guest.customer)
        self.assertEqual(credit["credit_days"], 45)
        current = frappe.get_doc("HS Billing Party", {"property": self.prop.name, "customer": guest.customer})
        changed = api.execute(self.prop.name, "billing_party", uuid.uuid4().hex,
                              dict(party=current.name, modified=str(current.modified), credit_days=60,
                                   reason="Extensión sintética aprobada"))
        self.assertEqual(changed["party"], current.name)
        self.assertEqual(invoice_due_date(self.prop, guest.customer), getdate(nowdate()) + timedelta(days=60))
        with self.assertRaises(frappe.TimestampMismatchError):
            api.execute(self.prop.name, "billing_party", uuid.uuid4().hex,
                        dict(party=current.name, modified=str(current.modified), credit_days=90,
                             reason="Cambio obsoleto de prueba"))
        portfolio = api.portfolio_snapshot()
        self.assertEqual(portfolio["counts"]["properties"], len(portfolio["properties"]))
        self.assertTrue({row["property"] for row in portfolio["properties"]}.issubset(set(allowed_properties())))
        for currency, values in portfolio["totals"].items():
            self.assertTrue(currency)
            self.assertGreaterEqual(float(values["receivable"]), 0)

    def test_health_requires_administrator(self):
        result = api.health_snapshot(self.prop.name)
        self.assertEqual(result["property"], self.prop.name)
        self.assertIn("database", {row["key"] for row in result["checks"]})
        frappe.set_user("manager@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            api.health_snapshot(self.prop.name)

    def test_credit_limit_exception_requires_reason_and_is_audited(self):
        room = frappe.get_doc("HS Room", self.room)
        guest = frappe.get_doc("HS Guest", {"property": self.prop.name})
        start = now_datetime().replace(microsecond=0)
        values = dict(starts_at=str(start), ends_at=str(start + timedelta(days=1)),
                      guest=guest.name, customer=guest.customer,
                      rooms=[dict(room=room.name, category=room.category, people=1)])
        values["acceptance"] = api.preview(self.prop.name, values)["acceptance"]
        stay = api.execute(self.prop.name, "walk_in", uuid.uuid4().hex, values)
        api.execute(self.prop.name, "invoice", uuid.uuid4().hex, {"folio": stay["folio"]})
        party = frappe.db.get_value("HS Billing Party", {"property": self.prop.name, "customer": guest.customer}, "name")
        if party:
            doc = frappe.get_doc("HS Billing Party", party)
            with operation():
                doc.credit_authorized, doc.credit_limit = 1, 1
                doc.valid_until = getdate(nowdate()) + timedelta(days=30)
                doc.save()
        else:
            api.save_setup(self.prop.name, "billing_party",
                           dict(customer=guest.customer, kind="Company", credit_authorized=1,
                                credit_limit=1, credit_days=30,
                                valid_until=str(getdate(nowdate()) + timedelta(days=30)), reason="Excepción sintética"),
                           uuid.uuid4().hex)
        self.prop.reload()
        api.save_setup(self.prop.name, "property", {"allow_credit": 1}, uuid.uuid4().hex, str(self.prop.modified))
        def leave(**extra):
            current = frappe.get_doc("HS Stay", stay["stay"])
            return api.execute(self.prop.name, "check_out", uuid.uuid4().hex,
                               dict(stay=current.name, modified=str(current.modified),
                                    credit_reason="Salida corporativa autorizada", **extra))
        with self.assertRaisesRegex(frappe.ValidationError, "supera su límite"):
            leave()
        with self.assertRaisesRegex(frappe.ValidationError, "8 a 500"):
            leave(credit_override_reason="breve")
        frappe.set_user("manager@hospitality.example.invalid")
        leave(credit_override_reason="Gerencia acepta saldo excepcional por contrato")
        self.assertEqual(frappe.db.get_value("HS Stay", stay["stay"], "status"), "Checked Out")
        event = frappe.get_doc("HS Audit Event", {"property": self.prop.name, "action": "Credit override"})
        self.assertEqual(event.reason, "Gerencia acepta saldo excepcional por contrato")
