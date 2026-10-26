"""Transactional MariaDB smoke path for a fresh Frappe-only test site.

Invoke with ``bench --site <disposable-site> execute
hospitality_suite.tests.smoke_standalone.run``. It rolls back its fixtures.
"""

import uuid
import base64
from collections import Counter
from datetime import timedelta
from io import BytesIO
from decimal import Decimal
from unittest.mock import patch

import frappe

from hospitality_suite import api, pms_cutover, setup, standalone_accounting, standalone_coa, standalone_currency, standalone_inventory
from hospitality_suite.coa_format import HEADERS, parse_csv
from hospitality_suite.service import command, insert, canonical, operation
from hospitality_suite.time import now_local


def run():
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente un sitio temporal Frappe sin ERPNext")
    frappe.set_user("Administrator")
    suffix = uuid.uuid4().hex[:8]
    try:
        org = frappe.get_doc(dict(doctype="HS Organization", legal_name="Entidad prueba " + suffix,
                                  base_currency="NIO", tax_regime="General", active=1)).insert()
        created = setup.create_property(dict(property_name="Hotel prueba " + suffix,
            organization=org.name, currency="NIO", mode="Hotel"), "property-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        assert prop.company == org.name and standalone_accounting.provider() == "pms"
        availability = api.availability_options(prop.name)
        assert (availability["property"] == prop.name and
                availability["time_zone"] == prop.time_zone and
                availability["categories"] == [] and availability["local_now"])
        retention = api.retention_history(prop.name, page_length=1)
        assert retention["property"] == prop.name and retention["total"] == 0
        assert retention["runs"] == []
        frappe.db.savepoint("hs_pms_retention_history_probe")
        try:
            with operation(prop):
                run = insert("HS Retention Run", prop, status="Pending",
                    approved_by="Administrator", approved_at=frappe.utils.now_datetime(),
                    retention_days=1, reason="Ensayo de historial",
                    files=[{"source_file": "SYNTHETIC-" + suffix,
                        "status": "Pending"}])
            page = api.retention_history(prop.name, page_length=1)
            assert (page["total"] == 1 and page["runs"][0]["name"] == run.name and
                    page["runs"][0]["file_counts"]["Pending"] == 1)
            assert api.retention_history(prop.name, offset=1, page_length=1)["runs"] == []
        finally:
            frappe.db.rollback(save_point="hs_pms_retention_history_probe")
        try:
            api.retention_history(prop.name, offset=-1)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La retención aceptó una página negativa")
        frappe.set_user("Guest")
        try:
            for private_call in (lambda: api.retention_history(prop.name),
                                 lambda: api.availability_options(prop.name),
                                 lambda: api.room_calendar(prop.name,
                                     str(now_local(prop).date()))):
                try:
                    private_call()
                except frappe.PermissionError:
                    pass
                else:
                    raise AssertionError("Un usuario anónimo consultó una vista privada")
        finally:
            frappe.set_user("Administrator")
        health = api.health_snapshot(prop.name)
        health_checks = {row["key"]: row for row in health["checks"]}
        assert (health["accounting_provider"] == "pms" and
                health_checks["configuration"]["status"] == "OK" and
                health_checks["accounts"]["status"] == "Warning" and
                "Almacén" not in health_checks["configuration"]["detail"])
        assert any(row["name"] == org.name for row in api.onboarding_options()["organizations"])
        frappe.db.savepoint("hs_pms_react_onboarding_probe")
        try:
            onboarding_data = {"property_name": "Alta React " + suffix,
                "new_organization": {"legal_name": "Entidad React " + suffix,
                    "tax_id": "", "tax_regime": "General"},
                "currency": "NIO", "mode": "Mixed",
                "time_zone": "America/Managua", "close_time": "06:00"}
            created_react = api.create_property(onboarding_data,
                "react-onboarding-" + suffix)
            assert api.create_property(onboarding_data,
                "react-onboarding-" + suffix) == created_react
            new_prop = frappe.get_doc("HS Property", created_react["property"])
            assert (new_prop.mode == "Mixed" and new_prop.organization == new_prop.company and
                    frappe.db.get_value("HS Organization", new_prop.organization,
                                        "legal_name") == "Entidad React " + suffix and
                    not new_prop.financial_enabled)
            try:
                api.create_property({**onboarding_data, "property_name": "Otra alta"},
                    "react-onboarding-" + suffix)
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("An onboarding key accepted a different hotel")
            failed_legal_name = "Entidad fallida " + suffix
            with patch("hospitality_suite.setup.initial_business_date",
                       side_effect=frappe.ValidationError("Fallo posterior a la entidad")):
                try:
                    api.create_property({**onboarding_data,
                        "property_name": "Alta fallida " + suffix,
                        "new_organization": {"legal_name": failed_legal_name,
                            "tax_id": "", "tax_regime": "General"}},
                        "react-onboarding-fail-" + suffix)
                except frappe.ValidationError:
                    pass
                else:
                    raise AssertionError("An injected onboarding failure was accepted")
            assert not frappe.db.exists("HS Organization",
                {"legal_name": failed_legal_name})
            frappe.set_user("Guest")
            try:
                for admin_call in (api.onboarding_options,
                        lambda: api.create_property(onboarding_data,
                            "react-onboarding-denied-" + suffix)):
                    try:
                        admin_call()
                    except frappe.PermissionError:
                        pass
                    else:
                        raise AssertionError("An unauthenticated user reached onboarding")
            finally:
                frappe.set_user("Administrator")
            staff_email = "setup-" + suffix + "@example.invalid"
            grant = {"email": staff_email, "first_name": "Personal",
                "roles": ["HS Manager"], "reason": "Ensayo de accesos"}
            api.execute(new_prop.name, "assign_user",
                "react-access-grant-" + suffix, grant)
            assert any(row["user"] == staff_email and
                row["roles"] == ["HS Manager"] for row in
                api.user_access_board(new_prop.name)["users"])
            try:
                api.execute(prop.name, "assign_user",
                    "react-access-escalate-" + suffix,
                    {"email": staff_email, "roles": ["HS Manager", "HS Cashier"]})
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Un rol global elevó permisos en otro hotel")
            frappe.set_user(staff_email)
            try:
                api.user_access_board(new_prop.name)
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("Gerencia consultó los accesos administrativos")
            finally:
                frappe.set_user("Administrator")
            try:
                api.execute(prop.name, "revoke_user_access",
                    "react-access-wrong-" + suffix,
                    {"user": staff_email, "reason": "Otro establecimiento"})
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Se retiró el acceso de otro establecimiento")
            withdrawal = {"user": staff_email, "reason": "Fin del ensayo"}
            removed = api.execute(new_prop.name, "revoke_user_access",
                "react-access-revoke-" + suffix, withdrawal)
            assert removed["revoked"] and api.execute(new_prop.name,
                "revoke_user_access", "react-access-revoke-" + suffix,
                withdrawal) == removed
            assert not frappe.db.exists("HS Access", {"property": new_prop.name,
                "user": staff_email})
        finally:
            frappe.db.rollback(save_point="hs_pms_react_onboarding_probe")

        frappe.db.savepoint("hs_pms_setup_edit_probe")
        try:
            category = api.save_setup(prop.name, "category",
                {"category_name": "Editable", "capacity": 2},
                "setup-category-" + suffix)["name"]
            original = frappe.get_doc("HS Category", category)
            api.save_setup(prop.name, "category",
                {"name": category, "category_name": "Editada", "capacity": 3},
                "setup-category-edit-" + suffix, str(original.modified))
            room = api.save_setup(prop.name, "room",
                {"room_number": "EDIT-" + suffix, "category": category,
                 "beds": 1, "active": 1}, "setup-room-" + suffix)["name"]
            api.save_setup(prop.name, "room",
                {"name": room, "parking": "P1", "active": 0},
                "setup-room-edit-" + suffix,
                str(frappe.db.get_value("HS Room", room, "modified")))
            assert frappe.db.get_value("HS Room", room, "parking") == "P1"
            assert any(row["name"] == category for row in
                       api.availability_options(prop.name)["categories"])
            start = now_local(prop) + timedelta(days=2)
            found = api.availability_search(prop.name, str(start),
                str(start + timedelta(days=1)), category)
            assert (not found["enough"] and found["available"] == 0 and
                    found["room_states"][0]["status"] == "Inactive")
            timeline = api.room_calendar(prop.name, str(start.date()), "week")
            assert (timeline["read_only"] and len(timeline["ticks"]) == 7 and
                    any(row["name"] == room and not row["active"]
                        for row in timeline["rooms"]))
            day_timeline = api.room_calendar(prop.name, str(start.date()), "day")
            assert (len(day_timeline["ticks"]) == 12 and
                    day_timeline["window_start"][:10] == str(start.date()) and
                    day_timeline["window_end"][:10] ==
                    str(start.date() + timedelta(days=1)))
            try:
                api.room_calendar(prop.name, "2026-99-99", "week")
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("El calendario aceptó una fecha inválida")
            rate = api.save_setup(prop.name, "rate",
                {"title": "Editable", "category": category, "mode": "Hotel",
                 "currency": prop.currency, "amount": 100, "block_hours": 3,
                 "active": 1}, "setup-rate-" + suffix)["name"]
            calendar = api.rate_calendar(prop.name, category,
                str(now_local(prop).date() + timedelta(days=2)), days=1,
                mode="Hotel")
            assert (calendar["read_only"] and len(calendar["rows"]) == 1 and
                    calendar["rows"][0]["rate"] == rate and
                    calendar["rows"][0]["available"] == 0)
            frappe.set_user("Guest")
            try:
                try:
                    api.rate_calendar(prop.name, category,
                        str(now_local(prop).date() + timedelta(days=2)), days=1)
                except frappe.PermissionError:
                    pass
                else:
                    raise AssertionError("Un usuario anónimo consultó tarifas")
            finally:
                frappe.set_user("Administrator")
            version = str(frappe.db.get_value("HS Rate", rate, "modified"))
            try:
                api.save_setup(prop.name, "rate", {"name": rate, "amount": 120},
                    "setup-rate-no-reason-" + suffix, version)
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Se modificó una tarifa sin motivo")
            change = {"name": rate, "amount": 120,
                      "change_reason": "Ajuste de prueba"}
            changed = api.save_setup(prop.name, "rate", change,
                "setup-rate-edit-" + suffix, version)
            assert changed == api.save_setup(prop.name, "rate", change,
                "setup-rate-edit-" + suffix, version)
            assert frappe.db.get_value("HS Rate", rate, "amount") == 120
            assert frappe.db.count("HS Audit Event", {"property": prop.name,
                "source_name": rate, "action": "Rate changed"}) == 1
            assert any(row.name == rate for row in api.setup_board(prop.name)["rates"])
            try:
                api.save_setup(prop.name, "rate",
                    {"name": rate, "amount": 125, "change_reason": "Versión vieja"},
                    "setup-rate-stale-" + suffix, version)
            except frappe.TimestampMismatchError:
                pass
            else:
                raise AssertionError("Se modificó una tarifa con versión antigua")
            other = api.create_property({"property_name": "Otro " + suffix,
                "organization": org.name, "mode": "Hotel", "currency": "NIO"},
                "setup-other-" + suffix)["property"]
            try:
                api.save_setup(other, "room", {"name": room, "zone": "Ajena"},
                    "setup-cross-" + suffix,
                    str(frappe.db.get_value("HS Room", room, "modified")))
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("Otro establecimiento modificó la habitación")
        finally:
            frappe.db.rollback(save_point="hs_pms_setup_edit_probe")

        def new_account(code, root, **extra):
            return api.execute(prop.name, "pms_account", "account-" + code + suffix,
                dict(account_code=code + suffix, account_name=code, root_type=root, **extra))["account"]

        cash = new_account("1000", "Asset", is_cash=1)
        inventory = new_account("1100", "Asset")
        equity = new_account("3000", "Equity")
        expense = new_account("5000", "Expense")
        assert next(row for row in api.health_snapshot(prop.name)["checks"]
            if row["key"] == "accounts")["status"] == "OK"
        assert api.pms_opening_balance_status(prop.name)["available"]
        opening = api.execute(prop.name, "pms_opening_balance", "opening-" + suffix,
            dict(reference="SMOKE-" + suffix, lines=[
                dict(account=cash, debit="100.00", credit=0),
                dict(account=equity, debit=0, credit="100.00")]))
        assert (not api.pms_opening_balance_status(prop.name)["available"] and
                api.pms_opening_balance_status(prop.name)["existing_journal"] ==
                    opening["journal"])
        assert standalone_accounting.balance(prop, cash) == "100.00"
        manual_data = dict(reference="AJ-" + suffix, reason="Ajuste de prueba con soporte",
                           lines=[dict(account=expense, debit="7.25", credit="0"),
                                  dict(account=equity, debit="0", credit="7.25")])
        manual = api.execute(prop.name, "pms_manual_journal", "manual-" + suffix, manual_data)
        repeated = api.execute(prop.name, "pms_manual_journal", "manual-" + suffix, manual_data)
        assert repeated == manual and manual["total"] == "7.25"
        eligible = api.pms_reversible_journals(prop.name)
        assert (eligible["total"] == 2 and
                {row["name"] for row in eligible["rows"]} ==
                    {opening["journal"], manual["journal"]} and
                all(len(row["lines"]) == 2 for row in eligible["rows"]))
        assert standalone_accounting.balance(prop, expense) == "7.25"
        assert any(row["name"] == expense for row in api.pms_accounts(prop.name))
        try:
            api.execute(prop.name, "pms_manual_journal", "manual-control-" + suffix,
                dict(reference="CONTROL-" + suffix, reason="Debe usar Caja",
                     lines=[dict(account=cash, debit="1.00", credit="0"),
                            dict(account=equity, debit="0", credit="1.00")]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Una cuenta de Caja se publicó por ajuste manual")
        report = api.pms_trial_balance(prop.name)
        assert sum(Decimal(row["debit"]) for row in report["rows"]) == Decimal("107.25")
        assert sum(Decimal(row["credit"]) for row in report["rows"]) == Decimal("107.25")
        api.execute(prop.name, "pms_reverse_journal", "reverse-" + suffix,
                    dict(journal=opening["journal"], reason="Prueba de reversión"))
        assert Decimal(standalone_accounting.balance(prop, cash)) == 0
        api.execute(prop.name, "pms_reverse_journal", "reverse-manual-" + suffix,
                    dict(journal=manual["journal"], reason="Prueba de reversión manual"))
        assert api.pms_reversible_journals(prop.name)["total"] == 0
        assert Decimal(standalone_accounting.balance(prop, expense)) == 0

        def create_masters(locked):
            warehouse = insert("HS Warehouse", locked, organization=org.name,
                warehouse_code="MAIN" + suffix, warehouse_name="Principal", active=1)
            product = insert("HS Product", locked, organization=org.name,
                product_code="SOAP" + suffix, product_name="Jabón", product_type="Stock",
                inventory_account=inventory, expense_account=expense, active=1)
            return dict(warehouse=warehouse.name, product=product.name)

        masters = command(prop.name, "setup", "masters-" + suffix,
            {"operation": "smoke_masters"}, create_masters)
        received = command(prop.name, "inventory", "receive-" + suffix,
            {"operation": "smoke_receive"}, lambda locked: standalone_inventory.receive(locked,
                product=masters["product"], warehouse=masters["warehouse"], quantity="2",
                value="20.00", counter_account=equity, source_doctype="Smoke",
                source_name="receipt-" + suffix, purpose="test"))
        consumed = command(prop.name, "inventory", "consume-" + suffix,
            {"operation": "smoke_consume"}, lambda locked: standalone_inventory.consume(locked,
                product=masters["product"], warehouse=masters["warehouse"], quantity="1",
                counter_account=expense, source_doctype="Smoke",
                source_name="issue-" + suffix, purpose="test"))
        assert received["balance_value"] == "20.00"
        assert consumed["balance_value"] == "10.00"
        assert standalone_inventory.current_balance(prop, masters["product"], masters["warehouse"]) == (
            Decimal("1"), Decimal("10.00"))
        def create_room(locked):
            category = insert("HS Category", locked, category_name="Estándar", capacity=2)
            room = insert("HS Room", locked, room_number="101", category=category.name,
                          active=1, cleaning_status="Clean")
            return room.name
        room_name = command(prop.name, "setup", "room-" + suffix,
            {"operation": "smoke_room"}, create_room)
        assert any(row["name"] == prop.name for row in api.bootstrap()["properties"])
        assert any(row["name"] == room_name for row in api.bootstrap(prop.name)["rooms"])
        assert any(row["name"] == room_name for row in api.room_board_snapshot(prop.name)["rooms"])
        assert api.room_snapshot(prop.name, room_name)["room"]["room_number"] == "101"
        room_day = str(now_local(prop).date())
        room_next = str(now_local(prop).date() + timedelta(days=1))
        schedule = api.room_schedule(prop.name, room_name,
            room_day + "T00:00:00", room_next + "T00:00:00")
        history = api.room_history(prop.name, room_name,
            room_day + "T00:00:00", room_next + "T00:00:00")
        insights = api.room_insights(prop.name, 7)
        assert (schedule["property"] == prop.name and schedule["room"] == room_name and
                history["property"] == prop.name and history["room"] == room_name and
                history["view"] == "activity" and
                any(row["room"] == room_name for row in insights["rooms"]))
        ticket_data = dict(kind="create", room=room_name, subject="Revisar habitación",
                           description="Solicitud operativa de ensayo", priority="High")
        ticket = api.execute(prop.name, "ticket", "ticket-" + suffix, ticket_data)
        assert api.execute(prop.name, "ticket", "ticket-" + suffix, ticket_data) == ticket
        assert any(row["name"] == ticket["ticket"] for row in
                   api.ticket_board(prop.name, "open")["rows"])
        assert api.ticket_detail(ticket["ticket"])["events"][0]["kind"] == "Created"
        resolved = api.execute(prop.name, "ticket", "ticket-resolve-" + suffix,
            dict(kind="resolve", ticket=ticket["ticket"], modified=ticket["modified"],
                 resolution="Habitación revisada"))
        assert resolved["status"] == "Resolved"
        assert any(row["name"] == ticket["ticket"] for row in
                   api.ticket_board(prop.name, "resolved")["rows"])
        setup_board = api.setup_board(prop.name)
        assert (setup_board["property"]["name"] == prop.name and
                any(row["name"] == room_name for row in setup_board["rooms"]) and
                "NIO" in setup_board["currencies"])
        frappe.db.savepoint("hs_pms_react_setup_probe")
        try:
            api.save_setup(prop.name, "property",
                {"brand_name": "Marca React " + suffix,
                 "cleaning_minutes": 25, "hold_minutes": 15},
                "react-property-" + suffix,
                expected_modified=str(setup_board["property"]["modified"]))
            assert api.setup_board(prop.name)["property"]["brand_name"] == "Marca React " + suffix
            extra_category = api.save_setup(prop.name, "category",
                {"category_name": "Suite React " + suffix, "capacity": 2},
                "react-category-" + suffix)["name"]
            extra_room = api.save_setup(prop.name, "room",
                {"room_number": "R-" + suffix, "category": extra_category,
                 "beds": 1, "active": 1}, "react-room-" + suffix)["name"]
            extra_rate = api.save_setup(prop.name, "rate",
                {"title": "Noche React " + suffix, "category": extra_category,
                 "mode": "Hotel", "currency": "NIO", "amount": 30,
                 "active": 1}, "react-rate-" + suffix)["name"]
            configured = api.setup_board(prop.name)
            assert (any(row["name"] == extra_category for row in configured["categories"]) and
                    any(row["name"] == extra_room for row in configured["rooms"]) and
                    any(row["name"] == extra_rate for row in configured["rates"]))
        finally:
            frappe.db.rollback(save_point="hs_pms_react_setup_probe")
        command(prop.name, "report", "close-" + suffix,
            {"operation": "smoke_close"},
            lambda locked: insert("HS Daily Close", locked, business_date=locked.business_date,
                                  status="Closed", summary="{}", blockers="{}",
                                  closed_at=frappe.utils.now_datetime()))
        try:
            api.execute(prop.name, "pms_count_stock", "count-after-close-" + suffix,
                dict(product=masters["product"], warehouse=masters["warehouse"],
                     counted_quantity="1", reference="CLOSED-COUNT-" + suffix,
                     reason="No alterar un cierre inmutable"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se registró un conteo después del cierre")
        try:
            api.execute(prop.name, "pms_manual_journal", "manual-after-close-" + suffix,
                dict(reference="LATE-" + suffix, reason="Debe rechazarse por cierre",
                     lines=manual_data["lines"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió un asiento en un período cerrado")
        second = setup.create_property(dict(property_name="Hotel divisas " + suffix,
            organization=org.name, currency="NIO", mode="Hotel"), "foreign-property-" + suffix)
        second_prop = frappe.get_doc("HS Property", second["property"])
        api.execute(second_prop.name, "pms_currencies", "currencies-" + suffix,
                    dict(currencies=["NIO", "USD"]))
        second_prop.reload()
        assert standalone_currency.enabled(second_prop, "USD")
        recorded_rate = api.execute(second_prop.name, "pms_exchange_rate", "rate-" + suffix,
                                    dict(from_currency="USD", rate="36.5", source="Ensayo contable"))
        assert recorded_rate["from_currency"] == "USD"
        assert standalone_currency.latest_rate(second_prop, "USD")[0] == Decimal("36.5")
        coa_lines = [",".join(HEADERS), "Assets,,,,1,,Asset,NIO", "Liabilities,,,,1,,Liability,NIO",
                     "Equity,,,,1,,Equity,NIO", "Income,,,,1,,Income,NIO",
                     "Expenses,,,,1,,Expense,NIO", "Owner Capital,Equity,3001,,0,,Equity,NIO",
                     "Dollar Expense,Expenses,5001,,0,Expense Account,Expense,USD",
                     "Cash Dollars,Assets,1010,,0,Cash,Asset,USD",
                     "Bank Dollars,Assets,1020,,0,Bank,Asset,USD",
                     "Guest Receivable,Assets,1200,,0,Receivable,Asset,NIO",
                     "Guest Deposits,Liabilities,2000,,0,Current Liability,Liability,NIO",
                     "Other Income,Income,4000,,0,Income Account,Income,NIO",
                     "Operating Expense,Expenses,5000,,0,Expense Account,Expense,NIO"]
        encoded = base64.b64encode("\n".join(coa_lines).encode()).decode()
        preview = standalone_coa.preview(second_prop.name, "coa.csv", encoded)
        from openpyxl import Workbook
        workbook = Workbook()
        for row in [HEADERS] + [line.split(",") for line in coa_lines[1:]]:
            workbook.active.append(row)
        workbook_bytes = BytesIO()
        workbook.save(workbook_bytes)
        xlsx_preview = standalone_coa.preview(second_prop.name, "coa.xlsx",
                                                base64.b64encode(workbook_bytes.getvalue()).decode())
        assert xlsx_preview["count"] == preview["count"]
        imported = api.execute(second_prop.name, "pms_coa_import", "coa-" + suffix,
            dict(file_name="coa.csv", content_base64=encoded, sha256=preview["sha256"]))
        assert imported["count"] == 13
        assert len(api.pms_chart(second_prop.name)["accounts"]) == 13
        exported = standalone_coa.export_chart(second_prop.name)
        assert len(parse_csv(base64.b64decode(exported["content_base64"]), "NIO")) == 13
        def account_number(number):
            return frappe.db.get_value("HS Account", {"property": second_prop.name,
                                                       "account_number": number}, "name")
        fx_expense = frappe.db.get_value("HS Account", {"property": second_prop.name,
                                                         "account_number": "5001"}, "name")
        owner = account_number("3001")
        usd_cash = account_number("1010")
        nio_cash = api.execute(second_prop.name, "pms_account", "nio-cash-" + suffix,
            dict(account_code="1000" + suffix, account_name="Caja córdobas",
                 root_type="Asset", account_type="Cash"))["account"]
        ar = account_number("1200")
        deposit = account_number("2000")
        income = account_number("4000")
        operating_expense = account_number("5000")
        def assert_manual_control_rejected(selected, label):
            assert not next(row for row in api.pms_accounts(second_prop.name)
                            if row["name"] == selected)["manual_enabled"]
            before = standalone_accounting.balance(second_prop, selected)
            try:
                api.execute(second_prop.name, "pms_manual_journal",
                    "manual-control-" + label + suffix,
                    dict(reference="CONTROL-" + label + suffix,
                         reason="La cuenta tiene un auxiliar operativo",
                         lines=[dict(account=selected, debit="1.00", credit="0"),
                                dict(account=owner, debit="0", credit="1.00")]))
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Se ajustó directamente una cuenta de control: " + label)
            assert standalone_accounting.balance(second_prop, selected) == before

        api.execute(second_prop.name, "pms_opening_balance", "opening-fx-" + suffix,
            dict(reference="FX-OPEN-" + suffix, lines=[
                dict(account=nio_cash, debit="100.00", credit="0"),
                dict(account=usd_cash, debit="365.00", credit="0", account_currency="USD",
                     exchange_rate="36.5", debit_in_account_currency="10.00", credit_in_account_currency="0"),
                dict(account=owner, debit="0", credit="465.00")]))
        fx = api.execute(second_prop.name, "pms_manual_journal", "fx-" + suffix,
            dict(reference="FX-" + suffix, reason="Asiento con importe original en USD",
                 lines=[dict(account=fx_expense, debit="365.00", credit="0",
                             account_currency="USD", exchange_rate="36.5",
                             debit_in_account_currency="10.00", credit_in_account_currency="0"),
                        dict(account=owner, debit="0", credit="365.00")]))
        assert fx["total"] == "365.00"
        assert standalone_accounting.account_currency_balance(second_prop, fx_expense) == {
            "currency": "USD", "balance": "10.00", "base_currency": "NIO", "base_balance": "365.00"}
        from hospitality_suite import standalone_cash
        cash_method = api.execute(second_prop.name, "pms_payment_method", "cash-method-" + suffix,
                                  dict(label="Efectivo USD", account=usd_cash))["method"]
        nio_method = api.execute(second_prop.name, "pms_payment_method", "nio-method-" + suffix,
                                 dict(label="Efectivo NIO", account=nio_cash))["method"]
        bank_method = api.execute(second_prop.name, "pms_payment_method", "bank-method-" + suffix,
                                  dict(label="Banco USD", account=account_number("1020")))["method"]
        category = api.execute(second_prop.name, "pms_expense_category", "expense-category-" + suffix,
                               dict(label="Operación", account=operating_expense, max_amount="200"))["category"]
        concept = api.execute(second_prop.name, "pms_income_concept", "income-concept-" + suffix,
                              dict(label="Ingreso eventual", nature="Other Income", account=income))["concept"]
        customer = api.execute(second_prop.name, "pms_customer", "customer-" + suffix,
                               dict(party_name="Huésped " + suffix))["party"]
        charge = api.execute(second_prop.name, "pms_receivable", "receivable-" + suffix,
            dict(party=customer, reference="SALE-" + suffix, description="Cargo interno de prueba",
                 amount="1000", receivable_account=ar, income_account=income))
        receivable = charge["receivable"]
        assert standalone_accounting.balance(second_prop, ar) == "1000.00"
        assert_manual_control_rejected(ar, "AR")
        try:
            api.execute(second_prop.name, "pms_reverse_journal", "reverse-charge-" + suffix,
                dict(journal=charge["journal"], reason="No dejar saldos huérfanos"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revirtió el asiento de una cuenta por cobrar vigente")
        cancelled_source = api.execute(second_prop.name, "pms_receivable", "cancel-source-" + suffix,
            dict(party=customer, reference="CANCEL-" + suffix,
                 description="Cargo duplicado de prueba", amount="20",
                 receivable_account=ar, income_account=income))
        cancelled = api.execute(second_prop.name, "pms_cancel_receivable", "cancel-charge-" + suffix,
            dict(receivable=cancelled_source["receivable"], reason="Duplicado"))
        assert cancelled["status"] == "Cancelled"
        assert standalone_accounting.balance(second_prop, ar) == "1000.00"
        assert any(row["name"] == cancelled_source["receivable"]
                   for row in api.pms_receivables(second_prop.name)["cancelled"])
        shift = api.execute(second_prop.name, "pms_open_shift", "shift-" + suffix,
                            dict(opening_by_currency={"NIO": "100", "USD": "10"}))["shift"]
        try:
            api.execute(second_prop.name, "pms_cash_movement", "collect-cancelled-" + suffix,
                dict(kind="Payment", amount="1", method=cash_method, shift=shift,
                     receivable=cancelled_source["receivable"],
                     reference="CANCELLED-PAY-" + suffix, reason="Debe rechazarse"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió cobrar un cargo cancelado")
        receipt = api.execute(second_prop.name, "pms_cash_movement", "receipt-" + suffix,
            dict(kind="Advance", amount="5", method=cash_method, shift=shift,
                 counter_account=deposit, party=customer,
                 reference="ADV-" + suffix, reason="Anticipo de cliente"))
        assert receipt["base_amount"] == "182.50"
        assert api.execute(second_prop.name, "pms_cash_movement", "receipt-" + suffix,
            dict(kind="Advance", amount="5", method=cash_method, shift=shift,
                 counter_account=deposit, party=customer, reference="ADV-" + suffix,
                 reason="Anticipo de cliente")) == receipt
        eligible_advances = api.pms_deposits_page(second_prop.name, receivable)
        assert ([row["name"] for row in eligible_advances["rows"]] ==
                [receipt["payment"]] and
                eligible_advances["rows"][0]["available"] == "182.50" and
                not api.pms_deposits_page(second_prop.name, receivable,
                    search="missing-" + suffix)["rows"])
        try:
            api.pms_deposits_page(prop.name, receivable)
        except (frappe.ValidationError, frappe.PermissionError):
            frappe.clear_messages()
        else:
            raise AssertionError("Otra sede consultó depósitos de la cuenta")
        receipt_lines = frappe.get_doc("HS Journal", receipt["journal"]).lines
        assert sum(Decimal(str(line.debit)) for line in receipt_lines) == Decimal("182.50")
        assert sum(Decimal(str(line.credit)) for line in receipt_lines) == Decimal("182.50")
        assert any(line.account == usd_cash and Decimal(str(line.debit_in_account_currency)) == 5
                   for line in receipt_lines)
        assert_manual_control_rejected(deposit, "DEPOSIT")
        try:
            api.execute(second_prop.name, "pms_cash_movement", "stale-rate-" + suffix,
                dict(kind="Advance", amount="1", method=cash_method, shift=shift,
                     counter_account=deposit, party=customer, reference="STALE-" + suffix,
                     reason="Tasa cambiada", expected_exchange_rate="37.00",
                     expected_rate_record=recorded_rate["rate"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó un tipo de cambio distinto al revisado")
        api.execute(second_prop.name, "pms_cash_movement", "income-" + suffix,
            dict(kind="Other Income", amount="2", method=cash_method, shift=shift,
                 concept=concept, reference="INC-" + suffix, reason="Ingreso eventual"))
        api.execute(second_prop.name, "pms_cash_movement", "expense-" + suffix,
            dict(kind="Expense", amount="3", method=cash_method, shift=shift,
                 category=category, reference="EXP-" + suffix, reason="Gasto menor"))
        api.execute(second_prop.name, "pms_cash_movement", "bank-income-" + suffix,
            dict(kind="Other Income", amount="1", method=bank_method,
                 concept=concept, reference="BANK-" + suffix, reason="Ingreso bancario"))
        split_reference = "SPLIT-" + suffix
        cash_receipt = api.execute(second_prop.name, "pms_cash_movement", "split-cash-" + suffix,
            dict(kind="Payment", amount="4", method=cash_method, shift=shift,
                 receivable=receivable, reference=split_reference, reason="Cobro parcial efectivo"))
        bank_receipt = api.execute(second_prop.name, "pms_cash_movement", "split-bank-" + suffix,
            dict(kind="Payment", amount="2", method=bank_method,
                 receivable=receivable, reference=split_reference, reason="Cobro parcial banco"))
        assert cash_receipt["allocation"] and bank_receipt["allocation"]
        frappe.db.savepoint("hs_pms_opening_guarantee_probe")
        try:
            from hospitality_suite import standalone_opening_guarantees
            temporary = api.execute(second_prop.name, "pms_account",
                "guarantee-temporary-" + suffix,
                dict(account_code="TMP-" + suffix,
                     account_name="Temporal de garantía", root_type="Asset",
                     account_type="Temporary"))["account"]
            source_hash = "a" * 64
            with operation(second_prop):
                opening_journal = standalone_accounting.post(second_prop,
                    source_doctype="HS PMS Opening Guarantee",
                    source_name="OLD-GUAR-" + suffix,
                    purpose="Opening Guarantee", memo="Traslado verificado",
                    lines=[dict(account=temporary, debit="3.65", credit="0"),
                           dict(account=deposit, debit="0", credit="3.65")])
                old_hash = getattr(frappe.local, "hs_reverse_opening", None)
                frappe.local.hs_reverse_opening = source_hash
                try:
                    imported = insert("HS PMS Opening Guarantee", second_prop,
                        organization=second_prop.organization, customer=customer,
                        opening_source_site="erp-source.local",
                        opening_source_name="OLD-GUAR-" + suffix,
                        opening_source_sha256=source_hash,
                        source_booking="OLD-BOOK-" + suffix,
                        opening_temporary_account=temporary,
                        liability_account=deposit,
                        business_date=second_prop.business_date,
                        currency="NIO", amount="3.65",
                        journal=opening_journal.name, status="Posted")
                finally:
                    frappe.local.hs_reverse_opening = old_hash
            assert standalone_opening_guarantees.available(second_prop,
                imported.name) == Decimal("3.65")
            assert any(row["name"] == imported.name and row["available"] == "3.65"
                       for row in api.pms_receivables(second_prop.name)["opening_guarantees"])
            refund_data = dict(guarantee=imported.name, method=bank_method,
                amount="0.02", reference="OLD-GUAR-REF-" + suffix,
                reason="Devolución parcial verificada")
            quote = api.pms_opening_guarantee_refund_quote(second_prop.name,
                refund_data)
            assert quote["base_amount"] == "0.73"
            returned = api.execute(second_prop.name,
                "pms_refund_opening_guarantee", "guarantee-refund-" + suffix,
                {**refund_data, "acceptance": quote["acceptance"]})
            assert returned["guarantee_available"] == "2.92"
            assert returned == api.execute(second_prop.name,
                "pms_refund_opening_guarantee", "guarantee-refund-" + suffix,
                {**refund_data, "acceptance": quote["acceptance"]})
            assert frappe.db.get_value("HS Payment", returned["payment"],
                "source_payment") is None
            lines = frappe.get_all("HS Journal Line",
                filters={"parent": returned["journal"]},
                fields=["account", "party", "debit", "credit"])
            assert {(row.account, row.party, Decimal(str(row.debit)),
                     Decimal(str(row.credit))) for row in lines} == {
                (deposit, None, Decimal("0.73"), Decimal(0)),
                (account_number("1020"), None, Decimal(0), Decimal("0.73"))}
            for denied in (
                    lambda: api.pms_opening_guarantee_refund_quote(prop.name,
                        refund_data),
                    lambda: api.pms_opening_guarantee_refund_quote(second_prop.name,
                        {**refund_data, "amount": "1"}),
                    lambda: api.execute(second_prop.name, "pms_reverse_journal",
                        "guarantee-reverse-" + suffix,
                        {"journal": opening_journal.name, "reason": "No aplica"})):
                try:
                    denied()
                except (frappe.ValidationError, frappe.PermissionError):
                    frappe.clear_messages()
                else:
                    raise AssertionError("Se alteró una garantía inicial fuera de su flujo")
        finally:
            frappe.db.rollback(save_point="hs_pms_opening_guarantee_probe")
        applied = api.execute(second_prop.name, "pms_apply_advance", "apply-" + suffix,
            dict(receivable=receivable, advance=receipt["payment"], amount="100",
                 reason="Aplicación parcial del anticipo"))
        assert applied["outstanding"] == "681.00" and applied["advance_available"] == "82.50"
        advance_applications = api.pms_applications_page(second_prop.name,
            kind="Advance", search="ADV-" + suffix)
        assert ([(row["name"], row["currency"], row["remaining"])
                 for row in advance_applications["rows"]] ==
                [(applied["allocation"], "NIO", "100.00")] and
                not api.pms_applications_page(second_prop.name,
                    kind="Guarantee", search="ADV-" + suffix)["rows"])
        try:
            api.execute(second_prop.name, "pms_cancel_receivable", "cancel-paid-" + suffix,
                dict(receivable=receivable, reason="Tiene aplicaciones"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló una cuenta con cobros aplicados")
        try:
            api.execute(second_prop.name, "pms_apply_advance", "overapply-" + suffix,
                dict(receivable=receivable, advance=receipt["payment"], amount="83",
                     reason="Exceso de aplicación"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió aplicar más del anticipo disponible")
        try:
            api.execute(second_prop.name, "pms_cash_movement", "overcollect-" + suffix,
                dict(kind="Payment", amount="100", method=bank_method,
                     receivable=receivable, reference="OVERPAY-" + suffix,
                     reason="Exceso de cobro"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió cobrar más del saldo pendiente")
        try:
            api.execute(second_prop.name, "pms_cash_movement", "overspend-" + suffix,
                dict(kind="Expense", amount="20", method=cash_method, shift=shift,
                     category=category, reference="OVER-" + suffix, reason="Exceso de efectivo"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió desembolsar más efectivo del turno")
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["USD"] == "18.00"
        assert standalone_accounting.account_currency_balance(second_prop, usd_cash)["balance"] == "18.00"
        cash_view = api.pms_cash_snapshot(second_prop.name)
        assert any(row["name"] == deposit for row in cash_view["deposit_accounts"])
        assert any(row["name"] == customer for row in cash_view["customers"])
        assert len(cash_view["movements"]) == 6
        assert cash_view["shifts"][0]["expected"]["USD"] == "18.00"
        assert any(row["name"] == receivable and row["outstanding"] == "681.00"
                   for row in api.pms_receivables(second_prop.name)["receivables"])
        def folio_fixture(locked):
            category = insert("HS Category", locked, category_name="Estándar", capacity=2)
            room = insert("HS Room", locked, room_number="201", category=category.name,
                          active=1, cleaning_status="Clean")
            arrival_room = insert("HS Room", locked, room_number="202", category=category.name,
                                  active=1, cleaning_status="Clean")
            reception_room = insert("HS Room", locked, room_number="203", category=category.name,
                                    active=1, cleaning_status="Clean")
            move_room = insert("HS Room", locked, room_number="204", category=category.name,
                               active=1, cleaning_status="Clean")
            rate = insert("HS Rate", locked, title="Tarifa de prueba", category=category.name,
                          mode="Hotel", currency=locked.currency, amount=100, active=1)
            guest = insert("HS Guest", locked, full_name="Huésped folio", customer=customer)
            start = frappe.utils.now_datetime()
            stay = insert("HS Stay", locked, guest=guest.name, customer=customer,
                          room=room.name, rate=rate.name, currency=locked.currency,
                          amount="100", starts_at=start, ends_at=start + timedelta(days=1),
                          status="Active", lodging_charge_policy="Arrival")
            folio = insert("HS Folio", locked, stay=stay.name, customer=customer,
                           currency=locked.currency, status="Open", label="Cuenta principal")
            product = insert("HS Product", locked, organization=org.name,
                             product_code="ROOM" + suffix, product_name="Alojamiento",
                             product_type="Service", income_account=income, active=1)
            source = insert("HS Charge", locked, stay=stay.name, folio=folio.name,
                            item=product.name, description="Noche", quantity=1, rate="100",
                            currency=locked.currency, amount="100", business_date=locked.business_date,
                            kind="Lodging", status="Pending")
            return {"folio": folio.name, "source": source.name, "stay": stay.name,
                    "category": category.name, "arrival_room": arrival_room.name,
                    "reception_room": reception_room.name, "move_room": move_room.name,
                    "guest": guest.name}

        fixture = command(second_prop.name, "setup", "folio-fixture-" + suffix,
                          {"operation": "smoke_folio_fixture"}, folio_fixture)
        room_services = api.pms_service_snapshot(second_prop.name, fixture["stay"])
        assert [row["name"] for row in room_services["stays"]] == [fixture["stay"]]
        assert fixture["folio"] in [row["name"] for row in room_services["stays"][0]["folios"]]
        try:
            api.pms_service_snapshot(prop.name, fixture["stay"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Una sede consultó servicios de la estancia ajena")
        initial_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=fixture["folio"], receivable_account=ar))
        assert initial_quote["total"] == "100.00"
        def add_discount(locked):
            source = frappe.get_doc("HS Charge", fixture["source"])
            return insert("HS Charge", locked, stay=source.stay, folio=source.folio,
                          item=source.item, description="Descuento", quantity=1, rate="-10",
                          currency=locked.currency, amount="-10", business_date=locked.business_date,
                          kind="Adjustment", status="Pending", applies_to_charge=source.name).name
        discount = command(second_prop.name, "approve", "folio-discount-" + suffix,
                           {"operation": "smoke_folio_discount"}, add_discount)
        try:
            api.execute(second_prop.name, "pms_bill_folio", "folio-stale-" + suffix,
                dict(folio=fixture["folio"], receivable_account=ar,
                     acceptance=initial_quote["acceptance"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se contabilizó un folio cuya cotización cambió")
        quote = api.pms_folio_quote(second_prop.name,
            dict(folio=fixture["folio"], receivable_account=ar))
        assert quote["total"] == "90.00" and len(quote["lines"]) == 1
        billed = api.execute(second_prop.name, "pms_bill_folio", "folio-bill-" + suffix,
            dict(folio=fixture["folio"], receivable_account=ar,
                 acceptance=quote["acceptance"]))
        assert billed["total"] == "90.00"
        room_cash = api.pms_cash_snapshot(second_prop.name, fixture["folio"])
        assert room_cash["receivables"]
        assert all(row["folio"] == fixture["folio"] for row in room_cash["receivables"])
        assert any(row["name"] == billed["receivables"][0]["receivable"]
                   for row in room_cash["receivables"])
        assert all(row["name"] != receivable for row in room_cash["receivables"])
        assert not api.pms_cash_snapshot(prop.name, fixture["folio"])["receivables"]
        assert api.execute(second_prop.name, "pms_bill_folio", "folio-bill-" + suffix,
            dict(folio=fixture["folio"], receivable_account=ar,
                 acceptance=quote["acceptance"])) == billed
        try:
            api.execute(second_prop.name, "pms_bill_folio", "folio-duplicate-" + suffix,
                dict(folio=fixture["folio"], receivable_account=ar,
                     acceptance=quote["acceptance"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se contabilizó dos veces el mismo cargo del folio")
        try:
            api.pms_folio_quote(prop.name,
                dict(folio=fixture["folio"], receivable_account=ar))
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Una sede consultó un folio ajeno")
        assert all(frappe.db.get_value("HS Charge", name, "pms_receivable") ==
                   billed["receivables"][0]["receivable"] for name in (fixture["source"], discount))
        from hospitality_suite.accounting import folio_balance
        assert folio_balance(fixture["folio"])["outstanding"] == "90.00"
        assert any(row["name"] == fixture["folio"] and
                   row["balance"]["outstanding"] == "90.00"
                   for row in api.pms_folios(second_prop.name))
        cancelled_folio = api.execute(second_prop.name, "pms_cancel_receivable",
            "folio-cancel-" + suffix,
            dict(receivable=billed["receivables"][0]["receivable"], reason="Corrección"))
        assert cancelled_folio["status"] == "Cancelled"
        assert frappe.db.get_value("HS Charge", fixture["source"], "status") == "Pending"
        assert folio_balance(fixture["folio"])["outstanding"] == "90.00"
        split = api.execute(second_prop.name, "create_folio",
            "folio-split-" + suffix,
            dict(stay=fixture["stay"], customer=customer, label="Cuenta separada"))
        source_page = api.folio_pending_charges(second_prop.name, fixture["folio"], 0, 25)
        assert source_page["total"] >= 1 and any(
            row["name"] == fixture["source"] for row in source_page["rows"])
        target_options = api.folio_transfer_targets(second_prop.name, fixture["source"])
        assert split["folio"] in [row["name"] for row in target_options["targets"]]
        try:
            api.folio_pending_charges(prop.name, fixture["folio"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Una sede consultó cargos de un folio ajeno")
        try:
            api.folio_transfer_targets(prop.name, fixture["source"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Una sede consultó destinos de un cargo ajeno")
        move_data = {"charge": fixture["source"], "folio": split["folio"],
            "reason": "Distribución del cargo"}
        moved = api.execute(second_prop.name, "move_charge", "folio-move-" + suffix,
            move_data)
        assert moved == api.execute(second_prop.name, "move_charge",
            "folio-move-" + suffix, move_data)
        assert all(frappe.db.get_value("HS Charge", name, "folio") == split["folio"]
            for name in (fixture["source"], discount))
        api.execute(second_prop.name, "move_charge", "folio-move-back-" + suffix,
            {"charge": fixture["source"], "folio": fixture["folio"],
             "reason": "Restablecer la cuenta original"})
        assert all(frappe.db.get_value("HS Charge", name, "folio") == fixture["folio"]
            for name in (fixture["source"], discount))
        revised_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=fixture["folio"], receivable_account=ar))
        rebilled = api.execute(second_prop.name, "pms_bill_folio", "folio-rebill-" + suffix,
            dict(folio=fixture["folio"], receivable_account=ar,
                 acceptance=revised_quote["acceptance"]))
        assert folio_balance(fixture["folio"])["outstanding"] == "90.00"
        api.execute(second_prop.name, "pms_cash_movement", "folio-bank-pay-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=rebilled["receivables"][0]["receivable"],
                 reference="FOLIO-PAY-" + suffix, reason="Cobro parcial del folio"))
        assert folio_balance(fixture["folio"])["outstanding"] == "53.50"
        from hospitality_suite.standalone_receivables import deposit_available
        liability_before = Decimal(standalone_accounting.balance(second_prop, deposit))
        guarantee = api.execute(second_prop.name, "pms_cash_movement", "guarantee-" + suffix,
            dict(kind="Guarantee", amount="2", method=bank_method,
                 counter_account=deposit, party=customer, folio=fixture["folio"],
                 reference="GUAR-" + suffix, reason="Garantía del folio"))
        assert api.execute(second_prop.name, "pms_cash_movement", "guarantee-" + suffix,
            dict(kind="Guarantee", amount="2", method=bank_method,
                 counter_account=deposit, party=customer, folio=fixture["folio"],
                 reference="GUAR-" + suffix, reason="Garantía del folio")) == guarantee
        assert guarantee["base_amount"] == "73.00"
        assert deposit_available(second_prop, guarantee["payment"], "Guarantee") == Decimal("73.00")
        eligible_guarantees = api.pms_deposits_page(second_prop.name,
            rebilled["receivables"][0]["receivable"], kind="Guarantee")
        assert ([row["name"] for row in eligible_guarantees["rows"]] ==
                [guarantee["payment"]] and
                eligible_guarantees["rows"][0]["available"] == "73.00")
        assert any(row["source"] == guarantee["payment"] and
                   row["kind"] == "Guarantee" for prop in
                   api.pms_cutover_preflight()["properties"]
                   for row in prop["open_deposits"])
        assert Decimal(standalone_accounting.balance(second_prop, deposit)) == liability_before - 73
        guarantee_applied = api.execute(second_prop.name, "pms_apply_guarantee", "apply-guarantee-" + suffix,
            dict(receivable=rebilled["receivables"][0]["receivable"],
                 guarantee=guarantee["payment"], amount="20", reason="Cargo cubierto con garantía"))
        assert api.execute(second_prop.name, "pms_apply_guarantee", "apply-guarantee-" + suffix,
            dict(receivable=rebilled["receivables"][0]["receivable"],
                 guarantee=guarantee["payment"], amount="20", reason="Cargo cubierto con garantía")) == guarantee_applied
        assert guarantee_applied["outstanding"] == "33.50"
        assert guarantee_applied["guarantee_available"] == "53.00"
        guarantee_applications = api.pms_applications_page(second_prop.name,
            kind="Guarantee", search="GUAR-" + suffix)
        assert any(row["name"] == guarantee_applied["allocation"] and
                   row["remaining"] == "20.00"
                   for row in guarantee_applications["rows"])
        assert folio_balance(fixture["folio"])["outstanding"] == "33.50"
        try:
            api.execute(prop.name, "pms_apply_guarantee", "foreign-guarantee-" + suffix,
                dict(receivable=rebilled["receivables"][0]["receivable"],
                     guarantee=guarantee["payment"], amount="1", reason="Sede ajena"))
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Otra sede aplicó la garantía")
        try:
            api.execute(second_prop.name, "pms_apply_guarantee", "over-guarantee-" + suffix,
                dict(receivable=rebilled["receivables"][0]["receivable"],
                     guarantee=guarantee["payment"], amount="54", reason="Excede el saldo"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aplicó una garantía por encima de su saldo")
        guarantee_unapplied = api.execute(second_prop.name, "pms_unapply_guarantee",
            "unapply-guarantee-" + suffix,
            dict(allocation=guarantee_applied["allocation"], amount="5", reason="Corrección"))
        assert guarantee_unapplied["outstanding"] == "38.50"
        assert guarantee_unapplied["guarantee_available"] == "58.00"
        assert any(row["name"] == guarantee_applied["allocation"] and
                   row["remaining"] == "15.00"
                   for row in api.pms_applications_page(second_prop.name,
                       kind="Guarantee", search="GUAR-" + suffix)["rows"])
        guarantee_refund = api.execute(second_prop.name, "pms_refund", "refund-guarantee-" + suffix,
            dict(source_payment=guarantee["payment"], amount="1",
                 reference="GUAR-REF-" + suffix, reason="Devolución parcial de garantía"))
        assert guarantee_refund["base_amount"] == "36.50"
        assert frappe.db.get_value("HS Payment", guarantee_refund["payment"], "kind") == "Guarantee Refund"
        assert deposit_available(second_prop, guarantee["payment"], "Guarantee") == Decimal("21.50")
        assert Decimal(standalone_accounting.balance(second_prop, deposit)) == liability_before - Decimal("21.50")
        assert any(row["name"] == guarantee["payment"] and row["remaining_amount"] == "0.59"
                   for row in api.pms_cash_snapshot(second_prop.name)["refundable"])
        try:
            api.execute(second_prop.name, "pms_refund", "over-guarantee-refund-" + suffix,
                dict(source_payment=guarantee["payment"], amount="1",
                     reference="GUAR-OVER-" + suffix, reason="Excede el saldo"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se devolvió una garantía ya aplicada")
        assert any(row["name"] == guarantee["payment"] and row["available"] == "21.50"
                   for row in api.pms_receivables(second_prop.name)["guarantees"])
        assert any(row["name"] == guarantee_applied["allocation"] and row["remaining"] == "15.00"
                   for row in api.pms_receivables(second_prop.name)["applied_guarantees"])
        cash_before = standalone_cash.expected(frappe.get_doc("HS Shift", shift))["USD"]
        cash_guarantee = api.execute(second_prop.name, "pms_cash_movement",
            "cash-guarantee-" + suffix,
            dict(kind="Guarantee", amount="1", method=cash_method, shift=shift,
                 counter_account=deposit, party=customer, folio=fixture["folio"],
                 reference="CASH-GUAR-" + suffix, reason="Garantía en efectivo"))
        assert Decimal(standalone_cash.expected(frappe.get_doc("HS Shift", shift))["USD"]) == Decimal(cash_before) + 1
        api.execute(second_prop.name, "pms_refund", "cash-guarantee-refund-" + suffix,
            dict(source_payment=cash_guarantee["payment"], amount="1", shift=shift,
                 reference="CASH-GUAR-REF-" + suffix, reason="Devolución íntegra"))
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["USD"] == cash_before
        try:
            api.execute(second_prop.name, "pms_cancel_receivable", "folio-paid-cancel-" + suffix,
                dict(receivable=rebilled["receivables"][0]["receivable"], reason="Con cobro"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló un cargo de folio ya cobrado")
        lodging_product = api.save_setup(second_prop.name, "product",
            dict(product_code="LODGE" + suffix, product_name="Alojamiento",
                 product_type="Service", income_account=income, active=1),
            "lodging-product-" + suffix)["name"]
        api.save_setup(second_prop.name, "property",
            dict(lodging_item=lodging_product), "lodging-binding-" + suffix,
            expected_modified=str(frappe.db.get_value("HS Property", second_prop.name, "modified")))
        catalog = api.pms_products(second_prop.name)
        assert catalog["bindings"]["lodging_item"] == lodging_product
        assert any(row["name"] == lodging_product for row in catalog["products"])
        api.save_setup(second_prop.name, "property",
            dict(timing_item=lodging_product), "reception-timing-" + suffix,
            expected_modified=str(frappe.db.get_value("HS Property", second_prop.name, "modified")))
        new_guest_data = dict(full_name="Huésped recepción " + suffix,
                              identity_type="Documento", identity_number="ID-" + suffix)
        new_guest = api.execute(second_prop.name, "pms_create_guest",
            "reception-guest-" + suffix, new_guest_data)
        assert api.execute(second_prop.name, "pms_create_guest",
            "reception-guest-" + suffix, new_guest_data) == new_guest
        companion_guest = api.execute(second_prop.name, "pms_create_guest",
            "reception-companion-" + suffix,
            dict(full_name="Acompañante recepción " + suffix,
                 identity_type="Documento", identity_number="AC-" + suffix))
        guest_page = api.guest_directory(second_prop.name, search=suffix, page_length=1)
        guest_next = api.guest_directory(second_prop.name, search=suffix,
            page_length=1, offset=1)
        assert guest_page["total"] >= 2 and guest_page["has_more"]
        assert guest_page["rows"][0]["name"] != guest_next["rows"][0]["name"]
        assert not api.guest_directory(prop.name, search="Acompañante recepción " + suffix)["rows"]
        frappe.set_user("Guest")
        try:
            api.guest_directory(second_prop.name)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Un visitante consultó las fichas de huéspedes")
        finally:
            frappe.set_user("Administrator")
        guest_profile = api.guest_detail(new_guest["guest"])
        assert guest_profile["property"] == second_prop.name
        assert guest_profile["customer"] == new_guest["party"]
        assert guest_profile["values"]["identity_number"] == "ID-" + suffix
        guest_update_data = {"phone": "+505 2222 0000"}
        guest_update = api.update_guest(second_prop.name, new_guest["guest"],
            guest_profile["modified"], guest_update_data, "Corrección de teléfono",
            "reception-guest-edit-" + suffix)
        assert guest_update == api.update_guest(second_prop.name, new_guest["guest"],
            guest_profile["modified"], guest_update_data, "Corrección de teléfono",
            "reception-guest-edit-" + suffix)
        assert api.guest_detail(new_guest["guest"])["values"]["phone"] == "+505 2222 0000"
        assert api.guest_detail(new_guest["guest"])["customer"] == new_guest["party"]
        try:
            api.update_guest(second_prop.name, new_guest["guest"],
                guest_update["modified"], {"customer": customer}, "Cambiar pagador",
                "reception-guest-payer-" + suffix)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se cambió el pagador al corregir la ficha")
        try:
            api.update_guest(second_prop.name, new_guest["guest"],
                guest_profile["modified"], {"phone": "0000"}, "Versión antigua",
                "reception-guest-stale-" + suffix)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó una versión antigua de la ficha")
        try:
            api.update_guest(prop.name, new_guest["guest"], guest_update["modified"],
                {"phone": "1111"}, "Hotel incorrecto", "reception-guest-foreign-" + suffix)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Se corrigió una ficha de otro establecimiento")
        try:
            api.execute(prop.name, "pms_create_guest", "foreign-reception-" + suffix,
                dict(full_name="Huésped de otra sede", party=new_guest["party"]))
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Se vinculó un huésped con pagador de otro establecimiento")
        def included_rate_fixture(locked):
            benefit = insert("HS Product", locked, organization=org.name,
                product_code="BREAKFAST" + suffix, product_name="Desayuno incluido",
                product_type="Service", income_account=income, active=1)
            nightly_benefit = insert("HS Product", locked, organization=org.name,
                product_code="NIGHTWATER" + suffix, product_name="Agua por noche",
                product_type="Service", income_account=income, active=1)
            rate = insert("HS Rate", locked, title="Tarifa con desayuno", category=fixture["category"],
                mode="Hotel", currency=locked.currency, amount=100, priority=15, active=1,
                included_services=[dict(item=benefit.name, quantity=1, basis="Stay"),
                                   dict(item=nightly_benefit.name, quantity=1, basis="Night")])
            return {"rate": rate.name, "product": benefit.name,
                    "nightly_product": nightly_benefit.name}
        included = command(second_prop.name, "setup", "included-rate-" + suffix,
            {"operation": "smoke_included_rate"}, included_rate_fixture)
        reception_start = (now_local(second_prop) - timedelta(minutes=1)).replace(
            second=0, microsecond=0, tzinfo=None)
        reception_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            starts_at=reception_start.isoformat(timespec="minutes"),
            ends_at=(reception_start + timedelta(days=1)).isoformat(timespec="minutes"), mode="Hotel",
            rooms=[dict(category=fixture["category"], room=fixture["reception_room"],
                        people=2, rate=included["rate"])])
        frappe.db.savepoint("hs_pms_booking_draft_react_probe")
        try:
            first_values = dict(mode="Hotel", customer=new_guest["party"],
                channel="Recepción React", rooms=[dict(category=fixture["category"], people=1)])
            first = api.execute(second_prop.name, "save_booking_draft",
                "draft-first-" + suffix, dict(values=first_values))
            assert first == api.execute(second_prop.name, "save_booking_draft",
                "draft-first-" + suffix, dict(values=first_values))
            second = api.execute(second_prop.name, "save_booking_draft",
                "draft-second-" + suffix, dict(values=dict(mode="Hotel")))
            first_page = api.reservation_page(second_prop.name, "draft", "", 0, 1)
            next_page = api.reservation_page(second_prop.name, "draft", "", 1, 1)
            assert (first_page["has_more"] and len(next_page["rows"]) == 1 and
                    first_page["rows"][0]["name"] != next_page["rows"][0]["name"] and
                    api.booking_detail(first["booking"])["draft"]["customer"] == new_guest["party"] and
                    api.reservation_page(second_prop.name, "draft", first["booking"])["rows"][0]["name"] == first["booking"] and
                    not api.reservation_page(prop.name, "draft", first["booking"])["rows"])
            from hospitality_suite.printing import hs_booking_customer
            assert "Huésped recepción" in str(hs_booking_customer(
                frappe.get_doc("HS Booking", first["booking"])))
            draft_print = frappe.get_print("HS Booking", first["booking"],
                print_format="HS Confirmación de reserva")
            assert ("BORRADOR DE RESERVA" in draft_print and
                    "Huésped recepción" in draft_print)
            discarded = api.execute(second_prop.name, "discard_booking_draft",
                "draft-discard-" + suffix, dict(booking=second["booking"],
                    modified=second["modified"], reason="No continúa"))
            assert (discarded["status"] == "Cancelled" and
                    api.reservation_page(second_prop.name, "history",
                        second["booking"])["rows"][0]["status"] == "Cancelled")
            complete = dict(first_values, **reception_data)
            reviewed = api.preview(second_prop.name,
                dict(booking=first["booking"], modified=first["modified"], values=complete),
                "confirm_booking_draft")
            accepted = api.execute(second_prop.name, "confirm_booking_draft",
                "draft-confirm-" + suffix,
                dict(booking=first["booking"], modified=first["modified"],
                     values=complete, draft_acceptance=reviewed["draft_acceptance"]))
            assert (accepted["status"] == "Confirmed" and
                    api.reservation_page(second_prop.name, "current",
                        first["booking"])["rows"][0]["name"] == first["booking"])
            workflow_detail = api.booking_detail(first["booking"])
            assert (workflow_detail["workflow"]["mode"] == "Hotel" and
                    workflow_detail["workflow"]["modifiable"] and
                    workflow_detail["workflow"]["can_arrive"] and
                    workflow_detail["workflow"]["can_cancel"] and
                    workflow_detail["workflow"]["customer"] == new_guest["party"] and
                    workflow_detail["workflow"]["rooms"][0]["category"] == fixture["category"] and
                    workflow_detail["allocations"][0]["booking"] == first["booking"])
            confirmed_print = frappe.get_print("HS Booking", first["booking"],
                print_format="HS Confirmación de reserva")
            assert ("CONFIRMACIÓN DE RESERVA" in confirmed_print and
                    "Huésped recepción" in confirmed_print)
            frappe.db.set_value("HS Property", second_prop.name, "discreet_mode", 1,
                                update_modified=False)
            try:
                assert api.reservation_page(second_prop.name, "current",
                    first["booking"])["rows"][0]["guest_label"] == "Huésped registrado"
            finally:
                frappe.db.set_value("HS Property", second_prop.name,
                                    "discreet_mode", second_prop.discreet_mode,
                                    update_modified=False)
            frappe.set_user("Guest")
            try:
                api.reservation_page(second_prop.name)
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("Un visitante consultó las reservas privadas")
            finally:
                frappe.set_user("Administrator")
        finally:
            frappe.db.rollback(save_point="hs_pms_booking_draft_react_probe")
        reception_quote = api.preview(second_prop.name, reception_data, "reserve")
        assert any("Desayuno incluido" in message for message in
                   reception_quote["lines"][0]["explanation"])
        reception_booking = api.execute(second_prop.name, "reserve", "reception-booking-" + suffix,
            {**reception_data, "acceptance": reception_quote["acceptance"]})
        reception_snapshot = api.pms_reception_snapshot(second_prop.name)
        assert any(row["name"] == new_guest["guest"] for row in reception_snapshot["guests"])
        assert any(row["name"] == reception_booking["booking"] for row in reception_snapshot["bookings"])
        frappe.db.savepoint("hs_reception_link_probe")
        try:
            frappe.db.set_value("HS Property", second_prop.name,
                "portal_enabled", 1, update_modified=False)
            assert api.pms_reception_snapshot(second_prop.name)["portal_enabled"]
            from hospitality_suite import portal
            signed = api.execute(second_prop.name, "portal_link",
                "reception-link-" + suffix, {"booking": reception_booking["booking"]})
            assert signed == api.execute(second_prop.name, "portal_link",
                "reception-link-" + suffix, {"booking": reception_booking["booking"]})
            token = signed["url"].split("token=", 1)[1]
            assert portal.verify(token)["name"] == reception_booking["booking"]
            assert portal.confirmation(token)["status"] == "Confirmed"
        finally:
            frappe.db.rollback(save_point="hs_reception_link_probe")
        arrival = next(row for row in reception_snapshot["allocations"]
                       if row["booking"] == reception_booking["booking"])
        arrival_quote = api.preview(second_prop.name,
            dict(booking=reception_booking["booking"], allocation=arrival["name"]), "check_in")
        reception_check_in = dict(booking=reception_booking["booking"],
            modified=reception_booking["modified"], allocation=arrival["name"],
            room=fixture["reception_room"], guest=new_guest["guest"],
            timing_acceptance=arrival_quote["acceptance"])
        reception_stay = api.execute(second_prop.name, "check_in",
            "reception-check-in-" + suffix, reception_check_in)
        assert api.execute(second_prop.name, "check_in",
            "reception-check-in-" + suffix, reception_check_in) == reception_stay
        assert reception_stay["room"] == fixture["reception_room"]
        stay_list = api.stay_page(second_prop.name, "active", reception_stay["stay"], 0, 1)
        stay_view = api.stay_overview(second_prop.name, reception_stay["stay"])
        stay_charges = api.stay_charge_page(second_prop.name, reception_stay["stay"], 0, 1)
        assert (len(stay_list["rows"]) == 1 and
                stay_list["rows"][0]["name"] == reception_stay["stay"] and
                stay_view["status"] == "Active" and
                stay_view["folios"][0]["name"] == reception_stay["folio"] and
                stay_charges["rows"] and
                stay_charges["rows"][0]["folio"] == reception_stay["folio"] and
                not api.stay_page(prop.name, "active", reception_stay["stay"])["rows"])
        assert api.stay_page(second_prop.name, "active",
            "Huésped recepción")["rows"][0]["name"] == reception_stay["stay"]
        frappe.db.set_value("HS Property", second_prop.name, "discreet_mode", 1,
                            update_modified=False)
        try:
            assert (api.stay_page(second_prop.name, "active",
                        reception_stay["stay"])["rows"][0]["guest_label"] ==
                    "Huésped registrado" and
                    api.stay_overview(second_prop.name,
                        reception_stay["stay"])["guest_label"] ==
                    "Huésped registrado" and
                    not api.stay_page(second_prop.name, "active",
                        "Huésped recepción")["rows"])
        finally:
            frappe.db.set_value("HS Property", second_prop.name,
                                "discreet_mode", second_prop.discreet_mode,
                                update_modified=False)
        try:
            api.stay_overview(prop.name, reception_stay["stay"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Una estancia de otro hotel quedó visible")
        frappe.set_user("Guest")
        try:
            api.stay_page(second_prop.name)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Un visitante consultó estancias privadas")
        finally:
            frappe.set_user("Administrator")
        assert included["product"] in frappe.db.get_value("HS Stay", reception_stay["stay"],
            "service_entitlements")
        companion_page = api.stay_companions(second_prop.name, reception_stay["stay"],
            search="Acompañante recepción " + suffix, page_length=1)
        assert companion_page["capacity"] == 2 and companion_page["total"] == 1
        assert companion_page["candidates"][0]["name"] == companion_guest["guest"]
        assert companion_page["candidates"][0]["has_identity"]
        try:
            api.stay_companions(prop.name, reception_stay["stay"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("La consulta de acompañantes cruzó establecimientos")
        companion_data = {"stay": reception_stay["stay"],
            "modified": companion_page["modified"],
            "guests": [companion_guest["guest"]]}
        companion_result = api.execute(second_prop.name, "companions",
            "reception-companions-" + suffix, companion_data)
        assert api.execute(second_prop.name, "companions",
            "reception-companions-" + suffix, companion_data) == companion_result
        assert [row["name"] for row in api.stay_companions(second_prop.name,
            reception_stay["stay"])["selected"]] == [companion_guest["guest"]]
        try:
            api.execute(second_prop.name, "companions", "reception-overcapacity-" + suffix,
                {"stay": reception_stay["stay"], "modified": companion_result["modified"],
                 "guests": [companion_guest["guest"], fixture["guest"]]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó ocupación superior a la reserva")
        move_data = dict(stay=reception_stay["stay"],
            modified=str(frappe.db.get_value("HS Stay", reception_stay["stay"], "modified")),
            room=fixture["move_room"], folio=reception_stay["folio"],
            reason="Cambio solicitado por el huésped")
        move_quote = api.preview(second_prop.name, move_data, "change_room")
        assert Decimal(move_quote["difference"]) == 0
        moved = api.execute(second_prop.name, "change_room", "reception-move-" + suffix,
            {**move_data, "acceptance": move_quote["acceptance"]})
        assert api.execute(second_prop.name, "change_room", "reception-move-" + suffix,
            {**move_data, "acceptance": move_quote["acceptance"]}) == moved
        assert moved["room"] == fixture["move_room"]
        assert frappe.db.get_value("HS Stay", reception_stay["stay"], "room") == fixture["move_room"]
        assert frappe.db.get_value("HS Room", fixture["reception_room"], "cleaning_status") == "Dirty"
        assert frappe.db.exists("HS Cleaning Task", {"stay": reception_stay["stay"],
            "room": fixture["reception_room"]})
        frappe.db.savepoint("pms_stay_extension")
        try:
            extension_data = dict(stay=reception_stay["stay"],
                modified=str(frappe.db.get_value("HS Stay", reception_stay["stay"], "modified")),
                ends_at=(reception_start + timedelta(days=2)).isoformat(timespec="minutes"),
                folio=reception_stay["folio"], reason="Una noche adicional solicitada")
            extension_quote = api.preview(second_prop.name, extension_data, "extend")
            assert Decimal(extension_quote["difference"]) == Decimal("100.00")
            assert any("Agua por noche" in line for line in extension_quote["explanation"]), extension_quote
            extended = api.execute(second_prop.name, "extend", "reception-extend-" + suffix,
                {**extension_data, "acceptance": extension_quote["acceptance"]})
            assert api.execute(second_prop.name, "extend", "reception-extend-" + suffix,
                {**extension_data, "acceptance": extension_quote["acceptance"]}) == extended
            assert Decimal(str(frappe.db.get_value("HS Stay", reception_stay["stay"],
                "amount"))) == Decimal("200.00")
            assert frappe.db.exists("HS Charge", {"stay": reception_stay["stay"],
                "description": "Extensión de estancia", "amount": 100,
                "item": lodging_product})
        finally:
            frappe.db.rollback(save_point="pms_stay_extension")
        frappe.db.savepoint("pms_room_upgrade")
        try:
            def upgrade_fixture(locked):
                standard_room = insert("HS Room", locked, room_number="206",
                    category=fixture["category"], active=1, cleaning_status="Clean")
                downgrade_room = insert("HS Room", locked, room_number="208",
                    category=fixture["category"], active=1, cleaning_status="Clean")
                suite_category = insert("HS Category", locked, category_name="Suite", capacity=2)
                suite_room = insert("HS Room", locked, room_number="207",
                    category=suite_category.name, active=1, cleaning_status="Clean")
                insert("HS Rate", locked, title="Tarifa Suite", category=suite_category.name,
                    mode="Hotel", currency=locked.currency, amount=150, priority=5, active=1)
                return dict(standard=standard_room.name, suite=suite_room.name,
                    downgrade=downgrade_room.name)
            upgrade = command(second_prop.name, "setup", "upgrade-fixture-" + suffix,
                {"operation": "upgrade_fixture"}, upgrade_fixture)
            upgrade_data = {**reception_data, "rooms": [dict(category=fixture["category"],
                room=upgrade["standard"], people=1, rate=included["rate"])]}
            upgrade_quote = api.preview(second_prop.name, upgrade_data, "reserve")
            upgrade_booking = api.execute(second_prop.name, "reserve", "upgrade-booking-" + suffix,
                {**upgrade_data, "acceptance": upgrade_quote["acceptance"]})
            upgrade_arrival = api.pms_reception_snapshot(second_prop.name)["allocations"]
            upgrade_allocation = next(row["name"] for row in upgrade_arrival
                if row["booking"] == upgrade_booking["booking"])
            upgrade_timing = api.preview(second_prop.name,
                dict(booking=upgrade_booking["booking"], allocation=upgrade_allocation), "check_in")
            upgrade_stay = api.execute(second_prop.name, "check_in", "upgrade-arrival-" + suffix,
                dict(booking=upgrade_booking["booking"], modified=upgrade_booking["modified"],
                     allocation=upgrade_allocation, room=upgrade["standard"],
                     guest=new_guest["guest"], timing_acceptance=upgrade_timing["acceptance"]))
            upgrade_move = dict(stay=upgrade_stay["stay"],
                modified=str(frappe.db.get_value("HS Stay", upgrade_stay["stay"], "modified")),
                room=upgrade["suite"], folio=upgrade_stay["folio"],
                reason="Cambio a una categoría superior")
            upgrade_price = api.preview(second_prop.name, upgrade_move, "change_room")
            assert Decimal(upgrade_price["difference"]) == Decimal("50.00")
            api.execute(second_prop.name, "change_room", "upgrade-move-" + suffix,
                {**upgrade_move, "acceptance": upgrade_price["acceptance"]})
            assert frappe.db.exists("HS Charge", {"stay": upgrade_stay["stay"],
                "description": "Cambio de habitación y tarifa", "item": lodging_product,
                "amount": 50})
            downgrade_move = dict(stay=upgrade_stay["stay"],
                modified=str(frappe.db.get_value("HS Stay", upgrade_stay["stay"], "modified")),
                room=upgrade["downgrade"], folio=upgrade_stay["folio"],
                reason="Regreso a categoría estándar")
            downgrade_price = api.preview(second_prop.name, downgrade_move, "change_room")
            assert Decimal(downgrade_price["difference"]) == Decimal("-50.00")
            api.execute(second_prop.name, "change_room", "downgrade-move-" + suffix,
                {**downgrade_move, "acceptance": downgrade_price["acceptance"]})
            assert frappe.db.exists("HS Charge", {"stay": upgrade_stay["stay"],
                "description": "Cambio de habitación y tarifa", "item": lodging_product,
                "amount": -50})
            assert Decimal(str(frappe.db.get_value("HS Stay", upgrade_stay["stay"],
                "amount"))) == Decimal("100.00")
        finally:
            frappe.db.rollback(save_point="pms_room_upgrade")
        assert any(row["name"] == reception_stay["stay"] for row in
                   api.pms_reception_snapshot(second_prop.name)["stays"])
        local_bank = api.execute(second_prop.name, "pms_account", "local-bank-" + suffix,
            dict(account_code="1030" + suffix, account_name="Banco local",
                 root_type="Asset", account_type="Bank", account_currency="NIO",
                 is_bank=1))["account"]
        local_method = api.execute(second_prop.name, "pms_payment_method",
            "local-method-" + suffix, dict(label="Banco local", account=local_bank))["method"]
        departure_detail = api.pms_departure_detail(second_prop.name, reception_stay["stay"])
        assert departure_detail["folios"][0]["balance"]["pending"] == "100.00"
        room_stay = api.room_snapshot(second_prop.name, fixture["move_room"])["current"]
        assert (room_stay["name"] == reception_stay["stay"] and
                room_stay["account_balances"] == [{"currency": "NIO", "outstanding": 100.0}])
        assert any(row["name"] == reception_stay["stay"] for row in
                   api.pms_departure_snapshot(second_prop.name)["stays"])
        try:
            api.execute(second_prop.name, "check_out", "departure-pending-" + suffix,
                dict(stay=reception_stay["stay"], modified=departure_detail["modified"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida omitió cargos PMS sin contabilizar")
        def schedule_reception_charge(locked):
            source = frappe.get_doc("HS Charge", frappe.db.get_value("HS Charge",
                {"folio": reception_stay["folio"]}, "name"))
            source.status = "Scheduled"
            source.service_date = locked.business_date
            source.period_key = "SMOKE-NIGHT-" + suffix
            source.save()
            return source.name
        scheduled_charge = command(second_prop.name, "finance", "schedule-reception-" + suffix,
            {"operation": "smoke_schedule_reception"}, schedule_reception_charge)
        scheduled_balance = api.pms_departure_detail(second_prop.name, reception_stay["stay"])[
            "folios"][0]["balance"]
        assert scheduled_balance["pending"] == "0.00"
        assert scheduled_balance["scheduled"] == "100.00"
        reception_bill_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=reception_stay["folio"], receivable_account=ar))
        assert reception_bill_quote["total"] == "100.00"
        reception_bill = api.execute(second_prop.name, "pms_bill_folio",
            "reception-bill-" + suffix,
            dict(folio=reception_stay["folio"], receivable_account=ar,
                 acceptance=reception_bill_quote["acceptance"]))
        assert reception_bill["total"] == "100.00"
        assert frappe.db.get_value("HS Charge", scheduled_charge, "status") == "Posted"
        try:
            api.execute(second_prop.name, "check_out", "departure-unpaid-" + suffix,
                dict(stay=reception_stay["stay"], modified=departure_detail["modified"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida omitió el saldo PMS por cobrar")
        reception_guarantee = api.execute(second_prop.name, "pms_cash_movement",
            "reception-guarantee-" + suffix,
            dict(kind="Guarantee", amount="5", method=local_method,
                 counter_account=deposit, party=new_guest["party"],
                 folio=reception_stay["folio"], reference="REC-GUAR-" + suffix,
                 reason="Garantía de salida"))
        assert api.pms_departure_detail(second_prop.name, reception_stay["stay"])[
            "guarantees"][0]["available"] == "5.00"
        api.execute(second_prop.name, "pms_cash_movement", "reception-pay-" + suffix,
            dict(kind="Payment", amount="100", method=local_method,
                 receivable=reception_bill["receivables"][0]["receivable"],
                 reference="REC-PAY-" + suffix, reason="Liquidación del folio"))
        assert api.pms_departure_detail(second_prop.name, reception_stay["stay"])[
            "folios"][0]["balance"]["outstanding"] == "0.00"
        try:
            api.execute(second_prop.name, "check_out", "departure-guarantee-" + suffix,
                dict(stay=reception_stay["stay"], modified=departure_detail["modified"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida omitió la garantía PMS sin resolver")
        api.execute(second_prop.name, "pms_refund", "reception-guarantee-refund-" + suffix,
            dict(source_payment=reception_guarantee["payment"], amount="5",
                 reference="REC-GUAR-REF-" + suffix, reason="Devolución de garantía"))
        assert not api.pms_departure_detail(second_prop.name, reception_stay["stay"])["guarantees"]
        departure_data = dict(stay=reception_stay["stay"], modified=departure_detail["modified"])
        checked_out = api.execute(second_prop.name, "check_out",
            "departure-complete-" + suffix, departure_data)
        assert api.execute(second_prop.name, "check_out",
            "departure-complete-" + suffix, departure_data) == checked_out
        assert frappe.db.get_value("HS Stay", reception_stay["stay"], "status") == "Checked Out"
        assert (api.stay_page(second_prop.name, "history",
                    reception_stay["stay"])["rows"][0]["status"] == "Checked Out" and
                api.stay_overview(second_prop.name,
                    reception_stay["stay"])["status"] == "Checked Out")
        assert frappe.db.get_value("HS Folio", reception_stay["folio"], "status") == "Closed"
        assert frappe.db.get_value("HS Booking", reception_booking["booking"], "status") == "Completed"
        assert frappe.db.get_value("HS Room", fixture["reception_room"], "cleaning_status") == "Dirty"
        assert frappe.db.get_value("HS Cleaning Task", checked_out["cleaning_task"], "room") == fixture["move_room"]
        assert not frappe.db.exists("HS Allocation", {"stay": reception_stay["stay"], "status": "Active"})
        group_start = (now_local(second_prop) + timedelta(days=30)).replace(
            hour=15, minute=0, second=0, microsecond=0, tzinfo=None)
        group_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            starts_at=group_start.isoformat(timespec="minutes"),
            ends_at=(group_start + timedelta(days=1)).isoformat(timespec="minutes"),
            mode="Hotel", rooms=[
                dict(category=fixture["category"], room=fixture["arrival_room"], people=1),
                dict(category=fixture["category"], room=fixture["reception_room"], people=2)])
        group_quote = api.preview(second_prop.name, group_data, "reserve")
        assert len(group_quote["lines"]) == 2 and group_quote["amount"] == "200.00"
        group_booking = api.execute(second_prop.name, "reserve", "group-booking-" + suffix,
            {**group_data, "acceptance": group_quote["acceptance"]})
        group_allocations = [row for row in api.pms_reception_snapshot(second_prop.name)["allocations"]
                             if row["booking"] == group_booking["booking"]]
        assert {row["room"] for row in group_allocations} == {
            fixture["arrival_room"], fixture["reception_room"]}
        group_snapshot = api.pms_reception_snapshot(second_prop.name)
        assert len([row for row in group_snapshot["booking_lines"]
                    if row["parent"] == group_booking["booking"]]) == 2
        assert next(row for row in group_snapshot["bookings"]
                    if row["name"] == group_booking["booking"])["modifiable"]
        changed_group = dict(booking=group_booking["booking"],
            modified=group_booking["modified"],
            ends_at=(group_start + timedelta(days=2)).isoformat(timespec="minutes"),
            reason="El grupo solicitó una noche adicional")
        changed_quote = api.preview(second_prop.name, changed_group, "modify_reservation")
        assert Decimal(changed_quote["amount"]) == Decimal("400.00")
        modified_group = api.execute(second_prop.name, "modify_reservation",
            "modify-group-" + suffix,
            {**changed_group, "acceptance": changed_quote["acceptance"]})
        assert api.execute(second_prop.name, "modify_reservation", "modify-group-" + suffix,
            {**changed_group, "acceptance": changed_quote["acceptance"]}) == modified_group
        assert Decimal(str(frappe.db.get_value("HS Booking", group_booking["booking"],
            "amount"))) == Decimal("400.00")
        assert frappe.db.count("HS Allocation", {"booking": group_booking["booking"],
            "kind": "Reservation", "status": "Active"}) == 2
        try:
            api.preview(second_prop.name,
                {**group_data, "rooms": [group_data["rooms"][0]] * 2}, "reserve")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Una reserva grupal asignó dos líneas a la misma habitación")
        api.execute(second_prop.name, "booking_status", "group-cancel-" + suffix,
            dict(booking=group_booking["booking"], modified=modified_group["modified"],
                 status="Cancelled", reason="Terminó la prueba de reserva grupal"))
        start = (now_local(second_prop) - timedelta(minutes=1)).replace(microsecond=0)
        reservation = dict(starts_at=str(start), ends_at=str(start + timedelta(days=1)),
            guest=fixture["guest"], customer=customer,
            rooms=[dict(category=fixture["category"], room=fixture["arrival_room"], people=1)])
        reservation["acceptance"] = api.preview(second_prop.name, reservation)["acceptance"]
        reserved = api.execute(second_prop.name, "reserve", "booking-" + suffix, reservation)
        assert not frappe.db.exists("HS Folio", {"property": second_prop.name,
                                                 "booking": reserved["booking"]})
        booking_guarantee = api.execute(second_prop.name, "pms_cash_movement",
            "booking-guarantee-" + suffix,
            dict(kind="Guarantee", amount="1", method=bank_method,
                 counter_account=deposit, party=customer, booking=reserved["booking"],
                 reference="BOOK-GUAR-" + suffix, reason="Garantía antes del ingreso"))
        assert frappe.db.get_value("HS Payment", booking_guarantee["payment"], "folio") is None
        assert any(row["name"] == reserved["booking"]
                   for row in api.pms_cash_snapshot(second_prop.name)["bookings"])
        timing_quote = api.preview(second_prop.name,
            dict(booking=reserved["booking"]), action="check_in")
        arrived = api.execute(second_prop.name, "check_in", "arrival-" + suffix,
            dict(booking=reserved["booking"], modified=reserved["modified"],
                 guest=fixture["guest"], timing_acceptance=timing_quote["acceptance"]))
        assert frappe.db.get_value("HS Folio", arrived["folio"], "booking") == reserved["booking"]
        stay_charge = frappe.db.get_value("HS Charge", {"folio": arrived["folio"]},
                                         ["name", "item", "status"], as_dict=True)
        assert stay_charge.item == lodging_product and stay_charge.status == "Pending"
        arrival_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=arrived["folio"], receivable_account=ar))
        assert arrival_quote["total"] == "100.00"
        arrival_bill = api.execute(second_prop.name, "pms_bill_folio", "arrival-bill-" + suffix,
            dict(folio=arrived["folio"], receivable_account=ar,
                 acceptance=arrival_quote["acceptance"]))
        assert arrival_bill["total"] == "100.00"
        assert folio_balance(arrived["folio"])["outstanding"] == "100.00"
        arrival_options = api.pms_deposits_page(second_prop.name,
            arrival_bill["receivables"][0]["receivable"], kind="Guarantee")
        assert (booking_guarantee["payment"] in {
                    row["name"] for row in arrival_options["rows"]} and
                guarantee["payment"] not in {
                    row["name"] for row in arrival_options["rows"]})
        try:
            api.execute(second_prop.name, "pms_apply_guarantee", "wrong-guarantee-folio-" + suffix,
                dict(receivable=arrival_bill["receivables"][0]["receivable"],
                     guarantee=guarantee["payment"], amount="1", reason="Folio ajeno"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aplicó una garantía a otro folio")
        final_guarantee_refund = dict(source_payment=guarantee["payment"], amount="0.59",
            reference="GUAR-FINAL-" + suffix, reason="Saldo final de garantía")
        final_quote = api.pms_refund_preview(second_prop.name, final_guarantee_refund)
        assert final_quote["base_amount"] == "21.50" and final_quote["remaining_base"] == "0.00", final_quote
        api.execute(second_prop.name, "pms_refund", "final-guarantee-refund-" + suffix,
            final_guarantee_refund)
        assert deposit_available(second_prop, guarantee["payment"], "Guarantee") == Decimal(0)
        assert Decimal(standalone_accounting.balance(second_prop, deposit)) == (
            liability_before - Decimal(booking_guarantee["base_amount"]))
        assert all(row["name"] != guarantee["payment"]
                   for row in api.pms_cash_snapshot(second_prop.name)["refundable"])
        api.execute(second_prop.name, "pms_cash_movement", "arrival-pay-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=arrival_bill["receivables"][0]["receivable"],
                 reference="ARRIVAL-PAY-" + suffix, reason="Cobro parcial de alojamiento"))
        assert folio_balance(arrived["folio"])["outstanding"] == "63.50"
        try:
            api.execute(second_prop.name, "pms_apply_guarantee", "wrong-booking-guarantee-" + suffix,
                dict(receivable=rebilled["receivables"][0]["receivable"],
                     guarantee=booking_guarantee["payment"], amount="1", reason="Otra reserva"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aplicó una garantía de reserva a otro folio")
        booked_application = api.execute(second_prop.name, "pms_apply_guarantee",
            "booking-guarantee-apply-" + suffix,
            dict(receivable=arrival_bill["receivables"][0]["receivable"],
                 guarantee=booking_guarantee["payment"], amount="20",
                 reason="Aplicar garantía de reserva tras ingreso"))
        assert booked_application["outstanding"] == "43.50"
        assert booked_application["guarantee_available"] == "16.50"
        assert folio_balance(arrived["folio"])["outstanding"] == "43.50"
        booked_refund_quote = api.pms_refund_preview(second_prop.name,
            dict(source_payment=booking_guarantee["payment"], amount="0.45",
                 reference="BOOK-GUAR-REF-" + suffix, reason="Devolver resto de garantía"))
        assert booked_refund_quote["base_amount"] == "16.50"
        api.execute(second_prop.name, "pms_refund", "booking-guarantee-refund-" + suffix,
            dict(source_payment=booking_guarantee["payment"], amount="0.45",
                 reference="BOOK-GUAR-REF-" + suffix, reason="Devolver resto de garantía"))
        assert deposit_available(second_prop, booking_guarantee["payment"], "Guarantee") == Decimal(0)
        assert Decimal(standalone_accounting.balance(second_prop, deposit)) == liability_before
        credit_before = api.pms_credit_status(second_prop.name, customer)
        assert credit_before["status"] == "Not Authorized"
        departure_modified = str(frappe.db.get_value("HS Stay", arrived["stay"], "modified"))
        credit_checkout = dict(stay=arrived["stay"], modified=departure_modified,
            credit_reason="Salida corporativa a crédito autorizada")
        try:
            api.execute(second_prop.name, "check_out", "credit-disabled-" + suffix,
                credit_checkout)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida concedió crédito PMS sin política ni autorización")
        policy_data = dict(allow_credit=1,
            modified=str(frappe.db.get_value("HS Property", second_prop.name, "modified")),
            reason="Habilitar crédito corporativo controlado")
        policy = api.execute(second_prop.name, "pms_credit_policy", "credit-policy-" + suffix,
            policy_data)
        assert api.execute(second_prop.name, "pms_credit_policy", "credit-policy-" + suffix,
            policy_data) == policy
        terms_data = dict(party=customer,
            modified=str(frappe.db.get_value("HS Party", customer, "modified")),
            credit_authorized=1, credit_limit="1.00", credit_days=30,
            credit_valid_until=None, reason="Límite de ensayo para crédito corporativo")
        terms = api.execute(second_prop.name, "pms_credit_terms", "credit-terms-" + suffix,
            terms_data)
        assert api.execute(second_prop.name, "pms_credit_terms", "credit-terms-" + suffix,
            terms_data) == terms
        try:
            api.execute(second_prop.name, "pms_credit_terms", "credit-stale-" + suffix,
                terms_data)
        except frappe.TimestampMismatchError:
            pass
        else:
            raise AssertionError("Se aceptaron condiciones de crédito obsoletas")
        def unauthorized_credit_change(locked):
            party_doc = frappe.get_doc("HS Party", customer)
            party_doc.credit_limit = "999999.00"
            party_doc.save()
        try:
            command(second_prop.name, "approve", "credit-direct-" + suffix,
                {"operation": "smoke_direct_credit_change"}, unauthorized_credit_change)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Se modificó el límite PMS fuera de la autorización")
        assert Decimal(str(frappe.db.get_value("HS Party", customer, "credit_limit"))) == 1
        try:
            api.pms_credit_status(prop.name, customer)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Se consultó el crédito PMS desde otro establecimiento")
        credit_status = api.pms_credit_status(second_prop.name, customer)
        assert credit_status["status"] in ("Overdue", "Over Limit"), credit_status
        if credit_status["status"] == "Overdue":
            assert Decimal(credit_status["overdue"]) > 0
        assert any(row["party"] == customer for row in
                   api.pms_credit_overview(second_prop.name)["rows"])
        assert api.pms_departure_detail(second_prop.name, arrived["stay"])[
            "folios"][0]["credit"]["status"] == credit_status["status"]
        fresh_terms = dict(party=new_guest["party"],
            modified=str(frappe.db.get_value("HS Party", new_guest["party"], "modified")),
            credit_authorized=1, credit_limit="100.00", credit_days=30,
            credit_valid_until=None, reason="Límite inicial para crédito del huésped")
        from frappe.utils import nowdate
        try:
            api.execute(second_prop.name, "pms_credit_terms", "credit-expired-" + suffix,
                {**fresh_terms, "credit_valid_until": str(frappe.utils.getdate(nowdate()) - timedelta(days=1))})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se autorizó crédito con vigencia vencida")
        api.execute(second_prop.name, "pms_credit_terms", "credit-fresh-terms-" + suffix,
            fresh_terms)
        fresh_due = api.execute(second_prop.name, "pms_receivable", "credit-fresh-due-" + suffix,
            dict(party=new_guest["party"], reference="CREDIT-FRESH-" + suffix,
                 description="Cargo con crédito vigente", amount="10",
                 receivable_account=ar, income_account=income))
        available_status = api.pms_credit_status(second_prop.name, new_guest["party"])
        assert available_status["status"] == "Available" and available_status["available"] == "90.00"
        api.execute(second_prop.name, "pms_credit_terms", "credit-lower-limit-" + suffix,
            {**fresh_terms, "modified": available_status["modified"],
             "credit_limit": "1.00", "reason": "Reducir límite para revisar exceso de exposición"})
        fresh_status = api.pms_credit_status(second_prop.name, new_guest["party"])
        assert fresh_status["status"] == "Over Limit" and fresh_status["overdue"] == "0.00", fresh_status
        future_due = api.execute(second_prop.name, "pms_receivable", "credit-due-" + suffix,
            dict(party=customer, reference="CREDIT-DUE-" + suffix,
                 description="Cargo con plazo PMS", amount="10",
                 receivable_account=ar, income_account=income))
        from frappe.utils import getdate
        assert getdate(frappe.db.get_value("HS PMS Receivable", future_due["receivable"],
            "due_date")) == getdate(second_prop.business_date) + timedelta(days=30)
        try:
            api.execute(second_prop.name, "check_out", "credit-overlimit-" + suffix,
                credit_checkout)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida excedió el límite sin excepción aprobada")
        credit_checkout["credit_override_reason"] = "Excepción gerencial por importe pendiente"
        credit_departure = api.execute(second_prop.name, "check_out", "credit-exception-" + suffix,
            credit_checkout)
        assert api.execute(second_prop.name, "check_out", "credit-exception-" + suffix,
            credit_checkout) == credit_departure
        assert frappe.db.get_value("HS Folio", arrived["folio"], "status") == "Closed"
        assert folio_balance(arrived["folio"])["outstanding"] == "43.50"
        assert frappe.db.get_value("HS Stay", arrived["stay"], "status") == "Checked Out"
        refund_data = dict(source_payment=cash_receipt["payment"], amount="2", shift=shift,
            reference="CASH-REF-" + suffix, reason="Devolución parcial de cobro")
        preview = api.pms_refund_preview(second_prop.name, refund_data)
        assert preview["debit"] == ar and preview["credit"] == usd_cash
        refunded = api.execute(second_prop.name, "pms_refund", "refund-cash-" + suffix,
            {**refund_data, "expected_base_amount": preview["base_amount"],
             "expected_debit": preview["debit"], "expected_credit": preview["credit"]})
        assert refunded["base_amount"] == "73.00" and refunded["allocation"]
        assert api.execute(second_prop.name, "pms_refund", "refund-cash-" + suffix,
            {**refund_data, "expected_base_amount": preview["base_amount"],
             "expected_debit": preview["debit"], "expected_credit": preview["credit"]}) == refunded
        from hospitality_suite.standalone_receivables import outstanding, advance_available, credited as pms_credited
        assert outstanding(second_prop, receivable) == Decimal("754.00")
        unapplied = api.execute(second_prop.name, "pms_unapply_advance", "unapply-" + suffix,
            dict(allocation=applied["allocation"], amount="50", reason="Corrección de aplicación"))
        assert unapplied["outstanding"] == "804.00" and unapplied["advance_available"] == "132.50"
        advanced_refund = api.execute(second_prop.name, "pms_refund", "refund-advance-" + suffix,
            dict(source_payment=receipt["payment"], amount="1", shift=shift,
                 reference="ADV-REF-" + suffix, reason="Devolución parcial de anticipo"))
        assert advanced_refund["base_amount"] == "36.50"
        assert advance_available(second_prop, receipt["payment"]) == Decimal("96.00")
        try:
            api.execute(second_prop.name, "pms_refund", "refund-over-" + suffix,
                dict(source_payment=receipt["payment"], amount="3", shift=shift,
                     reference="ADV-OVER-" + suffix, reason="Saldo insuficiente"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se devolvió un anticipo ya aplicado")
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["USD"] == "15.00"
        assert standalone_accounting.account_currency_balance(second_prop, usd_cash)["balance"] == "15.00"
        assert any(row["name"] == refunded["payment"] and row["source_payment"] == cash_receipt["payment"]
                   for row in api.pms_cash_snapshot(second_prop.name)["movements"])
        assert any(row["name"] == applied["allocation"] and row["remaining"] == "50.00"
                   for row in api.pms_receivables(second_prop.name)["applied_advances"])
        returned_charge = api.execute(second_prop.name, "pms_receivable", "returned-charge-" + suffix,
            dict(party=customer, reference="RETURNED-" + suffix,
                 description="Cargo cobrado y devuelto", amount="36.50",
                 receivable_account=ar, income_account=income))
        returned_payment = api.execute(second_prop.name, "pms_cash_movement", "returned-pay-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=returned_charge["receivable"], reference="RETURNED-PAY-" + suffix,
                 reason="Cobro a devolver"))
        api.execute(second_prop.name, "pms_refund", "returned-refund-" + suffix,
            dict(source_payment=returned_payment["payment"], amount="1",
                 reference="RETURNED-REF-" + suffix, reason="Pago devuelto íntegramente"))
        assert outstanding(second_prop, returned_charge["receivable"]) == Decimal("36.50")
        cancelled_return = api.execute(second_prop.name, "pms_cancel_receivable",
            "returned-cancel-" + suffix,
            dict(receivable=returned_charge["receivable"], reason="Cargo anulado tras devolución"))
        assert cancelled_return["status"] == "Cancelled"
        assert not org.tax_id and not second_prop.tax_policy_confirmed
        tax_account = api.execute(second_prop.name, "pms_account", "tax-account-" + suffix,
            dict(account_code="2100" + suffix, account_name="Impuesto por pagar",
                 root_type="Liability", account_type="Current Liability"))["account"]
        profile = api.execute(second_prop.name, "pms_tax_profile", "tax-profile-" + suffix,
            dict(label="Gravado de prueba", treatment="Taxable", rate="15",
                 included_in_price=0, liability_account=tax_account))["profile"]
        assert_manual_control_rejected(tax_account, "TAX")
        existing_product = frappe.get_doc("HS Product", lodging_product)
        api.save_setup(second_prop.name, "product",
            {"name": lodging_product, "tax_profile": profile}, "product-tax-" + suffix,
            expected_modified=str(existing_product.modified))
        assert frappe.db.get_value("HS Product", lodging_product, "tax_profile") == profile
        assert Decimal(str(frappe.db.get_value("HS PMS Receivable",
            rebilled["receivables"][0]["receivable"], "tax_amount"))) == 0
        portfolio_before = api.portfolio_snapshot()
        taxable = api.execute(second_prop.name, "pms_receivable", "taxable-" + suffix,
            dict(party=customer, reference="TAXABLE-" + suffix,
                 description="Servicio gravado de prueba", amount="100",
                 receivable_account=ar, income_account=income, tax_profile=profile))
        assert taxable["amount"] == "115.00" and taxable["tax_amount"] == "15.00"
        assert standalone_accounting.balance(second_prop, tax_account) == "-15.00"
        portfolio_after = api.portfolio_snapshot()
        before_hotel = next(row for row in portfolio_before["properties"]
            if row["property"] == second_prop.name)
        after_hotel = next(row for row in portfolio_after["properties"]
            if row["property"] == second_prop.name)
        assert (Decimal(after_hotel["amounts"]["NIO"]["receivable"]) -
                Decimal(before_hotel["amounts"]["NIO"]["receivable"])) == Decimal("115.00")
        assert (Decimal(portfolio_after["totals"]["NIO"]["receivable"]) -
                Decimal(portfolio_before["totals"]["NIO"]["receivable"])) == Decimal("115.00")
        invoice_series = api.execute(second_prop.name, "pms_fiscal_series", "invoice-series-" + suffix,
            dict(series_code="F" + suffix + "-", document_type="Invoice",
                 start_number=1, end_number=5, padding=4))["series"]
        credit_series = api.execute(second_prop.name, "pms_fiscal_series", "credit-series-" + suffix,
            dict(series_code="NC" + suffix + "-", document_type="Credit Note",
                 start_number=1, end_number=5, padding=4))["series"]
        assert not org.tax_id
        assert not frappe.db.get_value("HS PMS Fiscal Series", invoice_series,
                                       "authorization_reference")
        assert not frappe.db.get_value("HS PMS Fiscal Series", credit_series,
                                       "authorization_reference")
        penalty_tax_account = api.execute(second_prop.name, "pms_account",
            "penalty-tax-account-" + suffix,
            dict(account_code="2110" + suffix, account_name="Impuesto de penalización",
                 root_type="Liability", account_type="Current Liability"))["account"]
        penalty_profile = api.execute(second_prop.name, "pms_tax_profile",
            "penalty-tax-profile-" + suffix,
            dict(label="Penalización gravada", treatment="Taxable", rate="15",
                 included_in_price=0, liability_account=penalty_tax_account))["profile"]
        penalty_product = api.save_setup(second_prop.name, "product",
            dict(product_code="PEN" + suffix, product_name="Penalización de reserva",
                 product_type="Service", income_account=income, tax_profile=penalty_profile,
                 sales_rate="1", active=1), "penalty-product-" + suffix)["name"]
        second_prop.reload()
        api.save_setup(second_prop.name, "property",
            dict(penalty_item=penalty_product, receivable_account=ar,
                 cancellation_fee_mode="Fixed", cancellation_fee_value="100",
                 no_show_fee_mode="Percent", no_show_fee_value="10"),
            "penalty-policy-" + suffix, expected_modified=str(second_prop.modified))
        second_prop.reload()
        assert api.pms_booking_fee_settings(second_prop.name)["penalty_item"] == penalty_product
        penalty_start = (now_local(second_prop) + timedelta(days=45)).replace(
            hour=15, minute=0, second=0, microsecond=0, tzinfo=None)
        penalty_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            starts_at=penalty_start.isoformat(timespec="minutes"),
            ends_at=(penalty_start + timedelta(days=1)).isoformat(timespec="minutes"),
            mode="Hotel", rooms=[dict(category=fixture["category"], people=1)])
        penalty_quote = api.preview(second_prop.name, penalty_data, "reserve")
        penalty_booking = api.execute(second_prop.name, "reserve", "penalty-booking-" + suffix,
            {**penalty_data, "acceptance": penalty_quote["acceptance"]})
        penalty_request = dict(booking=penalty_booking["booking"],
            modified=penalty_booking["modified"], status="Cancelled",
            reason="Cancelación con cargo de prueba")
        fee_quote = api.preview(second_prop.name, penalty_request, "booking_status")
        assert fee_quote["amount"] == "100.00" and fee_quote["tax_amount"] == "15.00"
        assert fee_quote["total_amount"] == "115.00"
        try:
            api.execute(second_prop.name, "booking_status", "penalty-unaccepted-" + suffix,
                penalty_request)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló sin aceptar la penalización")
        assert frappe.db.get_value("HS Booking", penalty_booking["booking"], "status") == "Confirmed"
        penalized = api.execute(second_prop.name, "booking_status", "penalty-cancel-" + suffix,
            {**penalty_request, "fee_acceptance": fee_quote["acceptance"]})
        assert api.execute(second_prop.name, "booking_status", "penalty-cancel-" + suffix,
            {**penalty_request, "fee_acceptance": fee_quote["acceptance"]}) == penalized
        penalty_receivable = penalized["fee_receivable"]
        assert penalty_receivable and frappe.db.get_value("HS PMS Receivable",
            penalty_receivable, "booking") == penalty_booking["booking"]
        assert Decimal(str(frappe.db.get_value("HS PMS Receivable",
            penalty_receivable, "amount"))) == Decimal("115.00")
        assert standalone_accounting.balance(second_prop, penalty_tax_account) == "-15.00"
        assert any(row["booking"] == penalty_booking["booking"] and
                   row["name"] == penalty_receivable for row in
                   api.pms_receivables(second_prop.name)["receivables"])
        penalty_invoice_data = dict(series=invoice_series, receivables=[penalty_receivable])
        penalty_fiscal_quote = api.pms_invoice_quote(second_prop.name, penalty_invoice_data)
        penalty_fiscal = api.execute(second_prop.name, "pms_issue_invoice",
            "penalty-invoice-" + suffix,
            {**penalty_invoice_data, "acceptance": penalty_fiscal_quote["acceptance"]})
        assert penalty_fiscal["total_amount"] == "115.00"
        assert penalty_fiscal["document_number"] in frappe.get_print(
            "HS PMS Fiscal Document", penalty_fiscal["document"],
            print_format="HS Documento fiscal PMS")
        pending_fiscal = api.pms_fiscal_candidates(
            second_prop.name, "ready", taxable["receivable"], page_length=1)
        assert (len(pending_fiscal["rows"]) == 1 and
                pending_fiscal["rows"][0]["name"] == taxable["receivable"] and
                pending_fiscal["rows"][0]["party_name"])
        assert any(row["name"] == taxable["receivable"] for row in
                   api.pms_fiscal_candidates(second_prop.name, "ready",
                       pending_fiscal["rows"][0]["party_name"],
                       page_length=50)["rows"])
        invoice_data = dict(series=invoice_series, receivables=[taxable["receivable"]])
        fiscal_quote = api.pms_invoice_quote(second_prop.name, invoice_data)
        assert fiscal_quote["total_amount"] == "115.00" and fiscal_quote["tax_amount"] == "15.00"
        fiscal = api.execute(second_prop.name, "pms_issue_invoice", "fiscal-" + suffix,
            {**invoice_data, "acceptance": fiscal_quote["acceptance"]})
        assert fiscal["document_number"] == "F" + suffix + "-0002"
        assert not api.pms_fiscal_candidates(
            second_prop.name, "ready", taxable["receivable"],
            page_length=1)["rows"]
        original_fiscal = api.pms_fiscal_candidates(
            second_prop.name, "invoices", fiscal["document_number"],
            page_length=1)
        assert (len(original_fiscal["rows"]) == 1 and
                original_fiscal["rows"][0]["name"] == fiscal["document"] and
                original_fiscal["rows"][0]["buyer_name"])
        invoice_page_one = api.pms_fiscal_candidates(
            second_prop.name, "invoices", page_length=1)
        invoice_page_two = api.pms_fiscal_candidates(
            second_prop.name, "invoices", offset=1, page_length=1)
        assert (invoice_page_one["has_more"] and
                invoice_page_one["rows"][0]["name"] !=
                invoice_page_two["rows"][0]["name"])
        assert not api.pms_fiscal_candidates(
            prop.name, "invoices", fiscal["document_number"],
            page_length=1)["rows"]
        printed = frappe.get_print("HS PMS Fiscal Document", fiscal["document"],
            print_format="HS Documento fiscal PMS")
        assert fiscal["document_number"] in printed and "115.00" in printed
        assert " · RUC" not in printed and "<th>Referencia</th>" not in printed
        archived = api.pms_fiscal_archive(second_prop.name, 0, 1,
                                           fiscal["document_number"])
        assert archived["total"] == 1 and archived["documents"][0]["name"] == fiscal["document"]
        assert not api.pms_fiscal_archive(prop.name, 0, 1,
                                          fiscal["document_number"])["documents"]
        assert api.execute(second_prop.name, "pms_issue_invoice", "fiscal-" + suffix,
            {**invoice_data, "acceptance": fiscal_quote["acceptance"]}) == fiscal
        try:
            api.execute(second_prop.name, "pms_issue_invoice", "fiscal-duplicate-" + suffix,
                {**invoice_data, "acceptance": fiscal_quote["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se duplicó la factura del mismo cargo")
        try:
            api.execute(second_prop.name, "pms_cancel_receivable", "cancel-taxable-" + suffix,
                dict(receivable=taxable["receivable"], reason="Requiere nota de crédito"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló una cuenta con factura numerada")
        credit_data = dict(invoice=fiscal["document"], series=credit_series)
        tax_payment = api.execute(second_prop.name, "pms_cash_movement", "tax-payment-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=taxable["receivable"], reference="TAX-PAY-" + suffix,
                 reason="Cobro parcial de factura"))
        try:
            api.pms_credit_quote(second_prop.name, credit_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se acreditó una factura con cobro vigente")
        api.execute(second_prop.name, "pms_refund", "tax-refund-" + suffix,
            dict(source_payment=tax_payment["payment"], amount="1",
                 reference="TAX-REF-" + suffix, reason="Devolución antes de acreditar"))
        credit_quote = api.pms_credit_quote(second_prop.name, credit_data)
        credited = api.execute(second_prop.name, "pms_issue_credit_note", "credit-" + suffix,
            {**credit_data, "acceptance": credit_quote["acceptance"],
             "reason": "Anulación íntegra de prueba"})
        assert credited["source_invoice"] == fiscal["document"]
        printed_credit = frappe.get_print("HS PMS Fiscal Document", credited["document"],
            print_format="HS Documento fiscal PMS")
        assert credited["document_number"] in printed_credit and "NOTA DE CRÉDITO" in printed_credit
        assert " · RUC" not in printed_credit and "<th>Referencia</th>" not in printed_credit
        assert standalone_accounting.balance(second_prop, tax_account) == "0.00"
        assert frappe.db.get_value("HS PMS Receivable", taxable["receivable"], "status") == "Posted"
        assert outstanding(second_prop, taxable["receivable"]) == 0
        assert pms_credited(second_prop, taxable["receivable"]) == Decimal("115.00")
        try:
            api.execute(second_prop.name, "pms_reverse_journal", "reverse-fiscal-" + suffix,
                dict(journal=credited["journal"], reason="No revertir la nota fuera de su flujo"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revirtió el asiento de una nota fiscal vigente")
        assert len(api.pms_fiscal_snapshot(second_prop.name)["documents"]) == 3
        first_page = api.pms_fiscal_archive(second_prop.name, 0, 1)
        next_page = api.pms_fiscal_archive(second_prop.name, 1, 1)
        assert (first_page["total"] == next_page["total"] == 3 and
                len(first_page["documents"]) == len(next_page["documents"]) == 1 and
                first_page["documents"][0]["name"] != next_page["documents"][0]["name"])
        try:
            api.erp_fiscal_archive(second_prop.name)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El archivo ERPNext se habilitó antes del corte")
        included_profile = api.execute(second_prop.name, "pms_tax_profile", "tax-included-" + suffix,
            dict(label="Impuesto incluido", treatment="Taxable", rate="15",
                 included_in_price=1, liability_account=tax_account))["profile"]
        included_charge = api.execute(second_prop.name, "pms_receivable", "included-" + suffix,
            dict(party=customer, reference="INCLUDED-" + suffix,
                 description="Precio con impuesto incluido", amount="115",
                 receivable_account=ar, income_account=income, tax_profile=included_profile))
        assert included_charge["amount"] == "115.00"
        assert included_charge["net_amount"] == "100.00" and included_charge["tax_amount"] == "15.00"
        second_taxable = api.execute(second_prop.name, "pms_receivable", "second-taxable-" + suffix,
            dict(party=customer, reference="SECOND-TAX-" + suffix,
                 description="Segundo servicio gravado", amount="100",
                 receivable_account=ar, income_account=income, tax_profile=profile))
        second_invoice_data = dict(series=invoice_series,
            receivables=[included_charge["receivable"], second_taxable["receivable"]])
        second_invoice_quote = api.pms_invoice_quote(second_prop.name, second_invoice_data)
        assert second_invoice_quote["total_amount"] == "230.00"
        second_invoice = api.execute(second_prop.name, "pms_issue_invoice",
            "second-invoice-" + suffix,
            {**second_invoice_data, "acceptance": second_invoice_quote["acceptance"]})
        options = api.pms_credit_options(second_prop.name, second_invoice["document"])["lines"]
        assert {row["receivable"] for row in options} == {
            included_charge["receivable"], second_taxable["receivable"]}
        assert all(row["available"] == "115.00" for row in options)
        partial_data = dict(invoice=second_invoice["document"], series=credit_series,
            lines=[dict(receivable=included_charge["receivable"], amount="33.33")])
        partial_quote = api.pms_credit_quote(second_prop.name, partial_data)
        assert partial_quote["net_amount"] == "28.98"
        assert partial_quote["tax_amount"] == "4.35"
        assert partial_quote["total_amount"] == "33.33"
        partial_credit = api.execute(second_prop.name, "pms_issue_credit_note",
            "partial-credit-" + suffix,
            {**partial_data, "acceptance": partial_quote["acceptance"],
             "reason": "Corrección parcial de precio"})
        assert api.execute(second_prop.name, "pms_issue_credit_note",
            "partial-credit-" + suffix,
            {**partial_data, "acceptance": partial_quote["acceptance"],
             "reason": "Corrección parcial de precio"}) == partial_credit
        assert "33.33" in frappe.get_print("HS PMS Fiscal Document", partial_credit["document"],
            print_format="HS Documento fiscal PMS")
        assert outstanding(second_prop, included_charge["receivable"]) == Decimal("81.67")
        assert outstanding(second_prop, second_taxable["receivable"]) == Decimal("115.00")
        assert standalone_accounting.balance(second_prop, tax_account) == "-25.65"
        try:
            api.pms_credit_quote(second_prop.name, dict(invoice=second_invoice["document"],
                series=credit_series,
                lines=[dict(receivable=included_charge["receivable"], amount="82")]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Una segunda nota superó el remanente de la línea")
        paid_second = api.execute(second_prop.name, "pms_cash_movement", "second-tax-paid-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=second_taxable["receivable"], reference="SECOND-PAY-" + suffix,
                 reason="Pago parcial antes de acreditar"))
        remaining_data = dict(invoice=second_invoice["document"], series=credit_series,
            lines=[dict(receivable=included_charge["receivable"], amount="81.67"),
                   dict(receivable=second_taxable["receivable"], amount="115")])
        try:
            api.pms_credit_quote(second_prop.name, remaining_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se acreditó una porción todavía cobrada")
        api.execute(second_prop.name, "pms_refund", "second-tax-refund-" + suffix,
            dict(source_payment=paid_second["payment"], amount="1",
                 reference="SECOND-REF-" + suffix, reason="Devolver antes de acreditar"))
        remaining_quote = api.pms_credit_quote(second_prop.name, remaining_data)
        assert remaining_quote["net_amount"] == "171.02"
        assert remaining_quote["tax_amount"] == "25.65"
        assert remaining_quote["total_amount"] == "196.67"
        remaining_credit = api.execute(second_prop.name, "pms_issue_credit_note",
            "remaining-credit-" + suffix,
            {**remaining_data, "acceptance": remaining_quote["acceptance"],
             "reason": "Corrección del resto de la factura"})
        assert remaining_credit["source_invoice"] == second_invoice["document"]
        assert pms_credited(second_prop, included_charge["receivable"]) == Decimal("115.00")
        assert pms_credited(second_prop, second_taxable["receivable"]) == Decimal("115.00")
        assert outstanding(second_prop, included_charge["receivable"]) == 0
        assert outstanding(second_prop, second_taxable["receivable"]) == 0
        assert standalone_accounting.balance(second_prop, tax_account) == "0.00"
        no_show_start = (now_local(second_prop) - timedelta(minutes=5)).replace(
            second=0, microsecond=0, tzinfo=None)
        no_show_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            starts_at=no_show_start.isoformat(timespec="minutes"),
            ends_at=(no_show_start + timedelta(days=1)).isoformat(timespec="minutes"),
            mode="Hotel", rooms=[dict(category=fixture["category"], people=1)])
        no_show_booking_quote = api.preview(second_prop.name, no_show_data, "reserve")
        no_show_booking = api.execute(second_prop.name, "reserve", "no-show-booking-" + suffix,
            {**no_show_data, "acceptance": no_show_booking_quote["acceptance"]})
        no_show_request = dict(booking=no_show_booking["booking"],
            modified=no_show_booking["modified"], status="No Show",
            reason="Huésped no llegó")
        no_show_fee = api.preview(second_prop.name, no_show_request, "booking_status")
        assert Decimal(no_show_fee["amount"]) == Decimal(no_show_booking_quote["amount"]) / 10
        no_show_result = api.execute(second_prop.name, "booking_status", "no-show-" + suffix,
            {**no_show_request, "fee_acceptance": no_show_fee["acceptance"]})
        assert frappe.db.get_value("HS Booking", no_show_booking["booking"], "status") == "No Show"
        assert frappe.db.get_value("HS PMS Receivable", no_show_result["fee_receivable"],
                                   "booking") == no_show_booking["booking"]
        assert not frappe.db.exists("HS Allocation", {"booking": no_show_booking["booking"],
                                                "status": "Active"})
        pass_profile = api.execute(second_prop.name, "pms_tax_profile",
            "day-pass-profile-" + suffix,
            dict(label="Acceso exento", treatment="Exempt", rate="0",
                 included_in_price=0))["profile"]
        pass_product = api.save_setup(second_prop.name, "product",
            dict(product_code="DAY" + suffix, product_name="Acceso diurno",
                 product_type="Service", income_account=income,
                 tax_profile=pass_profile, sales_rate="40", active=1),
            "day-pass-product-" + suffix)["name"]
        second_prop.reload()
        api.save_setup(second_prop.name, "property",
            dict(day_pass_item=pass_product), "day-pass-binding-" + suffix,
            expected_modified=str(second_prop.modified))
        second_prop.reload()
        pass_start = (now_local(second_prop) + timedelta(days=3)).replace(
            hour=9, minute=0, second=0, microsecond=0, tzinfo=None)
        pass_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            people=2, starts_at=pass_start.isoformat(timespec="minutes"),
            ends_at=pass_start.replace(hour=17).isoformat(timespec="minutes"),
            notes="Acceso sin habitación de prueba")
        try:
            api.preview(second_prop.name, {**pass_data,
                "ends_at": (pass_start + timedelta(days=1)).isoformat(timespec="minutes")},
                "day_pass_no_room")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Day Pass sin habitación atravesó dos días")
        pass_quote = api.preview(second_prop.name, pass_data, "day_pass_no_room")
        assert pass_quote["total_amount"] == "80.00" and pass_quote["tax_amount"] == "0.00"
        try:
            api.execute(second_prop.name, "day_pass_no_room", "day-pass-stale-" + suffix,
                {**pass_data, "acceptance": "obsoleta"})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se emitió Day Pass sin aceptar el importe")
        issued_pass = api.execute(second_prop.name, "day_pass_no_room",
            "day-pass-issue-" + suffix,
            {**pass_data, "acceptance": pass_quote["acceptance"]})
        assert api.execute(second_prop.name, "day_pass_no_room",
            "day-pass-issue-" + suffix,
            {**pass_data, "acceptance": pass_quote["acceptance"]}) == issued_pass
        pass_doc = frappe.get_doc("HS Day Pass", issued_pass["day_pass"])
        assert pass_doc.pms_receivable == issued_pass["receivable"]
        assert not pass_doc.service and not pass_doc.sales_invoice and not pass_doc.payment
        live_pass_blockers = []
        live_passes = pms_cutover._active_day_passes(
            second_prop, live_pass_blockers)
        frozen_pass = next(row for row in live_passes
            if row["name"] == pass_doc.name)
        assert frozen_pass["accepted_sale"]["total_amount"] == "80"
        assert frozen_pass["source_financial"]["receivable"] == issued_pass[
            "receivable"]
        assert frozen_pass["source_financial"]["total_amount"] == "80"
        assert frozen_pass["source_settlements"]["allocated_amount"] == "0"
        assert not any(row["code"].startswith("invalid_active_pms_day_pass")
                       for row in live_pass_blockers)
        assert any(row["name"] == issued_pass["day_pass"] and row["can_cancel"]
                   for row in api.pms_day_pass_snapshot(second_prop.name)["day_passes"])
        try:
            api.execute(second_prop.name, "pms_cancel_receivable",
                "day-pass-direct-cancel-" + suffix,
                dict(receivable=issued_pass["receivable"], reason="Debe cancelar el acceso"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La cancelación directa dejó vigente el acceso")
        cancelled_pass = api.execute(second_prop.name, "pms_day_pass_cancel",
            "day-pass-cancel-" + suffix,
            dict(day_pass=pass_doc.name, modified=str(pass_doc.modified),
                 reason="Se anuló el acceso antes de usarlo"))
        assert cancelled_pass["status"] == "Cancelled"
        assert frappe.db.get_value("HS Day Pass", pass_doc.name, "status") == "Cancelled"
        assert frappe.db.get_value("HS PMS Receivable", issued_pass["receivable"],
                                   "status") == "Cancelled"
        assert not any(row["name"] == pass_doc.name for row in
            pms_cutover._active_day_passes(second_prop, []))
        def add_taxed_folio_product(locked):
            product = insert("HS Product", locked, organization=org.name,
                product_code="TAXROOM" + suffix, product_name="Alojamiento gravado",
                product_type="Service", income_account=income, tax_profile=profile,
                sales_rate="90.00", active=1)
            return product.name
        taxed_product = command(second_prop.name, "setup", "folio-tax-fixture-" + suffix,
            {"operation": "smoke_folio_tax"}, add_taxed_folio_product)
        service_request = dict(stay=fixture["stay"], folio=fixture["folio"],
                               item=taxed_product, quantity="1", included=False)
        service_quote = api.preview(second_prop.name, service_request, "request_service")
        assert (service_quote["net"], service_quote["tax"], service_quote["total"]) == (
            "90.00", "13.50", "103.50")
        try:
            api.execute(second_prop.name, "request_service", "stale-service-quote-" + suffix,
                {**service_request, "quantity": "2", "acceptance": service_quote["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó una cotización de consumo con otra cantidad")
        reviewed_service_request = {**service_request, "acceptance": service_quote["acceptance"]}
        requested = api.execute(second_prop.name, "request_service", "service-request-" + suffix,
                                reviewed_service_request)
        assert api.execute(second_prop.name, "request_service", "service-request-" + suffix,
                           reviewed_service_request) == requested
        assert requested["status"] == "Requested"
        assert any(row["name"] == requested["service"] for row in
                   api.pms_service_snapshot(second_prop.name)["requests"])
        prepared = api.execute(second_prop.name, "update_service", "service-prepare-" + suffix,
            dict(service=requested["service"],
                 modified=str(frappe.db.get_value("HS Service Request", requested["service"], "modified")),
                 status="In Progress"))
        delivered = api.execute(second_prop.name, "update_service", "service-deliver-" + suffix,
            dict(service=requested["service"], modified=prepared["modified"], status="Delivered"))
        assert frappe.db.get_value("HS Charge", delivered["charge"], "status") == "Pending"
        returned = api.execute(second_prop.name, "update_service", "service-return-" + suffix,
            dict(service=requested["service"], modified=delivered["modified"],
                 status="Returned", reason="Servicio no utilizado"))
        assert returned["status"] == "Returned"
        assert frappe.db.get_value("HS Charge", delivered["charge"], "status") == "Reversed"
        def grant_included(locked):
            stay = frappe.get_doc("HS Stay", fixture["stay"], for_update=True)
            stay.service_entitlements = canonical([dict(item=taxed_product, quantity="1")])
            stay.save()
            return stay.name
        command(second_prop.name, "setup", "service-entitlement-" + suffix,
            {"operation": "smoke_service_entitlement"}, grant_included)
        included_data = {**service_request, "included": True}
        included_quote = api.preview(second_prop.name, included_data, "request_service")
        assert (included_quote["amount"], included_quote["tax"], included_quote["total"]) == (
            "0", "0.00", "0.00")
        included_data["acceptance"] = included_quote["acceptance"]
        included_request = api.execute(second_prop.name, "request_service",
            "service-included-" + suffix, included_data)
        try:
            api.execute(second_prop.name, "request_service", "service-overincluded-" + suffix,
                        included_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El servicio incluido superó la asignación de la estancia")
        included_delivered = api.execute(second_prop.name, "update_service",
            "service-included-deliver-" + suffix,
            dict(service=included_request["service"],
                 modified=str(frappe.db.get_value("HS Service Request", included_request["service"], "modified")),
                 status="Delivered"))
        assert not included_delivered["charge"]
        def separate_service_folio(locked):
            return insert("HS Folio", locked, stay=fixture["stay"], customer=customer,
                currency=locked.currency, status="Open", label="Servicios facturados").name
        billed_service_folio = command(second_prop.name, "stay", "service-folio-" + suffix,
            {"operation": "smoke_service_folio"}, separate_service_folio)
        billed_service_data = {**service_request, "folio": billed_service_folio}
        billed_service = api.execute(second_prop.name, "request_service",
            "service-billed-request-" + suffix, billed_service_data)
        billed_delivered = api.execute(second_prop.name, "update_service",
            "service-billed-deliver-" + suffix,
            dict(service=billed_service["service"],
                 modified=str(frappe.db.get_value("HS Service Request", billed_service["service"], "modified")),
                 status="Delivered"))
        billed_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=billed_service_folio, receivable_account=ar))
        billed_service_account = api.execute(second_prop.name, "pms_bill_folio",
            "service-billed-account-" + suffix,
            dict(folio=billed_service_folio, receivable_account=ar,
                 acceptance=billed_quote["acceptance"]))
        billed_receivable = billed_service_account["receivables"][0]["receivable"]
        try:
            api.execute(second_prop.name, "update_service", "service-billed-return-early-" + suffix,
                dict(service=billed_service["service"], modified=billed_delivered["modified"],
                     status="Returned", reason="Se requiere nota de crédito"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se devolvió un servicio contabilizado sin nota de crédito")
        billed_invoice_data = dict(series=invoice_series, receivables=[billed_receivable])
        billed_invoice_quote = api.pms_invoice_quote(second_prop.name, billed_invoice_data)
        billed_invoice = api.execute(second_prop.name, "pms_issue_invoice",
            "service-billed-invoice-" + suffix,
            {**billed_invoice_data, "acceptance": billed_invoice_quote["acceptance"]})
        billed_credit_data = dict(invoice=billed_invoice["document"], series=credit_series)
        billed_credit_quote = api.pms_credit_quote(second_prop.name, billed_credit_data)
        billed_credit = api.execute(second_prop.name, "pms_issue_credit_note",
            "service-billed-credit-" + suffix,
            {**billed_credit_data, "acceptance": billed_credit_quote["acceptance"],
             "reason": "Devolución íntegra del servicio"})
        billed_returned = api.execute(second_prop.name, "update_service",
            "service-billed-return-" + suffix,
            dict(service=billed_service["service"], modified=billed_delivered["modified"],
                 status="Returned", reason="Servicio devuelto al huésped"))
        assert billed_returned["status"] == "Returned"
        assert frappe.db.get_value("HS Service Request", billed_service["service"],
                                   "credit_note") == billed_credit["document"]
        stock_asset = api.execute(second_prop.name, "pms_account", "stock-asset-" + suffix,
            dict(account_code="1150" + suffix, account_name="Inventario huéspedes",
                 root_type="Asset"))["account"]
        stock_warehouse = api.execute(second_prop.name, "pms_warehouse",
            "service-warehouse-" + suffix,
            dict(warehouse_code="GUEST" + suffix, warehouse_name="Huéspedes"))["warehouse"]
        def create_service_stock(locked):
            item = insert("HS Product", locked, organization=org.name,
                product_code="WATER" + suffix, product_name="Agua minibar",
                product_type="Stock", inventory_account=stock_asset,
                expense_account=operating_expense, income_account=income,
                tax_profile=profile, sales_rate="15.00", active=1)
            return dict(warehouse=stock_warehouse, item=item.name)
        stock_service = command(second_prop.name, "setup", "service-stock-master-" + suffix,
            {"operation": "smoke_service_stock_master"}, create_service_stock)
        assert_manual_control_rejected(stock_asset, "STOCK")
        stock_opening_data = dict(product=stock_service["item"],
            warehouse=stock_service["warehouse"], quantity="2", value="20.00",
            equity_account=owner, reference="guest-stock-" + suffix)
        stock_opening = api.execute(second_prop.name, "pms_opening_stock",
            "service-stock-receipt-" + suffix, stock_opening_data)
        assert api.execute(second_prop.name, "pms_opening_stock",
            "service-stock-receipt-" + suffix, stock_opening_data) == stock_opening
        assert any(row["product"] == stock_service["item"] and
                   Decimal(str(row["quantity"])) == 2 for row in
                   api.pms_inventory_snapshot(second_prop.name)["balances"])
        stock_data = {**service_request, "item": stock_service["item"],
                      "warehouse": stock_service["warehouse"]}
        try:
            api.execute(prop.name, "request_service", "wrong-property-service-" + suffix,
                        stock_data)
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Se solicitó inventario de otro establecimiento")
        stock_request = api.execute(second_prop.name, "request_service", "service-stock-" + suffix,
            stock_data)
        cost_before = Decimal(standalone_accounting.balance(second_prop, operating_expense))
        stock_delivery_data = dict(service=stock_request["service"],
            modified=str(frappe.db.get_value("HS Service Request", stock_request["service"], "modified")),
            status="Delivered")
        stock_delivered = api.execute(second_prop.name, "update_service",
            "service-stock-deliver-" + suffix, stock_delivery_data)
        assert api.execute(second_prop.name, "update_service",
            "service-stock-deliver-" + suffix, stock_delivery_data) == stock_delivered
        assert stock_delivered["stock_movement"] and stock_delivered["charge"]
        assert Decimal(standalone_accounting.balance(second_prop, operating_expense)) == cost_before + 10
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            stock_service["warehouse"]) == (Decimal("1"), Decimal("10.00"))
        stock_returned = api.execute(second_prop.name, "update_service",
            "service-stock-return-" + suffix,
            dict(service=stock_request["service"], modified=stock_delivered["modified"],
                 status="Returned", reason="Producto sin consumir"))
        assert stock_returned["return_stock_movement"]
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            stock_service["warehouse"]) == (Decimal("2"), Decimal("20.00"))
        assert Decimal(standalone_accounting.balance(second_prop, operating_expense)) == cost_before
        assert frappe.db.get_value("HS Charge", stock_delivered["charge"], "status") == "Reversed"
        clearing = api.execute(second_prop.name, "pms_account", "stock-clearing-" + suffix,
            dict(account_code="1190" + suffix, account_name="Tránsito de inventario",
                 root_type="Asset", account_type="Temporary"))["account"]
        destination = api.execute(second_prop.name, "pms_warehouse",
            "service-warehouse-destination-" + suffix,
            dict(warehouse_code="BACK" + suffix, warehouse_name="Reserva"))["warehouse"]
        transfer_data = dict(product=stock_service["item"],
            source_warehouse=stock_service["warehouse"], target_warehouse=destination,
            quantity="1", clearing_account=clearing,
            reference="TRANSFER-" + suffix, reason="Reponer almacén de reserva")
        transferred = api.execute(second_prop.name, "pms_transfer_stock",
            "stock-transfer-" + suffix, transfer_data)
        assert api.execute(second_prop.name, "pms_transfer_stock",
            "stock-transfer-" + suffix, transfer_data) == transferred
        assert transferred["value"] == "10.00"
        assert_manual_control_rejected(clearing, "STOCKCLEARING")
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            stock_service["warehouse"]) == (Decimal("1"), Decimal("10.00"))
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            destination) == (Decimal("1"), Decimal("10.00"))
        assert standalone_accounting.balance(second_prop, clearing) == "0.00"
        assert frappe.db.get_value("HS Stock Transfer", transferred["transfer"],
            "target_movement") == transferred["target_movement"]
        try:
            api.execute(second_prop.name, "pms_transfer_stock", "duplicate-transfer-reference-" + suffix,
                transfer_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se duplicó un traslado con otra clave")
        try:
            api.execute(second_prop.name, "pms_transfer_stock", "stock-transfer-too-much-" + suffix,
                {**transfer_data, "quantity": "4", "reference": "TRANSFER-OVER-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El traslado permitió inventario negativo")
        linen_product = api.save_setup(second_prop.name, "product",
            dict(product_code="LINEN" + suffix, product_name="Sábana del hotel",
                 product_type="Stock", inventory_account=stock_asset,
                 expense_account=operating_expense, active=1),
            "linen-product-" + suffix)["name"]
        api.execute(second_prop.name, "pms_opening_stock", "linen-opening-" + suffix,
            dict(product=linen_product, warehouse=stock_service["warehouse"],
                 quantity="3", value="30.00", equity_account=owner,
                 reference="LINEN-OPEN-" + suffix))
        second_prop.reload()
        api.save_setup(second_prop.name, "property",
            dict(pms_linen_operating_warehouse=stock_service["warehouse"],
                 pms_linen_laundry_warehouse=destination,
                 pms_linen_clearing_account=clearing),
            "linen-config-" + suffix, expected_modified=str(second_prop.modified))
        second_prop.reload()
        assert api.pms_linen_setup_options(second_prop.name)["warehouses"]
        assert any(row["name"] == linen_product for row in
                   api.linen_board(second_prop.name)["products"])
        linen_send_data = dict(room=fixture["arrival_room"], item=linen_product,
                               quantity="2", direction="Send")
        linen_sent = api.execute(second_prop.name, "linen", "linen-send-" + suffix,
                                 linen_send_data)
        assert api.execute(second_prop.name, "linen", "linen-send-" + suffix,
                           linen_send_data) == linen_sent
        assert linen_sent["value"] == "20.00"
        assert standalone_inventory.current_balance(second_prop, linen_product,
            stock_service["warehouse"]) == (Decimal("1"), Decimal("10.00"))
        assert standalone_inventory.current_balance(second_prop, linen_product,
            destination) == (Decimal("2"), Decimal("20.00"))
        assert standalone_accounting.balance(second_prop, clearing) == "0.00"
        assert frappe.db.get_value("HS Incident", linen_sent["incident"],
                                   "stock_entry") == linen_sent["stock_entry"]
        assert any(row["name"] == linen_product for row in
                   api.linen_board(second_prop.name, "Receive")["products"])
        try:
            api.execute(prop.name, "linen", "linen-wrong-property-" + suffix,
                        linen_send_data)
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Ropa de otro establecimiento se movió")
        try:
            incident_count = frappe.db.count("HS Incident", {
                "property": second_prop.name, "kind": "Linen"})
            api.execute(second_prop.name, "linen", "linen-overdraw-" + suffix,
                {**linen_send_data, "quantity": "2"})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La salida de ropa permitió saldo negativo")
        assert frappe.db.count("HS Incident", {"property": second_prop.name,
            "kind": "Linen"}) == incident_count
        linen_received = api.execute(second_prop.name, "linen",
            "linen-receive-" + suffix,
            {**linen_send_data, "direction": "Receive", "quantity": "1"})
        assert linen_received["value"] == "10.00"
        expense_before_linen_loss = Decimal(standalone_accounting.balance(
            second_prop, operating_expense))
        linen_lost = api.execute(second_prop.name, "linen", "linen-loss-" + suffix,
            {**linen_send_data, "direction": "Loss", "quantity": "1",
             "reason": "Pieza no devuelta por lavandería"})
        assert Decimal(linen_lost["value"]) == Decimal("10.00")
        assert standalone_inventory.current_balance(second_prop, linen_product,
            destination) == (Decimal("0"), Decimal("0.00"))
        assert Decimal(standalone_accounting.balance(second_prop,
            operating_expense)) == expense_before_linen_loss + 10
        assert standalone_accounting.balance(second_prop, clearing) == "0.00"
        history = api.linen_board(second_prop.name, "Send")["history"]
        assert {row["linen_direction"] for row in history if row["item"] == linen_product} == {
            "Send", "Receive", "Loss"}
        shortage_data = dict(product=stock_service["item"],
            warehouse=stock_service["warehouse"], counted_quantity="0",
            adjustment_account=operating_expense,
            reference="COUNT-SHORT-" + suffix, reason="Conteo físico con faltante")
        shortage = api.execute(second_prop.name, "pms_count_stock",
            "count-short-" + suffix, shortage_data)
        assert api.execute(second_prop.name, "pms_count_stock",
            "count-short-" + suffix, shortage_data) == shortage
        assert Decimal(shortage["difference"]) == -1 and Decimal(shortage["value"]) == -10
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            stock_service["warehouse"]) == (Decimal("0"), Decimal("0.00"))
        overage_data = dict(product=stock_service["item"], warehouse=destination,
            counted_quantity="2", adjustment_account=income,
            reference="COUNT-OVER-" + suffix, reason="Conteo físico con sobrante")
        overage = api.execute(second_prop.name, "pms_count_stock",
            "count-over-" + suffix, overage_data)
        assert Decimal(overage["difference"]) == 1 and Decimal(overage["value"]) == 10
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            destination) == (Decimal("2"), Decimal("20.00"))
        matching = api.execute(second_prop.name, "pms_count_stock",
            "count-matching-" + suffix,
            dict(product=stock_service["item"], warehouse=destination,
                 counted_quantity="2", reference="COUNT-EQUAL-" + suffix,
                 reason="Conteo físico conciliado"))
        assert Decimal(matching["difference"]) == 0 and not matching["movement"]
        try:
            api.execute(second_prop.name, "pms_count_stock", "duplicate-count-reference-" + suffix,
                dict(product=stock_service["item"], warehouse=destination,
                     counted_quantity="2", reference="COUNT-EQUAL-" + suffix,
                     reason="No duplicar un conteo conciliado"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se duplicó un conteo con otra clave")
        new_value = api.execute(second_prop.name, "pms_count_stock",
            "count-new-value-" + suffix,
            dict(product=stock_service["item"], warehouse=stock_service["warehouse"],
                 counted_quantity="1", value="12.50", adjustment_account=income,
                 reference="COUNT-NEW-" + suffix, reason="Producto encontrado en almacén"))
        assert new_value["value"] == "12.50"
        assert any(row["name"] == matching["count"] for row in
                   api.pms_inventory_snapshot(second_prop.name)["counts"])
        supplier = api.execute(second_prop.name, "pms_supplier", "purchase-supplier-" + suffix,
            dict(party_name="Proveedor de minibar", tax_id="SUP-" + suffix))["supplier"]
        payable = api.execute(second_prop.name, "pms_account", "purchase-payable-" + suffix,
            dict(account_code="2200" + suffix, account_name="Proveedores PMS",
                 root_type="Liability", account_type="Payable"))["account"]
        assert_manual_control_rejected(payable, "AP")
        input_tax = api.execute(second_prop.name, "pms_account", "purchase-tax-" + suffix,
            dict(account_code="1300" + suffix, account_name="Impuesto recuperable",
                 root_type="Asset", account_type="Tax"))["account"]
        purchase_data = dict(supplier=supplier, supplier_reference="BILL-" + suffix,
            product=stock_service["item"], warehouse=stock_service["warehouse"],
            quantity="2", invoice_currency="USD", invoice_amount="2.00",
            recoverable_tax="0.20", payable_account=payable, tax_account=input_tax,
            notes="Compra de reposición")
        purchase_quote = api.pms_purchase_quote(second_prop.name, purchase_data)
        assert purchase_quote["base_amount"] == "73.00"
        assert purchase_quote["base_cost"] == "65.70"
        assert purchase_quote["base_tax"] == "7.30"
        purchase_command = {**purchase_data, "acceptance": purchase_quote["acceptance"]}
        purchase = api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-receipt-" + suffix, purchase_command)
        assert api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-receipt-" + suffix, purchase_command) == purchase
        assert_manual_control_rejected(input_tax, "INPUTTAX")
        assert standalone_accounting.balance(second_prop, payable) == "-73.00"
        assert standalone_accounting.balance(second_prop, input_tax) == "7.30"
        assert standalone_inventory.current_balance(second_prop, stock_service["item"],
            stock_service["warehouse"]) == (Decimal("3"), Decimal("78.20"))
        for journal_name in (purchase["stock_journal"], purchase["tax_journal"]):
            try:
                api.execute(second_prop.name, "pms_reverse_journal",
                    "reverse-purchase-" + journal_name + suffix,
                    dict(journal=journal_name, reason="Debe conservar la compra y su inventario"))
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Se revirtió un asiento de compra con saldos vinculados")
        from hospitality_suite.standalone_purchases import outstanding as supplier_outstanding
        assert supplier_outstanding(second_prop, purchase["purchase"]) == Decimal("73.00")
        try:
            api.execute(second_prop.name, "pms_receive_purchase", "duplicate-purchase-" + suffix,
                purchase_command)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se registró dos veces la factura del proveedor")
        cash_supplier_data = dict(purchase=purchase["purchase"], method=cash_method,
            shift=shift, amount="1.00", reference="SUP-CASH-" + suffix,
            reason="Abono en efectivo al proveedor")
        cash_supplier_quote = api.pms_supplier_payment_quote(second_prop.name,
            cash_supplier_data)
        paid_cash = api.execute(second_prop.name, "pms_pay_supplier",
            "supplier-cash-payment-" + suffix,
            {**cash_supplier_data, "acceptance": cash_supplier_quote["acceptance"]})
        assert paid_cash["outstanding"] == "36.50"
        assert frappe.db.get_value("HS Payment", paid_cash["payment"],
                                   "pms_purchase") == purchase["purchase"]
        assert supplier_outstanding(second_prop, purchase["purchase"]) == Decimal("36.50")
        bank_supplier_data = dict(purchase=purchase["purchase"], method=bank_method,
            amount="1.00", reference="SUP-BANK-" + suffix,
            reason="Saldo bancario al proveedor")
        bank_supplier_quote = api.pms_supplier_payment_quote(second_prop.name,
            bank_supplier_data)
        paid_bank = api.execute(second_prop.name, "pms_pay_supplier",
            "supplier-bank-payment-" + suffix,
            {**bank_supplier_data, "acceptance": bank_supplier_quote["acceptance"]})
        assert paid_bank["outstanding"] == "0.00"
        assert supplier_outstanding(second_prop, purchase["purchase"]) == 0
        assert standalone_accounting.balance(second_prop, payable) == "0.00"
        assert any(row["name"] == purchase["purchase"] and row["outstanding"] == "0.00"
                   for row in api.pms_purchase_snapshot(second_prop.name)["purchases"])
        try:
            api.execute(second_prop.name, "pms_pay_supplier", "supplier-overpay-" + suffix,
                {**bank_supplier_data, "reference": "SUP-OVER-" + suffix,
                 "acceptance": bank_supplier_quote["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se pagó una compra ya saldada")
        loan_account = api.execute(second_prop.name, "pms_account", "loan-account-" + suffix,
            dict(account_code="2300" + suffix, account_name="Préstamos PMS",
                 root_type="Liability", account_type="Liability"))["account"]
        capital_account = api.execute(second_prop.name, "pms_account", "capital-account-" + suffix,
            dict(account_code="3200" + suffix, account_name="Capital PMS",
                 root_type="Equity", account_type="Equity"))["account"]
        loan_concept = api.execute(second_prop.name, "pms_income_concept", "loan-concept-" + suffix,
            dict(label="Préstamo socios", nature="Loan", account=loan_account))["concept"]
        capital_concept = api.execute(second_prop.name, "pms_income_concept", "capital-concept-" + suffix,
            dict(label="Aporte propietarios", nature="Capital", account=capital_account))["concept"]
        assert_manual_control_rejected(loan_account, "LOAN")
        assert_manual_control_rejected(capital_account, "CAPITAL")
        loan_request = api.execute(second_prop.name, "pms_financing_request", "loan-request-" + suffix,
            dict(kind="Loan Received", concept=loan_concept, amount="73.00",
                 reason="Financiar reposición de inventario"))["movement"]
        try:
            api.execute(second_prop.name, "pms_financing_approve", "self-loan-" + suffix,
                dict(movement=loan_request, reason="Intento de autoaprobación"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió aprobar el préstamo propio")
        approver = "hs-manager-" + suffix + "@example.invalid"
        frappe.get_doc(dict(doctype="User", email=approver, first_name="Gerencia PMS",
            enabled=1, send_welcome_email=0,
            roles=[dict(role="System Manager")])).insert(ignore_permissions=True)
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_financing_approve", "approve-loan-" + suffix,
                dict(movement=loan_request, reason="Principal autorizado"))
        finally:
            frappe.set_user("Administrator")
        loan_data = dict(movement=loan_request, method=bank_method, amount="2.00",
            reference="LOAN-" + suffix, reason="Ingreso de préstamo bancario")
        loan_quote = api.pms_financing_quote(second_prop.name, loan_data)
        assert loan_quote["base_amount"] == "73.00"
        received_loan = api.execute(second_prop.name, "pms_financing_post", "post-loan-" + suffix,
            {**loan_data, "acceptance": loan_quote["acceptance"]})
        assert api.execute(second_prop.name, "pms_financing_post", "post-loan-" + suffix,
            {**loan_data, "acceptance": loan_quote["acceptance"]}) == received_loan
        assert standalone_accounting.balance(second_prop, loan_account) == "-73.00"
        repayment = api.execute(second_prop.name, "pms_financing_request", "loan-return-" + suffix,
            dict(kind="Loan Repayment", source_movement=loan_request,
                 amount="36.50", reason="Abono del principal"))["movement"]
        try:
            api.execute(second_prop.name, "pms_financing_request", "loan-excess-" + suffix,
                dict(kind="Loan Repayment", source_movement=loan_request,
                     amount="73.00", reason="Duplicar el principal reservado"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se reservó dos veces el principal del préstamo")
        from hospitality_suite.standalone_financing import remaining as principal_remaining
        loan_source = frappe.get_doc("HS Treasury Movement", loan_request)
        assert principal_remaining(second_prop, loan_source) == Decimal("36.50")
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_financing_approve", "approve-return-" + suffix,
                dict(movement=repayment, reason="Devolución autorizada"))
        finally:
            frappe.set_user("Administrator")
        repayment_data = dict(movement=repayment, method=bank_method, amount="1.00",
            reference="REPAY-" + suffix, reason="Devolución bancaria de principal")
        repayment_quote = api.pms_financing_quote(second_prop.name, repayment_data)
        repaid = api.execute(second_prop.name, "pms_financing_post", "post-return-" + suffix,
            {**repayment_data, "acceptance": repayment_quote["acceptance"]})
        assert standalone_accounting.balance(second_prop, loan_account) == "-36.50"
        assert principal_remaining(second_prop, loan_source, reserve=False) == Decimal("36.50")
        from hospitality_suite.financial_movements import outstanding as erp_principal_remaining
        assert erp_principal_remaining(loan_source) == Decimal("36.50")
        spare_request = api.execute(second_prop.name, "pms_financing_request",
            "loan-cancel-request-" + suffix,
            dict(kind="Loan Repayment", source_movement=loan_request,
                 amount="36.50", reason="Solicitud que se cancelará"))["movement"]
        assert principal_remaining(second_prop, loan_source) == 0
        assert erp_principal_remaining(loan_source) == 0
        api.execute(second_prop.name, "pms_financing_cancel", "loan-cancel-" + suffix,
            dict(movement=spare_request, reason="No se entregará este principal"))
        assert principal_remaining(second_prop, loan_source) == Decimal("36.50")
        assert erp_principal_remaining(loan_source) == Decimal("36.50")
        frappe.db.savepoint("pms_loan_origin_probe")
        try:
            frappe.db.set_value("HS Treasury Movement", loan_request,
                "pms_journal", None, update_modified=False)
            try:
                erp_principal_remaining(frappe.get_doc("HS Treasury Movement", loan_request))
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("ERPNext aceptó un préstamo PMS sin asiento original")
        finally:
            frappe.db.rollback(save_point="pms_loan_origin_probe")
        income_before = Decimal(standalone_accounting.balance(second_prop, income))
        other_income_data = dict(concept=concept, method=bank_method, amount="1.00",
            reference="OTHER-BANK-" + suffix, reason="Otro ingreso bancario sin factura")
        other_income_quote = api.pms_financing_quote(second_prop.name, other_income_data)
        api.execute(second_prop.name, "pms_financing_post", "other-bank-" + suffix,
            {**other_income_data, "acceptance": other_income_quote["acceptance"]})
        assert Decimal(standalone_accounting.balance(second_prop, income)) == income_before - Decimal("36.50")
        try:
            api.execute(second_prop.name, "pms_reverse_journal", "reverse-loan-" + suffix,
                dict(journal=repaid["journal"], reason="Debe conservar el principal vinculado"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revirtió el asiento de un principal vinculado")
        capital_request = api.execute(second_prop.name, "pms_financing_request", "capital-in-" + suffix,
            dict(kind="Capital Contribution", concept=capital_concept,
                 amount="36.50", reason="Aporte de propietario"))["movement"]
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_financing_approve", "approve-capital-" + suffix,
                dict(movement=capital_request, reason="Aporte autorizado"))
        finally:
            frappe.set_user("Administrator")
        capital_in_data = dict(movement=capital_request, method=cash_method, shift=shift,
            amount="1.00", reference="CAPITAL-IN-" + suffix,
            reason="Aporte efectivo del propietario")
        capital_in_quote = api.pms_financing_quote(second_prop.name, capital_in_data)
        api.execute(second_prop.name, "pms_financing_post", "post-capital-" + suffix,
            {**capital_in_data, "acceptance": capital_in_quote["acceptance"]})
        assert standalone_accounting.balance(second_prop, capital_account) == "-36.50"
        withdrawal = api.execute(second_prop.name, "pms_financing_request", "capital-out-" + suffix,
            dict(kind="Capital Withdrawal", source_movement=capital_request,
                 amount="36.50", reason="Retiro del aporte"))["movement"]
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_financing_approve", "approve-withdrawal-" + suffix,
                dict(movement=withdrawal, reason="Retiro autorizado"))
        finally:
            frappe.set_user("Administrator")
        withdrawal_data = dict(movement=withdrawal, method=cash_method, shift=shift,
            amount="1.00", reference="CAPITAL-OUT-" + suffix,
            reason="Retiro efectivo del aporte")
        withdrawal_quote = api.pms_financing_quote(second_prop.name, withdrawal_data)
        api.execute(second_prop.name, "pms_financing_post", "post-withdrawal-" + suffix,
            {**withdrawal_data, "acceptance": withdrawal_quote["acceptance"]})
        assert standalone_accounting.balance(second_prop, capital_account) == "0.00"
        assert principal_remaining(second_prop,
            frappe.get_doc("HS Treasury Movement", capital_request), reserve=False) == 0
        assert api.pms_financing_snapshot(second_prop.name)["sources"]
        petty_account = api.execute(second_prop.name, "pms_account", "petty-account-" + suffix,
            dict(account_code="1400" + suffix, account_name="Caja Chica",
                 root_type="Asset", account_type="Current Asset"))["account"]
        overage_account = api.execute(second_prop.name, "pms_account", "petty-over-" + suffix,
            dict(account_code="4100" + suffix, account_name="Sobrante Caja Chica",
                 root_type="Income", account_type="Income Account"))["account"]
        shortage_account = api.execute(second_prop.name, "pms_account", "petty-short-" + suffix,
            dict(account_code="5100" + suffix, account_name="Faltante Caja Chica",
                 root_type="Expense", account_type="Expense Account"))["account"]
        assert api.execute(second_prop.name, "pms_petty_configure", "petty-config-" + suffix,
            dict(petty_cash_account=petty_account,
                 petty_cash_responsible="Administrator",
                 petty_cash_overage_account=overage_account,
                 petty_cash_shortage_account=shortage_account))["active"]
        second_prop.reload()
        petty_fund_data = dict(kind="Initial Fund", method=nio_method, shift=shift,
            amount="40.00", reference="PETTY-OPEN-" + suffix,
            reason="Entrega inicial de Caja Chica")
        initial_fund = api.execute(second_prop.name, "pms_petty_fund",
            "petty-initial-" + suffix, petty_fund_data)
        assert api.execute(second_prop.name, "pms_petty_fund",
            "petty-initial-" + suffix, petty_fund_data) == initial_fund
        assert standalone_accounting.balance(second_prop, petty_account) == "40.00"
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["NIO"] == "60.00"
        from hospitality_suite.standalone_petty_cash import operational_balance
        assert operational_balance(second_prop) == Decimal("40.00")
        try:
            api.execute(second_prop.name, "pms_petty_fund", "petty-second-" + suffix,
                {**petty_fund_data, "reference": "PETTY-SECOND-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se entregó dos veces el fondo inicial")
        transient = api.execute(second_prop.name, "pms_petty_expense", "petty-temp-" + suffix,
            dict(category=category, beneficiary="Proveedor temporal", concept="Compra revertida",
                 receipt_reference="PT-" + suffix, amount="3.00"))["expense"]
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_petty_reverse", "reverse-petty-temp-" + suffix,
                dict(doctype="HS Petty Cash Expense", name=transient,
                     reason="Comprobante duplicado"))
        finally:
            frappe.set_user("Administrator")
        assert operational_balance(second_prop) == Decimal("40.00")
        expense_one = api.execute(second_prop.name, "pms_petty_expense", "petty-one-" + suffix,
            dict(category=category, beneficiary="Papelería", concept="Útiles de oficina",
                 receipt_reference="P1-" + suffix, amount="10.00"))["expense"]
        expense_two = api.execute(second_prop.name, "pms_petty_expense", "petty-two-" + suffix,
            dict(category=category, beneficiary="Mensajería", concept="Entrega local",
                 receipt_reference="P2-" + suffix, amount="5.00"))["expense"]
        assert operational_balance(second_prop) == Decimal("25.00")
        try:
            api.execute(second_prop.name, "pms_petty_expense", "petty-overdraw-" + suffix,
                dict(category=category, beneficiary="Exceso", concept="Sin fondo",
                     receipt_reference="PX-" + suffix, amount="26.00"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Caja Chica permitió saldo negativo")
        first_rendition = api.execute(second_prop.name, "pms_petty_submit",
            "petty-submit-" + suffix, dict(counted_cash="25.00"))["rendition"]
        try:
            api.execute(second_prop.name, "pms_petty_review", "self-rendition-" + suffix,
                dict(rendition=first_rendition, approve=1, note="Autoaprobación"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El responsable aprobó su propia rendición")
        try:
            frappe.set_user(approver)
            returned = api.execute(second_prop.name, "pms_petty_review",
                "return-rendition-" + suffix,
                dict(rendition=first_rendition, approve=0,
                     note="Corregir referencia y arqueo"))
        finally:
            frappe.set_user("Administrator")
        assert returned["status"] == "Returned"
        api.execute(second_prop.name, "pms_petty_correct", "correct-petty-" + suffix,
            dict(expense=expense_two, receipt_reference="P2-COR-" + suffix))
        resubmitted = api.execute(second_prop.name, "pms_petty_submit",
            "resubmit-petty-" + suffix,
            dict(rendition=first_rendition, counted_cash="22.00",
                 explanation="Faltante físico justificado"))
        assert resubmitted["variance"] == "-3.00" and resubmitted["expense_total"] == "15.00"
        try:
            frappe.set_user(approver)
            approved_rendition = api.execute(second_prop.name, "pms_petty_review",
                "approve-rendition-" + suffix,
                dict(rendition=first_rendition, approve=1,
                     note="Diferencia revisada"))
        finally:
            frappe.set_user("Administrator")
        assert approved_rendition["status"] == "Approved"
        assert standalone_accounting.balance(second_prop, petty_account) == "22.00"
        assert standalone_accounting.balance(second_prop, shortage_account) == "3.00"
        partial_data = dict(kind="Replenishment", rendition=first_rendition,
            method=nio_method, shift=shift, amount="6.00",
            reference="PETTY-PART-" + suffix, reason="Reposición parcial")
        partial = api.execute(second_prop.name, "pms_petty_fund",
            "petty-partial-" + suffix, partial_data)
        assert partial["balance"] == "28.00"
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_petty_reverse", "reverse-partial-" + suffix,
                dict(doctype="HS Treasury Movement", name=partial["movement"],
                     reason="Entrega física anulada"))
        finally:
            frappe.set_user("Administrator")
        assert operational_balance(second_prop) == Decimal("22.00")
        assert frappe.db.get_value("HS Petty Cash Rendition", first_rendition,
                                   "status") == "Approved"
        api.execute(second_prop.name, "pms_petty_fund", "petty-partial-again-" + suffix,
            {**partial_data, "reference": "PETTY-RETRY-" + suffix})
        try:
            api.execute(second_prop.name, "pms_petty_fund", "petty-overreplenish-" + suffix,
                {**partial_data, "amount": "10.00", "reference": "PETTY-OVER-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La reposición excedió gastos aprobados pendientes")
        api.execute(second_prop.name, "pms_petty_fund", "petty-rest-" + suffix,
            {**partial_data, "amount": "9.00", "reference": "PETTY-REST-" + suffix})
        assert operational_balance(second_prop) == Decimal("37.00")
        assert frappe.db.get_value("HS Petty Cash Rendition", first_rendition,
                                   "status") == "Reimbursed"
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["NIO"] == "45.00"
        try:
            api.execute(second_prop.name, "pms_manual_journal", "manual-petty-" + suffix,
                dict(reference="MANUAL-PETTY-" + suffix,
                     reason="La cuenta de control requiere su flujo propio",
                     lines=[dict(account=petty_account, debit="1.00", credit="0"),
                            dict(account=capital_account, debit="0", credit="1.00")]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Un asiento manual alteró Caja Chica")
        overage_expense = api.execute(second_prop.name, "pms_petty_expense",
            "petty-overage-expense-" + suffix,
            dict(category=category, beneficiary="Entrega menor",
                 concept="Gasto previo a arqueo", receipt_reference="PO-" + suffix,
                 amount="2.00"))["expense"]
        overage_rendition = api.execute(second_prop.name, "pms_petty_submit",
            "petty-overage-submit-" + suffix,
            dict(counted_cash="36.00", explanation="Sobrante físico de un córdoba"))["rendition"]
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_petty_review",
                "petty-overage-approve-" + suffix,
                dict(rendition=overage_rendition, approve=1,
                     note="Sobrante físico confirmado"))
            api.execute(second_prop.name, "pms_petty_reverse",
                "petty-overage-reverse-" + suffix,
                dict(doctype="HS Petty Cash Rendition", name=overage_rendition,
                     reason="Repetir el arqueo antes de ajustar"))
        finally:
            frappe.set_user("Administrator")
        assert standalone_accounting.balance(second_prop, overage_account) == "0.00"
        assert operational_balance(second_prop) == Decimal("35.00")
        api.execute(second_prop.name, "pms_petty_submit",
            "petty-overage-resubmit-" + suffix,
            dict(rendition=overage_rendition, counted_cash="36.00",
                 explanation="Sobrante confirmado en segundo conteo"))
        try:
            frappe.set_user(approver)
            api.execute(second_prop.name, "pms_petty_review",
                "petty-overage-reapprove-" + suffix,
                dict(rendition=overage_rendition, approve=1,
                     note="Segundo arqueo aprobado"))
        finally:
            frappe.set_user("Administrator")
        assert standalone_accounting.balance(second_prop, overage_account) == "-1.00"
        assert operational_balance(second_prop) == Decimal("36.00")
        assert frappe.db.get_value("HS Petty Cash Expense", overage_expense,
                                   "rendition") == overage_rendition
        api.execute(second_prop.name, "pms_petty_fund", "petty-overage-replenish-" + suffix,
            dict(kind="Replenishment", rendition=overage_rendition,
                 method=nio_method, shift=shift, amount="2.00",
                 reference="PETTY-OVER-REP-" + suffix,
                 reason="Reponer solo el gasto aprobado"))
        assert operational_balance(second_prop) == Decimal("38.00")
        assert standalone_cash.expected(frappe.get_doc("HS Shift", shift))["NIO"] == "43.00"
        handover = api.execute(second_prop.name, "pms_petty_handover",
            "petty-handover-" + suffix,
            dict(incoming=approver, counted_cash="38.00",
                 reason="Cambio de custodio"))["handover"]
        assert api.execute(second_prop.name, "pms_petty_accept",
            "petty-outgoing-" + suffix, dict(handover=handover))["status"] == "Awaiting Acceptance"
        try:
            frappe.set_user(approver)
            accepted_handover = api.execute(second_prop.name, "pms_petty_accept",
                "petty-incoming-" + suffix, dict(handover=handover))
        finally:
            frappe.set_user("Administrator")
        assert accepted_handover["status"] == "Completed"
        second_prop.reload()
        assert second_prop.petty_cash_responsible == approver
        assert api.pms_petty_snapshot(second_prop.name)["reconciled"]
        try:
            api.execute(second_prop.name, "pms_petty_expense", "old-responsible-" + suffix,
                dict(category=category, beneficiary="No autorizado", concept="Custodia nueva",
                     receipt_reference="OLD-" + suffix, amount="1.00"))
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("El responsable saliente siguió desembolsando")
        try:
            api.save_setup(second_prop.name, "product",
                {"name": stock_service["item"], "inventory_account": clearing},
                "change-stock-account-" + suffix,
                expected_modified=str(frappe.db.get_value("HS Product", stock_service["item"], "modified")))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se cambió la cuenta de inventario con movimientos históricos")
        def deactivate_stock_warehouse(locked):
            warehouse = frappe.get_doc("HS Warehouse", destination, for_update=True)
            warehouse.active = 0
            warehouse.save()
            return warehouse.name
        try:
            command(second_prop.name, "setup", "deactivate-stock-warehouse-" + suffix,
                {"operation": "smoke_deactivate_stock_warehouse"}, deactivate_stock_warehouse)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se desactivó un almacén con existencias")
        try:
            api.execute(second_prop.name, "pms_opening_stock", "second-opening-" + suffix,
                {**stock_opening_data, "reference": "second-guest-stock-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se registró un saldo inicial después de movimientos de inventario")
        no_stock = api.execute(second_prop.name, "request_service", "service-no-stock-" + suffix,
            {**stock_data, "quantity": "4"})
        try:
            api.execute(second_prop.name, "update_service", "service-no-stock-deliver-" + suffix,
                dict(service=no_stock["service"],
                     modified=str(frappe.db.get_value("HS Service Request", no_stock["service"], "modified")),
                     status="Delivered"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se entregó un producto sin existencias")
        api.execute(second_prop.name, "update_service", "service-no-stock-cancel-" + suffix,
            dict(service=no_stock["service"],
                 modified=str(frappe.db.get_value("HS Service Request", no_stock["service"], "modified")),
                 status="Cancelled"))
        service_options = api.pms_folio_service_options(second_prop.name, fixture["folio"])
        assert fixture["stay"] in [row["name"] for row in service_options["stays"]]
        assert taxed_product in [row["name"] for row in service_options["products"]]
        service_data = dict(folio=fixture["folio"], stay=fixture["stay"],
                            product=taxed_product, quantity="1")
        stale_service = api.pms_folio_service_quote(second_prop.name, service_data)
        assert stale_service["total_amount"] == "103.50"
        api.save_setup(second_prop.name, "product",
            {"name": taxed_product, "sales_rate": "100.00"},
            "service-price-" + suffix,
            expected_modified=str(frappe.db.get_value("HS Product", taxed_product, "modified")))
        try:
            api.execute(second_prop.name, "pms_add_folio_service", "stale-service-" + suffix,
                {**service_data, "acceptance": stale_service["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Un servicio conservó una cotización de precio anterior")
        try:
            api.pms_folio_service_quote(prop.name, service_data)
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Se consultó un servicio de otro establecimiento")
        service_quote = api.pms_folio_service_quote(second_prop.name, service_data)
        assert service_quote["net_amount"] == "100.00"
        assert service_quote["tax_amount"] == "15.00"
        service_command = {**service_data, "acceptance": service_quote["acceptance"]}
        added_service = api.execute(second_prop.name, "pms_add_folio_service",
            "folio-service-" + suffix, service_command)
        assert api.execute(second_prop.name, "pms_add_folio_service",
            "folio-service-" + suffix, service_command) == added_service
        taxed_charge = added_service["charge"]
        assert frappe.db.get_value("HS Charge", taxed_charge, "amount") == Decimal("100.00")
        assert folio_balance(fixture["folio"])["pending"] == "115.00"
        adjustment_base = dict(folio=fixture["folio"], source_charge=taxed_charge)
        adjustment_options = api.pms_folio_adjustment_options(second_prop.name, fixture["folio"])
        assert any(row["source_charge"] == taxed_charge and row["current_price"] == "100.00"
                   for row in adjustment_options)
        discount_data = {**adjustment_base, "amount": "-10.00", "reason": "Descuento autorizado"}
        discount_quote = api.pms_folio_adjustment_quote(second_prop.name, discount_data)
        assert discount_quote["new_price"] == "90.00"
        assert discount_quote["new_tax"] == "13.50"
        discount_command = {**discount_data, "acceptance": discount_quote["acceptance"]}
        discount = api.execute(second_prop.name, "pms_adjust_folio_charge",
            "folio-discount-tax-" + suffix, discount_command)
        assert api.execute(second_prop.name, "pms_adjust_folio_charge",
            "folio-discount-tax-" + suffix, discount_command) == discount
        assert folio_balance(fixture["folio"])["pending"] == "103.50"
        stale_adjustment = {**adjustment_base, "amount": "5.00", "reason": "Cambio pendiente"}
        stale_adjustment_quote = api.pms_folio_adjustment_quote(second_prop.name, stale_adjustment)
        surcharge_data = {**adjustment_base, "amount": "10.00", "reason": "Recargo autorizado"}
        surcharge_quote = api.pms_folio_adjustment_quote(second_prop.name, surcharge_data)
        surcharge = api.execute(second_prop.name, "pms_adjust_folio_charge",
            "folio-surcharge-" + suffix,
            {**surcharge_data, "acceptance": surcharge_quote["acceptance"]})
        assert surcharge["new_total"] == "115.00"
        assert folio_balance(fixture["folio"])["pending"] == "115.00"
        try:
            api.execute(second_prop.name, "pms_adjust_folio_charge",
                "stale-adjustment-" + suffix,
                {**stale_adjustment, "acceptance": stale_adjustment_quote["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aprobó un ajuste tras cambiar el cargo")
        try:
            api.pms_folio_adjustment_quote(second_prop.name,
                {**adjustment_base, "amount": "-101.00", "reason": "Excede el cargo"})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El descuento superó el saldo pendiente")
        try:
            api.pms_folio_adjustment_quote(prop.name, discount_data)
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("Se ajustó un cargo de otro establecimiento")
        void_service_data = {**service_data, "quantity": "0.5"}
        void_service_quote = api.pms_folio_service_quote(second_prop.name, void_service_data)
        void_service = api.execute(second_prop.name, "pms_add_folio_service",
            "void-service-" + suffix,
            {**void_service_data, "acceptance": void_service_quote["acceptance"]})
        assert folio_balance(fixture["folio"])["pending"] == "172.50"
        void_discount_data = dict(folio=fixture["folio"],
            source_charge=void_service["charge"], amount="-10.00",
            reason="Descuento previo a la anulación")
        void_discount_quote = api.pms_folio_adjustment_quote(second_prop.name,
            void_discount_data)
        void_discount = api.execute(second_prop.name, "pms_adjust_folio_charge",
            "void-discount-" + suffix,
            {**void_discount_data, "acceptance": void_discount_quote["acceptance"]})
        assert folio_balance(fixture["folio"])["pending"] == "161.00"
        void_data = dict(folio=fixture["folio"], source_charge=void_service["charge"],
                         amount="-40.00", reason="Servicio registrado por error")
        void_quote = api.pms_folio_adjustment_quote(second_prop.name, void_data)
        assert void_quote["action"] == "Void" and void_quote["new_total"] == "0.00"
        void_command = {**void_data, "acceptance": void_quote["acceptance"]}
        voided = api.execute(second_prop.name, "pms_adjust_folio_charge",
            "void-charge-" + suffix, void_command)
        assert api.execute(second_prop.name, "pms_adjust_folio_charge",
            "void-charge-" + suffix, void_command) == voided
        assert frappe.db.get_value("HS Charge", void_service["charge"], "status") == "Reversed"
        assert frappe.db.get_value("HS Charge", void_discount["adjustment"], "status") == "Reversed"
        assert folio_balance(fixture["folio"])["pending"] == "115.00"
        taxed_quote = api.pms_folio_quote(second_prop.name,
            dict(folio=fixture["folio"], receivable_account=ar))
        assert taxed_quote["total"] == "115.00" and taxed_quote["lines"][0]["tax_amount"] == "15.00"
        assert len(taxed_quote["lines"][0]["charge_names"]) == 3
        taxed_bill = api.execute(second_prop.name, "pms_bill_folio", "folio-tax-bill-" + suffix,
            dict(folio=fixture["folio"], receivable_account=ar,
                 acceptance=taxed_quote["acceptance"]))
        assert taxed_bill["total"] == "115.00"
        assert frappe.db.get_value("HS Charge", taxed_charge, "pms_receivable") == taxed_bill["receivables"][0]["receivable"]
        try:
            api.pms_folio_adjustment_quote(second_prop.name, discount_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se ajustó un cargo después de contabilizarlo")
        assert folio_balance(fixture["folio"])["outstanding"] == "153.50"
        assert api.execute(second_prop.name, "pms_close_shift", "close-fx-" + suffix,
                           dict(shift=shift, counted_by_currency={"NIO": "43", "USD": "14"}))["status"] == "Closed"
        finance_review = api.pms_close_preview(second_prop.name)
        assert finance_review["snapshot"]["breakdown"]["treasury"]
        assert finance_review["snapshot"]["breakdown"]["petty_expenses"]
        assert finance_review["snapshot"]["breakdown"]["petty_variances"]
        assert finance_review["snapshot"]["ledger"]["day_debit"] == finance_review["snapshot"]["ledger"]["day_credit"]
        close_property = setup.create_property(dict(property_name="Hotel cierre " + suffix,
            organization=org.name, currency="NIO", mode="Hotel"), "close-property-" + suffix)
        close_prop = frappe.get_doc("HS Property", close_property["property"])
        close_cash = api.execute(close_prop.name, "pms_account", "close-cash-" + suffix,
            dict(account_code="1011" + suffix, account_name="Caja de cierre",
                 root_type="Asset", account_type="Cash", is_cash=1))["account"]
        close_capital = api.execute(close_prop.name, "pms_account", "close-capital-" + suffix,
            dict(account_code="3011" + suffix, account_name="Capital de cierre",
                 root_type="Equity", account_type="Equity"))["account"]
        close_income = api.execute(close_prop.name, "pms_account", "close-income-" + suffix,
            dict(account_code="4011" + suffix, account_name="Otros ingresos de cierre",
                 root_type="Income", account_type="Income Account"))["account"]
        api.execute(close_prop.name, "pms_opening_balance", "close-opening-" + suffix,
            dict(reference="CLOSE-OPEN-" + suffix, lines=[
                dict(account=close_cash, debit="50.00", credit=0),
                dict(account=close_capital, debit=0, credit="50.00")]))
        close_method = api.execute(close_prop.name, "pms_payment_method", "close-method-" + suffix,
            dict(label="Efectivo cierre", account=close_cash))["method"]
        close_concept = api.execute(close_prop.name, "pms_income_concept", "close-concept-" + suffix,
            dict(label="Ingreso ajeno a ventas", nature="Other Income",
                 account=close_income))["concept"]
        close_shift = api.execute(close_prop.name, "pms_open_shift", "close-shift-" + suffix,
            dict(opening_by_currency={"NIO": "50.00"}))["shift"]
        income_data = dict(kind="Other Income", amount="5.00", method=close_method,
            shift=close_shift, concept=close_concept, reference="CLOSE-IN-" + suffix,
            reason="Ingreso separado de ventas")
        income_quote = api.pms_cash_preview(close_prop.name, income_data)
        api.execute(close_prop.name, "pms_cash_movement", "close-income-post-" + suffix,
            {**income_data, "expected_exchange_rate": income_quote["exchange_rate"],
             "expected_rate_record": income_quote["exchange_rate_record"],
             "expected_debit": income_quote["debit"],
             "expected_credit": income_quote["credit"]})
        blocked_close = api.pms_close_preview(close_prop.name)
        assert any(row["type"] == "Turnos sin arquear" for row in blocked_close["blockers"])
        try:
            api.execute(close_prop.name, "pms_daily_close", "blocked-close-" + suffix,
                dict(review_acceptance=blocked_close["review_acceptance"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("El cierre permitió un turno abierto")
        api.execute(close_prop.name, "pms_close_shift", "close-shift-end-" + suffix,
            dict(shift=close_shift, counted_by_currency={"NIO": "55.00"}))
        close_review = api.pms_close_preview(close_prop.name)
        assert not close_review["blockers"]
        assert not close_review["snapshot"]["breakdown"]["production"]
        assert close_review["snapshot"]["breakdown"]["other_cash"][0]["base_amount"] == "5.00"
        assert close_review["snapshot"]["ledger"]["day_debit"] == "55.00"
        original_day = str(close_prop.business_date)
        confirmed = api.execute(close_prop.name, "pms_daily_close", "confirm-close-" + suffix,
            dict(review_acceptance=close_review["review_acceptance"],
                 reason="Cierre sin diferencias"))
        assert confirmed["status"] == "Closed"
        assert api.execute(close_prop.name, "pms_daily_close", "confirm-close-" + suffix,
            dict(review_acceptance=close_review["review_acceptance"],
                 reason="Cierre sin diferencias")) == confirmed
        close_prop.reload()
        assert str(close_prop.business_date) != original_day
        frozen = api.pms_close_detail(close_prop.name, confirmed["close"])
        assert frozen["snapshot"] == close_review["snapshot"]
        assert api.pms_close_history(close_prop.name)[0]["name"] == confirmed["close"]
        try:
            api.pms_close_detail(prop.name, confirmed["close"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Se consultó el cierre de otro establecimiento")
        reopened = api.execute(close_prop.name, "reopen_day", "reopen-close-" + suffix,
            dict(close=confirmed["close"], reason="Corrección autorizada"))
        assert reopened["status"] == "Reopened"
        close_prop.reload()
        assert str(close_prop.business_date) == original_day
        assert api.pms_close_detail(close_prop.name, confirmed["close"])["snapshot"] == frozen["snapshot"]
        stale_review = api.pms_close_preview(close_prop.name)
        api.execute(close_prop.name, "pms_manual_journal", "close-correction-" + suffix,
            dict(reference="CLOSE-CORR-" + suffix,
                 reason="Corrección contable posterior a reapertura",
                 lines=[dict(account=close_capital, debit="1.00", credit="0"),
                        dict(account=close_income, debit="0", credit="1.00")]))
        try:
            api.execute(close_prop.name, "pms_daily_close", "stale-close-" + suffix,
                dict(review_acceptance=stale_review["review_acceptance"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se confirmó un resumen anterior a una corrección")
        revised_review = api.pms_close_preview(close_prop.name)
        assert revised_review["snapshot"]["ledger"]["day_debit"] == "56.00"
        revised = api.execute(close_prop.name, "pms_daily_close", "revised-close-" + suffix,
            dict(review_acceptance=revised_review["review_acceptance"],
                 reason="Corrección incorporada"))
        assert revised["close"] != confirmed["close"]
        assert api.pms_close_detail(close_prop.name, confirmed["close"])["snapshot"] == frozen["snapshot"]
        assert len(api.pms_close_history(close_prop.name)) == 2
        report_day = str(second_prop.business_date)
        report_filters = {"from_date": report_day, "to_date": report_day}
        options = api.pms_report_options(second_prop.name)
        assert {row["name"] for row in options["reports"]} == {
            "trial_balance", "general_ledger", "receivables", "funds", "sales"}
        trial = api.pms_report(second_prop.name, "trial_balance", report_filters)
        assert trial["totals"]["debit"] == trial["totals"]["credit"]
        ledger = api.pms_report(second_prop.name, "general_ledger",
            {**report_filters, "account": petty_account}, 0, 2)
        assert ledger["total_rows"] > 2 and len(ledger["rows"]) == 2
        next_ledger = api.pms_report(second_prop.name, "general_ledger",
            {**report_filters, "account": petty_account}, 2, 2)
        assert next_ledger["rows"][0]["journal"] != ledger["rows"][0]["journal"]
        assert all(row["account"] == petty_account for row in ledger["rows"])
        full_ledger = api.pms_report(second_prop.name, "general_ledger",
            {**report_filters, "account": petty_account}, 0, 200)
        assert full_ledger["rows"][-1]["running_base"] == standalone_accounting.balance(
            second_prop, petty_account)
        funds_report = api.pms_report(second_prop.name, "funds", report_filters)
        assert any(row["source_type"] == "Treasury" for row in funds_report["rows"])
        assert any(row["source_type"] == "Petty Cash Expense" for row in funds_report["rows"])
        assert len({row["currency"] for row in funds_report["totals"]}) >= 2
        sales_report = api.pms_report(second_prop.name, "sales", report_filters)
        assert any(row["source_type"] == "Charge" for row in sales_report["rows"])
        assert any(row["source_type"] == "Credit Note" for row in sales_report["rows"])
        assert all(row["source_type"] != "Treasury" for row in sales_report["rows"])
        assert Decimal(sales_report["totals"]["net_amount"]) == sum(
            (Decimal(row["net_amount"]) for row in sales_report["rows"]), Decimal(0))
        customer_sales = api.pms_report(second_prop.name, "sales",
            {**report_filters, "party": customer})
        assert customer_sales["total_rows"] > 0
        assert all(row["party"] == customer for row in customer_sales["rows"])
        aging = api.pms_report(second_prop.name, "receivables", report_filters)
        assert aging["total_rows"] >= 1
        from hospitality_suite.standalone_receivables import list_receivables
        assert Decimal(aging["totals"]["outstanding"]) == sum(
            (max(Decimal(0), Decimal(row["outstanding"]))
             for row in list_receivables(second_prop)), Decimal(0))
        from hospitality_suite import standalone_reports
        previous_response = dict(frappe.local.response)
        try:
            standalone_reports.export_csv(second_prop.name, "general_ledger",
                {**report_filters, "account": petty_account})
            exported = frappe.local.response["filecontent"].decode("utf-8-sig")
            assert "Saldo original" in exported and petty_account not in exported
            assert "Caja Chica" in exported
        finally:
            frappe.local.response.clear()
            frappe.local.response.update(previous_response)
        try:
            api.pms_report(second_prop.name, "general_ledger",
                {**report_filters, "account": close_cash})
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("El mayor aceptó una cuenta de otro establecimiento")
        work_room = command(second_prop.name, "setup", "work-room-" + suffix,
            {"operation": "smoke_work_room"}, lambda locked: insert("HS Room", locked,
                room_number="909" + suffix, category=fixture["category"], active=1,
                cleaning_status="Clean").name)
        work_snapshot = api.pms_room_operations(second_prop.name)
        assert any(row["name"] == work_room for row in work_snapshot["rooms"])
        assert work_snapshot["can"]["clean"] and work_snapshot["can"]["maintain"]
        incident_data = {"room": work_room, "kind": "Lost Property",
            "description": "Objeto hallado durante limpieza"}
        incident = api.execute(second_prop.name, "incident", "work-incident-" + suffix,
            incident_data)
        assert api.execute(second_prop.name, "incident", "work-incident-" + suffix,
            incident_data) == incident
        second_incident = api.execute(second_prop.name, "incident",
            "work-incident-second-" + suffix,
            {**incident_data, "description": "Segundo objeto hallado"})
        first_page = api.room_incident_page(second_prop.name, room=work_room,
            page_length=1)
        next_page = api.room_incident_page(second_prop.name, room=work_room,
            page_length=1, offset=1)
        assert first_page["total"] == 2 and first_page["has_more"]
        assert not next_page["has_more"]
        assert {first_page["rows"][0]["name"], next_page["rows"][0]["name"]} == {
            incident["incident"], second_incident["incident"]}
        incident_page = api.room_incident_page(second_prop.name, room=work_room)
        incident_row = next(row for row in incident_page["rows"]
            if row["name"] == incident["incident"])
        assert incident_row["room"] == work_room and incident_row["kind"] == "Lost Property"
        assert incident_page["total"] >= 1
        assert api.room_incident_page(second_prop.name, room=work_room,
            search="durante limpieza", page_length=1)["rows"][0]["name"] == incident["incident"]
        try:
            api.room_incident_page(prop.name, room=work_room)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("La consulta de novedades aceptó una habitación de otro hotel")
        incident_file = frappe.get_doc({"doctype": "File",
            "file_name": "incident-" + suffix + ".txt",
            "content": ("Prueba de novedad " + suffix).encode(),
            "is_private": 1, "attached_to_doctype": "HS Incident",
            "attached_to_name": incident["incident"]}).insert(ignore_permissions=True)
        api.execute(second_prop.name, "incident", "work-incident-evidence-" + suffix,
            {"incident": incident["incident"],
             "modified": str(incident_row["modified"]),
             "evidence": incident_file.file_url})
        incident_row = next(row for row in api.room_incident_page(second_prop.name,
            room=work_room)["rows"]
            if row["name"] == incident["incident"])
        assert incident_row["evidence"] == incident_file.file_url
        try:
            api.execute(prop.name, "incident", "work-incident-wrong-property-" + suffix,
                incident_data)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Una novedad aceptó una habitación de otro establecimiento")
        api.execute(second_prop.name, "incident", "work-incident-resolve-" + suffix,
            {"incident": incident["incident"], "modified": str(incident_row["modified"]),
             "resolve": True, "resolution": "Entregado y documentado por Gerencia"})
        assert not any(row["name"] == incident["incident"] for row in
            api.room_incident_page(second_prop.name, room=work_room)["rows"])
        resolved = next(row for row in api.room_incident_page(second_prop.name,
            status="Resolved", room=work_room)["rows"]
            if row["name"] == incident["incident"])
        assert resolved["resolution"] == "Entregado y documentado por Gerencia"
        assert resolved["evidence"] == incident_file.file_url and resolved["resolved_at"]
        frappe.delete_doc("File", incident_file.name, ignore_permissions=True)
        block_start = (now_local(second_prop) + timedelta(days=60)).replace(
            hour=10, minute=0, second=0, microsecond=0, tzinfo=None)
        block_data = dict(room=work_room, reason="Owner",
            starts_at=block_start.isoformat(timespec="minutes"),
            ends_at=(block_start + timedelta(hours=2)).isoformat(timespec="minutes"),
            note="Uso de prueba")
        blocked = api.execute(second_prop.name, "room_block", "work-block-" + suffix,
            block_data)
        assert api.execute(second_prop.name, "room_block", "work-block-" + suffix,
            block_data) == blocked
        assert any(row["name"] == blocked["block"] for row in
                   api.pms_room_operations(second_prop.name)["room_blocks"])
        try:
            api.execute(second_prop.name, "room_block", "work-overlap-" + suffix,
                {**block_data, "reason": "VIP Hold"})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió un segundo bloqueo superpuesto")
        api.execute(second_prop.name, "room_unblock", "work-unblock-" + suffix,
            dict(block=blocked["block"], modified=blocked["modified"],
                 reason="Fin de la retención de prueba"))
        assert not any(row["name"] == blocked["block"] for row in
                       api.pms_room_operations(second_prop.name)["room_blocks"])
        cleaning = api.execute(second_prop.name, "schedule_cleaning", "work-clean-" + suffix,
            dict(room=work_room, kind="Deep", priority="High", notes="Limpieza de prueba"))
        task = next(row for row in api.pms_room_operations(second_prop.name)["tasks"]
                    if row["name"] == cleaning["task"])
        assert set(task["checklist"]) == {"baño", "cama", "minibar", "superficies"}
        api.execute(second_prop.name, "cleaning", "work-clean-start-" + suffix,
            dict(task=task["name"], modified=str(task["modified"]), status="In Progress"))
        task = next(row for row in api.pms_room_operations(second_prop.name)["tasks"]
                    if row["name"] == cleaning["task"])
        checklist = {key: True for key in task["checklist"]}
        api.execute(second_prop.name, "cleaning", "work-clean-review-" + suffix,
            dict(task=task["name"], modified=str(task["modified"]),
                 status="Inspection", checklist=checklist))
        task = next(row for row in api.pms_room_operations(second_prop.name)["tasks"]
                    if row["name"] == cleaning["task"])
        api.execute(second_prop.name, "cleaning", "work-clean-done-" + suffix,
            dict(task=task["name"], modified=str(task["modified"]),
                 status="Completed", checklist=checklist))
        assert frappe.db.get_value("HS Room", work_room, "cleaning_status") == "Clean"
        order_data = dict(room=work_room, title="Revisión preventiva de prueba",
            kind="Preventive", starts_at=block_start.isoformat(timespec="minutes"),
            ends_at=(block_start + timedelta(hours=1)).isoformat(timespec="minutes"),
            blocks_room=True, until_reopened=False)
        work_order = api.execute(second_prop.name, "maintenance", "work-order-" + suffix,
            order_data)
        order = next(row for row in api.pms_room_operations(second_prop.name)["maintenance"]
                     if row["name"] == work_order["order"])
        parts_before = standalone_inventory.current_balance(second_prop,
            stock_service["item"], stock_service["warehouse"])
        expense_before_parts = Decimal(standalone_accounting.balance(second_prop,
            operating_expense))
        parts_board = api.maintenance_parts_board(second_prop.name, order["name"],
            warehouse=stock_service["warehouse"], search="Agua minibar", page_length=1)
        assert parts_board["total"] == 1 and parts_board["products"][0]["name"] == stock_service["item"]
        try:
            api.maintenance_parts_board(prop.name, order["name"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Se consultaron repuestos de otro establecimiento")
        try:
            api.execute(second_prop.name, "maintenance_parts",
                "work-parts-atomic-" + suffix,
                {"order": order["name"], "modified": parts_board["modified"],
                 "warehouse": stock_service["warehouse"], "parts": [
                    {"item": stock_service["item"], "quantity": "1"},
                    {"item": stock_service["item"], "quantity": "-1"}]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aceptó un lote de repuestos con línea inválida")
        assert standalone_inventory.current_balance(second_prop,
            stock_service["item"], stock_service["warehouse"]) == parts_before
        assert not api.maintenance_parts_board(second_prop.name, order["name"])["parts"]
        issue_parts_data = {"order": order["name"], "modified": parts_board["modified"],
            "warehouse": stock_service["warehouse"],
            "parts": [{"item": stock_service["item"], "quantity": "1"}]}
        issued_parts = api.execute(second_prop.name, "maintenance_parts",
            "work-parts-issue-" + suffix, issue_parts_data)
        assert api.execute(second_prop.name, "maintenance_parts",
            "work-parts-issue-" + suffix, issue_parts_data) == issued_parts
        part_cost = Decimal(issued_parts["cost"])
        assert part_cost > 0
        assert standalone_inventory.current_balance(second_prop,
            stock_service["item"], stock_service["warehouse"]) == (
                parts_before[0] - 1, parts_before[1] - part_cost)
        assert Decimal(standalone_accounting.balance(second_prop,
            operating_expense)) == expense_before_parts + part_cost
        assert api.maintenance_parts_board(second_prop.name, order["name"])["parts"][0]["stock_entry"] == issued_parts["stock_entry"]
        assert any(blocker["code"] == "open_pms_maintenance_parts_at_cutover" and
            blocker["source"] == order["name"] for blocker in
            api.pms_cutover_preflight()["blockers"])
        try:
            api.execute(second_prop.name, "maintenance_parts", "work-parts-stale-" + suffix,
                {"order": order["name"], "modified": parts_board["modified"],
                 "return_entry": issued_parts["stock_entry"],
                 "reason": "Versión antigua"})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se devolvió un repuesto con versión antigua")
        returned_parts_data = {"order": order["name"],
            "modified": issued_parts["modified"],
            "return_entry": issued_parts["stock_entry"],
            "reason": "Repuesto no utilizado"}
        returned_parts = api.execute(second_prop.name, "maintenance_parts",
            "work-parts-return-" + suffix, returned_parts_data)
        assert api.execute(second_prop.name, "maintenance_parts",
            "work-parts-return-" + suffix, returned_parts_data) == returned_parts
        assert Decimal(returned_parts["cost"]) == 0
        assert standalone_inventory.current_balance(second_prop,
            stock_service["item"], stock_service["warehouse"]) == parts_before
        assert Decimal(standalone_accounting.balance(second_prop,
            operating_expense)) == expense_before_parts
        assert api.maintenance_parts_board(second_prop.name, order["name"])["parts"][0]["status"] == "Returned"
        assert not any(blocker["code"] == "open_pms_maintenance_parts_at_cutover" and
            blocker["source"] == order["name"] for blocker in
            api.pms_cutover_preflight()["blockers"])
        try:
            api.execute(second_prop.name, "maintenance_parts", "work-parts-again-" + suffix,
                {**returned_parts_data, "modified": returned_parts["modified"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se devolvió dos veces el mismo repuesto")
        order = next(row for row in api.pms_room_operations(second_prop.name)["maintenance"]
                     if row["name"] == work_order["order"])
        order_file = frappe.get_doc({"doctype": "File",
            "file_name": "maintenance-" + suffix + ".txt",
            "content": ("Prueba de mantenimiento " + suffix).encode(),
            "is_private": 1, "attached_to_doctype": "HS Maintenance Order",
            "attached_to_name": order["name"]}).insert(ignore_permissions=True)
        api.execute(second_prop.name, "maintenance", "work-order-evidence-" + suffix,
            dict(order=order["name"], modified=str(order["modified"]),
                 evidence=order_file.file_url))
        order = next(row for row in api.pms_room_operations(second_prop.name)["maintenance"]
                     if row["name"] == work_order["order"])
        assert order["evidence"] == order_file.file_url
        api.execute(second_prop.name, "maintenance", "work-order-start-" + suffix,
            dict(order=order["name"], modified=str(order["modified"]), status="In Progress"))
        order = next(row for row in api.pms_room_operations(second_prop.name)["maintenance"]
                     if row["name"] == work_order["order"])
        api.execute(second_prop.name, "maintenance", "work-order-done-" + suffix,
            dict(order=order["name"], modified=str(order["modified"]), status="Completed"))
        frappe.delete_doc("File", order_file.name, ignore_permissions=True)
        assert frappe.db.get_value("HS Room", work_room, "cleaning_status") == "Dirty"
        assert any(row["room"] == work_room and row["kind"] == "Deep" for row in
                   api.pms_room_operations(second_prop.name)["tasks"])
        second_stock_account = api.execute(second_prop.name, "pms_account",
            "purchase-second-asset-" + suffix,
            dict(account_code="1160" + suffix, account_name="Inventario adicional",
                 root_type="Asset"))["account"]
        def add_second_purchase_product(locked):
            return insert("HS Product", locked, organization=org.name,
                product_code="EXTRA" + suffix, product_name="Producto de segunda línea",
                product_type="Stock", inventory_account=second_stock_account,
                expense_account=operating_expense, income_account=income,
                tax_profile=profile, sales_rate="20.00", active=1).name
        second_purchase_product = command(second_prop.name, "setup",
            "purchase-second-product-" + suffix,
            {"operation": "smoke_second_purchase_product"}, add_second_purchase_product)
        multi_data = dict(supplier=supplier, supplier_reference="MULTI-" + suffix,
            invoice_currency="USD", payable_account=payable, tax_account=input_tax,
            notes="Dos artículos en una factura", lines=[
                dict(product=stock_service["item"], warehouse=stock_service["warehouse"],
                     quantity="2", invoice_amount="1.00", recoverable_tax="0.10"),
                dict(product=second_purchase_product, warehouse=stock_service["warehouse"],
                     quantity="3", invoice_amount="2.00", recoverable_tax="0.20")])
        multi_quote = api.pms_purchase_quote(second_prop.name, multi_data)
        assert len(multi_quote["lines"]) == 2
        assert (multi_quote["invoice_amount"], multi_quote["base_amount"],
                multi_quote["base_cost"], multi_quote["base_tax"]) == (
                    "3.00", "109.50", "98.55", "10.95")
        rounding_quote = api.pms_purchase_quote(second_prop.name, {
            **multi_data, "supplier_reference": "ROUND-" + suffix,
            "tax_account": None, "lines": [
                {**multi_data["lines"][0], "invoice_amount": "0.01",
                 "recoverable_tax": "0"},
                {**multi_data["lines"][1], "invoice_amount": "0.01",
                 "recoverable_tax": "0"}]})
        assert rounding_quote["base_amount"] == "0.73"
        assert [line["base_amount"] for line in rounding_quote["lines"]] == ["0.37", "0.36"]
        try:
            api.pms_purchase_quote(second_prop.name, {**multi_data, "lines": [
                multi_data["lines"][0], multi_data["lines"][0]]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La compra aceptó dos líneas del mismo producto y almacén")
        payable_before = Decimal(standalone_accounting.balance(second_prop, payable))
        multi_command = {**multi_data, "acceptance": multi_quote["acceptance"]}
        multi_purchase = api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-multiline-" + suffix, multi_command)
        assert api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-multiline-" + suffix, multi_command) == multi_purchase
        assert len(multi_purchase["stock_movements"]) == 2
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before - Decimal("109.50")
        multi_doc = frappe.get_doc("HS PMS Purchase", multi_purchase["purchase"])
        assert len(multi_doc.lines) == 2
        assert {row.inventory_account for row in multi_doc.lines} == {stock_asset, second_stock_account}
        assert {row.stock_movement for row in multi_doc.lines} == set(multi_purchase["stock_movements"])
        purchase_page = api.pms_purchase_document_page(second_prop.name,
            kind="Purchase", search=multi_data["supplier_reference"])
        assert len(purchase_page["rows"]) == 1
        assert purchase_page["rows"][0]["name"] == multi_doc.name
        assert purchase_page["rows"][0]["can_cancel"]
        assert {row["stock_movement"] for row in purchase_page["rows"][0]["lines"]} == set(multi_purchase["stock_movements"])
        first_purchase_page = api.pms_purchase_document_page(second_prop.name,
            kind="Purchase", page_length=1)
        next_purchase_page = api.pms_purchase_document_page(second_prop.name,
            kind="Purchase", offset=1, page_length=1)
        assert first_purchase_page["has_more"]
        assert len(first_purchase_page["rows"]) == len(next_purchase_page["rows"]) == 1
        assert first_purchase_page["rows"][0]["name"] != next_purchase_page["rows"][0]["name"]
        assert not api.pms_purchase_document_page(prop.name, kind="Purchase",
            search=multi_data["supplier_reference"])["rows"]
        frappe.set_user("Guest")
        try:
            try:
                api.pms_purchase_document_page(second_prop.name, kind="Purchase")
            except frappe.PermissionError:
                frappe.clear_messages()
            else:
                raise AssertionError("Un visitante consultó compras privadas")
        finally:
            frappe.set_user("Administrator")
        assert standalone_inventory.current_balance(second_prop, second_purchase_product,
            stock_service["warehouse"]) == (Decimal("3"), Decimal("65.70"))
        assert any(row["name"] == multi_doc.name and len(row["lines"]) == 2 and
                   row["outstanding"] == "109.50" for row in
                   api.pms_purchase_snapshot(second_prop.name)["purchases"])
        for part, remaining in (("1.00", "73.00"), ("2.00", "0.00")):
            multi_payment_data = dict(purchase=multi_doc.name, method=bank_method,
                amount=part, reference="MULTI-PAY-" + part + suffix,
                reason="Abono de factura con varias líneas")
            multi_payment_quote = api.pms_supplier_payment_quote(second_prop.name,
                multi_payment_data)
            result = api.execute(second_prop.name, "pms_pay_supplier",
                "purchase-multiline-payment-" + part + suffix,
                {**multi_payment_data, "acceptance": multi_payment_quote["acceptance"]})
            assert result["outstanding"] == remaining
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        unpaid_data = dict(supplier=supplier, supplier_reference="RETURN-UNPAID-" + suffix,
            product=second_purchase_product, warehouse=stock_service["warehouse"],
            quantity="1", invoice_currency="USD", invoice_amount="1.00",
            recoverable_tax="0", payable_account=payable, tax_account=None,
            notes="Prueba de devolución sin pagar")
        unpaid_quote = api.pms_purchase_quote(second_prop.name, unpaid_data)
        unpaid = api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-unpaid-return-" + suffix,
            {**unpaid_data, "acceptance": unpaid_quote["acceptance"]})
        def deactivate_return_product(locked):
            item = frappe.get_doc("HS Product", second_purchase_product, for_update=True)
            item.active = 0
            item.save()
            return item.name
        command(second_prop.name, "setup", "deactivate-return-product-" + suffix,
            {"operation": "smoke_inactive_return_product"}, deactivate_return_product)
        unpaid_return_data = dict(purchase=unpaid["purchase"],
            reference="RETURN-OPEN-" + suffix,
            reason="Producto no conforme", variance_account=None,
            lines=[dict(source_movement=unpaid["stock_movement"], quantity="1")])
        unpaid_return_quote = api.pms_purchase_return_quote(second_prop.name,
            unpaid_return_data)
        assert unpaid_return_quote["variance_nature"] == "Income"
        assert not unpaid_return_quote["acceptance"]
        unpaid_return_data["variance_account"] = income
        unpaid_return_quote = api.pms_purchase_return_quote(second_prop.name,
            unpaid_return_data)
        assert (unpaid_return_quote["payable_applied"],
                unpaid_return_quote["supplier_credit"]) == ("36.50", "0.00")
        unpaid_return = api.execute(second_prop.name, "pms_return_purchase",
            "purchase-return-open-" + suffix,
            {**unpaid_return_data, "acceptance": unpaid_return_quote["acceptance"]})
        assert unpaid_return["outstanding"] == "0.00"
        assert unpaid_return["adjustment_journal"]
        try:
            api.execute(second_prop.name, "pms_reverse_journal",
                "reverse-purchase-return-" + suffix,
                dict(journal=unpaid_return["adjustment_journal"],
                     reason="La devolución conserva saldos vinculados"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revirtió directamente el ajuste de una devolución de compra")
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        paid_return_data = dict(purchase=multi_doc.name,
            reference="RETURN-PAID-" + suffix, reason="Devolución parcial de factura pagada",
            variance_account=None,
            lines=[dict(source_movement=multi_doc.lines[0].stock_movement, quantity="1")])
        paid_return_quote = api.pms_purchase_return_quote(second_prop.name,
            paid_return_data)
        if paid_return_quote["variance_nature"]:
            paid_return_data["variance_account"] = (
                income if paid_return_quote["variance_nature"] == "Income"
                else operating_expense)
            paid_return_quote = api.pms_purchase_return_quote(second_prop.name,
                paid_return_data)
        assert paid_return_quote["supplier_credit"] == "18.25"
        paid_return_command = {**paid_return_data,
            "acceptance": paid_return_quote["acceptance"]}
        paid_return = api.execute(second_prop.name, "pms_return_purchase",
            "purchase-return-paid-" + suffix, paid_return_command)
        assert api.execute(second_prop.name, "pms_return_purchase",
            "purchase-return-paid-" + suffix, paid_return_command) == paid_return
        assert paid_return["supplier_credit"] == "18.25"
        assert any(row["name"] == paid_return["return"] and
                   row["refund_available"] == "18.25" for row in
                   api.pms_purchase_snapshot(second_prop.name)["returns"])
        return_page = api.pms_purchase_document_page(second_prop.name,
            kind="Return", search=paid_return_data["reference"],
            available_only=1)
        assert len(return_page["rows"]) == 1
        assert return_page["rows"][0]["name"] == paid_return["return"]
        assert return_page["rows"][0]["refund_available"] == "18.25"
        try:
            api.pms_purchase_return_quote(second_prop.name, {**paid_return_data,
                "reference": "RETURN-OVER-" + suffix,
                "lines": [dict(source_movement=multi_doc.lines[0].stock_movement,
                               quantity="2")]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("La devolución superó la cantidad recibida")
        refund_data = {"return": paid_return["return"], "method": bank_method,
            "amount": "0.50", "reference": "RETURN-REFUND-" + suffix,
            "reason": "Proveedor reintegró el crédito"}
        refund_quote = api.pms_supplier_refund_quote(second_prop.name, refund_data)
        refund_command = {**refund_data, "acceptance": refund_quote["acceptance"]}
        refunded = api.execute(second_prop.name, "pms_supplier_refund",
            "purchase-supplier-refund-" + suffix, refund_command)
        assert refunded["available"] == "0.00"
        assert not api.pms_purchase_document_page(second_prop.name,
            kind="Return", search=paid_return_data["reference"],
            available_only=1)["rows"]
        assert api.execute(second_prop.name, "pms_supplier_refund",
            "purchase-supplier-refund-" + suffix, refund_command) == refunded
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        assert any(row["kind"] == "Supplier Refund" and
                   row["pms_purchase_return"] == paid_return["return"] for row in
                   api.pms_purchase_snapshot(second_prop.name)["payments"])
        try:
            api.pms_supplier_refund_quote(second_prop.name,
                {**refund_data, "reference": "RETURN-OVERPAY-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió reintegrar dos veces el crédito del proveedor")
        try:
            api.pms_purchase_return_quote(prop.name, paid_return_data)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se consultó una devolución de otro establecimiento")
        from hospitality_suite import standalone_closing
        return_close = standalone_closing.build(frappe.get_doc("HS Property", second_prop.name))
        assert any(row["name"] == paid_return["return"] for row in
                   return_close["sources"]["supplier_returns"])
        assert any(row["kind"] == "Supplier Refund" for row in
                   return_close["breakdown"]["other_cash"])
        try:
            api.pms_purchase_cancel_quote(second_prop.name, dict(
                purchase=multi_doc.name, reference="CANCEL-PAID-" + suffix,
                reason="No se puede cancelar una compra pagada", variance_account=None,
                lines=[dict(source_movement=line.stock_movement, quantity=str(line.quantity))
                       for line in multi_doc.lines]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió cancelar una compra pagada")
        def add_cancel_product(locked):
            return insert("HS Product", locked, organization=org.name,
                product_code="CANCEL" + suffix, product_name="Producto de cancelación",
                product_type="Stock", inventory_account=second_stock_account,
                expense_account=operating_expense, income_account=income,
                tax_profile=profile, sales_rate="20.00", active=1).name
        cancel_product = command(second_prop.name, "setup", "cancel-product-" + suffix,
            {"operation": "smoke_cancel_purchase_product"}, add_cancel_product)
        cancel_data = dict(supplier=supplier, supplier_reference="BILL-CANCEL-" + suffix,
            invoice_currency="USD", payable_account=payable, tax_account=input_tax,
            notes="Factura que se anulará", lines=[
                dict(product=stock_service["item"], warehouse=stock_service["warehouse"],
                     quantity="1", invoice_amount="1.00", recoverable_tax="0.10"),
                dict(product=cancel_product, warehouse=stock_service["warehouse"],
                     quantity="2", invoice_amount="2.00", recoverable_tax="0.20")])
        cancel_purchase_quote = api.pms_purchase_quote(second_prop.name, cancel_data)
        to_cancel = api.execute(second_prop.name, "pms_receive_purchase",
            "purchase-to-cancel-" + suffix,
            {**cancel_data, "acceptance": cancel_purchase_quote["acceptance"]})
        cancellation_doc = frappe.get_doc("HS PMS Purchase", to_cancel["purchase"])
        cancel_request = dict(purchase=cancellation_doc.name,
            reference="CANCEL-" + suffix, reason="Factura registrada por error",
            variance_account=None,
            lines=[dict(source_movement=line.stock_movement, quantity=str(line.quantity))
                   for line in cancellation_doc.lines])
        cancel_review = api.pms_purchase_cancel_quote(second_prop.name, cancel_request)
        if cancel_review["variance_nature"]:
            cancel_request["variance_account"] = (
                income if cancel_review["variance_nature"] == "Income"
                else operating_expense)
            cancel_review = api.pms_purchase_cancel_quote(second_prop.name, cancel_request)
        cancel_command = {**cancel_request, "acceptance": cancel_review["acceptance"]}
        cancelled_purchase = api.execute(second_prop.name, "pms_cancel_purchase",
            "cancel-purchase-" + suffix, cancel_command)
        assert api.execute(second_prop.name, "pms_cancel_purchase",
            "cancel-purchase-" + suffix, cancel_command) == cancelled_purchase
        assert cancelled_purchase["status"] == "Cancelled"
        assert frappe.db.get_value("HS PMS Purchase", cancellation_doc.name,
                                   "cancellation_return") == cancelled_purchase["return"]
        assert standalone_inventory.current_balance(second_prop, cancel_product,
            stock_service["warehouse"]) == (Decimal(0), Decimal("0.00"))
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        assert any(row["name"] == cancellation_doc.name and row["status"] == "Cancelled"
                   and row["outstanding"] == "0.00" for row in
                   api.pms_purchase_snapshot(second_prop.name)["purchases"])
        assert any(row["name"] == cancelled_purchase["return"] and
                   row["kind"] == "Full Cancellation" and
                   row["refund_available"] == "0.00" for row in
                   api.pms_purchase_snapshot(second_prop.name)["returns"])
        try:
            api.execute(second_prop.name, "pms_cancel_purchase",
                "cancel-purchase-twice-" + suffix, cancel_command)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló dos veces una compra")
        billed_pass_quote = api.preview(second_prop.name, pass_data, "day_pass_no_room")
        billed_pass = api.execute(second_prop.name, "day_pass_no_room",
            "day-pass-billed-" + suffix,
            {**pass_data, "acceptance": billed_pass_quote["acceptance"]})
        billed_pass_doc = frappe.get_doc("HS Day Pass", billed_pass["day_pass"])
        pass_invoice_data = dict(series=invoice_series,
                                 receivables=[billed_pass["receivable"]])
        pass_invoice_quote = api.pms_invoice_quote(second_prop.name, pass_invoice_data)
        pass_invoice = api.execute(second_prop.name, "pms_issue_invoice",
            "day-pass-invoice-" + suffix,
            {**pass_invoice_data, "acceptance": pass_invoice_quote["acceptance"]})
        billed_inventory = pms_cutover._active_day_passes(second_prop, [])
        billed_source = next(row for row in billed_inventory
            if row["name"] == billed_pass_doc.name)
        assert billed_source["source_fiscal"]["invoice"]["document"] == \
            pass_invoice["document"]
        assert billed_source["source_fiscal"]["credited_amount"] == "0"
        assert billed_source["source_settlements"]["allocated_amount"] == "0"
        try:
            api.execute(second_prop.name, "pms_day_pass_cancel",
                "day-pass-billed-cancel-early-" + suffix,
                dict(day_pass=billed_pass_doc.name, modified=str(billed_pass_doc.modified),
                     reason="Factura todavía vigente"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se canceló Day Pass facturado sin nota de crédito")
        pass_credit_data = dict(invoice=pass_invoice["document"], series=credit_series)
        pass_credit_quote = api.pms_credit_quote(second_prop.name, pass_credit_data)
        api.execute(second_prop.name, "pms_issue_credit_note",
            "day-pass-credit-" + suffix,
            {**pass_credit_data, "acceptance": pass_credit_quote["acceptance"],
             "reason": "Anulación de acceso Day Pass"})
        credited_inventory = pms_cutover._active_day_passes(second_prop, [])
        credited_source = next(row for row in credited_inventory
            if row["name"] == billed_pass_doc.name)
        assert credited_source["source_fiscal"]["credited_amount"] == "80"
        assert credited_source["source_settlements"]["allocated_amount"] == "0"
        api.execute(second_prop.name, "pms_day_pass_cancel",
            "day-pass-billed-cancel-" + suffix,
            dict(day_pass=billed_pass_doc.name, modified=str(billed_pass_doc.modified),
                 reason="Acceso acreditado íntegramente"))
        assert frappe.db.get_value("HS Day Pass", billed_pass_doc.name,
                                   "status") == "Cancelled"
        assert pms_credited(second_prop, billed_pass["receivable"]) == Decimal("80.00")
        paid_pass_quote = api.preview(second_prop.name, pass_data, "day_pass_no_room")
        paid_pass = api.execute(second_prop.name, "day_pass_no_room",
            "day-pass-paid-" + suffix,
            {**pass_data, "acceptance": paid_pass_quote["acceptance"]})
        pass_payment = api.execute(second_prop.name, "pms_cash_movement",
            "day-pass-bank-payment-" + suffix,
            dict(kind="Payment", amount="1", method=bank_method,
                 receivable=paid_pass["receivable"],
                 reference="DAY-PASS-PAY-" + suffix,
                 reason="Cobro parcial de Day Pass"))
        paid_inventory_blockers = []
        paid_inventory = pms_cutover._active_day_passes(
            second_prop, paid_inventory_blockers)
        paid_source = next(row for row in paid_inventory
            if row["name"] == paid_pass["day_pass"])
        assert Decimal(paid_source["source_settlements"]["allocated_amount"]) == \
            Decimal(pass_payment["base_amount"])
        assert paid_source["source_settlements"]["allocations"][0][
            "payment_currency"] == "USD"
        assert Decimal(paid_source["source_financial"]["outstanding_amount"]) == \
            Decimal("80") - Decimal(pass_payment["base_amount"])
        assert not any(row["code"].startswith("invalid_active_pms_day_pass")
                       for row in paid_inventory_blockers)
        pass_refund_data = dict(source_payment=pass_payment["payment"],
            amount="0.25", reference="DAY-PASS-REFUND-" + suffix,
            reason="Devolución parcial de cobro Day Pass")
        pass_refund_quote = api.pms_refund_preview(
            second_prop.name, pass_refund_data)
        pass_refund = api.execute(second_prop.name, "pms_refund",
            "day-pass-bank-refund-" + suffix,
            {**pass_refund_data,
             "expected_base_amount": pass_refund_quote["base_amount"],
             "expected_debit": pass_refund_quote["debit"],
             "expected_credit": pass_refund_quote["credit"]})
        refunded_inventory = pms_cutover._active_day_passes(second_prop, [])
        refunded_source = next(row for row in refunded_inventory
            if row["name"] == paid_pass["day_pass"])
        assert Decimal(refunded_source["source_settlements"][
            "allocated_amount"]) == (Decimal(pass_payment["base_amount"]) -
                                   Decimal(pass_refund["base_amount"]))
        assert {row["payment"] for row in refunded_source[
            "source_settlements"]["allocations"]} == {
                pass_payment["payment"], pass_refund["payment"]}
        order_data = dict(supplier=supplier, reference="PO-" + suffix,
            currency="USD", payable_account=payable, tax_account=input_tax,
            lines=[dict(product=stock_service["item"],
                warehouse=stock_service["warehouse"], quantity="3",
                amount="3.00", recoverable_tax="0.30")])
        order_review = api.pms_order_quote(second_prop.name, order_data)
        assert order_review["amount"] == "3.00" and order_review["recoverable_tax"] == "0.30"
        order_command = {**order_data, "acceptance": order_review["acceptance"]}
        order_result = api.execute(second_prop.name, "pms_order_request",
            "order-request-" + suffix, order_command)
        assert api.execute(second_prop.name, "pms_order_request",
            "order-request-" + suffix, order_command) == order_result
        assert order_result["status"] == "Pending"
        order_name = order_result["order"]
        try:
            api.execute(second_prop.name, "pms_order_approve", "self-order-" + suffix,
                dict(order=order_name, modified=order_result["modified"]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se autoaprobó una orden")
        try:
            frappe.set_user(approver)
            approved_order = api.execute(second_prop.name, "pms_order_approve",
                "approve-order-" + suffix,
                dict(order=order_name, modified=order_result["modified"]))
        finally:
            frappe.set_user("Administrator")
        assert approved_order["status"] == "Approved"
        assert not frappe.db.exists("HS Journal", {"property": second_prop.name,
            "source_doctype": "HS PMS Purchase Order", "source_name": order_name})
        order_line = next(row for row in api.pms_purchase_snapshot(second_prop.name)["orders"]
            if row["name"] == order_name)["lines"][0]["name"]

        def ordered_receipt(ref, qty, key):
            data = dict(purchase_order=order_name, supplier=supplier,
                supplier_reference=ref, invoice_currency="USD",
                payable_account=payable, tax_account=input_tax,
                lines=[dict(order_line=order_line, product=stock_service["item"],
                    warehouse=stock_service["warehouse"], quantity=qty)])
            review = api.pms_purchase_quote(second_prop.name, data)
            result = api.execute(second_prop.name, "pms_receive_purchase", key,
                {**data, "acceptance": review["acceptance"]})
            return result, review

        stale_data = dict(purchase_order=order_name, supplier=supplier,
            supplier_reference="PO-STALE-" + suffix, invoice_currency="USD",
            payable_account=payable, tax_account=input_tax,
            lines=[dict(order_line=order_line, product=stock_service["item"],
                warehouse=stock_service["warehouse"], quantity="1")])
        stale_review = api.pms_purchase_quote(second_prop.name, stale_data)
        first_order_receipt, first_order_review = ordered_receipt(
            "PO-BILL-1-" + suffix, "1", "order-receipt-1-" + suffix)
        try:
            api.execute(second_prop.name, "pms_receive_purchase",
                "stale-order-receipt-" + suffix,
                {**stale_data, "acceptance": stale_review["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Una cotización anterior ignoró el saldo recibido de la orden")
        second_order_receipt, second_order_review = ordered_receipt(
            "PO-BILL-2-" + suffix, "1", "order-receipt-2-" + suffix)
        assert first_order_receipt["purchase"] != second_order_receipt["purchase"]
        assert first_order_review["invoice_amount"] == "1.00"
        assert second_order_review["invoice_amount"] == "1.00"
        assert frappe.db.get_value("HS PMS Purchase", first_order_receipt["purchase"],
            "purchase_order") == order_name
        try:
            api.pms_purchase_quote(second_prop.name, dict(
                purchase_order=order_name, supplier=supplier,
                supplier_reference="PO-EXCESS-" + suffix, invoice_currency="USD",
                payable_account=payable, tax_account=input_tax,
                lines=[dict(order_line=order_line, product=stock_service["item"],
                    warehouse=stock_service["warehouse"], quantity="2")]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió recibir más de lo ordenado")
        first_order_doc = frappe.get_doc("HS PMS Purchase", first_order_receipt["purchase"])
        order_cancel_data = dict(purchase=first_order_doc.name,
            reference="PO-CANCEL-" + suffix,
            reason="Factura de recepción anulada por el proveedor",
            variance_account=None,
            lines=[dict(source_movement=line.stock_movement,
                quantity=str(line.quantity)) for line in first_order_doc.lines])
        order_cancel_review = api.pms_purchase_cancel_quote(second_prop.name,
            order_cancel_data)
        if order_cancel_review["variance_nature"]:
            order_cancel_data["variance_account"] = (
                income if order_cancel_review["variance_nature"] == "Income"
                else operating_expense)
            order_cancel_review = api.pms_purchase_cancel_quote(second_prop.name,
                order_cancel_data)
        api.execute(second_prop.name, "pms_cancel_purchase",
            "order-cancel-receipt-" + suffix,
            {**order_cancel_data, "acceptance": order_cancel_review["acceptance"]})
        reopened = next(row for row in api.pms_purchase_snapshot(second_prop.name)["orders"]
            if row["name"] == order_name)
        assert Decimal(reopened["lines"][0]["received_quantity"]) == 1
        assert Decimal(reopened["lines"][0]["remaining_quantity"]) == 2
        final_order_receipt, final_order_review = ordered_receipt(
            "PO-BILL-3-" + suffix, "2", "order-receipt-3-" + suffix)
        assert final_order_review["invoice_amount"] == "2.00"
        assert supplier_outstanding(second_prop, final_order_receipt["purchase"]) == Decimal("73.00")
        completed = next(row for row in api.pms_purchase_snapshot(second_prop.name)["orders"]
            if row["name"] == order_name)
        assert completed["progress"] == "Completed"
        closed_order = api.execute(second_prop.name, "pms_order_close",
            "order-close-" + suffix,
            dict(order=order_name, modified=str(completed["modified"]),
                 reason="Recepción de la orden completada"))
        assert closed_order["status"] == "Closed"
        try:
            api.pms_purchase_quote(second_prop.name, dict(
                purchase_order=order_name, supplier=supplier,
                supplier_reference="PO-LATE-" + suffix, invoice_currency="USD",
                payable_account=payable, tax_account=input_tax,
                lines=[dict(order_line=order_line, product=stock_service["item"],
                    warehouse=stock_service["warehouse"], quantity="1")]))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió recibir una orden cerrada")
        laundry_rate = api.execute(second_prop.name, "laundry_rate",
            "pms-laundry-rate-" + suffix,
            dict(garment="Camisa", service_type="Wash & Iron",
                 pms_product=taxed_product, rate="10.00", express_rate="15.00"))["rate"]
        laundry_board = api.pms_laundry_snapshot(second_prop.name)
        assert any(row["name"] == laundry_rate and row["pms_product"] == taxed_product
                   for row in laundry_board["rates"])
        laundry_request = dict(stay=fixture["stay"], folio=fixture["folio"],
                               express=1, notes="Servicio exprés de prueba")
        pickup = api.execute(second_prop.name, "laundry_request",
            "pms-laundry-pickup-" + suffix, laundry_request)
        assert api.execute(second_prop.name, "laundry_request",
            "pms-laundry-pickup-" + suffix, laundry_request) == pickup
        laundry_order = pickup["order"]
        collected_laundry = api.execute(second_prop.name, "laundry_collect",
            "pms-laundry-collect-" + suffix,
            dict(order=laundry_order,
                 modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified")),
                 items=[dict(rate=laundry_rate, quantity=2)]))
        assert Decimal(collected_laundry["total"]) == 30
        assert frappe.db.get_value("HS Laundry Order Item",
            {"parent": laundry_order}, "pms_product") == taxed_product
        process_laundry = api.execute(second_prop.name, "laundry_advance",
            "pms-laundry-process-" + suffix,
            dict(order=laundry_order,
                 modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified")),
                 status="In Process"))
        ready_laundry = api.execute(second_prop.name, "laundry_advance",
            "pms-laundry-ready-" + suffix,
            dict(order=laundry_order,
                 modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified")),
                 status="Ready"))
        assert process_laundry["status"] == "In Process" and ready_laundry["status"] == "Ready"
        try:
            api.execute(second_prop.name, "laundry_deliver",
                "pms-laundry-uncounted-" + suffix,
                dict(order=laundry_order,
                     modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified"))))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se entregó lavandería sin arqueo de prendas")
        laundry_line = frappe.db.get_value("HS Laundry Order Item",
            {"parent": laundry_order}, "name")
        api.execute(second_prop.name, "laundry_return",
            "pms-laundry-count-" + suffix,
            dict(order=laundry_order,
                 modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified")),
                 counts={laundry_line: 1}))
        try:
            api.execute(second_prop.name, "laundry_deliver",
                "pms-laundry-shortage-unexplained-" + suffix,
                dict(order=laundry_order,
                     modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified"))))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se entregó lavandería faltante sin explicación")
        delivered_laundry_data = dict(order=laundry_order,
            modified=str(frappe.db.get_value("HS Laundry Order", laundry_order, "modified")),
            shortage_note="Una camisa no fue devuelta")
        delivered_laundry = api.execute(second_prop.name, "laundry_deliver",
            "pms-laundry-deliver-" + suffix, delivered_laundry_data)
        assert api.execute(second_prop.name, "laundry_deliver",
            "pms-laundry-deliver-" + suffix, delivered_laundry_data) == delivered_laundry
        assert Decimal(delivered_laundry["billed_total"]) == 15
        laundry_charge = frappe.db.get_value("HS Laundry Order Item",
            laundry_line, "charge")
        charge_row = frappe.db.get_value("HS Charge", laundry_charge,
            ["property", "folio", "item", "amount", "status"], as_dict=True)
        assert (charge_row.property, charge_row.folio, charge_row.item,
            Decimal(str(charge_row.amount)), charge_row.status) == (
            second_prop.name, fixture["folio"], taxed_product, Decimal("15"), "Pending")
        laundry_print = frappe.get_print("HS Laundry Order", laundry_order,
            print_format="HS Comprobante de lavandería")
        assert "Camisa" in laundry_print and "15.00" in laundry_print
        laundry_bill_data = dict(folio=fixture["folio"], receivable_account=ar)
        laundry_bill_quote = api.pms_folio_quote(second_prop.name, laundry_bill_data)
        assert laundry_bill_quote["total"] == "17.25"
        laundry_bill = api.execute(second_prop.name, "pms_bill_folio",
            "pms-laundry-bill-" + suffix,
            {**laundry_bill_data, "acceptance": laundry_bill_quote["acceptance"]})
        assert laundry_bill["total"] == "17.25"
        laundry_receivable = frappe.db.get_value("HS Charge", laundry_charge,
            "pms_receivable")
        assert laundry_receivable and Decimal(str(frappe.db.get_value(
            "HS PMS Receivable", laundry_receivable, "tax_amount"))) == Decimal("2.25")
        assert any(row["name"] == laundry_order and row["status"] == "Delivered"
                   for row in api.pms_laundry_snapshot(second_prop.name)["orders"])
        cancelled_laundry = api.execute(second_prop.name, "laundry_request",
            "pms-laundry-cancel-source-" + suffix,
            dict(stay=fixture["stay"], folio=fixture["folio"]))
        api.execute(second_prop.name, "laundry_cancel",
            "pms-laundry-cancel-" + suffix,
            dict(order=cancelled_laundry["order"],
                 modified=str(frappe.db.get_value("HS Laundry Order",
                     cancelled_laundry["order"], "modified")),
                 reason="Solicitud duplicada"))
        assert not frappe.db.exists("HS Charge", {"property": second_prop.name,
            "description": ["like", "%" + cancelled_laundry["order"] + "%"]})
        travel_supplier = api.execute(second_prop.name, "pms_supplier",
            "travel-supplier-" + suffix, dict(party_name="Operador turístico " + suffix))["supplier"]
        travel_agent = api.execute(second_prop.name, "travel_agent",
            "travel-agent-" + suffix, dict(agent_name="Agencia de prueba " + suffix,
                agent_type="Travel Agent", commission_pct="10",
                pms_supplier=travel_supplier))["agent"]
        experience_product = api.save_setup(second_prop.name, "product",
            dict(product_code="EXP" + suffix, product_name="Ruta cultural",
                product_type="Service", income_account=income,
                tax_profile=profile, sales_rate="90.00", active=1),
            "experience-product-" + suffix)["name"]
        experience = api.execute(second_prop.name, "experience",
            "experience-" + suffix, dict(experience_name="Ruta cultural " + suffix,
                experience_category="Tour", pms_product=experience_product,
                duration="2 horas", show_on_booking_page=1))["experience"]
        agency_board = api.pms_travel_experiences_snapshot(second_prop.name)
        assert any(row["name"] == travel_agent and row["pms_supplier"] == travel_supplier
                   for row in agency_board["agents"])
        assert any(row["name"] == experience and row["pms_product"] == experience_product
                   for row in agency_board["experiences"])
        historical = frappe.get_doc(dict(doctype="HS Experience Order",
            company=second_prop.company, property=second_prop.name,
            experience=experience, customer=new_guest["party"],
            pms_product=experience_product, quantity=2, participants=2,
            unit_rate="90.00", amount="180.00", currency=second_prop.currency,
            status="Reserved"))
        historical.db_insert()  # Simulate an order saved before accepted tax fields existed.
        historical_confirmed = api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-historical-confirm-" + suffix,
            dict(order=historical.name, modified=str(historical.modified),
                 status="Confirmed", scheduled_at=(now_local(second_prop) +
                 timedelta(hours=4)).replace(second=0, microsecond=0,
                 tzinfo=None).isoformat(timespec="minutes"), participants=2))
        try:
            api.preview(second_prop.name,
                dict(order=historical.name, receivable_account=ar),
                "pms_direct_experience_delivery")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se entregó una orden histórica sin desglose aprobado")
        historic_data = dict(order=historical.name,
            modified=historical_confirmed["modified"], tax_profile=profile,
            income_account=income, evidence="Comprobante histórico " + suffix)
        historic_review = api.preview(second_prop.name, historic_data,
            "pms_legacy_direct_experience_review")
        assert (historic_review["net_amount"], historic_review["tax_amount"],
                historic_review["total_amount"]) == ("180.00", "27.00", "207.00")
        try:
            api.execute(second_prop.name, "pms_legacy_direct_experience_review",
                "experience-historical-stale-" + suffix,
                {**historic_data, "evidence": "Respaldo distinto " + suffix,
                 "acceptance": historic_review["acceptance"]})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se aprobó un respaldo distinto al revisado")
        historic_command = {**historic_data,
            "acceptance": historic_review["acceptance"]}
        historic_frozen = api.execute(second_prop.name,
            "pms_legacy_direct_experience_review",
            "experience-historical-freeze-" + suffix, historic_command)
        assert api.execute(second_prop.name,
            "pms_legacy_direct_experience_review",
            "experience-historical-freeze-" + suffix,
            historic_command) == historic_frozen
        historical.reload()
        assert (Decimal(str(historical.accepted_net)),
                Decimal(str(historical.accepted_tax)),
                Decimal(str(historical.accepted_total)),
                historical.accepted_tax_profile,
                historical.income_account) == (
                Decimal("180"), Decimal("27"), Decimal("207"), profile, income)
        assert frappe.db.exists("HS Audit Event", {
            "property": second_prop.name, "source_name": historical.name,
            "action": "pms_legacy_direct_experience_reviewed"})
        from hospitality_suite.pms_cutover import _open_operations
        historic_blockers = []
        _open_operations(second_prop, historic_blockers)
        assert not any(row["code"] == "pending_direct_experience_incomplete" and
                       row["source"] == historical.name for row in historic_blockers)
        try:
            api.preview(second_prop.name, historic_data,
                "pms_legacy_direct_experience_review")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revisó dos veces la orden histórica")
        api.execute(second_prop.name, "pms_direct_experience_status",
            "experience-historical-cancel-" + suffix,
            dict(order=historical.name, modified=str(historical.modified),
                 status="Cancelled", reason="Orden histórica de prueba"))
        direct_data = dict(customer=new_guest["party"], experience=experience, quantity=2)
        direct_review = api.preview(second_prop.name, direct_data,
            "pms_direct_experience_order")
        assert direct_review["line"]["total_amount"] == "207.00"
        direct_command = {**direct_data, "acceptance": direct_review["acceptance"]}
        direct_order = api.execute(second_prop.name, "pms_direct_experience_order",
            "experience-direct-" + suffix, direct_command)
        assert api.execute(second_prop.name, "pms_direct_experience_order",
            "experience-direct-" + suffix, direct_command) == direct_order
        assert not frappe.db.get_value("HS Experience Order", direct_order["order"], "booking")
        with operation(second_prop):
            tampered_order = frappe.get_doc("HS Experience Order",
                direct_order["order"])
            tampered_order.accepted_tax = 0
            try:
                tampered_order.save()
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Se modificó el impuesto aceptado de una experiencia")
        assert Decimal(str(frappe.db.get_value("HS Experience Order",
            direct_order["order"], "accepted_tax"))) == Decimal("27")
        try:
            api.preview(prop.name, direct_data, "pms_direct_experience_order")
        except (frappe.ValidationError, frappe.PermissionError):
            pass
        else:
            raise AssertionError("La experiencia directa cruzó establecimientos")
        direct_scheduled = (now_local(second_prop) + timedelta(hours=3)).replace(
            second=0, microsecond=0, tzinfo=None).isoformat(timespec="minutes")
        direct_confirmed = api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-direct-confirm-" + suffix,
            dict(order=direct_order["order"], modified=direct_order["modified"],
                 status="Confirmed", scheduled_at=direct_scheduled, participants=2))
        try:
            api.execute(second_prop.name, "experience_status",
                "experience-direct-service-denied-" + suffix,
                dict(order=direct_order["order"], modified=direct_confirmed["modified"],
                     status="Delivered"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Recepción entregó una venta directa sin control financiero")
        assert any(row["name"] == travel_agent for row in
                   api.pms_reception_snapshot(second_prop.name)["agents"])
        from hospitality_suite.travel_experiences import quote_experiences
        try:
            quote_experiences(prop, [dict(experience=experience, quantity=1)])
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Una experiencia cruzó establecimientos")
        travel_room = command(second_prop.name, "setup", "travel-room-" + suffix,
            {"operation": "smoke_travel_room"}, lambda locked: insert("HS Room", locked,
                room_number="711", category=fixture["category"], active=1,
                cleaning_status="Clean").name)
        travel_start = (now_local(second_prop) - timedelta(minutes=1)).replace(
            second=0, microsecond=0, tzinfo=None)
        travel_data = dict(customer=new_guest["party"], guest=new_guest["guest"],
            starts_at=travel_start.isoformat(timespec="minutes"),
            ends_at=(travel_start + timedelta(days=1)).isoformat(timespec="minutes"),
            mode="Hotel", travel_agent=travel_agent,
            experiences=[dict(experience=experience, quantity=2)],
            rooms=[dict(category=fixture["category"], room=travel_room, people=1)])
        travel_quote = api.preview(second_prop.name, travel_data, "reserve")
        assert travel_quote["experiences_total"] == "207.00"
        assert Decimal(str(travel_quote["agent"]["agent_commission_estimate"])) == Decimal("10.00")
        travel_booking = api.execute(second_prop.name, "reserve", "travel-booking-" + suffix,
            {**travel_data, "acceptance": travel_quote["acceptance"]})
        assert api.execute(second_prop.name, "reserve", "travel-booking-" + suffix,
            {**travel_data, "acceptance": travel_quote["acceptance"]}) == travel_booking
        booked = frappe.get_doc("HS Booking", travel_booking["booking"])
        assert booked.travel_agent == travel_agent and Decimal(str(
            booked.agent_commission_estimate)) == Decimal("10.00")
        travel_order = frappe.get_doc("HS Experience Order", frappe.db.get_value(
            "HS Experience Order", {"booking": booked.name,
                "experience": experience}, "name"))
        assert travel_order.pms_product == experience_product and Decimal(str(
            travel_order.amount)) == Decimal("180.00")
        changed_product = frappe.get_doc("HS Product", experience_product)
        api.save_setup(second_prop.name, "product", {"name": experience_product,
            "sales_rate": "95"}, "travel-price-change-" + suffix,
            expected_modified=str(changed_product.modified))
        travel_order.reload()
        assert Decimal(str(travel_order.unit_rate)) == Decimal("90.00")
        assert frappe.db.get_value("HS Experience Order", direct_order["order"],
                                   "accepted_tax_profile") == profile
        changed_tax_profile = api.execute(second_prop.name, "pms_tax_profile",
            "experience-new-tax-" + suffix,
            dict(label="Impuesto posterior a la reserva", treatment="Taxable",
                 rate="20", included_in_price=0,
                 liability_account=tax_account))["profile"]
        changed_product = frappe.get_doc("HS Product", experience_product)
        api.save_setup(second_prop.name, "product",
            {"name": experience_product, "tax_profile": changed_tax_profile},
            "experience-tax-change-" + suffix,
            expected_modified=str(changed_product.modified))
        direct_delivery_data = dict(order=direct_order["order"], receivable_account=ar)
        direct_delivery_review = api.preview(second_prop.name, direct_delivery_data,
            "pms_direct_experience_delivery")
        assert direct_delivery_review["price"] == "180.00"
        assert direct_delivery_review["tax_amount"] == "27.00"
        direct_delivered_data = {**direct_delivery_data,
            "modified": direct_confirmed["modified"], "status": "Delivered",
            "acceptance": direct_delivery_review["acceptance"]}
        direct_delivered = api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-direct-deliver-" + suffix,
            direct_delivered_data)
        assert api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-direct-deliver-" + suffix,
            direct_delivered_data) == direct_delivered
        direct_receivable = frappe.get_doc("HS PMS Receivable",
            direct_delivered["pms_receivable"])
        assert (direct_receivable.experience_order, direct_receivable.folio,
                direct_receivable.booking, Decimal(str(direct_receivable.net_amount)),
                Decimal(str(direct_receivable.tax_amount))) == (
                direct_order["order"], None, None, Decimal("180.00"), Decimal("27.00"))
        assert direct_receivable.tax_profile == profile
        changed_product = frappe.get_doc("HS Product", experience_product)
        api.save_setup(second_prop.name, "product",
            {"name": experience_product, "tax_profile": profile},
            "experience-tax-restore-" + suffix,
            expected_modified=str(changed_product.modified))
        direct_invoice_series = api.execute(second_prop.name, "pms_fiscal_series",
            "experience-direct-series-" + suffix,
            dict(series_code="EX" + suffix + "-", document_type="Invoice",
                 start_number=1, end_number=5, padding=4))["series"]
        direct_invoice_data = dict(series=direct_invoice_series,
            receivables=[direct_receivable.name])
        direct_invoice_review = api.pms_invoice_quote(second_prop.name,
            direct_invoice_data)
        assert direct_invoice_review["lines"][0]["product"] == experience_product
        direct_invoice = api.execute(second_prop.name, "pms_issue_invoice",
            "experience-direct-invoice-" + suffix,
            {**direct_invoice_data, "acceptance": direct_invoice_review["acceptance"]})
        assert direct_invoice["total_amount"] == "207.00"
        direct_print = frappe.get_print("HS PMS Fiscal Document",
            direct_invoice["document"], print_format="HS Documento fiscal PMS")
        assert "Ruta cultural" in direct_print and direct_invoice["document_number"] in direct_print
        direct_payment = api.execute(second_prop.name, "pms_cash_movement",
            "experience-direct-payment-" + suffix,
            dict(kind="Payment", amount="0.10", method=bank_method,
                 receivable=direct_receivable.name,
                 reference="EX-PAY-" + suffix,
                 reason="Abono bancario de experiencia directa"))
        from hospitality_suite.standalone_receivables import outstanding as receivable_outstanding
        assert direct_payment["allocation"] and receivable_outstanding(
            second_prop, direct_receivable.name) == Decimal("203.35")
        assert any(row["name"] == direct_order["order"] and
                   row["pms_receivable"] == direct_receivable.name for row in
                   api.pms_travel_experiences_snapshot(second_prop.name)["orders"])
        try:
            api.execute(second_prop.name, "pms_cancel_receivable",
                "experience-direct-cancel-invoiced-" + suffix,
                dict(receivable=direct_receivable.name,
                     reason="Factura vigente"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se anuló una experiencia directa ya facturada")
        cancellable_review = api.preview(second_prop.name,
            dict(customer=new_guest["party"], experience=experience, quantity=1),
            "pms_direct_experience_order")
        cancellable = api.execute(second_prop.name, "pms_direct_experience_order",
            "experience-direct-cancellable-" + suffix,
            dict(customer=new_guest["party"], experience=experience, quantity=1,
                 acceptance=cancellable_review["acceptance"]))
        cancellable_confirmed = api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-direct-cancellable-confirm-" + suffix,
            dict(order=cancellable["order"], modified=cancellable["modified"],
                 status="Confirmed", scheduled_at=direct_scheduled, participants=1))
        cancellable_delivery = api.preview(second_prop.name,
            dict(order=cancellable["order"], receivable_account=ar),
            "pms_direct_experience_delivery")
        cancellable_delivered = api.execute(second_prop.name,
            "pms_direct_experience_status", "experience-direct-cancellable-deliver-" + suffix,
            dict(order=cancellable["order"], modified=cancellable_confirmed["modified"],
                 receivable_account=ar, status="Delivered",
                 acceptance=cancellable_delivery["acceptance"]))
        api.execute(second_prop.name, "pms_cancel_receivable",
            "experience-direct-cancel-" + suffix,
            dict(receivable=cancellable_delivered["pms_receivable"],
                 reason="Servicio duplicado"))
        assert frappe.db.get_value("HS Experience Order", cancellable["order"],
                                   "status") == "Cancelled"
        extra_quote = api.preview(second_prop.name, dict(booking=booked.name,
            experience=experience, quantity=1), "experience_order")
        assert extra_quote["line"]["total_amount"] == "109.25"
        extra_order = api.execute(second_prop.name, "experience_order",
            "travel-extra-" + suffix, dict(booking=booked.name,
                experience=experience, quantity=1,
                acceptance=extra_quote["acceptance"]))["order"]
        api.execute(second_prop.name, "experience_status", "travel-extra-cancel-" + suffix,
            dict(order=extra_order, modified=str(frappe.db.get_value(
                "HS Experience Order", extra_order, "modified")),
                status="Cancelled", reason="Experiencia duplicada"))
        arrival_quote = api.preview(second_prop.name,
            dict(booking=booked.name), action="check_in")
        arrived = api.execute(second_prop.name, "check_in", "travel-arrival-" + suffix,
            dict(booking=booked.name, modified=travel_booking["modified"],
                room=travel_room, guest=new_guest["guest"],
                timing_acceptance=arrival_quote["acceptance"]))
        schedule = (travel_start + timedelta(hours=4)).isoformat(timespec="minutes")
        confirmed_order = api.execute(second_prop.name, "experience_status",
            "travel-confirm-" + suffix, dict(order=travel_order.name,
                modified=str(travel_order.modified), status="Confirmed",
                scheduled_at=schedule, participants=2))
        delivery_data = dict(order=travel_order.name,
            modified=confirmed_order["modified"], status="Delivered",
            stay=arrived["stay"], folio=arrived["folio"])
        delivered_order = api.execute(second_prop.name, "experience_status",
            "travel-deliver-" + suffix, delivery_data)
        assert api.execute(second_prop.name, "experience_status",
            "travel-deliver-" + suffix, delivery_data) == delivered_order
        experience_charge = frappe.get_doc("HS Charge", delivered_order["charge"])
        assert (experience_charge.item, experience_charge.folio,
                Decimal(str(experience_charge.amount)), experience_charge.status) == (
                    experience_product, arrived["folio"], Decimal("180.00"), "Pending")
        bill_data = dict(folio=arrived["folio"], receivable_account=ar)
        bill_quote = api.pms_folio_quote(second_prop.name, bill_data)
        assert any(row["source_charge"] == experience_charge.name and
                   row["amount"] == "207.00" for row in bill_quote["lines"])
        billed_travel = api.execute(second_prop.name, "pms_bill_folio",
            "travel-bill-" + suffix,
            {**bill_data, "acceptance": bill_quote["acceptance"]})
        assert api.execute(second_prop.name, "pms_bill_folio",
            "travel-bill-" + suffix,
            {**bill_data, "acceptance": bill_quote["acceptance"]}) == billed_travel
        experience_charge.reload()
        assert experience_charge.pms_receivable and Decimal(str(frappe.db.get_value(
            "HS PMS Receivable", experience_charge.pms_receivable,
            "tax_amount"))) == Decimal("27.00")
        # La comisión se devenga sobre alojamiento facturado y se paga en
        # moneda base o en una moneda habilitada, sin duplicar la cuenta por pagar.
        second_prop.reload()
        api.save_setup(second_prop.name, "property", {
            "pms_commission_expense_account": operating_expense,
            "pms_commission_payable_account": payable},
            "agency-accounts-" + suffix, expected_modified=str(second_prop.modified))
        second_prop.reload()
        def complete_travel_fixture(locked):
            travel_stay = frappe.get_doc("HS Stay", arrived["stay"])
            travel_stay.status = "Checked Out"
            travel_stay.save()
            travel_reservation = frappe.get_doc("HS Booking", booked.name)
            travel_reservation.status = "Completed"
            travel_reservation.save()
            return travel_reservation.name
        command(second_prop.name, "approve", "travel-complete-" + suffix,
            {"operation": "smoke_travel_completion"}, complete_travel_fixture)
        expense_before = Decimal(standalone_accounting.balance(second_prop, operating_expense))
        payable_before = Decimal(standalone_accounting.balance(second_prop, payable))
        commission_review = api.preview(second_prop.name,
            {"booking": booked.name}, "agent_commission")
        assert commission_review["base"] == "100.00"
        assert commission_review["amount"] == "10.00"
        try:
            api.preview(prop.name, {"booking": booked.name}, "agent_commission")
        except (frappe.PermissionError, frappe.ValidationError):
            pass
        else:
            raise AssertionError("Se consultó una comisión de otro establecimiento")
        commission_data = {"booking": booked.name,
            "modified": commission_review["modified"],
            "acceptance": commission_review["acceptance"]}
        commission = api.execute(second_prop.name, "agent_commission",
            "agency-accrual-" + suffix, commission_data)
        assert api.execute(second_prop.name, "agent_commission",
            "agency-accrual-" + suffix, commission_data) == commission
        assert Decimal(standalone_accounting.balance(second_prop, operating_expense)) == expense_before + 10
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before - 10
        assert frappe.db.get_value("HS Booking", booked.name,
                                   "pms_agent_commission") == commission["commission"]
        try:
            api.preview(second_prop.name, {"booking": booked.name}, "agent_commission")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió duplicar una comisión vigente")
        try:
            api.execute(second_prop.name, "pms_reverse_journal",
                "agency-reverse-denied-" + suffix,
                dict(journal=commission["journal"], reason="Reversión externa"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se revirtió una comisión por fuera de su flujo")
        cancelled_commission = api.execute(second_prop.name,
            "pms_cancel_agent_commission", "agency-cancel-" + suffix,
            dict(commission=commission["commission"],
                modified=str(frappe.db.get_value("HS PMS Agency Commission",
                    commission["commission"], "modified")),
                reason="Revisión de liquidación"))
        assert cancelled_commission["status"] == "Cancelled"
        assert not frappe.db.get_value("HS Booking", booked.name, "pms_agent_commission")
        assert Decimal(standalone_accounting.balance(second_prop, operating_expense)) == expense_before
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        commission_review = api.preview(second_prop.name,
            {"booking": booked.name}, "agent_commission")
        commission = api.execute(second_prop.name, "agent_commission",
            "agency-accrual-again-" + suffix,
            {"booking": booked.name, "modified": commission_review["modified"],
             "acceptance": commission_review["acceptance"]})
        agency_shift = api.execute(second_prop.name, "pms_open_shift",
            "agency-shift-" + suffix,
            dict(opening_by_currency={"NIO": "43", "USD": "14"}))["shift"]
        first_payment = dict(commission=commission["commission"],
            method=bank_method, amount="0.10",
            reference="AGENCY-USD-" + suffix,
            reason="Abono de comisión en dólares")
        payment_review = api.pms_agent_commission_payment_quote(second_prop.name,
            first_payment)
        assert payment_review["base_amount"] == "3.65"
        paid = api.execute(second_prop.name, "pms_pay_agent_commission",
            "agency-pay-usd-" + suffix,
            {**first_payment, "acceptance": payment_review["acceptance"]})
        assert paid["outstanding"] == "6.35"
        assert api.execute(second_prop.name, "pms_pay_agent_commission",
            "agency-pay-usd-" + suffix,
            {**first_payment, "acceptance": payment_review["acceptance"]}) == paid
        try:
            api.pms_agent_commission_payment_quote(second_prop.name,
                {**first_payment, "amount": "0.20", "reference": "AGENCY-OVER-" + suffix})
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se permitió exceder el saldo de comisión")
        try:
            api.execute(second_prop.name, "pms_cancel_agent_commission",
                "agency-cancel-paid-" + suffix,
                dict(commission=commission["commission"],
                     modified=str(frappe.db.get_value("HS PMS Agency Commission",
                         commission["commission"], "modified")),
                     reason="Pago ya aplicado"))
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Se anuló una comisión pagada parcialmente")
        final_payment = dict(commission=commission["commission"],
            method=nio_method, shift=agency_shift, amount="6.35",
            reference="AGENCY-NIO-" + suffix,
            reason="Saldo final de comisión")
        final_review = api.pms_agent_commission_payment_quote(second_prop.name,
            final_payment)
        assert final_review["outstanding_after"] == "0.00"
        api.execute(second_prop.name, "pms_pay_agent_commission",
            "agency-pay-nio-" + suffix,
            {**final_payment, "acceptance": final_review["acceptance"]})
        from hospitality_suite.standalone_agency_commissions import outstanding
        assert outstanding(second_prop, commission["commission"]) == 0
        assert Decimal(standalone_accounting.balance(second_prop, payable)) == payable_before
        agency_close = api.pms_close_preview(second_prop.name)["snapshot"]
        assert any(row["agent"] == travel_agent for row in
            agency_close["breakdown"]["agency_commissions"])
        assert any(row["pms_agent_commission"] == commission["commission"]
                   for row in agency_close["breakdown"]["agency_commission_payments"])
        assert any(row["pms_agent_commission"] == commission["commission"]
                   for row in agency_close["sources"]["payments"])
        from hospitality_suite.pms_cutover import preflight
        cutover_review = preflight()
        assert cutover_review["provider"] == "PMS" and not cutover_review["cutover_performed"]
        assert not cutover_review["ready_for_mapping"]
        assert cutover_review["source_sha256"] == api.pms_cutover_preflight()["source_sha256"]
        cutover_property = next(row for row in cutover_review["properties"]
            if row["property"] == second_prop.name)
        assert any(row["source"] == direct_receivable.name for row in
                   cutover_property["open_receivables"])
        assert not any(row["source"] == commission["commission"] for row in
                       cutover_property["open_payables"] if row["kind"] == "Agency Commission")
        assert not any(row["code"] == "negative_supplier_payable" and
                       row["source"] == multi_doc.name for row in
                       cutover_property["blockers"])
        assert any(row["code"] == "unclosed_cash_shifts" for row in
                   cutover_property["blockers"])
        map_template = api.pms_cutover_mapping_template()
        assert map_template["source_sha256"] == cutover_review["source_sha256"]
        assert direct_receivable.party in map_template["properties"][second_prop.name]["parties"]
        from hospitality_suite.pms_cutover_plan import build as build_cutover_plan
        draft_plan = build_cutover_plan(cutover_review, map_template)
        assert any(row["source"] == direct_receivable.name for prop_plan in
                   draft_plan["properties"] for row in prop_plan["opening_receivables"])
        from hospitality_suite.pms_cutover_links import build as build_link_manifest
        link_manifest = build_link_manifest(cutover_review, map_template)
        assert link_manifest["link_sha256"] and not link_manifest["cutover_performed"]
        assert any(row["code"] == "unmapped_existing_link" and
                   row["target_type"] == "Customer" for row in link_manifest["blockers"])
        assert any(row["doctype"] == "HS Account" and row["field"] == "company"
                   for row in link_manifest["blockers"])
        map_review = api.pms_cutover_mapping_review(dict(
            source_sha256=cutover_review["source_sha256"], properties={}))
        assert not map_review["mapping_complete"] and not map_review["cutover_performed"]
        blocked_plan = api.pms_cutover_transfer_plan(dict(
            source_sha256=cutover_review["source_sha256"], properties={}))
        assert blocked_plan["plan"] is None and not blocked_plan["cutover_performed"]
        assert {"erpnext_not_installed", "missing_property_mapping"}.issubset(
            {row["code"] for row in map_review["mapping_blockers"]})
        assert "stale_source_hash" in {row["code"] for row in
            api.pms_cutover_mapping_review(dict(source_sha256="stale", properties={}))[
                "mapping_blockers"]}
        frappe.set_user("Guest")
        try:
            try:
                api.pms_cutover_preflight()
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("El informe global de corte quedó visible para Guest")
            try:
                api.pms_cutover_mapping_review(dict(source_sha256="x", properties={}))
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("El mapeo global quedó visible para Guest")
            try:
                api.pms_cutover_mapping_template()
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("La plantilla global quedó visible para Guest")
            try:
                api.pms_cutover_transfer_plan(dict(source_sha256="x", properties={}))
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("El plan global quedó visible para Guest")
        finally:
            frappe.set_user("Administrator")
        return {"provider": "pms", "journal": opening["journal"],
                "stock": consumed["balance_value"],
                "link_blockers": dict(Counter(row["code"] for row in link_manifest["blockers"]))}
    finally:
        frappe.db.rollback()
