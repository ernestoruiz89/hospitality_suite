"""Rollback-only companion registration on the ERPNext authority site."""

from datetime import timedelta
from uuid import uuid4

import frappe

from hospitality_suite import api
from hospitality_suite.service import command, insert
from hospitality_suite.standalone_accounting import provider


def run():
    if provider() != "erpnext" or not frappe.local.site.startswith("hs-cutover-race"):
        frappe.throw("Use únicamente el sitio ERPNext descartable de ensayo")
    previous_user = frappe.session.user
    frappe.set_user("Administrator")
    prop = frappe.get_doc("HS Property", frappe.get_all("HS Property", pluck="name", limit=1)[0])
    suffix = uuid4().hex[:8]
    try:
        def fixture(locked):
            category = insert("HS Category", locked, category_name="Acompañantes " + suffix,
                capacity=2)
            room = insert("HS Room", locked, room_number="CMP-" + suffix,
                category=category.name, active=1, cleaning_status="Clean")
            rate = insert("HS Rate", locked, title="Tarifa acompañantes " + suffix,
                category=category.name, mode="Hotel", currency=locked.currency,
                amount=10, active=1)
            principal = insert("HS Guest", locked, full_name="Principal " + suffix,
                identity_type="Documento", identity_number="PR-" + suffix)
            companion = insert("HS Guest", locked, full_name="Acompañante " + suffix,
                identity_type="Documento", identity_number="AC-" + suffix)
            extra = insert("HS Guest", locked, full_name="Extra " + suffix,
                identity_type="Documento", identity_number="EX-" + suffix)
            start = frappe.utils.now_datetime()
            groups = frappe.get_all("Customer Group", filters={"is_group": 0},
                pluck="name", limit=1)
            if not groups:
                parents = frappe.get_all("Customer Group", filters={"is_group": 1},
                    pluck="name", limit=1)
                groups = [frappe.get_doc({"doctype": "Customer Group",
                    "customer_group_name": "Acompañantes " + suffix, "is_group": 0,
                    "parent_customer_group": parents[0] if parents else None,
                }).insert(ignore_permissions=True).name]
            territories = frappe.get_all("Territory", filters={"is_group": 0},
                pluck="name", limit=1)
            if not territories:
                parents = frappe.get_all("Territory", filters={"is_group": 1},
                    pluck="name", limit=1)
                territories = [frappe.get_doc({"doctype": "Territory",
                    "territory_name": "Acompañantes " + suffix, "is_group": 0,
                    "parent_territory": parents[0] if parents else None,
                }).insert(ignore_permissions=True).name]
            customer = frappe.get_doc({"doctype": "Customer",
                "customer_name": "Acompañantes " + suffix,
                "customer_type": "Individual",
                "customer_group": groups[0], "territory": territories[0],
            }).insert(ignore_permissions=True).name
            stay = insert("HS Stay", locked, guest=principal.name,
                customer=customer, room=room.name, rate=rate.name,
                currency=locked.currency, amount=10, starts_at=start,
                ends_at=start + timedelta(days=1), status="Active",
                quote_snapshot='{"people":2}',
                guests=[dict(guest=principal.name, relationship="Principal")])
            return {"stay": stay.name, "principal": principal.name,
                "companion": companion.name, "extra": extra.name}

        records = command(prop.name, "setup", "companions-erp-fixture-" + suffix,
            {"operation": "companions_erp_fixture"}, fixture)
        guests = api.guest_directory(prop.name, search=suffix, page_length=1)
        assert guests["total"] == 3 and guests["has_more"]
        profile = api.guest_detail(records["principal"])
        assert profile["property"] == prop.name
        update = api.update_guest(prop.name, records["principal"], profile["modified"],
            {"nationality": "Nicaragua"}, "Corrección de nacionalidad",
            "companions-erp-profile-" + suffix, profile["related_versions"])
        assert update == api.update_guest(prop.name, records["principal"],
            profile["modified"], {"nationality": "Nicaragua"},
            "Corrección de nacionalidad", "companions-erp-profile-" + suffix,
            profile["related_versions"])
        assert api.guest_detail(records["principal"])["values"]["nationality"] == "Nicaragua"
        page = api.stay_companions(prop.name, records["stay"],
            search="Acompañante " + suffix)
        assert page["capacity"] == 2 and page["total"] == 1
        assert page["candidates"][0]["name"] == records["companion"]
        assert page["candidates"][0]["has_identity"]
        payload = {"stay": records["stay"], "modified": page["modified"],
            "guests": [records["companion"]]}
        result = api.execute(prop.name, "companions", "companions-erp-" + suffix, payload)
        assert result == api.execute(prop.name, "companions", "companions-erp-" + suffix,
            payload)
        assert api.stay_companions(prop.name, records["stay"])["selected"][0]["name"] == records["companion"]
        try:
            api.execute(prop.name, "companions", "companions-erp-over-" + suffix,
                {"stay": records["stay"], "modified": result["modified"],
                 "guests": [records["companion"], records["extra"]]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó ocupación superior a la reserva")
        return {"provider": provider(), "companions": "updated"}
    finally:
        frappe.db.rollback()
        frappe.set_user(previous_user)
