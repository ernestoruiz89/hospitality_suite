"""Transactional MariaDB smoke path for a fresh Frappe-only test site.

Invoke with ``bench --site <disposable-site> execute
hospitality_suite.tests.smoke_standalone.run``. It rolls back its fixtures.
"""

import uuid
import base64
from io import BytesIO
from decimal import Decimal

import frappe

from hospitality_suite import api, setup, standalone_accounting, standalone_coa, standalone_currency, standalone_inventory
from hospitality_suite.coa_format import HEADERS, parse_csv
from hospitality_suite.service import command, insert


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

        def new_account(code, root, **extra):
            return api.execute(prop.name, "pms_account", "account-" + code + suffix,
                dict(account_code=code + suffix, account_name=code, root_type=root, **extra))["account"]

        cash = new_account("1000", "Asset", is_cash=1)
        inventory = new_account("1100", "Asset")
        equity = new_account("3000", "Equity")
        expense = new_account("5000", "Expense")
        opening = api.execute(prop.name, "pms_opening_balance", "opening-" + suffix,
            dict(reference="SMOKE-" + suffix, lines=[
                dict(account=cash, debit="100.00", credit=0),
                dict(account=equity, debit=0, credit="100.00")]))
        assert standalone_accounting.balance(prop, cash) == "100.00"
        manual_data = dict(reference="AJ-" + suffix, reason="Ajuste de prueba con soporte",
                           lines=[dict(account=expense, debit="7.25", credit="0"),
                                  dict(account=equity, debit="0", credit="7.25")])
        manual = api.execute(prop.name, "pms_manual_journal", "manual-" + suffix, manual_data)
        repeated = api.execute(prop.name, "pms_manual_journal", "manual-" + suffix, manual_data)
        assert repeated == manual and manual["total"] == "7.25"
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
        command(prop.name, "report", "close-" + suffix,
            {"operation": "smoke_close"},
            lambda locked: insert("HS Daily Close", locked, business_date=locked.business_date,
                                  status="Closed", summary="{}", blockers="{}"))
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
        ar = account_number("1200")
        deposit = account_number("2000")
        income = account_number("4000")
        operating_expense = account_number("5000")
        api.execute(second_prop.name, "pms_opening_balance", "opening-fx-" + suffix,
            dict(reference="FX-OPEN-" + suffix, lines=[
                dict(account=usd_cash, debit="365.00", credit="0", account_currency="USD",
                     exchange_rate="36.5", debit_in_account_currency="10.00", credit_in_account_currency="0"),
                dict(account=owner, debit="0", credit="365.00")]))
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
                            dict(opening_by_currency={"NIO": "0", "USD": "10"}))["shift"]
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
        receipt_lines = frappe.get_doc("HS Journal", receipt["journal"]).lines
        assert sum(Decimal(str(line.debit)) for line in receipt_lines) == Decimal("182.50")
        assert sum(Decimal(str(line.credit)) for line in receipt_lines) == Decimal("182.50")
        assert any(line.account == usd_cash and Decimal(str(line.debit_in_account_currency)) == 5
                   for line in receipt_lines)
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
        applied = api.execute(second_prop.name, "pms_apply_advance", "apply-" + suffix,
            dict(receivable=receivable, advance=receipt["payment"], amount="100",
                 reason="Aplicación parcial del anticipo"))
        assert applied["outstanding"] == "681.00" and applied["advance_available"] == "82.50"
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
        assert api.execute(second_prop.name, "pms_close_shift", "close-fx-" + suffix,
                           dict(shift=shift, counted_by_currency={"NIO": "0", "USD": "18"}))["status"] == "Closed"
        return {"provider": "pms", "journal": opening["journal"], "stock": consumed["balance_value"]}
    finally:
        frappe.db.rollback()
