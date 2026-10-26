"""Rollback-only foreign supplier credit: transfer, partial FX offsets and refund."""

from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

import frappe

from hospitality_suite import api, erp_to_pms_transfer_plan, erp_to_pms_transfer_rehearsal, setup
from hospitality_suite.service import insert, operation
from hospitality_suite.standalone_accounting import account_currency_balance
from hospitality_suite.standalone_closing import build as close_snapshot
from hospitality_suite.standalone_opening_payables import outstanding
from hospitality_suite.standalone_opening_supplier_credits import balances


def run():
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente el sitio PMS de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex
    marker = "hs_supplier_credit_fx"
    frappe.db.savepoint(marker)
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "FX supplier credit " + suffix,
            "base_currency": "NIO", "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": "FX supplier credit " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "fx-supplier-credit-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.set("accepted_currencies", [{"currency": "USD"}])
        prop.save()
        with operation(prop):
            temporary = insert("HS Account", prop, organization=org.name,
                account_code="1990-" + suffix[:8], account_name="Puente FX",
                root_type="Asset", account_type="Temporary",
                account_currency="NIO", active=1, is_group=0)
            credit_ap = insert("HS Account", prop, organization=org.name,
                account_code="2110-" + suffix[:8], account_name="Crédito USD",
                root_type="Liability", account_type="Payable",
                account_currency="USD", active=1, is_group=0)
            debt_ap = insert("HS Account", prop, organization=org.name,
                account_code="2120-" + suffix[:8], account_name="Deuda USD",
                root_type="Liability", account_type="Payable",
                account_currency="USD", active=1, is_group=0)
            bank = insert("HS Account", prop, organization=org.name,
                account_code="1110-" + suffix[:8], account_name="Banco NIO",
                root_type="Asset", account_type="Bank", account_currency="NIO",
                active=1, is_group=0, is_bank=1)
            variance = insert("HS Account", prop, organization=org.name,
                account_code="5190-" + suffix[:8], account_name="Cambio",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            supplier = insert("HS Party", prop, organization=org.name,
                party_name="Proveedor FX", party_type="Supplier", active=1)
            plan = {"temporary_opening_account": temporary.name,
                "opening_receivables": [], "opening_customer_credits": [],
                "opening_advances": [], "opening_guarantees": [],
                "opening_payables": [{"source": "PINV-" + suffix,
                    "account": debt_ap.name, "party": supplier.name, "currency": "USD",
                    "signed_base_balance": "-3500.00",
                    "signed_account_balance": "-100.00",
                    "due_date": str(prop.business_date)}],
                "opening_supplier_credits": [{"source": "PCN-" + suffix,
                    "account": credit_ap.name, "party": supplier.name,
                    "currency": "USD", "signed_base_balance": "1800.00",
                    "signed_account_balance": "50.00"}],
                "opening_stock": [], "residual_journal": []}
            refs = erp_to_pms_transfer_rehearsal._post_property(
                prop, "erp.example.invalid", "a" * 64, plan)
            credit = frappe.get_doc("HS PMS Opening Supplier Credit",
                refs["supplier_credits"][0])
            payable = frappe.get_doc("HS PMS Opening Payable", refs["payables"][0])
        if (credit.currency != "USD" or Decimal(str(credit.base_amount)) != 1800 or
                balances(prop, credit.name) != (Decimal(50), Decimal(1800)) or
                outstanding(prop, payable.name) != Decimal(100)):
            frappe.throw("La apertura no conservó principal y valor base")
        records = {"blockers": [], "opening_supplier_credits": []}
        controls = defaultdict(Decimal)
        erp_to_pms_transfer_plan._control(
            {"property": "SOURCE", "currency": "NIO"},
            {"accounts": {"AP-USD": credit_ap.name},
             "suppliers": {"VENDOR": supplier.name}},
            records, controls, "opening_supplier_credits", "PCN-SOURCE",
            "AP-USD", "VENDOR", "suppliers", "1800.00", "USD", 2,
            signed_original="50.00")
        if (records["blockers"] or
                records["opening_supplier_credits"][0]["signed_account_balance"] !=
                    "50.00" or
                controls[(credit_ap.name, supplier.name)] != Decimal(1800)):
            frappe.throw("El plan no acepta la nota extranjera conciliada")
        prop.reload()
        setup_view = api.setup_board(prop.name)
        api.save_setup(prop.name, "property",
            {"pms_exchange_variance_account": variance.name},
            "fx-supplier-variance-" + suffix,
            setup_view["property"]["modified"])
        prop.reload()
        method = api.execute(prop.name, "pms_payment_method", "fx-bank-" + suffix,
            {"label": "Banco NIO FX", "account": bank.name})["method"]
        application_data = {"credit": credit.name,
            "target_type": "Opening Payable", "target": payable.name,
            "amount": "20.00", "reason": "Compensación parcial"}
        quote = api.pms_opening_supplier_credit_apply_quote(prop.name,
            application_data)
        if (quote["source_base_amount"] != "720.00" or
                quote["target_base_amount"] != "700.00" or
                quote["exchange_variance_base"] != "20.00"):
            frappe.throw("La compensación no calculó la diferencia cambiaria")
        try:
            api.pms_opening_supplier_credit_apply_quote(prop.name,
                {**application_data, "amount": "50.01"})
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se aceptó aplicación mayor al crédito disponible")

        def journal_lines(name):
            rows = frappe.get_all("HS Journal Line", filters={"parent": name},
                fields=["account", "debit", "credit",
                        "debit_in_account_currency",
                        "credit_in_account_currency"])
            return {(row.account, Decimal(str(row.debit)),
                Decimal(str(row.credit)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency))) for row in rows}

        applied = api.execute(prop.name, "pms_apply_opening_supplier_credit",
            "fx-supplier-apply-" + suffix,
            {**application_data, "acceptance": quote["acceptance"]})
        if (api.execute(prop.name, "pms_apply_opening_supplier_credit",
                "fx-supplier-apply-" + suffix,
                {**application_data, "acceptance": quote["acceptance"]}) != applied or
                balances(prop, credit.name) != (Decimal(30), Decimal(1080)) or
                outstanding(prop, payable.name) != Decimal(80)):
            frappe.throw("La aplicación extranjera no fue idempotente")
        if journal_lines(applied["journal"]) != {
                (debt_ap.name, Decimal(700), Decimal(0), Decimal(20), Decimal(0)),
                (credit_ap.name, Decimal(0), Decimal(720), Decimal(0), Decimal(20)),
                (variance.name, Decimal(20), Decimal(0), Decimal(20), Decimal(0))}:
            frappe.throw("El asiento de aplicación no concilió ambas monedas")
        variance.active = 0
        try:
            variance.save()
        except frappe.ValidationError:
            frappe.clear_messages()
            variance.reload()
        else:
            frappe.throw("Se desactivó la cuenta de cambio de una aplicación reversible")
        reversal = api.execute(prop.name, "pms_unapply_opening_supplier_credit",
            "fx-supplier-unapply-" + suffix,
            {"allocation": applied["allocation"], "amount": "10.00",
             "reason": "Corrección parcial"})
        if (not reversal["journal"] or
                balances(prop, credit.name) != (Decimal(40), Decimal(1440)) or
                outstanding(prop, payable.name) != Decimal(90)):
            frappe.throw("La reversión no restituyó ambos saldos")
        if journal_lines(reversal["journal"]) != {
                (credit_ap.name, Decimal(360), Decimal(0), Decimal(10), Decimal(0)),
                (debt_ap.name, Decimal(0), Decimal(350), Decimal(0), Decimal(10)),
                (variance.name, Decimal(0), Decimal(10), Decimal(0), Decimal(10))}:
            frappe.throw("El asiento de reversión no congeló el cambio original")
        refund_data = {"credit": credit.name, "method": method,
            "amount": "1480.00", "settled_amount": "40.00",
            "reference": "PCN-REF-" + suffix, "reason": "Reintegro final FX"}
        refund_quote = api.pms_opening_supplier_credit_refund_quote(
            prop.name, refund_data)
        if (refund_quote["released_base_amount"] != "1440.00" or
                refund_quote["exchange_variance_base"] != "40.00"):
            frappe.throw("El reintegro no libera el valor base histórico")
        refunded = api.execute(prop.name, "pms_refund_opening_supplier_credit",
            "fx-supplier-refund-" + suffix,
            {**refund_data, "acceptance": refund_quote["acceptance"]})
        if (api.execute(prop.name, "pms_refund_opening_supplier_credit",
                "fx-supplier-refund-" + suffix,
                {**refund_data, "acceptance": refund_quote["acceptance"]}) != refunded or
                balances(prop, credit.name) != (Decimal(0), Decimal(0))):
            frappe.throw("El reintegro extranjero duplicó el crédito")
        if journal_lines(refunded["journal"]) != {
                (bank.name, Decimal(1480), Decimal(0), Decimal(1480), Decimal(0)),
                (credit_ap.name, Decimal(0), Decimal(1440), Decimal(0), Decimal(40)),
                (variance.name, Decimal(0), Decimal(40), Decimal(0), Decimal(40))}:
            frappe.throw("El reintegro no contabilizó el cambio y el principal")
        payment = frappe.get_doc("HS Payment", refunded["payment"])
        payment.pms_settled_amount = "41.00"
        try:
            payment.save()
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se alteró un reintegro contabilizado")
        snapshot = close_snapshot(prop)
        if (not snapshot["breakdown"]["foreign_supplier_credit_applications"] or
                not snapshot["breakdown"]["foreign_supplier_credit_refunds"] or
                not snapshot["breakdown"]["supplier_credit_exchange_variance"] or
                not snapshot["breakdown"][
                    "supplier_credit_refund_exchange_variance"]):
            frappe.throw("El cierre no desglosó el crédito extranjero")
        position = account_currency_balance(prop, credit_ap.name)
        if position["balance"] != "0.00":
            frappe.throw("El pasivo del crédito no quedó liquidado")
        return {"opening_usd": "50.00", "opening_base_nio": "1800.00",
            "applied_usd": "20.00", "reversed_usd": "10.00",
            "refunded_usd": "40.00", "closing_detailed": True,
            "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=marker)
