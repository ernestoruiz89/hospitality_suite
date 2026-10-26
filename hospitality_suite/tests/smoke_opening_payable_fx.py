"""Rollback-only proof of foreign opening payable and partial FX settlement."""

from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

import frappe

from hospitality_suite import (api, erp_to_pms_transfer_plan,
                               erp_to_pms_transfer_rehearsal, setup)
from hospitality_suite.standalone_closing import build as close_snapshot
from hospitality_suite.service import insert, operation
from hospitality_suite.standalone_accounting import account_currency_balance, post
from hospitality_suite.standalone_opening_payables import outstanding


def run():
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente el sitio PMS de ensayo")
    if not frappe.db.get_value("Currency", "USD", "enabled"):
        frappe.throw("Habilite USD en el sitio de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex
    savepoint = "hs_fx_opening_probe"
    frappe.db.savepoint(savepoint)
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "FX opening " + suffix, "base_currency": "NIO",
            "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": "FX opening " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "fx-opening-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.set("accepted_currencies", [{"currency": "USD"}])
        prop.save()
        with operation(prop):
            temporary = insert("HS Account", prop, organization=org.name,
                account_code="1990-" + suffix[:8], account_name="Puente FX",
                root_type="Asset", account_type="Temporary",
                account_currency="NIO", active=1, is_group=0)
            payable = insert("HS Account", prop, organization=org.name,
                account_code="2110-" + suffix[:8], account_name="Proveedor USD",
                root_type="Liability", account_type="Payable",
                account_currency="USD", active=1, is_group=0)
            bank = insert("HS Account", prop, organization=org.name,
                account_code="1110-" + suffix[:8], account_name="Banco NIO",
                root_type="Asset", account_type="Bank", account_currency="NIO",
                active=1, is_group=0, is_bank=1)
            dollar_bank = insert("HS Account", prop, organization=org.name,
                account_code="1120-" + suffix[:8], account_name="Banco USD",
                root_type="Asset", account_type="Bank", account_currency="USD",
                active=1, is_group=0, is_bank=1)
            equity = insert("HS Account", prop, organization=org.name,
                account_code="3110-" + suffix[:8], account_name="Patrimonio FX",
                root_type="Equity", account_type="Equity",
                account_currency="NIO", active=1, is_group=0)
            variance = insert("HS Account", prop, organization=org.name,
                account_code="5190-" + suffix[:8], account_name="Diferencia de cambio",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            supplier = insert("HS Party", prop, organization=org.name,
                party_name="Proveedor FX", party_type="Supplier", active=1)
            post(prop, source_doctype="HS Opening Balance", source_name=suffix,
                purpose="Opening Balance", lines=[
                    {"account": bank.name, "debit": "5000.00", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "5000.00"}])
            post(prop, source_doctype="HS Opening Balance", source_name="USD-" + suffix,
                purpose="Opening Balance", lines=[
                    {"account": dollar_bank.name, "debit": "3600.00", "credit": "0",
                     "account_currency": "USD", "exchange_rate": "36",
                     "debit_in_account_currency": "100.00",
                     "credit_in_account_currency": "0"},
                    {"account": equity.name, "debit": "0", "credit": "3600.00"}])
            plan = {"temporary_opening_account": temporary.name,
                "opening_receivables": [], "opening_customer_credits": [],
                "opening_advances": [], "opening_guarantees": [],
                "opening_payables": [{"source": "PINV-FX-" + suffix,
                    "account": payable.name, "party": supplier.name,
                    "currency": "USD", "signed_base_balance": "-3600.00",
                    "signed_account_balance": "-100.00",
                    "due_date": str(prop.business_date)}],
                "opening_supplier_credits": [], "opening_stock": [],
                "residual_journal": []}
            refs = erp_to_pms_transfer_rehearsal._post_property(prop,
                "erp.example.invalid", "a" * 64, plan)
            opening = frappe.get_doc("HS PMS Opening Payable", refs["payables"][0])
            erp_to_pms_transfer_rehearsal._verify_property(prop,
                {"net_balances": [
                    {"account": bank.name, "party": None,
                     "account_currency": "NIO", "debit": "5000.00",
                     "credit": "0", "debit_in_account_currency": "5000.00",
                     "credit_in_account_currency": "0"},
                    {"account": equity.name, "party": None,
                     "account_currency": "NIO", "debit": "0",
                     "credit": "8600.00", "debit_in_account_currency": "0",
                     "credit_in_account_currency": "8600.00"},
                    {"account": dollar_bank.name, "party": None,
                     "account_currency": "USD", "debit": "3600.00",
                     "credit": "0", "debit_in_account_currency": "100.00",
                     "credit_in_account_currency": "0"},
                    {"account": temporary.name, "party": None,
                     "account_currency": "NIO", "debit": "3600.00",
                     "credit": "0", "debit_in_account_currency": "3600.00",
                     "credit_in_account_currency": "0"},
                    {"account": payable.name, "party": supplier.name,
                     "account_currency": "USD", "debit": "0",
                     "credit": "3600.00", "debit_in_account_currency": "0",
                     "credit_in_account_currency": "100.00"}]}, [])
        planned = {"blockers": [], "opening_payables": []}
        controls = defaultdict(Decimal)
        erp_to_pms_transfer_plan._control(
            {"property": "ERP-SOURCE", "currency": "NIO"},
            {"accounts": {"AP-USD": payable.name},
             "suppliers": {"SUPPLIER-SOURCE": supplier.name}},
            planned, controls, "opening_payables", "PINV-FX-SOURCE",
            "AP-USD", "SUPPLIER-SOURCE", "suppliers", "-3600.00",
            "USD", 2, signed_original="-100.00")
        if (planned["blockers"] or
                planned["opening_payables"][0]["signed_account_balance"] !=
                    "-100.00" or
                controls[(payable.name, supplier.name)] != Decimal("-3600.00")):
            frappe.throw("El plan no acepta un pasivo extranjero conciliado")
        if outstanding(prop, opening.name) != Decimal("100.00"):
            frappe.throw("La apertura extranjera perdió el saldo original")
        method = api.execute(prop.name, "pms_payment_method", "fx-method-" + suffix,
            {"label": "Banco NIO FX", "account": bank.name})["method"]
        dollar_method = api.execute(prop.name, "pms_payment_method",
            "fx-usd-method-" + suffix,
            {"label": "Banco USD FX", "account": dollar_bank.name})["method"]
        api.execute(prop.name, "pms_exchange_rate", "fx-rate-" + suffix,
            {"from_currency": "USD", "rate": "35", "source": "Ensayo FX"})
        first_data = {"payable": opening.name, "method": method,
            "amount": "1480.00", "settled_amount": "40.00",
            "reference": "FX-FIRST-" + suffix, "reason": "Primer abono FX"}
        try:
            api.pms_opening_supplier_payment_quote(prop.name, first_data)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se pagó diferencia de cambio sin cuenta configurada")
        prop.reload()
        prop.pms_exchange_variance_account = payable.name
        try:
            prop.save()
        except frappe.ValidationError as exc:
            if "diferencia cambiaria" not in str(exc):
                raise
            frappe.clear_messages()
        else:
            frappe.throw("Se aceptó un pasivo extranjero como cuenta de cambio")
        prop.reload()
        setup_view = api.setup_board(prop.name)
        if variance.name not in {row["name"] for row in
                setup_view["pms_variance_accounts"]}:
            frappe.throw("Configuración no ofrece la cuenta de cambio")
        api.save_setup(prop.name, "property",
            {"pms_exchange_variance_account": variance.name},
            "fx-variance-setup-" + suffix,
            setup_view["property"]["modified"])
        prop.reload()
        first_quote = api.pms_opening_supplier_payment_quote(prop.name, first_data)
        if (first_quote["payable_release_base"] != "1440.00" or
                first_quote["exchange_variance_base"] != "40.00" or
                first_quote["outstanding_after"] != "60.00" or
                first_quote["base_outstanding_after"] != "2160.00"):
            frappe.throw("El primer abono extranjero no conserva ambos saldos")
        first = api.execute(prop.name, "pms_pay_opening_supplier",
            "fx-first-" + suffix,
            {**first_data, "acceptance": first_quote["acceptance"]})
        tampered = frappe.get_doc("HS Payment", first["payment"])
        tampered.pms_settled_amount = "41.00"
        try:
            tampered.save()
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se alteró la liquidación después de contabilizar")
        if api.execute(prop.name, "pms_pay_opening_supplier", "fx-first-" + suffix,
                {**first_data, "acceptance": first_quote["acceptance"]}) != first:
            frappe.throw("El reintento duplicó el abono extranjero")
        first_lines = frappe.get_all("HS Journal Line",
            filters={"parent": first["journal"]},
            fields=["account", "debit", "credit", "debit_in_account_currency"])
        if {(row.account, Decimal(str(row.debit)), Decimal(str(row.credit)),
                Decimal(str(row.debit_in_account_currency))) for row in first_lines} != {
                    (payable.name, Decimal("1440"), Decimal(0), Decimal("40")),
                    (bank.name, Decimal(0), Decimal("1480"), Decimal(0)),
                    (variance.name, Decimal("40"), Decimal(0), Decimal("40"))}:
            frappe.throw("La pérdida cambiaria no concilió")
        second_data = {"payable": opening.name, "method": dollar_method,
            "amount": "60.00",
            "reference": "FX-FINAL-" + suffix, "reason": "Pago final FX"}
        second_quote = api.pms_opening_supplier_payment_quote(prop.name, second_data)
        if (second_quote["payable_release_base"] != "2160.00" or
                second_quote["exchange_variance_base"] != "-60.00" or
                second_quote["outstanding_after"] != "0.00" or
                second_quote["base_outstanding_after"] != "0.00"):
            frappe.throw("El pago final no libera ambos saldos")
        second = api.execute(prop.name, "pms_pay_opening_supplier",
            "fx-final-" + suffix,
            {**second_data, "acceptance": second_quote["acceptance"]})
        second_lines = frappe.get_all("HS Journal Line",
            filters={"parent": second["journal"]}, fields=["account", "debit", "credit"])
        if {(row.account, Decimal(str(row.debit)), Decimal(str(row.credit)))
                for row in second_lines} != {
                    (payable.name, Decimal("2160"), Decimal(0)),
                    (dollar_bank.name, Decimal(0), Decimal("2100")),
                    (variance.name, Decimal(0), Decimal("60"))}:
            frappe.throw("La ganancia cambiaria no concilió")
        balance = account_currency_balance(prop, payable.name)
        if (outstanding(prop, opening.name) != 0 or
                Decimal(balance["balance"]) != 0 or
                Decimal(balance["base_balance"]) != 0):
            frappe.throw("La deuda extranjera no quedó saldada")
        try:
            api.pms_opening_supplier_payment_quote(prop.name, second_data)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se permitió sobrepagar la deuda extranjera")
        snapshot = close_snapshot(prop)
        breakdown = snapshot["breakdown"]
        foreign_opening = next(row for row in breakdown["opening_payables"]
            if row["currency"] == "USD")
        settled = next(row for row in breakdown["opening_supplier_settlements"]
            if row["currency"] == "USD")
        differences = {row["kind"]: row["base_amount"]
            for row in breakdown["opening_exchange_differences"]}
        if (snapshot["version"] != 8 or
                (foreign_opening["amount"], foreign_opening["base_amount"]) !=
                    ("100.00", "3600.00") or
                (settled["amount"], settled["base_amount"]) !=
                    ("100.00", "3600.00") or
                differences != {"Loss": "40.00", "Gain": "60.00"} or
                breakdown["production"]):
            frappe.throw("El cierre mezcló deuda extranjera, cambio o producción")
        return {"opened_usd": "100.00", "opening_base": "3600.00",
                "partial_payments": 2, "fx_loss": "40.00", "fx_gain": "60.00",
                "second_tender_usd": "60.00",
                "nominal_and_base_zero": True, "idempotent": True,
                "plan_accepts_foreign_payable": True,
                "opening_writer_reconciled": True,
                "posted_payment_immutable": True,
                "invalid_variance_account_rejected": True,
                "overpayment_rejected": True,
                "close_separates_fx": True, "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
        frappe.set_user("Administrator")
